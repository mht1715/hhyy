"""Agent 与 Prompt 模板的请求/响应模型（M2-01 / M4-05 共用）。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

CODE_PATTERN = r"^[a-z][a-z0-9_]{1,63}$"


class AgentFields(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    avatar: Optional[str] = Field(default=None, max_length=255)
    description: str = ""
    system_prompt_code: str = ""
    model: Optional[str] = None
    temperature: float = Field(default=0.3, ge=0.0, le=1.0)
    kb_ids: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    allowed_roles: list[str] = Field(default_factory=list)
    handoff_targets: list[str] = Field(default_factory=list)
    ui_mode: str = "chat"
    status: str = "active"
    sort_order: int = 0


class AgentCreate(AgentFields):
    code: str = Field(pattern=CODE_PATTERN)


class AgentUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=64)
    avatar: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = None
    system_prompt_code: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    kb_ids: Optional[list[str]] = None
    tools: Optional[list[str]] = None
    allowed_roles: Optional[list[str]] = None
    handoff_targets: Optional[list[str]] = None
    ui_mode: Optional[str] = None
    status: Optional[str] = None
    sort_order: Optional[int] = None


class AgentOut(AgentFields):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    created_at: datetime
    updated_at: datetime


class AgentCard(BaseModel):
    """前台广场/`@` 候选用的卡片（不暴露 prompt、模型等内部字段）。"""

    code: str
    name: str
    avatar: Optional[str] = None
    description: str = ""
    ui_mode: str = "chat"
    entry: str = ""
    tools: list[str] = Field(default_factory=list)
    kb_codes: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)


class PromptTemplateCreate(BaseModel):
    code: str = Field(pattern=CODE_PATTERN)
    content: str = Field(min_length=1)
    version: Optional[int] = Field(default=None, ge=1)
    variables_schema: dict[str, Any] = Field(default_factory=dict)
    model: Optional[str] = None
    status: str = "production"
    labels: list[str] = Field(default_factory=list)
    rollout: int = Field(default=100, ge=0, le=100)


class PromptTemplateUpdate(BaseModel):
    content: Optional[str] = None
    variables_schema: Optional[dict[str, Any]] = None
    model: Optional[str] = None
    status: Optional[str] = None
    labels: Optional[list[str]] = None
    rollout: Optional[int] = Field(default=None, ge=0, le=100)


class PromptPreviewIn(BaseModel):
    """后台「渲染预览」：只替换给了值的变量，缺的变量原样保留并单独返回。"""

    variables: dict[str, Any] = Field(default_factory=dict)


class PromptTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    version: int
    content: str
    variables_schema: dict[str, Any] = Field(default_factory=dict)
    model: Optional[str] = None
    status: str
    labels: list[str] = Field(default_factory=list)
    rollout: int
    created_at: datetime
    updated_at: datetime
