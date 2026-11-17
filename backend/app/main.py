import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.api import auth, product, agent, upload, agent_drug

app = FastAPI()

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
app.include_router(agent.router, prefix="/api/agent", tags=["Agent"])
app.include_router(agent_drug.router, prefix="/api/agent", tags=["Agent-Drug"])
app.include_router(upload.router, prefix="/api/upload", tags=["Upload"])  # 注册上传

# 挂载静态文件目录，让浏览器可以直接访问 /static/xxx.jpg
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/health")
def health():
    return {"status": "ok"}


def main():
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
