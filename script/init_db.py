import asyncio
from sqlalchemy import text
from app.core.database import engine
from app.models import Base


async def init_models():
    print("正在创建数据库表...")
    async with engine.begin() as conn:
        # 确保 pgvector 扩展存在
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        # 创建所有表
        await conn.run_sync(Base.metadata.create_all)
    print("数据库表创建完成。")


if __name__ == "__main__":
    asyncio.run(init_models())
