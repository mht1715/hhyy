"""知识库（M1）：knowledge_bases / kb_documents / kb_chunks / kb_role_permissions
+ audit_logs + kb_search_logs，并给 userrole 枚举补 SUPPORT。

冻结说明：
- 状态类字段一律 VARCHAR（PRD §6.1），不加 PG 原生 enum，避免每加一个状态就
  ALTER TYPE；取值由 app/models/kb.py 的 str 枚举约束。
- ``kb_documents.last_indexed_offset`` 是断点续传游标，PRD 里没单列，实现 M1-05 时补的。
- ``kb_search_logs`` 支撑 M1-14 的「7 日检索次数 / 零召回 query 榜」，已同步回 PRD。

Revision ID: 0002_knowledge_base
Revises: 0001_baseline
Create Date: 2026-11-18

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_knowledge_base"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    ]


def _add_support_role() -> None:
    """给已有的 userrole 枚举补 'SUPPORT'。

    PG 的 ``ALTER TYPE ... ADD VALUE`` 在新版本里可以放在事务里，但为了兼容
    更老的实例，这里用 Alembic 的 autocommit_block；并且先查 pg_enum，
    保证迁移可重复执行（枚举值无法回滚，重复执行必须安全）。
    """
    bind = op.get_bind()
    exists = bind.execute(
        sa.text(
            "SELECT 1 FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
            "WHERE t.typname = 'userrole' AND e.enumlabel = 'SUPPORT'"
        )
    ).scalar()
    if exists:
        return
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE userrole ADD VALUE 'SUPPORT'")


def upgrade() -> None:
    _add_support_role()

    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("embedding_model", sa.String(length=64), nullable=False),
        sa.Column("dim", sa.Integer(), nullable=False),
        sa.Column("chunk_strategy", sa.String(length=32), nullable=False),
        sa.Column("rerank_enabled", sa.Boolean(), nullable=False),
        sa.Column("score_threshold", sa.Float(), nullable=False),
        sa.Column("visibility", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_knowledge_bases_code", "knowledge_bases", ["code"], unique=True)

    op.create_table(
        "kb_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kb_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("source_type", sa.String(length=16), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("file_hash", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error_msg", sa.Text(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("last_indexed_offset", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("uploaded_by", sa.Uuid(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["kb_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_kb_documents_kb_id", "kb_documents", ["kb_id"])
    op.create_index("ix_kb_documents_file_hash", "kb_documents", ["file_hash"])

    op.create_table(
        "kb_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("doc_id", sa.Uuid(), nullable=False),
        sa.Column("kb_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("section", sa.String(length=128), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("hit_count", sa.Integer(), nullable=False),
        sa.Column("vector_id", sa.String(length=64), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["doc_id"], ["kb_documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("doc_id", "chunk_index", name="uq_kb_chunks_doc_index"),
    )
    op.create_index("ix_kb_chunks_kb_id", "kb_chunks", ["kb_id"])
    op.create_index("ix_kb_chunks_kb_doc", "kb_chunks", ["kb_id", "doc_id"])

    op.create_table(
        "kb_role_permissions",
        sa.Column("kb_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("can_read", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["kb_id"], ["knowledge_bases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("kb_id", "role"),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("actor_role", sa.String(length=16), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=False),
        sa.Column("before", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])

    op.create_table(
        "kb_search_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("query_norm", sa.String(length=255), nullable=False),
        sa.Column("kb_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=True),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("hit_count", sa.Integer(), nullable=False),
        sa.Column("top_score", sa.Float(), nullable=False),
        sa.Column("refused", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_kb_search_logs_created_at", "kb_search_logs", ["created_at"])
    op.create_index("ix_kb_search_logs_hit_count", "kb_search_logs", ["hit_count"])
    op.create_index("ix_kb_search_logs_query_norm", "kb_search_logs", ["query_norm"])


def downgrade() -> None:
    op.drop_index("ix_kb_search_logs_query_norm", table_name="kb_search_logs")
    op.drop_index("ix_kb_search_logs_hit_count", table_name="kb_search_logs")
    op.drop_index("ix_kb_search_logs_created_at", table_name="kb_search_logs")
    op.drop_table("kb_search_logs")

    op.drop_index("ix_audit_logs_action", table_name="audit_logs")
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_table("audit_logs")

    op.drop_table("kb_role_permissions")

    op.drop_index("ix_kb_chunks_kb_doc", table_name="kb_chunks")
    op.drop_index("ix_kb_chunks_kb_id", table_name="kb_chunks")
    op.drop_table("kb_chunks")

    op.drop_index("ix_kb_documents_file_hash", table_name="kb_documents")
    op.drop_index("ix_kb_documents_kb_id", table_name="kb_documents")
    op.drop_table("kb_documents")

    op.drop_index("ix_knowledge_bases_code", table_name="knowledge_bases")
    op.drop_table("knowledge_bases")
    # 注意：PG 无法从枚举里删除单个值，'SUPPORT' 会保留（对旧代码无影响：
    # 旧代码不认识这个值，只是不会用它）。
