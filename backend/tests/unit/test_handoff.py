"""转人工测试（M3-08 / M3-09）：5 类触发、状态机、交接摘要。"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.models.agent import ConversationStatus
from app.models.handoff import HandoffTicket, HandoffTrigger, TicketStatus
from app.services import handoff as svc


class _Scalar:
    def __init__(self, value) -> None:  # noqa: ANN001
        self._value = value

    def scalar_one(self) -> int:
        return self._value

    def scalar_one_or_none(self):  # noqa: ANN201
        return self._value


class FakeDB:
    """只实现状态机用到的那几个动作。"""

    def __init__(self, conversation=None, ticket=None) -> None:  # noqa: ANN001
        self.conversation = conversation
        self.ticket = ticket
        self.added: list = []
        self.flushed = 0

    async def get(self, model, pk):  # noqa: ANN001
        return self.conversation

    async def execute(self, statement):  # noqa: ANN001
        sql = str(statement).lower()
        if "count(" in sql:
            return _Scalar(0)
        return _Scalar(self.ticket)

    async def flush(self) -> None:
        self.flushed += 1

    def add(self, obj) -> None:  # noqa: ANN001
        self.added.append(obj)
        if isinstance(obj, HandoffTicket):
            self.ticket = obj


def _conversation() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), status=ConversationStatus.BOT_ACTIVE.value, title="花红片怎么吃")


def _ticket(status: str = TicketStatus.QUEUED.value, *, age: int = 0) -> HandoffTicket:
    ticket = HandoffTicket(
        id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        status=status,
        queue_position=2,
        trigger=HandoffTrigger.SENSITIVE.value,
        risk_flags=["投诉"],
        summary={},
        reason="投诉",
    )
    ticket.created_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=age)
    return ticket


def _msg(role: str, content: str, *, citations=None, tool_calls=None) -> SimpleNamespace:  # noqa: ANN001
    return SimpleNamespace(
        role=role,
        content=content,
        citations=citations or [],
        tool_calls=tool_calls or [],
    )


# --------------------------------------------------------------------------- 触发规则
def test_detect_sensitive_returns_group_flags():
    hit, flags = svc.detect_sensitive("我要投诉，还要赔偿")
    assert hit is True
    assert set(flags) == {"投诉", "赔偿"}

    miss, empty = svc.detect_sensitive("花红片怎么吃")
    assert miss is False and empty == []


def test_detect_emotion_and_refusal():
    assert svc.detect_emotion("太差了，我很失望") is True
    assert svc.detect_emotion("谢谢") is False
    from app.rag.citation import refusal_text

    assert svc.is_refusal(refusal_text("no_hit")) is True
    assert svc.is_refusal("建议您咨询药师") is False


def test_suggest_trigger_covers_refusal_and_emotion():
    from app.rag.citation import refusal_text

    refusal = refusal_text("no_hit")
    assert svc.suggest_trigger(["问题一", "问题二"], [refusal, refusal]) == "refusal"
    assert svc.suggest_trigger(["太差了", "垃圾服务"], ["好的", "抱歉"]) == "emotion"
    assert svc.suggest_trigger(["花红片怎么吃"], ["一次两片"]) is None


# --------------------------------------------------------------------------- 状态机
async def test_request_handoff_creates_ticket_and_moves_conversation():
    conversation = _conversation()
    db = FakeDB(conversation)

    ticket, created = await svc.request_handoff(
        db,
        conversation=conversation,
        user_id=uuid.uuid4(),
        reason="用户请求转人工",
        trigger=HandoffTrigger.EXPLICIT.value,
    )
    assert created is True and ticket.status == TicketStatus.QUEUED.value
    assert ticket.queue_position == 1
    assert conversation.status == ConversationStatus.HANDOFF_PENDING.value


async def test_request_handoff_is_idempotent_per_conversation():
    conversation = _conversation()
    existing = _ticket()
    existing.conversation_id = conversation.id
    db = FakeDB(conversation, ticket=existing)

    ticket, created = await svc.request_handoff(
        db,
        conversation=conversation,
        user_id=uuid.uuid4(),
        reason="再来一次",
        trigger=HandoffTrigger.EXPLICIT.value,
    )
    assert created is False and ticket is existing
    assert conversation.status == ConversationStatus.HANDOFF_PENDING.value


async def test_accept_then_resolve_happy_path():
    conversation = _conversation()
    ticket = _ticket()
    ticket.conversation_id = conversation.id
    db = FakeDB(conversation, ticket=ticket)
    agent = uuid.uuid4()

    await svc.accept_ticket(db, ticket, agent)
    assert ticket.status == TicketStatus.ASSIGNED.value
    assert ticket.accepted_at is not None and ticket.queue_position == 0
    assert conversation.status == ConversationStatus.HUMAN_ACTIVE.value

    await svc.resolve_ticket(db, ticket, tags=["已解决"])
    assert ticket.status == TicketStatus.RESOLVED.value
    assert ticket.summary["tags"] == ["已解决"]
    # 坐席结束 ≠ 会话结束：AI 接回来，用户还能继续问、也能再次转人工
    assert conversation.status == ConversationStatus.BOT_ACTIVE.value


async def test_illegal_transitions_are_rejected():
    ticket = _ticket(status=TicketStatus.RESOLVED.value)
    db = FakeDB(_conversation(), ticket=ticket)

    with pytest.raises(svc.InvalidTransition):
        await svc.accept_ticket(db, ticket, uuid.uuid4())
    with pytest.raises(svc.InvalidTransition):
        await svc.resolve_ticket(db, ticket)


async def test_mark_offline_is_idempotent_but_rejects_resolved():
    conversation = _conversation()
    ticket = _ticket()
    ticket.conversation_id = conversation.id
    db = FakeDB(conversation, ticket=ticket)

    await svc.mark_offline(db, ticket, name="张三", contact="138****1111", demand="希望回电")
    assert ticket.status == TicketStatus.OFFLINE.value
    assert ticket.summary["offline"]["demand"] == "希望回电"
    assert conversation.status == ConversationStatus.CLOSED.value

    # 重复提交留言：只更新内容，不报状态错
    await svc.mark_offline(db, ticket, name="张三", contact="138****1111", demand="改成明天联系")
    assert ticket.summary["offline"]["demand"] == "改成明天联系"

    resolved = _ticket(status=TicketStatus.RESOLVED.value)
    with pytest.raises(svc.InvalidTransition):
        await svc.mark_offline(FakeDB(conversation), resolved, name="a", contact="b", demand="c")


# --------------------------------------------------------------------------- 交接摘要
def test_build_summary_has_all_fields_and_is_short():
    conversation = _conversation()
    messages = [
        _msg("user", "我吃了花红片之后肚子疼，要投诉"),
        _msg(
            "assistant",
            "建议立即停药",
            citations=[{"doc_title": "花红片说明书"}],
            tool_calls=[{"name": "kb_search"}],
        ),
        _msg("user", "我要你们赔偿"),
    ]

    summary = svc.build_summary(
        conversation,
        messages,
        risk_flags=["投诉"],
        trigger=HandoffTrigger.SENSITIVE.value,
        reason="投诉",
    )
    assert set(summary) >= {
        "intent",
        "entities",
        "tried_steps",
        "unresolved",
        "risk_flags",
        "suggested_reply",
        "text",
    }
    assert "花红片说明书" in summary["entities"]
    assert summary["tried_steps"] == ["知识库检索"]
    assert "投诉" in summary["risk_flags"]
    assert len(summary["text"]) < 200
    assert summary["suggested_reply"]


def test_ticket_payload_countdown_only_while_queued():
    queued = _ticket(age=30)
    payload = svc.ticket_payload(queued, queue_timeout=90)
    assert payload["status"] == "queued"
    assert 50 <= payload["queue_expires_in"] <= 60
    assert payload["wait_seconds"] >= 29

    assigned = _ticket(status=TicketStatus.ASSIGNED.value, age=30)
    assert svc.ticket_payload(assigned)["queue_expires_in"] == 0
