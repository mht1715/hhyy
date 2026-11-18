"""指代消解（M3 上下文修复）。

「这个药怎么购买」「它有什么禁忌」这类句子离开上文就读不懂：

1. supervisor 会把「短 + 指代」判成「指向不明确」→ 走 clarify，用户看到一条
   「请问你问的是哪一类」的废话（这正是「上下文没有记忆」的真实体感）；
2. 检索会拿原句去搜向量库，搜不到任何药品，于是退化成拒答。

所以在路由之前用一次小模型调用把它改写成**自包含的查询**。改写结果只用于
路由 / 检索 / 子 Agent 的「当前问题」，**不会覆盖用户原话**——落库、记忆抽取、
Langfuse 里看到的仍然是用户原话。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Mapping, Sequence

logger = logging.getLogger(__name__)

# 出现这些词（且句子短）就认为依赖上文
FOLLOWUP_MARKERS = (
    "这个",
    "那个",
    "这款",
    "这药",
    "该药",
    "这种",
    "它",
    "刚才",
    "上面",
    "前面",
    "刚才说",
)
MAX_FOLLOWUP_CHARS = 40
MAX_REWRITE_CHARS = 120


def needs_contextualize(
    message: str, history: Sequence[Mapping[str, Any]] | None
) -> bool:
    """只有「短句 + 含指代词 + 有上文」才值得多花一次模型调用。"""
    text = (message or "").strip()
    if not text or not history:
        return False
    if len(text) > MAX_FOLLOWUP_CHARS:
        return False
    return any(marker in text for marker in FOLLOWUP_MARKERS)


def build_rewrite_prompt(
    message: str, history: Sequence[Mapping[str, Any]]
) -> str:
    lines = []
    for item in list(history)[-6:]:
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        role = item.get("role")
        who = "用户" if role == "user" else ("人工客服" if role == "human_agent" else "助手")
        lines.append(f"{who}：{content[:200]}")
    dialogue = "\n".join(lines)
    return (
        "把用户最后一句话改写成一句**脱离上文也能看懂**的问题："
        "把「这个药 / 它 / 刚才那个」替换成上文里具体的药品名或事物。\n"
        "要求：\n"
        "- 只输出改写后的那一句话，不要解释、不要引号、不要「改写为」之类的前缀；\n"
        "- 不要添加原文没有的信息，不要回答问题；\n"
        "- 如果上文也判断不出指代，就原样输出用户的话。\n\n"
        f"【最近对话】\n{dialogue}\n\n"
        f"用户最后一句：{message}\n"
        "改写："
    )


def _clean(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    text = text.strip("「」『』\"'`* \n")
    # 模型偶尔会输出多行（解释 + 改写）：取第一行有效内容
    for line in text.splitlines():
        line = line.strip().strip("「」『』\"'`* ")
        if line:
            text = line
            break
    return text[:MAX_REWRITE_CHARS]


async def rewrite_query(
    message: str,
    history: Sequence[Mapping[str, Any]],
    llm: Any,
    *,
    timeout: float = 3.0,
) -> str:
    """改写失败一律返回空串，调用方回退到原句（上下文是增强项，不是前置条件）。"""
    if llm is None or not history:
        return ""
    try:
        response = await asyncio.wait_for(
            llm.ainvoke(build_rewrite_prompt(message, history)), timeout=timeout
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("指代消解失败，用原句：%s", exc)
        return ""
    text = _clean(str(getattr(response, "content", "") or ""))
    if not text or text == message:
        return ""
    return text


__all__ = [
    "FOLLOWUP_MARKERS",
    "build_rewrite_prompt",
    "needs_contextualize",
    "rewrite_query",
]
