import uuid
from sqlalchemy import String, Float, ForeignKey, Enum, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
import enum

class OrderStatus(str, enum.Enum):
    PENDING = "pending"    # 待支付
    PAID = "paid"          # 已支付
    SHIPPED = "shipped"    # 已发货
    CANCELLED = "cancelled"# 已取消

class Order(Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    total_amount: Mapped[float] = mapped_column(Float)
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus), default=OrderStatus.PENDING)

    user: Mapped["User"] = relationship(back_populates="orders")
    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")

class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"))
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[float] = mapped_column(Float) # 记录购买时的单价

    order: Mapped["Order"] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship()