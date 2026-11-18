"""测试替身：让单元测试不依赖任何外部服务（LLM / Milvus / PG / Langfuse）。

这些替身**实现生产契约**（Protocol），所以测的是真实接口形状，而不是另一套假 API。
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, AsyncIterator, Iterator, Sequence

from app.memory.base import MemoryItem
from app.observability.base import ObservationType, TraceContext
from app.rag.base import RetrievalResult, RetrievedChunk


class FakeLLM:
    """可预设回答的对话模型替身。"""

    def __init__(self, reply: str = "（fake reply）", chunks: Sequence[str] | None = None) -> None:
        self.reply = reply
        self.chunks = list(chunks) if chunks else None
        self.calls: list[dict[str, Any]] = []

    async def ainvoke(self, messages: Sequence[Any], **kwargs: Any) -> Any:
        self.calls.append({"messages": list(messages), "kwargs": kwargs})
        return _FakeMessage(self.reply)

    async def astream(self, messages: Sequence[Any], **kwargs: Any) -> AsyncIterator[Any]:
        self.calls.append({"messages": list(messages), "kwargs": kwargs})
        for piece in self.chunks or [self.reply]:
            yield _FakeMessage(piece)


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content
        self.response_metadata: dict[str, Any] = {}
        self.usage_metadata: dict[str, Any] = {}


class FakeRetriever:
    """按 ``kb_ids`` 过滤的检索替身——保证「权限参数被真的用上了」。"""

    def __init__(
        self,
        chunks: Sequence[RetrievedChunk] | None = None,
        *,
        threshold: float = 0.0,
    ) -> None:
        self.chunks = list(chunks or [])
        self.threshold = threshold
        self.calls: list[dict[str, Any]] = []

    async def retrieve(
        self,
        query: str,
        *,
        kb_ids: Sequence[str],
        top_k: int | None = None,
        history: Sequence[Any] | None = None,
    ) -> RetrievalResult:
        self.calls.append({"query": query, "kb_ids": list(kb_ids), "top_k": top_k})
        allowed = [c for c in self.chunks if c.kb_id in set(kb_ids)]
        allowed.sort(key=lambda c: c.score, reverse=True)
        if top_k:
            allowed = allowed[:top_k]
        result = RetrievalResult(
            query=query,
            chunks=allowed,
            kb_ids=list(kb_ids),
        )
        if not allowed:
            result.refused = True
            result.reason = "no_hit"
        elif allowed[0].score < self.threshold:
            result.refused = True
            result.reason = "low_score"
        return result


class FakeReranker:
    """按分数重排并截断的替身。"""

    def __init__(self, *, boost: float = 1.0) -> None:
        self.boost = boost
        self.calls = 0

    async def rerank(
        self,
        query: str,
        chunks: Sequence[RetrievedChunk],
        *,
        top_n: int = 5,
    ) -> list[RetrievedChunk]:
        self.calls += 1
        ordered = sorted(chunks, key=lambda c: c.score * self.boost, reverse=True)
        return ordered[:top_n]


class FakeMemoryStore:
    """内存版长期记忆。"""

    def __init__(self) -> None:
        self._items: dict[str, MemoryItem] = {}

    async def add(self, item: MemoryItem) -> str:
        self._items[item.id] = item
        return item.id

    async def search(self, user_id: str, query: str, *, limit: int = 3) -> list[MemoryItem]:
        hits = [i for i in self._items.values() if i.user_id == user_id]
        return hits[:limit]

    async def list_for_user(self, user_id: str, *, limit: int = 50) -> list[MemoryItem]:
        return [i for i in self._items.values() if i.user_id == user_id][:limit]

    async def delete(self, user_id: str, memory_id: str) -> bool:
        item = self._items.get(memory_id)
        if not item or item.user_id != user_id:
            return False
        del self._items[memory_id]
        return True

    async def clear(self, user_id: str) -> int:
        targets = [k for k, v in self._items.items() if v.user_id == user_id]
        for key in targets:
            del self._items[key]
        return len(targets)


class FakeTraceSink:
    """记录型追踪替身，便于断言「有没有埋点」。"""

    def __init__(self) -> None:
        self.traces: list[TraceContext] = []
        self.spans: list[tuple[str, str]] = []
        self.scores: list[tuple[str, str, float | str]] = []
        self.errors: list[str] = []
        self._callbacks: list[Any] = []

    @contextmanager
    def trace(
        self,
        name: str,
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Iterator[TraceContext]:
        ctx = TraceContext(
            trace_id=f"trace-{len(self.traces) + 1}",
            name=name,
            user_id=user_id,
            session_id=session_id,
            tags=list(tags or []),
            metadata=dict(metadata or {}),
        )
        self.traces.append(ctx)
        try:
            yield ctx
        except Exception as exc:  # 记录后原样上抛，模拟真实 sink 的语义
            self.errors.append(str(exc))
            raise

    @contextmanager
    def span(
        self,
        ctx: TraceContext,
        name: str,
        *,
        as_type: ObservationType = "span",
        input: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> Iterator[TraceContext]:
        self.spans.append((ctx.trace_id, name))
        yield ctx

    def score(
        self,
        ctx: TraceContext,
        name: str,
        value: float | str,
        *,
        comment: str | None = None,
    ) -> None:
        self.scores.append((ctx.trace_id, name, value))

    def callbacks(self) -> list[Any]:
        return list(self._callbacks)

    def flush(self) -> None:
        return None
