"""对话请求模型（M2-06）。

``mentions`` 必须是**结构化**的（PRD FR4.2）：后端不解析文本里的 ``@``。
``client_message_id`` 默认由服务端生成，但前端应当显式传（否则幂等不成立）。
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from pydantic import BaseModel, Field


class MentionIn(BaseModel):
    agent_code: str = Field(min_length=1, max_length=64)
    name: str = Field(default="", max_length=64)
    offset: int = Field(default=0, ge=0)


class ChatContext(BaseModel):
    product_id: Optional[uuid.UUID] = None
    order_id: Optional[uuid.UUID] = None


class ChatStreamRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    agent_code: str = Field(default="drug_consult", min_length=1, max_length=64)
    conversation_id: Optional[uuid.UUID] = None
    client_message_id: Optional[str] = Field(default=None, max_length=64)
    mentions: list[MentionIn] = Field(default_factory=list)
    context: ChatContext = Field(default_factory=ChatContext)

    def mention_dicts(self) -> list[dict[str, Any]]:
        return [mention.model_dump() for mention in self.mentions]
