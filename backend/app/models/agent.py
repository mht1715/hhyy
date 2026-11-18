"""Agent 注册与会话模型（PRD §6.1，M2-01）。

核心思想：**Agent 是配置，工具是代码**。新增一个 Agent = 往 ``agents`` 表插一行
（选知识库、选工具、写 prompt 模板），不需要改编排逻辑，也不需要发版。

四张表：

- ``agents``：Agent 注册信息，``kb_ids`` / ``tools`` 存的是 **code 而不是 UUID**。
  配置是给人看的、也会写进 prompt 与日志，用 code 比用 UUID 可读得多；代价是
  删库/删工具时要校验引用（见 ``app.agent.registry``）。
- ``prompt_templates``：``(code, version)`` 唯一，``status`` 标记哪个版本在跑。
- ``conversations`` / ``messages``：会话与消息。``client_message_id`` 唯一索引
  支撑 M2-06 的幂等重放（同一客户端消息 5 分钟内重复提交不重复计费）。
"""

from __future__ import annotations

import enum
import uuid
from typing import Any, Optional

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class AgentStatus(str, enum.Enum):
    ACTIVE = "active"
    DRAFT = "draft"
    ARCHIVED = "archived"


class UiMode(str, enum.Enum):
    """前台怎么用这个 Agent：对话 / 内嵌 / 表单。"""

    CHAT = "chat"
    INLINE = "inline"
    FORM = "form"


class PromptStatus(str, enum.Enum):
    DRAFT = "draft"
    TESTING = "testing"
    PRODUCTION = "production"
    ARCHIVED = "archived"


class ConversationStatus(str, enum.Enum):
    BOT_ACTIVE = "bot_active"
    HANDOFF_PENDING = "handoff_pending"
    HUMAN_ACTIVE = "human_active"
    CLOSED = "closed"


class MessageRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    HUMAN_AGENT = "human_agent"
    TOOL = "tool"


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64))
    avatar: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    system_prompt_code: Mapped[str] = mapped_column(String(64), default="")
    model: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    temperature: Mapped[float] = mapped_column(Float, default=0.3)
    # 存知识库 code（不是 UUID）：配置要进日志、进 prompt、进前端，可读性优先
    kb_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    tools: Mapped[list[str]] = mapped_column(JSONB, default=list)
    allowed_roles: Mapped[list[str]] = mapped_column(JSONB, default=list)
    handoff_targets: Mapped[list[str]] = mapped_column(JSONB, default=list)
    ui_mode: Mapped[str] = mapped_column(String(16), default=UiMode.CHAT.value)
    status: Mapped[str] = mapped_column(String(16), default=AgentStatus.ACTIVE.value, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"
    __table_args__ = (UniqueConstraint("code", "version", name="uq_prompt_code_version"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    content: Mapped[str] = mapped_column(Text, default="")
    variables_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    model: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # draft / testing / production / archived：一个 code 同一时刻只应有一个 production
    status: Mapped[str] = mapped_column(String(16), default=PromptStatus.PRODUCTION.value)
    labels: Mapped[list[str]] = mapped_column(JSONB, default=list)
    rollout: Mapped[int] = mapped_column(Integer, default=100)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    anonymous_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    agent_code: Mapped[str] = mapped_column(String(64), default="")
    title: Mapped[str] = mapped_column(String(255), default="")
    channel: Mapped[str] = mapped_column(String(16), default="web")
    status: Mapped[str] = mapped_column(
        String(24), default=ConversationStatus.BOT_ACTIVE.value, index=True
    )
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    # M3 短期记忆：超出窗口的历史压成摘要（PRD FR6.1）。``summary_upto`` 记录
    # 「已经浓缩到第几条消息」，避免每轮都重复摘要同一批内容。
    summary: Mapped[str] = mapped_column(Text, default="")
    summary_upto: Mapped[int] = mapped_column(Integer, default=0)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        # 幂等的抓手：同一客户端消息 id 只能落一条用户消息
        Index("ix_messages_client_message_id", "client_message_id"),
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(16))
    agent_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    content: Mapped[str] = mapped_column(Text, default="")
    mentions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    tool_calls: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    contributors: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    client_message_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    trace_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    usage: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
