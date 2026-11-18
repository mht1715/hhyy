"""记忆模型（M3-03，PRD FR6.2 / FR6.6）。

两张表分工明确：

- ``user_profiles``：**每用户一行**的画像与开关。``memory_enabled`` 放在这里而不是
  放 ``users`` 表，是因为「关闭记忆」是 Agent 能力的一部分，不该污染账号表。
- ``user_memories``：一条条可解释、可单条删除的记忆。``source_message_id`` 是溯源锚点
  （回答里说「您上次提到…」时，前端要能指回那句话）。

三个设计约束：

1. **绝不跨用户**：所有查询的第一个条件都是 ``user_id``（见 ``app.memory.long_term``）。
2. **过期不等于删除**：语义记忆有 180 天 TTL，到期只是不再召回；行还在，用户仍能看见
   并自己删（合规上「保留可见」比「悄悄消失」更让人放心）。
3. **敏感项标记**：``sensitive=True`` 的（孕早期、疾病史）在注入 prompt 时会被单独措辞，
   且默认不写入语义 collection（只留结构化行）。
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, Float, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MemoryType(str, enum.Enum):
    FACT = "fact"  # 事实：对青霉素过敏
    PREFERENCE = "preference"  # 偏好：希望电话联系
    EPISODE = "episode"  # 情节：2026-11 咨询过哺乳期用药
    RISK = "risk"  # 禁忌：孕早期（高敏感）


class UserProfile(Base):
    """用户画像 + 记忆开关。"""

    __tablename__ = "user_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # 关闭后：不再抽取、不再注入；历史条目保留可删（PRD FR6.6）
    memory_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)


class UserMemory(Base):
    """一条长期记忆。"""

    __tablename__ = "user_memories"
    __table_args__ = (
        Index("ix_user_memories_user_type", "user_id", "type"),
        Index("ix_user_memories_user_created", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(16), default=MemoryType.FACT.value)
    content: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    source_message_id: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True)
    source_conversation_id: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True)
    # Milvus 里的向量主键（= 本行 id 的字符串形式），删除时用它做补偿
    vector_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
