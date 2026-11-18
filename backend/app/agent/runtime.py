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

from app.agent.checkpointer import thread_config
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
from app.memory.inject import InjectedMemory, load_memory
from app.models.agent import Conversation
from app.rag.citation import refusal_text
from app.services import handoff as handoff_service

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
    # 更早对话的滚动摘要（M3-02）：和 history 一起拼进 prompt
    summary: str = ""


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
    # M3-01：由 API 层显式传入（测试不传就不会去连 PG）
    checkpointer: Any = None
    # M3-03~06：已加载的长期记忆（API 层或路由节点填）
    memory: Optional[InjectedMemory] = None
    # 会话状态（bot_active / handoff_pending / human_active / closed）
    status: str = "bot_active"
    # API 层预检到的敏感场景：进流前就已建好工单，保证「3 秒内坐席可见」
    pre_handoff: Optional[dict[str, Any]] = None
    # 指代消解后的「当前问题」：路由 / 检索 / 子 Agent 都用它，用户原话仍按 request.message 落库
    query: str = ""

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
    # M4-06：合规改写命中项（流式与非流式两条路径都往这里记）
    compliance_hits: list[dict[str, Any]] = field(default_factory=list)
    # M4-06：用户这句话里的高危症状（非空时回答前会插「立即就医」）
    high_risk: list[str] = field(default_factory=list)
    # M4-05：本轮实际命中的 prompt 版本（code@vN）
    prompt_version: str = ""
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
    def build_graph(self, ctx: TurnContext, *, checkpointer: Any = None):
        """构建并编译编排图。

        用闭包持有 ``ctx``（里面是 AsyncSession 等不可序列化依赖），``state`` 只留
        业务字段——checkpointer 只序列化 ``AgentState``，所以它拿到的东西都是纯数据。

        ``checkpointer`` 由 API 层传入：测试不传就编译成无持久化的图，
        不会去连 Postgres（单测不该依赖外部服务）。
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
        return graph.compile(checkpointer=checkpointer)

    # ------------------------------------------------------------------ 节点
    async def _route_node(self, state: AgentState, ctx: TurnContext) -> AgentState:
        request = ctx.request
        primary = await self.registry.get(ctx.db, request.agent_code)
        if primary is None:
            raise RouteError("FORBIDDEN_AGENT", f"未知的 Agent：{request.agent_code}")
        if not primary.allows(request.role):
            raise RouteError("FORBIDDEN_AGENT", f"当前身份无权使用 {primary.name}")

        agents = await self.registry.all(ctx.db)

        # 指代消解：「这个药怎么购买」这种句子先补全成自包含的问题。
        # 注意**只用于检索和子 Agent 的当前问题**，路由仍用原话 + 历史：
        # 实测改写句会让 supervisor 的置信度反而略降（0.62 → 0.55），
        # 用它去路由会把「本来能答」的问题变成澄清。
        from app.agent.contextual import needs_contextualize, rewrite_query

        query = request.message
        if ctx.route_llm is not None and needs_contextualize(request.message, request.history):
            rewritten = await rewrite_query(request.message, request.history, ctx.route_llm)
            if rewritten:
                query = rewritten
        ctx.query = query

        decision = await decide_route(
            message=request.message,
            mentions=request.mentions,
            role=request.role,
            registry=agents,
            primary=primary,
            llm=ctx.route_llm,
            # 路由也要看上下文：否则「这个药怎么购买」这种指代句会被判成「指向不明确」→ clarify
            history=request.history,
        )
        ctx.route = decision
        route_payload = decision.as_event_data()
        if query != request.message:
            # 让前端 DEV 面板能看到「检索实际用的查询」，排查上下文问题不用猜
            route_payload["rewritten"] = query
        ctx.emit("route", route_payload)

        # 长期记忆：只加载一次，注入给所有子 Agent（并行时各查一次既慢又可能不一致）
        if ctx.memory is None and request.user_id and settings.memory_enabled:
            from app.memory.semantic import get_semantic_memory

            ctx.memory = await load_memory(
                ctx.db,
                user_id=request.user_id,
                query=ctx.query or request.message,
                limit=settings.memory_inject_limit,
                semantic=get_semantic_memory(),
            )
        if ctx.memory is not None and ctx.memory.enabled:
            ctx.emit("memory", ctx.memory.as_event())

        # 敏感场景的工单在进流之前就建好了（API 层预检），这里只负责告知前端
        if ctx.pre_handoff:
            ctx.handoff = ctx.pre_handoff
            ctx.status = "handoff_pending"
            if ctx.pre_handoff.get("status") == "assigned":
                ctx.status = "human_active"
            ctx.emit("handoff", ctx.pre_handoff)

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
                        message=ctx.query or request.message,
                        role=request.role,
                        user_id=request.user_id,
                        conversation_id=request.conversation_id,
                        product_id=request.product_id,
                        order_id=request.order_id,
                        retrieval=ctx.retrieval,
                        history=request.history,
                        summary=request.summary,
                        memory_block=ctx.memory.block if ctx.memory else "",
                        memory_items=ctx.memory.items if ctx.memory else None,
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
            if not ctx.prompt_version and getattr(item, "prompt_version", ""):
                ctx.prompt_version = item.prompt_version

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
        # 只把「给下一轮/给排障看」的最小信息放进 state（drafts/results 是对象，
        # 进 checkpointer 要么依赖未注册的类型、要么把 AsyncSession 一起拖进去）
        return {
            "agents": [
                {"code": draft.agent.code, "name": draft.agent.name} for draft in drafts
            ]
        }

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

        # M4-06：用户描述了急症 → 任何药品建议都要让位给「立即就医」。
        # 这段话必须在生成之前发出去，等回答写完再补就晚了。
        from app.guardrail.compliance import (
            EMERGENCY_NOTICE,
            apply_emergency_notice,
            detect_high_risk,
            rewrite_claims,
        )

        ctx.high_risk = detect_high_risk(request.message)
        if ctx.high_risk:
            ctx.emit("delta", {"text": f"{EMERGENCY_NOTICE}\n\n"})

        def clean(text: str) -> str:
            """非流式文本统一过合规改写（流式路径在 _stream_answer 里边流边改）。"""
            outcome = rewrite_claims(text)
            ctx.compliance_hits.extend(hit.as_dict() for hit in outcome.hits)
            return outcome.text

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
                    "messages": [{"role": "assistant", "content": ctx.answer}],
                    "citations": merged,
                    "contributors": ctx.contributors,
                }

            # 默认：确定性合并。来源由代码拼、不经过模型，既不会张冠李戴，
            # 也不需要多等一次完整生成——多 Agent 的体验瓶颈本来就在「等两路都答完」。
            names = "、".join(result.agent.name for result in ctx.results if result.ok) or "以上助手"
            answer = "\n\n".join(sections)
            answer += f"\n\n> 以上结论分别来自 {names}；涉及用药与售后两件事时，请以各自主管助手的答复为准。"
            answer = clean(answer)
            ctx.emit("delta", {"text": answer})
            ctx.answer = answer
            return {
                "messages": [{"role": "assistant", "content": answer}],
                "citations": merged,
                "contributors": ctx.contributors,
            }

        draft = ctx.drafts[0] if ctx.drafts else None
        if draft is None:
            text = clean(refusal_text("no_kb"))
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
            text = clean(draft.fallback_text)
            ctx.emit("delta", {"text": text})
            ctx.answer = text
            ctx.need_disclaimer = False
        else:
            ctx.answer = await self._stream_answer(
                draft.messages, ctx, valid={c["index"] for c in draft.citations}
            )
        if ctx.high_risk:
            # 提示已经在最前面发过，这里只是让「落库/治理」看到和用户一样的内容
            ctx.answer = apply_emergency_notice(ctx.answer)
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
        return {
            "messages": [{"role": "assistant", "content": ctx.answer}],
            "citations": draft.citations,
        }

    async def _stream_answer(
        self,
        messages: list[dict[str, str]],
        ctx: TurnContext,
        *,
        valid: set[int],
        max_tokens: int | None = None,
    ) -> str:
        """流式生成 + 边发边过滤（引用角标 + 医药合规词），见 app/guardrail/。"""
        from app.guardrail.compliance import ComplianceStreamFilter

        guard = CitationStreamFilter(valid)
        compliance = ComplianceStreamFilter()
        pieces: list[str] = []

        def pump(raw: str) -> None:
            """先过引用闸门、再过合规闸门；只把最终要发出去的文本收集起来。

            ``pieces`` 必须是**过滤后**的文本：它会被写回 ``messages.content``，
            如果收集原文，用户看到的和库里存的就不是同一句话了。
            """
            safe = compliance.feed(guard.feed(raw))
            if safe:
                pieces.append(safe)
                ctx.emit("delta", {"text": safe})

        try:
            from app.observability.tracing import get_trace_sink

            llm = _llm_for(ctx, max_tokens=max_tokens)
            async for chunk in llm.astream(
                messages, config={"callbacks": get_trace_sink().callbacks()}
            ):
                text = str(getattr(chunk, "content", "") or "")
                if not text:
                    continue
                pump(text)
        except Exception as exc:  # noqa: BLE001 —— 生成失败也要把已得内容说清楚
            logger.warning("生成失败：%s", exc)
            note = "\n\n（回答生成中断，请重试）"
            if not pieces:
                pieces.append(refusal_text("no_kb"))
            pieces.append(note)
            ctx.emit("delta", {"text": note})

        pump(guard.flush())
        tail = compliance.flush()
        if tail:
            pieces.append(tail)
            ctx.emit("delta", {"text": tail})
        ctx.compliance_hits.extend(hit.as_dict() for hit in compliance.hits)
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

        # M4-06：②④⑤ 三层（引用存在性 / 批准文号 / 免责声明）+ 合规改写结果合并成一份报告。
        # 流式路径的违规词已在 _stream_answer 里改掉，这里只做「事后审计 + 记账」。
        from app.guardrail.validators import validate_output

        report = validate_output(
            ctx.answer, citations=outcome.citations, need_disclaimer=ctx.need_disclaimer
        )
        flags = list(outcome.flags)
        if ctx.compliance_hits:
            flags.append("compliance_rewritten")
        if ctx.high_risk:
            flags.append("high_risk_notice")
        flags.extend(report.flags)
        violations = list(ctx.compliance_hits) + [item.as_dict() for item in report.violations]

        ctx.guardrail = {
            "passed": outcome.passed and report.passed,
            "flags": sorted(set(flags)),
            "violations": violations,
            "high_risk": list(ctx.high_risk),
            "prompt_version": ctx.prompt_version,
        }

        # 合规命中要能在 Langfuse 里按类型聚合（PRD FR8.6）
        if violations:
            try:
                from app.observability.tracing import get_trace_sink

                category = str(violations[0].get("category") or violations[0].get("kind") or "other")
                get_trace_sink().score(
                    ctx.trace,
                    "guardrail_violation",
                    category,
                    comment=f"{len(violations)} 处：{category}",
                )
            except Exception:  # noqa: BLE001 —— 打分失败不影响回答
                logger.debug("guardrail 打分失败", exc_info=True)

        # 转人工：模型调了 escalate_human（敏感词也会走到这里）→ 真正建工单。
        # 敏感场景的更早期路径在 API 层预检（ctx.pre_handoff），那条路径能保证
        # 「用户刚说完投诉、坐席端 1 秒内就能看到」，不用等模型写完回答。
        requested_handoff = any(
            call.get("suggested_action")
            for draft in ctx.drafts
            for call in draft.tool_calls
        )
        if requested_handoff and not ctx.suggested_actions:
            ctx.suggested_actions = [{"type": "handoff", "label": "转人工客服"}]
        if requested_handoff and ctx.handoff is None:
            ctx.handoff = await self._create_handoff(
                ctx, trigger="agent_tool", reason="助手请求人工跟进"
            )
            if ctx.handoff:
                ctx.emit("handoff", ctx.handoff)

        # 「建议转人工」两档（连续拒答 / 连续负面情绪）：只给按钮，不替用户建单
        if ctx.handoff is None:
            suggestion = handoff_service.suggest_trigger(
                [
                    item.get("content", "")
                    for item in ctx.request.history
                    if item.get("role") == "user"
                ]
                + [ctx.request.message],
                [
                    item.get("content", "")
                    for item in ctx.request.history
                    if item.get("role") == "assistant"
                ]
                + [ctx.answer],
            )
            if suggestion:
                label = handoff_service.TRIGGER_LABELS.get(suggestion, "转人工客服")
                ctx.suggested_actions = [
                    {"type": "handoff", "label": "转人工客服", "reason": label}
                ]

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
                "status": ctx.status,
                "ticket": ctx.handoff,
                "silenced": False,
                "memory_used": len(ctx.memory.items) if ctx.memory else 0,
            },
        )
        return {
            "guardrail": ctx.guardrail,
            "citations": outcome.citations,
            "contributors": ctx.contributors,
            "handoff": ctx.handoff,
            "suggested_actions": ctx.suggested_actions,
        }

    async def _create_handoff(
        self,
        ctx: TurnContext,
        *,
        trigger: str,
        reason: str,
        risk_flags: Optional[list[str]] = None,
    ) -> Optional[dict[str, Any]]:
        """建单并**立刻提交**。

        为什么在流里 commit：坐席工作台是另一个请求在看这张表，不提交就看不到——
        否则「3 秒内出现待接入」这条验收永远过不了（回答可能还要再写 3 秒）。
        这里的 session 是流式端点自己开的那个，提交不会影响别的请求。
        """
        conversation = None
        if ctx.request.conversation_id:
            conversation = await ctx.db.get(Conversation, ctx.request.conversation_id)
        if conversation is None:
            # 没有真实会话（单测 / 匿名调试）：只发意图，不建单
            return {
                "ticket_id": None,
                "queue_position": 0,
                "queue_expires_in": 0,
                "reason": reason,
                "trigger": trigger,
                "status": "queued",
            }
        try:
            summary = handoff_service.build_summary(
                conversation,
                self._summary_messages(ctx),
                risk_flags=risk_flags or [],
                trigger=trigger,
                reason=reason,
            )
            ticket, _created = await handoff_service.request_handoff(
                ctx.db,
                conversation=conversation,
                user_id=ctx.request.user_id,
                reason=reason,
                trigger=trigger,
                risk_flags=risk_flags,
                summary=summary,
            )
            await ctx.db.commit()
        except Exception as exc:  # noqa: BLE001 —— 建单失败不该让整轮回答失败
            logger.warning("创建转人工工单失败：%s", exc)
            await ctx.db.rollback()
            return None

        ctx.status = (
            "human_active" if ticket.status == "assigned" else "handoff_pending"
        )
        return handoff_service.ticket_payload(ticket)

    def _summary_messages(self, ctx: TurnContext) -> list[Any]:
        """把 history + 本轮消息包成 ``build_summary`` 认识的形状。"""
        from types import SimpleNamespace

        rows: list[Any] = [
            SimpleNamespace(
                role=item.get("role", "user"),
                content=str(item.get("content") or ""),
                citations=[],
                tool_calls=[],
            )
            for item in ctx.request.history
            if item.get("content")
        ]
        rows.append(
            SimpleNamespace(
                role="user",
                content=ctx.request.message,
                citations=[],
                tool_calls=[],
            )
        )
        rows.append(
            SimpleNamespace(
                role="assistant",
                content=ctx.answer,
                citations=ctx.citations,
                tool_calls=[call for draft in ctx.drafts for call in draft.tool_calls],
            )
        )
        return rows

    # ------------------------------------------------------------------ 入口
    async def run_turn(self, ctx: TurnContext) -> AsyncIterator[SSEEvent]:
        """跑完一轮，逐个吐事件。异常统一转成 ``error`` 事件（不会抛出）。

        ``durability="exit"``：每轮只在结束时写一次 checkpoint。默认策略是每个
        节点都写一次（一轮 5 次），对「按会话恢复」这个目标没有额外价值，却让
        checkpointer 表随对话量线性膨胀。
        """
        checkpointer = ctx.checkpointer
        graph = self.build_graph(ctx, checkpointer=checkpointer)
        state: AgentState = {
            "message": ctx.request.message,
            "mentions": ctx.request.mentions,
            "role": ctx.request.role,
            "primary_code": ctx.request.agent_code,
            "messages": [{"role": "user", "content": ctx.request.message}],
        }
        config = (
            thread_config(ctx.request.conversation_id)
            if checkpointer is not None and ctx.request.conversation_id
            else None
        )
        try:
            stream = graph.astream(
                state,
                config,
                stream_mode="custom",
                durability="exit" if config is not None else None,
            )
            async for payload in stream:
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
