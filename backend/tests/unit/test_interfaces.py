"""M0-04 验收：六个接口契约成立，且测试替身真的实现它们。

这些用例保证「接口不是摆设」：
- Fake 实现通过 isinstance 检查（结构性子类型）
- 检索替身真的按 kb_ids 过滤（权限参数不会被忽略）
- 上下文编号与工具 schema 形状固定
"""

import pytest

from app.llm.base import LLMClient
from app.memory.base import MemoryItem, MemoryStore
from app.observability.base import TraceSink
from app.rag.base import Reranker, RetrievalResult, RetrievedChunk, Retriever
from app.testing.fakes import (
    FakeLLM,
    FakeMemoryStore,
    FakeReranker,
    FakeRetriever,
    FakeTraceSink,
)
from app.tools.base import (
    _TOOL_REGISTRY,
    ToolSpec,
    build_function_schemas,
    ensure_tool_allowed,
    get_tool,
    register_tool,
)


def test_fakes_satisfy_protocols():
    assert isinstance(FakeLLM(), LLMClient)
    assert isinstance(FakeRetriever(), Retriever)
    assert isinstance(FakeReranker(), Reranker)
    assert isinstance(FakeMemoryStore(), MemoryStore)
    assert isinstance(FakeTraceSink(), TraceSink)


async def test_fake_retriever_respects_kb_scope():
    chunks = [
        RetrievedChunk(id="c1", content="企业介绍", score=0.90, kb_id="kb_public"),
        RetrievedChunk(id="c2", content="内部 SOP", score=0.95, kb_id="kb_internal"),
    ]
    retriever = FakeRetriever(chunks)

    result = await retriever.retrieve("怎么退货", kb_ids=["kb_public"])

    assert [c.kb_id for c in result.chunks] == ["kb_public"]
    assert result.refused is False


async def test_fake_retriever_refuses_when_no_hit():
    result = await FakeRetriever([]).retrieve("今天股价怎么样", kb_ids=["kb_public"])

    assert result.refused is True
    assert result.reason == "no_hit"


async def test_fake_retriever_refuses_on_low_score():
    chunks = [RetrievedChunk(id="c1", content="无关内容", score=0.10, kb_id="kb1")]
    result = await FakeRetriever(chunks, threshold=0.3).retrieve("q", kb_ids=["kb1"])

    assert result.refused is True
    assert result.reason == "low_score"


def test_context_uses_numbered_citations():
    result = RetrievalResult(
        query="哺乳期能吃吗",
        chunks=[
            RetrievedChunk(
                id="c1",
                content="孕妇及哺乳期妇女禁用。",
                score=0.8,
                kb_id="kb_drug",
                doc_title="花红片说明书",
                section="禁忌",
            )
        ],
    )

    context = result.as_context()

    assert "[1] 花红片说明书 · 禁忌" in context
    assert "孕妇及哺乳期妇女禁用" in context


async def test_memory_store_isolated_by_user():
    store = FakeMemoryStore()
    await store.add(MemoryItem(id="m1", user_id="u1", type="fact", content="对青霉素过敏"))

    assert await store.search("u1", "青霉素") != []
    assert await store.search("u2", "青霉素") == []
    assert await store.delete("u2", "m1") is False
    assert await store.delete("u1", "m1") is True


def test_trace_sink_records_spans_and_scores():
    sink = FakeTraceSink()

    with sink.trace("chat.turn", user_id="u1", session_id="c1", tags=["drug"]) as ctx:
        with sink.span(ctx, "retrieval"):
            pass
        sink.score(ctx, "user_feedback", 1.0)

    assert sink.spans == [(ctx.trace_id, "retrieval")]
    assert sink.scores == [(ctx.trace_id, "user_feedback", 1.0)]
    assert sink.traces[0].session_id == "c1"


def test_trace_sink_propagates_business_error():
    """埋点不能吞掉业务异常，也不能让 contextmanager 二次 yield。"""
    sink = FakeTraceSink()

    with pytest.raises(ValueError, match="boom"):
        with sink.trace("x") as ctx:
            raise ValueError("boom")

    assert sink.errors == ["boom"]
    assert ctx.trace_id


@pytest.fixture
def clean_registry():
    snapshot = dict(_TOOL_REGISTRY)
    try:
        yield _TOOL_REGISTRY
    finally:
        _TOOL_REGISTRY.clear()
        _TOOL_REGISTRY.update(snapshot)


def test_tool_registry_and_function_schema(clean_registry):
    spec = ToolSpec(
        name="demo_tool",
        description="演示工具",
        args_schema={"type": "object", "properties": {"x": {"type": "string"}}},
    )

    @register_tool(spec)
    async def demo_tool(x: str) -> str:
        return x

    assert get_tool("demo_tool").spec.name == "demo_tool"

    schema = build_function_schemas(["demo_tool"])[0]
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "demo_tool"
    assert schema["function"]["parameters"]["properties"]["x"]["type"] == "string"

    with pytest.raises(ValueError):
        register_tool(spec)(demo_tool)


def test_tool_role_gate(clean_registry):
    spec = ToolSpec(name="admin_only_tool", description="仅管理员", required_roles=("admin",))

    @register_tool(spec)
    async def admin_only_tool() -> str:
        return "ok"

    ensure_tool_allowed("admin_only_tool", "admin")
    with pytest.raises(PermissionError):
        ensure_tool_allowed("admin_only_tool", "patient")
