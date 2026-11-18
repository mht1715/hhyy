"""坐席通道的广播层（M3-10）：Redis Pub/Sub + 进程内兜底。

为什么不是「WebSocket 之间直接互发」：生产上客服和用户往往连在不同 worker/不同进程，
只有 Redis 这种外部总线才能把消息送到对端。但 Redis 不是必需品——单进程演示、
或者 Redis 临时挂了，也应该能聊完一个会话，所以这里还有一层**进程内队列**：

```
publish(payload) ─┬─▶ 本地订阅者（同一进程的所有 WS 连接）
                  └─▶ Redis channel（其他进程）
subscribe()       ◀── 本地队列 ◀── Redis 订阅（去重交给前端按 message.id 处理）
```

频道名带会话 id：坐席只要订阅自己接管的那个会话，不该收到全站消息。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

_LOCAL: dict[str, set[asyncio.Queue]] = {}


def channel_name(conversation_id: Any) -> str:
    return f"hhyy:support:{conversation_id}"


def _register(conversation_id: str, queue: asyncio.Queue) -> None:
    _LOCAL.setdefault(conversation_id, set()).add(queue)


def _unregister(conversation_id: str, queue: asyncio.Queue) -> None:
    subscribers = _LOCAL.get(conversation_id)
    if not subscribers:
        return
    subscribers.discard(queue)
    if not subscribers:
        _LOCAL.pop(conversation_id, None)


def local_subscriber_count(conversation_id: Any) -> int:
    return len(_LOCAL.get(str(conversation_id), ()))


async def publish(conversation_id: Any, payload: dict[str, Any]) -> None:
    """广播一帧。Redis 失败只记日志（本地订阅者已经收到）。"""
    cid = str(conversation_id)
    for queue in list(_LOCAL.get(cid, ())):
        queue.put_nowait(payload)

    try:
        from app.core.redis import get_redis

        await get_redis().publish(channel_name(cid), json.dumps(payload, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001 —— 跨进程广播失败不影响本进程
        logger.debug("Redis 发布失败（%s）：%s", cid, exc)


async def _redis_reader(conversation_id: str, queue: asyncio.Queue) -> None:
    """订阅 Redis 并把消息塞进本地队列；连不上就安静退出（本地广播仍工作）。"""
    pubsub = None
    try:
        from app.core.redis import get_redis

        pubsub = get_redis().pubsub()
        await pubsub.subscribe(channel_name(conversation_id))
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            try:
                payload = json.loads(message.get("data") or "{}")
            except (TypeError, ValueError):
                continue
            if isinstance(payload, dict):
                queue.put_nowait(payload)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.debug("Redis 订阅失败（%s）：%s", conversation_id, exc)
    finally:
        if pubsub is not None:
            try:
                await pubsub.aclose()
            except Exception:  # noqa: BLE001
                logger.debug("关闭 pubsub 失败", exc_info=True)


@asynccontextmanager
async def subscription(conversation_id: Any) -> AsyncIterator[asyncio.Queue]:
    """订阅一个会话的广播，``yield`` 出一个队列。"""
    cid = str(conversation_id)
    queue: asyncio.Queue = asyncio.Queue()
    _register(cid, queue)
    task = asyncio.create_task(_redis_reader(cid, queue))
    try:
        yield queue
    finally:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        _unregister(cid, queue)


def redis_channel_hint() -> str:
    return f"redis://{settings.redis_host}:{settings.redis_port}"


__all__ = [
    "channel_name",
    "local_subscriber_count",
    "publish",
    "redis_channel_hint",
    "subscription",
]
