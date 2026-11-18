"""重排器（M1-07）。

RRF 融合分只有 0.0x 量级、且只反映「两路召回的名次」，不反映语义相关度；
真正决定「答不答」的阈值必须落在重排分数上。所以这一层是阈值语义的地基，
没配 key 时必须**安静地降级**，而不是抛异常把整条链路弄挂。

模型名：阿里云百炼当前可用的文本重排模型是 ``gte-rerank-v2``。
写成 ``gte-rerank``（老名字）会拿到 403 AccessDenied，症状是「重排静默失效 →
退回余弦阈值 → 泛问句全被拒答」，排查时极易被误判成权限问题。
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence

import httpx

from app.core.config import settings
from app.rag.base import Reranker, RetrievedChunk

logger = logging.getLogger(__name__)

# 熔断：rerank 一旦失败（未开通/鉴权失败），5 分钟内不再尝试。
# 否则每次检索都要多付一次几十~几百毫秒的失败请求，还会把日志刷满。
_COOLDOWN_SECONDS = 300
_cooldown_until = 0.0


def rerank_available(now: float | None = None) -> bool:
    return (now if now is not None else time.monotonic()) >= _cooldown_until


def _trip_cooldown() -> None:
    global _cooldown_until
    _cooldown_until = time.monotonic() + _COOLDOWN_SECONDS


def reset_rerank_cooldown() -> None:
    """测试用。"""
    global _cooldown_until
    _cooldown_until = 0.0


class RerankUnavailable(RuntimeError):
    """重排服务不可用（未开通、鉴权失败、超时）。

    抛出而不是静默返回原顺序：调用方需要知道「这批分数不是重排分」，
    才能改成用余弦相似度打分——否则阈值会拿 RRF 的 0.0x 去跟 0.30 比，永远拒答。
    """


class NoopReranker:
    """没有 rerank 凭据时的降级实现：只截断，不改分。"""

    is_active = False

    async def rerank(
        self,
        query: str,
        chunks: Sequence[RetrievedChunk],
        *,
        top_n: int = 5,
    ) -> list[RetrievedChunk]:
        return list(chunks)[:top_n]


class DashScopeReranker:
    """阿里云百炼 ``gte-rerank-v2``。

    接口返回 ``relevance_score``（0~1），直接当作 ``RetrievedChunk.score`` 使用，
    这样阈值判断、上下文排序、前端展示的分数是同一个口径。

    注意分数刻度很保守：实测无关问题基本落在 0.006 一档，相关问题 0.17~0.95，
    所以判断阈值取 ``rerank_score_threshold``（默认 0.12），不能沿用余弦的 0.30/0.40。
    """

    is_active = True

    def __init__(self, *, model: str | None = None, timeout: float = 15.0) -> None:
        self.model = model or settings.rerank_model
        self.timeout = timeout

    async def rerank(
        self,
        query: str,
        chunks: Sequence[RetrievedChunk],
        *,
        top_n: int = 5,
    ) -> list[RetrievedChunk]:
        items = list(chunks)
        if not items or not settings.dashscope_api_key:
            return items[:top_n]

        payload = {
            "model": self.model,
            "input": {"query": query, "documents": [c.content for c in items]},
            "parameters": {"return_documents": False, "top_n": min(top_n, len(items))},
        }
        headers = {
            "Authorization": f"Bearer {settings.dashscope_api_key}",
            "Content-Type": "application/json",
        }
        url = settings.rerank_base_url.rstrip("/") + "/api/v1/services/rerank/text-rerank/text-rerank"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPStatusError as exc:
            _trip_cooldown()
            text = exc.response.text or ""
            # 模型名写错时百炼返回 403 AccessDenied 而不是 404，容易被当成「没开通」
            typo = "Model not exist" in text or exc.response.status_code == 404
            hint = "（模型名可能不对：本账号可用 gte-rerank-v2）" if typo else ""
            raise RerankUnavailable(
                f"HTTP {exc.response.status_code} {text[:200]}{hint}"
            ) from exc
        except Exception as exc:  # noqa: BLE001 —— 交给调用方决定降级方式
            _trip_cooldown()
            raise RerankUnavailable(f"{type(exc).__name__}: {exc}") from exc

        try:
            results = body["output"]["results"]
        except (KeyError, TypeError) as exc:
            _trip_cooldown()
            raise RerankUnavailable(f"返回结构异常：{str(body)[:200]}") from exc

        reordered: list[RetrievedChunk] = []
        for item in results:
            index = int(item["index"])
            if index >= len(items):
                continue
            chunk = items[index]
            # 复制一份再改分：调用方可能还持有原列表用于「重排前后对比」
            reordered.append(
                RetrievedChunk(
                    id=chunk.id,
                    content=chunk.content,
                    score=float(item.get("relevance_score", 0.0)),
                    kb_id=chunk.kb_id,
                    doc_id=chunk.doc_id,
                    doc_title=chunk.doc_title,
                    section=chunk.section,
                    page=chunk.page,
                    source_url=chunk.source_url,
                    metadata={**chunk.metadata, "pre_rerank_score": chunk.score},
                )
            )
        if not reordered:  # 空结果说明接口异常，退回原顺序更安全
            return items[:top_n]
        logger.info(
            "rerank 完成：%s -> %s", [round(c.score, 3) for c in items[:3]],
            [round(c.score, 3) for c in reordered[:3]],
        )
        return reordered


def get_reranker(*, enabled: bool = True) -> Reranker:
    """按配置返回重排器：有 key、开关打开、且不在熔断期才启用，否则 no-op。"""
    if (
        not enabled
        or not settings.rerank_enabled
        or not settings.dashscope_api_key
        or not rerank_available()
    ):
        return NoopReranker()
    return DashScopeReranker()
