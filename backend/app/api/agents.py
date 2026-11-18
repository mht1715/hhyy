"""前台 Agent 列表（M2-12 / FR4.8）。

只返回「当前角色可见」的卡片，字段刻意裁剪过（不含 prompt、模型、温度）——
前台需要的只是「叫什么、能干什么、点进去用哪个入口」。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.registry import AgentConfig, get_agent_registry
from app.api.auth import get_optional_user
from app.core.database import get_db
from app.models.user import User
from app.rag.acl import VISITOR_ROLE
from app.schemas.agent import AgentCard
from app.schemas.response import ResponseModel
from app.tools.base import TOOL_LABELS, get_tool

router = APIRouter()



def _capabilities(agent: AgentConfig) -> list[str]:
    caps = [f"知识库：{code}" for code in agent.kb_codes]
    for name in agent.tools:
        try:
            get_tool(name)
        except KeyError:
            continue
        caps.append(f"工具：{TOOL_LABELS.get(name, name)}")
    return caps


def to_card(agent: AgentConfig) -> AgentCard:
    return AgentCard(
        code=agent.code,
        name=agent.name,
        avatar=agent.avatar,
        description=agent.description,
        ui_mode=agent.ui_mode,
        entry=f"/agents/{agent.code}",
        tools=list(agent.tools),
        kb_codes=list(agent.kb_codes),
        capabilities=_capabilities(agent),
    )


@router.get("", response_model=ResponseModel[list[AgentCard]])
@router.get("/", response_model=ResponseModel[list[AgentCard]], include_in_schema=False)
async def list_agents(
    visible: bool = True,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
):
    role = current_user.role.value if current_user else VISITOR_ROLE
    registry = get_agent_registry()
    agents = await registry.all(db)

    if visible:
        cards = [to_card(agent) for agent in agents.values() if agent.is_active and agent.allows(role)]
    else:
        if current_user is None or current_user.role.value not in {"admin", "doctor"}:
            raise HTTPException(status_code=403, detail="权限不足，仅限管理员和医生操作")
        cards = [to_card(agent) for agent in agents.values() if agent.is_active]

    cards.sort(key=lambda card: card.code)
    return ResponseModel(data=cards)
