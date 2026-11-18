from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel


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
