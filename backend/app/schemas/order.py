from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import List, Optional


class OrderItemResponse(BaseModel):
    product_id: UUID
    name: str
    quantity: int
    unit_price: float
    image_url: Optional[str] = None


class OrderResponse(BaseModel):
    id: UUID
    total_amount: float
    status: str
    created_at: datetime
    items: List[OrderItemResponse]
