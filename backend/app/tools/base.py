"""工具（Function Calling）注册表。

**约定**：Agent 是配置，工具是代码。新增一个能力 = 在这里注册一个函数，
后台配置 Agent 时按名字引用即可，无需改动编排逻辑。

每个工具声明 ``required_roles``：工具层自己校验权限，不依赖上层「记得检查」。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable, Sequence


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

    async def __call__(self, **kwargs: Any) -> Any:
        return await self.fn(**kwargs)


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
