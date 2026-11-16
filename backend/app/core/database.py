from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.core.config import settings

# 创建异步引擎
engine = create_async_engine(
    settings.database_url,
    echo=True,  # 开发阶段可以改为 True 查看 SQL 日志
    pool_size=10,
    max_overflow=20
)

# 创建异步 Session 工厂
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)


# 依赖注入用的获取 Session 函数
async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
