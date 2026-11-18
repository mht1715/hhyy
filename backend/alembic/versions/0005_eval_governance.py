"""评估与治理（M4）：消息级 guardrail / feedback / prompt_version + 评估结果表。

冻结说明：

- ``messages.guardrail``：这一轮输出治理的结果（``flags`` / ``violations``），
  看板按 flag 聚合、按消息回溯都靠它。M3 之前只在 SSE 的 ``done`` 里带，落库后才有历史。
- ``messages.feedback``：用户 👍/👎 与原因（M4-09），直接挂在消息上而不是新表：
  一条消息只有一份反馈，导出一行 eval_case 时不用 join。
- ``messages.prompt_version``：这一轮实际用的 prompt 版本（灰度命中哪一版），
  没有它就没法做「版本对比」。
- ``eval_runs``：一次评估运行的结果（指标 + 失败样例），看板读最新一条；
  单独建表而不是写文件，是因为演示机是 Windows 容器环境，文件路径最容易丢。

Revision ID: 0005_eval_governance
Revises: 0004_memory_handoff
Create Date: 2026-11-19
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_eval_governance"
down_revision: Union[str, None] = "0004_memory_handoff"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column(
            "guardrail",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "messages",
        sa.Column(
            "feedback",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "messages",
        sa.Column("prompt_version", sa.String(length=32), server_default="", nullable=False),
    )
    op.create_index("ix_messages_created", "messages", ["created_at"], unique=False)
    op.create_index("ix_messages_agent_created", "messages", ["agent_code", "created_at"], unique=False)
    # 下划线开头的部分索引：只索引「有反馈」的行，导出口径全走它
    op.create_index(
        "ix_messages_feedback",
        "messages",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("feedback <> '{}'::jsonb"),
    )

    op.create_table(
        "eval_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("cases", sa.Integer(), nullable=False),
        sa.Column("metrics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("failures", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("notes", sa.Text(), server_default="", nullable=False),
        sa.Column("ran_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        # Base 混入的通用时间戳（SQLAlchemy 模型自动带上，迁移里必须显式建）
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_eval_runs_ran_at", "eval_runs", ["ran_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_eval_runs_ran_at", table_name="eval_runs")
    op.drop_table("eval_runs")
    op.drop_index("ix_messages_feedback", table_name="messages")
    op.drop_index("ix_messages_agent_created", table_name="messages")
    op.drop_index("ix_messages_created", table_name="messages")
    op.drop_column("messages", "prompt_version")
    op.drop_column("messages", "feedback")
    op.drop_column("messages", "guardrail")
