from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

# 创建异步引擎
# echo 只在 LOG_LEVEL=DEBUG 时打开：默认开着会把每次检索、每批 embedding 的 SQL 全打出来，
# 既拖慢速度，又让真正的告警淹没在日志里。
engine = create_async_engine(
    settings.database_url,
    echo=settings.log_level.upper() == "DEBUG",
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
