import asyncio
import logging
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.agent.checkpointer import close_checkpointer, init_checkpointer
from app.api import (
    admin_agents,
    admin_kb,
    agent,
    agent_drug,
    agents,
    auth,
    cart,
    chat,
    conversations,
    handoff,
    memory,
    order,
    product,
    support,
    support_ws,
    upload,
)
from app.core.config import settings
from app.observability.tracing import get_trace_sink

logger = logging.getLogger(__name__)

# Windows 上必须用 SelectorEventLoop：psycopg 的异步连接不支持 ProactorEventLoop，
# 而 LangGraph checkpointer 走的就是 psycopg。策略必须在事件循环创建**之前**设置，
# 所以放在模块导入期（uvicorn 会先导入 app 再建 loop）。
if sys.platform == "win32":  # pragma: no cover - 平台相关
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@asynccontextmanager
async def lifespan(app: FastAPI):
    # checkpointer 的表由库自带 setup() 幂等创建（不写进 Alembic，避免版本漂移）。
    # 失败只记日志：没有持久化也要能对话。
    try:
        await init_checkpointer()
    except Exception:  # noqa: BLE001
        logger.exception("checkpointer 初始化失败，本次运行不持久化图状态")

    yield
    # 进程退出前把 Langfuse 缓冲区刷出去；未配置时是空操作
    get_trace_sink().flush()
    await close_checkpointer()


app = FastAPI(lifespan=lifespan)

# 配置 CORS（允许前端跨域请求）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite 的默认端口
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由，注意这里的前缀必须和前端匹配
app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])
app.include_router(product.router, prefix="/api/products", tags=["Products"])
app.include_router(cart.router, prefix="/api/cart", tags=["Cart"])
app.include_router(order.router, prefix="/api/orders", tags=["Orders"])
app.include_router(agent.router, prefix="/api/agent", tags=["Agent"])
app.include_router(agent_drug.router, prefix="/api/agent", tags=["Agent-Drug"])
app.include_router(upload.router, prefix="/api/upload", tags=["Upload"])  # 注册上传
app.include_router(admin_kb.router, prefix="/api/admin/kb", tags=["Admin-KB"])
app.include_router(admin_agents.router, prefix="/api/admin", tags=["Admin-Agents"])
app.include_router(agents.router, prefix="/api/agents", tags=["Agents"])
app.include_router(chat.router, prefix="/api/chat", tags=["Chat"])
app.include_router(conversations.router, prefix="/api/conversations", tags=["Conversations"])
app.include_router(memory.router, prefix="/api/me/memory", tags=["Memory"])
app.include_router(handoff.router, prefix="/api/handoff", tags=["Handoff"])
app.include_router(support.router, prefix="/api/support", tags=["Support"])
# WS 不走 /api 前缀：浏览器直连 /ws/support/{conversation_id}（Vite 已配代理）
app.include_router(support_ws.router, tags=["Support-WS"])

# 挂载静态文件目录，让浏览器可以直接访问 /static/xxx.jpg
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/health")
async def health():
    """健康检查：同时暴露依赖状态，缺失时服务仍可用（降级而非崩）。"""
    from app.agent.checkpointer import get_checkpointer
    from app.core.redis import redis_ping

    checkpointer = None
    if settings.checkpointer_enabled:
        try:
            checkpointer = await get_checkpointer()
        except Exception:  # noqa: BLE001
            checkpointer = None

    return {
        "status": "ok",
        "env": settings.app_env,
        "observability": "enabled" if settings.observability_enabled else "disabled",
        "llm": "configured" if settings.llm_configured else "missing",
        "embedding": "configured" if settings.embedding_configured else "missing",
        "redis": "ok" if await redis_ping() else "unavailable",
        "checkpointer": (
            "disabled" if not settings.checkpointer_enabled else ("ok" if checkpointer else "unavailable")
        ),
    }


def main():
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
