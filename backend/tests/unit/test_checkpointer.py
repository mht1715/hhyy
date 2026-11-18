"""checkpointer 测试（M3-01）。

单元部分只测「配置拼装」这类不连库的逻辑；真正落库的部分标 ``integration``，
默认跳过（``RUN_INTEGRATION=1`` 才跑），因为它需要真 Postgres。
"""

from __future__ import annotations

import os

import pytest

from app.agent.checkpointer import (
    dsn,
    read_thread_state,
    reset_checkpointer_cache,
    thread_config,
)
from app.core.config import settings


def test_dsn_is_psycopg_style():
    url = dsn()
    assert url.startswith("postgresql://")
    # 绝不能带 +asyncpg：psycopg 不认 SQLAlchemy 的方言前缀
    assert "+asyncpg" not in url
    assert settings.postgres_db in url


def test_thread_config_uses_conversation_id():
    assert thread_config("abc") == {"configurable": {"thread_id": "abc"}}


async def test_checkpointer_disabled_returns_none(monkeypatch):
    monkeypatch.setattr(settings, "checkpointer_enabled", False)
    reset_checkpointer_cache()
    from app.agent.checkpointer import get_checkpointer

    assert await get_checkpointer() is None
    assert await read_thread_state("whatever") is None


@pytest.mark.integration
async def test_checkpointer_roundtrip_against_postgres():
    """真库往返：建表 → 写入一轮状态 → 换一个 saver 仍能读到（= 重启续上下文）。"""
    if os.getenv("RUN_INTEGRATION") != "1":
        pytest.skip("需要真 Postgres")

    reset_checkpointer_cache()
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from langgraph.graph import END, START, StateGraph

    from app.agent.state import AgentState

    async with AsyncPostgresSaver.from_conn_string(dsn()) as saver:
        await saver.setup()

        graph = StateGraph(AgentState)

        async def node(state: AgentState) -> AgentState:
            return {
                "route": {"mode": "mention"},
                "messages": [{"role": "assistant", "content": "上一轮的回答"}],
            }

        graph.add_node("n", node)
        graph.add_edge(START, "n")
        graph.add_edge("n", END)

        app_graph = graph.compile(checkpointer=saver)
        thread = f"probe-{os.getpid()}"
        config = thread_config(thread)
        async for _ in app_graph.astream(
            {"messages": [{"role": "user", "content": "你好"}]}, config, durability="exit"
        ):
            pass

        # 新 saver（模拟进程重启后重新连库）
        async with AsyncPostgresSaver.from_conn_string(dsn()) as saver2:
            snapshot = await graph.compile(checkpointer=saver2).aget_state(config)
            assert snapshot.values["route"] == {"mode": "mention"}
            assert len(snapshot.values["messages"]) == 2

        await saver.adelete_thread(thread)
