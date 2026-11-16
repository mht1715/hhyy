import asyncio
import sys

import redis.asyncio as aioredis
from app.core.config import settings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


async def test_postgres():
    print("[INFO] 正在测试 PostgreSQL 连接...")
    try:
        # 创建异步引擎
        engine = create_async_engine(settings.database_url, echo=False)

        # 尝试连接并执行一条简单 SQL
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT version();"))
            version = result.scalar()
            print("[PASS] PostgreSQL 连接成功！")
            print(f"       版本信息: {version.split(',')[0]}")

            # 额外测试：验证 pgvector 扩展是否安装
            try:
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
                await conn.commit()
                print("[PASS] pgvector 扩展已启用！")
            except Exception as e:
                print(f"[WARN] pgvector 启用失败: {e}")

        await engine.dispose()
    except Exception as e:
        print(f"[FAIL] PostgreSQL 连接失败: {e}")
        sys.exit(1)


async def test_redis():
    print("\n[INFO] 正在测试 Redis 连接...")
    try:
        # 连接 Redis
        r = aioredis.Redis(
            host=settings.redis_host, port=settings.redis_port, decode_responses=True
        )

        # 测试 ping
        pong = await r.ping()
        if pong:
            print("[PASS] Redis 连接成功！")

        # 测试读写
        await r.set("agent_test_key", "hello_redis")
        val = await r.get("agent_test_key")
        print(f"[PASS] Redis 读写测试成功，读取到的值: {val}")

        # 清理测试数据
        await r.delete("agent_test_key")
        await r.aclose()
    except Exception as e:
        print(f"[FAIL] Redis 连接失败: {e}")
        sys.exit(1)


async def main():
    print("=== 开始基础设施连接测试 ===\n")
    await test_postgres()
    await test_redis()
    print("\n[DONE] 所有基础设施测试通过！")


if __name__ == "__main__":
    asyncio.run(main())
