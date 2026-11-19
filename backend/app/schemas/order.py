from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, field_validator

from app.core.media import normalize_image_url


class OrderItemResponse(BaseModel):
    product_id: UUID
    name: str
    quantity: int
    unit_price: float
    image_url: Optional[str] = None

    @field_validator("image_url")
    @classmethod
    def _normalize_image(cls, value: Optional[str]) -> Optional[str]:
        return normalize_image_url(value)


class OrderResponse(BaseModel):
    id: UUID
    total_amount: float
    status: str
    created_at: datetime
    items: List[OrderItemResponse]


class AdminOrderResponse(OrderResponse):
    """管理员视角多两个归属字段：这单是谁下的。"""

    user_id: UUID
    username: str
