"""ORM 模型聚合导入。

⚠️ 这里的 import 是**副作用**：只有被 import 过，``Base.metadata`` 才知道这些表存在，
Alembic 的 autogenerate 才能看到完整结构。

因此显式声明 ``__all__``——既表达「这是对外导出的符号」，也避免被 lint 当作
未使用导入删掉（删了不会报错，只会静默生成空迁移，非常难查）。
"""

from app.models.base import Base
from app.models.cart import CartItem
from app.models.kb import (
    AuditLog,
    ChunkStrategy,
    DocumentSource,
    DocumentStatus,
    KbChunk,
    KbDocument,
    KbRolePermission,
    KbSearchLog,
    KbStatus,
    KbVisibility,
    KnowledgeBase,
)
from app.models.order import Order, OrderItem
from app.models.product import Product
from app.models.user import User, UserRole

__all__ = [
    "AuditLog",
    "Base",
    "CartItem",
    "ChunkStrategy",
    "DocumentSource",
    "DocumentStatus",
    "KbChunk",
    "KbDocument",
    "KbRolePermission",
    "KbSearchLog",
    "KbStatus",
    "KbVisibility",
    "KnowledgeBase",
    "Order",
    "OrderItem",
    "Product",
    "User",
    "UserRole",
]
