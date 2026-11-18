"""知识库 ACL（M1-09）：谁能检索到哪些库。

两条铁律（PRD §3.2）在这里落地：

1. **默认拒绝**：``kb_role_permissions`` 里没有行就是没有权限，代码里没有任何
   「未配置 = 放行」的分支。``visibility=public`` 是唯一的例外，且它等价于
   「显式授权给所有人」，仍然要写进库里可见。
2. **过滤下推到检索层**：本模块只产出 ``kb_id`` 集合和 Milvus 表达式，
   检索时必须把它们交给向量库，绝不允许「先召回再过滤」。

缓存：``acl:v{ver}:{role}:{user}``，TTL 30s（PRD §3.4 的 ≤30s 生效）。
失效策略用**版本号自增**而不是 ``keys acl:*`` 模式删除——后者在共享 Redis 上是
禁忌操作，而版本号只是一次 INCR，旧 key 自然过期。
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.redis import cache_get, cache_incr, cache_set
from app.models.kb import KbRolePermission, KbStatus, KbVisibility, KnowledgeBase
from app.models.user import UserRole

logger = logging.getLogger(__name__)

VISITOR_ROLE = "visitor"
_ACL_VERSION_KEY = "acl:ver"


@dataclass(slots=True)
class AclSnapshot:
    """一次权限判定的结果。"""

    role: str
    kb_ids: list[str] = field(default_factory=list)
    kb_codes: dict[str, str] = field(default_factory=dict)
    # 存在但当前角色无权访问的库，仅用于后台检索测试台展示「过滤掉了哪些」
    denied_kb_ids: list[str] = field(default_factory=list)
    denied_kb_codes: dict[str, str] = field(default_factory=dict)
    from_cache: bool = False

    @property
    def empty(self) -> bool:
        return not self.kb_ids

    def to_json(self) -> str:
        return json.dumps(
            {
                "kb_ids": self.kb_ids,
                "kb_codes": self.kb_codes,
                "denied": self.denied_kb_ids,
                "denied_codes": self.denied_kb_codes,
            },
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, payload: str, *, role: str) -> AclSnapshot | None:
        try:
            data = json.loads(payload)
        except (TypeError, ValueError):
            return None
        return cls(
            role=role,
            kb_ids=list(data.get("kb_ids", [])),
            kb_codes=dict(data.get("kb_codes", {})),
            denied_kb_ids=list(data.get("denied", [])),
            denied_kb_codes=dict(data.get("denied_codes", {})),
            from_cache=True,
        )


def _role_value(role: UserRole | str) -> str:
    return role.value if isinstance(role, UserRole) else str(role)


async def _acl_version() -> str:
    version = await cache_get(_ACL_VERSION_KEY)
    return version or "0"


async def invalidate_acl() -> None:
    """权限变更后调用：版本号 +1，旧缓存全部失去意义。"""
    await cache_incr(_ACL_VERSION_KEY)


async def resolve_acl(
    db: AsyncSession,
    *,
    role: UserRole | str,
    user_id: uuid.UUID | str | None = None,
    use_cache: bool = True,
) -> AclSnapshot:
    """算出该角色（及该用户）可检索的知识库集合。"""
    role_value = _role_value(role)
    cache_key = f"acl:v{await _acl_version()}:{role_value}:{user_id or '-'}" if use_cache else ""

    if use_cache:
        cached = await cache_get(cache_key)
        if cached:
            snapshot = AclSnapshot.from_json(cached, role=role_value)
            if snapshot is not None:
                return snapshot

    rows = (
        await db.execute(
            select(
                KnowledgeBase.id,
                KnowledgeBase.code,
                KnowledgeBase.visibility,
                KnowledgeBase.status,
            ).order_by(KnowledgeBase.created_at)
        )
    ).all()

    granted: set[str] = set()
    if role_value != VISITOR_ROLE:
        permission_rows = (
            await db.execute(
                select(KbRolePermission.kb_id).where(
                    KbRolePermission.role == role_value,
                    KbRolePermission.can_read.is_(True),
                )
            )
        ).scalars().all()
        granted = {str(kb_id) for kb_id in permission_rows}

    snapshot = AclSnapshot(role=role_value)
    for kb_id, code, visibility, status in rows:
        kb_key = str(kb_id)
        if status == KbStatus.ARCHIVED.value:
            # 归档库对谁都不可检索（数据仍在），不参与「被拒绝」展示
            continue
        allowed = (
            status == KbStatus.ACTIVE.value
            and (
                role_value == UserRole.ADMIN.value
                or kb_key in granted
                or visibility == KbVisibility.PUBLIC.value
            )
        )
        if allowed:
            snapshot.kb_ids.append(kb_key)
            snapshot.kb_codes[kb_key] = code
        else:
            snapshot.denied_kb_ids.append(kb_key)
            snapshot.denied_kb_codes[kb_key] = code

    if use_cache:
        await cache_set(cache_key, snapshot.to_json(), ttl=settings.acl_cache_ttl)
    return snapshot


async def allowed_kb_ids(
    db: AsyncSession,
    *,
    role: UserRole | str,
    user_id: uuid.UUID | str | None = None,
) -> list[str]:
    """只要 id 列表时的便捷入口。"""
    snapshot = await resolve_acl(db, role=role, user_id=user_id)
    return snapshot.kb_ids


def build_filter(
    kb_ids: list[str],
    *,
    status: str = "published",
    include_effective: bool = True,
    now: int | None = None,
) -> str | None:
    """构造 Milvus 过滤表达式。

    ``kb_ids`` 为空时返回 ``None``——**调用方必须据此直接拒答**，
    不能退化成「不带过滤条件查全库」，那是数据泄露。
    """
    if not kb_ids:
        return None

    quoted = ", ".join('"' + _quote(kb_id) + '"' for kb_id in kb_ids)
    conditions = [f"kb_id in [{quoted}]", f'status == "{status}"']
    if include_effective:
        ts = int(now if now is not None else time.time())
        # 0 表示不限，用 0 哨兵而不是 NULL，省掉表达式里的 null 判断（Milvus 表达式对 null 支持有限）
        conditions.append(f"(effective_from == 0 or effective_from <= {ts})")
        conditions.append(f"(effective_to == 0 or effective_to >= {ts})")
    return " and ".join(conditions)


def _quote(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def describe_acl(snapshot: AclSnapshot, *, names: dict[str, str] | None = None) -> dict[str, Any]:
    """给检索测试台用的可读摘要。"""
    names = names or {}
    return {
        "role": snapshot.role,
        "allowed": [
            {"kb_id": kb_id, "code": snapshot.kb_codes.get(kb_id), "name": names.get(kb_id)}
            for kb_id in snapshot.kb_ids
        ],
        "filtered_out_kbs": [
            {"kb_id": kb_id, "code": snapshot.denied_kb_codes.get(kb_id), "name": names.get(kb_id)}
            for kb_id in snapshot.denied_kb_ids
        ],
        "from_cache": snapshot.from_cache,
    }
