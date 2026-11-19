"""角色工作台聚合接口（M5）。

**为什么是聚合接口**：工作台首屏要「一眼看到自己现在是什么状态」。如果让前端
分别请求订单 / 购物车 / 记忆 / 会话 / 工单，首屏就是 5 次串行往返，而且每个接口
都要重复一遍「只查自己」的权限判断——口径一旦分散，早晚会对不上。

所以这里按**角色**返回一个扁平结构：

```
GET /api/me/workbench      患者 / 医生 / 客服：我的计数 + 最近几条 + 服务进度
GET /api/public/stats      游客落地页：知识库 / Agent / 最近评估（无需登录）
GET /api/support/stats     坐席：队列与今日接待
```

三个原则：

1. **只查自己的**：所有查询第一个条件都是 ``user_id``（与 M4 看板的「全局视角」相反）；
2. **数字给原始值**：百分比换算、单位、颜色都交给前端，避免「这个接口给 12，
   那个接口给 0.12」；
3. **宁缺毋滥**：算不出来的指标直接不返回字段，前端显示「—」，不编造。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import AnyUser
from app.core.database import get_db
from app.core.timefmt import iso_utc
from app.models.agent import Agent, AgentStatus, Conversation, Message
from app.models.cart import CartItem
from app.models.eval import EvalRun
from app.models.handoff import HandoffTicket, TicketStatus
from app.models.kb import KbChunk, KbDocument, KbStatus, KnowledgeBase
from app.models.memory import UserMemory, UserProfile
from app.models.order import Order, OrderItem, OrderStatus
from app.models.product import Product
from app.models.user import User, UserRole
from app.schemas.response import ResponseModel

router = APIRouter()

ROLE_LABELS = {
    UserRole.ADMIN: "管理员",
    UserRole.DOCTOR: "医生",
    UserRole.PATIENT: "患者",
    UserRole.SUPPORT: "客服",
}

# 患者首页「服务进度」允许展示的活跃工单状态：已结束的不再占据首屏
ACTIVE_TICKET_STATUS = (TicketStatus.QUEUED.value, TicketStatus.ASSIGNED.value)


def _role_value(user: User) -> str:
    role = user.role
    return role.value if hasattr(role, "value") else str(role)


async def _count(db: AsyncSession, stmt) -> int:
    return int((await db.execute(stmt)).scalar_one() or 0)


async def _patient_blocks(db: AsyncSession, user: User) -> dict[str, Any]:
    status_rows = (
        await db.execute(
            select(Order.status, func.count())
            .where(Order.user_id == user.id)
            .group_by(Order.status)
        )
    ).all()
    by_status = {str(status): int(count) for status, count in status_rows}

    recent_orders = (
        await db.execute(
            select(Order)
            .where(Order.user_id == user.id)
            .order_by(Order.created_at.desc())
            .limit(3)
            .options(selectinload(Order.items).selectinload(OrderItem.product))
        )
    ).scalars().all()

    cart_row = (
        await db.execute(
            select(
                func.count(CartItem.id),
                func.coalesce(func.sum(Product.price * CartItem.quantity), 0.0),
            )
            .select_from(CartItem)
            .join(Product, Product.id == CartItem.product_id)
            .where(CartItem.user_id == user.id)
        )
    ).one()

    orders = [
        {
            "id": str(order.id),
            "status": order.status,
            "total_amount": float(order.total_amount or 0),
            "created_at": iso_utc(order.created_at),
            "item_names": [
                (item.product.name if item.product is not None else "商品已下架")
                for item in (order.items or [])
            ][:3],
            "item_count": len(order.items or []),
        }
        for order in recent_orders
    ]

    return {
        "stats": {
            "orders": sum(by_status.values()),
            "orders_pending": by_status.get(OrderStatus.SHIPPED.value, 0),
            "orders_paid": by_status.get(OrderStatus.PAID.value, 0),
            "cart_items": int(cart_row[0] or 0),
            "cart_amount": round(float(cart_row[1] or 0), 2),
        },
        "recent_orders": orders,
    }


async def _doctor_blocks(db: AsyncSession) -> dict[str, Any]:
    products = await _count(db, select(func.count()).select_from(Product))
    libraries = await _count(
        db, select(func.count()).select_from(KnowledgeBase).where(
            KnowledgeBase.status == KbStatus.ACTIVE.value
        )
    )
    documents = await _count(db, select(func.count()).select_from(KbDocument))
    chunks = await _count(db, select(func.count()).select_from(KbChunk))
    since = datetime.utcnow() - timedelta(days=1)
    consults = await _count(
        db,
        select(func.count())
        .select_from(Conversation)
        .where(Conversation.created_at >= since),
    )
    return {
        "stats": {
            "products": products,
            "libraries": libraries,
            "documents": documents,
            "chunks": chunks,
            "consults_24h": consults,
        },
        "recent_orders": [],
    }


async def _support_blocks(db: AsyncSession, user: User) -> dict[str, Any]:
    queue_rows = (
        await db.execute(
            select(HandoffTicket.status, func.count()).group_by(HandoffTicket.status)
        )
    ).all()
    by_status = {str(status): int(count) for status, count in queue_rows}
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    resolved_today = await _count(
        db,
        select(func.count())
        .select_from(HandoffTicket)
        .where(
            HandoffTicket.status == TicketStatus.RESOLVED.value,
            HandoffTicket.closed_at >= today,
        ),
    )
    mine = await _count(
        db,
        select(func.count())
        .select_from(HandoffTicket)
        .where(
            HandoffTicket.assigned_to == user.id,
            HandoffTicket.status == TicketStatus.ASSIGNED.value,
        ),
    )
    return {
        "stats": {
            "queued": by_status.get(TicketStatus.QUEUED.value, 0),
            "assigned": by_status.get(TicketStatus.ASSIGNED.value, 0),
            "offline": by_status.get(TicketStatus.OFFLINE.value, 0),
            "resolved": by_status.get(TicketStatus.RESOLVED.value, 0),
            "resolved_today": resolved_today,
            "mine": mine,
        },
        "recent_orders": [],
    }


@router.get("/me/workbench", response_model=ResponseModel[dict])
async def my_workbench(
    db: AsyncSession = Depends(get_db),
    current_user: User = AnyUser,
):
    role = _role_value(current_user)

    blocks: dict[str, Any] = {"stats": {}, "recent_orders": []}
    if role == UserRole.PATIENT.value:
        blocks = await _patient_blocks(db, current_user)
    elif role == UserRole.DOCTOR.value:
        blocks = await _doctor_blocks(db)
    elif role == UserRole.SUPPORT.value:
        blocks = await _support_blocks(db, current_user)

    conversations = (
        await db.execute(
            select(Conversation)
            .where(Conversation.user_id == current_user.id)
            .order_by(Conversation.updated_at.desc())
            .limit(3)
        )
    ).scalars().all()
    conversation_ids = [row.id for row in conversations]
    message_counts: dict[Any, int] = {}
    if conversation_ids:
        count_rows = (
            await db.execute(
                select(Message.conversation_id, func.count())
                .where(Message.conversation_id.in_(conversation_ids))
                .group_by(Message.conversation_id)
            )
        ).all()
        message_counts = {row[0]: int(row[1]) for row in count_rows}

    tickets = (
        await db.execute(
            select(HandoffTicket)
            .where(HandoffTicket.user_id == current_user.id)
            .order_by(HandoffTicket.created_at.desc())
            .limit(5)
        )
    ).scalars().all()

    profile = await db.get(UserProfile, current_user.id)
    memory_items = await _count(
        db,
        select(func.count()).select_from(UserMemory).where(UserMemory.user_id == current_user.id),
    )

    stats = dict(blocks["stats"])
    stats["conversations"] = await _count(
        db,
        select(func.count()).select_from(Conversation).where(
            Conversation.user_id == current_user.id
        ),
    )
    stats["memories"] = memory_items
    active_tickets = [row for row in tickets if row.status in ACTIVE_TICKET_STATUS]
    stats["open_tickets"] = len(active_tickets)

    latest = tickets[0] if tickets else None
    ticket_payload: Optional[dict[str, Any]] = None
    if latest is not None:
        ticket_payload = {
            "id": str(latest.id),
            "status": latest.status,
            "reason": latest.reason or "",
            "trigger": latest.trigger or "",
            "conversation_id": str(latest.conversation_id),
            "queue_position": int(latest.queue_position or 0),
            "created_at": iso_utc(latest.created_at),
            "accepted_at": iso_utc(latest.accepted_at),
            "closed_at": iso_utc(latest.closed_at),
        }

    return ResponseModel(
        data={
            "role": role,
            "role_label": ROLE_LABELS.get(current_user.role, role),
            "user": {
                "id": str(current_user.id),
                "username": current_user.username,
                "role": role,
            },
            "stats": stats,
            "recent_conversations": [
                {
                    "id": str(row.id),
                    "title": row.title or "未命名会话",
                    "agent_code": row.agent_code or "",
                    "status": row.status,
                    "message_count": message_counts.get(row.id, 0),
                    "updated_at": iso_utc(row.updated_at),
                }
                for row in conversations
            ],
            "recent_orders": blocks["recent_orders"],
            "ticket": ticket_payload,
            "memory": {
                "enabled": bool(profile.memory_enabled) if profile is not None else True,
                "items": memory_items,
                "summary": (profile.summary or "")[:200] if profile is not None else "",
            },
            "generated_at": iso_utc(datetime.utcnow()),
        }
    )


@router.get("/public/stats", response_model=ResponseModel[dict])
async def public_stats(db: AsyncSession = Depends(get_db)):
    """游客落地页的真实数字（无需登录、只读、不含任何业务数据）。

    落地页最容易犯的错是写死「服务 10 万用户」——面试官一问就露。这里全部来自库：
    知识库文档数、切片数、Agent 数、最近一次评估的召回率。
    """
    libraries = await _count(
        db,
        select(func.count()).select_from(KnowledgeBase).where(
            KnowledgeBase.status == KbStatus.ACTIVE.value
        ),
    )
    documents = await _count(db, select(func.count()).select_from(KbDocument))
    chunks = await _count(db, select(func.count()).select_from(KbChunk))
    agents = await _count(
        db,
        select(func.count()).select_from(Agent).where(Agent.status == AgentStatus.ACTIVE.value),
    )

    latest_eval = (
        await db.execute(select(EvalRun).order_by(EvalRun.ran_at.desc()).limit(1))
    ).scalar_one_or_none()
    eval_payload: dict[str, Any] = {"available": False}
    if latest_eval is not None:
        metrics = dict(latest_eval.metrics or {})
        eval_payload = {
            "available": True,
            "cases": latest_eval.cases,
            "recall_at_5": metrics.get("recall_at_5"),
            "mrr": metrics.get("mrr"),
            "refusal_accuracy": metrics.get("refusal_accuracy"),
            "ran_at": iso_utc(latest_eval.ran_at),
        }

    return ResponseModel(
        data={
            "kb": {"libraries": libraries, "documents": documents, "chunks": chunks},
            "agents": agents,
            "eval": eval_payload,
            "generated_at": iso_utc(datetime.utcnow()),
        }
    )


@router.get("/support/stats", response_model=ResponseModel[dict])
async def support_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = AnyUser,
):
    role = _role_value(current_user)
    if role not in {UserRole.SUPPORT.value, UserRole.ADMIN.value}:
        raise HTTPException(status_code=403, detail="仅客服与管理员可用")

    since = datetime.utcnow() - timedelta(hours=24)
    accepted = (
        await db.execute(
            select(HandoffTicket).where(
                HandoffTicket.accepted_at.is_not(None),
                HandoffTicket.accepted_at >= since,
            )
        )
    ).scalars().all()
    waits = [
        (row.accepted_at - row.created_at).total_seconds()
        for row in accepted
        if row.accepted_at is not None and row.created_at is not None
    ]
    resolved = await _count(
        db,
        select(func.count())
        .select_from(HandoffTicket)
        .where(
            HandoffTicket.status == TicketStatus.RESOLVED.value,
            HandoffTicket.closed_at >= since,
        ),
    )
    queued = await _count(
        db,
        select(func.count())
        .select_from(HandoffTicket)
        .where(HandoffTicket.status == TicketStatus.QUEUED.value),
    )

    return ResponseModel(
        data={
            "window_hours": 24,
            "accepted": len(accepted),
            "resolved": resolved,
            "queued": queued,
            "avg_wait_seconds": int(sum(waits) / len(waits)) if waits else 0,
            "max_wait_seconds": int(max(waits)) if waits else 0,
            "generated_at": iso_utc(datetime.utcnow()),
        }
    )


__all__ = ["router", "ROLE_LABELS"]
