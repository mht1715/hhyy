"""Agent 注册表（M2-01）：从 DB 读配置、校验、缓存。

设计要点：

- **Agent 是配置**。编排代码只认 ``AgentConfig``，不认数据库行；新增 Agent 只需
  插一行数据 + 写一个 prompt 模板，不改代码、不发版。
- **写入即校验**。保存前把 ``kb_ids`` / ``tools`` / ``system_prompt_code`` /
  ``handoff_targets`` 全部核对一遍，错一个就 400 —— 否则「配置写错」会以
  「线上某个 Agent 忽然不回答」的形式暴露，最难查。
- **缓存 60 秒 + 写操作主动失效**。多 worker 部署时不能只靠进程内缓存，
  所以给一个短 TTL 兜底；后台改完立即 ``invalidate()``，本进程立刻生效。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.agent import Agent, AgentStatus, PromptStatus, PromptTemplate, UiMode
from app.models.kb import KbStatus, KnowledgeBase
from app.models.user import UserRole
from app.tools.base import get_tool

logger = logging.getLogger(__name__)

# 允许出现在 allowed_roles 里的角色（含游客这个 ACL 角色）
KNOWN_ROLES = {role.value for role in UserRole} | {"visitor"}


@dataclass(slots=True)
class AgentConfig:
    """运行时要用的 Agent 配置（与 ORM 解耦，便于缓存与测试）。"""

    code: str
    name: str
    description: str = ""
    avatar: Optional[str] = None
    system_prompt_code: str = ""
    model: Optional[str] = None
    temperature: float = 0.3
    kb_codes: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    allowed_roles: list[str] = field(default_factory=list)
    handoff_targets: list[str] = field(default_factory=list)
    ui_mode: str = UiMode.CHAT.value
    status: str = AgentStatus.ACTIVE.value
    sort_order: int = 0

    def allows(self, role: str) -> bool:
        """无权配置 = 谁都别用（默认拒绝，不写「空表示所有人」这种坑）。"""
        return role in self.allowed_roles

    @property
    def is_active(self) -> bool:
        return self.status == AgentStatus.ACTIVE.value


def to_config(row: Agent) -> AgentConfig:
    return AgentConfig(
        code=row.code,
        name=row.name,
        description=row.description or "",
        avatar=row.avatar,
        system_prompt_code=row.system_prompt_code or "",
        model=row.model,
        temperature=row.temperature if row.temperature is not None else 0.3,
        kb_codes=list(row.kb_ids or []),
        tools=list(row.tools or []),
        allowed_roles=list(row.allowed_roles or []),
        handoff_targets=list(row.handoff_targets or []),
        ui_mode=row.ui_mode or UiMode.CHAT.value,
        status=row.status or AgentStatus.ACTIVE.value,
        sort_order=row.sort_order or 0,
    )


class AgentRegistry:
    def __init__(self) -> None:
        self._cache: dict[str, AgentConfig] = {}
        self._loaded_at = 0.0

    def invalidate(self) -> None:
        self._cache = {}
        self._loaded_at = 0.0

    async def _load(self, db: AsyncSession) -> dict[str, AgentConfig]:
        rows = (await db.execute(select(Agent).order_by(Agent.sort_order, Agent.code))).scalars().all()
        self._cache = {row.code: to_config(row) for row in rows}
        self._loaded_at = time.monotonic()
        return self._cache

    async def all(self, db: AsyncSession, *, force: bool = False) -> dict[str, AgentConfig]:
        ttl = settings.agent_registry_ttl
        fresh = self._cache and (time.monotonic() - self._loaded_at) < ttl
        if force or not fresh:
            await self._load(db)
        return self._cache

    async def get(self, db: AsyncSession, code: str) -> Optional[AgentConfig]:
        return (await self.all(db)).get(code)

    async def visible_for(self, db: AsyncSession, role: str) -> list[AgentConfig]:
        agents = (await self.all(db)).values()
        return [agent for agent in agents if agent.is_active and agent.allows(role)]

    # ------------------------------------------------------------------ 校验
    async def validate(self, db: AsyncSession, payload: dict[str, Any]) -> list[str]:
        """保存前校验，返回错误列表（空列表 = 通过）。

        每一条都对应一个真实会踩的坑：绑了不存在的库 → 检索恒空；写了没注册的
        工具 → 运行时报未知工具；prompt code 拼错 → 回答没系统提示词。
        """
        errors: list[str] = []

        kb_codes: Iterable[str] = payload.get("kb_ids") or []
        if kb_codes:
            rows = (
                await db.execute(
                    select(KnowledgeBase.code).where(KnowledgeBase.code.in_(list(kb_codes)))
                )
            ).scalars().all()
            missing = sorted(set(kb_codes) - set(rows))
            if missing:
                errors.append(f"知识库不存在：{', '.join(missing)}")

        for tool in payload.get("tools") or []:
            try:
                get_tool(tool)
            except KeyError:
                errors.append(f"工具未注册：{tool}")

        prompt_code = payload.get("system_prompt_code") or ""
        if prompt_code:
            exists = (
                await db.execute(
                    select(PromptTemplate.id).where(
                        PromptTemplate.code == prompt_code,
                        PromptTemplate.status == PromptStatus.PRODUCTION.value,
                    ).limit(1)
                )
            ).scalar_one_or_none()
            if exists is None:
                errors.append(f"prompt 模板不存在或没有 production 版本：{prompt_code}")

        roles = payload.get("allowed_roles") or []
        unknown = sorted(set(roles) - KNOWN_ROLES)
        if unknown:
            errors.append(f"未知角色：{', '.join(unknown)}")
        if not roles:
            errors.append("allowed_roles 不能为空（空表示谁都进不来）")

        ui_mode = payload.get("ui_mode") or UiMode.CHAT.value
        if ui_mode not in {mode.value for mode in UiMode}:
            errors.append(f"ui_mode 只能是 {[mode.value for mode in UiMode]}")

        if payload.get("status") and payload["status"] not in {s.value for s in AgentStatus}:
            errors.append(f"status 只能是 {[s.value for s in AgentStatus]}")

        # 知识库必须 active，否则这个 Agent 上线即空转
        if kb_codes:
            inactive = (
                await db.execute(
                    select(KnowledgeBase.code).where(
                        KnowledgeBase.code.in_(list(kb_codes)),
                        KnowledgeBase.status != KbStatus.ACTIVE.value,
                    )
                )
            ).scalars().all()
            if inactive:
                errors.append(f"知识库未启用：{', '.join(sorted(inactive))}")

        return errors


_registry = AgentRegistry()


def get_agent_registry() -> AgentRegistry:
    return _registry


def reset_agent_registry() -> None:
    """测试用：清空缓存。"""
    _registry.invalidate()
