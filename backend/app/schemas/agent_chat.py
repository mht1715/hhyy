from pydantic import BaseModel
from uuid import UUID
from typing import Optional


class DrugChatRequest(BaseModel):
    product_id: UUID
    message: str
    session_id: str  # 用于区分对话上下文
