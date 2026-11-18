"""检索服务（M1-08）：改写 → 混合召回 → 重排 → 阈值 → 上下文。

为什么阈值必须落在**重排分**上
--------------------------------
RRF 的融合分只有 0.0x 量级（``RRFRanker(60)`` 下第一名的上限约 0.033），
它只表示"两路召回里排第几"，不表示"有多相关"。拿它跟 0.30 比，等于永远拒答；
而把它按最大值归一化，归一化后的 0.9 也不代表语义相关。所以：

- 有 reranker：hybrid 召回 → 重排分（0~1）→ 与阈值比较；
- 没 reranker：直接用 dense 检索，分数是余弦相似度（0~1）→ 与阈值比较。

两条路的分数都满足"abs(score) 与阈值同量纲"，这是阈值能成立的前提。
但**同量纲不等于同分布**：重排分与余弦分的刻度差着一个数量级，所以两个口径
各有一个阈值（``rerank_score_threshold`` / 库上的 ``score_threshold``），
见 :meth:`RetrievalService._threshold`。
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.llm.client import LLMNotConfigured, get_chat_client
from app.llm.embedding import EmbeddingError, embed_query
from app.models.kb import KbChunk, KbDocument, KbSearchLog, KnowledgeBase
from app.models.user import UserRole
from app.rag.acl import AclSnapshot, build_filter, resolve_acl
from app.rag.base import RetrievalResult, RetrievedChunk
from app.rag.milvus_repo import MilvusRepo, MilvusUnavailable, get_milvus_repo
from app.rag.reranker import RerankUnavailable, get_reranker

logger = logging.getLogger(__name__)

REWRITE_MAX_CHARS = 60


def normalize_query(query: str) -> str:
    """归一化：去多余空白与标点，用于零召回榜单聚合。"""
    text = "".join(" " if ch.isspace() else ch for ch in query)
    text = "".join(ch for ch in text if ch.isalnum() or "\u4e00" <= ch <= "\u9fff" or ch == " ")
    return " ".join(text.split())[:255]


def resolve_threshold(
    *,
    source: str,
    override: float | None = None,
    kb_threshold: float | None = None,
) -> float:
    """阈值口径必须跟着分数走——这是「同量纲 ≠ 同分布」的落地点。

    重排分（0~1）和余弦相似度（0~1）虽然都落在 0~1，分布却完全不同：
    实测同一批问题，重排把无关问题打到 0.006、相关问题 0.17~0.94；
    余弦则把无关问题也能打到 0.4+，反而把「介绍一下企业」打到 0.28。
    拿 0.30 去卡两种分数，必然一边全拒、一边全放。所以：

    - ``source="rerank"`` → 全局 ``rerank_score_threshold``（重排分与库无关）；
    - ``source="dense"`` → 库上配置的余弦阈值（每个库文档密度不同，要各自标定）。
    """
    if override is not None:
        return override
    if source == "rerank":
        return settings.rerank_score_threshold
    return kb_threshold if kb_threshold is not None else settings.score_threshold


class RetrievalService:
    def __init__(
        self,
        *,
        repo: MilvusRepo | None = None,
        reranker: Any | None = None,
    ) -> None:
        self._repo = repo
        self._reranker = reranker

    @property
    def repo(self) -> MilvusRepo:
        if self._repo is None:
            self._repo = get_milvus_repo()
        return self._repo

    def reranker(self, *, enabled: bool = True) -> Any:
        if self._reranker is not None:
            return self._reranker
        return get_reranker(enabled=enabled)

    # ------------------------------------------------------------------ 主流程
    async def retrieve(
        self,
        db: AsyncSession,
        query: str,
        *,
        role: UserRole | str,
        user_id: uuid.UUID | str | None = None,
        kb_ids: Sequence[str] | None = None,
        top_k: int | None = None,
        threshold: float | None = None,
        history: Sequence[Any] | None = None,
        rewrite: bool = True,
        write_log: bool = True,
    ) -> RetrievalResult:
        started = time.perf_counter()
        acl: AclSnapshot = await resolve_acl(db, role=role, user_id=user_id)

        allowed = list(acl.kb_ids)
        if kb_ids is not None:
            wanted = {str(kb_id) for kb_id in kb_ids}
            allowed = [kb_id for kb_id in allowed if kb_id in wanted]

        result = RetrievalResult(
            query=query,
            kb_ids=allowed,
            filtered_out_kb_ids=list(acl.denied_kb_ids),
        )

        if not allowed:
            result.refused = True
            result.reason = "no_permission" if acl.denied_kb_ids else "no_kb"
            await self._log(db, result, role=role, user_id=user_id, latency_ms=_elapsed(started),
                            write_log=write_log)
            return result

        # 1. 多轮改写：只在有历史时做，避免把单轮问题的语义改坏
        rewritten: str | None = None
        if rewrite and history:
            rewritten = await self._rewrite(query, history)
        effective_query = rewritten or query
        result.rewritten_query = rewritten

        # 2. 权限过滤表达式（下推到向量库）
        expr = build_filter(allowed)
        if expr is None:  # 理论上走不到，防御性返回
            result.refused = True
            result.reason = "no_permission"
            return result

        try:
            vector = await embed_query(effective_query)
        except EmbeddingError as exc:
            logger.warning("检索向量化失败：%s", exc)
            result.refused = True
            result.reason = "no_kb"
            await self._log(db, result, role=role, user_id=user_id, latency_ms=_elapsed(started),
                            write_log=write_log)
            return result

        top = top_k or settings.retrieval_top_k
        top_n = settings.rerank_top_n
        reranker = self.reranker()
        use_hybrid = bool(getattr(reranker, "is_active", False))
        candidates: list[RetrievedChunk] = []
        try:
            if use_hybrid:
                candidates = await self.repo.hybrid_search(
                    vector, effective_query, expr=expr, limit=top
                )
                try:
                    candidates = await reranker.rerank(effective_query, candidates, top_n=top_n)
                except RerankUnavailable as exc:
                    # 重排不可用（账号未开通 / 鉴权失败 / 超时）：不能拿 RRF 分当相似度用
                    logger.warning("重排不可用，退回 dense 打分：%s", exc)
                    use_hybrid = False
                    candidates = []
            if not use_hybrid:
                # 无重排：用余弦相似度保证分数与阈值同量纲（见模块 docstring）
                candidates = (await self.repo.dense_search(vector, expr=expr, limit=top))[:top_n]
        except MilvusUnavailable as exc:
            logger.warning("向量检索不可用：%s", exc)
            result.refused = True
            result.reason = "no_kb"
            await self._log(db, result, role=role, user_id=user_id, latency_ms=_elapsed(started),
                            write_log=write_log)
            return result

        result.chunks = candidates
        if not candidates:
            result.refused = True
            result.reason = "no_hit"
            await self._log(db, result, role=role, user_id=user_id, latency_ms=_elapsed(started),
                            write_log=write_log)
            return result

        # 范围守卫：问题里出现「知识库里根本没提的疾病」时，分数再高也不能答
        # （典型：问「花红片能治糖尿病吗」，命中说明书但说明书没写糖尿病）
        from app.rag.scope import out_of_scope_terms

        out_of_scope = out_of_scope_terms(effective_query, [chunk.content for chunk in candidates])
        if out_of_scope:
            result.refused = True
            result.reason = f"out_of_scope:{'、'.join(out_of_scope)}"
            result.rejected_chunks = list(candidates)
            result.chunks = []
            result.top_score = candidates[0].score
            await self._log(db, result, role=role, user_id=user_id, latency_ms=_elapsed(started),
                            write_log=write_log)
            return result

        result.score_source = "rerank" if use_hybrid else "dense"
        result.top_score = candidates[0].score
        # 3. 阈值：口径跟着分数走（重排分用全局阈值，余弦分用库级阈值）
        cut = await self._threshold(
            db, candidates[0].kb_id, override=threshold, source=result.score_source
        )
        result.threshold = cut
        if result.top_score < cut:
            result.refused = True
            result.reason = "low_score"
            # 拒答时清空 chunks：调用方不该拿到一个"虽然拒答但仍可拼上下文"的结果。
            # 但把候选留在 rejected_chunks，后台测试台才能看到「差多少分」。
            result.rejected_chunks = list(result.chunks)
            result.chunks = []
            await self._log(db, result, role=role, user_id=user_id, latency_ms=_elapsed(started),
                            write_log=write_log)
            return result

        await self._enrich_titles(db, result.chunks)
        await self._bump_hit_count(db, result.chunks)
        await self._log(db, result, role=role, user_id=user_id, latency_ms=_elapsed(started),
                        write_log=write_log)
        return result

    # ------------------------------------------------------------------ 子步骤
    async def _rewrite(self, query: str, history: Sequence[Any]) -> str | None:
        """把「那孕妇呢」这类依赖上文的问法改写成可独立检索的 query。"""
        if not settings.llm_configured:
            return None
        context_lines: list[str] = []
        for item in list(history)[-4:]:
            content = getattr(item, "content", None) or (item.get("content") if isinstance(item, dict) else None)
            if content:
                context_lines.append(str(content)[:200])
        if not context_lines:
            return None

        prompt = (
            "把用户最新的一句话改写成一条不依赖上下文的检索查询，用于在知识库中检索。\n"
            "要求：保留药品名/商品名/订单号等关键实体；不要回答问题；不要解释；"
            f"只输出查询本身，不超过 {REWRITE_MAX_CHARS} 字。\n\n"
            "对话历史：\n" + "\n".join(f"- {line}" for line in context_lines) + f"\n\n最新一句：{query}"
        )
        try:
            llm = get_chat_client(temperature=0)
            response = await llm.ainvoke(prompt)
        except LLMNotConfigured:
            return None
        except Exception as exc:  # noqa: BLE001 —— 改写失败就用原句，不能让检索挂掉
            logger.warning("query 改写失败，使用原句：%s", exc)
            return None
        text = str(getattr(response, "content", "") or "").strip().strip('"').strip()
        if not text or len(text) > REWRITE_MAX_CHARS * 2:
            return None
        return text

    async def _threshold(
        self,
        db: AsyncSession,
        kb_id: str,
        *,
        override: float | None,
        source: str,
    ) -> float:
        """选阈值：库级阈值只在余弦口径下才有意义，重排口径不查库。"""
        kb_threshold = await self._kb_threshold(db, kb_id) if source != "rerank" else None
        return resolve_threshold(source=source, override=override, kb_threshold=kb_threshold)

    async def _kb_threshold(self, db: AsyncSession, kb_id: str) -> float:
        try:
            kb_uuid = uuid.UUID(str(kb_id))
        except ValueError:
            return settings.score_threshold
        value = (
            await db.execute(
                select(KnowledgeBase.score_threshold).where(KnowledgeBase.id == kb_uuid)
            )
        ).scalar_one_or_none()
        return float(value) if value is not None else settings.score_threshold

    async def _enrich_titles(self, db: AsyncSession, chunks: list[RetrievedChunk]) -> None:
        """Milvus 里只有 doc_id，标题这类展示信息回 PG 取（一次批量查询）。"""
        doc_ids: list[uuid.UUID] = []
        for chunk in chunks:
            try:
                doc_ids.append(uuid.UUID(chunk.doc_id))
            except (ValueError, AttributeError):
                continue
        if not doc_ids:
            return
        rows = (
            await db.execute(
                select(KbDocument.id, KbDocument.title, KbDocument.source_url).where(
                    KbDocument.id.in_(set(doc_ids))
                )
            )
        ).all()
        titles = {str(doc_id): (title, url) for doc_id, title, url in rows}
        for chunk in chunks:
            pair = titles.get(str(chunk.doc_id))
            if pair:
                chunk.doc_title, chunk.source_url = pair

    async def _bump_hit_count(self, db: AsyncSession, chunks: list[RetrievedChunk]) -> None:
        """累计命中次数（后台「哪些段落最常被问」）。失败不影响检索。"""
        ids = [chunk.id for chunk in chunks if chunk.id]
        if not ids:
            return
        try:
            await db.execute(
                update(KbChunk)
                .where(KbChunk.vector_id.in_(ids))
                .values(hit_count=KbChunk.hit_count + 1)
            )
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.debug("更新 hit_count 失败：%s", exc)
            await db.rollback()

    async def _log(
        self,
        db: AsyncSession,
        result: RetrievalResult,
        *,
        role: UserRole | str,
        user_id: uuid.UUID | str | None,
        latency_ms: int,
        write_log: bool,
    ) -> None:
        if not write_log:
            return
        try:
            actor: uuid.UUID | None = None
            if user_id:
                actor = uuid.UUID(str(user_id))
            db.add(
                KbSearchLog(
                    query=result.query[:2000],
                    query_norm=normalize_query(result.query),
                    kb_ids=list(result.kb_ids),
                    role=role.value if isinstance(role, UserRole) else str(role),
                    actor_id=actor,
                    # 记「召回到几条」，不是「最终给了几条」：拒答时 chunks 被清空，
                    # 若按 chunks 记，所有 low_score 都会混进零召回榜，榜单就失效了
                    hit_count=len(result.chunks) + len(result.rejected_chunks),
                    top_score=float(result.top_score),
                    refused=result.refused,
                    reason=result.reason,
                    latency_ms=latency_ms,
                )
            )
            await db.commit()
        except Exception as exc:  # noqa: BLE001 —— 统计写入失败不该影响回答
            logger.debug("写检索日志失败：%s", exc)
            await db.rollback()


def _elapsed(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


_service: RetrievalService | None = None


def get_retrieval_service() -> RetrievalService:
    global _service
    if _service is None:
        _service = RetrievalService()
    return _service


def reset_retrieval_service() -> None:
    global _service
    _service = None
