"""编排层的 M3 接线测试：记忆注入 + 工单落库 + 预检转人工。

M2 的主干测试在 ``test_agent_runtime.py``；这里只验证 M3 新加的三条线，
用替身 DB 而不是真库，保持单测零外部依赖。
"""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

from app.agent.registry import AgentConfig, AgentRegistry
from app.agent.runtime import ChatRuntime, TurnContext, TurnRequest
from app.memory.base import MemoryItem
from app.memory.inject import InjectedMemory, render_block
from app.models.agent import ConversationStatus
from app.models.handoff import HandoffTicket
from app.rag.base import RetrievedChunk
from app.testing.fakes import FakeLLM, FakeRetrievalService

KB_ID = str(uuid.uuid4())


class _Rows:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def scalar_one(self):
        return self._rows[0] if self._rows else 0

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class FakeDB:
    """够用的会话替身：知识库 code→id、工单查询、会话读取。"""

    def __init__(self, conversation: SimpleNamespace) -> None:
        self.conversation = conversation
        self.ticket: Any = None
        self.added: list = []
        self.commits = 0
        self.flushes = 0

    async def execute(self, statement):  # noqa: ANN001
        sql = str(statement).lower()
        if "knowledge_bases" in sql:
            return _Rows([(uuid.UUID(KB_ID), "kb_drug_manual")])
        if "count(" in sql:
            return _Rows([0])
        if "handoff_tickets" in sql:
            return _Rows([self.ticket] if self.ticket is not None else [])
        return _Rows([])

    async def get(self, model, pk):  # noqa: ANN001
        return self.conversation

    async def flush(self) -> None:
        self.flushes += 1

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        pass

    def add(self, obj) -> None:  # noqa: ANN001
        self.added.append(obj)
        if isinstance(obj, HandoffTicket):
            self.ticket = obj


class StubRegistry(AgentRegistry):
    def __init__(self, agents: list[AgentConfig]) -> None:
        super().__init__()
        self._cache = {agent.code: agent for agent in agents}
        # 必须是「刚刚加载」的时间戳：0 会被判为缓存过期而去查替身 DB（结果为空）
        self._loaded_at = time.monotonic()


@asynccontextmanager
async def _session_factory(db: Any):
    """子 Agent 会话工厂的替身：直接复用同一个 FakeDB（工具要查知识库 code）。"""
    yield db


def _agent(tools: tuple[str, ...] = ("kb_search", "escalate_human")) -> AgentConfig:
    return AgentConfig(
        code="drug_consult",
        name="AI 药师",
        description="药品咨询",
        kb_codes=["kb_drug_manual"],
        tools=list(tools),
        allowed_roles=["patient", "admin"],
    )


def _ctx(*, message: str, db: FakeDB, memory: InjectedMemory | None = None) -> TurnContext:
    return TurnContext(
        db=db,
        request=TurnRequest(
            message=message,
            agent_code="drug_consult",
            role="patient",
            user_id=uuid.uuid4(),
            conversation_id=db.conversation.id,
        ),
        registry=StubRegistry([_agent()]),
        retrieval=FakeRetrievalService(
            [
                RetrievedChunk(
                    id="c1",
                    content="孕妇及哺乳期妇女禁用。",
                    score=0.93,
                    kb_id=KB_ID,
                    doc_id="doc-1",
                    doc_title="花红片说明书",
                )
            ]
        ),
        gen_llm=FakeLLM(chunks=["根据说明书，孕妇禁用[1]。"]),
        session_factory=lambda: _session_factory(db),
        memory=memory,
    )


def _conversation() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        status=ConversationStatus.BOT_ACTIVE.value,
        title="花红片怎么吃",
    )


async def test_sensitive_message_creates_real_ticket():
    """M3-08：模型调 escalate_human → 真正落一张工单，会话进入排队。"""
    conversation = _conversation()
    db = FakeDB(conversation)
    ctx = _ctx(message="我要投诉，吃了不舒服", db=db)

    events = [event async for event in ChatRuntime(registry=ctx.registry).run_turn(ctx)]
    handoff_events = [event for event in events if event.event == "handoff"]

    assert handoff_events, "应当发出 handoff 事件"
    payload = handoff_events[0].data
    assert payload["ticket_id"], "手上有真实工单 id"
    assert payload["trigger"] == "agent_tool"
    assert conversation.status == ConversationStatus.HANDOFF_PENDING.value
    assert db.ticket is not None and db.ticket.status == "queued"

    done = events[-1]
    assert done.event == "done"
    assert done.data["status"] == "handoff_pending"
    assert done.data["ticket"]["ticket_id"] == payload["ticket_id"]


async def test_preflight_handoff_is_announced_before_answer():
    """API 层预检的工单：进流就告知前端，不必等回答写完。"""
    conversation = _conversation()
    conversation.status = ConversationStatus.HANDOFF_PENDING.value
    db = FakeDB(conversation)
    ctx = _ctx(message="我要投诉", db=db)
    ctx.pre_handoff = {
        "ticket_id": "t-1",
        "queue_position": 1,
        "queue_expires_in": 90,
        "reason": "敏感场景，立即转人工",
        "trigger": "sensitive",
        "status": "queued",
    }

    events = [event async for event in ChatRuntime(registry=ctx.registry).run_turn(ctx)]
    names = [event.event for event in events]
    assert names.index("handoff") < names.index("delta")
    assert events[-1].data["status"] == "handoff_pending"


async def test_memory_is_injected_into_prompt():
    """M3-06：记忆块进 system prompt，并带上「您上次提到」的口径。"""
    conversation = _conversation()
    db = FakeDB(conversation)
    items = [MemoryItem(id="m1", user_id="u1", type="risk", content="孕早期")]
    memory = InjectedMemory(items=items, block=render_block(items), enabled=True)
    ctx = _ctx(message="这个药能吃吗", db=db, memory=memory)

    events = [event async for event in ChatRuntime(registry=ctx.registry).run_turn(ctx)]
    memory_events = [event for event in events if event.event == "memory"]
    assert memory_events and memory_events[0].data["items"][0]["content"] == "孕早期"

    sent = ctx.gen_llm.calls[0]["messages"]
    system_prompt = sent[0]["content"]
    assert "孕早期" in system_prompt
    assert "您上次提到" in system_prompt
    assert events[-1].data["memory_used"] == 1


async def test_refusal_streak_suggests_handoff_without_ticket():
    """连续拒答只建议不建单（PRD FR5.1）。"""
    from app.rag.citation import refusal_text

    conversation = _conversation()
    db = FakeDB(conversation)
    ctx = _ctx(message="这个问题你们能解决吗", db=db)
    ctx.request.history = [
        {"role": "user", "content": "问题一"},
        {"role": "assistant", "content": refusal_text("no_hit")},
    ]
    # 本轮也拒答：把检索替身换成空结果
    from app.testing.fakes import FakeRetrievalService as FRS

    ctx.retrieval = FRS([], reason="no_hit")

    events = [event async for event in ChatRuntime(registry=ctx.registry).run_turn(ctx)]
    done = events[-1]
    assert done.data["suggested_actions"][0]["type"] == "handoff"
    assert done.data["ticket"] is None
    assert not [event for event in events if event.event == "handoff"]
    assert conversation.status == ConversationStatus.BOT_ACTIVE.value
