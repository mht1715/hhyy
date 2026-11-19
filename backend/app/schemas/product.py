from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.core.media import normalize_image_url


class ProductBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=100, description="商品名称")
    generic_name: str = Field(..., min_length=2, max_length=100)
    image_url: str = ""
    price: float = Field(..., gt=0, description="价格必须大于0")
    original_price: float = Field(..., gt=0)
    stock: int = Field(..., ge=0, description="库存不能为负数")
    spec: str = "45ml"
    category: str = "中成药"
    dosage_form: str = "酊剂"
    shelf_life: str = "36个月"
    indications: str = Field(..., min_length=5)
    contraindications: str = Field(..., min_length=2)
    precautions: str = Field(..., min_length=2)
    adverse_reactions: str = ""
    approval_number: str
    manufacturer: str

    @field_validator("image_url")
    @classmethod
    def _normalize_image(cls, value: Optional[str]) -> Optional[str]:
        """历史数据里有反斜杠路径，接口出口统一纠正，前端才能正常显示。"""
        return normalize_image_url(value)


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    name: Optional[str] = None
    generic_name: Optional[str] = None
    image_url: Optional[str] = None
    price: Optional[float] = None
    original_price: Optional[float] = None
    stock: Optional[int] = None
    spec: Optional[str] = None
    category: Optional[str] = None
    dosage_form: Optional[str] = None
    shelf_life: Optional[str] = None
    indications: Optional[str] = None
    contraindications: Optional[str] = None
    precautions: Optional[str] = None
    adverse_reactions: Optional[str] = None
    approval_number: Optional[str] = None
    manufacturer: Optional[str] = None

    @field_validator("image_url")
    @classmethod
    def _normalize_image(cls, value: Optional[str]) -> Optional[str]:
        return normalize_image_url(value)


class ProductResponse(ProductBase):
    id: UUID
    sales: int

    class Config:
        from_attributes = True
