"""语义记忆（M3-05，PRD FR6.3）：Milvus collection ``hhyy_memory``。

和 ``hhyy_kb_chunks`` 的区别要先说清楚，否则很容易照抄错：

| | 知识库 | 记忆 |
| --- | --- | --- |
| 生命周期 | 文档在就一直有效 | 180 天 TTL，到期不再召回 |
| 权限 | ``kb_id`` 过滤（角色 ACL） | **``user_id`` 强制过滤**（永不跨用户） |
| 写入者 | 管理员上传 | 用户自己说的一句话 |
| 精确性要求 | 高（要有原文出处） | 中（模糊同义就够） |

因此这里**没有**「查全库」的方法：``search`` 的签名第一个参数就是 ``user_id``，
过滤表达式由本模块拼，调用方无法绕过——这是 M1 里 ACL 的同一条纪律。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Sequence

from app.core.config import settings
from app.llm.embedding import EmbeddingError, embed_query, embed_texts
from app.memory.base import MemoryItem
from app.rag.milvus_repo import MilvusUnavailable, _escape

logger = logging.getLogger(__name__)

F_ID = "id"
F_USER = "user_id"
F_TYPE = "type"
F_CONTENT = "content"
F_DENSE = "dense"
F_CREATED = "created_at"
F_EXPIRES = "expires_at"
F_SOURCE = "source_message_id"
F_SENSITIVE = "sensitive"

OUTPUT_FIELDS = [F_ID, F_USER, F_TYPE, F_CONTENT, F_CREATED, F_EXPIRES, F_SOURCE, F_SENSITIVE]


def _user_expr(user_id: str, *, now: int | None = None) -> str:
    """权限 + TTL 过滤表达式。两件事必须同时成立，所以拼在一处、不拆开。"""
    ts = int(now if now is not None else time.time())
    return f'{F_USER} == "{_escape(str(user_id))}" and {F_EXPIRES} > {ts}'


class SemanticMemory:
    """``hhyy_memory`` 的唯一读写入口。"""

    def __init__(self, collection: str | None = None, *, dim: int | None = None) -> None:
        self.collection = collection or settings.memory_collection
        self.dim = dim or settings.embedding_dimensions
        self._client: Any | None = None
        self._ready = False

    @property
    def client(self) -> Any:
        if self._client is None:
            from pymilvus import MilvusClient

            kwargs: dict[str, Any] = {"uri": settings.milvus_uri}
            if settings.milvus_token:
                kwargs["token"] = settings.milvus_token
            try:
                self._client = MilvusClient(**kwargs)
            except Exception as exc:  # noqa: BLE001
                raise MilvusUnavailable(f"连接 Milvus 失败（{settings.milvus_uri}）：{exc}") from exc
        return self._client

    async def _call(self, fn_name: str, *args: Any, **kwargs: Any) -> Any:
        fn = getattr(self.client, fn_name)
        try:
            return await asyncio.to_thread(fn, *args, **kwargs)
        except MilvusUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            raise MilvusUnavailable(f"Milvus {fn_name} 失败：{exc}") from exc

    async def ensure_collection(self) -> None:
        if self._ready:
            return
        from pymilvus import DataType

        client = self.client
        exists = await asyncio.to_thread(client.has_collection, self.collection)
        if not exists:
            schema = client.create_schema(enable_dynamic_field=False)
            schema.add_field(F_ID, DataType.VARCHAR, is_primary=True, max_length=64)
            schema.add_field(F_USER, DataType.VARCHAR, max_length=64)
            schema.add_field(F_TYPE, DataType.VARCHAR, max_length=16)
            schema.add_field(F_CONTENT, DataType.VARCHAR, max_length=4096)
            schema.add_field(F_DENSE, DataType.FLOAT_VECTOR, dim=self.dim)
            schema.add_field(F_CREATED, DataType.INT64, default_value=0)
            schema.add_field(F_EXPIRES, DataType.INT64, default_value=0)
            schema.add_field(F_SOURCE, DataType.VARCHAR, max_length=64, default_value="")
            schema.add_field(F_SENSITIVE, DataType.BOOL, default_value=False)

            index_params = client.prepare_index_params()
            index_params.add_index(
                field_name=F_DENSE,
                index_type="HNSW",
                metric_type="COSINE",
                params={"M": 16, "efConstruction": 200},
            )
            # 每用户一条过滤条件，必须走 INVERTED；否则「按人隔离」会退化成全表扫
            index_params.add_index(field_name=F_USER, index_type="INVERTED")
            try:
                await asyncio.to_thread(
                    client.create_collection,
                    collection_name=self.collection,
                    schema=schema,
                    index_params=index_params,
                )
                logger.info("已创建 Milvus collection %s（语义记忆）", self.collection)
            except Exception as exc:  # noqa: BLE001 —— 并发建集合时可能已存在
                if not await asyncio.to_thread(client.has_collection, self.collection):
                    raise MilvusUnavailable(f"创建记忆 collection 失败：{exc}") from exc
        await self._call("load_collection", self.collection)
        self._ready = True

    # ------------------------------------------------------------------ 写入
    async def add(self, items: Sequence[MemoryItem]) -> list[str | None]:
        """写入一批记忆，返回每条的向量 id（失败为 ``None``）。

        所有类型都写向量——包括 ``risk``（过敏、孕期）。早期版本把敏感项排除在外，
        结果「我对青霉素过敏」这条永远检索不到，跨会话记忆直接失效（M3 验收项）。
        敏感项的风险靠**注入时的措辞和用户的删除权**控制，而不是靠不检索。
        """
        targets = [item for item in items if item.content.strip()]
        if not targets:
            return [None] * len(items)
        try:
            vectors = await embed_texts([item.content[:2000] for item in targets])
        except EmbeddingError as exc:
            logger.warning("记忆向量化失败（条目保留在 PG）：%s", exc)
            return [None] * len(items)

        await self.ensure_collection()
        now = int(time.time())
        ttl_days = settings.memory_ttl_days
        rows = []
        for item, vector in zip(targets, vectors):
            expires = int(item.expires_at.timestamp()) if item.expires_at else now + ttl_days * 86400
            rows.append(
                {
                    F_ID: str(item.id),
                    F_USER: str(item.user_id),
                    F_TYPE: item.type,
                    F_CONTENT: item.content[:4096],
                    F_DENSE: list(vector),
                    F_CREATED: int(item.created_at.timestamp()) if item.created_at else now,
                    F_EXPIRES: expires,
                    F_SOURCE: str(item.source_message_id or ""),
                    F_SENSITIVE: bool(item.sensitive),
                }
            )
        await self._call("upsert", collection_name=self.collection, data=rows)
        await self._call("flush", self.collection)

        ids: list[str | None] = []
        for item in items:
            ids.append(str(item.id) if item.content.strip() else None)
        return ids

    async def delete(self, ids: Sequence[str]) -> None:
        if not ids:
            return
        await self.ensure_collection()
        quoted = ", ".join(f'"{_escape(str(i))}"' for i in ids)
        await self._call("delete", self.collection, filter=f"{F_ID} in [{quoted}]")

    async def delete_user(self, user_id: str) -> None:
        await self.ensure_collection()
        await self._call("delete", self.collection, filter=_user_expr(user_id, now=0))

    # ------------------------------------------------------------------ 读取
    async def search(self, user_id: str, query: str, *, limit: int = 3) -> list[MemoryItem]:
        """按当前用户检索 top-k 记忆。**过滤条件在第一行**，没有「不传用户」的用法。"""
        if not query.strip():
            return []
        try:
            vector = await embed_query(query)
        except EmbeddingError as exc:
            logger.warning("记忆检索向量化失败：%s", exc)
            return []

        await self.ensure_collection()
        hits = await self._call(
            "search",
            collection_name=self.collection,
            data=[list(vector)],
            anns_field=F_DENSE,
            search_params={"metric_type": "COSINE", "params": {"ef": 64}},
            limit=max(1, limit),
            filter=_user_expr(str(user_id)),
            output_fields=OUTPUT_FIELDS,
        )
        results: list[MemoryItem] = []
        for hit in hits[0] if hits else []:
            entity = hit.get("entity") or hit
            results.append(
                MemoryItem(
                    id=str(hit.get("id", entity.get(F_ID, ""))),
                    user_id=str(entity.get(F_USER, "")),
                    type=str(entity.get(F_TYPE, "fact")),
                    content=str(entity.get(F_CONTENT, "")),
                    score=round(float(hit.get("distance", 0.0)), 4),
                    sensitive=bool(entity.get(F_SENSITIVE, False)),
                    source_message_id=str(entity.get(F_SOURCE) or "") or None,
                )
            )
        return results

    async def count(self, user_id: str) -> int:
        await self.ensure_collection()
        rows = await self._call(
            "query",
            collection_name=self.collection,
            filter=_user_expr(str(user_id), now=0),
            output_fields=["count(*)"],
        )
        return int(rows[0].get("count(*)", 0)) if rows else 0

    async def health(self) -> dict[str, Any]:
        try:
            await self.ensure_collection()
            return {"memory_collection": self.collection, "milvus": "ok", "dim": self.dim}
        except Exception as exc:  # noqa: BLE001
            return {"memory_collection": self.collection, "milvus": "unavailable", "error": str(exc)}


def get_semantic_memory() -> SemanticMemory:
    """每次新建一个轻量壳（内部 client 懒加载），便于测试注入替身。"""
    return SemanticMemory()
