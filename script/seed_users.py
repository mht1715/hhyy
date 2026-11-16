import asyncio
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.user import User, UserRole
from app.core.security import get_password_hash


async def seed():
    async with AsyncSessionLocal() as db:
        users = [
            {"username": "admin", "password": "123456", "role": UserRole.ADMIN},
            {"username": "doctor", "password": "123456", "role": UserRole.DOCTOR},
            {"username": "patient", "password": "123456", "role": UserRole.PATIENT},
        ]
        for u in users:
            res = await db.execute(select(User).where(User.username == u["username"]))
            if not res.scalar_one_or_none():
                db.add(User(username=u["username"], hashed_password=get_password_hash(u["password"]), role=u["role"]))
        await db.commit()
        print("预置快捷账号完成")


if __name__ == "__main__":
    asyncio.run(seed())
