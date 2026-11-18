"""坐席工作台接口（M3-10，契约 §5.3 / §5.4）。

只给 ``support`` / ``admin``。四个动作对应工单状态机：

```
GET  /tickets            队列（默认 queued+assigned）
POST /tickets/{id}/accept    queued → assigned，会话 → human_active
POST /tickets/{id}/resolve   assigned → resolved，会话 → closed
POST /tickets/{id}/messages  坐席发言（落库 + 广播给用户）
```

非法流转统一由 ``app.services.handoff`` 抛 ``InvalidTransition``，这里转 409——
前端拿到 409 就知道「这个单已经被别人接管了」，而不是一个含糊的 500。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.core.database import get_db
from app.models.agent import Conversation, Message, MessageRole
from app.models.handoff import HandoffTicket, TicketStatus
from app.models.user import User, UserRole
from app.schemas.handoff import (
    AcceptOut,
    AgentMessageIn,
    AgentMessageOut,
    ResolveIn,
    TicketListItem,
    TicketOut,
    WsTicketOut,
)
from app.schemas.response import ResponseModel
from app.services import handoff as handoff_service
from app.services import ws_auth

router = APIRouter()

SUPPORT_ROLES = {UserRole.SUPPORT, UserRole.ADMIN}
DEFAULT_STATUSES = "queued,assigned"


def _require_support(user: User) -> None:
    if user.role not in SUPPORT_ROLES:
        raise HTTPException(status_code=403, detail="仅客服与管理员可用")


def _iso(value: Any) -> str:
    return value.isoformat() if isinstance(value, datetime) else ""


@router.get("/tickets", response_model=ResponseModel[list[TicketListItem]])
async def list_tickets(
    status: Optional[str] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_support(current_user)
    wanted = [item.strip() for item in (status or DEFAULT_STATUSES).split(",") if item.strip()]
    valid = {item.value for item in TicketStatus}
    wanted = [item for item in wanted if item in valid] or list(DEFAULT_STATUSES.split(","))
    size = max(1, min(int(limit or 50), 100))

    order = (
        HandoffTicket.created_at.asc()
        if TicketStatus.QUEUED.value in wanted
        else HandoffTicket.created_at.desc()
    )
    tickets = list(
        (
            await db.execute(
                select(HandoffTicket)
                .where(HandoffTicket.status.in_(wanted))
                .order_by(order)
                .limit(size)
            )
        )
        .scalars()
        .all()
    )
    if not tickets:
        return ResponseModel(data=[])

    conversations = {
        row.id: row
        for row in (
            await db.execute(
                select(Conversation).where(
                    Conversation.id.in_([ticket.conversation_id for ticket in tickets])
                )
            )
        )
        .scalars()
        .all()
    }
    users = {
        row.id: row
        for row in (
            await db.execute(
                select(User).where(
                    User.id.in_([ticket.user_id for ticket in tickets if ticket.user_id])
                )
            )
        )
        .scalars()
        .all()
    }

    data: list[TicketListItem] = []
    for ticket in tickets:
        payload = handoff_service.ticket_payload(ticket)
        assigned = users.get(ticket.assigned_to) if ticket.assigned_to else None
        if assigned is not None:
            payload["assigned_to"] = assigned.username
        conversation = conversations.get(ticket.conversation_id)
        owner = users.get(ticket.user_id) if ticket.user_id else None
        data.append(
            TicketListItem(
                **payload,
                conversation_title=(conversation.title if conversation else ""),
                user_label=(owner.username if owner else "游客"),
            )
        )
    return ResponseModel(data=data)


async def _get_ticket(db: AsyncSession, ticket_id: uuid.UUID) -> HandoffTicket:
    ticket = await db.get(HandoffTicket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail="工单不存在")
    return ticket


@router.post("/tickets/{ticket_id}/accept", response_model=ResponseModel[AcceptOut])
async def accept_ticket(
    ticket_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_support(current_user)
    ticket = await _get_ticket(db, ticket_id)
    if ticket.status == TicketStatus.ASSIGNED.value and str(ticket.assigned_to) != str(
        current_user.id
    ):
        raise HTTPException(status_code=409, detail="该工单已被其他坐席接管")
    try:
        await handoff_service.accept_ticket(db, ticket, current_user.id)
    except handoff_service.InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.commit()
    await handoff_service.broadcast_status(ticket, by=current_user.username)
    return ResponseModel(
        data=AcceptOut(
            ticket_id=str(ticket.id),
            status=ticket.status,
            conversation_id=str(ticket.conversation_id),
            status_of_conversation="human_active",
        )
    )


@router.post("/tickets/{ticket_id}/resolve", response_model=ResponseModel[TicketOut])
async def resolve_ticket(
    ticket_id: uuid.UUID,
    payload: Optional[ResolveIn] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_support(current_user)
    ticket = await _get_ticket(db, ticket_id)
    try:
        await handoff_service.resolve_ticket(db, ticket, tags=(payload.tags if payload else []))
    except handoff_service.InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await db.commit()
    await handoff_service.broadcast_status(ticket, by=current_user.username)
    return ResponseModel(data=TicketOut(**handoff_service.ticket_payload(ticket)))


@router.post("/tickets/{ticket_id}/messages", response_model=ResponseModel[AgentMessageOut])
async def send_message(
    ticket_id: uuid.UUID,
    payload: AgentMessageIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _require_support(current_user)
    ticket = await _get_ticket(db, ticket_id)
    if ticket.status != TicketStatus.ASSIGNED.value:
        raise HTTPException(status_code=409, detail="接管后才能发消息")
    if ticket.assigned_to is not None and str(ticket.assigned_to) != str(current_user.id):
        raise HTTPException(status_code=403, detail="该工单由其他坐席处理")

    message = Message(
        conversation_id=ticket.conversation_id,
        role=MessageRole.HUMAN_AGENT.value,
        content=payload.content.strip(),
    )
    db.add(message)
    await db.commit()
    await db.refresh(message)

    from app.services.support_bus import publish

    await publish(
        ticket.conversation_id,
        {
            "type": "message",
            "message": {
                "id": str(message.id),
                "role": MessageRole.HUMAN_AGENT.value,
                "content": message.content,
                "actor_name": current_user.username,
                "created_at": _iso(message.created_at),
            },
        },
    )
    return ResponseModel(data=AgentMessageOut(message_id=str(message.id), delivered=True))


@router.post("/ws-ticket", response_model=ResponseModel[WsTicketOut])
async def create_ws_ticket(
    conversation_id: Optional[uuid.UUID] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """签发一次性 WS 票据（契约 §5.4）：先 HTTP 拿 ticket，再用第一帧连 WS。

    ``conversation_id`` 可选（前端在连接前才确定会话，历史版本实现里也没带）：
    给了就在这里顺手做一次归属校验并把会话绑进票据；没给就只证明身份，
    真正的权限校验发生在 WS 握手的 ``_authorize`` 里（两道都校验，不依赖前端）。
    """
    if conversation_id is not None:
        conversation = await db.get(Conversation, conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        is_support = current_user.role in SUPPORT_ROLES
        if not is_support and (
            conversation.user_id is None or str(conversation.user_id) != str(current_user.id)
        ):
            raise HTTPException(status_code=403, detail="无权进入该会话")

    token, ttl = await ws_auth.issue_ticket(
        user_id=current_user.id,
        username=current_user.username,
        role="support" if current_user.role in SUPPORT_ROLES else "user",
        conversation_id=conversation_id,
    )
    return ResponseModel(
        data=WsTicketOut(
            ws_ticket=token,
            expires_in=ttl,
            ws_url=f"/ws/support/{conversation_id}" if conversation_id else "",
        )
    )
