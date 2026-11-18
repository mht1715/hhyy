"""坐席通道广播 + WS 票据测试（M3-10）。

单元测试不碰真 Redis：把 ``get_redis`` 打成「连不上」，验证**降级路径**仍然可用
（这条降级路径是单进程演示能跑的前提，必须有测试兜着）。
"""

from __future__ import annotations

import asyncio

import pytest

from app.core.config import settings
from app.services import support_bus, ws_auth


@pytest.fixture(autouse=True)
def _broken_redis(monkeypatch):
    def _raise(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise RuntimeError("redis 不可用（单测）")

    monkeypatch.setattr("app.core.redis.get_redis", _raise)
    ws_auth.reset_ticket_cache()
    yield
    ws_auth.reset_ticket_cache()


async def test_publish_reaches_local_subscriber_without_redis():
    conversation_id = "c-local-1"
    async with support_bus.subscription(conversation_id) as queue:
        await support_bus.publish(conversation_id, {"type": "message", "content": "hi"})
        payload = await asyncio.wait_for(queue.get(), timeout=1)
    assert payload == {"type": "message", "content": "hi"}
    assert support_bus.local_subscriber_count(conversation_id) == 0


async def test_channels_are_isolated_per_conversation():
    async with support_bus.subscription("c-a") as queue_a:
        await support_bus.publish("c-b", {"type": "message"})
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(queue_a.get(), timeout=0.2)


async def test_ws_ticket_is_one_time_and_expires():
    token, ttl = await ws_auth.issue_ticket(
        user_id="u-1", username="patient_1", role="user", conversation_id="c-1"
    )
    assert ttl == settings.ws_ticket_ttl
    claims = await ws_auth.consume_ticket(token)
    assert claims is not None and claims["conversation_id"] == "c-1"

    # 一次性：第二次必须失败
    assert await ws_auth.consume_ticket(token) is None
    assert await ws_auth.consume_ticket("not-a-ticket") is None


async def test_ws_ticket_rejects_bad_token(monkeypatch):
    async def _noop(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        return None

    monkeypatch.setattr("app.core.redis.get_redis", lambda: _Client())
    assert await ws_auth.consume_ticket("") is None


class _Client:
    async def getdel(self, key: str):  # noqa: ANN201
        return b"not-json"
