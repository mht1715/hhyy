"""知识库后台的请求/响应模型。"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

ChunkStrategyLiteral = Literal["structured", "recursive"]
VisibilityLiteral = Literal["private", "public"]
KbStatusLiteral = Literal["draft", "active", "archived"]
RoleLiteral = Literal["admin", "doctor", "patient", "support", "visitor"]


class KbBase(BaseModel):
    code: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9_]+$")
    name: str = Field(min_length=2, max_length=128)
    description: Optional[str] = None

    @field_validator("code")
    @classmethod
    def _lower_code(cls, value: str) -> str:
        # code 会拼进检索表达式和前端路由，统一小写避免大小写不一致的坑
        return value.strip().lower()


class KbCreate(KbBase):
    embedding_model: str = "text-embedding-v4"
    dim: int = 1024
    chunk_strategy: ChunkStrategyLiteral = "structured"
    rerank_enabled: bool = True
    score_threshold: float = Field(default=0.30, ge=0.0, le=1.0)
    visibility: VisibilityLiteral = "private"
    status: KbStatusLiteral = "draft"


class KbUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=128)
    description: Optional[str] = None
    chunk_strategy: Optional[ChunkStrategyLiteral] = None
    rerank_enabled: Optional[bool] = None
    score_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    visibility: Optional[VisibilityLiteral] = None
    status: Optional[KbStatusLiteral] = None


class KbOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    description: Optional[str] = None
    embedding_model: str
    dim: int
    chunk_strategy: str
    rerank_enabled: bool
    score_threshold: float
    visibility: str
    status: str
    created_at: datetime
    updated_at: datetime

    # 列表页要显示「几个文档、几段内容」，这两个是聚合出来的
    document_count: int = 0
    chunk_count: int = 0


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kb_id: uuid.UUID
    title: str
    source_type: str
    source_url: Optional[str] = None
    status: str
    error_msg: Optional[str] = None
    chunk_count: int
    version: int
    last_indexed_offset: int
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    created_at: datetime
    updated_at: datetime


class DocumentCreateResult(BaseModel):
    document: DocumentOut
    queued: bool = True


class ChunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    doc_id: uuid.UUID
    chunk_index: int
    section: Optional[str] = None
    content: str
    token_count: Optional[int] = None
    hit_count: int
    page: Optional[int] = None
    vector_id: Optional[str] = None


class ChunkUpdate(BaseModel):
    content: Optional[str] = Field(default=None, min_length=1)
    section: Optional[str] = Field(default=None, max_length=128)


class PermissionItem(BaseModel):
    role: RoleLiteral
    can_read: bool = True


class PermissionUpdate(BaseModel):
    permissions: list[PermissionItem] = Field(default_factory=list)


class PermissionMatrix(BaseModel):
    kb_id: uuid.UUID
    kb_code: str
    rows: list[PermissionItem]


class SearchTestRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    role: RoleLiteral = "patient"
    kb_ids: Optional[list[uuid.UUID]] = None
    top_k: Optional[int] = Field(default=None, ge=1, le=50)
    threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class SearchHit(BaseModel):
    index: int
    doc_id: str
    kb_id: str
    doc_title: str
    section: Optional[str] = None
    page: Optional[int] = None
    score: float
    snippet: str


class SearchTestResponse(BaseModel):
    query: str
    rewritten_query: Optional[str] = None
    role: str
    allowed_kbs: list[dict[str, Any]] = Field(default_factory=list)
    filtered_out_kbs: list[dict[str, Any]] = Field(default_factory=list)
    hits: list[SearchHit] = Field(default_factory=list)
    context: str = ""
    refused: bool = False
    reason: Optional[str] = None
    top_score: float = 0.0
    # 判定用的阈值，以及 top_score 的分数量口径（rerank / dense）——
    # 没有这两个值，测试台只能看到「已拒答」，看不出差多少
    threshold_used: Optional[float] = None
    score_source: Optional[str] = None
    # hits 是否只是「未达阈值」的候选（拒答时的参考命中）
    hits_are_rejected: bool = False
    latency_ms: int = 0


class ZeroRecallItem(BaseModel):
    query: str
    count: int


class StatsResponse(BaseModel):
    kb_count: int
    document_count: int
    chunk_count: int
    searches_7d: int
    zero_recall: list[ZeroRecallItem] = Field(default_factory=list)
    zero_recall_7d: int = 0
    refused_7d: int = 0
