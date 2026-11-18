"""会话列表与详情（M3，PRD §7.1；契约 §4）。

前端有两处用：用户在「我的会话」里回看，坐席在详情里看完整上下文 + 交接摘要。
权限只有两条：
- 本人（``conversations.user_id == 当前用户``）；
- ``support`` / ``admin``（工单处理需要看别人的会话，这是职务权限）。
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.core.database import get_db
from app.models.agent import Conversation, Message, MessageRole
from app.models.handoff import HandoffTicket, TicketStatus
from app.models.user import User, UserRole
from app.services import handoff as handoff_service

router = APIRouter()

SUPPORT_ROLES = {UserRole.SUPPORT, UserRole.ADMIN}
MAX_MESSAGES = 200


def _iso(value: Any) -> str:
    from app.core.timefmt import iso_utc

    return iso_utc(value)


def _message_payload(message: Message) -> dict[str, Any]:
    return {
        "id": str(message.id),
        "role": message.role,
        "content": message.content or "",
        "agent_code": message.agent_code,
        "citations": message.citations or [],
        "contributors": message.contributors or [],
        "created_at": _iso(message.created_at),
    }


def _can_access(user: User, conversation: Conversation) -> bool:
    if user.role in SUPPORT_ROLES:
        return True
    return conversation.user_id is not None and str(conversation.user_id) == str(user.id)


@router.get("")
async def list_conversations(
    scope: Optional[str] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    size = max(1, min(int(limit or 50), 100))
    statement = select(Conversation).order_by(Conversation.updated_at.desc()).limit(size)
    if not (scope == "all" and current_user.role in SUPPORT_ROLES):
        statement = statement.where(Conversation.user_id == current_user.id)
    rows = list((await db.execute(statement)).scalars().all())

    tickets: dict[str, HandoffTicket] = {}
    if rows:
        active = (
            await db.execute(
                select(HandoffTicket)
                .where(
                    HandoffTicket.conversation_id.in_([row.id for row in rows]),
                    HandoffTicket.status.in_(handoff_service.ACTIVE_STATUSES),
                )
                .order_by(HandoffTicket.created_at.desc())
            )
        ).scalars().all()
        for ticket in active:
            tickets.setdefault(str(ticket.conversation_id), ticket)

    data = []
    for row in rows:
        ticket = tickets.get(str(row.id))
        data.append(
            {
                "id": str(row.id),
                "title": row.title,
                "agent_code": row.agent_code,
                "status": row.status,
                "channel": row.channel,
                "ticket": handoff_service.ticket_payload(ticket) if ticket else None,
                "created_at": _iso(row.created_at),
                "updated_at": _iso(row.updated_at),
            }
        )
    return {"code": 200, "message": "ok", "data": data}


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if not _can_access(current_user, conversation):
        raise HTTPException(status_code=403, detail="无权访问该会话")

    rows = (
        await db.execute(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at.asc())
            .limit(MAX_MESSAGES)
        )
    ).scalars().all()

    ticket = (
        await db.execute(
            select(HandoffTicket)
            .where(HandoffTicket.conversation_id == conversation.id)
            .order_by(HandoffTicket.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    assigned_name = ""
    if ticket is not None and ticket.assigned_to is not None:
        agent = await db.get(User, ticket.assigned_to)
        assigned_name = agent.username if agent is not None else ""

    # 坐席发的消息要标出「谁说的」，用户端才知道自己是在跟人聊
    message_payloads = []
    for row in rows:
        if row.role not in {
            MessageRole.USER.value,
            MessageRole.ASSISTANT.value,
            MessageRole.HUMAN_AGENT.value,
            MessageRole.SYSTEM.value,
        }:
            continue
        # 流式回答会先落一条空 assistant 行，正文等流结束才写回；
        # 坐席在生成途中打开会话不该看到一条永远补不上的空气泡
        if row.role == MessageRole.ASSISTANT.value and not (row.content or "").strip():
            continue
        payload = _message_payload(row)
        payload["actor_name"] = assigned_name if row.role == MessageRole.HUMAN_AGENT.value else ""
        message_payloads.append(payload)

    return {
        "code": 200,
        "message": "ok",
        "data": {
            "id": str(conversation.id),
            "title": conversation.title,
            "agent_code": conversation.agent_code,
            "status": conversation.status,
            "channel": conversation.channel,
            "summary": conversation.summary or "",
            "ticket": (
                handoff_service.ticket_payload(ticket, assigned_name=assigned_name)
                if ticket is not None
                else None
            ),
            "messages": message_payloads,
            "created_at": _iso(conversation.created_at),
            "updated_at": _iso(conversation.updated_at),
        },
    }


__all__ = ["router", "TicketStatus"]
