"""短期记忆（M3-02，PRD FR6.1）：窗口 + 滚动摘要 + token 预算。

为什么不把全部历史都塞给模型：20 轮问答大约 6~8k token，成本翻倍、首字延迟 +1~2s，
而且模型对「中间那段」的注意力本来就弱。这里做三件事：

1. **窗口**：只保留最近 10 轮原文（``MAX_TURNS``）。
2. **滚动摘要**：超窗口的部分压成一段摘要存进 ``conversations.summary``，
   用 ``summary_upto`` 记住「已经浓缩到第几条」，避免每轮重复摘要同一批消息。
3. **预算**：整段历史硬上限 1500 token（PRD §13 的预算：system 800 + 记忆 300 +
   检索 2500 + 历史 1500）。超了就从最老的开始丢——宁可少一点上下文，也不能让
   一次请求的 prompt 无限膨胀。

「1 token ≈ 1.6 个汉字」是保守估计（实际各家分词器在 1.3~2.0 之间），宁可低估容量。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy import func, select

from app.core.config import settings
from app.models.agent import Conversation, Message, MessageRole

logger = logging.getLogger(__name__)

MAX_TURNS = 10
HISTORY_BUDGET = 1500
MAX_SUMMARY_CHARS = 600
CHARS_PER_TOKEN = 1.6

SUMMARY_PROMPT = """你是客服系统的对话摘要助手。请把下面的历史对话压缩成一段摘要，供后续继续对话使用。

要求：
- 只保留对后续回答有用的信息：用户身份/病情相关事实、已确认的需求、已经给过的结论、未解决的问题；
- 不要写「用户问」「助手答」这类过程描述，直接给结论；
- 不要编造原文没有的信息；
- 300 字以内，用中文。

{previous}历史对话：
{dialogue}

摘要："""


def estimate_tokens(text: str) -> int:
    """粗略 token 估计（中文按 1.6 字符/token，至少 1）。"""
    return max(1, int(len(text or "") / CHARS_PER_TOKEN) + 1)


@dataclass(slots=True)
class HistoryContext:
    """一次请求要带进 prompt 的历史。"""

    messages: list[dict[str, str]] = field(default_factory=list)
    summary: str = ""
    tokens: int = 0
    total_messages: int = 0
    truncated: bool = False

    def as_event(self) -> dict[str, Any]:
        return {
            "messages": len(self.messages),
            "tokens": self.tokens,
            "summary_chars": len(self.summary),
            "truncated": self.truncated,
        }


@dataclass(slots=True)
class SummaryOutcome:
    summary: str
    upto: int
    generated_with_llm: bool = False


async def _recent_messages(
    db: Any, conversation_id: Any, *, limit: int
) -> list[Message]:
    rows = (
        await db.execute(
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                # 人工客服说过的话也进上下文：坐席结束会话后 AI 要接着聊，
                # 不知道坐席刚才承诺了什么就会自相矛盾
                Message.role.in_(
                    [
                        MessageRole.USER.value,
                        MessageRole.ASSISTANT.value,
                        MessageRole.HUMAN_AGENT.value,
                    ]
                ),
            )
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return list(reversed(rows))


async def load_history(
    db: Any,
    conversation_id: Any,
    *,
    max_turns: int = MAX_TURNS,
    budget: int = HISTORY_BUDGET,
) -> HistoryContext:
    """取「最近 max_turns 轮 + 已有摘要」，按 token 预算裁剪。"""
    conversation = await db.get(Conversation, conversation_id)
    summary = (conversation.summary or "").strip() if conversation is not None else ""
    rows = await _recent_messages(db, conversation_id, limit=max_turns * 2)

    picked: list[dict[str, str]] = []
    tokens = estimate_tokens(summary) if summary else 0
    truncated = False
    for row in reversed(rows):  # 从最新往回装，超预算就丢最老的
        content = (row.content or "").strip()
        if not content:
            continue
        cost = estimate_tokens(content)
        if tokens + cost > budget:
            if picked:
                truncated = True
                break
            # 单条就超预算：截断这一条也要留（否则模型完全不知道用户刚说了什么）
            content = content[: int(budget * CHARS_PER_TOKEN)]
            cost = estimate_tokens(content)
            truncated = True
        picked.append({"role": row.role, "content": content})
        tokens += cost
        if tokens >= budget:
            truncated = truncated or len(rows) > len(picked)
            break

    picked.reverse()
    return HistoryContext(
        messages=picked,
        summary=summary,
        tokens=tokens,
        total_messages=len(rows),
        truncated=truncated,
    )


def _deterministic_summary(previous: str, rows: list[Message]) -> str:
    """没有模型时的兜底摘要：保留每句话的开头，按时间顺序拼。

    不追求可读性，只保证「不丢关键实体」（药名、过敏史、订单号通常出现在句子前半段）。
    """
    parts: list[str] = []
    if previous:
        parts.append(previous.strip())
    for row in rows:
        text = " ".join((row.content or "").split())
        if not text:
            continue
        head = text[:60]
        parts.append(("用户：" if row.role == MessageRole.USER.value else "客服：") + head)
    return "\n".join(parts)[-MAX_SUMMARY_CHARS:]


async def maybe_summarize(
    db: Any,
    conversation_id: Any,
    *,
    llm: Any = None,
    max_turns: int = MAX_TURNS,
) -> Optional[SummaryOutcome]:
    """消息数超出窗口时，把超出的部分压进 ``conversations.summary``。

    返回 ``None`` 表示还不需要摘要。**失败不抛异常**：摘要只是省钱/提速手段，
    失败了下一轮就当没有摘要，不能影响用户对话。
    """
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        return None

    total = int(
        (
            await db.execute(
                select(func.count())
                .select_from(Message)
                .where(
                    Message.conversation_id == conversation_id,
                    Message.role.in_([MessageRole.USER.value, MessageRole.ASSISTANT.value]),
                )
            )
        ).scalar_one()
    )
    cut = total - max_turns * 2
    upto = int(conversation.summary_upto or 0)
    if cut <= upto:
        return None

    rows = (
        await db.execute(
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.role.in_([MessageRole.USER.value, MessageRole.ASSISTANT.value]),
            )
            .order_by(Message.created_at.asc())
            .offset(upto)
            .limit(cut - upto)
        )
    ).scalars().all()
    if not rows:
        return None

    previous = (conversation.summary or "").strip()
    used_llm = False
    summary = ""
    if llm is None and settings.llm_configured:
        try:
            from app.llm.client import get_chat_client

            llm = get_chat_client(temperature=0)
        except Exception:  # noqa: BLE001 —— 没配模型就走确定性摘要
            llm = None
    if llm is not None:
        dialogue = "\n".join(
            ("用户：" if row.role == MessageRole.USER.value else "客服：")
            + " ".join((row.content or "").split())[:300]
            for row in rows
        )
        prompt = SUMMARY_PROMPT.replace(
            "{previous}", f"此前的摘要（需要合并进来）：\n{previous}\n\n" if previous else ""
        ).replace("{dialogue}", dialogue)
        try:
            response = await llm.ainvoke(
                [
                    {"role": "system", "content": "你是严谨的对话摘要助手。"},
                    {"role": "user", "content": prompt},
                ]
            )
            summary = str(getattr(response, "content", "") or "").strip()[:MAX_SUMMARY_CHARS]
            used_llm = bool(summary)
        except Exception as exc:  # noqa: BLE001
            logger.warning("滚动摘要生成失败，改用确定性摘要：%s", exc)

    if not summary:
        summary = _deterministic_summary(previous, rows)

    conversation.summary = summary
    conversation.summary_upto = cut
    await db.flush()
    return SummaryOutcome(summary=summary, upto=cut, generated_with_llm=used_llm)


__all__ = [
    "HISTORY_BUDGET",
    "HistoryContext",
    "MAX_TURNS",
    "SummaryOutcome",
    "estimate_tokens",
    "load_history",
    "maybe_summarize",
]
