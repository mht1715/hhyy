"""工具（Function Calling）注册表。

**约定**：Agent 是配置，工具是代码。新增一个能力 = 在这里注册一个函数，
后台配置 Agent 时按名字引用即可，无需改动编排逻辑。

每个工具声明 ``required_roles``：工具层自己校验权限，不依赖上层「记得检查」。
工具实现统一签名 ``async def fn(ctx: ToolContext, **kwargs) -> dict``，
返回体里若带 ``_summary``，会被 :func:`call_tool` 提出来作为给用户看的摘要
（``tool`` 事件只发摘要，不发正文）。
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable, Sequence

# 工具名 → 给人看的能力标签（`@` 候选面板、广场卡片、交接摘要都用它）
TOOL_LABELS: dict[str, str] = {
    "kb_search": "知识库检索",
    "policy_search": "售后政策",
    "product_lookup": "药品查询",
    "order_lookup": "订单查询",
    "remember": "记住偏好",
    "escalate_human": "转人工",
}


def tool_label(name: str) -> str:
    return TOOL_LABELS.get(name, name)


@dataclass(slots=True)
class ToolContext:
    """一次工具调用的上下文。

    ``db`` 用 ``Any`` 而不是 ``AsyncSession``：工具层不该把 SQLAlchemy 的类型
    泄漏到编排层，测试里也可以传任何带 ``execute`` 的替身。
    """

    db: Any
    role: str
    user_id: Any = None
    # 当前 Agent 绑定的知识库 code，工具只能在这些库里检索（再叠加 ACL）
    kb_codes: tuple[str, ...] = ()
    conversation_id: Any = None
    # 可注入的检索服务替身（测试用）；为空则用全局单例
    retrieval: Any = None


class ToolError(RuntimeError):
    """工具的可预期失败（无权限、找不到、缺参数）。

    与「代码炸了」区分开：这类错误要原样告诉模型，让它换个说法或转人工。
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """工具的静态声明。"""

    name: str
    description: str
    args_schema: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})
    required_roles: tuple[str, ...] = ()
    timeout_seconds: float = 8.0

    def allowed_for(self, role: str) -> bool:
        return not self.required_roles or role in self.required_roles

    def as_function_schema(self) -> dict[str, Any]:
        """转成 OpenAI Function Calling 的 schema。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.args_schema,
            },
        }


@dataclass(slots=True)
class Tool:
    """已注册的工具：声明 + 可调用实现。"""

    spec: ToolSpec
    fn: Callable[..., Awaitable[Any]]

    async def __call__(self, ctx: ToolContext, **kwargs: Any) -> Any:
        return await self.fn(ctx, **kwargs)


_TOOL_REGISTRY: dict[str, Tool] = {}


def register_tool(spec: ToolSpec) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """装饰器：把一个 async 函数注册为工具。"""

    def decorator(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        if spec.name in _TOOL_REGISTRY:
            raise ValueError(f"工具 {spec.name} 已注册，请勿重复注册")
        _TOOL_REGISTRY[spec.name] = Tool(spec=spec, fn=fn)
        return fn

    return decorator


def get_tool(name: str) -> Tool:
    try:
        return _TOOL_REGISTRY[name]
    except KeyError as exc:
        raise KeyError(f"未知工具：{name}") from exc


def list_tools(required_roles: Sequence[str] | None = None) -> list[Tool]:
    """列出工具；传角色时只返回该角色可用的。"""
    tools = list(_TOOL_REGISTRY.values())
    if required_roles is None:
        return tools
    return [tool for tool in tools if any(tool.spec.allowed_for(role) for role in required_roles)]


def build_function_schemas(names: Iterable[str]) -> list[dict[str, Any]]:
    """按名字列表生成 LLM 可用的 function schema（顺序稳定）。"""
    return [get_tool(name).spec.as_function_schema() for name in names]


def ensure_tool_allowed(name: str, role: str) -> None:
    """工具级权限闸门，越权抛 PermissionError。"""
    tool = get_tool(name)
    if not tool.spec.allowed_for(role):
        raise PermissionError(f"角色 {role} 无权调用工具 {name}")


@dataclass(slots=True)
class ToolResult:
    """一次工具调用的结果（永远不抛给编排层）。"""

    name: str
    ok: bool
    data: Any = None
    summary: str = ""
    error: str | None = None
    code: str | None = None
    elapsed_ms: int = 0


async def call_tool(name: str, ctx: ToolContext, **kwargs: Any) -> ToolResult:
    """统一入口：查表 → 权限 → 超时 → 异常收敛成 ``ToolResult``。

    任何失败都变成 ``ok=False`` 而不是异常向上冒泡——一个工具挂掉不该让整条
    回答链路 500，模型可以拿 ``error`` 去决定「换个工具」还是「转人工」。
    唯一的例外是 ``asyncio.CancelledError``（外部取消要穿透）。
    """
    started = time.perf_counter()

    def elapsed() -> int:
        return int((time.perf_counter() - started) * 1000)

    try:
        tool = get_tool(name)
    except KeyError:
        return ToolResult(name=name, ok=False, error=f"未知工具：{name}", code="UNKNOWN_TOOL")

    if not tool.spec.allowed_for(ctx.role):
        return ToolResult(
            name=name,
            ok=False,
            error=f"角色 {ctx.role} 无权调用 {name}",
            code="FORBIDDEN",
            elapsed_ms=elapsed(),
        )

    try:
        raw = await asyncio.wait_for(tool.fn(ctx, **kwargs), timeout=tool.spec.timeout_seconds)
    except asyncio.TimeoutError:
        return ToolResult(
            name=name,
            ok=False,
            error=f"{name} 超时（{tool.spec.timeout_seconds:g}s）",
            code="TIMEOUT",
            elapsed_ms=elapsed(),
        )
    except ToolError as exc:
        return ToolResult(name=name, ok=False, error=exc.message, code=exc.code, elapsed_ms=elapsed())
    except Exception as exc:  # noqa: BLE001 —— 工具故障不许影响主链路
        return ToolResult(
            name=name, ok=False, error=f"{type(exc).__name__}: {exc}", code="ERROR", elapsed_ms=elapsed()
        )

    data = raw if isinstance(raw, dict) else {"result": raw}
    summary = str(data.pop("_summary", "") or "")
    return ToolResult(name=name, ok=True, data=data, summary=summary, elapsed_ms=elapsed())
