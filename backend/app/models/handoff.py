"""转人工工单（M3-08，PRD FR5.1~FR5.6）。

为什么工单是独立表而不是给 ``conversations`` 加几个字段：一次会话可能反复转人工
（投诉升级、超时留言后重新排队），每次都要留下「谁、为什么、什么时候接的、结论是什么」。
本表里每条记录只走单向状态机（见 ``app.services.handoff``），历史不可变。

``trigger`` 记录触发来源，是评估「哪类问题最需要人工」的数据来源：
显式点击 / 模型调 ``escalate_human`` / 敏感词 / 连续拒答 / 负面情绪。
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TicketStatus(str, enum.Enum):
    QUEUED = "queued"  # 排队中（等坐席接管）
    ASSIGNED = "assigned"  # 已接管，通道打开
    RESOLVED = "resolved"  # 坐席主动结束
    OFFLINE = "offline"  # 90s 无人接管，转留言工单


class HandoffTrigger(str, enum.Enum):
    EXPLICIT = "explicit"  # 用户点「转人工」
    AGENT_TOOL = "agent_tool"  # 模型调用 escalate_human
    SENSITIVE = "sensitive"  # 投诉/纠纷/过量/自杀倾向 → 立即转
    REFUSAL = "refusal"  # 连续 2 次拒答 → 只建议
    EMOTION = "emotion"  # 连续 2 轮负面情绪 → 只建议
    OFFLINE = "offline"  # 超时留言


class HandoffTicket(Base):
    __tablename__ = "handoff_tickets"
    __table_args__ = (
        Index("ix_handoff_tickets_status_created", "status", "created_at"),
        Index("ix_handoff_tickets_conversation", "conversation_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reason: Mapped[str] = mapped_column(String(64), default="")
    trigger: Mapped[str] = mapped_column(String(24), default=HandoffTrigger.EXPLICIT.value)
    risk_flags: Mapped[list[str]] = mapped_column(JSONB, default=list)
    # 交接摘要（结构化）：{intent, entities, tried_steps, unresolved, risk_flags, suggested_reply}
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    queue_position: Mapped[int] = mapped_column(Integer, default=0)
    assigned_to: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), default=TicketStatus.QUEUED.value)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
