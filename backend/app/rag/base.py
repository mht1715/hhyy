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
    # 阈值判定用的分数：**拒答时也要保留**，否则后台只能看到 0.0，无法判断是
    # 「差一点没过」还是「召回为空」，排查全靠猜。
    top_score: float = 0.0
    # 这个 top_score 是什么口径的分：余弦相似度（dense）还是重排分（rerank）
    score_source: str = "dense"
    threshold: float | None = None
    # 因低于阈值被拒时，把「差一点」的片段留在这里给检索测试台看；不参与拼上下文
    rejected_chunks: list[RetrievedChunk] = field(default_factory=list)

    def as_context(self, max_chars: int = 6000) -> str:
        """拼成给 LLM 的上下文，带 [n] 角标。"""
        if self.refused:  # 拒答时绝不给上下文，防止调用方漏判 refused 后硬答
            return ""
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
