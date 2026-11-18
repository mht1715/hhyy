"""ACL 矩阵集成测试（需要真 PG + 迁移已执行）。

默认跳过；显式开启：

```bash
$env:RUN_INTEGRATION=1; pytest backend/tests/integration -q
```

覆盖 PRD M1-09 的验收：5 角色 × 4 库矩阵全过，且「默认拒绝」成立。
"""

from __future__ import annotations

import pytest

from app.core.database import AsyncSessionLocal
from app.models.kb import KbRolePermission, KnowledgeBase
from app.rag.acl import invalidate_acl, resolve_acl

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_permission_matrix_5_roles_x_4_kbs():
    async with AsyncSessionLocal() as db:
        specs = [
            # code, visibility, status, 授权角色
            ("it_company", "public", "active", []),
            ("it_manual", "private", "active", ["patient", "doctor", "support"]),
            ("it_after_sale", "private", "active", ["doctor", "support"]),
            ("it_sop", "private", "active", ["support"]),
        ]
        created: list[KnowledgeBase] = []
        try:
            for code, visibility, status, roles in specs:
                kb = KnowledgeBase(
                    code=code,
                    name=code,
                    visibility=visibility,
                    status=status,
                    chunk_strategy="structured",
                )
                db.add(kb)
                await db.flush()
                created.append(kb)
                for role in roles:
                    db.add(KbRolePermission(kb_id=kb.id, role=role, can_read=True))
            await db.commit()
            await invalidate_acl()

            expected = {
                "visitor": {"it_company"},
                "patient": {"it_company", "it_manual"},
                "doctor": {"it_company", "it_manual", "it_after_sale"},
                "support": {"it_company", "it_manual", "it_after_sale", "it_sop"},
                "admin": {"it_company", "it_manual", "it_after_sale", "it_sop"},
            }
            for role, codes in expected.items():
                snapshot = await resolve_acl(db, role=role, use_cache=False)
                got = {snapshot.kb_codes[kb_id] for kb_id in snapshot.kb_ids if kb_id in snapshot.kb_codes}
                # 只比对本次创建的库，避免被 seed 数据干扰
                got &= set(c[0] for c in specs)
                assert got == codes, f"{role} 期望 {codes}，实际 {got}"

            # 默认拒绝：没有任何授权行的私有库对 patient 必须不可见
            patient = await resolve_acl(db, role="patient", use_cache=False)
            assert not (set(patient.kb_codes.values()) & {"it_sop", "it_after_sale"})

        finally:
            for kb in created:
                await db.delete(kb)
            await db.commit()
            await invalidate_acl()
