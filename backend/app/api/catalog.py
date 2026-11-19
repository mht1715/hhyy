"""药品目录（公开只读）。

`GET /api/products` 是后台接口（仅 admin/doctor，带库存维护权限），游客和患者打不开。
但「药品广场」是 C 端入口：不登录也要能逛，登录后才能加购。所以单独开一个只读目录，
**只返回展示需要的字段**（价格 / 规格 / 图片 / 分类），不暴露成本价、库存流水这类后台数据。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.media import normalize_image_url
from app.models.product import Product
from app.schemas.response import ResponseModel

router = APIRouter()

MAX_ITEMS = 60


@router.get("/products", response_model=ResponseModel[list[dict]])
async def list_catalog(
    keyword: str = Query(default="", max_length=32),
    category: str = Query(default="", max_length=32),
    db: AsyncSession = Depends(get_db),
):
    """药品广场：无需登录、只读。

    ``keyword`` 同时匹配名称/通用名/适应症，够用且不引入分词——
    目录规模只有几十条，前端本地过滤也可以，但放后端能让首页请求少一次全量拉取。
    """
    stmt = select(Product).order_by(Product.created_at.desc()).limit(MAX_ITEMS)
    if category and category != "全部":
        stmt = stmt.where(Product.category == category)
    text = (keyword or "").strip()
    if text:
        like = f"%{text}%"
        stmt = stmt.where(
            or_(
                Product.name.ilike(like),
                Product.generic_name.ilike(like),
                Product.indications.ilike(like),
            )
        )

    rows = (await db.execute(stmt)).scalars().all()
    data: list[dict[str, Any]] = [
        {
            "id": str(item.id),
            "name": item.name,
            "generic_name": item.generic_name or "",
            "category": item.category or "",
            "dosage_form": item.dosage_form or "",
            "spec": item.spec or "",
            "price": float(item.price or 0),
            "original_price": float(item.original_price or 0),
            "stock": int(item.stock or 0),
            "image_url": normalize_image_url(item.image_url) or "",
            "indications": (item.indications or "")[:120],
            "on_sale": bool(int(item.stock or 0) > 0),
        }
        for item in rows
    ]
    return ResponseModel(data=data)


@router.get("/categories", response_model=ResponseModel[list[str]])
async def list_categories(db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(Product.category).distinct())).scalars().all()
    data = sorted({str(item) for item in rows if item})
    return ResponseModel(data=data)


__all__ = ["router", "MAX_ITEMS"]
