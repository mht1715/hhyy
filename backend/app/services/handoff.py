"""转人工：触发规则、工单状态机、交接摘要（M3-08 / M3-09）。

**状态机是单向的**，且只有这里能改状态：

```
queued ──接管──▶ assigned ──结束──▶ resolved
   │                 │
   └──90s 超时──▶ offline ──次日跟进──▶ assigned
```

非法流转一律抛 :class:`InvalidTransition`（API 层转 409）。为什么不做「容错的自动纠正」：
工单状态是要给人看的（坐席工作台、满意度回访、评估集回流），悄悄改状态比报错更难查。

**五类触发**（PRD FR5.1）分成两档：

| 触发 | 行为 |
| --- | --- |
| 显式点击 / 模型调 ``escalate_human`` / 敏感词 | **立即建单** |
| 连续 2 次拒答 / 连续 2 轮负面情绪 | **只建议**（``suggested_actions``），不建单 |

敏感词必须走「立即」，因为这类对话多等 5 秒（等模型写完）在体验上是灾难；
而「建议转人工」不该替用户做主，只给一个按钮。
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from sqlalchemy import func, select

from app.core.config import settings
from app.models.agent import Conversation, ConversationStatus, Message, MessageRole
from app.models.handoff import HandoffTicket, HandoffTrigger, TicketStatus
from app.rag.citation import REFUSAL_TEMPLATES
from app.services.support_bus import publish

logger = logging.getLogger(__name__)

# 出现即「立即转人工」的词。分三组是为了写进 risk_flags（坐席一眼看到风险类型）。
SENSITIVE_GROUPS: dict[str, tuple[str, ...]] = {
    "投诉": ("投诉", "举报", "曝光", "12315", "药监局"),
    "纠纷": ("起诉", "律师", "医疗纠纷", "维权", "索赔"),
    "赔偿": ("赔偿", "退款不成", "要求赔"),
    "用药安全": ("过量", "吃多了", "误服", "自杀", "轻生"),
}
SENSITIVE_WORDS: tuple[str, ...] = tuple(
    word for group in SENSITIVE_GROUPS.values() for word in group
)

# 负面情绪（「建议」档：连续 2 轮才提示）
EMOTION_WORDS: tuple[str, ...] = (
    "生气", "气愤", "气死", "失望", "垃圾", "骗子", "骗人", "什么破",
    "差评", "无语", "恶心", "垃圾服务", "态度差", "太差",
)

REFUSAL_PREFIXES: tuple[str, ...] = tuple(text[:12] for text in REFUSAL_TEMPLATES.values())

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    TicketStatus.QUEUED.value: {
        TicketStatus.ASSIGNED.value,
        TicketStatus.OFFLINE.value,
        TicketStatus.RESOLVED.value,
    },
    TicketStatus.ASSIGNED.value: {TicketStatus.RESOLVED.value},
    TicketStatus.OFFLINE.value: {TicketStatus.ASSIGNED.value},
    TicketStatus.RESOLVED.value: set(),
}

ACTIVE_STATUSES = (TicketStatus.QUEUED.value, TicketStatus.ASSIGNED.value)

TRIGGER_LABELS: dict[str, str] = {
    "explicit": "用户请求",
    "agent_tool": "助手请求",
    "sensitive": "敏感场景",
    "refusal": "连续拒答",
    "emotion": "情绪升级",
    "offline": "超时留言",
}

_REPLY_TEMPLATES: dict[str, str] = {
    "sensitive": "您好，我是人工客服。您反馈的问题我已经记录，会优先为您核实处理，请稍等。",
    "explicit": "您好，我是人工客服，请问方便说下具体情况吗？我这边帮您跟进。",
    "agent_tool": "您好，我是人工客服。前面的问题我再帮您确认一下，请补充下具体情况。",
    "refusal": "您好，我是人工客服，这个问题我来帮您看，请稍等。",
    "emotion": "非常抱歉给您带来不好的体验，我是人工客服，这就帮您处理。",
    "offline": "您好，已收到您的留言，我们会在工作时间内与您联系。",
}
DEFAULT_REPLY = _REPLY_TEMPLATES["explicit"]


class InvalidTransition(ValueError):
    """工单状态流转不合法（API 层转 409）。"""


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(value: Any) -> str:
    from app.core.timefmt import iso_utc

    return iso_utc(value)


def _elapsed_seconds(since: Any, *, now: datetime | None = None) -> int:
    if not isinstance(since, datetime):
        return 0
    return max(0, int(((now or _now()) - since).total_seconds()))


# --------------------------------------------------------------------------- 触发规则
def detect_sensitive(message: str) -> tuple[bool, list[str]]:
    """命中敏感词则返回 ``(True, risk_flags)``。"""
    text = message or ""
    flags = [group for group, words in SENSITIVE_GROUPS.items() if any(w in text for w in words)]
    return bool(flags), flags


def detect_emotion(text: str) -> bool:
    return any(word in (text or "") for word in EMOTION_WORDS)


def is_refusal(text: str) -> bool:
    """判断一条助手回答是不是「拒答」（按内置话术前缀识别）。

    为什么不给 messages 加 ``refused`` 列：拒答话术本身就是稳定的（只有几套），
    前缀匹配零成本，也不需要在 M2 的表结构上再改一次。
    """
    value = (text or "").strip()
    return any(value.startswith(prefix) for prefix in REFUSAL_PREFIXES)


def suggest_trigger(user_texts: Sequence[str], assistant_texts: Sequence[str]) -> Optional[str]:
    """根据最近几条消息判断「该不该建议转人工」（不建单）。"""
    streak = max(1, settings.handoff_refusal_streak)
    recent_assistant = [text for text in assistant_texts if (text or "").strip()][-streak:]
    if len(recent_assistant) >= streak and all(is_refusal(text) for text in recent_assistant):
        return HandoffTrigger.REFUSAL.value
    recent_user = [text for text in user_texts if (text or "").strip()][-streak:]
    if len(recent_user) >= streak and all(detect_emotion(text) for text in recent_user):
        return HandoffTrigger.EMOTION.value
    return None


# --------------------------------------------------------------------------- 状态机
def _ensure_transition(current: str, target: str) -> None:
    if target not in ALLOWED_TRANSITIONS.get(current, set()):
        raise InvalidTransition(f"工单状态不允许该操作：{current} → {target}")


async def _set_conversation_status(db: Any, conversation_id: Any, status: str) -> None:
    conversation = await db.get(Conversation, conversation_id)
    if conversation is not None and conversation.status != status:
        conversation.status = status
        await db.flush()


async def queue_position(db: Any, ticket: HandoffTicket) -> int:
    """排在第几位：比它早建、且还在排队的工单数 + 1。"""
    if ticket.status != TicketStatus.QUEUED.value:
        return 0
    # 刚 flush 出来的行可能还没拿到库里的 created_at，用当前时间兜底
    cutoff = ticket.created_at or _now()
    ahead = int(
        (
            await db.execute(
                select(func.count())
                .select_from(HandoffTicket)
                .where(
                    HandoffTicket.status == TicketStatus.QUEUED.value,
                    HandoffTicket.created_at < cutoff,
                )
            )
        ).scalar_one()
    )
    return ahead + 1


async def active_ticket(db: Any, conversation_id: Any) -> Optional[HandoffTicket]:
    return (
        await db.execute(
            select(HandoffTicket)
            .where(
                HandoffTicket.conversation_id == conversation_id,
                HandoffTicket.status.in_(ACTIVE_STATUSES),
            )
            .order_by(HandoffTicket.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def request_handoff(
    db: Any,
    *,
    conversation: Conversation,
    user_id: Any,
    reason: str,
    trigger: str,
    risk_flags: Optional[Sequence[str]] = None,
    summary: Optional[dict[str, Any]] = None,
) -> tuple[HandoffTicket, bool]:
    """建单（幂等）。返回 ``(ticket, created)``，不 commit。"""
    existing = await active_ticket(db, conversation.id)
    if existing is not None:
        existing.queue_position = await queue_position(db, existing)
        await _set_conversation_status(
            db,
            conversation.id,
            ConversationStatus.HUMAN_ACTIVE.value
            if existing.status == TicketStatus.ASSIGNED.value
            else ConversationStatus.HANDOFF_PENDING.value,
        )
        await db.flush()
        return existing, False

    ticket = HandoffTicket(
        conversation_id=conversation.id,
        user_id=user_id,
        reason=" ".join(str(reason or "").split())[:64],
        trigger=trigger if trigger in TRIGGER_LABELS else HandoffTrigger.EXPLICIT.value,
        risk_flags=list(dict.fromkeys(risk_flags or [])),
        summary=summary or {},
        status=TicketStatus.QUEUED.value,
    )
    db.add(ticket)
    await db.flush()
    ticket.queue_position = await queue_position(db, ticket)
    await _set_conversation_status(db, conversation.id, ConversationStatus.HANDOFF_PENDING.value)
    await db.flush()
    return ticket, True


async def accept_ticket(db: Any, ticket: HandoffTicket, agent_id: Any) -> HandoffTicket:
    _ensure_transition(ticket.status, TicketStatus.ASSIGNED.value)
    ticket.status = TicketStatus.ASSIGNED.value
    ticket.assigned_to = agent_id
    ticket.accepted_at = _now()
    ticket.queue_position = 0
    await _set_conversation_status(
        db, ticket.conversation_id, ConversationStatus.HUMAN_ACTIVE.value
    )
    await db.flush()
    return ticket


async def resolve_ticket(db: Any, ticket: HandoffTicket, *, tags: Sequence[str] = ()) -> HandoffTicket:
    _ensure_transition(ticket.status, TicketStatus.RESOLVED.value)
    ticket.status = TicketStatus.RESOLVED.value
    ticket.closed_at = _now()
    if tags:
        summary = dict(ticket.summary or {})
        summary["tags"] = [str(tag)[:16] for tag in tags][:6]
        ticket.summary = summary
    # 人工结束 ≠ 会话结束：把会话交还给 AI，用户能继续问、也能再次转人工。
    # 只有「留言/超时」这种没人接的情况才真正关掉会话。
    await _set_conversation_status(
        db, ticket.conversation_id, ConversationStatus.BOT_ACTIVE.value
    )
    await db.flush()
    return ticket


async def mark_offline(
    db: Any, ticket: HandoffTicket, *, name: str, contact: str, demand: str
) -> HandoffTicket:
    """90s 无坐席 → 留言工单（PRD FR5.3）。

    对**已经是 offline** 的工单是幂等的：用户重复提交只更新留言内容，不报状态错。
    """
    if ticket.status != TicketStatus.OFFLINE.value:
        _ensure_transition(ticket.status, TicketStatus.OFFLINE.value)
        ticket.status = TicketStatus.OFFLINE.value
        ticket.closed_at = _now()
        ticket.reason = (ticket.reason or "超时留言")[:64]
    summary = dict(ticket.summary or {})
    summary["offline"] = {
        "name": str(name or "")[:32],
        "contact": str(contact or "")[:64],
        "demand": " ".join(str(demand or "").split())[:200],
    }
    ticket.summary = summary
    await _set_conversation_status(db, ticket.conversation_id, ConversationStatus.CLOSED.value)
    await db.flush()
    return ticket


# --------------------------------------------------------------------------- 交接摘要
def _entities(messages: Sequence[Message]) -> list[str]:
    """从消息里抠「坐席要知道」的实体：药品名、订单号。"""
    found: list[str] = []
    for message in messages:
        for citation in message.citations or []:
            title = str((citation or {}).get("doc_title") or "").strip()
            if title and title not in found:
                found.append(title[:40])
    for message in messages:
        for match in re.findall(r"订单\s*([0-9a-f]{8})", message.content or ""):
            label = f"订单 {match}"
            if label not in found:
                found.append(label)
    return found[:5]


def _tried_steps(messages: Sequence[Message]) -> list[str]:
    from app.tools.base import tool_label

    labels: list[str] = []
    for message in messages:
        for call in message.tool_calls or []:
            name = str((call or {}).get("name") or "").strip()
            if not name:
                continue
            label = tool_label(name)
            if label not in labels:
                labels.append(label)
    return labels[:5]


def _short(text: str, limit: int) -> str:
    value = " ".join((text or "").split())
    return value if len(value) <= limit else value[: limit - 1] + "…"


def build_summary(
    conversation: Conversation | None,
    messages: Sequence[Message],
    *,
    risk_flags: Sequence[str] = (),
    trigger: str = "",
    reason: str = "",
) -> dict[str, Any]:
    """确定性交接摘要（不依赖模型，永不为空）。

    坐席看到的必须是一屏能看完的东西：诉求 / 已尝试 / 卡在哪 / 风险 / 建议话术。
    ``text`` 控制在 200 字内，直接渲染到工单卡片上。
    """
    user_texts = [m.content for m in messages if m.role == MessageRole.USER.value]
    assistant_texts = [m.content for m in messages if m.role == MessageRole.ASSISTANT.value]
    intent = _short(user_texts[0], 48) if user_texts else _short(reason or "用户发起咨询", 48)
    unresolved = _short(user_texts[-1], 48) if user_texts else ""
    if not unresolved or is_refusal(assistant_texts[-1] if assistant_texts else ""):
        unresolved = unresolved or _short(reason, 48)
    tried = _tried_steps(messages)
    entities = _entities(messages)
    suggested = _REPLY_TEMPLATES.get(trigger, DEFAULT_REPLY)

    text = f"用户诉求：{intent}"
    if tried:
        text += f"；已尝试：{'、'.join(tried)}"
    if unresolved:
        text += f"；待解决：{unresolved}"
    if risk_flags:
        text += f"；风险：{'、'.join(risk_flags)}"
    if len(text) > 199:
        text = text[:196] + "…"

    return {
        "intent": intent,
        "entities": entities,
        "tried_steps": tried,
        "unresolved": unresolved,
        "risk_flags": list(risk_flags),
        "suggested_reply": suggested,
        "trigger": trigger,
        "text": text,
    }


SUMMARY_PROMPT = """你是客服工单助手。把下面的对话压缩成给人工坐席看的交接摘要，只输出 JSON：
{{"intent": "用户想做什么，≤30字", "entities": ["药品名/订单号等实体"], "tried_steps": ["已经做过的尝试"], "unresolved": "还没解决的点，≤30字", "risk_flags": ["风险点"], "suggested_reply": "坐席开场白，≤40字", "text": "整段摘要，≤180字"}}

只依据对话内容，不要编造。对话如下：
{dialogue}
"""


def _parse_summary(raw: str) -> Optional[dict[str, Any]]:
    text = (raw or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    for key in ("intent", "unresolved", "suggested_reply", "text"):
        if key in data:
            data[key] = _short(str(data[key]), 60 if key != "text" else 180)
    for key in ("entities", "tried_steps", "risk_flags"):
        if key in data and isinstance(data[key], list):
            data[key] = [str(item)[:32] for item in data[key]][:5]
    return data


async def refresh_summary(
    db: Any, ticket: HandoffTicket, *, llm: Any = None, limit: int = 20
) -> dict[str, Any]:
    """生成/刷新交接摘要：先确定性兜底，再用模型润色（失败就保留兜底）。"""
    conversation = await db.get(Conversation, ticket.conversation_id)
    rows = (
        await db.execute(
            select(Message)
            .where(
                Message.conversation_id == ticket.conversation_id,
                Message.role.in_(
                    [
                        MessageRole.USER.value,
                        MessageRole.ASSISTANT.value,
                        MessageRole.HUMAN_AGENT.value,
                    ]
                ),
            )
            .order_by(Message.created_at.asc())
            .limit(limit)
        )
    ).scalars().all()

    base = build_summary(
        conversation,
        list(rows),
        risk_flags=ticket.risk_flags or [],
        trigger=ticket.trigger or "",
        reason=ticket.reason or "",
    )

    if llm is not None:
        dialogue = "\n".join(
            f"{'用户' if m.role == MessageRole.USER.value else '客服'}：{_short(m.content, 200)}"
            for m in rows
        )
        try:
            response = await llm.ainvoke(
                [
                    {"role": "system", "content": "你是严谨的客服摘要器，只输出 JSON。"},
                    {"role": "user", "content": SUMMARY_PROMPT.format(dialogue=dialogue)},
                ]
            )
            polished = _parse_summary(str(getattr(response, "content", "") or ""))
            if polished:
                base.update({k: v for k, v in polished.items() if v})
        except Exception as exc:  # noqa: BLE001 —— 摘要是加分项，失败用兜底
            logger.warning("交接摘要模型润色失败，使用确定性摘要：%s", exc)

    ticket.summary = base
    await db.flush()
    return base


# --------------------------------------------------------------------------- 对外载荷
def ticket_payload(
    ticket: HandoffTicket,
    *,
    queue_timeout: int | None = None,
    assigned_name: str | None = None,
) -> dict[str, Any]:
    """SSE / HTTP 共用的一份工单视图。"""
    timeout = (
        settings.handoff_queue_timeout if queue_timeout is None else queue_timeout
    )
    remaining = 0
    if ticket.status == TicketStatus.QUEUED.value:
        remaining = max(0, timeout - _elapsed_seconds(ticket.created_at))
    return {
        "ticket_id": str(ticket.id),
        "status": ticket.status,
        "queue_position": int(ticket.queue_position or 0),
        "queue_expires_in": remaining,
        "reason": ticket.reason or "",
        "trigger": ticket.trigger or "",
        "risk_flags": list(ticket.risk_flags or []),
        "summary": dict(ticket.summary or {}),
        "conversation_id": str(ticket.conversation_id),
        "created_at": _iso(ticket.created_at),
        "assigned_to": assigned_name or "",
        "wait_seconds": _elapsed_seconds(ticket.created_at),
    }


async def broadcast_status(ticket: HandoffTicket, *, by: str = "") -> None:
    """把工单状态变化推给该会话的所有连接（用户端 + 坐席端）。

    载荷用完整的 ``ticket_payload``：用户端要靠它把排队条切成「客服已接入」，
    只发 ``{ticket_id, status}`` 的话前端拿不到坐席名和排队时限，只能再查一次接口。
    """
    await publish(
        ticket.conversation_id,
        {
            "type": "status",
            "status": _conversation_status_for(ticket),
            "ticket": ticket_payload(ticket, assigned_name=by),
            "by": by,
        },
    )


def _conversation_status_for(ticket: HandoffTicket) -> str:
    if ticket.status == TicketStatus.ASSIGNED.value:
        return ConversationStatus.HUMAN_ACTIVE.value
    # 坐席结束会话 → AI 接回来（用户还能继续问、也能再次转人工）
    if ticket.status == TicketStatus.RESOLVED.value:
        return ConversationStatus.BOT_ACTIVE.value
    # 90s 无人接管、用户留了言 → 会话结束，等回访
    if ticket.status == TicketStatus.OFFLINE.value:
        return ConversationStatus.CLOSED.value
    return ConversationStatus.HANDOFF_PENDING.value


__all__ = [
    "ALLOWED_TRANSITIONS",
    "EMOTION_WORDS",
    "InvalidTransition",
    "SENSITIVE_GROUPS",
    "SENSITIVE_WORDS",
    "TRIGGER_LABELS",
    "accept_ticket",
    "active_ticket",
    "broadcast_status",
    "build_summary",
    "detect_emotion",
    "detect_sensitive",
    "is_refusal",
    "mark_offline",
    "queue_position",
    "refresh_summary",
    "request_handoff",
    "resolve_ticket",
    "suggest_trigger",
    "ticket_payload",
]
