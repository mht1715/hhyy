"""记忆相关出入参（M3-07，契约 docs/接口契约-M3.md §3）。"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Optional

from pydantic import BaseModel, Field, PlainSerializer

from app.core.timefmt import iso_utc

# 出口统一 UTC + Z：否则浏览器会按本地时间解析，时间整体偏 8 小时（见 core/timefmt）
UtcTime = Annotated[datetime, PlainSerializer(iso_utc, return_type=str)]


class MemoryItemOut(BaseModel):
    id: str
    type: str
    content: str
    confidence: float = 1.0
    sensitive: bool = False
    source_message_id: Optional[str] = None
    source_conversation_id: Optional[str] = None
    created_at: Optional[UtcTime] = None
    expires_at: Optional[UtcTime] = None


class MemoryProfileOut(BaseModel):
    summary: str = ""
    attributes: dict[str, Any] = Field(default_factory=dict)
    updated_at: Optional[UtcTime] = None


class MemoryStatsOut(BaseModel):
    total: int = 0
    by_type: dict[str, int] = Field(default_factory=dict)


class MemoryListOut(BaseModel):
    enabled: bool = True
    profile: MemoryProfileOut = Field(default_factory=MemoryProfileOut)
    items: list[MemoryItemOut] = Field(default_factory=list)
    stats: MemoryStatsOut = Field(default_factory=MemoryStatsOut)


class MemoryToggleIn(BaseModel):
    enabled: bool


class MemoryToggleOut(BaseModel):
    enabled: bool


class MemoryDeleteOut(BaseModel):
    deleted: bool


class MemoryClearOut(BaseModel):
    deleted: int
