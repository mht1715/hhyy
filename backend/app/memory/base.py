"""记忆层契约。

分两类：

- **短期**：会话窗口 + 滚动摘要，由 ``app.memory.short_term`` 承载（M3-01/02）。
- **长期**：结构化画像 + 语义记忆，由 :class:`MemoryStore` 承载（M3-03~05）。

memory 的写操作一律异步、失败不影响主回答。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

MemoryType = Literal["fact", "preference", "episode", "risk"]

# 注入 prompt 时的类型中文名（前端也会用到同样的词）
TYPE_LABELS: dict[str, str] = {
    "fact": "已知事实",
    "preference": "偏好",
    "episode": "过往咨询",
    "risk": "需要特别留意",
}


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
    source_conversation_id: str | None = None
    created_at: datetime | None = None
    expires_at: datetime | None = None
    # 检索相关度（语义检索时填，结构化列表里恒为 0）
    score: float = 0.0


@dataclass(slots=True)
class MemoryProfile:
    """用户画像 + 记忆开关（``user_profiles`` 的一行）。"""

    user_id: str
    enabled: bool = True
    summary: str = ""
    attributes: dict = field(default_factory=dict)
    updated_at: datetime | None = None


@runtime_checkable
class MemoryStore(Protocol):
    """长期记忆存储。所有方法都以 ``user_id`` 为第一维度，天然隔离。"""

    async def add(self, item: MemoryItem) -> str: ...

    async def search(self, user_id: str, query: str, *, limit: int = 3) -> list[MemoryItem]: ...

    async def list_for_user(self, user_id: str, *, limit: int = 50) -> list[MemoryItem]: ...

    async def delete(self, user_id: str, memory_id: str) -> bool: ...

    async def clear(self, user_id: str) -> int: ...

    async def get_profile(self, user_id: str) -> MemoryProfile: ...

    async def set_enabled(self, user_id: str, enabled: bool) -> bool: ...
