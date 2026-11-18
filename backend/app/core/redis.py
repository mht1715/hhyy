"""Redis 连接（缓存用）。

约定：**Redis 不可用时不是错误**。缓存层挂掉只会让请求变慢（每次回源查库），
不该让业务 500——所以这里的读写都吞异常并记录，调用方拿到 ``None`` 自己决定。
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_redis() -> Any:
    """返回 ``redis.asyncio.Redis``（懒加载，避免导入期连不上就崩）。"""
    import redis.asyncio as aioredis

    return aioredis.from_url(
        f"redis://{settings.redis_host}:{settings.redis_port}/0",
        decode_responses=True,
        socket_timeout=1.5,
        socket_connect_timeout=1.5,
        health_check_interval=30,
    )


async def cache_get(key: str) -> str | None:
    try:
        return await get_redis().get(key)
    except Exception as exc:  # noqa: BLE001 —— 缓存故障不影响主链路
        logger.debug("redis get 失败（%s）：%s", key, exc)
        return None


async def cache_set(key: str, value: str, *, ttl: int) -> None:
    try:
        await get_redis().set(key, value, ex=ttl)
    except Exception as exc:  # noqa: BLE001
        logger.debug("redis set 失败（%s）：%s", key, exc)


async def cache_incr(key: str) -> int | None:
    try:
        return int(await get_redis().incr(key))
    except Exception as exc:  # noqa: BLE001
        logger.debug("redis incr 失败（%s）：%s", key, exc)
        return None


async def cache_delete(key: str) -> None:
    try:
        await get_redis().delete(key)
    except Exception as exc:  # noqa: BLE001
        logger.debug("redis delete 失败（%s）：%s", key, exc)


async def redis_ping() -> bool:
    try:
        return bool(await get_redis().ping())
    except Exception:  # noqa: BLE001
        return False


async def rate_limit_hit(key: str, *, limit: int, window_seconds: int = 60) -> tuple[bool, int]:
    """滑动窗口计数（固定窗口实现）。

    返回 ``(是否放行, 当前计数)``。**Redis 挂了就放行**——限流是保护措施，
    不该因为缓存故障把所有人的对话都拒绝掉（可用性优先于节流）。
    """
    try:
        client = get_redis()
        pipe = client.pipeline()
        pipe.incr(key)
        pipe.expire(key, window_seconds)
        count = int((await pipe.execute())[0])
    except Exception as exc:  # noqa: BLE001
        logger.debug("rate limit 失败（%s）：%s", key, exc)
        return True, 0
    return count <= limit, count


def reset_redis_cache() -> None:
    """测试用：丢掉连接缓存。"""
    get_redis.cache_clear()
