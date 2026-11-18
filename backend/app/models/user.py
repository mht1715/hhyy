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


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.PATIENT)

    # 关联购物车和订单
    cart_items: Mapped[list["CartItem"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    orders: Mapped[list["Order"]] = relationship(back_populates="user")
