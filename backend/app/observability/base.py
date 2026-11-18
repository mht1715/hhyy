"""可观测契约。

设计取舍：用 **上下文管理器**（``with sink.trace(...)``）而不是 ``start_trace`` /
``end_trace`` 成对调用。原因是 Langfuse 5.x 基于 OpenTelemetry，span 的进入/退出
必须严格配对；成对 API 一旦某条异常分支漏了 ``end_trace``，trace 就会悬挂。
``with`` 交给解释器保证配对。

Trace 结构（对应 PRD §F7.2）::

    trace: chat.turn
    ├── span: router.decide
    ├── span: retrieval
    ├── span: subagent.<code>
    │    ├── generation: llm
    │    └── span: tool.<name>
    └── span: guardrail.check
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

ObservationType = Literal[
    "span",
    "generation",
    "retriever",
    "tool",
    "chain",
    "agent",
    "guardrail",
]


@dataclass(slots=True)
class TraceContext:
    """一次 trace 的句柄。``raw`` 承载实现方的原生对象。"""

    trace_id: str
    name: str
    user_id: str | None = None
    session_id: str | None = None
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    raw: Any = None


@runtime_checkable
class TraceSink(Protocol):
    """追踪出口。实现方必须保证「上报失败不影响主链路」。"""

    def trace(
        self,
        name: str,
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AbstractContextManager[TraceContext]: ...

    def span(
        self,
        ctx: TraceContext,
        name: str,
        *,
        as_type: ObservationType = "span",
        input: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> AbstractContextManager[TraceContext]: ...

    def score(
        self,
        ctx: TraceContext,
        name: str,
        value: float | str,
        *,
        comment: str | None = None,
    ) -> None: ...

    def callbacks(self) -> list[Any]:
        """给 LangChain 用的 callback 列表；未启用时返回空列表。"""
        ...

    def flush(self) -> None:
        """进程退出前强制上报（失败静默）。"""
        ...
