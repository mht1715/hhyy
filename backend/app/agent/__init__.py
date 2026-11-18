"""Agent 编排层（M2 实现）。

规划中的模块：

- ``state.py``   AgentState：messages / mentions / citations / contributors
- ``registry.py`` Agent 定义读取与校验（DB 配置）
- ``router.py``  显式 mentions 路由 / supervisor 路由
- ``runtime.py``  LangGraph 图构建 + checkpointer
- ``subagent.py`` 单个子 Agent 的执行单元
- ``sse.py``     SSE 事件编码
"""
