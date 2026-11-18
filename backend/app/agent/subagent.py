"""单个子 Agent 的执行单元（M2-07）。

拆成**两段**是刻意设计：

- ``prepare_subagent``：跑工具（检索 / 查订单 / 查药品），产出「参考资料 + 引用」。
  这一段没有模型生成，多个子 Agent 可以真并行（``asyncio.gather``）。
- ``generate_subagent``：拿准备好的消息让模型写一段短结论。只在**多 Agent** 时才需要，
  因为多路结果要交给汇总节点融合；单 Agent 时直接流式生成，省一次模型往返。

工具计划是**确定性**的：绑定 ``kb_search`` 就一定先检索，绑定 ``order_lookup`` 就一定
先查订单。理由有两条：RAG 类问题的回答质量完全取决于「有没有真的检索」（让模型自己
决定要不要检索，它经常偷懒直接编），以及确定性计划的结果可复现、好测试。
``as_function_schema`` 仍然由工具注册表统一生成，留给后续「自主 ReAct」用。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

from sqlalchemy import select

from app.agent.registry import AgentConfig
from app.guardrail.citations import DISCLAIMER, needs_disclaimer
from app.llm.client import get_chat_client
from app.memory.extractor import has_explicit_trigger
from app.models.agent import PromptStatus, PromptTemplate
from app.rag.citation import refusal_text
from app.services.handoff import SENSITIVE_WORDS
from app.tools.base import ToolContext, ToolResult, call_tool

logger = logging.getLogger(__name__)

DEFAULT_PROMPT = """你是「{agent_name}」。{description}

【参考资料】
{context}

【回答规则】
1. 只能依据上面的参考资料回答。资料里没有的内容，明确说「资料中没有相关信息」，绝不猜测。
2. 引用资料时在句末标注角标，例如「孕妇禁用[1]」。角标编号必须来自参考资料。
3. 涉及诊断、处方调整、严重不良反应时，提示用户前往正规医院就诊。
4. 语气温和专业，先给结论再解释；不要写免责声明（系统会统一追加）。
"""

# 追加到每个 Agent 的系统提示词后面：多 Agent 并行时最容易出的问题是「越界」——
# AI 药师去回答订单问题、订单售后去回答哺乳期能不能吃药，汇总后就成了两份互相矛盾的答案。
SCOPE_RULES = """

【职责边界】
- 只回答与你职责相关的那部分问题。用户同时问了别的领域时，只答自己这一块，
  不要重复、也不要评价其他助手的结论。
- 如果问题完全不属于你的职责，直接说明「这部分请 @ 对应的助手」，不要硬答。
- 回答控制在 300 字以内：先给结论，再给依据，不要展开无关背景。
"""

# 多 Agent 汇总时单个 Agent 的输出上限（字符数），配合 SCOPE_RULES 一起收口
SUBAGENT_MAX_TOKENS = 500
SYNTHESIS_MAX_TOKENS = 700


@dataclass(slots=True)
class SubAgentDraft:
    """子 Agent 的「准备结果」：消息 + 引用 + 可观测数据，还没有生成文字。"""

    agent: AgentConfig
    messages: list[dict[str, str]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    retrieval: dict[str, Any] = field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    refused: bool = False
    reason: Optional[str] = None
    needs_disclaimer: bool = False
    # 准备阶段就判定「无法作答」时直接给的固定话术（不花模型调用）
    fallback_text: Optional[str] = None
    # M4-05：这一版 prompt 的标识（code@vN），灰度时同一 Agent 可能落在不同版本
    prompt_version: str = ""


@dataclass(slots=True)
class SubAgentResult:
    """子 Agent 的最终产出。``ok=False`` 表示超时/异常，由汇总节点降级处理。"""

    agent: AgentConfig
    text: str = ""
    ok: bool = True
    error: Optional[str] = None
    elapsed_ms: int = 0
    citations: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    retrieval: dict[str, Any] = field(default_factory=dict)
    refused: bool = False
    needs_disclaimer: bool = False


def _render(template: str, values: dict[str, str]) -> str:
    """只替换已知占位符。

    不用 ``str.format``：prompt 里经常出现 JSON 例子，一个没转义的 ``{`` 就会让
    整轮对话 500，而这个错误在演示现场几乎无法解释。
    """
    text = template
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return text


async def load_prompt(db: Any, agent: AgentConfig) -> str:
    """取该 Agent 的 production prompt，取不到就用内置模板（降级不报错）。"""
    content, _version = await load_prompt_versioned(db, agent)
    return content


def rollout_bucket(user_id: Any) -> int:
    """兼容旧调用点：实现已收敛到 ``app.agent.prompts``。"""
    from app.agent.prompts import rollout_bucket as _bucket

    return _bucket(user_id)


async def load_prompt_versioned(
    db: Any, agent: AgentConfig, *, user_id: Any = None
) -> tuple[str, str]:
    """返回 ``(content, "code@vN")``；灰度命中 testing 版本时返回那一版。"""
    if not agent.system_prompt_code:
        return DEFAULT_PROMPT, ""
    rows = list(
        (
            await db.execute(
                select(PromptTemplate)
                .where(
                    PromptTemplate.code == agent.system_prompt_code,
                    PromptTemplate.status.in_(
                        [PromptStatus.PRODUCTION.value, PromptStatus.TESTING.value]
                    ),
                )
                .order_by(PromptTemplate.version.desc())
            )
        )
        .scalars()
        .all()
    )
    from app.agent.prompts import resolve_prompt_rows, version_label

    row, _reason = resolve_prompt_rows(rows, bucket=rollout_bucket(user_id))
    if row is None:
        return DEFAULT_PROMPT, ""
    return (row.content or DEFAULT_PROMPT), version_label(row)


def _context_from_chunks(chunks: list[Any]) -> tuple[str, list[dict[str, Any]]]:
    """把检索片段拼成带 [n] 的上下文，同时产出引用列表（序号从 1 开始）。"""
    blocks: list[str] = []
    citations: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks, start=1):
        head = f"[{index}] {chunk.doc_title or chunk.doc_id}"
        if chunk.section:
            head += f" · {chunk.section}"
        blocks.append(f"{head}\n{chunk.content}")
        citations.append(
            {
                "index": index,
                "doc_id": chunk.doc_id,
                "kb_id": chunk.kb_id,
                "doc_title": chunk.doc_title or chunk.doc_id,
                "section": chunk.section,
                "page": chunk.page,
                "score": round(chunk.score, 4),
                "snippet": " ".join(chunk.content.split())[:160],
                "url": chunk.source_url,
            }
        )
    return "\n\n".join(blocks), citations


def _orders_block(orders: list[dict[str, Any]]) -> str:
    if not orders:
        return ""
    lines = ["【订单信息】"]
    for order in orders:
        items = "、".join(f"{item['name']}×{item['quantity']}" for item in order.get("items") or [])
        lines.append(
            f"- 订单 {order['order_id'][:8]}：{order['status']}，金额 ¥{order['total_amount']}，"
            f"下单 {order.get('age_days')} 天前，商品 {items or '（无）'}"
        )
    return "\n".join(lines)


def _products_block(items: list[dict[str, Any]]) -> str:
    if not items:
        return ""
    lines = ["【药品信息】"]
    for item in items:
        lines.append(
            f"- {item['name']}（{item['generic_name']}）：{item['spec']}，¥{item['price']}，"
            f"厂家 {item['manufacturer']}，批准文号 {item['approval_number']}"
        )
    return "\n".join(lines)


def _tool_event(agent: AgentConfig, result: ToolResult) -> dict[str, Any]:
    return {
        "agent_code": agent.code,
        "name": result.name,
        "ok": result.ok,
        "summary": result.summary or (result.error or ""),
        "elapsed_ms": result.elapsed_ms,
    }


def _history_messages(history: Optional[list[dict[str, Any]]]) -> list[dict[str, str]]:
    """把会话历史转成 chat 消息。

    ``human_agent`` 不是合法的 chat role：转成 assistant 并打上「人工客服」前缀，
    否则模型会以为那是自己说过的话，或者干脆忽略（坐席结束会话后 AI 要接着聊）。
    """
    out: list[dict[str, str]] = []
    for item in history or []:
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        role = item.get("role")
        if role == "human_agent":
            out.append({"role": "assistant", "content": f"【人工客服】{content}"})
        elif role in {"user", "assistant"}:
            out.append({"role": role, "content": content})
        else:
            out.append({"role": "assistant", "content": content})
    return out


async def prepare_subagent(
    *,
    db: Any,
    agent: AgentConfig,
    message: str,
    role: str,
    user_id: Any = None,
    conversation_id: Any = None,
    product_id: Any = None,
    order_id: Any = None,
    retrieval: Any = None,
    history: Optional[list[dict[str, str]]] = None,
    summary: str = "",
    memory_block: str = "",
    memory_items: Optional[list[Any]] = None,
    on_event: Optional[Any] = None,
) -> SubAgentDraft:
    """跑工具、拼上下文。``on_event`` 是同步回调，用来即时发 ``tool``/``retrieval`` 事件。

    ``summary`` 是滚动摘要（更早的对话），``memory_block`` 是长期记忆。
    两者都由运行时统一取一次再传给各子 Agent——不能每个子 Agent 自己查：
    两个 ``@`` 并行时会重复读库，而且可能出现「A 看到了记忆、B 没看到」的不一致。
    """
    started = time.perf_counter()
    tool_ctx = ToolContext(
        db=db,
        role=role,
        user_id=user_id,
        kb_codes=tuple(agent.kb_codes),
        conversation_id=conversation_id,
        retrieval=retrieval,
    )

    chunks: list[Any] = []
    kb_hits: dict[str, Any] = {}
    tool_events: list[dict[str, Any]] = []
    blocks: list[str] = []
    suggested: dict[str, Any] | None = None

    async def run(name: str, **kwargs: Any) -> ToolResult:
        result = await call_tool(name, tool_ctx, **kwargs)
        event = _tool_event(agent, result)
        tool_events.append(event)
        if on_event:
            on_event("tool", event)
        if name == "escalate_human" and result.ok:
            nonlocal suggested
            suggested = (result.data or {}).get("suggested_action")
        return result

    # 1) 知识库：Agent 绑了 kb_search 就一定检索（决定回答有没有依据）
    retrieval_query = message
    if "kb_search" in agent.tools and agent.kb_codes:
        result = await run("kb_search", query=retrieval_query)
        if result.ok:
            data = result.data or {}
            chunks = list(data.get("chunks") or [])
            kb_hits = {k: v for k, v in data.items() if k != "chunks"}
            context, citations = _context_from_chunks(chunks)
            if context:
                blocks.append(context)
            if on_event:
                on_event("retrieval", {**kb_hits, "agent_code": agent.code})
    elif "policy_search" in agent.tools and agent.kb_codes:
        result = await run("policy_search", query=retrieval_query)
        if result.ok:
            data = result.data or {}
            chunks = list(data.get("chunks") or [])
            kb_hits = {k: v for k, v in data.items() if k != "chunks"}
            context, citations = _context_from_chunks(chunks)
            if context:
                blocks.append(context)
            if on_event:
                on_event("retrieval", {**kb_hits, "agent_code": agent.code})

    # 2) 结构化数据：药品 / 订单
    if "product_lookup" in agent.tools and product_id:
        result = await run("product_lookup", product_id=str(product_id))
        if result.ok:
            block = _products_block((result.data or {}).get("items") or [])
            if block:
                blocks.append(block)

    if "order_lookup" in agent.tools:
        result = await run("order_lookup", **({"order_id": str(order_id)} if order_id else {}))
        if result.ok:
            block = _orders_block((result.data or {}).get("orders") or [])
            if block:
                blocks.append(block)

    # 3) 敏感词：先建「转人工」意图，再照常回答（真实工单由运行时/API 层建）
    if "escalate_human" in agent.tools and any(word in message for word in SENSITIVE_WORDS):
        await run("escalate_human", reason="用户问题涉及敏感场景", summary=message[:200])

    # 4) 显式记忆指令（「记住…」）：立即写入并回执，不等异步抽取（PRD FR6.4-4）
    if "remember" in agent.tools and user_id and has_explicit_trigger(message):
        await run("remember", content=message)

    context_text = "\n\n".join(blocks).strip()
    prompt_template, prompt_version = await load_prompt_versioned(db, agent, user_id=user_id)
    system_prompt = _render(
        prompt_template,
        {
            "agent_name": agent.name,
            "description": agent.description or "",
            "context": context_text or "（本次没有检索到资料）",
            "today": date.today().isoformat(),
            "role": role,
            "summary": summary or "（无）",
            "memory": memory_block or "（无）",
        },
    )

    citations: list[dict[str, Any]] = []
    if context_text:
        # 重新编号：只有真正拼进上下文的片段才配拥有 [n]
        _, citations = _context_from_chunks(chunks)

    # 摘要 / 记忆 / 职责边界统一在运行时追加，不指望每个 prompt 模板都记得写
    if summary:
        system_prompt += f"\n\n【更早的对话摘要】（来自本会话之前的对话）\n{summary}"
    if memory_block:
        system_prompt += f"\n\n{memory_block}"
    system_prompt = system_prompt + SCOPE_RULES

    draft = SubAgentDraft(
        agent=agent,
        messages=[
            {"role": "system", "content": system_prompt},
            *_history_messages(history),
            {"role": "user", "content": message},
        ],
        citations=citations,
        retrieval={**kb_hits, "agent_code": agent.code},
        tool_calls=tool_events,
        needs_disclaimer=needs_disclaimer(agent),
        prompt_version=prompt_version,
    )

    # 4) 没有资料可依据：直接给拒答话术，不浪费一次模型调用
    kb_refused = bool(kb_hits.get("refused")) if kb_hits else True
    if not context_text and agent.kb_codes and kb_refused:
        draft.refused = True
        draft.reason = str(kb_hits.get("reason") or "no_hit")
        draft.fallback_text = refusal_text(draft.reason)
        # 有可信记忆时，拒答也要「记得用户」：只复述记忆、不给药品结论（M3-06）。
        # 什么都不说会显得「刚说过的话你都没记住」，直接答又违反「无依据不猜」。
        if memory_items:
            from app.memory.inject import memory_refusal_text

            with_memory = memory_refusal_text(memory_items)
            if with_memory:
                draft.fallback_text = with_memory

    logger.debug(
        "prepared agent=%s tools=%s chars=%d elapsed=%dms",
        agent.code,
        len(tool_events),
        len(context_text),
        int((time.perf_counter() - started) * 1000),
    )
    if suggested:
        draft.tool_calls.append({"suggested_action": suggested})
    return draft


async def generate_subagent(draft: SubAgentDraft, *, llm: Any = None) -> SubAgentResult:
    """让模型写一段短结论（多 Agent 汇总时才需要）。``llm`` 用于测试注入。"""
    started = time.perf_counter()
    if draft.fallback_text:
        return SubAgentResult(
            agent=draft.agent,
            text=draft.fallback_text,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            citations=[],
            tool_calls=draft.tool_calls,
            retrieval=draft.retrieval,
            refused=True,
            needs_disclaimer=False,
        )

    try:
        client = llm or get_chat_client(
            temperature=draft.agent.temperature,
            model=draft.agent.model or None,
            max_tokens=SUBAGENT_MAX_TOKENS,
        )
        # 带上 Langfuse 的 CallbackHandler：否则这一路 generation（含 token/成本）
        # 不会出现在 trace 里，只剩一个空 span
        from app.observability.tracing import get_trace_sink

        response = await client.ainvoke(
            draft.messages, config={"callbacks": get_trace_sink().callbacks()}
        )
        text = str(getattr(response, "content", "") or "").strip()
    except Exception as exc:  # noqa: BLE001 —— 单路失败由汇总节点降级
        return SubAgentResult(
            agent=draft.agent,
            ok=False,
            error=f"{type(exc).__name__}: {exc}",
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            citations=[],
            tool_calls=draft.tool_calls,
            retrieval=draft.retrieval,
        )

    return SubAgentResult(
        agent=draft.agent,
        text=text,
        elapsed_ms=int((time.perf_counter() - started) * 1000),
        citations=draft.citations,
        tool_calls=draft.tool_calls,
        retrieval=draft.retrieval,
        refused=draft.refused,
        needs_disclaimer=draft.needs_disclaimer,
    )


__all__ = [
    "DISCLAIMER",
    "DEFAULT_PROMPT",
    "SENSITIVE_WORDS",
    "SubAgentDraft",
    "SubAgentResult",
    "generate_subagent",
    "load_prompt",
    "prepare_subagent",
]
