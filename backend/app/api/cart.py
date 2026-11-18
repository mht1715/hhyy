from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import AnyUser
from app.core.database import get_db
from app.models.cart import CartItem
from app.models.product import Product
from app.models.user import User
from app.schemas.cart import CartAdd, CartItemResponse, CartResponse
from app.schemas.response import ResponseModel

router = APIRouter()


class CartUpdate(BaseModel):
    quantity: int = Field(..., ge=1)  # ge=1 表示大于等于 1，不满足会直接报 422 错误


@router.get("", response_model=ResponseModel[CartResponse])
async def get_cart(db: AsyncSession = Depends(get_db), current_user: User = AnyUser):
    result = await db.execute(
        select(CartItem).where(CartItem.user_id == current_user.id).options(selectinload(CartItem.product))
    )
    items = result.scalars().all()

    res_items = []
    total = 0.0
    for item in items:
        res_items.append(CartItemResponse(
            id=item.id, product_id=item.product_id, quantity=item.quantity,
            name=item.product.name, price=item.product.price,
            image_url=item.product.image_url, spec=item.product.spec
        ))
        total += item.product.price * item.quantity

    return ResponseModel(data=CartResponse(items=res_items, total_price=total))


@router.post("", response_model=ResponseModel[dict])
async def add_to_cart(data: CartAdd, db: AsyncSession = Depends(get_db), current_user: User = AnyUser):
    # 检查商品是否存在
    prod = await db.get(Product, data.product_id)
    if not prod:
        raise HTTPException(404, "商品不存在")

    # 检查购物车是否已有
    result = await db.execute(
        select(CartItem).where(CartItem.user_id == current_user.id, CartItem.product_id == data.product_id))
    item = result.scalar_one_or_none()

    if item:
        item.quantity += data.quantity
    else:
        item = CartItem(user_id=current_user.id, product_id=data.product_id, quantity=data.quantity)
        db.add(item)

    await db.commit()
    return ResponseModel(data={"message": "添加成功"})


@router.delete("/{item_id}", response_model=ResponseModel[dict])
async def remove_item(item_id: UUID, db: AsyncSession = Depends(get_db), current_user: User = AnyUser):
    result = await db.execute(select(CartItem).where(CartItem.id == item_id, CartItem.user_id == current_user.id))
    item = result.scalar_one_or_none()
    if item:
        await db.delete(item)
        await db.commit()
    return ResponseModel(data={"message": "删除成功"})


@router.delete("", response_model=ResponseModel[dict])
async def clear_cart(db: AsyncSession = Depends(get_db), current_user: User = AnyUser):
    await db.execute(select(CartItem).where(CartItem.user_id == current_user.id))
    items = (await db.execute(select(CartItem).where(CartItem.user_id == current_user.id))).scalars().all()
    for item in items:
        await db.delete(item)
    await db.commit()
    return ResponseModel(data={"message": "已清空"})


@router.put("/{item_id}", response_model=ResponseModel[dict])
async def update_cart_item(
        item_id: UUID,
        data: CartUpdate,
        db: AsyncSession = Depends(get_db),
        current_user: User = AnyUser
):
    result = await db.execute(select(CartItem).where(CartItem.id == item_id, CartItem.user_id == current_user.id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(404, "购物车记录不存在")

    item.quantity = data.quantity
    await db.commit()
    return ResponseModel(data={"message": "更新成功"})


class CartUpdate(BaseModel):
    quantity: int
