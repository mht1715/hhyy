from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID

from app.api.deps import AdminOrDoctor
from app.core.database import get_db
from app.models.product import Product
from app.schemas.product import ProductCreate, ProductUpdate, ProductResponse
from app.schemas.response import ResponseModel
from app.api.auth import get_current_user
from app.models.user import User, UserRole

router = APIRouter()


def require_roles(allowed_roles: list[UserRole]):
    def checker(current_user: User = Depends(get_current_user)):
        if current_user.role not in allowed_roles:
            raise HTTPException(status_code=403, detail="权限不足")
        return current_user

    return checker


@router.get("/", response_model=ResponseModel[list[ProductResponse]])
async def get_products(db: AsyncSession = Depends(get_db), current_user: User = AdminOrDoctor):
    result = await db.execute(select(Product).order_by(Product.created_at.desc()))
    return ResponseModel(data=result.scalars().all())


@router.post("/", response_model=ResponseModel[ProductResponse])
async def create_product(product_in: ProductCreate, db: AsyncSession = Depends(get_db),
                         current_user: User = AdminOrDoctor):
    new_product = Product(**product_in.model_dump())
    db.add(new_product)
    await db.commit()
    await db.refresh(new_product)
    return ResponseModel(data=new_product)


@router.put("/{product_id}", response_model=ResponseModel[ProductResponse])
async def update_product(product_id: UUID, product_in: ProductUpdate, db: AsyncSession = Depends(get_db),
                         current_user: User = AdminOrDoctor):
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="药品不存在")

    update_data = product_in.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(product, key, value)

    await db.commit()
    await db.refresh(product)
    return ResponseModel(data=product)


@router.delete("/{product_id}", response_model=ResponseModel[dict])
async def delete_product(product_id: UUID, db: AsyncSession = Depends(get_db), current_user: User = AdminOrDoctor):
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="药品不存在")

    await db.delete(product)
    await db.commit()
    return ResponseModel(data={"message": "删除成功"})


@router.get("/{product_id}", response_model=ResponseModel[ProductResponse])
async def get_product(
        product_id: UUID,
        db: AsyncSession = Depends(get_db)
):
    # 注意这里没有加 current_user: User = AdminOrDoctor，所以是公开接口
    result = await db.execute(select(Product).where(Product.id == product_id))
    product = result.scalar_one_or_none()
    if not product:
        raise HTTPException(status_code=404, detail="药品不存在")
    return ResponseModel(data=product)
