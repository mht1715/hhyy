"""记忆与转人工（M3）：user_profiles / user_memories / handoff_tickets。

冻结说明：

- ``conversations.summary`` + ``summary_upto`` 是短期记忆的「滚动摘要」和「已摘要到第几条」。
  单独加列而不是放进 ``context`` JSONB：它要参与排序/判空，也需要在后台会话列表里直接看。
- ``user_memories.expires_at`` 允许为空（永久事实），检索侧只按 ``expires_at > now`` 过滤，
  语义记忆的 TTL 是 180 天（PRD FR6.3）。
- ``handoff_tickets.status`` 用 VARCHAR 而不是 PG ENUM：状态机在应用层
  （``app.services.handoff``）校验，加状态不需要改类型。
- **LangGraph checkpointer 的表不在这里建**：由 ``app.agent.checkpointer.init_checkpointer()``
  调库自带的 ``setup()`` 幂等创建（PRD 任务 M3-01 的明确要求），避免手写表结构与库版本漂移。

Revision ID: 0004_memory_handoff
Revises: 0003_agents_chat
Create Date: 2026-11-19
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_memory_handoff"
down_revision: Union[str, None] = "0003_agents_chat"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("summary", sa.Text(), server_default="", nullable=False),
    )
    op.add_column(
        "conversations",
        sa.Column("summary_upto", sa.Integer(), server_default="0", nullable=False),
    )

    op.create_table(
        "user_profiles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("memory_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("summary", sa.Text(), server_default="", nullable=False),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )

    op.create_table(
        "user_memories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("sensitive", sa.Boolean(), nullable=False),
        sa.Column("source_message_id", sa.Uuid(), nullable=True),
        sa.Column("source_conversation_id", sa.Uuid(), nullable=True),
        sa.Column("vector_id", sa.String(length=64), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_memories_user_id", "user_memories", ["user_id"], unique=False)
    op.create_index(
        "ix_user_memories_user_type", "user_memories", ["user_id", "type"], unique=False
    )
    op.create_index(
        "ix_user_memories_user_created", "user_memories", ["user_id", "created_at"], unique=False
    )

    op.create_table(
        "handoff_tickets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column("trigger", sa.String(length=24), nullable=False),
        sa.Column("risk_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("queue_position", sa.Integer(), nullable=False),
        sa.Column("assigned_to", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["assigned_to"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_handoff_tickets_user_id", "handoff_tickets", ["user_id"], unique=False)
    op.create_index(
        "ix_handoff_tickets_status_created", "handoff_tickets", ["status", "created_at"], unique=False
    )
    op.create_index(
        "ix_handoff_tickets_conversation", "handoff_tickets", ["conversation_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_handoff_tickets_conversation", table_name="handoff_tickets")
    op.drop_index("ix_handoff_tickets_status_created", table_name="handoff_tickets")
    op.drop_index("ix_handoff_tickets_user_id", table_name="handoff_tickets")
    op.drop_table("handoff_tickets")

    op.drop_index("ix_user_memories_user_created", table_name="user_memories")
    op.drop_index("ix_user_memories_user_type", table_name="user_memories")
    op.drop_index("ix_user_memories_user_id", table_name="user_memories")
    op.drop_table("user_memories")
    op.drop_table("user_profiles")

    op.drop_column("conversations", "summary_upto")
    op.drop_column("conversations", "summary")
