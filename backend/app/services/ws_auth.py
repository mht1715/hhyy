"""WebSocket 短期票据（M3-10）。

为什么不让 WS 直接用 JWT：浏览器 ``WebSocket`` 不能自定义 header，JWT 只能塞进
query string——而 query string 会进 Nginx / 网关的访问日志，等于把长期凭证写进日志。
所以走「HTTP 换一张 60 秒、一次性的 ticket，再用第一帧把它交给服务端」。

存储用 Redis（多 worker 共享），Redis 不可用时退化成进程内字典（单进程演示仍可用）。
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from typing import Any, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

_PREFIX = "ws:ticket:"
_LOCAL: dict[str, tuple[float, dict[str, Any]]] = {}


def _key(token: str) -> str:
    return f"{_PREFIX}{token}"


async def issue_ticket(
    *, user_id: Any, username: str, role: str, conversation_id: Any = None, ttl: int | None = None
) -> tuple[str, int]:
    """签发一次性票据，返回 ``(ticket, ttl)``。

    ``conversation_id`` 可选：给了就在票据里绑定「只能进这个会话」，
    没给就只证明身份（具体会话在 WS 握手时按归属/角色再校验一次）。
    """
    expires_in = int(ttl or settings.ws_ticket_ttl)
    token = secrets.token_urlsafe(24)
    payload = {
        "user_id": str(user_id),
        "username": username,
        "role": role,
        "conversation_id": str(conversation_id or ""),
        "exp": time.time() + expires_in,
    }
    try:
        from app.core.redis import get_redis

        await get_redis().setex(_key(token), expires_in, json.dumps(payload, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001 —— Redis 挂了也要能连上（单进程场景）
        logger.warning("WS 票据写入 Redis 失败，改用进程内存储：%s", exc)
        _LOCAL[token] = (payload["exp"], payload)
    return token, expires_in


async def consume_ticket(token: str) -> Optional[dict[str, Any]]:
    """校验并**作废**票据（一次性）。无效/过期返回 ``None``。"""
    if not token:
        return None

    raw: Optional[str] = None
    try:
        from app.core.redis import get_redis

        client = get_redis()
        # 先取再删：并发重放时只有一个能拿到值（GETDEL 在 Redis 6.2+ 可用）
        raw = await client.getdel(_key(token))
    except Exception as exc:  # noqa: BLE001
        logger.debug("WS 票据读取失败（尝试进程内）：%s", exc)
        raw = None

    if raw:
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            return None
        if float(payload.get("exp", 0)) < time.time():
            return None
        return payload

    entry = _LOCAL.pop(token, None)
    if entry is None:
        return None
    expires, payload = entry
    if expires < time.time():
        return None
    return payload


def reset_ticket_cache() -> None:
    """测试用。"""
    _LOCAL.clear()


__all__ = ["consume_ticket", "issue_ticket", "reset_ticket_cache"]
