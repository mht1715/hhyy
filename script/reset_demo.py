"""一键重置演示数据（M4-11，PRD §11.2 演示脚本的前置）。

做的事只有四件，**不动**知识库 / 账号 / Agent 配置——那些是「作品」的一部分，
每场演示都重新灌一遍既慢又容易在某些环节失败：

1. 清会话、消息、工单、记忆、检查点（含 LangGraph 的三张表）；
2. 删掉 Milvus 的 ``hhyy_memory``（记忆向量），下次写入会按 schema 自动重建；
3. 清检索日志（否则「零召回榜」被压测/评估流量污染）；
4. 打印重置后的计数，方便确认「真的空了」。

```powershell
$env:PYTHONPATH="backend"; .venv/Scripts/python -X utf8 script/reset_demo.py
# 连评估结果一起清（演示前想要一块干净看板时用）
.venv/Scripts/python -X utf8 script/reset_demo.py --with-eval
```
"""

from __future__ import annotations

import argparse
import asyncio

TABLES = (
    "messages",
    "handoff_tickets",
    "conversations",
    "user_memories",
    "user_profiles",
    "checkpoints",
    "checkpoint_blobs",
    "checkpoint_writes",
    "kb_search_logs",
)

COUNTS = (
    ("conversations", "conversations"),
    ("messages", "messages"),
    ("handoff_tickets", "handoff_tickets"),
    ("user_memories", "user_memories"),
    ("user_profiles", "user_profiles"),
)


async def reset(*, with_eval: bool) -> None:
    from sqlalchemy import text

    from app.core.database import engine

    tables = list(TABLES)
    if with_eval:
        tables.append("eval_runs")
    # RESTART IDENTITY 对这些表没有自增序列，但保留着无害；CASCADE 处理外键顺序
    statement = "TRUNCATE " + ", ".join(tables) + " RESTART IDENTITY CASCADE"
    async with engine.begin() as conn:
        await conn.execute(text(statement))
    print(f"已清空 {len(tables)} 张表")

    async with engine.connect() as conn:
        for label, table in COUNTS:
            value = (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
            print(f"  {label:<16}{value}")


def reset_vectors() -> None:
    try:
        from pymilvus import MilvusClient

        from app.core.config import settings

        client = MilvusClient(uri=settings.milvus_uri, token=settings.milvus_token)
        if client.has_collection("hhyy_memory"):
            client.drop_collection("hhyy_memory")
            print("已删除 Milvus collection hhyy_memory（下次写入自动重建）")
        else:
            print("hhyy_memory 不存在，跳过")
    except Exception as exc:  # noqa: BLE001 —— 向量库没起也要能把业务库清干净
        print(f"! 清理向量库失败（不影响业务库）：{exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description="重置演示数据")
    parser.add_argument("--with-eval", action="store_true", help="连 eval_runs 一起清")
    args = parser.parse_args()

    asyncio.run(reset(with_eval=args.with_eval))
    reset_vectors()
    print("\n完成。知识库、账号、Agent 配置均未改动。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
