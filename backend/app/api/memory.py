"""「我的记忆」接口（M3-07，PRD FR6.6）。

合规上这一组接口比功能本身更重要：用户必须能**看见、删掉、关掉**系统记住的东西。
因此三件事都做全，且**只操作自己的数据**（``user_id`` 一律从 token 取，不信任前端）。

删除时同时清向量库：只删 PG 行会留下孤儿向量，语义检索照样能把「已删除」的记忆
召回回来——用户点了删除却还在被使用，这是最不能接受的一种 bug。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.core.database import get_db
from app.memory.long_term import PgMemoryStore
from app.memory.semantic import get_semantic_memory
from app.models.user import User
from app.schemas.memory import (
    MemoryClearOut,
    MemoryDeleteOut,
    MemoryItemOut,
    MemoryListOut,
    MemoryProfileOut,
    MemoryStatsOut,
    MemoryToggleIn,
    MemoryToggleOut,
)
from app.schemas.response import ResponseModel

router = APIRouter()

MAX_ITEMS = 100


def _store(db: AsyncSession) -> PgMemoryStore:
    return PgMemoryStore(db, vectors=get_semantic_memory())


def _to_out(item) -> MemoryItemOut:  # noqa: ANN001 —— MemoryItem
    return MemoryItemOut(
        id=item.id,
        type=item.type,
        content=item.content,
        confidence=item.confidence,
        sensitive=item.sensitive,
        source_message_id=item.source_message_id,
        source_conversation_id=item.source_conversation_id,
        created_at=item.created_at,
        expires_at=item.expires_at,
    )


@router.get("", response_model=ResponseModel[MemoryListOut])
@router.get("/", response_model=ResponseModel[MemoryListOut], include_in_schema=False)
async def list_memory(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    store = _store(db)
    profile = await store.get_profile(current_user.id)
    items = await store.list_for_user(current_user.id, limit=MAX_ITEMS)
    by_type = await store.count_by_type(current_user.id)
    return ResponseModel(
        data=MemoryListOut(
            enabled=profile.enabled,
            profile=MemoryProfileOut(
                summary=profile.summary,
                attributes=profile.attributes,
                updated_at=profile.updated_at,
            ),
            items=[_to_out(item) for item in items],
            stats=MemoryStatsOut(total=sum(by_type.values()), by_type=by_type),
        )
    )


@router.patch("", response_model=ResponseModel[MemoryToggleOut])
@router.patch("/", response_model=ResponseModel[MemoryToggleOut], include_in_schema=False)
async def toggle_memory(
    payload: MemoryToggleIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    store = _store(db)
    enabled = await store.set_enabled(current_user.id, payload.enabled)
    await db.commit()
    return ResponseModel(data=MemoryToggleOut(enabled=enabled))


@router.delete("/{memory_id}", response_model=ResponseModel[MemoryDeleteOut])
async def delete_memory(
    memory_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        uuid.UUID(str(memory_id))
    except (ValueError, AttributeError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="记忆 id 不合法") from exc

    store = _store(db)
    deleted = await store.delete(current_user.id, memory_id)
    await db.commit()
    # 别人的 id 与不存在的 id 都返回 deleted=false：不泄露「这条记忆存在」的信息
    return ResponseModel(data=MemoryDeleteOut(deleted=deleted))


@router.delete("", response_model=ResponseModel[MemoryClearOut])
@router.delete("/", response_model=ResponseModel[MemoryClearOut], include_in_schema=False)
async def clear_memory(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    store = _store(db)
    removed = await store.clear(current_user.id)
    await db.commit()
    return ResponseModel(data=MemoryClearOut(deleted=removed))
