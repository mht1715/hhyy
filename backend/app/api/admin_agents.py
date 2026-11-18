"""Agent 与 Prompt 管理（M2-01 / M4-05 的接口部分）。

两个原则：

- **保存即校验**：``kb_ids`` / ``tools`` / ``system_prompt_code`` 有一个写错就 400，
  并一次把错误全列出来（前端一次改完，不要挤牙膏式报错）。
- **写操作让注册表缓存立刻失效**：后台改完，本进程下一次请求就是新配置，
  不必等 60s TTL。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.registry import get_agent_registry
from app.api.admin_kb import _client_ip
from app.api.deps import AdminOnly
from app.core.database import get_db
from app.models.agent import Agent, AgentStatus, PromptStatus, PromptTemplate
from app.models.user import User
from app.schemas.agent import (
    AgentCreate,
    AgentOut,
    AgentUpdate,
    PromptTemplateCreate,
    PromptTemplateOut,
    PromptTemplateUpdate,
)
from app.schemas.response import ResponseModel
from app.services.audit import write_audit
from app.tools.base import list_tools

logger = logging.getLogger(__name__)

router = APIRouter()


async def _get_agent(db: AsyncSession, code: str) -> Agent:
    agent = (
        await db.execute(select(Agent).where(Agent.code == code))
    ).scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent 不存在：{code}")
    return agent


def _payload(model: Any) -> dict[str, Any]:
    data = model.model_dump(exclude_unset=True, exclude_none=True)
    data.pop("code", None)
    return data


async def _validate(db: AsyncSession, payload: dict[str, Any]) -> None:
    registry = get_agent_registry()
    errors = await registry.validate(db, payload)
    if errors:
        raise HTTPException(status_code=400, detail="；".join(errors))


# --------------------------------------------------------------------- Agent
@router.get("/agents", response_model=ResponseModel[list[AgentOut]])
async def list_agents(db: AsyncSession = Depends(get_db), current_user: User = AdminOnly):
    rows = (await db.execute(select(Agent).order_by(Agent.sort_order, Agent.code))).scalars().all()
    return ResponseModel(data=list(rows))


@router.post("/agents", response_model=ResponseModel[AgentOut])
async def create_agent(
    payload: AgentCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = AdminOnly,
):
    exists = (await db.execute(select(Agent.id).where(Agent.code == payload.code))).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=400, detail=f"Agent code 已存在：{payload.code}")

    data = payload.model_dump()
    await _validate(db, data)

    agent = Agent(**data)
    db.add(agent)
    await write_audit(
        db,
        action="agent.create",
        target_type="agent",
        target_id=agent.code,
        actor=current_user,
        after=data,
        ip=_client_ip(request),
    )
    await db.commit()
    await db.refresh(agent)
    get_agent_registry().invalidate()
    return ResponseModel(data=agent)


@router.get("/agents/{code}", response_model=ResponseModel[AgentOut])
async def get_agent(code: str, db: AsyncSession = Depends(get_db), current_user: User = AdminOnly):
    return ResponseModel(data=await _get_agent(db, code))


@router.put("/agents/{code}", response_model=ResponseModel[AgentOut])
async def update_agent(
    code: str,
    payload: AgentUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = AdminOnly,
):
    agent = await _get_agent(db, code)
    changes = _payload(payload)

    merged = {
        "kb_ids": changes.get("kb_ids", agent.kb_ids),
        "tools": changes.get("tools", agent.tools),
        "allowed_roles": changes.get("allowed_roles", agent.allowed_roles),
        "system_prompt_code": changes.get("system_prompt_code", agent.system_prompt_code),
        "ui_mode": changes.get("ui_mode", agent.ui_mode),
        "status": changes.get("status", agent.status),
    }
    await _validate(db, merged)

    before = {key: getattr(agent, key) for key in changes}
    for key, value in changes.items():
        setattr(agent, key, value)

    await write_audit(
        db,
        action="agent.update",
        target_type="agent",
        target_id=code,
        actor=current_user,
        before=before,
        after=changes,
        ip=_client_ip(request),
    )
    await db.commit()
    await db.refresh(agent)
    get_agent_registry().invalidate()
    return ResponseModel(data=agent)


@router.delete("/agents/{code}", response_model=ResponseModel[dict])
async def archive_agent(
    code: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = AdminOnly,
):
    """归档而不是物理删除：历史消息里还引用着这个 code，删了会断链。"""
    agent = await _get_agent(db, code)
    agent.status = AgentStatus.ARCHIVED.value
    await write_audit(
        db,
        action="agent.archive",
        target_type="agent",
        target_id=code,
        actor=current_user,
        ip=_client_ip(request),
    )
    await db.commit()
    get_agent_registry().invalidate()
    return ResponseModel(data={"code": code, "status": agent.status})


# --------------------------------------------------------------------- Prompt
@router.get("/prompts", response_model=ResponseModel[list[PromptTemplateOut]])
async def list_prompts(
    code: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = AdminOnly,
):
    statement = select(PromptTemplate).order_by(PromptTemplate.code, PromptTemplate.version.desc())
    if code:
        statement = statement.where(PromptTemplate.code == code)
    rows = (await db.execute(statement)).scalars().all()
    return ResponseModel(data=list(rows))


@router.post("/prompts", response_model=ResponseModel[PromptTemplateOut])
async def create_prompt(
    payload: PromptTemplateCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = AdminOnly,
):
    version = payload.version
    if version is None:
        latest = (
            await db.execute(
                select(PromptTemplate.version)
                .where(PromptTemplate.code == payload.code)
                .order_by(PromptTemplate.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        version = (latest or 0) + 1

    exists = (
        await db.execute(
            select(PromptTemplate.id).where(
                PromptTemplate.code == payload.code, PromptTemplate.version == version
            )
        )
    ).scalar_one_or_none()
    if exists:
        raise HTTPException(status_code=400, detail=f"{payload.code} v{version} 已存在")

    if payload.status not in {status.value for status in PromptStatus}:
        raise HTTPException(status_code=400, detail=f"status 只能是 {[s.value for s in PromptStatus]}")

    if payload.status == PromptStatus.PRODUCTION.value:
        # 一个 code 只留一个 production：否则 load_prompt 取谁取决于排序，线上会「随机」变
        for row in (
            await db.execute(
                select(PromptTemplate).where(
                    PromptTemplate.code == payload.code,
                    PromptTemplate.status == PromptStatus.PRODUCTION.value,
                )
            )
        ).scalars().all():
            row.status = PromptStatus.ARCHIVED.value

    prompt = PromptTemplate(
        code=payload.code,
        version=version,
        content=payload.content,
        variables_schema=payload.variables_schema,
        model=payload.model,
        status=payload.status,
        labels=payload.labels,
        rollout=payload.rollout,
    )
    db.add(prompt)
    await write_audit(
        db,
        action="prompt.create",
        target_type="prompt_template",
        target_id=f"{payload.code}@v{version}",
        actor=current_user,
        after={"code": payload.code, "version": version, "status": payload.status},
        ip=_client_ip(request),
    )
    await db.commit()
    await db.refresh(prompt)
    return ResponseModel(data=prompt)


@router.put("/prompts/{prompt_id}", response_model=ResponseModel[PromptTemplateOut])
async def update_prompt(
    prompt_id: uuid.UUID,
    payload: PromptTemplateUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = AdminOnly,
):
    prompt = await db.get(PromptTemplate, prompt_id)
    if prompt is None:
        raise HTTPException(status_code=404, detail="prompt 不存在")

    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    if changes.get("status") == PromptStatus.PRODUCTION.value:
        for row in (
            await db.execute(
                select(PromptTemplate).where(
                    PromptTemplate.code == prompt.code,
                    PromptTemplate.status == PromptStatus.PRODUCTION.value,
                    PromptTemplate.id != prompt.id,
                )
            )
        ).scalars().all():
            row.status = PromptStatus.ARCHIVED.value

    for key, value in changes.items():
        setattr(prompt, key, value)
    await write_audit(
        db,
        action="prompt.update",
        target_type="prompt_template",
        target_id=str(prompt.id),
        actor=current_user,
        after=changes,
        ip=_client_ip(request),
    )
    await db.commit()
    await db.refresh(prompt)
    return ResponseModel(data=prompt)


# --------------------------------------------------------------------- 工具清单
@router.get("/tools", response_model=ResponseModel[list[dict]])
async def list_available_tools(current_user: User = AdminOnly):
    """给后台下拉用：工具名 + 描述 + JSON Schema（Function Calling 同一份）。"""
    return ResponseModel(
        data=[
            {
                "name": tool.spec.name,
                "description": tool.spec.description,
                "required_roles": list(tool.spec.required_roles),
                "timeout_seconds": tool.spec.timeout_seconds,
                "schema": tool.spec.as_function_schema(),
            }
            for tool in list_tools()
        ]
    )
