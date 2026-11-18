"""Embedding 批处理封装（M1-06）。

为什么要单独一层，而不是让调用方直接用 ``get_embedding_client()``：

1. **批大小可控**：DashScope 兼容模式对单次请求条数有限制（本项目默认 10 条/批），
   但这个限制属于供应商细节，不应该泄漏到索引流水线里。
2. **重试带退避**：嵌入接口偶发 429/超时，直接失败会让整篇文档进 failed 状态。
   退避重试把这类抖动挡在流水线之外。
3. **维度校验**：模型换了而库里的 collection 还是 1024 维时，最坏情况是写入
   Milvus 才报错、或更糟——写入成功但检索语义错乱。这里入库前就断言维度。
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Sequence
from contextlib import nullcontext
from typing import Any

from app.core.config import settings
from app.llm.client import LLMNotConfigured, get_embedding_client
from app.observability.base import TraceContext, TraceSink

logger = logging.getLogger(__name__)


class EmbeddingError(RuntimeError):
    """嵌入失败：重试耗尽、维度不符、或未配置凭据。"""


def _validate(vec: Sequence[float], expected: int, where: str) -> list[float]:
    if len(vec) != expected:
        raise EmbeddingError(
            f"{where} 返回维度 {len(vec)}，与配置的 {expected} 不一致；"
            f"请检查 EMBEDDING_DIMENSIONS 与 Milvus collection 的 dim 是否匹配"
        )
    return list(vec)


async def _with_backoff(coro_factory: Any, *, attempts: int, where: str) -> Any:
    """指数退避执行 ``coro_factory()``。"""
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            return await coro_factory()
        except LLMNotConfigured:
            raise
        except Exception as exc:  # noqa: BLE001 —— 供应商异常类型不稳定，统一退避
            last = exc
            if attempt == attempts - 1:
                break
            delay = min(0.5 * (2**attempt), 8.0) + random.uniform(0, 0.2)
            logger.warning("%s 第 %d 次失败（%s），%.1fs 后重试", where, attempt + 1, exc, delay)
            await asyncio.sleep(delay)
    raise EmbeddingError(f"{where} 连续 {attempts} 次失败：{last}") from last


async def embed_texts(
    texts: Sequence[str],
    *,
    batch_size: int | None = None,
    max_attempts: int = 3,
    sink: TraceSink | None = None,
    ctx: TraceContext | None = None,
) -> list[list[float]]:
    """把一批文本转成向量，返回顺序与入参一致。

    :raises EmbeddingError: 未配置凭据 / 重试耗尽 / 维度不符。
    """
    items = list(texts)
    if not items:
        return []

    try:
        client = get_embedding_client()
    except LLMNotConfigured as exc:
        raise EmbeddingError(str(exc)) from exc

    size = max(1, batch_size or settings.embedding_batch_size)
    expected = settings.embedding_dimensions
    vectors: list[list[float]] = []

    for start in range(0, len(items), size):
        batch = items[start:start + size]
        label = f"embedding batch [{start}:{start + len(batch)}]"
        # 没有 tracer 时用 nullcontext，保持下面只有一条代码路径
        span_cm = (
            sink.span(ctx, "embedding.batch", as_type="span", metadata={"size": len(batch)})
            if (sink is not None and ctx is not None)
            else nullcontext()
        )
        with span_cm:
            raw = await _with_backoff(
                lambda b=batch: client.aembed_documents(list(b)),
                attempts=max_attempts,
                where=label,
            )
        vectors.extend(_validate(vec, expected, label) for vec in raw)

    if len(vectors) != len(items):
        raise EmbeddingError(f"期望 {len(items)} 条向量，实际拿到 {len(vectors)} 条")
    return vectors


async def embed_query(query: str, *, max_attempts: int = 3) -> list[float]:
    """检索用的单条查询向量。"""
    try:
        client = get_embedding_client()
    except LLMNotConfigured as exc:
        raise EmbeddingError(str(exc)) from exc

    raw = await _with_backoff(
        lambda: client.aembed_query(query),
        attempts=max_attempts,
        where="embedding query",
    )
    return _validate(raw, settings.embedding_dimensions, "embedding query")
