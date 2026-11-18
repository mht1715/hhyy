"""Prompt 版本的解析规则（M4-05）。

抽成一个纯函数，是为了让「运行时取哪一版」和「后台预览命中哪一版」共用同一份逻辑——
两边各写一遍，灰度演示就会出现「后台说是 v3、实际跑的是 v2」这种最难解释的问题。

规则（按优先级）：

1. **testing 且 rollout > 0 的版本**：按 ``hash(user) % 100 < rollout`` 命中，
   命中多个时取版本号最大的那个（新版本优先）。
2. 否则取 **production**。
3. 都没有就用内置模板（返回空 version，调用方降级）。
"""

from __future__ import annotations

import hashlib
from typing import Any, Iterable


def rollout_bucket(user_id: Any) -> int:
    """把用户稳定映射到 0~99。

    用 ``sha1`` 而不是 Python ``hash()``：后者有进程级随机种子，重启后同一用户
    会跳到另一个版本，灰度就变成了「随机抖动」。
    """
    if user_id is None:
        return 0
    digest = hashlib.sha1(str(user_id).encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 100


def resolve_prompt_rows(
    rows: Iterable[Any], *, bucket: int
) -> tuple[Any | None, str]:
    """从候选行里选一条 → ``(row, reason)``。

    ``rows`` 需带 ``status`` / ``rollout`` / ``version`` 属性（ORM 行或替身都行）。
    ``reason`` 是给后台/日志看的中文说明，例如「灰度命中 v3（rollout=20，桶=7）」。
    """
    items = list(rows)
    production = None
    testing = []
    for row in items:
        status = getattr(row, "status", "")
        if status == "production":
            # 同一个 code 正常只有一个 production；多个时取版本号最大的
            if production is None or getattr(row, "version", 0) > getattr(production, "version", 0):
                production = row
        elif status == "testing" and int(getattr(row, "rollout", 0) or 0) > 0:
            testing.append(row)

    for row in sorted(testing, key=lambda item: getattr(item, "version", 0), reverse=True):
        rollout = int(getattr(row, "rollout", 0) or 0)
        if bucket < rollout:
            return row, f"灰度命中 v{getattr(row, 'version', 0)}（rollout={rollout}%，桶={bucket}）"

    if production is not None:
        return production, f"production v{getattr(production, 'version', 0)}"
    return None, "没有 production / 灰度版本，使用内置模板"


def version_label(row: Any) -> str:
    """``drug_consult@v3`` 这种可读标签，落库到 ``messages.prompt_version``。"""
    if row is None:
        return ""
    code = getattr(row, "code", "") or ""
    version = getattr(row, "version", None)
    if not code or version is None:
        return ""
    return f"{code}@v{version}"


__all__ = ["resolve_prompt_rows", "rollout_bucket", "version_label"]
