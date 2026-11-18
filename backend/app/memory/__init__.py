"""记忆层：短期（窗口 + 摘要）与长期（画像 + 语义记忆）。

对外只需要三个入口：

- :func:`app.memory.short_term.load_history` / :func:`~app.memory.short_term.maybe_summarize`
- :func:`app.memory.inject.load_memory`（读）与 :func:`app.memory.extractor.extract_memories`（写）
- :class:`app.memory.long_term.PgMemoryStore`（用户「我的记忆」页面的增删查）

其余模块（``base`` / ``semantic``）是实现细节，业务层不直接依赖。
"""

from app.memory.base import TYPE_LABELS, MemoryItem, MemoryProfile, MemoryStore, MemoryType
from app.memory.inject import InjectedMemory, load_memory, render_block
from app.memory.long_term import PgMemoryStore, normalize_text, similarity
from app.memory.semantic import SemanticMemory
from app.memory.short_term import HistoryContext, estimate_tokens, load_history, maybe_summarize

__all__ = [
    "HistoryContext",
    "InjectedMemory",
    "MemoryItem",
    "MemoryProfile",
    "MemoryStore",
    "MemoryType",
    "PgMemoryStore",
    "SemanticMemory",
    "TYPE_LABELS",
    "estimate_tokens",
    "load_history",
    "load_memory",
    "maybe_summarize",
    "normalize_text",
    "render_block",
    "similarity",
]
