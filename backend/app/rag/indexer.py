"""索引流水线（M1-05）。

状态机（PRD FR2.2）::

    pending → parsing → chunking → embedding → ready
                                           ↘ failed（带 error_msg，可重试）

三个工程细节值得单独说：

1. **先把 chunk 正文写进 PG，再写向量**。正文是「真源」，向量可重建；
   顺序反了会出现「向量库里有一条，PG 里查不到」的孤儿数据。
2. **断点续传靠 ``last_indexed_offset``**。每成功写入一批就更新游标并 commit，
   所以「中途 kill 进程」后重跑是从断点继续，而不是从头再来——也就不会出现
   重复向量（向量 id 是 ``{doc_id}_{chunk_index}``，upsert 天然幂等，
   但对账时游标仍然是对「到底索引到第几条」的唯一答案）。
3. **重索引先清旧向量**。文档内容变化后（重新解析），旧的向量必须删掉，
   否则同一篇文档会同时存在新旧两版内容。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import BASE_DIR, settings
from app.llm.embedding import EmbeddingError, embed_texts
from app.models.kb import (
    ChunkStrategy,
    DocumentSource,
    DocumentStatus,
    KbChunk,
    KbDocument,
    KnowledgeBase,
)
from app.rag.chunker import chunk_document, reassemble
from app.rag.milvus_repo import MilvusRepo, MilvusUnavailable, build_chunk_row, get_milvus_repo
from app.rag.parser import ParsedDoc, ParseError, parse_docx, parse_pdf, parse_plain_text, parse_url

logger = logging.getLogger(__name__)

EMBED_BATCH = 32


class IndexingError(RuntimeError):
    """索引失败（已写入 ``doc.error_msg``）。"""


@dataclass(slots=True)
class IndexOutcome:
    doc_id: str
    status: str
    chunk_count: int
    error: str | None = None
    resumed_from: int = 0


def storage_root() -> Path:
    """上传文件的落盘根目录（按仓库根解析，避免受启动 CWD 影响）。"""
    root = BASE_DIR / settings.kb_storage_dir
    root.mkdir(parents=True, exist_ok=True)
    return root


def _to_timestamp(value: date | None, *, end_of_day: bool = False) -> int:
    if not value:
        return 0
    moment = datetime.combine(value, time.max if end_of_day else time.min)
    return int(moment.replace(tzinfo=timezone.utc).timestamp())


async def _load_parsed(doc: KbDocument) -> ParsedDoc:
    """按来源类型解析出 ``ParsedDoc``。"""
    source = doc.source_type or DocumentSource.MANUAL.value
    if source == DocumentSource.URL.value:
        if not doc.source_url:
            raise IndexingError("URL 文档缺少 source_url")
        return await parse_url(doc.source_url)

    if source == DocumentSource.MANUAL.value:
        if not doc.file_path:
            raise IndexingError("手工录入的文档缺少正文文件")
        text = Path(doc.file_path).read_text(encoding="utf-8")
        return parse_plain_text(text, source_type=source)

    if not doc.file_path:
        raise IndexingError("文件路径为空")
    path = Path(doc.file_path)
    if not path.exists():
        raise IndexingError(f"文件已不存在：{path.name}")
    data = path.read_bytes()

    if source == DocumentSource.PDF.value:
        return parse_pdf(data)
    if source == DocumentSource.DOCX.value:
        return parse_docx(data)
    return parse_plain_text(data.decode("utf-8", errors="replace"), source_type=source)


def _set_status(doc: KbDocument, status: DocumentStatus) -> None:
    doc.status = status.value


async def index_document(
    db: AsyncSession,
    doc_id: uuid.UUID | str,
    *,
    repo: MilvusRepo | None = None,
) -> IndexOutcome:
    """解析 → 分块 → 写 PG → 批量写向量。失败不抛，落库并可重试。"""
    repo = repo or get_milvus_repo()
    document = (
        await db.execute(select(KbDocument).where(KbDocument.id == uuid.UUID(str(doc_id))))
    ).scalar_one_or_none()
    if document is None:
        return IndexOutcome(doc_id=str(doc_id), status="missing", chunk_count=0, error="文档不存在")

    kb = (
        await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == document.kb_id))
    ).scalar_one_or_none()
    if kb is None:
        document.status = DocumentStatus.FAILED.value
        document.error_msg = "所属知识库不存在"
        await db.commit()
        return IndexOutcome(str(doc_id), document.status, 0, document.error_msg)

    resumed_from = int(document.last_indexed_offset or 0)

    try:
        # ---------- 1. 解析 ----------
        _set_status(document, DocumentStatus.PARSING)
        document.error_msg = None
        await db.commit()
        parsed = await _load_parsed(document)

        # ---------- 2. 分块 ----------
        _set_status(document, DocumentStatus.CHUNKING)
        await db.commit()
        strategy = kb.chunk_strategy or ChunkStrategy.STRUCTURED.value
        chunks = chunk_document(parsed, strategy=strategy)
        if not chunks:
            raise IndexingError("解析成功但没有得到任何分块（文档可能是空的）")

        # 切分自检：拼回去必须和「喂给分块器的输入」一致，否则说明切分逻辑丢了字。
        # 注意输入随策略不同：structured 吃的是各小节正文，recursive 吃的是整篇文本。
        if strategy == ChunkStrategy.STRUCTURED.value and parsed.sections:
            source_text = "".join(section.text for section in parsed.sections)
        else:
            source_text = parsed.text
        if reassemble(chunks).strip() != source_text.strip():
            logger.warning(
                "文档 %s 分块无法逐字还原原文（chunk 数 %d），请检查切分策略",
                document.id,
                len(chunks),
            )

        # ---------- 3. 写 PG（清旧数据） ----------
        await db.execute(delete(KbChunk).where(KbChunk.doc_id == document.id))
        role_tags = await _role_tags_for(db, kb)
        effective_from = _to_timestamp(document.effective_from)
        effective_to = _to_timestamp(document.effective_to, end_of_day=True)

        chunk_rows: list[KbChunk] = []
        for chunk in chunks:
            chunk_rows.append(
                KbChunk(
                    doc_id=document.id,
                    kb_id=document.kb_id,
                    chunk_index=chunk.index,
                    section=chunk.section,
                    content=chunk.content,
                    token_count=chunk.token_count,
                    vector_id=f"{document.id}_{chunk.index}",
                    page=chunk.page,
                )
            )
        db.add_all(chunk_rows)
        document.chunk_count = len(chunk_rows)
        _set_status(document, DocumentStatus.EMBEDDING)
        await db.commit()

        await repo.ensure_collection()

        # 「重新解析」把游标清零 → 全文重建（先清向量）；
        # 「失败重试」保留游标 → 断点续传，已写入的向量不动。
        resuming = 0 < resumed_from < len(chunks)
        if resuming:
            logger.info("文档 %s 从断点 %d/%d 续传", document.id, resumed_from, len(chunks))
        else:
            await repo.delete_by_doc(str(document.id))
            document.last_indexed_offset = 0
            await db.commit()

        # ---------- 4. 批量写向量 ----------
        offset = resumed_from if resuming else 0
        for start in range(offset, len(chunks), EMBED_BATCH):
            batch = chunks[start:start + EMBED_BATCH]
            vectors = await embed_texts([c.content for c in batch])
            rows = [
                build_chunk_row(
                    chunk_id=f"{document.id}_{chunk.index}",
                    kb_id=str(document.kb_id),
                    doc_id=str(document.id),
                    chunk_index=chunk.index,
                    content=chunk.content,
                    section=chunk.section,
                    page=chunk.page,
                    dense=vector,
                    role_tags=role_tags,
                    effective_from=effective_from,
                    effective_to=effective_to,
                )
                for chunk, vector in zip(batch, vectors, strict=True)
            ]
            await repo.upsert_chunks(rows)
            document.last_indexed_offset = start + len(batch)
            await db.commit()
            logger.info(
                "文档 %s 向量进度 %d/%d", document.id, document.last_indexed_offset, len(chunks)
            )

        # ---------- 5. 完成 ----------
        _set_status(document, DocumentStatus.READY)
        document.error_msg = None
        document.last_indexed_offset = len(chunks)
        await db.commit()
        return IndexOutcome(str(document.id), document.status, len(chunks), resumed_from=resumed_from)

    except (ParseError, EmbeddingError, IndexingError) as exc:
        await _fail(db, document, str(exc))
        return IndexOutcome(str(document.id), document.status, document.chunk_count or 0, str(exc))
    except MilvusUnavailable as exc:
        await _fail(db, document, f"向量库不可用：{exc}")
        return IndexOutcome(str(document.id), document.status, document.chunk_count or 0, str(exc))
    except Exception as exc:  # noqa: BLE001 —— 兜底：任何异常都要落到 failed + 原因
        logger.exception("文档 %s 索引时出现未预期异常", document.id)
        await _fail(db, document, f"未知错误：{exc}")
        return IndexOutcome(str(document.id), document.status, document.chunk_count or 0, str(exc))


async def _fail(db: AsyncSession, document: KbDocument, message: str) -> None:
    document.status = DocumentStatus.FAILED.value
    # 截断：错误信息会展示在后台列表里，太长的堆栈既没用又刷屏
    document.error_msg = message[:500]
    try:
        await db.commit()
    except Exception:  # noqa: BLE001
        await db.rollback()


async def _role_tags_for(db: AsyncSession, kb: KnowledgeBase) -> list[str]:
    """把「哪些角色能读这个库」冗余一份到向量里（双保险）。

    权限的唯一真源始终是 PG 的 ``kb_role_permissions``；写进 Milvus 只是为了
    在「有人绕过 ACL 直接查库」时还能再做一层过滤，同时也方便运维排查。
    """
    from app.models.kb import KbRolePermission

    rows = (
        await db.execute(
            select(KbRolePermission.role).where(
                KbRolePermission.kb_id == kb.id,
                KbRolePermission.can_read.is_(True),
            )
        )
    ).scalars().all()
    return [str(role) for role in rows]


async def reindex_stale(db: AsyncSession, *, repo: MilvusRepo | None = None) -> list[IndexOutcome]:
    """把所有 ``failed`` 的文档重跑一遍（后台「一键重试」用）。"""
    docs = (
        await db.execute(
            select(KbDocument.id).where(KbDocument.status == DocumentStatus.FAILED.value)
        )
    ).scalars().all()
    return [await index_document(db, doc_id, repo=repo) for doc_id in docs]
