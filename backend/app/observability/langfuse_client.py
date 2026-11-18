"""Langfuse 客户端接入（SDK 5.x，OpenTelemetry 原生）。

三条硬约束：

1. **未配置即降级**：``LANGFUSE_PUBLIC_KEY/SECRET_KEY/BASE_URL`` 任一为空，
   不初始化、不导入 SDK、不影响主链路。
2. **不做网络探测**：``get_trace_url()`` 会同步请求 Langfuse API 取 project_id，
   绝不能出现在请求路径里（只在需要生成跳转链接的运维脚本中用）。
3. **失败只记日志**：初始化或上报抛异常一律吞掉，AI 回复不能因为观测挂掉。

SDK 5.x 用「环境变量 + 全局 client」的模式：``CallbackHandler()`` 不带参数时按
``LANGFUSE_PUBLIC_KEY`` 解析同一个 client，因此这里把 settings 桥接到环境变量，
保证「trace 根节点」和「LangChain 自动埋的 generation」落在同一条 trace 上。
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

_ENV_KEYS = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST")


def _bridge_settings_to_env() -> None:
    """把 pydantic settings 里的配置桥接成 SDK 认识的环境变量。"""
    os.environ.setdefault("LANGFUSE_PUBLIC_KEY", settings.langfuse_public_key)
    os.environ.setdefault("LANGFUSE_SECRET_KEY", settings.langfuse_secret_key)
    os.environ.setdefault("LANGFUSE_HOST", settings.langfuse_base_url)


@lru_cache(maxsize=1)
def get_langfuse() -> Any | None:
    """返回已配置的 Langfuse client；未配置或初始化失败返回 None。"""
    if not settings.observability_enabled:
        logger.info("Langfuse 未配置（缺 key 或 host），观测功能关闭")
        return None

    try:
        _bridge_settings_to_env()
        from langfuse import get_client

        client = get_client()
        logger.info("Langfuse 已启用：%s", settings.langfuse_base_url)
        return client
    except Exception:  # noqa: BLE001 - 观测初始化失败绝不能影响服务启动
        logger.exception("Langfuse 初始化失败，降级为 no-op")
        return None


def observability_enabled() -> bool:
    return get_langfuse() is not None


def reset_observability_cache() -> None:
    """清缓存，仅供测试使用。"""
    get_langfuse.cache_clear()
    for key in _ENV_KEYS:
        os.environ.pop(key, None)
