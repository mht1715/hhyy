"""检索层契约。

设计要点：**权限过滤（kb_ids）是必填参数而不是可选参数**——从类型上就堵死
「忘了传权限」的写法，对应 PRD §3.2 的铁律。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence, runtime_checkable


@dataclass(slots=True)
class RetrievedChunk:
    """一条召回片段（含溯源信息）。"""

    id: str
    content: str
    score: float
    kb_id: str
    doc_id: str = ""
    doc_title: str = ""
    section: str | None = None
    page: int | None = None
    source_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RetrievalResult:
    """一次检索的完整结果，含「为什么没答」的原因。"""

    query: str
    chunks: list[RetrievedChunk] = field(default_factory=list)
    rewritten_query: str | None = None
    kb_ids: list[str] = field(default_factory=list)
    filtered_out_kb_ids: list[str] = field(default_factory=list)
    refused: bool = False
    reason: str | None = None

    @property
    def top_score(self) -> float:
        return self.chunks[0].score if self.chunks else 0.0

    def as_context(self, max_chars: int = 6000) -> str:
        """拼成给 LLM 的上下文，带 [n] 角标。"""
        parts: list[str] = []
        used = 0
        for index, chunk in enumerate(self.chunks, start=1):
            head = f"[{index}] {chunk.doc_title or chunk.doc_id}"
            if chunk.section:
                head += f" · {chunk.section}"
            block = f"{head}\n{chunk.content}"
            if used + len(block) > max_chars and parts:
                break
            parts.append(block)
            used += len(block)
        return "\n\n".join(parts)


@runtime_checkable
class Retriever(Protocol):
    """混合检索器：改写 → 多路召回 → 融合 → 重排 → 阈值。"""

    async def retrieve(
        self,
        query: str,
        *,
        kb_ids: Sequence[str],
        top_k: int | None = None,
        history: Sequence[Any] | None = None,
    ) -> RetrievalResult: ...


@runtime_checkable
class Reranker(Protocol):
    """重排器。"""

    async def rerank(
        self,
        query: str,
        chunks: Sequence[RetrievedChunk],
        *,
        top_n: int = 5,
    ) -> list[RetrievedChunk]: ...
