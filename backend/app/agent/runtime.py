"""编排运行时（M2-03 / M2-05 / M2-07）：LangGraph 图 + 事件流。

图结构（``build_graph``）::

    START → route ─┬─(mode=clarify)→ clarify ─┐
                   └─(其余)────────→ dispatch ─┴→ compose → guardrail → END

- ``route``：显式 mentions 直连 / supervisor 决策（``app.agent.router``）
- ``dispatch``：``asyncio.gather`` 并行跑子 Agent（单路 8s 超时，失败降级）
- ``compose``：单 Agent 直接流式生成；多 Agent 先各写一段结论再汇总
- ``guardrail``：引用裁剪 + 免责声明 + 终止事件 ``done``

事件通过 ``get_stream_writer()`` 实时外发（``stream_mode="custom"``），所以
「两个 Agent 同时开始」「检索命中了几段」这些过程中信息是真的边跑边发，
而不是跑完一次性吐出来。

**状态与依赖分离**：``AgentState`` 只放可序列化的业务字段（M3 要接 checkpointer），
``AsyncSession`` / trace / LLM 这些运行时依赖挂在 :class:`TurnContext` 上。
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional, Sequence

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from app.agent.registry import AgentConfig, AgentRegistry, get_agent_registry
from app.agent.router import RouteDecision, RouteError, decide_route
from app.agent.sse import SSEEvent, error_event
from app.agent.state import AgentState
from app.agent.subagent import (
    SubAgentDraft,
    SubAgentResult,
    generate_subagent,
    prepare_subagent,
)
from app.core.config import settings
from app.guardrail.citations import CitationStreamFilter, finalize, needs_disclaimer
from app.llm.client import get_chat_client
from app.rag.citation import refusal_text

logger = logging.getLogger(__name__)

SYNTHESIS_PROMPT = """你是「花红药业」在线客服的汇总助手。下面有多个 Agent 分别回答了用户同一个问题。
请把它们融合成一段给用户的回答：

- 按主题分段，每段开头用「**{来源** 」标明结论来自哪个 Agent（例如「**AI 药师**」）；
- **只能转述对应 Agent 已经说过的内容**，不要替某个 Agent 补它没说的结论；
- 保留原文里的 [n] 角标，不要新增角标，也不要改动编号；
- 结论冲突时并列陈述，并说明「两种说法存在差异，建议人工确认」；
- 全文控制在 500 字以内；
- 不要写免责声明（系统会统一追加）；不要提到"参考资料""Agent"这类内部词汇。

用户问题：{question}

各 Agent 的结论：
{answers}
"""


@dataclass(slots=True)
class TurnRequest:
    """一次对话请求（与 HTTP 层解耦，便于单测直接构造）。"""

    message: str
    agent_code: str = "drug_consult"
    mentions: list[dict[str, Any]] = field(default_factory=list)
    role: str = "visitor"
    user_id: Any = None
    conversation_id: Any = None
    product_id: Any = None
    order_id: Any = None
    history: list[dict[str, str]] = field(default_factory=list)


@dataclass(slots=True)
class TurnContext:
    """一次对话的运行时依赖 + 产出（side channel）。"""

    db: Any
    request: TurnRequest
    registry: AgentRegistry = field(default_factory=get_agent_registry)
    retrieval: Any = None
    route_llm: Any = None      # 注入 supervisor 的模型（测试用）
    gen_llm: Any = None        # 注入生成模型（测试用）
    trace: Any = None          # observability TraceContext
    # 子 Agent 各自的数据库会话工厂。**不能共用父会话**：
    # AsyncSession 不是并发安全的，两个子 Agent 同时 commit/rollback 会抛
    # IllegalStateChangeError，而且这类错误只在「两个 @ 同时命中」时出现，最难复现。
    session_factory: Any = None

    # 图节点写、API 层读
    route: Optional[RouteDecision] = None
    drafts: list[SubAgentDraft] = field(default_factory=list)
    results: list[SubAgentResult] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    contributors: list[dict[str, Any]] = field(default_factory=list)
    suggested_actions: list[dict[str, Any]] = field(default_factory=list)
    handoff: Optional[dict[str, Any]] = None
    answer: str = ""
    guardrail: dict[str, Any] = field(default_factory=dict)
    started_at: float = field(default_factory=time.perf_counter)
    need_disclaimer: bool = False

    def emit(self, event: str, data: dict[str, Any]) -> None:
        """发一个流式事件；非流式调用（ainvoke）时静默丢弃。"""
        try:
            writer = get_stream_writer()
            writer({"event": event, "data": data})
        except Exception:  # noqa: BLE001 —— 没有 writer 说明不是流式路径
            pass


def _llm_for(
    ctx: TurnContext, agent: AgentConfig | None = None, *, max_tokens: int | None = None
) -> Any:
    if ctx.gen_llm is not None:
        return ctx.gen_llm
    return get_chat_client(
        temperature=agent.temperature if agent else None,
        model=(agent.model or None) if agent else None,
        max_tokens=max_tokens,
    )


def merge_citations(results: Sequence[SubAgentResult]) -> tuple[list[dict[str, Any]], dict[str, dict[int, int]]]:
    """把多个子 Agent 的引用合并成全局编号，并返回「每个 Agent 的旧→新」映射。

    单 Agent 时映射是恒等，多 Agent 时第二个 Agent 的 [1] 会变成全局的 [k+1]，
    正文里的角标同步改写——否则汇总文本里会出现两个 [1] 指向不同文档。
    """
    merged: list[dict[str, Any]] = []
    remaps: dict[str, dict[int, int]] = {}
    for result in results:
        mapping: dict[int, int] = {}
        for citation in result.citations:
            mapping[int(citation["index"])] = len(merged) + 1
            merged.append({**citation, "index": len(merged) + 1, "agent_code": result.agent.code})
        remaps[result.agent.code] = mapping
    return merged, remaps


def _rewrite_marks(text: str, mapping: dict[int, int]) -> str:
    if not mapping:
        return text

    def repl(match: re.Match[str]) -> str:
        number = int(match.group(1))
        return f"[{mapping[number]}]" if number in mapping else ""

    return re.sub(r"\[(\d{1,2})\]", repl, text)


def _clarify_text(route: RouteDecision) -> str:
    names = "、".join(agent.name for agent in route.agents[:4]) or "相关助手"
    return (
        "为了回答得更准，我想先确认一下您的问题属于哪一类。\n\n"
        "药品用法、禁忌、不良反应可以直接问我；订单退款、物流进度可以 @订单售后；"
        "公司信息、客服流程可以 @客服助手。\n\n"
        f"（当前您可用的助手：{names}）"
    )


class ChatRuntime:
    """把「一次对话」跑成一条事件流。"""

    def __init__(self, registry: AgentRegistry | None = None) -> None:
        self.registry = registry or get_agent_registry()

    # ------------------------------------------------------------------ 图
    def build_graph(self, ctx: TurnContext):
        """构建编排图。

        用闭包持有 ``ctx``（里面是 AsyncSession 等不可序列化依赖），``state`` 只留
        业务字段——M3 加 checkpointer 时不需要动节点签名。
        """
        graph = StateGraph(AgentState)

        # 用显式 async 包装而不是 lambda：LangGraph 靠 iscoroutinefunction 判断
        # 节点是同步还是异步，lambda 返回协程会被当成同步节点（协程永远不被 await）。
        async def route_node(state: AgentState) -> AgentState:
            return await self._route_node(state, ctx)

        async def dispatch_node(state: AgentState) -> AgentState:
            return await self._dispatch_node(state, ctx)

        async def clarify_node(state: AgentState) -> AgentState:
            return await self._clarify_node(state, ctx)

        async def compose_node(state: AgentState) -> AgentState:
            return await self._compose_node(state, ctx)

        async def guardrail_node(state: AgentState) -> AgentState:
            return await self._guardrail_node(state, ctx)

        graph.add_node("route", route_node)
        graph.add_node("dispatch", dispatch_node)
        graph.add_node("clarify", clarify_node)
        graph.add_node("compose", compose_node)
        graph.add_node("guardrail", guardrail_node)

        graph.add_edge(START, "route")
        graph.add_conditional_edges(
            "route",
            lambda state: "clarify" if state.get("route", {}).get("mode") == "clarify" else "dispatch",
            {"clarify": "clarify", "dispatch": "dispatch"},
        )
        graph.add_edge("clarify", "guardrail")
        graph.add_edge("dispatch", "compose")
        graph.add_edge("compose", "guardrail")
        graph.add_edge("guardrail", END)
        return graph.compile()

    # ------------------------------------------------------------------ 节点
    async def _route_node(self, state: AgentState, ctx: TurnContext) -> AgentState:
        request = ctx.request
        primary = await self.registry.get(ctx.db, request.agent_code)
        if primary is None:
            raise RouteError("FORBIDDEN_AGENT", f"未知的 Agent：{request.agent_code}")
        if not primary.allows(request.role):
            raise RouteError("FORBIDDEN_AGENT", f"当前身份无权使用 {primary.name}")

        agents = await self.registry.all(ctx.db)
        decision = await decide_route(
            message=request.message,
            mentions=request.mentions,
            role=request.role,
            registry=agents,
            primary=primary,
            llm=ctx.route_llm,
        )
        ctx.route = decision
        ctx.emit("route", decision.as_event_data())
        return {
            "route": decision.as_event_data(),
            "mentions": request.mentions,
            "role": request.role,
            "primary_code": primary.code,
        }

    async def _dispatch_node(self, state: AgentState, ctx: TurnContext) -> AgentState:
        decision = ctx.route
        assert decision is not None
        request = ctx.request
        timeout = settings.agent_timeout_seconds

        drafts: list[SubAgentDraft] = []
        results: list[SubAgentResult] = []

        async def prepare(agent: AgentConfig) -> SubAgentDraft:
            # 每个子 Agent 一个独立会话：见 TurnContext.session_factory 的注释
            async with self._agent_session(ctx) as adb:
                return await asyncio.wait_for(
                    prepare_subagent(
                        db=adb,
                        agent=agent,
                        message=request.message,
                        role=request.role,
                        user_id=request.user_id,
                        conversation_id=request.conversation_id,
                        product_id=request.product_id,
                        order_id=request.order_id,
                        retrieval=ctx.retrieval,
                        history=request.history,
                        on_event=ctx.emit,
                    ),
                    timeout=timeout,
                )

        for agent in decision.agents:
            ctx.emit("agent", {"code": agent.code, "name": agent.name, "phase": "start"})

        raw = await asyncio.gather(
            *(prepare(agent) for agent in decision.agents), return_exceptions=True
        )
        multi = len(decision.agents) > 1
        for agent, item in zip(decision.agents, raw):
            if isinstance(item, BaseException):
                error = f"{type(item).__name__}: {item}"
                logger.warning("子 Agent %s 准备失败：%s", agent.code, error)
                results.append(
                    SubAgentResult(agent=agent, ok=False, error=error, text="")
                )
                ctx.emit("agent", {"code": agent.code, "name": agent.name, "phase": "done", "ok": False})
                continue
            drafts.append(item)

        # 多 Agent 才需要各自先写一段结论（单 Agent 直接流式生成，省一次往返）
        if multi and drafts:
            generated = await asyncio.gather(
                *(self._generate_with_timeout(draft, ctx) for draft in drafts),
                return_exceptions=True,
            )
            for item in generated:
                if isinstance(item, BaseException):
                    logger.warning("子 Agent 生成失败：%s", item)
                    continue
                results.append(item)
            for draft in drafts:
                result = next((r for r in results if r.agent.code == draft.agent.code), None)
                ctx.emit(
                    "agent",
                    {
                        "code": draft.agent.code,
                        "name": draft.agent.name,
                        "phase": "done",
                        "ok": bool(result and result.ok),
                        "elapsed_ms": result.elapsed_ms if result else 0,
                    },
                )

        ctx.drafts = drafts
        ctx.results = results
        return {"drafts": drafts, "results": results}

    def _agent_session(self, ctx: TurnContext) -> Any:
        if ctx.session_factory is not None:
            return ctx.session_factory()

        from app.core.database import AsyncSessionLocal

        return AsyncSessionLocal()

    async def _generate_with_timeout(self, draft: SubAgentDraft, ctx: TurnContext) -> SubAgentResult:
        return await asyncio.wait_for(
            generate_subagent(draft, llm=_llm_for(ctx, draft.agent)),
            timeout=settings.agent_timeout_seconds,
        )

    async def _clarify_node(self, state: AgentState, ctx: TurnContext) -> AgentState:
        text = _clarify_text(ctx.route)  # type: ignore[arg-type]
        ctx.emit("delta", {"text": text})
        ctx.answer = text
        ctx.contributors = []
        ctx.need_disclaimer = False
        return {"messages": [{"role": "assistant", "content": text}]}

    async def _compose_node(self, state: AgentState, ctx: TurnContext) -> AgentState:
        request = ctx.request

        if ctx.results:  # 多 Agent：合并引用后汇总
            merged, remaps = merge_citations(ctx.results)
            ctx.citations = merged
            for citation in merged:
                ctx.emit("citation", citation)

            blocks = []
            sections: list[str] = []
            for result in ctx.results:
                if not result.ok and not result.text:
                    line = f"**{result.agent.name}**：暂时没能获取信息，请稍后再试。"
                    blocks.append(line)
                    sections.append(line)
                    continue
                text = _rewrite_marks(result.text, remaps.get(result.agent.code, {})).strip()
                blocks.append(f"【{result.agent.name}】{text}")
                sections.append(f"**{result.agent.name}**：{text}")
                ctx.contributors.append(
                    {
                        "code": result.agent.code,
                        "name": result.agent.name,
                        "summary": " ".join(result.text.split())[:120],
                    }
                )
            ctx.need_disclaimer = any(result.needs_disclaimer for result in ctx.results)

            if settings.chat_llm_synthesis and ctx.results:
                # 可选的「模型融合」：读起来更连贯，但要多一次完整生成（实测 +3~5s），
                # 而且模型有可能把 A 的结论说成 B 的。默认关闭。
                messages = [
                    {"role": "system", "content": "你是专业的医药电商客服汇总助手。"},
                    {
                        "role": "user",
                        "content": SYNTHESIS_PROMPT.replace("{question}", request.message).replace(
                            "{answers}", "\n\n".join(blocks)
                        ),
                    },
                ]
                ctx.answer = await self._stream_answer(
                    messages, ctx, valid={c["index"] for c in merged}, max_tokens=700
                )
                return {
                    "messages": messages,
                    "citations": merged,
                    "contributors": ctx.contributors,
                }

            # 默认：确定性合并。来源由代码拼、不经过模型，既不会张冠李戴，
            # 也不需要多等一次完整生成——多 Agent 的体验瓶颈本来就在「等两路都答完」。
            names = "、".join(result.agent.name for result in ctx.results if result.ok) or "以上助手"
            answer = "\n\n".join(sections)
            answer += f"\n\n> 以上结论分别来自 {names}；涉及用药与售后两件事时，请以各自主管助手的答复为准。"
            ctx.emit("delta", {"text": answer})
            ctx.answer = answer
            return {"messages": [], "citations": merged, "contributors": ctx.contributors}

        draft = ctx.drafts[0] if ctx.drafts else None
        if draft is None:
            text = refusal_text("no_kb")
            ctx.emit("delta", {"text": text})
            ctx.answer = text
            return {"messages": [{"role": "assistant", "content": text}]}

        for citation in draft.citations if not draft.fallback_text else []:
            ctx.emit("citation", citation)
        ctx.citations = [] if draft.fallback_text else draft.citations
        ctx.need_disclaimer = draft.needs_disclaimer or needs_disclaimer(draft.agent)
        ctx.contributors = [
            {"code": draft.agent.code, "name": draft.agent.name, "summary": ""}
        ]

        if draft.fallback_text:  # 无资料可依据：直接给拒答话术，不调模型
            ctx.emit("delta", {"text": draft.fallback_text})
            ctx.answer = draft.fallback_text
            ctx.need_disclaimer = False
        else:
            ctx.answer = await self._stream_answer(
                draft.messages, ctx, valid={c["index"] for c in draft.citations}
            )
        ctx.emit(
            "agent",
            {
                "code": draft.agent.code,
                "name": draft.agent.name,
                "phase": "done",
                "ok": True,
                "elapsed_ms": int((time.perf_counter() - ctx.started_at) * 1000),
            },
        )
        return {"messages": draft.messages, "citations": draft.citations}

    async def _stream_answer(
        self,
        messages: list[dict[str, str]],
        ctx: TurnContext,
        *,
        valid: set[int],
        max_tokens: int | None = None,
    ) -> str:
        """流式生成 + 边发边过滤角标（见 app/guardrail/citations.py）。"""
        guard = CitationStreamFilter(valid)
        pieces: list[str] = []
        try:
            llm = _llm_for(ctx, max_tokens=max_tokens)
            async for chunk in llm.astream(messages):
                text = str(getattr(chunk, "content", "") or "")
                if not text:
                    continue
                pieces.append(text)
                safe = guard.feed(text)
                if safe:
                    ctx.emit("delta", {"text": safe})
        except Exception as exc:  # noqa: BLE001 —— 生成失败也要把已得内容说清楚
            logger.warning("生成失败：%s", exc)
            note = "\n\n（回答生成中断，请重试）"
            if not pieces:
                pieces.append(refusal_text("no_kb"))
            pieces.append(note)
            ctx.emit("delta", {"text": note})

        tail = guard.flush()
        if tail:
            pieces.append(tail)
            ctx.emit("delta", {"text": tail})
        return "".join(pieces)

    async def _guardrail_node(self, state: AgentState, ctx: TurnContext) -> AgentState:
        outcome = finalize(
            ctx.answer, ctx.citations, need_disclaimer=ctx.need_disclaimer
        )
        if "disclaimer_injected" in outcome.flags:
            # 免责声明统一在最后追加：流式已经发出去的内容不能再改，只能往后补
            from app.guardrail.citations import DISCLAIMER

            extra = f"\n\n> {DISCLAIMER}"
            ctx.emit("delta", {"text": extra})
            outcome.text = ctx.answer.rstrip() + extra

        ctx.answer = outcome.text
        ctx.guardrail = {"passed": outcome.passed, "flags": outcome.flags}

        # 转人工：escalate_human 工具（敏感词/模型自决）触发，M3 才真正建工单
        requested_handoff = any(
            call.get("suggested_action")
            for draft in ctx.drafts
            for call in draft.tool_calls
        )
        if requested_handoff and not ctx.suggested_actions:
            ctx.suggested_actions = [{"type": "handoff", "label": "转人工客服"}]
        if requested_handoff and ctx.handoff is None:
            ctx.handoff = {"ticket_id": None, "queue_position": 0, "reason": "建议人工跟进"}
            ctx.emit("handoff", ctx.handoff)

        ctx.emit(
            "done",
            {
                "usage": {"input_tokens": 0, "output_tokens": 0, "cost": 0},
                "latency_ms": int((time.perf_counter() - ctx.started_at) * 1000),
                "citations": outcome.citations,
                "contributors": ctx.contributors,
                "guardrail": ctx.guardrail,
                "suggested_actions": ctx.suggested_actions,
                "replayed": False,
            },
        )
        return {
            "guardrail": ctx.guardrail,
            "citations": outcome.citations,
            "contributors": ctx.contributors,
            "handoff": ctx.handoff,
            "suggested_actions": ctx.suggested_actions,
        }

    # ------------------------------------------------------------------ 入口
    async def run_turn(self, ctx: TurnContext) -> AsyncIterator[SSEEvent]:
        """跑完一轮，逐个吐事件。异常统一转成 ``error`` 事件（不会抛出）。"""
        graph = self.build_graph(ctx)
        state: AgentState = {
            "message": ctx.request.message,
            "mentions": ctx.request.mentions,
            "role": ctx.request.role,
            "primary_code": ctx.request.agent_code,
        }
        try:
            async for payload in graph.astream(state, stream_mode="custom"):
                if not isinstance(payload, dict):
                    continue
                event = str(payload.get("event") or "")
                data = payload.get("data") or {}
                if event:
                    yield SSEEvent(event, data)
        except RouteError as exc:
            logger.info("路由失败：%s", exc.message)
            yield error_event(exc.code, exc.message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("对话运行时异常")
            yield error_event("INTERNAL_ERROR", f"{type(exc).__name__}: {exc}", retryable=True)
            return

        ctx.suggested_actions = list(state.get("suggested_actions") or ctx.suggested_actions)


_runtime = ChatRuntime()


def get_chat_runtime() -> ChatRuntime:
    return _runtime


def reset_chat_runtime() -> None:
    """测试用。"""
    global _runtime
    _runtime = ChatRuntime()
