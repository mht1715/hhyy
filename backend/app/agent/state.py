"""图状态（M2-03 / M3-01）。

``AgentState`` 是 LangGraph 的 state：只放**可序列化**的字段（消息、mentions、
引用、贡献者），不放 AsyncSession / 请求对象。运行时依赖（db、用户、sink、
checkpointer）走 ``TurnContext``，所以 M3 接 ``AsyncPostgresSaver`` 时节点签名没变。

两条口径：

- ``messages`` 是**对话投影**（user/assistant 的纯 dict），用 :func:`keep_last` 截断到
  最近 40 条。为什么不无限追加：checkpointer 每轮都把状态写一遍，不截断的话一个
  长会话的 checkpoint 会线性膨胀，写库时间和存储都会失控。
- 刻意**不用** LangChain 的 ``add_messages``：那会把 dict 转成 ``HumanMessage``/``AIMessage``，
  序列化时依赖 LangChain 的 msgpack 注册表；我们用纯 dict，checkpointer 直接按 JSON
  存，重启、换版本都不会因为「未注册类型」读不出来。
"""

from __future__ import annotations

from typing import Annotated, Any, Callable, TypedDict

MAX_STATE_MESSAGES = 40


def keep_last(limit: int = MAX_STATE_MESSAGES) -> Callable[[Any, Any], list[Any]]:
    """返回一个只保留最后 ``limit`` 条的 reducer。"""

    def merge(left: Any, right: Any) -> list[Any]:
        merged = list(left or []) + list(right or [])
        return merged[-limit:]

    return merge


class AgentState(TypedDict, total=False):
    # 输入
    message: str
    mentions: list[dict[str, Any]]
    role: str
    primary_code: str
    # 路由结果
    route: dict[str, Any]
    # 子 Agent 的**摘要**产出（不放大对象：drafts/results 留在 TurnContext 上，
    # 进 state 的只有给下一轮/给排障看的最小信息）
    agents: list[dict[str, Any]]
    # 汇总
    citations: list[dict[str, Any]]
    contributors: list[dict[str, Any]]
    messages: Annotated[list[Any], keep_last()]
    # 治理
    guardrail: dict[str, Any]
    handoff: dict[str, Any] | None
    suggested_actions: list[dict[str, Any]]


__all__ = ["AgentState", "MAX_STATE_MESSAGES", "keep_last"]
