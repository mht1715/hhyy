import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.core.security import get_password_hash  # noqa: E402
from app.models.user import User, UserRole  # noqa: E402


async def seed():
    async with AsyncSessionLocal() as db:
        users = [
            {"username": "admin", "password": "123456", "role": UserRole.ADMIN},
            {"username": "doctor", "password": "123456", "role": UserRole.DOCTOR},
            {"username": "patient", "password": "123456", "role": UserRole.PATIENT},
            # M1 新增：客服坐席，用来演示「同一问题不同角色看到的答案不同」
            {"username": "support", "password": "123456", "role": UserRole.SUPPORT},
        ]
        for u in users:
            res = await db.execute(select(User).where(User.username == u["username"]))
            if not res.scalar_one_or_none():
                db.add(User(username=u["username"], hashed_password=get_password_hash(u["password"]), role=u["role"]))
        await db.commit()
        print("预置快捷账号完成")


if __name__ == "__main__":
    asyncio.run(seed())
