"""知识库后台 API（M1-10 ~ M1-14）。

路由顺序是有意安排的：``/permissions``、``/stats`` 必须声明在 ``/{kb_id}`` 之前，
否则会被当成 UUID 路径参数吃掉（FastAPI 按声明顺序匹配）。

写操作的三个统一动作：
1. 变更前把旧值序列化出来（审计的 ``before``）；
2. 提交后 ``invalidate_acl()``——权限/状态变了，缓存必须立刻失效（PRD ≤30s）；
3. 一条 ``audit_logs``，与业务变更同事务提交。
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.core.config import settings
from app.core.database import AsyncSessionLocal, get_db
from app.llm.embedding import EmbeddingError, embed_texts
from app.models.kb import (
    DocumentSource,
    DocumentStatus,
    KbChunk,
    KbDocument,
    KbRolePermission,
    KbSearchLog,
    KnowledgeBase,
)
from app.models.user import User, UserRole
from app.rag import acl as acl_module
from app.rag.acl import describe_acl, invalidate_acl, resolve_acl
from app.rag.chunker import estimate_tokens
from app.rag.indexer import index_document, storage_root
from app.rag.milvus_repo import MilvusUnavailable, build_chunk_row, get_milvus_repo
from app.rag.parser import file_sha256
from app.rag.retriever import get_retrieval_service
from app.schemas.kb import (
    ChunkOut,
    ChunkUpdate,
    DocumentCreateResult,
    DocumentOut,
    KbCreate,
    KbOut,
    KbUpdate,
    PermissionItem,
    PermissionMatrix,
    PermissionUpdate,
    SearchHit,
    SearchTestRequest,
    SearchTestResponse,
    StatsResponse,
    ZeroRecallItem,
)
from app.schemas.response import ResponseModel
from app.services.audit import write_audit

logger = logging.getLogger(__name__)
router = APIRouter()

AdminUser = Depends(require_roles([UserRole.ADMIN]))
ALL_ROLES = [role.value for role in UserRole] + [acl_module.VISITOR_ROLE]


# --------------------------------------------------------------------- 工具函数
def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return request.client.host if request.client else None


async def _get_kb(db: AsyncSession, kb_id: uuid.UUID) -> KnowledgeBase:
    kb = (
        await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
    ).scalar_one_or_none()
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return kb


async def _get_doc(db: AsyncSession, kb_id: uuid.UUID, doc_id: uuid.UUID) -> KbDocument:
    document = (
        await db.execute(
            select(KbDocument).where(KbDocument.id == doc_id, KbDocument.kb_id == kb_id)
        )
    ).scalar_one_or_none()
    if document is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    return document


def _kb_snapshot(kb: KnowledgeBase) -> dict:
    return {
        "code": kb.code,
        "name": kb.name,
        "description": kb.description,
        "chunk_strategy": kb.chunk_strategy,
        "rerank_enabled": kb.rerank_enabled,
        "score_threshold": kb.score_threshold,
        "visibility": kb.visibility,
        "status": kb.status,
    }


async def _index_in_background(doc_id: uuid.UUID) -> None:
    """后台任务：自己开 session，不依赖请求生命周期。"""
    async with AsyncSessionLocal() as session:
        try:
            await index_document(session, doc_id)
        except Exception:  # noqa: BLE001 —— 后台任务不能把异常抛到无人处理的地方
            logger.exception("后台索引任务失败 doc=%s", doc_id)


async def _counts(db: AsyncSession) -> tuple[dict[uuid.UUID, int], dict[uuid.UUID, int]]:
    doc_rows = (
        await db.execute(
            select(KbDocument.kb_id, func.count(KbDocument.id)).group_by(KbDocument.kb_id)
        )
    ).all()
    chunk_rows = (
        await db.execute(select(KbChunk.kb_id, func.count(KbChunk.id)).group_by(KbChunk.kb_id))
    ).all()
    return (
        {kb_id: int(count) for kb_id, count in doc_rows},
        {kb_id: int(count) for kb_id, count in chunk_rows},
    )


def _kb_out(kb: KnowledgeBase, docs: dict, chunks: dict) -> KbOut:
    payload = KbOut.model_validate(kb)
    payload.document_count = docs.get(kb.id, 0)
    payload.chunk_count = chunks.get(kb.id, 0)
    return payload


# --------------------------------------------------------------------- 统计 / 矩阵
@router.get("/stats", response_model=ResponseModel[StatsResponse])
async def kb_stats(db: AsyncSession = Depends(get_db), current_user: User = AdminUser):
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)

    kb_count = (await db.execute(select(func.count(KnowledgeBase.id)))).scalar_one()
    doc_count = (await db.execute(select(func.count(KbDocument.id)))).scalar_one()
    chunk_count = (await db.execute(select(func.count(KbChunk.id)))).scalar_one()

    searches_7d = (
        await db.execute(
            select(func.count(KbSearchLog.id)).where(KbSearchLog.created_at >= since)
        )
    ).scalar_one()
    refused_7d = (
        await db.execute(
            select(func.count(KbSearchLog.id)).where(
                KbSearchLog.created_at >= since, KbSearchLog.refused.is_(True)
            )
        )
    ).scalar_one()

    # 零召回榜：真的「一条都没召回到」的问题，直接指导「该补哪篇文档」。
    # 只统计 no_hit——无权限/无库/向量化失败也会是 0 条，但那补文档没用。
    zero_rows = (
        await db.execute(
            select(KbSearchLog.query_norm, func.count(KbSearchLog.id).label("cnt"))
            .where(
                KbSearchLog.created_at >= since,
                KbSearchLog.hit_count == 0,
                KbSearchLog.reason == "no_hit",
            )
            .group_by(KbSearchLog.query_norm)
            .order_by(func.count(KbSearchLog.id).desc())
            .limit(10)
        )
    ).all()

    zero_recall = [ZeroRecallItem(query=query or "(空)", count=int(count)) for query, count in zero_rows]
    return ResponseModel(
        data=StatsResponse(
            kb_count=int(kb_count),
            document_count=int(doc_count),
            chunk_count=int(chunk_count),
            searches_7d=int(searches_7d),
            zero_recall=zero_recall,
            zero_recall_7d=sum(item.count for item in zero_recall),
            refused_7d=int(refused_7d),
        )
    )


@router.get("/permissions", response_model=ResponseModel[list[PermissionMatrix]])
async def list_permissions(db: AsyncSession = Depends(get_db), current_user: User = AdminUser):
    """权限矩阵（库 × 角色），前端一次拿全，避免 N+1 次请求。"""
    kbs = (
        await db.execute(select(KnowledgeBase).order_by(KnowledgeBase.created_at))
    ).scalars().all()
    grants = (
        await db.execute(
            select(KbRolePermission.kb_id, KbRolePermission.role, KbRolePermission.can_read)
        )
    ).all()

    grant_map: dict[uuid.UUID, dict[str, bool]] = {}
    for kb_id, role, can_read in grants:
        grant_map.setdefault(kb_id, {})[role] = bool(can_read)

    matrices = []
    for kb in kbs:
        per_role = grant_map.get(kb.id, {})
        matrices.append(
            PermissionMatrix(
                kb_id=kb.id,
                kb_code=kb.code,
                rows=[
                    PermissionItem(role=role, can_read=per_role.get(role, False))
                    for role in ALL_ROLES
                    if role != acl_module.VISITOR_ROLE or kb.visibility == "public"
                ],
            )
        )
    return ResponseModel(data=matrices)


# --------------------------------------------------------------------- 知识库 CRUD
@router.get("", response_model=ResponseModel[list[KbOut]])
@router.get("/", response_model=ResponseModel[list[KbOut]], include_in_schema=False)
async def list_kb(db: AsyncSession = Depends(get_db), current_user: User = AdminUser):
    kbs = (
        await db.execute(select(KnowledgeBase).order_by(KnowledgeBase.created_at.desc()))
    ).scalars().all()
    docs, chunks = await _counts(db)
    return ResponseModel(data=[_kb_out(kb, docs, chunks) for kb in kbs])


@router.post("", response_model=ResponseModel[KbOut])
@router.post("/", response_model=ResponseModel[KbOut], include_in_schema=False)
async def create_kb(
    payload: KbCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = AdminUser,
):
    kb = KnowledgeBase(
        **payload.model_dump(),
        owner_id=current_user.id,
    )
    # 默认拒绝：新建库没有任何角色授权（PRD §3.2 铁律 1）
    db.add(kb)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"知识库编码 {payload.code} 已存在") from exc

    await write_audit(
        db,
        action="kb.create",
        target_type="knowledge_base",
        target_id=str(kb.id),
        actor=current_user,
        before=None,
        after=_kb_snapshot(kb),
        ip=_client_ip(request),
    )
    await db.commit()
    await db.refresh(kb)
    return ResponseModel(data=_kb_out(kb, {}, {}))


@router.get("/{kb_id}", response_model=ResponseModel[KbOut])
async def get_kb(
    kb_id: uuid.UUID, db: AsyncSession = Depends(get_db), current_user: User = AdminUser
):
    kb = await _get_kb(db, kb_id)
    docs, chunks = await _counts(db)
    return ResponseModel(data=_kb_out(kb, docs, chunks))


@router.put("/{kb_id}", response_model=ResponseModel[KbOut])
async def update_kb(
    kb_id: uuid.UUID,
    payload: KbUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = AdminUser,
):
    kb = await _get_kb(db, kb_id)
    before = _kb_snapshot(kb)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(kb, field, value)
    await write_audit(
        db,
        action="kb.update",
        target_type="knowledge_base",
        target_id=str(kb.id),
        actor=current_user,
        before=before,
        after=_kb_snapshot(kb),
        ip=_client_ip(request),
    )
    await db.commit()
    await db.refresh(kb)
    # 状态/可见性/阈值都影响可检索性，缓存必须失效
    await invalidate_acl()
    docs, chunks = await _counts(db)
    return ResponseModel(data=_kb_out(kb, docs, chunks))


@router.delete("/{kb_id}", response_model=ResponseModel[dict])
async def delete_kb(
    kb_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = AdminUser,
):
    kb = await _get_kb(db, kb_id)
    before = _kb_snapshot(kb)
    vector_error: str | None = None
    try:
        # 先删向量再删元数据（PRD FR2.3）；向量删失败也继续删元数据，
        # 因为元数据没了以后这些向量再也无法被检索到（ACL 里查不到这个库）
        await get_milvus_repo().delete_by_kb(str(kb.id))
    except MilvusUnavailable as exc:
        vector_error = str(exc)
        logger.warning("删除知识库向量失败（继续删除元数据）：%s", exc)

    await db.delete(kb)
    await write_audit(
        db,
        action="kb.delete",
        target_type="knowledge_base",
        target_id=str(kb_id),
        actor=current_user,
        before=before,
        after={"vector_error": vector_error},
        ip=_client_ip(request),
    )
    await db.commit()
    await invalidate_acl()
    return ResponseModel(data={"message": "删除成功", "vector_error": vector_error})


# --------------------------------------------------------------------- 权限
@router.put("/{kb_id}/permissions", response_model=ResponseModel[PermissionMatrix])
async def set_permissions(
    kb_id: uuid.UUID,
    payload: PermissionUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = AdminUser,
):
    kb = await _get_kb(db, kb_id)
    old_rows = (
        await db.execute(
            select(KbRolePermission.role, KbRolePermission.can_read).where(
                KbRolePermission.kb_id == kb_id
            )
        )
    ).all()
    before = {role: can_read for role, can_read in old_rows}

    await db.execute(delete(KbRolePermission).where(KbRolePermission.kb_id == kb_id))
    for item in payload.permissions:
        if item.can_read:
            db.add(KbRolePermission(kb_id=kb_id, role=item.role, can_read=True))

    after = {item.role: item.can_read for item in payload.permissions if item.can_read}
    await write_audit(
        db,
        action="kb.permissions.update",
        target_type="knowledge_base",
        target_id=str(kb_id),
        actor=current_user,
        before=before,
        after=after,
        ip=_client_ip(request),
    )
    await db.commit()
    await invalidate_acl()

    return ResponseModel(
        data=PermissionMatrix(
            kb_id=kb.id,
            kb_code=kb.code,
            rows=[PermissionItem(role=role, can_read=role in after) for role in ALL_ROLES],
        )
    )


# --------------------------------------------------------------------- 文档
@router.get("/{kb_id}/documents", response_model=ResponseModel[list[DocumentOut]])
async def list_documents(
    kb_id: uuid.UUID, db: AsyncSession = Depends(get_db), current_user: User = AdminUser
):
    await _get_kb(db, kb_id)
    rows = (
        await db.execute(
            select(KbDocument)
            .where(KbDocument.kb_id == kb_id)
            .order_by(KbDocument.created_at.desc())
        )
    ).scalars().all()
    return ResponseModel(data=rows)


@router.post("/{kb_id}/documents", response_model=ResponseModel[DocumentCreateResult])
async def upload_document(
    kb_id: uuid.UUID,
    background: BackgroundTasks,
    request: Request,
    file: UploadFile | None = File(default=None),
    url: str | None = Form(default=None),
    text: str | None = Form(default=None),
    title: str | None = Form(default=None),
    effective_from: str | None = Form(default=None),
    effective_to: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: User = AdminUser,
):
    """三种接入方式：上传文件 / 抓取 URL / 手工粘贴正文。"""
    kb = await _get_kb(db, kb_id)

    from app.rag.parser import ParseError, detect_source_type

    source_type: str
    file_hash: str | None = None
    stored_path: Path | None = None
    doc_title = title or ""

    if file is not None and file.filename:
        data = await file.read()
        limit = settings.kb_max_file_mb * 1024 * 1024
        if len(data) > limit:
            raise HTTPException(
                status_code=413, detail=f"文件超过 {settings.kb_max_file_mb}MB 上限"
            )
        try:
            source_type = detect_source_type(file.filename)
        except ParseError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        file_hash = file_sha256(data)
        doc_title = doc_title or Path(file.filename).stem
        target_dir = storage_root() / str(kb.id)
        target_dir.mkdir(parents=True, exist_ok=True)
        stored_path = target_dir / f"{uuid.uuid4().hex}{Path(file.filename).suffix.lower()}"
        stored_path.write_bytes(data)

    elif url:
        source_type = DocumentSource.URL.value
        doc_title = doc_title or url
    elif text:
        source_type = DocumentSource.MANUAL.value
        doc_title = doc_title or (text.strip().splitlines()[0][:60] if text.strip() else "手工录入")
    else:
        raise HTTPException(status_code=400, detail="请提供 file、url 或 text 之一")

    if not doc_title:
        raise HTTPException(status_code=400, detail="标题不能为空")

    # 同一份文件重复上传：直接拒绝，避免向量库里出现两份相同内容
    if file_hash:
        duplicate = (
            await db.execute(
                select(KbDocument).where(
                    KbDocument.kb_id == kb.id, KbDocument.file_hash == file_hash
                )
            )
        ).scalar_one_or_none()
        if duplicate is not None:
            if stored_path and stored_path.exists():
                stored_path.unlink(missing_ok=True)
            raise HTTPException(
                status_code=409,
                detail=f"该文件已存在于本库（文档：{duplicate.title}）",
            )

    document = KbDocument(
        kb_id=kb.id,
        title=doc_title[:255],
        source_type=source_type,
        source_url=url if source_type == DocumentSource.URL.value else None,
        file_path=str(stored_path) if stored_path else None,
        file_hash=file_hash,
        status=DocumentStatus.PENDING.value,
        uploaded_by=current_user.id,
        effective_from=_parse_date(effective_from),
        effective_to=_parse_date(effective_to),
    )
    db.add(document)
    await db.flush()

    if source_type == DocumentSource.MANUAL.value and text:
        # 手工贴进来的正文也落盘，保持「文件是唯一真源」，重新解析时才有一手材料
        target_dir = storage_root() / str(kb.id)
        target_dir.mkdir(parents=True, exist_ok=True)
        manual_path = target_dir / f"{document.id}.txt"
        manual_path.write_text(text, encoding="utf-8")
        document.file_path = str(manual_path)

    await write_audit(
        db,
        action="kb.document.upload",
        target_type="kb_document",
        target_id=str(document.id),
        actor=current_user,
        after={"title": document.title, "source_type": source_type},
        ip=_client_ip(request),
    )
    await db.commit()
    await db.refresh(document)

    background.add_task(_index_in_background, document.id)
    return ResponseModel(data=DocumentCreateResult(document=DocumentOut.model_validate(document)))


@router.post("/{kb_id}/documents/{doc_id}/reindex", response_model=ResponseModel[DocumentOut])
async def reindex_document(
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    background: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = AdminUser,
):
    """重新解析：游标清零 → 全量重建（先删旧向量）。"""
    document = await _get_doc(db, kb_id, doc_id)
    document.last_indexed_offset = 0
    document.version = (document.version or 1) + 1
    document.status = DocumentStatus.PENDING.value
    document.error_msg = None
    await write_audit(
        db,
        action="kb.document.reindex",
        target_type="kb_document",
        target_id=str(doc_id),
        actor=current_user,
        after={"version": document.version},
        ip=_client_ip(request),
    )
    await db.commit()
    await db.refresh(document)
    background.add_task(_index_in_background, document.id)
    return ResponseModel(data=document)


@router.post("/{kb_id}/documents/{doc_id}/retry", response_model=ResponseModel[DocumentOut])
async def retry_document(
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    background: BackgroundTasks,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = AdminUser,
):
    """失败重试：保留游标 → 从断点续传，已写入的向量不重复写。"""
    document = await _get_doc(db, kb_id, doc_id)
    if document.status == DocumentStatus.READY.value:
        raise HTTPException(status_code=409, detail="该文档已就绪，如需重建请使用 reindex")
    document.status = DocumentStatus.PENDING.value
    document.error_msg = None
    await write_audit(
        db,
        action="kb.document.retry",
        target_type="kb_document",
        target_id=str(doc_id),
        actor=current_user,
        after={"resume_from": document.last_indexed_offset},
        ip=_client_ip(request),
    )
    await db.commit()
    await db.refresh(document)
    background.add_task(_index_in_background, document.id)
    return ResponseModel(data=document)


@router.delete("/{kb_id}/documents/{doc_id}", response_model=ResponseModel[dict])
async def delete_document(
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = AdminUser,
):
    document = await _get_doc(db, kb_id, doc_id)
    title = document.title
    vector_error: str | None = None
    try:
        await get_milvus_repo().delete_by_doc(str(doc_id))
    except MilvusUnavailable as exc:
        vector_error = str(exc)
        logger.warning("删除文档向量失败（继续删除元数据）：%s", exc)

    await db.delete(document)
    await write_audit(
        db,
        action="kb.document.delete",
        target_type="kb_document",
        target_id=str(doc_id),
        actor=current_user,
        before={"title": title},
        after={"vector_error": vector_error},
        ip=_client_ip(request),
    )
    await db.commit()
    return ResponseModel(data={"message": "删除成功", "vector_error": vector_error})


# --------------------------------------------------------------------- 分段
@router.get("/{kb_id}/documents/{doc_id}/chunks", response_model=ResponseModel[list[ChunkOut]])
async def list_chunks(
    kb_id: uuid.UUID,
    doc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = AdminUser,
):
    await _get_doc(db, kb_id, doc_id)
    rows = (
        await db.execute(
            select(KbChunk).where(KbChunk.doc_id == doc_id).order_by(KbChunk.chunk_index)
        )
    ).scalars().all()
    return ResponseModel(data=rows)


@router.put("/{kb_id}/chunks/{chunk_id}", response_model=ResponseModel[ChunkOut])
async def update_chunk(
    kb_id: uuid.UUID,
    chunk_id: uuid.UUID,
    payload: ChunkUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = AdminUser,
):
    """改正文后只重建这一条向量，``hit_count`` 保留（运营视角不能丢）。"""
    chunk = (
        await db.execute(
            select(KbChunk).where(KbChunk.id == chunk_id, KbChunk.kb_id == kb_id)
        )
    ).scalar_one_or_none()
    if chunk is None:
        raise HTTPException(status_code=404, detail="分段不存在")

    document = await _get_doc(db, kb_id, chunk.doc_id)
    await _get_kb(db, kb_id)
    if document.status != DocumentStatus.READY.value:
        # 未就绪的文档向量可能正在写，单条编辑会和流水线打架
        raise HTTPException(status_code=409, detail="文档尚未索引完成，请稍后再编辑分段")
    before = {"content": chunk.content[:200], "section": chunk.section}

    if payload.content is not None:
        chunk.content = payload.content
        chunk.token_count = estimate_tokens(payload.content)
    if payload.section is not None:
        chunk.section = payload.section[:128] or None

    try:
        vectors = await embed_texts([chunk.content])
    except EmbeddingError as exc:
        await db.rollback()
        raise HTTPException(status_code=503, detail=f"重建向量失败：{exc}") from exc

    roles = (
        await db.execute(
            select(KbRolePermission.role).where(
                KbRolePermission.kb_id == kb_id, KbRolePermission.can_read.is_(True)
            )
        )
    ).scalars().all()

    vector_id = chunk.vector_id or f"{chunk.doc_id}_{chunk.chunk_index}"
    chunk.vector_id = vector_id
    await db.flush()

    try:
        await get_milvus_repo().upsert_chunks(
            [
                build_chunk_row(
                    chunk_id=vector_id,
                    kb_id=str(kb_id),
                    doc_id=str(chunk.doc_id),
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    section=chunk.section,
                    page=chunk.page,
                    dense=vectors[0],
                    role_tags=roles,
                )
            ]
        )
    except MilvusUnavailable as exc:
        await db.rollback()
        raise HTTPException(status_code=503, detail=f"向量库不可用：{exc}") from exc

    await write_audit(
        db,
        action="kb.chunk.update",
        target_type="kb_chunk",
        target_id=str(chunk.id),
        actor=current_user,
        before=before,
        after={"content": chunk.content[:200], "section": chunk.section},
        ip=_client_ip(request),
    )
    await db.commit()
    await db.refresh(chunk)
    return ResponseModel(data=chunk)


# --------------------------------------------------------------------- 检索测试台
@router.post("/{kb_id}/search-test", response_model=ResponseModel[SearchTestResponse])
async def search_test(
    kb_id: uuid.UUID,
    payload: SearchTestRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = AdminUser,
):
    """以指定角色身份检索：演示「同一条 query，patient 与 visitor 看到的不一样」。

    路径里的 ``kb_id`` 只用来校验库存在；真正的检索范围由 ``kb_ids`` 决定：
    传了就是「只看这几个库」，不传就是「该角色能看的全部库」。
    早先的实现把「不传」悄悄兜底成「只看路径里那个库」，界面上写着「全部库」
    实际只搜一个库，是排查「怎么都拒答」时最费时间的一类坑。
    """
    await _get_kb(db, kb_id)
    kb_ids = [str(one) for one in payload.kb_ids] if payload.kb_ids else None

    started = time.perf_counter()
    result = await get_retrieval_service().retrieve(
        db,
        payload.query,
        role=payload.role,
        kb_ids=kb_ids,
        top_k=payload.top_k,
        threshold=payload.threshold,
        write_log=True,
    )
    latency_ms = int((time.perf_counter() - started) * 1000)

    snapshot = await resolve_acl(db, role=payload.role)
    names = {str(kb.id): kb.name for kb in (await db.execute(select(KnowledgeBase))).scalars().all()}
    acl_view = describe_acl(snapshot, names=names)

    # 拒答时把「差一点」的候选也返回：测试台的价值就在于能看出差多少分
    near_miss = list(result.chunks) if result.chunks else list(result.rejected_chunks)
    hits = [
        SearchHit(
            index=index,
            doc_id=chunk.doc_id,
            kb_id=chunk.kb_id,
            doc_title=chunk.doc_title or chunk.doc_id,
            section=chunk.section,
            page=chunk.page,
            score=round(chunk.score, 4),
            snippet=" ".join(chunk.content.split())[:180],
        )
        for index, chunk in enumerate(near_miss, start=1)
    ]

    return ResponseModel(
        data=SearchTestResponse(
            query=payload.query,
            rewritten_query=result.rewritten_query,
            role=payload.role,
            allowed_kbs=acl_view["allowed"],
            filtered_out_kbs=acl_view["filtered_out_kbs"],
            hits=hits,
            context=result.as_context() if result.chunks else "",
            refused=result.refused,
            reason=result.reason,
            top_score=round(result.top_score, 4),
            threshold_used=result.threshold,
            score_source=result.score_source,
            hits_are_rejected=bool(result.refused and near_miss),
            latency_ms=latency_ms,
        )
    )


def _parse_date(value: str | None):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"日期格式应为 YYYY-MM-DD：{value}") from exc
