import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    # 仅供类型检查；运行时由 SQLAlchemy 按字符串解析，避免循环 import
    from app.models.cart import CartItem
    from app.models.order import Order


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    DOCTOR = "doctor"  # 医生
    PATIENT = "patient"  # 患者
    # 客服坐席（M1 新增）：可接管会话、查订单售后知识库，但进不了知识库后台。
    # 注意 PG 的 userrole 枚举存的是成员名（'ADMIN'/'SUPPORT'），不是 value，
    # 迁移里必须 ALTER TYPE userrole ADD VALUE 'SUPPORT'。
    SUPPORT = "support"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.PATIENT)

    # 关联购物车和订单
    cart_items: Mapped[list["CartItem"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    orders: Mapped[list["Order"]] = relationship(back_populates="user")
