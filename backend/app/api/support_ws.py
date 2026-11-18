"""人工坐席 WebSocket 通道（M3-10，契约 §6）。

一条连接同时服务两种角色：

- 用户（会话本人）：把自己说的话推给坐席，并接收坐席的回复；
- 坐席（support/admin）：接管后收发消息。

**鉴权在第一帧**：URL 里只有 ``conversation_id``，凭证用 HTTP 换来的 60 秒一次性
票据，通过 ``{"type":"auth","ticket":"..."}`` 交上来。这样 JWT 永远不进 query
string，也不会被网关日志记下来。

两件事必须做对：

1. **收与发彻底分开**。收消息的循环和推送的循环各自一个 task：如果合成一个循环，
   用户不说话时收不到别人（Redis）推来的消息。
2. **推送走总线不直接写 socket**。本进程的另一个连接发消息时，要能立刻出现在这里，
   跨进程则靠 Redis Pub/Sub（见 ``app.services.support_bus``）。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Optional

from fastapi import APIRouter, WebSocket
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.agent import Conversation, Message, MessageRole
from app.models.handoff import HandoffTicket, TicketStatus
from app.models.user import User, UserRole
from app.services import handoff as handoff_service
from app.services import ws_auth
from app.services.support_bus import publish, subscription

logger = logging.getLogger(__name__)

router = APIRouter()

SUPPORT_ROLES = {UserRole.SUPPORT, UserRole.ADMIN}
AUTH_TIMEOUT = 10.0
MAX_FRAME_CHARS = 4000


def _iso(value: Any) -> str:
    from app.core.timefmt import iso_utc

    return iso_utc(value)


def _message_frame(message: Message, *, actor_name: str = "") -> dict[str, Any]:
    return {
        "type": "message",
        "message": {
            "id": str(message.id),
            "role": message.role,
            "content": message.content or "",
            "actor_name": actor_name,
            # 回带给发送方：前端用它把「本地乐观气泡」和服务端落库的那条对齐，
            # 否则自己发的消息会显示两遍
            "client_message_id": message.client_message_id or "",
            "created_at": _iso(message.created_at),
        },
    }


async def _load_context(conversation_id: uuid.UUID) -> Optional[dict[str, Any]]:
    async with AsyncSessionLocal() as db:
        conversation = await db.get(Conversation, conversation_id)
        if conversation is None:
            return None
        ticket = await handoff_service.active_ticket(db, conversation.id)
        return {"conversation": conversation, "ticket": ticket}


async def _authorize(ticket_payload: dict[str, Any], conversation_id: uuid.UUID) -> Optional[dict]:
    """校验票据与权限，返回 ``{role, user_id, username}``。

    票据里若绑定了会话（``conversation_id`` 非空），必须与当前 URL 一致；
    没绑定时只校验「这个用户是否有权进入这个会话」。
    """
    claimed_conversation = str(ticket_payload.get("conversation_id") or "")
    if claimed_conversation and claimed_conversation != str(conversation_id):
        return None
    context = await _load_context(conversation_id)
    if context is None:
        return None
    conversation: Conversation = context["conversation"]
    claimed = str(ticket_payload.get("role"))
    user_id = str(ticket_payload.get("user_id") or "")
    is_support = claimed == "support"
    if is_support:
        if ticket_payload.get("role") not in {"support", "admin"}:
            return None
        owner = str(conversation.user_id or "")
        if owner == user_id:
            return {"role": "user", "user_id": user_id, "username": ticket_payload.get("username", "")}
        return {"role": "support", "user_id": user_id, "username": ticket_payload.get("username", "")}
    if conversation.user_id is None or str(conversation.user_id) != user_id:
        return None
    return {"role": "user", "user_id": user_id, "username": ticket_payload.get("username", "")}


@router.websocket("/ws/support/{conversation_id}")
async def support_socket(websocket: WebSocket, conversation_id: str) -> None:
    await websocket.accept()
    try:
        uuid.UUID(conversation_id)
    except (ValueError, AttributeError, TypeError):
        await websocket.close(code=4400)
        return

    # ---- 1) 第一帧鉴权 ----
    try:
        frame = await asyncio.wait_for(websocket.receive_json(), timeout=AUTH_TIMEOUT)
    except Exception:  # noqa: BLE001 —— 超时 / 断开 / 非 JSON 一律按未授权处理
        await _safe_close(websocket, 4401)
        return
    if not isinstance(frame, dict) or frame.get("type") != "auth":
        await _safe_close(websocket, 4401)
        return
    claims = await ws_auth.consume_ticket(str(frame.get("ticket") or ""))
    if claims is None:
        await _safe_close(websocket, 4401)
        return
    identity = await _authorize(claims, uuid.UUID(conversation_id))
    if identity is None:
        await _safe_close(websocket, 4403)
        return

    context = await _load_context(uuid.UUID(conversation_id))
    conversation: Conversation = context["conversation"]
    ticket: Optional[HandoffTicket] = context["ticket"]
    await websocket.send_json(
        {
            "type": "ready",
            "role": identity["role"],
            "conversation_id": str(conversation.id),
            "status": conversation.status,
            "name": identity["username"],
            "ticket": handoff_service.ticket_payload(ticket) if ticket else None,
        }
    )

    stop = asyncio.Event()

    async def send_loop() -> None:
        try:
            async with subscription(conversation.id) as queue:
                while not stop.is_set():
                    try:
                        payload = await asyncio.wait_for(
                            queue.get(), timeout=float(settings.ws_heartbeat_seconds)
                        )
                    except asyncio.TimeoutError:
                        payload = {"type": "ping"}
                    try:
                        await websocket.send_json(payload)
                    except Exception:  # noqa: BLE001 —— 对端已断开，安静退出
                        return
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.debug("坐席通道推送循环结束", exc_info=True)

    async def recv_loop() -> None:
        while not stop.is_set():
            try:
                data = await websocket.receive_json()
            except Exception:  # noqa: BLE001 —— 断开 / 非 JSON
                return
            if not isinstance(data, dict):
                continue
            kind = data.get("type")
            if kind in {"pong", "auth"}:
                continue
            if kind != "message":
                continue
            content = str(data.get("content") or "").strip()
            if not content:
                continue
            content = content[:MAX_FRAME_CHARS]
            client_message_id = str(data.get("client_message_id") or "").strip()[:64]
            try:
                await _handle_message(
                    websocket,
                    conversation_id=uuid.UUID(conversation_id),
                    identity=identity,
                    content=content,
                    client_message_id=client_message_id,
                )
            except Exception:  # noqa: BLE001 —— 单条消息失败不该断开整条通道
                logger.exception("处理坐席消息失败")

    tasks = [asyncio.create_task(send_loop()), asyncio.create_task(recv_loop())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        stop.set()
        for task in tasks:
            task.cancel()
        # 必须 gather 一下：否则被取消/异常结束的 task 会在回收时打
        # 「Task exception was never retrieved」，日志里看着像真故障
        await asyncio.gather(*tasks, return_exceptions=True)
        await _safe_close(websocket, 1000)


async def _handle_message(
    websocket: WebSocket,
    *,
    conversation_id: uuid.UUID,
    identity: dict[str, Any],
    content: str,
    client_message_id: str = "",
) -> None:
    """把一条入站消息落库并广播。坐席必须先接管。"""
    async with AsyncSessionLocal() as db:
        conversation = await db.get(Conversation, conversation_id)
        if conversation is None:
            await websocket.send_json(
                {"type": "error", "code": "NOT_FOUND", "message": "会话不存在"}
            )
            return

        if identity["role"] == "support":
            user = await db.get(User, uuid.UUID(identity["user_id"]))
            if user is None or user.role not in SUPPORT_ROLES:
                await websocket.send_json(
                    {"type": "error", "code": "FORBIDDEN", "message": "坐席身份无效"}
                )
                return
            ticket = await handoff_service.active_ticket(db, conversation.id)
            if ticket is None or ticket.status != TicketStatus.ASSIGNED.value:
                await websocket.send_json(
                    {"type": "error", "code": "NOT_ASSIGNED", "message": "请先接管该会话"}
                )
                return
            if ticket.assigned_to is not None and str(ticket.assigned_to) != identity["user_id"]:
                await websocket.send_json(
                    {"type": "error", "code": "NOT_ASSIGNED", "message": "该会话由其他坐席处理"}
                )
                return
            message = Message(
                conversation_id=conversation.id,
                role=MessageRole.HUMAN_AGENT.value,
                content=content,
                client_message_id=client_message_id or None,
            )
        else:
            if conversation.user_id is None or str(conversation.user_id) != identity["user_id"]:
                await websocket.send_json(
                    {"type": "error", "code": "FORBIDDEN", "message": "无权发送消息"}
                )
                return
            message = Message(
                conversation_id=conversation.id,
                role=MessageRole.USER.value,
                content=content,
                client_message_id=client_message_id or None,
            )

        # 幂等：同一个 client_message_id 只落一条（断线重发 / 重连后补发都会重放这一帧）
        if client_message_id:
            existing = (
                await db.execute(
                    select(Message).where(
                        Message.conversation_id == conversation.id,
                        Message.client_message_id == client_message_id,
                    )
                )
            ).scalars().first()
            if existing is not None:
                actor_name = (
                    identity["username"]
                    if existing.role == MessageRole.HUMAN_AGENT.value
                    else ""
                )
                await publish(conversation_id, _message_frame(existing, actor_name=actor_name))
                return

        db.add(message)
        await db.commit()
        await db.refresh(message)

    actor = identity["username"] if identity["role"] == "support" else ""
    await publish(conversation_id, _message_frame(message, actor_name=actor))
    if identity["role"] == "support":
        logger.info("坐席 %s 发言 conversation=%s", actor, conversation_id)


async def _safe_close(websocket: WebSocket, code: int) -> None:
    try:
        await websocket.close(code=code)
    except Exception:  # noqa: BLE001 —— 已经断开时 close 会抛
        pass


__all__ = ["router"]
