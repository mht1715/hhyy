from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel


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
