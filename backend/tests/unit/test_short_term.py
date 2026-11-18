"""短期记忆测试（M3-02）：窗口、预算、滚动摘要。"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from app.memory.short_term import (
    _deterministic_summary,
    estimate_tokens,
    load_history,
    maybe_summarize,
)


class _Rows:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _Scalar:
    def __init__(self, value: int) -> None:
        self._value = value

    def scalar_one(self) -> int:
        return self._value


class FakeDB:
    """够用的替身：``get`` 返回会话摘要，``execute`` 返回消息或计数。"""

    def __init__(self, rows: list, *, summary: str = "", summary_upto: int = 0) -> None:
        self.rows = rows
        self.conversation = SimpleNamespace(summary=summary, summary_upto=summary_upto)
        self.flushed = 0

    async def get(self, model, pk):  # noqa: ANN001
        return self.conversation

    async def execute(self, statement):  # noqa: ANN001
        sql = str(statement).lower()
        if "count(" in sql:
            return _Scalar(len(self.rows))
        # 真库按 created_at 升/降序返回，这里照做，否则「最近 N 条」的判断会被骗过
        ordered = sorted(self.rows, key=lambda row: row.created_at)
        if "desc" in sql:
            ordered.reverse()
        return _Rows(ordered)

    async def flush(self) -> None:
        self.flushed += 1


def _msg(role: str, content: str, *, minutes: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        role=role,
        content=content,
        created_at=datetime(2026, 11, 18, 10, 0) + timedelta(minutes=minutes),
    )


def test_estimate_tokens_is_conservative():
    assert estimate_tokens("") >= 1
    assert estimate_tokens("花红片孕妇禁用") < estimate_tokens("花红片孕妇禁用" * 10)


async def test_load_history_keeps_recent_turns_within_budget():
    rows = [_msg("user" if i % 2 == 0 else "assistant", "这" * 80, minutes=i) for i in range(40)]
    history = await load_history(FakeDB(rows), "c-1", max_turns=10, budget=300)

    assert history.messages, "至少要保留最近一轮"
    assert history.tokens <= 300
    assert history.truncated is True
    # 最新的一条一定在（否则模型不知道用户刚说了什么）
    assert history.messages[-1]["content"].startswith("这")


async def test_load_history_includes_summary_and_small_talk_stays_small():
    rows = [_msg("user", "花红片怎么吃"), _msg("assistant", "一次两片", minutes=1)]
    history = await load_history(FakeDB(rows, summary="用户问过花红片用法"), "c-1")

    assert history.summary == "用户问过花红片用法"
    assert [item["role"] for item in history.messages] == ["user", "assistant"]
    assert history.truncated is False


async def test_maybe_summarize_skips_when_within_window():
    rows = [_msg("user", "x", minutes=i) for i in range(4)]
    assert await maybe_summarize(FakeDB(rows), "c-1", max_turns=10) is None


async def test_maybe_summarize_writes_deterministic_summary_without_llm(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "deepseek_api_key", "")  # 不调外部模型
    rows = [_msg("user" if i % 2 == 0 else "assistant", f"第{i}条消息", minutes=i) for i in range(30)]
    db = FakeDB(rows, summary="旧摘要", summary_upto=0)

    outcome = await maybe_summarize(db, "c-1", max_turns=3)

    assert outcome is not None
    assert outcome.upto == 30 - 3 * 2
    assert outcome.generated_with_llm is False
    assert "旧摘要" in outcome.summary
    assert db.conversation.summary_upto == outcome.upto
    assert db.flushed == 1


def test_deterministic_summary_prefixes_roles_and_truncates():
    rows = [_msg("user", "我对青霉素过敏"), _msg("assistant", "建议避免青霉素类")]
    summary = _deterministic_summary("", rows)
    assert "用户：我对青霉素过敏" in summary
    assert "客服：建议避免青霉素类" in summary
    assert len(_deterministic_summary("", [_msg("user", "啊" * 500)])) <= 600
