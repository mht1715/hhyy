"""转人工与坐席工单出入参（M3-08~M3-11，契约 §5）。"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from pydantic import BaseModel, Field


class HandoffRequest(BaseModel):
    conversation_id: uuid.UUID
    reason: Optional[str] = Field(default=None, max_length=200)


class OfflineRequest(BaseModel):
    conversation_id: uuid.UUID
    name: str = Field(min_length=1, max_length=32)
    contact: str = Field(min_length=3, max_length=64)
    demand: str = Field(min_length=2, max_length=300)


class TicketOut(BaseModel):
    ticket_id: str
    status: str
    queue_position: int = 0
    queue_expires_in: int = 0
    reason: str = ""
    trigger: str = ""
    risk_flags: list[str] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    conversation_id: str = ""
    created_at: str = ""
    assigned_to: str = ""
    wait_seconds: int = 0


class TicketListItem(TicketOut):
    conversation_title: str = ""
    user_label: str = ""


class AcceptOut(BaseModel):
    ticket_id: str
    status: str
    conversation_id: str
    status_of_conversation: str


class ResolveIn(BaseModel):
    tags: list[str] = Field(default_factory=list)


class AgentMessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class AgentMessageOut(BaseModel):
    message_id: str
    delivered: bool = True


class WsTicketOut(BaseModel):
    ws_ticket: str
    expires_in: int
    ws_url: str
