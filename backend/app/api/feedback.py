"""用户反馈（M4-09）：👍/👎 + 原因，落到 ``messages.feedback``。

三个决定：

- **不建新表**：一条消息只有一份反馈，直接挂 JSONB；导出 eval_case 时不用 join。
- **重复提交 400**：前端已禁用按钮，这里是兜底——按钮状态丢了也不能把一条消息刷成两票。
- **顺带上报 Langfuse 分**（PRD FR7.4 ``user_feedback``）：上报失败不影响落库，
  反馈是产品的数据，不是可观测性的附庸。
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.core.database import get_db
from app.core.timefmt import iso_utc
from app.models.agent import Conversation, Message, MessageRole
from app.models.user import User
from app.schemas.response import ResponseModel

router = APIRouter()

# 前端给的原因 chip；也允许自由文本（≤64 字），方便面试官现场吐槽
REASON_CHOICES = ("答非所问", "引用不对", "太啰嗦", "不该拒答", "信息过时", "其他")


class FeedbackIn(BaseModel):
    message_id: uuid.UUID
    rating: Literal["up", "down"]
    reason: str = Field(default="", max_length=64)


@router.post("/feedback", response_model=ResponseModel[dict])
async def submit_feedback(
    payload: FeedbackIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    message = await db.get(Message, payload.message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="消息不存在")
    conversation = await db.get(Conversation, message.conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if conversation.user_id is None or str(conversation.user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="只能反馈自己会话里的回答")
    if message.role != MessageRole.ASSISTANT.value:
        raise HTTPException(status_code=400, detail="只能对 AI 回答做反馈")
    if message.feedback and message.feedback.get("rating"):
        raise HTTPException(status_code=400, detail="这条回答已经反馈过了")

    message.feedback = {
        "rating": payload.rating,
        "reason": (payload.reason or "").strip()[:64],
        "by": current_user.username,
        "at": iso_utc(message.created_at),
    }
    await db.commit()

    # Langfuse：把反馈当成 trace 的一个分（trace_id 存在消息上，天然可回溯）
    if message.trace_id:
        try:
            from app.observability.base import TraceContext
            from app.observability.tracing import get_trace_sink

            get_trace_sink().score(
                TraceContext(trace_id=message.trace_id, name="chat.turn"),
                "user_feedback",
                1.0 if payload.rating == "up" else 0.0,
                comment=payload.reason or "",
            )
        except Exception:  # noqa: BLE001 —— 上报失败不影响反馈落库
            pass

    return ResponseModel(
        data={
            "recorded": True,
            "message_id": str(message.id),
            "rating": payload.rating,
            "reason": message.feedback["reason"],
        }
    )


__all__ = ["router", "REASON_CHOICES"]
