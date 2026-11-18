"""Milvus 访问层（M1-02）。

**单 collection + ``kb_id`` 强制过滤**（PRD §6.3 的 ADR）。这一层是唯一直接碰
Milvus 的地方，两条纪律写在代码里：

1. 所有检索方法都**必须**收到 ``expr``（权限过滤表达式），没有「查全库」的入口。
   调用方拿不到裸 client，从结构上防止越权召回。
2. 检索结果是同步的 pymilvus 调用，统一用 ``asyncio.to_thread`` 丢到线程池，
   避免一次向量查询把整个事件循环卡住。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Sequence
from functools import lru_cache
from typing import Any

from app.core.config import settings
from app.rag.base import RetrievedChunk

logger = logging.getLogger(__name__)

# 字段名常量：字符串散落在三四个文件里最容易写错，收在一处
F_ID = "id"
F_KB = "kb_id"
F_DOC = "doc_id"
F_INDEX = "chunk_index"
F_SECTION = "section"
F_CONTENT = "content"
F_DENSE = "dense"
F_SPARSE = "sparse"
F_PAGE = "page"
F_ROLE_TAGS = "role_tags"
F_STATUS = "status"
F_FROM = "effective_from"
F_TO = "effective_to"
F_CREATED = "created_at"

OUTPUT_FIELDS = [F_ID, F_KB, F_DOC, F_INDEX, F_SECTION, F_CONTENT, F_PAGE]

PUBLISHED = "published"


class MilvusUnavailable(RuntimeError):
    """连不上 Milvus 或建集合失败。调用方应降级而不是 500。"""


def _escape(value: str) -> str:
    """表达式里的字符串字面量转义，防止 ``"`` 提前闭合。"""
    return value.replace("\\", "\\\\").replace('"', '\\"')


class MilvusRepo:
    """``hhyy_kb_chunks`` 的唯一读写入口。"""

    def __init__(self, collection: str | None = None, *, dim: int | None = None) -> None:
        self.collection = collection or settings.rag_collection
        self.dim = dim or settings.embedding_dimensions
        self._client: Any | None = None
        self._ready = False

    # ------------------------------------------------------------------ 连接
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
        """把同步的 pymilvus 调用丢进线程池。"""
        fn = getattr(self.client, fn_name)
        try:
            return await asyncio.to_thread(fn, *args, **kwargs)
        except MilvusUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            raise MilvusUnavailable(f"Milvus {fn_name} 失败：{exc}") from exc

    def _build_schema(self) -> Any:
        from pymilvus import DataType, Function, FunctionType

        client = self.client
        schema = client.create_schema(enable_dynamic_field=False)
        schema.add_field(F_ID, DataType.VARCHAR, is_primary=True, max_length=64)
        schema.add_field(F_KB, DataType.VARCHAR, max_length=64)
        schema.add_field(F_DOC, DataType.VARCHAR, max_length=64)
        schema.add_field(F_INDEX, DataType.INT64)
        schema.add_field(F_SECTION, DataType.VARCHAR, max_length=128)
        # enable_analyzer + chinese：中文分词交给 Milvus 服务端（内部用 jieba），
        # 这样 BM25 稀疏向量由服务端自动生成，客户端不用自己算词频
        schema.add_field(
            F_CONTENT,
            DataType.VARCHAR,
            max_length=8192,
            enable_analyzer=True,
            analyzer_params={"type": "chinese"},
        )
        schema.add_field(F_DENSE, DataType.FLOAT_VECTOR, dim=self.dim)
        schema.add_field(F_SPARSE, DataType.SPARSE_FLOAT_VECTOR)
        schema.add_field(F_STATUS, DataType.VARCHAR, max_length=16, default_value=PUBLISHED)
        schema.add_field(F_PAGE, DataType.INT64, default_value=0)
        schema.add_field(
            F_ROLE_TAGS,
            DataType.ARRAY,
            element_type=DataType.VARCHAR,
            max_capacity=8,
            max_length=32,
        )
        schema.add_field(F_FROM, DataType.INT64, default_value=0)
        schema.add_field(F_TO, DataType.INT64, default_value=0)
        schema.add_field(F_CREATED, DataType.INT64, default_value=0)
        schema.add_function(
            Function(
                name="bm25_content",
                function_type=FunctionType.BM25,
                input_field_names=[F_CONTENT],
                output_field_names=[F_SPARSE],
            )
        )
        return schema

    async def ensure_collection(self) -> None:
        """集合不存在就建（含索引与 BM25 函数），并 load 到内存。"""
        if self._ready:
            return
        client = self.client
        exists = await asyncio.to_thread(client.has_collection, self.collection)
        if not exists:
            schema = await asyncio.to_thread(self._build_schema)
            index_params = client.prepare_index_params()
            index_params.add_index(
                field_name=F_DENSE,
                index_type="HNSW",
                metric_type="COSINE",
                params={"M": 16, "efConstruction": 200},
            )
            index_params.add_index(
                field_name=F_SPARSE, index_type="SPARSE_INVERTED_INDEX", metric_type="BM25"
            )
            # 标量索引：kb_id 是权限过滤的第一道闸门，必须走 INVERTED 而不是全表扫
            index_params.add_index(field_name=F_KB, index_type="INVERTED")
            index_params.add_index(field_name=F_STATUS, index_type="INVERTED")
            index_params.add_index(field_name=F_DOC, index_type="INVERTED")
            try:
                await asyncio.to_thread(
                    client.create_collection,
                    collection_name=self.collection,
                    schema=schema,
                    index_params=index_params,
                )
                logger.info("已创建 Milvus collection %s（dim=%d）", self.collection, self.dim)
            except Exception as exc:  # noqa: BLE001 —— 并发建集合时可能已存在
                if not await asyncio.to_thread(client.has_collection, self.collection):
                    raise MilvusUnavailable(f"创建 collection 失败：{exc}") from exc
        await self._call("load_collection", self.collection)
        self._ready = True

    # ------------------------------------------------------------------ 写入
    async def upsert_chunks(self, rows: Sequence[dict[str, Any]]) -> int:
        """写入/覆盖分块向量。``id`` 为 ``{doc_id}_{chunk_index}``，重复索引不会造成重复。"""
        if not rows:
            return 0
        await self.ensure_collection()
        # BM25 的稀疏向量由服务端根据 content 自动生成，客户端不能也不该传
        payload = [{k: v for k, v in row.items() if k != F_SPARSE} for row in rows]
        await self._call("upsert", collection_name=self.collection, data=payload)
        await self._call("flush", self.collection)
        return len(payload)

    async def delete_by_doc(self, doc_id: str) -> None:
        await self.ensure_collection()
        await self._call(
            "delete", self.collection, filter=f'{F_DOC} == "{_escape(str(doc_id))}"'
        )

    async def delete_by_kb(self, kb_id: str) -> None:
        await self.ensure_collection()
        await self._call(
            "delete", self.collection, filter=f'{F_KB} == "{_escape(str(kb_id))}"'
        )

    async def flush(self) -> None:
        await self._call("flush", self.collection)

    # ------------------------------------------------------------------ 读取
    async def count(self, *, kb_id: str | None = None, doc_id: str | None = None) -> int:
        await self.ensure_collection()
        conditions = []
        if kb_id:
            conditions.append(f'{F_KB} == "{_escape(str(kb_id))}"')
        if doc_id:
            conditions.append(f'{F_DOC} == "{_escape(str(doc_id))}"')
        expr = " and ".join(conditions) if conditions else None
        result = await self._call(
            "query",
            collection_name=self.collection,
            filter=expr,
            output_fields=["count(*)"],
        )
        if not result:
            return 0
        return int(result[0].get("count(*)", 0))

    def _to_chunk(self, hit: dict[str, Any], *, score_key: str = "distance") -> RetrievedChunk:
        # pymilvus 3.x 把 output_fields 摊平在 hit 顶层，老版本放在 entity 里，两种都兼容
        entity = hit.get("entity") or hit
        return RetrievedChunk(
            id=str(hit.get("id", entity.get(F_ID, ""))),
            content=str(entity.get(F_CONTENT, "")),
            score=float(hit.get(score_key, 0.0)),
            kb_id=str(entity.get(F_KB, "")),
            doc_id=str(entity.get(F_DOC, "")),
            section=entity.get(F_SECTION) or None,
            page=int(entity.get(F_PAGE) or 0) or None,
            metadata={
                "chunk_index": int(entity.get(F_INDEX) or 0),
                "raw_score": float(hit.get(score_key, 0.0)),
            },
        )

    async def hybrid_search(
        self,
        query_vector: Sequence[float],
        query_text: str,
        *,
        expr: str,
        limit: int | None = None,
    ) -> list[RetrievedChunk]:
        """dense + BM25 稀疏向量并行召回，RRF(k=60) 融合（PRD FR3.4）。"""
        from pymilvus import AnnSearchRequest, RRFRanker

        await self.ensure_collection()
        top = limit or settings.retrieval_top_k
        requests = [
            AnnSearchRequest(
                data=[list(query_vector)],
                anns_field=F_DENSE,
                param={"metric_type": "COSINE", "params": {"ef": 64}},
                limit=top,
                expr=expr,
            ),
            AnnSearchRequest(
                # 稀疏这一路直接传原文，服务端做分词与 BM25 打分
                data=[query_text],
                anns_field=F_SPARSE,
                param={"metric_type": "BM25"},
                limit=top,
                expr=expr,
            ),
        ]
        hits = await self._call(
            "hybrid_search",
            collection_name=self.collection,
            reqs=requests,
            ranker=RRFRanker(60),
            limit=top,
            output_fields=OUTPUT_FIELDS,
        )
        return [self._to_chunk(hit) for hit in (hits[0] if hits else [])]

    async def dense_search(
        self,
        query_vector: Sequence[float],
        *,
        expr: str,
        limit: int | None = None,
    ) -> list[RetrievedChunk]:
        """纯稠密检索，分数是余弦相似度（0~1）。

        没有 reranker 时走这条路：RRF 的融合分（0.0x 量级）没法直接和
        「相似度阈值 0.30」比较，而余弦相似度可以。这一点在 retriever 里会再解释。
        """
        await self.ensure_collection()
        top = limit or settings.retrieval_top_k
        hits = await self._call(
            "search",
            collection_name=self.collection,
            data=[list(query_vector)],
            anns_field=F_DENSE,
            search_params={"metric_type": "COSINE", "params": {"ef": 64}},
            limit=top,
            filter=expr,
            output_fields=OUTPUT_FIELDS,
        )
        return [self._to_chunk(hit) for hit in (hits[0] if hits else [])]

    async def list_ids(self, *, doc_id: str) -> list[str]:
        """列出某文档已入库的向量 id，用于删除补偿与对账。"""
        await self.ensure_collection()
        rows = await self._call(
            "query",
            collection_name=self.collection,
            filter=f'{F_DOC} == "{_escape(str(doc_id))}"',
            output_fields=[F_ID],
        )
        return [str(row[F_ID]) for row in rows]

    async def health(self) -> dict[str, Any]:
        """给 /health 用的轻量探活。"""
        try:
            await self.ensure_collection()
            return {"milvus": "ok", "collection": self.collection, "dim": self.dim}
        except Exception as exc:  # noqa: BLE001
            return {"milvus": "unavailable", "error": str(exc)}

    async def drop_collection(self) -> None:
        """仅测试与重置用。"""
        client = self.client
        if await asyncio.to_thread(client.has_collection, self.collection):
            await asyncio.to_thread(client.drop_collection, self.collection)
        self._ready = False


def build_chunk_row(
    *,
    chunk_id: str,
    kb_id: str,
    doc_id: str,
    chunk_index: int,
    content: str,
    section: str | None,
    page: int | None,
    dense: Sequence[float],
    role_tags: Sequence[str] = (),
    effective_from: int = 0,
    effective_to: int = 0,
) -> dict[str, Any]:
    """构造一行待写入数据。字段顺序与 schema 对齐，缺字段由服务端 default 补。"""
    return {
        F_ID: chunk_id,
        F_KB: kb_id,
        F_DOC: doc_id,
        F_INDEX: int(chunk_index),
        F_SECTION: (section or "")[:128],
        F_CONTENT: content[:8192],
        F_DENSE: list(dense),
        F_PAGE: int(page or 0),
        F_ROLE_TAGS: [str(tag)[:32] for tag in list(role_tags)[:8]],
        F_STATUS: PUBLISHED,
        F_FROM: int(effective_from),
        F_TO: int(effective_to),
        F_CREATED: int(time.time()),
    }


@lru_cache(maxsize=2)
def get_milvus_repo(collection: str | None = None) -> MilvusRepo:
    return MilvusRepo(collection)


def reset_milvus_cache() -> None:
    """测试用：清掉连接缓存。"""
    get_milvus_repo.cache_clear()
