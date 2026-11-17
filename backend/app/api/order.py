from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from uuid import UUID
from typing import List, Optional
from pydantic import BaseModel

from app.core.database import get_db
from app.models.cart import CartItem
from app.models.product import Product
from app.models.order import Order, OrderItem, OrderStatus
from app.models.user import User
from app.schemas.order import OrderResponse, OrderItemResponse
from app.schemas.response import ResponseModel
from app.api.deps import AnyUser

router = APIRouter()


class OrderItemCreate(BaseModel):
    product_id: UUID
    quantity: int


class OrderCreate(BaseModel):
    items: Optional[List[OrderItemCreate]] = None


@router.post("/checkout", response_model=ResponseModel[dict])
async def checkout(data: OrderCreate = None, db: AsyncSession = Depends(get_db), current_user: User = AnyUser):
    order_items_to_create = []

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
    order = Order(user_id=current_user.id, total_amount=total, status=OrderStatus.PAID)
    db.add(order)
    await db.flush()

    for item in order_items_to_create:
        oi = OrderItem(order_id=order.id, product_id=item["product"].id, quantity=item["quantity"],
                       unit_price=item["price"])
        db.add(oi)
        item["product"].stock -= item["quantity"]

    if not (data and data.items):
        for ci in cart_items:
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
        items = [OrderItemResponse(
            product_id=i.product_id, name=i.product.name, quantity=i.quantity,
            unit_price=i.unit_price, image_url=i.product.image_url
        ) for i in o.items]
        res.append(OrderResponse(
            id=o.id, total_amount=o.total_amount, status=o.status.value,
            created_at=o.created_at, items=items
        ))
    return ResponseModel(data=res)
