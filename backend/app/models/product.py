import uuid
from sqlalchemy import String, Float, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector
from app.models.base import Base
from typing import Optional


class Product(Base):
    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), index=True)
    generic_name: Mapped[str] = mapped_column(String(100))
    image_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    price: Mapped[float] = mapped_column(Float)
    original_price: Mapped[float] = mapped_column(Float)
    stock: Mapped[int] = mapped_column(Integer, default=0)
    sales: Mapped[int] = mapped_column(Integer, default=20000)
    spec: Mapped[str] = mapped_column(String(50), default="45ml")
    category: Mapped[str] = mapped_column(String(50))
    dosage_form: Mapped[str] = mapped_column(String(50))
    shelf_life: Mapped[str] = mapped_column(String(50), default="36个月")

    # 以下是说明书字段，全部允许为空
    indications: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    contraindications: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    precautions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    adverse_reactions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    approval_number: Mapped[str] = mapped_column(String(50))
    manufacturer: Mapped[str] = mapped_column(String(100))
    embedding: Mapped[Optional[list[float]]] = mapped_column(Vector(1024), nullable=True)
