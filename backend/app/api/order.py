
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import AdminOnly, AnyUser
from app.core.database import get_db
from app.core.timefmt import iso_utc
from app.models.cart import CartItem
from app.models.order import Order, OrderItem, OrderStatus
from app.models.product import Product
from app.models.user import User, UserRole
from app.schemas.order import OrderItemResponse, OrderResponse
from app.schemas.response import ResponseModel

router = APIRouter()


class OrderItemCreate(BaseModel):
    product_id: UUID
    # ge=1：数量 0 / 负数会造出 0 元订单，库存还会被「减 0」，属于静默脏数据
    quantity: int = Field(..., ge=1)


class OrderCreate(BaseModel):
    items: Optional[List[OrderItemCreate]] = None
    # 这批 items 是不是「从购物车勾选结算」的：
    # True 时下单成功后要把对应购物车行删掉，否则勾选结算会变成「下单了但车里还在」。
    # 立即购买（detail 页）不置位——那时购物车里的同款商品不是这次下单的对象。
    from_cart: bool = False


@router.post("/checkout", response_model=ResponseModel[dict])
async def checkout(data: OrderCreate = None, db: AsyncSession = Depends(get_db), current_user: User = AnyUser):
    order_items_to_create = []
    cart_items = []

    if data and data.items:
        for item in data.items:
            prod = await db.get(Product, item.product_id)
            if not prod or prod.stock < item.quantity:
                raise HTTPException(400, f"{prod.name if prod else '商品'} 库存不足")
            order_items_to_create.append({
                "product": prod, "quantity": item.quantity, "price": prod.price
            })
    else:
        result = await db.execute(
            select(CartItem).where(CartItem.user_id == current_user.id).options(selectinload(CartItem.product)))
        cart_items = result.scalars().all()
        if not cart_items:
            raise HTTPException(400, "购物车为空")
        for ci in cart_items:
            if ci.product.stock < ci.quantity:
                raise HTTPException(400, f"{ci.product.name} 库存不足")
            order_items_to_create.append({
                "product": ci.product, "quantity": ci.quantity, "price": ci.product.price
            })

    total = sum(item["price"] * item["quantity"] for item in order_items_to_create)
    order = Order(user_id=current_user.id, total_amount=total, status=OrderStatus.PAID.value)
    db.add(order)
    await db.flush()

    for item in order_items_to_create:
        oi = OrderItem(order_id=order.id, product_id=item["product"].id, quantity=item["quantity"],
                       unit_price=item["price"])
        db.add(oi)
        item["product"].stock -= item["quantity"]

    if not (data and data.items):
        # 整车结算：购物车清空
        for ci in cart_items:
            await db.delete(ci)
    elif data.from_cart:
        # 勾选结算：只删这次真正下过单的那几行，车里其它商品要留着
        ordered_ids = {item["product"].id for item in order_items_to_create}
        rows = await db.execute(
            select(CartItem).where(
                CartItem.user_id == current_user.id,
                CartItem.product_id.in_(ordered_ids),
            )
        )
        for ci in rows.scalars().all():
            await db.delete(ci)

    await db.commit()
    return ResponseModel(data={"order_id": order.id, "message": "支付成功"})


@router.get("", response_model=ResponseModel[list[OrderResponse]])
async def my_orders(db: AsyncSession = Depends(get_db), current_user: User = AnyUser):
    # 确保加载了订单里的商品信息
    result = await db.execute(
        select(Order).where(Order.user_id == current_user.id)
        .options(selectinload(Order.items).selectinload(OrderItem.product))
        .order_by(Order.created_at.desc())
    )
    orders = result.scalars().all()

    res = []
    for o in orders:
        items = _order_items(o)
        res.append(OrderResponse(
            id=o.id, total_amount=o.total_amount, status=o.status,
            created_at=o.created_at, items=items
        ))
    return ResponseModel(data=res)


def _order_items(order: Order) -> list[OrderItemResponse]:
    return [
        OrderItemResponse(
            product_id=i.product_id,
            name=i.product.name,
            quantity=i.quantity,
            unit_price=i.unit_price,
            image_url=i.product.image_url,
        )
        for i in order.items
    ]


@router.get("/admin/all", response_model=ResponseModel[dict])
async def admin_all_orders(
    status: str = Query(default="", max_length=20),
    keyword: str = Query(default="", max_length=32),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = AdminOnly,
):
    """管理员订单管理列表。

    之前后台没有任何「看全部订单」的入口：管理员只能在订单详情页里点一下
    「模拟发货」，先得知道订单号——等于没有。这个接口按状态筛选 + 按用户名搜索，
    顺带回一份各状态数量，前端 Tab 上的角标直接用。

    注意路由顺序：本接口必须声明在 ``GET /{order_id}`` 之前，否则 ``admin``
    会被当成 UUID 去解析，直接 422。
    """
    conditions = []
    status_text = (status or "").strip().lower()
    if status_text and status_text != "all":
        conditions.append(Order.status == status_text)
    text = (keyword or "").strip()
    if text:
        conditions.append(User.username.ilike(f"%{text}%"))

    base = select(Order).options(
        selectinload(Order.items).selectinload(OrderItem.product),
        selectinload(Order.user),
    )
    if conditions:
        base = base.join(Order.user, isouter=True).where(*conditions)

    orders = (
        await db.execute(base.order_by(Order.created_at.desc()).limit(limit))
    ).scalars().all()

    count_rows = (
        await db.execute(select(Order.status, func.count()).group_by(Order.status))
    ).all()
    counts = {str(row[0]): int(row[1]) for row in count_rows}

    items: list[dict] = []
    for order in orders:
        items.append(
            {
                "id": str(order.id),
                "status": order.status,
                "total_amount": float(order.total_amount or 0),
                "created_at": iso_utc(order.created_at),
                "user_id": str(order.user_id),
                "username": order.user.username if order.user is not None else "—",
                "items": [item.model_dump(mode="json") for item in _order_items(order)],
                "item_count": sum(int(i.quantity or 0) for i in order.items),
            }
        )

    return ResponseModel(
        data={
            "items": items,
            "counts": counts,
            "total": sum(counts.values()),
            "pending_ship": counts.get(OrderStatus.PAID.value, 0),
            "filter": {"status": status_text or "all", "keyword": text, "limit": limit},
        }
    )


@router.get("/admin/summary", response_model=ResponseModel[dict])
async def admin_order_summary(db: AsyncSession = Depends(get_db), current_user: User = AdminOnly):
    """工作台角标用的极简计数：只要数字，不带列表。"""
    count_rows = (
        await db.execute(select(Order.status, func.count()).group_by(Order.status))
    ).all()
    counts = {str(row[0]): int(row[1]) for row in count_rows}
    paid = counts.get(OrderStatus.PAID.value, 0)
    shipped = counts.get(OrderStatus.SHIPPED.value, 0)
    revenue_row = (
        await db.execute(
            select(func.coalesce(func.sum(Order.total_amount), 0)).where(
                Order.status.in_([OrderStatus.PAID.value, OrderStatus.SHIPPED.value, OrderStatus.COMPLETED.value])
            )
        )
    ).scalar_one()
    return ResponseModel(
        data={
            "counts": counts,
            "total": sum(counts.values()),
            "pending_ship": paid,
            "in_transit": shipped,
            "revenue": float(revenue_row or 0),
        }
    )


# 获取单个订单详情
@router.get("/{order_id}", response_model=ResponseModel[OrderResponse])
async def get_order_detail(order_id: UUID, db: AsyncSession = Depends(get_db), current_user: User = AnyUser):
    # 管理员订单管理里点「详情」要看得到别人的订单；患者/医生等只能看自己的
    stmt = select(Order).where(Order.id == order_id)
    if current_user.role != UserRole.ADMIN:
        stmt = stmt.where(Order.user_id == current_user.id)
    result = await db.execute(
        stmt.options(selectinload(Order.items).selectinload(OrderItem.product))
    )
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(404, "订单不存在")

    items = _order_items(order)

    return ResponseModel(data=OrderResponse(
        id=order.id, total_amount=order.total_amount, status=order.status,
        created_at=order.created_at, items=items
    ))


# 取消订单
@router.put("/{order_id}/cancel", response_model=ResponseModel[dict])
async def cancel_order(order_id: UUID, db: AsyncSession = Depends(get_db), current_user: User = AnyUser):
    result = await db.execute(select(Order).where(Order.id == order_id, Order.user_id == current_user.id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(404, "订单不存在")

    if order.status not in [OrderStatus.PENDING.value, OrderStatus.PAID.value]:
        raise HTTPException(400, "当前状态不可取消")

    order.status = OrderStatus.CANCELLED.value
    await db.commit()
    return ResponseModel(data={"message": "订单已取消"})


# 确认收货
@router.put("/{order_id}/receive", response_model=ResponseModel[dict])
async def receive_order(order_id: UUID, db: AsyncSession = Depends(get_db), current_user: User = AnyUser):
    result = await db.execute(select(Order).where(Order.id == order_id, Order.user_id == current_user.id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(404, "订单不存在")

    if order.status != OrderStatus.SHIPPED:
        raise HTTPException(400, "当前状态不可收货")

    order.status = OrderStatus.COMPLETED.value
    await db.commit()
    return ResponseModel(data={"message": "确认收货成功"})


# 模拟发货接口 (演示用，真实场景由后台系统调用)
@router.put("/{order_id}/ship", response_model=ResponseModel[dict])
async def ship_order(
        order_id: UUID,
        db: AsyncSession = Depends(get_db),
        current_user: User = AdminOnly
):
    result = await db.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(404, "订单不存在")
    # 之前这里对「非待发货」的订单静默返回成功，管理员点一下以为发货了，
    # 实际状态没变——现在明确报错，前端才能给出准确反馈
    if order.status != OrderStatus.PAID.value:
        raise HTTPException(400, f"只有「待发货」订单可以发货，当前状态：{order.status}")
    order.status = OrderStatus.SHIPPED.value
    await db.commit()
    return ResponseModel(data={"message": "发货成功", "status": order.status})
