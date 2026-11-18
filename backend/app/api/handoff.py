"""用户侧转人工（M3-08，契约 §5.1 / §5.2）。

两个入口：

- ``POST /api/handoff``：用户点「转人工」。立即建单，返回排队位次与倒计时；
- ``POST /api/handoff/offline``：90s 没人接管后提交留言，转离线工单。

**为什么要求登录**：坐席要能看到「这是谁、怎么联系」，而且 WS 通道需要身份。
PRD FR5.1 写的是「全角色」，这里收紧为登录用户，属于有意识的取舍（见 README 的差异说明）：
匿名会话没有可回访的联系人，转人工只会变成一条查不到人的工单。
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.core.database import get_db
from app.models.agent import Conversation, Message, MessageRole
from app.models.handoff import HandoffTrigger
from app.models.user import User
from app.schemas.handoff import HandoffRequest, OfflineRequest, TicketOut
from app.schemas.response import ResponseModel
from app.services import handoff as handoff_service

router = APIRouter()


async def get_owned_conversation(
    db: AsyncSession, conversation_id: uuid.UUID, user: User
) -> Conversation:
    conversation = await db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if conversation.user_id is None or str(conversation.user_id) != str(user.id):
        raise HTTPException(status_code=403, detail="无权操作该会话")
    return conversation


async def _last_user_message(db: AsyncSession, conversation_id: Any) -> str:
    row = (
        await db.execute(
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.role == MessageRole.USER.value,
            )
            .order_by(Message.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return (row.content or "") if row is not None else ""


@router.post("", response_model=ResponseModel[TicketOut])
@router.post("/", response_model=ResponseModel[TicketOut], include_in_schema=False)
async def request_handoff(
    payload: HandoffRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conversation = await get_owned_conversation(db, payload.conversation_id, current_user)

    # 触发来源按内容判定：用户点按钮只是「想转人工」，但如果他刚说的是投诉，
    # 这张单应该直接带 sensitive + risk_flags（坐席要按风险优先级处理）。
    text = " ".join(filter(None, [payload.reason or "", await _last_user_message(db, conversation.id)]))
    sensitive, risk_flags = handoff_service.detect_sensitive(text)
    trigger = HandoffTrigger.SENSITIVE.value if sensitive else HandoffTrigger.EXPLICIT.value
    reason = payload.reason or ("用户请求转人工" if not sensitive else "敏感场景，立即转人工")

    ticket, _created = await handoff_service.request_handoff(
        db,
        conversation=conversation,
        user_id=current_user.id,
        reason=reason,
        trigger=trigger,
        risk_flags=risk_flags,
    )
    await handoff_service.refresh_summary(db, ticket)
    await db.commit()
    await handoff_service.broadcast_status(ticket, by="用户")
    return ResponseModel(data=TicketOut(**handoff_service.ticket_payload(ticket)))


@router.post("/offline", response_model=ResponseModel[TicketOut])
async def offline_message(
    payload: OfflineRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conversation = await get_owned_conversation(db, payload.conversation_id, current_user)

    ticket = await handoff_service.active_ticket(db, conversation.id)
    if ticket is None:
        ticket, _created = await handoff_service.request_handoff(
            db,
            conversation=conversation,
            user_id=current_user.id,
            reason="超时留言",
            trigger=HandoffTrigger.OFFLINE.value,
        )
    # 重复提交留言只更新内容（mark_offline 对已离线的工单是幂等的）
    await handoff_service.mark_offline(
        db, ticket, name=payload.name, contact=payload.contact, demand=payload.demand
    )
    await db.commit()
    await handoff_service.broadcast_status(ticket, by="用户")
    return ResponseModel(data=TicketOut(**handoff_service.ticket_payload(ticket)))


__all__ = ["get_owned_conversation", "router"]
