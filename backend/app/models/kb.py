"""知识库数据模型（PRD §6.1）。

四张表构成「知识库 → 文档 → 分段」的树，加一张「库 × 角色」授权表。
正文留在 PostgreSQL（便于后台编辑、审计、逐条重建向量），向量存 Milvus，两边用
``kb_chunks.vector_id`` 对应。

两个刻意的取舍：

1. **状态字段用 ``VARCHAR`` 而不是 PG 原生 enum**。状态机（``pending → parsing →
   ... → ready``）和可见性在迭代中一定会加值；PG 原生 enum 每加一个值都要
   ``ALTER TYPE``，且旧版本 PG 还限制在事务内使用。PRD §6.1 也是 VARCHAR。
   代码层面仍用 ``str`` 枚举约束取值，避免拼错字符串。
2. **``kb_chunks.kb_id`` 冗余存一份**，不做 join。检索后要按库聚合、按库统计、
   按库做权限复核，冗余一列换来的是这些查询都不用连表。
"""

from __future__ import annotations

import enum
import uuid
from datetime import date
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class KbStatus(str, enum.Enum):
    """知识库生命周期。归档后不再参与检索，数据保留。"""

    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class KbVisibility(str, enum.Enum):
    """可见性：``public`` 对外（含游客），``private`` 必须显式授权。"""

    PRIVATE = "private"
    PUBLIC = "public"


class ChunkStrategy(str, enum.Enum):
    STRUCTURED = "structured"
    RECURSIVE = "recursive"


class DocumentStatus(str, enum.Enum):
    """文档索引状态机（PRD FR2.2）。失败一定带 ``error_msg``，可重试。"""

    PENDING = "pending"
    PARSING = "parsing"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    READY = "ready"
    FAILED = "failed"


class DocumentSource(str, enum.Enum):
    PDF = "pdf"
    DOCX = "docx"
    MD = "md"
    TXT = "txt"
    URL = "url"
    MANUAL = "manual"


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 每个库可以独立选模型与切分策略：药品说明书要 structured，客服话术 recursive
    embedding_model: Mapped[str] = mapped_column(String(64), default="text-embedding-v4")
    dim: Mapped[int] = mapped_column(Integer, default=1024)
    chunk_strategy: Mapped[str] = mapped_column(String(32), default=ChunkStrategy.STRUCTURED.value)
    rerank_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    score_threshold: Mapped[float] = mapped_column(Float, default=0.30)
    visibility: Mapped[str] = mapped_column(String(16), default=KbVisibility.PRIVATE.value)
    status: Mapped[str] = mapped_column(String(16), default=KbStatus.DRAFT.value)

    owner_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    documents: Mapped[list["KbDocument"]] = relationship(
        back_populates="kb", cascade="all, delete-orphan", passive_deletes=True
    )
    permissions: Mapped[list["KbRolePermission"]] = relationship(
        back_populates="kb", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def is_searchable(self) -> bool:
        """只有 ``active`` 的库参与检索；``draft`` 是「还没配好」，``archived`` 是「下线」。"""
        return self.status == KbStatus.ACTIVE.value


class KbDocument(Base):
    __tablename__ = "kb_documents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    kb_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(16), default=DocumentSource.MANUAL.value)
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # 同一份文件重复上传时靠 hash 拦掉，避免向量库里出现两份相同内容
    file_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)

    status: Mapped[str] = mapped_column(String(16), default=DocumentStatus.PENDING.value)
    error_msg: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)

    # 断点续传：已经写进 Milvus 的 chunk 序号，重跑时从这里继续（M1-05）
    last_indexed_offset: Mapped[int] = mapped_column(Integer, default=0)

    effective_from: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    effective_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    uploaded_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    kb: Mapped["KnowledgeBase"] = relationship(back_populates="documents")
    chunks: Mapped[list["KbChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )


class KbChunk(Base):
    __tablename__ = "kb_chunks"
    __table_args__ = (
        UniqueConstraint("doc_id", "chunk_index", name="uq_kb_chunks_doc_index"),
        Index("ix_kb_chunks_kb_doc", "kb_id", "doc_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    doc_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("kb_documents.id", ondelete="CASCADE")
    )
    kb_id: Mapped[uuid.UUID] = mapped_column(index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    section: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # 命中次数由检索链路累加，用于「哪些段落最常被问」的运营视角
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    vector_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    page: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    document: Mapped["KbDocument"] = relationship(back_populates="chunks")


class KbRolePermission(Base):
    """知识库 × 角色 的读权限。默认没有任何行 = 没有任何角色可读（默认拒绝）。"""

    __tablename__ = "kb_role_permissions"

    kb_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(16), primary_key=True)
    can_read: Mapped[bool] = mapped_column(Boolean, default=True)

    kb: Mapped["KnowledgeBase"] = relationship(back_populates="permissions")


class AuditLog(Base):
    """写操作审计（PRD FR2.8 / §3.4）：谁、何时、对谁、改了什么、前后值。

    复用 ``Base`` 的 ``created_at`` / ``updated_at``；审计行只写不改，
    ``updated_at`` 会与 ``created_at`` 相同。
    """

    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_logs_created_at", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True)
    actor_role: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[str] = mapped_column(String(64))
    before: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    after: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class KbSearchLog(Base):
    """检索日志：支撑「7 日检索次数」和「零召回 query 榜」（PRD FR2.7）。

    PRD §6.1 原本没有这张表，实现 M1-14 时发现统计需求绕不开它，遂补上，
    已同步回 PRD。只记 query 与结果摘要，不记回答正文。
    """

    __tablename__ = "kb_search_logs"
    __table_args__ = (
        Index("ix_kb_search_logs_created_at", "created_at"),
        Index("ix_kb_search_logs_hit_count", "hit_count"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    query: Mapped[str] = mapped_column(Text)
    # 归一化后的 query（去空白/标点），零召回榜单按它聚合
    query_norm: Mapped[str] = mapped_column(String(255), index=True)
    kb_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    role: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True)
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    top_score: Mapped[float] = mapped_column(Float, default=0.0)
    refused: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
