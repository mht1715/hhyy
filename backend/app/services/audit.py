"""审计日志（M1-10 / PRD FR2.8）。

约定：``write_audit`` **只 add + flush，不 commit**。理由是审计必须和业务变更
在同一个事务里落库——"改成功了但没记审计"和"记了审计但没改成功"都是事故。
调用方在提交业务变更时一起提交。
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.kb import AuditLog
from app.models.user import User


def jsonable(value: Any) -> Any:
    """把 UUID / datetime / Enum 转成可存 JSONB 的形式（递归）。"""
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(item) for item in value]
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, enum.Enum):
        return value.value
    return value


async def write_audit(
    db: AsyncSession,
    *,
    action: str,
    target_type: str,
    target_id: str,
    actor: User | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    ip: str | None = None,
) -> AuditLog:
    record = AuditLog(
        actor_id=actor.id if actor else None,
        actor_role=actor.role.value if actor and actor.role else None,
        action=action,
        target_type=target_type,
        target_id=str(target_id)[:64],
        before=jsonable(before),
        after=jsonable(after),
        ip=ip,
    )
    db.add(record)
    await db.flush()
    return record
