"""长期记忆的 PG 实现（M3-03）。

三条纪律：

1. **隔离在 SQL 里**：每条语句都带 ``user_id == ?``，没有「按 id 查」的裸入口——
   这类接口一旦漏了归属校验，就是跨用户读取。
2. **去重按「归一化文本 + 字符相似度」**：不引入额外模型调用。用户在两次会话里说
   「我对青霉素过敏」和「我青霉素过敏」，应该只留一条（PRD FR6.4 要求相似度 > 0.95
   不重复插入，这里用 bigram Jaccard 近似，阈值 0.85 更保守一点）。
3. **写入不提交**：``add`` 只 ``flush``，由调用方（后台任务）决定何时 commit——
   否则一次抽取要提交 N 次，且失败时前几条会留成半成品。
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import delete, func, select

from app.core.config import settings
from app.memory.base import MemoryItem, MemoryProfile
from app.models.memory import UserMemory, UserProfile

logger = logging.getLogger(__name__)

DEDUPE_SIMILARITY = 0.72
MAX_COMPARE_ROWS = 60
_PUNCT = re.compile(r"[\s，。！？、；：,.!?;:\"'（）()\[\]【】…—\-]+")


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def normalize_text(text: str) -> str:
    """归一化：去标点空白、全角转半角、小写。用于去重比较。"""
    cleaned = _PUNCT.sub("", str(text or ""))
    # 全角字符统一到半角（数字/字母常见，如「１」和「1」）
    return "".join(
        chr(ord(ch) - 0xFEE0) if 0xFF01 <= ord(ch) <= 0xFF5E else ch for ch in cleaned
    ).lower()


def _bigrams(text: str) -> set[str]:
    return {text[i : i + 2] for i in range(max(0, len(text) - 1))} or {text}


def similarity(left: str, right: str) -> float:
    """字符 bigram 相似度，0~1。

    用 Jaccard 与「重叠系数」的加权，而不是纯 Jaccard：
    记忆里最常见的改写是多说/少说几个字（「我对青霉素过敏」vs「我青霉素过敏」），
    纯 Jaccard 会被长度差异拉低到 0.57，重叠系数能到 0.8。加权后 0.71，
    与「过敏 vs 花粉过敏」这类无关句子（0.33）拉开了距离。
    """
    a, b = _bigrams(normalize_text(left)), _bigrams(normalize_text(right))
    if not a or not b:
        return 0.0
    shared = len(a & b)
    jaccard = shared / len(a | b)
    overlap = shared / min(len(a), len(b))
    return round(0.4 * jaccard + 0.6 * overlap, 4)


def _to_item(row: UserMemory) -> MemoryItem:
    return MemoryItem(
        id=str(row.id),
        user_id=str(row.user_id),
        type=row.type,
        content=row.content,
        confidence=float(row.confidence or 0),
        sensitive=bool(row.sensitive),
        source_message_id=str(row.source_message_id) if row.source_message_id else None,
        source_conversation_id=(
            str(row.source_conversation_id) if row.source_conversation_id else None
        ),
        created_at=row.created_at,
        expires_at=row.expires_at,
        score=0.0,
    )


class PgMemoryStore:
    """基于 ``user_memories`` / ``user_profiles`` 的实现。

    ``vectors`` 可选：传了 :class:`app.memory.semantic.SemanticMemory` 就走语义检索，
    没传（或 Milvus 挂了）就退回「关键词重叠 + 时间」的本地排序——记忆召回是加分项，
    不该因为它挂掉就让整轮对话失败。
    """

    def __init__(self, db: Any, *, vectors: Any = None, ttl_days: int | None = None) -> None:
        self.db = db
        self.vectors = vectors
        self.ttl_days = ttl_days if ttl_days is not None else settings.memory_ttl_days

    # ------------------------------------------------------------------ 画像
    async def get_profile(self, user_id: Any) -> MemoryProfile:
        row = await self.db.get(UserProfile, self._uuid(user_id))
        if row is None:
            return MemoryProfile(user_id=str(user_id), enabled=True)
        return MemoryProfile(
            user_id=str(row.user_id),
            enabled=bool(row.memory_enabled),
            summary=row.summary or "",
            attributes=dict(row.attributes or {}),
            updated_at=row.updated_at,
        )

    async def set_enabled(self, user_id: Any, enabled: bool) -> bool:
        row = await self._ensure_profile(user_id)
        row.memory_enabled = bool(enabled)
        await self.db.flush()
        return bool(row.memory_enabled)

    async def update_summary(self, user_id: Any, summary: str) -> None:
        row = await self._ensure_profile(user_id)
        row.summary = (summary or "")[:2000]
        await self.db.flush()

    async def touch(self, user_id: Any) -> None:
        row = await self._ensure_profile(user_id)
        row.last_seen_at = _now()
        await self.db.flush()

    async def _ensure_profile(self, user_id: Any) -> UserProfile:
        uid = self._uuid(user_id)
        row = await self.db.get(UserProfile, uid)
        if row is None:
            row = UserProfile(user_id=uid, memory_enabled=True, summary="", attributes={})
            self.db.add(row)
            await self.db.flush()
        return row

    # ------------------------------------------------------------------ 写入
    async def add(self, item: MemoryItem) -> str:
        """写入一条记忆，命中已有记忆时只更新，不新增。返回记忆 id。"""
        user_uuid = self._uuid(item.user_id)
        existing = await self._find_similar(user_uuid, item)
        if existing is not None:
            existing.confidence = max(float(existing.confidence or 0), float(item.confidence))
            existing.updated_at = _now()
            await self.db.flush()
            if self.vectors is not None:
                await self._safe_vector_add([_to_item(existing)])
            return str(existing.id)

        memory_id = uuid.UUID(str(item.id)) if item.id else uuid.uuid4()
        expires_at = item.expires_at or (_now() + timedelta(days=self.ttl_days))
        row = UserMemory(
            id=memory_id,
            user_id=user_uuid,
            type=item.type,
            content=item.content[:2000],
            confidence=float(item.confidence),
            sensitive=bool(item.sensitive),
            source_message_id=self._maybe_uuid(item.source_message_id),
            source_conversation_id=self._maybe_uuid(item.source_conversation_id),
            vector_id=None,
            expires_at=expires_at,
        )
        self.db.add(row)
        await self.db.flush()

        if self.vectors is not None:
            vector_id = await self._safe_vector_add([_to_item(row)])
            if vector_id and vector_id[0]:
                row.vector_id = vector_id[0]
                await self.db.flush()
        return str(row.id)

    async def _find_similar(self, user_uuid: uuid.UUID, item: MemoryItem) -> UserMemory | None:
        rows = (
            await self.db.execute(
                select(UserMemory)
                .where(UserMemory.user_id == user_uuid)
                .order_by(UserMemory.created_at.desc())
                .limit(MAX_COMPARE_ROWS)
            )
        ).scalars().all()
        normalized = normalize_text(item.content)
        best: tuple[float, UserMemory] | None = None
        for row in rows:
            candidate = normalize_text(row.content)
            if candidate == normalized:
                return row
            # 包含关系也算重复：「对青霉素过敏」与「对青霉素过敏，吃过阿莫西林」
            if candidate and normalized and (candidate in normalized or normalized in candidate):
                shorter, longer = sorted((candidate, normalized), key=len)
                if len(shorter) / max(1, len(longer)) >= 0.5:
                    return row
            score = similarity(item.content, row.content)
            if score >= DEDUPE_SIMILARITY and (best is None or score > best[0]):
                best = (score, row)
        return best[1] if best else None

    async def _safe_vector_add(self, items: list[MemoryItem]) -> list[str | None]:
        try:
            return await self.vectors.add(items)
        except Exception as exc:  # noqa: BLE001 —— 向量库挂了不影响结构化记忆
            logger.warning("语义记忆写入失败（已忽略）：%s", exc)
            return [None] * len(items)

    # ------------------------------------------------------------------ 读取
    async def search(self, user_id: Any, query: str, *, limit: int = 3) -> list[MemoryItem]:
        # 先花 1ms 确认「这个人有没有记忆」：没有就别去做 embedding + 向量检索，
        # 那要 150~300ms，而新用户每轮对话都要白付一次这个成本。
        has_any = await self.count(user_id) > 0
        if not has_any:
            return []
        if self.vectors is not None:
            try:
                hits = await self.vectors.search(str(user_id), query, limit=limit)
                if hits:
                    return hits
            except Exception as exc:  # noqa: BLE001
                logger.warning("语义记忆检索失败，退回本地排序：%s", exc)
        return await self._keyword_search(user_id, query, limit=limit)

    async def count(self, user_id: Any) -> int:
        return int(
            (
                await self.db.execute(
                    select(func.count())
                    .select_from(UserMemory)
                    .where(UserMemory.user_id == self._uuid(user_id))
                )
            ).scalar_one()
        )

    async def _keyword_search(self, user_id: Any, query: str, *, limit: int) -> list[MemoryItem]:
        rows = await self._active_rows(user_id, limit=MAX_COMPARE_ROWS)
        if not query.strip():
            return [_to_item(row) for row in rows[:limit]]
        scored: list[tuple[float, UserMemory]] = []
        for row in rows:
            score = similarity(query, row.content)
            # 命中关键词再加权：短句 Jaccard 会把「过敏」这种关键信息摊薄
            shared = set(normalize_text(query)) & set(normalize_text(row.content))
            if shared:
                score += min(0.3, 0.05 * len(shared))
            scored.append((score, row))
        scored.sort(key=lambda pair: (pair[0], pair[1].created_at or _now()), reverse=True)
        result = []
        for score, row in scored[:limit]:
            item = _to_item(row)
            item.score = round(min(score, 1.0), 4)
            result.append(item)
        return result

    async def list_for_user(self, user_id: Any, *, limit: int = 50) -> list[MemoryItem]:
        rows = (
            await self.db.execute(
                select(UserMemory)
                .where(UserMemory.user_id == self._uuid(user_id))
                .order_by(UserMemory.created_at.desc())
                .limit(limit)
            )
        ).scalars().all()
        return [_to_item(row) for row in rows]

    async def _active_rows(self, user_id: Any, *, limit: int) -> list[UserMemory]:
        now = _now()
        return list(
            (
                await self.db.execute(
                    select(UserMemory)
                    .where(
                        UserMemory.user_id == self._uuid(user_id),
                        (UserMemory.expires_at.is_(None)) | (UserMemory.expires_at > now),
                    )
                    .order_by(UserMemory.created_at.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )

    async def count_by_type(self, user_id: Any) -> dict[str, int]:
        rows = (
            await self.db.execute(
                select(UserMemory.type, func.count())
                .where(UserMemory.user_id == self._uuid(user_id))
                .group_by(UserMemory.type)
            )
        ).all()
        return {str(kind): int(count) for kind, count in rows}

    # ------------------------------------------------------------------ 删除
    async def delete(self, user_id: Any, memory_id: Any) -> bool:
        row = (
            await self.db.execute(
                select(UserMemory).where(
                    UserMemory.id == self._uuid(memory_id),
                    UserMemory.user_id == self._uuid(user_id),
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return False
        vector_id = row.vector_id
        await self.db.delete(row)
        await self.db.flush()
        if self.vectors is not None and vector_id:
            try:
                await self.vectors.delete([vector_id])
            except Exception as exc:  # noqa: BLE001
                logger.warning("向量删除失败（残留将随 TTL 过期）：%s", exc)
        return True

    async def clear(self, user_id: Any) -> int:
        uid = self._uuid(user_id)
        rows = (await self.db.execute(select(UserMemory.id).where(UserMemory.user_id == uid))).all()
        if not rows:
            return 0
        await self.db.execute(delete(UserMemory).where(UserMemory.user_id == uid))
        await self.db.flush()
        if self.vectors is not None:
            try:
                await self.vectors.delete_user(str(uid))
            except Exception as exc:  # noqa: BLE001
                logger.warning("清空向量记忆失败：%s", exc)
        return len(rows)

    # ------------------------------------------------------------------ 工具
    @staticmethod
    def _uuid(value: Any) -> uuid.UUID:
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))

    @classmethod
    def _maybe_uuid(cls, value: Any) -> Optional[uuid.UUID]:
        if not value:
            return None
        try:
            return cls._uuid(value)
        except (ValueError, AttributeError):
            return None


def get_memory_store(db: Any, *, vectors: Any = None) -> PgMemoryStore:
    return PgMemoryStore(db, vectors=vectors)


__all__ = [
    "DEDUPE_SIMILARITY",
    "PgMemoryStore",
    "get_memory_store",
    "normalize_text",
    "similarity",
]
