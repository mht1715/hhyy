"""工具层：Function Calling 注册表（M2 注册具体工具）。

导入本包即完成内置工具注册——``app/tools/__init__.py`` 里的 ``from app.tools import builtin``
是**副作用导入**，删掉它会让后台配置 Agent 时报「未知工具」。
"""

from app.tools import builtin  # noqa: F401 —— 副作用：注册 6 个内置工具
from app.tools.base import (
    Tool,
    ToolContext,
    ToolError,
    ToolResult,
    ToolSpec,
    build_function_schemas,
    call_tool,
    ensure_tool_allowed,
    get_tool,
    list_tools,
    register_tool,
)

__all__ = [
    "Tool",
    "ToolContext",
    "ToolError",
    "ToolResult",
    "ToolSpec",
    "build_function_schemas",
    "call_tool",
    "ensure_tool_allowed",
    "get_tool",
    "list_tools",
    "register_tool",
]
