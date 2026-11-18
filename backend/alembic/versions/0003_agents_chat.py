"""多 Agent 与会话（M2）：agents / prompt_templates / conversations / messages。

冻结说明：
- ``agents.kb_ids`` 存**知识库 code**、``tools`` 存**工具名**，不是 UUID/函数引用。
  理由见 app/models/agent.py 的模块注释：配置要可读、可进日志、可跨环境复用。
- 状态类字段一律 VARCHAR（与 M1 一致），取值由 app/models/agent.py 的 str 枚举约束。
- ``messages.client_message_id`` 建索引而不是唯一约束：真要有并发重复提交，
  我们希望由业务层「查到就重放」来收敛，而不是让 INSERT 直接抛 500。
- M3 会在这两张表上加 handoff 状态机与 checkpointer，届时只加列/加表，不改这里。

Revision ID: 0003_agents_chat
Revises: 0002_knowledge_base
Create Date: 2026-11-18

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_agents_chat"
down_revision: Union[str, None] = "0002_knowledge_base"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "agents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("avatar", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("system_prompt_code", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("temperature", sa.Float(), nullable=False),
        sa.Column("kb_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("tools", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("allowed_roles", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("handoff_targets", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("ui_mode", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agents_code", "agents", ["code"], unique=True)
    op.create_index("ix_agents_status", "agents", ["status"], unique=False)

    op.create_table(
        "prompt_templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "variables_schema", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("model", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("labels", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("rollout", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", "version", name="uq_prompt_code_version"),
    )
    op.create_index("ix_prompt_templates_code", "prompt_templates", ["code"], unique=False)

    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("anonymous_id", sa.String(length=64), nullable=True),
        sa.Column("agent_code", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("context", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"], unique=False)
    op.create_index("ix_conversations_anonymous_id", "conversations", ["anonymous_id"], unique=False)
    op.create_index("ix_conversations_status", "conversations", ["status"], unique=False)

    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("agent_code", sa.String(length=64), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("mentions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("citations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("tool_calls", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("contributors", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("client_message_id", sa.String(length=64), nullable=True),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("usage", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_messages_client_message_id", "messages", ["client_message_id"], unique=False
    )
    op.create_index(
        "ix_messages_conversation_created", "messages", ["conversation_id", "created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_messages_conversation_created", table_name="messages")
    op.drop_index("ix_messages_client_message_id", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_conversations_status", table_name="conversations")
    op.drop_index("ix_conversations_anonymous_id", table_name="conversations")
    op.drop_index("ix_conversations_user_id", table_name="conversations")
    op.drop_table("conversations")
    op.drop_index("ix_prompt_templates_code", table_name="prompt_templates")
    op.drop_table("prompt_templates")
    op.drop_index("ix_agents_status", table_name="agents")
    op.drop_index("ix_agents_code", table_name="agents")
    op.drop_table("agents")
