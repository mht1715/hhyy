"""时间的对外格式：一律 UTC + 带 ``Z``。

库里存的是「naive UTC」（列类型 ``DateTime`` 无时区，PG 容器时区为 ``Etc/UTC``，
``server_default=now()`` 落地就是 UTC）。如果直接把这种字符串发给浏览器，
JS 的 ``new Date('2026-11-18T15:07:00')`` 会按**本地时间**解析，
于是「等了 3 分钟」在页面上变成「等了 8 小时 3 分钟」。

所以出口统一走 :func:`iso_utc`：补上时区并转成 ``Z`` 结尾。
前提是数据库跑在 UTC（``docker-compose`` 的默认值），README 里写明了这一点。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional


def iso_utc(value: Any) -> str:
    """``datetime`` → ISO8601 UTC 字符串（``...Z``）；非时间返回空串。"""
    if not isinstance(value, datetime):
        return ""
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return aware.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_optional(value: Any) -> Optional[datetime]:
    return value if isinstance(value, datetime) else None


__all__ = ["iso_utc", "parse_optional"]
