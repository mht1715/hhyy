"""baseline：项目既有的 5 张表（users / products / cart_items / orders / order_items）

本迁移是「把 create_all 时代已经存在的结构固化下来」，字段与 app/models 完全对齐。

- 新库：``alembic upgrade head`` 直接建出整套表
- 老库（已由 create_all 建过表）：由 script/init_db.py 自动 stamp head，不重复建表

Revision ID: 0001_baseline
Revises:
Create Date: 2026-11-18

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

USER_ROLE = sa.Enum("ADMIN", "DOCTOR", "PATIENT", name="userrole")


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    # products.embedding 依赖 pgvector；pgvector 官方镜像里该扩展是 trusted，
    # 普通 owner 也能创建。
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(length=50), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("role", USER_ROLE, nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
    )
    # unique=True + index=True 在 SQLAlchemy 中生成唯一索引（而非独立约束）
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    op.create_table(
        "products",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("generic_name", sa.String(length=100), nullable=False),
        sa.Column("image_url", sa.String(length=255), nullable=True),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("original_price", sa.Float(), nullable=False),
        sa.Column("stock", sa.Integer(), nullable=False),
        sa.Column("sales", sa.Integer(), nullable=False),
        sa.Column("spec", sa.String(length=50), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("dosage_form", sa.String(length=50), nullable=False),
        sa.Column("shelf_life", sa.String(length=50), nullable=False),
        sa.Column("indications", sa.Text(), nullable=True),
        sa.Column("contraindications", sa.Text(), nullable=True),
        sa.Column("precautions", sa.Text(), nullable=True),
        sa.Column("adverse_reactions", sa.Text(), nullable=True),
        sa.Column("approval_number", sa.String(length=50), nullable=False),
        sa.Column("manufacturer", sa.String(length=100), nullable=False),
        sa.Column("embedding", Vector(1024), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_products_name", "products", ["name"])

    op.create_table(
        "cart_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("total_amount", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "order_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Float(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("order_items")
    op.drop_table("orders")
    op.drop_table("cart_items")
    op.drop_index("ix_products_name", table_name="products")
    op.drop_table("products")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
    USER_ROLE.drop(op.get_bind(), checkfirst=True)
