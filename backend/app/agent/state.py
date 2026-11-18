"""图状态（M2-03）。

``AgentState`` 是 LangGraph 的 state：只放**可序列化语义**的字段（消息、mentions、
引用、贡献者），不放 AsyncSession / 请求对象——M3 接 ``AsyncPostgresSaver`` 做
会话恢复时，这些字段要能落盘。运行时依赖（db、用户、sink）走 ``config``。
"""

from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    # 输入
    message: str
    mentions: list[dict[str, Any]]
    role: str
    primary_code: str
    # 路由结果
    route: dict[str, Any]
    # 子 Agent 产出（drafts 是「还没生成文字」的检索结果，results 是「已生成」的）
    drafts: list[Any]
    results: list[Any]
    # 汇总
    citations: list[dict[str, Any]]
    contributors: list[dict[str, Any]]
    messages: list[Any]
    # 治理
    guardrail: dict[str, Any]
    handoff: dict[str, Any] | None
    suggested_actions: list[dict[str, Any]]
