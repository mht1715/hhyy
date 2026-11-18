"""编排图 + 事件流测试（M2-03 / M2-07）。

这是 M2 的「主干测试」：用替身模型 + 替身检索把一整个对话跑完，
断言事件序列、引用过滤、免责声明、并行与降级。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from app.agent.registry import AgentConfig, AgentRegistry
from app.agent.runtime import ChatRuntime, TurnContext, TurnRequest
from app.agent.sse import SSEEvent
from app.guardrail.citations import DISCLAIMER
from app.rag.base import RetrievedChunk
from app.testing.fakes import FakeLLM, FakeRetrievalService

KB_ID = str(uuid.uuid4())


class _Msg:
    """最小消息替身（只有 ``content``，编排层也只读这个字段）。"""

    def __init__(self, content: str) -> None:
        self.content = content


def _agent(
    code: str,
    *,
    name: str = "",
    kb: tuple[str, ...] = ("kb_drug_manual",),
    tools: tuple[str, ...] = ("kb_search",),
    roles: tuple[str, ...] = ("patient", "admin"),
) -> AgentConfig:
    return AgentConfig(
        code=code,
        name=name or code,
        description=f"{code} 说明",
        kb_codes=list(kb),
        tools=list(tools),
        allowed_roles=list(roles),
    )


DRUG = _agent("drug_consult", name="AI 药师")
ORDER = _agent("order_after_sale", name="订单售后", kb=("kb_after_sale",), tools=("policy_search", "order_lookup"))


class StubRegistry(AgentRegistry):
    """预置缓存的注册表：绕过 DB，直接给定配置。"""

    def __init__(self, agents: list[AgentConfig]) -> None:
        super().__init__()
        self._cache = {agent.code: agent for agent in agents}
        self._loaded_at = time.monotonic()


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class FakeDB:
    """认识三种查询：知识库 code→id、prompt 模板（返回空→用内置模板）。"""

    def __init__(self) -> None:
        self.commits = 0

    async def execute(self, statement):  # noqa: ANN001
        sql = str(statement).lower()
        if "knowledge_bases" in sql:
            return _Result([(uuid.UUID(KB_ID), "kb_drug_manual"), (uuid.UUID(KB_ID), "kb_after_sale")])
        return _Result([])

    async def get(self, model, pk):  # noqa: ANN001
        return None

    async def commit(self) -> None:
        self.commits += 1


def _chunk(*, kb_id: str = KB_ID, section: str = "禁忌", score: float = 0.93) -> RetrievedChunk:
    return RetrievedChunk(
        id=f"c-{section}",
        content="孕妇及哺乳期妇女禁用。",
        score=score,
        kb_id=kb_id,
        doc_id="doc-1",
        doc_title="花红片说明书",
        section=section,
    )


async def _run_events(ctx: TurnContext) -> list[SSEEvent]:
    runtime = ChatRuntime(registry=ctx.registry)
    return [event async for event in runtime.run_turn(ctx)]


@asynccontextmanager
async def _fake_session():
    """子 Agent 会话工厂的替身（每个子 Agent 一个独立会话）。"""
    yield FakeDB()


def _ctx(
    *,
    agents: list[AgentConfig],
    message: str,
    mentions: list[dict] | None = None,
    agent_code: str = "drug_consult",
    route_llm: Any = None,
    gen_llm: Any = None,
    retrieval: Any = None,
    role: str = "patient",
) -> TurnContext:
    return TurnContext(
        db=FakeDB(),
        request=TurnRequest(
            message=message,
            agent_code=agent_code,
            mentions=mentions or [],
            role=role,
        ),
        registry=StubRegistry(agents),
        retrieval=retrieval if retrieval is not None else FakeRetrievalService([_chunk()]),
        route_llm=route_llm,
        gen_llm=gen_llm,
        session_factory=_fake_session,
    )


async def test_single_agent_turn_streams_expected_events():
    """M2-03 验收：mock LLM 下单轮问答跑通，事件顺序正确。"""
    gen = FakeLLM(chunks=["根据说明书，", "孕妇及哺乳期妇女禁用[1]。"])
    ctx = _ctx(agents=[DRUG], message="哺乳期能吃吗", gen_llm=gen)

    events = await _run_events(ctx)
    names = [event.event for event in events]

    assert names[0] == "route"
    assert "agent" in names and "retrieval" in names and "citation" in names
    assert names[-1] == "done"
    assert "delta" in names

    deltas = "".join(event.data["text"] for event in events if event.event == "delta")
    assert "[1]" in deltas
    assert DISCLAIMER in deltas  # 药品类必须带免责声明
    assert events[-1].data["guardrail"]["passed"] is True
    assert ctx.answer.startswith("根据说明书")


async def test_hallucinated_citation_is_filtered_from_stream():
    gen = FakeLLM(chunks=["依据说明书[9]，建议观察。"])
    ctx = _ctx(agents=[DRUG], message="有什么禁忌", gen_llm=gen)

    events = await _run_events(ctx)
    deltas = "".join(event.data["text"] for event in events if event.event == "delta")

    assert "[9]" not in deltas
    assert events[-1].data["citations"] == []


async def test_mention_routes_to_mentioned_agent_without_llm():
    llm = FakeLLM(reply="{}")
    gen = FakeLLM(chunks=["该订单已签收，支持 7 天无理由退货[1]。"])
    retrieval = FakeRetrievalService([_chunk(kb_id=KB_ID)])
    ctx = _ctx(
        agents=[DRUG, ORDER],
        message="@订单售后 这单能退吗",
        mentions=[{"agent_code": "order_after_sale", "name": "订单售后", "offset": 0}],
        route_llm=llm,
        gen_llm=gen,
        retrieval=retrieval,
    )

    events = await _run_events(ctx)
    route = events[0].data
    assert route["mode"] == "mention"
    assert [agent["code"] for agent in route["agents"]] == ["order_after_sale"]
    assert llm.calls == []  # 显式 @ 不花模型路由


async def test_two_agents_run_in_parallel_and_are_attributed():
    """M2-07：两个 @ 总耗时 ≈ max 而非 sum，且各自贡献被标注。"""

    class SlowLLM:
        """每个子 Agent 各睡 0.3s；串行需要 0.6s，并行应 ≈0.3s。"""

        def __init__(self) -> None:
            self.calls = 0

        async def ainvoke(self, messages: Any, **kwargs: Any) -> Any:
            self.calls += 1
            await asyncio.sleep(0.3)
            return _Msg("结论：可以退。")

        async def astream(self, messages: Any, **kwargs: Any):
            yield _Msg("汇总：")

    class _Msg:
        def __init__(self, content: str) -> None:
            self.content = content

    ctx = _ctx(
        agents=[DRUG, ORDER],
        message="@AI药师 @订单售后 这个药能退吗",
        mentions=[
            {"agent_code": "drug_consult", "name": "AI 药师", "offset": 0},
            {"agent_code": "order_after_sale", "name": "订单售后", "offset": 8},
        ],
        gen_llm=SlowLLM(),
        retrieval=FakeRetrievalService([_chunk()]),
    )

    started = time.perf_counter()
    events = await _run_events(ctx)
    elapsed = time.perf_counter() - started

    done = events[-1]
    assert done.event == "done"
    assert {item["code"] for item in done.data["contributors"]} == {"drug_consult", "order_after_sale"}
    # 并行：两路各 0.3s，串行会 ≥0.6s；留一点余量给调度
    assert elapsed < 0.6, f"两个子 Agent 没有并行，耗时 {elapsed:.2f}s"


async def test_one_agent_failure_does_not_break_the_turn():
    class ExplodingLLM:
        def __init__(self) -> None:
            self.calls = 0

        async def ainvoke(self, messages: Any, **kwargs: Any) -> Any:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("第一路挂了")
            return _Msg("结论：可以退。")

        async def astream(self, messages: Any, **kwargs: Any):
            yield _Msg("汇总：")

    ctx = _ctx(
        agents=[DRUG, ORDER],
        message="@AI药师 @订单售后 问个事",
        mentions=[
            {"agent_code": "drug_consult"},
            {"agent_code": "order_after_sale"},
        ],
        gen_llm=ExplodingLLM(),
        retrieval=FakeRetrievalService([_chunk()]),
    )

    events = await _run_events(ctx)
    assert events[-1].event == "done"


async def test_no_hit_returns_refusal_without_calling_llm():
    gen = FakeLLM(chunks=["不该被调用"])
    ctx = _ctx(
        agents=[DRUG],
        message="今天天气怎么样",
        gen_llm=gen,
        retrieval=FakeRetrievalService([], reason="no_hit"),
    )

    events = await _run_events(ctx)
    deltas = "".join(event.data["text"] for event in events if event.event == "delta")

    assert "没有在相关资料里找到" in deltas or "资料中没有" in deltas
    assert gen.calls == []


async def test_sensitive_words_trigger_handoff():
    escalate_agent = _agent(
        "drug_consult", name="AI 药师", tools=("kb_search", "escalate_human")
    )
    gen = FakeLLM(chunks=["建议转人工处理。"])
    ctx = _ctx(agents=[escalate_agent], message="我要投诉你们，要求赔偿", gen_llm=gen)

    events = await _run_events(ctx)
    names = [event.event for event in events]

    assert "handoff" in names
    done = events[-1]
    assert done.data["suggested_actions"][0]["type"] == "handoff"


async def test_unknown_primary_agent_emits_error():
    ctx = _ctx(agents=[DRUG], message="你好", agent_code="ghost", gen_llm=FakeLLM())

    events = await _run_events(ctx)
    assert events[-1].event == "error"
    assert events[-1].data["code"] == "FORBIDDEN_AGENT"
