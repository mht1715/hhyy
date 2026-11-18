from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import admin_kb, agent, agent_drug, auth, cart, order, product, upload
from app.core.config import settings
from app.observability.tracing import get_trace_sink


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # 进程退出前把 Langfuse 缓冲区刷出去；未配置时是空操作
    get_trace_sink().flush()


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

# 挂载静态文件目录，让浏览器可以直接访问 /static/xxx.jpg
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/health")
def health():
    """健康检查：同时暴露依赖配置状态，缺凭据时服务仍可用（降级而非崩）。"""
    return {
        "status": "ok",
        "env": settings.app_env,
        "observability": "enabled" if settings.observability_enabled else "disabled",
        "llm": "configured" if settings.llm_configured else "missing",
        "embedding": "configured" if settings.embedding_configured else "missing",
    }


def main():
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
