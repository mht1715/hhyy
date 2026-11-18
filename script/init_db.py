"""数据库初始化：统一走 Alembic 迁移（**不再使用 create_all**）。

用法（在项目根目录或 backend/ 下均可）::

    python script/init_db.py            # 建表 / 升级到最新
    python script/init_db.py --stamp    # 只把已有库标记为最新，不执行建表

首次给「已经用 create_all 建过表」的老库启用 Alembic 时，脚本会自动检测到
「有业务表但没有 alembic_version」，先 stamp head 再 upgrade，避免重复建表报错。
"""

import asyncio
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import inspect  # noqa: E402

from app.core.database import engine  # noqa: E402


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    # script_location 用绝对路径，避免受当前工作目录影响
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return cfg


def _table_names_of(sync_conn) -> set[str]:
    return set(inspect(sync_conn).get_table_names())


async def _table_names() -> set[str]:
    try:
        async with engine.connect() as conn:
            return await conn.run_sync(_table_names_of)
    finally:
        await engine.dispose()


def main() -> None:
    cfg = _alembic_config()

    if "--stamp" in sys.argv:
        print("[init_db] stamp head（仅标记版本，不改结构）")
        command.stamp(cfg, "head")
        return

    tables = asyncio.run(_table_names())

    if "alembic_version" not in tables and "users" in tables:
        print("[init_db] 检测到已有业务表但没有 alembic_version → 先 stamp head")
        command.stamp(cfg, "head")

    print("[init_db] 执行 alembic upgrade head ...")
    command.upgrade(cfg, "head")
    print("[init_db] 数据库已就绪。")


if __name__ == "__main__":
    main()
