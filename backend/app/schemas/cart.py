from pydantic import BaseModel
from uuid import UUID
from typing import Optional, List


class CartAdd(BaseModel):
    product_id: UUID
    quantity: int = 1


class CartItemResponse(BaseModel):
    id: UUID
    product_id: UUID
    quantity: int
    name: str
    price: float
    image_url: Optional[str] = None
    spec: Optional[str] = None


class CartResponse(BaseModel):
    items: List[CartItemResponse]
    total_price: float
