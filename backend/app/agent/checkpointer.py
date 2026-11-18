"""LangGraph checkpointer（M3-01）：把图状态按会话持久化到 Postgres。

为什么要有它，而不是「反正消息都落 ``messages`` 表了」：

- ``messages`` 表是**给人和接口看的**（列表、引用、审计），它没有「图跑到哪一步」。
- checkpointer 存的是**图自己的状态**（本轮路由决策、引用、守卫结果、最近 40 条
  对话投影）。进程重启、换 worker 后，同一个 ``thread_id``（= ``conversation_id``）
  仍能接着跑——这是「短期记忆」真正落地的地方（PRD FR6.1）。

两个工程细节：

1. **表由库自带 ``setup()`` 建**，不写进 Alembic。手写表结构会在库升级时漂移，
   而且 checkpointer 的迁移逻辑只有库自己知道（任务清单 M3-01 的明确要求）。
   ``setup()`` 是幂等的（``CREATE TABLE IF NOT EXISTS``），启动时调一次即可。
2. **Windows 上必须用 SelectorEventLoop**：``psycopg`` 的异步连接不支持
   ProactorEventLoop（Python 3.8+ 在 Windows 的默认值），会直接抛
   ``InterfaceError: Psycopg cannot use the 'ProactorEventLoop'``。事件循环策略
   必须**在 loop 启动前**设置（见 ``app/main.py``），这里只做兜底提示。
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

_saver: Any | None = None
_cm: Any | None = None
_lock: asyncio.Lock | None = None


def _lock_obj() -> asyncio.Lock:
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


def dsn() -> str:
    """psycopg 用的同步 DSN（不能带 ``+asyncpg``）。"""
    return (
        f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_server}:{settings.postgres_port}/{settings.postgres_db}"
    )


def thread_config(conversation_id: Any) -> dict[str, Any]:
    """``thread_id`` 用会话 id：一个会话一条线程，跨轮次累积。"""
    return {"configurable": {"thread_id": str(conversation_id)}}


async def get_checkpointer() -> Any | None:
    """取全局 checkpointer，懒加载；不可用时返回 ``None``（对话照常跑，只是不持久化）。"""
    if not settings.checkpointer_enabled:
        return None

    global _saver, _cm
    if _saver is not None:
        return _saver

    async with _lock_obj():
        if _saver is not None:
            return _saver
        if sys.platform == "win32":
            # 判**正在跑的 loop**，而不是事件循环策略：策略可能已经被设置成
            # Selector，但 loop 是在设置之前创建的（uvicorn 无 --reload 时就是这种情况），
            # 那种时候 psycopg 一样会抛 InterfaceError。
            loop = asyncio.get_running_loop()
            if "Proactor" in type(loop).__name__:
                logger.warning(
                    "当前事件循环是 %s，psycopg 异步连接需要 SelectorEventLoop；"
                    "checkpointer 不可用（对话不受影响）。请用 ``python serve.py`` "
                    "或 ``uvicorn --reload`` 启动。",
                    type(loop).__name__,
                )
                return None
        try:
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            cm = AsyncPostgresSaver.from_conn_string(dsn())
            saver = await cm.__aenter__()
            await saver.setup()
        except Exception as exc:  # noqa: BLE001 —— 持久化失败不能拖垮对话
            logger.warning("checkpointer 初始化失败（本轮不持久化图状态）：%s", exc)
            return None
        _cm, _saver = cm, saver
        logger.info("checkpointer 就绪（Postgres，thread_id=conversation_id）")
        return _saver


async def close_checkpointer() -> None:
    """进程退出时关闭连接（lifespan 里调）。"""
    global _saver, _cm
    if _cm is not None:
        try:
            await _cm.__aexit__(None, None, None)
        except Exception:  # noqa: BLE001
            logger.debug("关闭 checkpointer 失败", exc_info=True)
    _saver = None
    _cm = None


async def init_checkpointer() -> bool:
    """幂等初始化（建表）。供启动钩子与 ``script/`` 反复调用。"""
    return (await get_checkpointer()) is not None


async def read_thread_state(conversation_id: Any) -> Optional[dict[str, Any]]:
    """读某会话最近一次图状态；没有（或不可用）返回 ``None``。

    用于「重启后续上下文」的自检与后台排障：能看到上一轮的 ``route`` / ``citations`` /
    最近对话投影，就说明状态真的落库了。
    """
    saver = await get_checkpointer()
    if saver is None or not conversation_id:
        return None
    try:
        tup = await saver.aget_tuple(thread_config(conversation_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取 checkpointer 状态失败：%s", exc)
        return None
    if tup is None:
        return None
    values = dict((tup.checkpoint or {}).get("channel_values") or {})
    return values or None


async def delete_thread(conversation_id: Any) -> None:
    """删除某会话的图状态（测试与「重置演示数据」用）。"""
    saver = await get_checkpointer()
    if saver is None or not conversation_id:
        return
    try:
        await saver.adelete_thread(str(conversation_id))
    except Exception as exc:  # noqa: BLE001
        logger.debug("删除 checkpointer 线程失败：%s", exc)


def reset_checkpointer_cache() -> None:
    """仅供测试：丢掉单例（不关连接，避免在别的 loop 上 await）。"""
    global _saver, _cm, _lock
    _saver = None
    _cm = None
    _lock = None


__all__ = [
    "close_checkpointer",
    "delete_thread",
    "dsn",
    "get_checkpointer",
    "init_checkpointer",
    "read_thread_state",
    "reset_checkpointer_cache",
    "thread_config",
]
