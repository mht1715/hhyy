"""记忆层契约。

分两类：
- **短期**：会话窗口 + 滚动摘要，由 LangGraph checkpointer 承载（M3-01/02）。
- **长期**：结构化画像 + 语义记忆，由 :class:`MemoryStore` 承载（M3-03~05）。

MEMORY 的写操作一律异步、失败不影响主回答。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

MemoryType = Literal["fact", "preference", "episode", "risk"]


@dataclass(slots=True)
class MemoryItem:
    """一条长期记忆。"""

    id: str
    user_id: str
    type: str
    content: str
    confidence: float = 1.0
    sensitive: bool = False
    source_message_id: str | None = None
    created_at: datetime | None = None
    expires_at: datetime | None = None


@runtime_checkable
class MemoryStore(Protocol):
    """长期记忆存储。所有方法都以 ``user_id`` 为第一维度，天然隔离。"""

    async def add(self, item: MemoryItem) -> str: ...

    async def search(self, user_id: str, query: str, *, limit: int = 3) -> list[MemoryItem]: ...

    async def list_for_user(self, user_id: str, *, limit: int = 50) -> list[MemoryItem]: ...

    async def delete(self, user_id: str, memory_id: str) -> bool: ...

    async def clear(self, user_id: str) -> int: ...
