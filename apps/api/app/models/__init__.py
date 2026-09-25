"""P1・P2-a のテーブル（設計仕様書 5.2: DS-TBL-05〜09・12〜16・21・23 の 12 表、
P2 追補a 5.1: DS-TBL-22 contents を加えた 13 表）。

設計書本文は「13 表」と書くが、P1 時点で列挙された DS-TBL を数えると 12
（P2-a の DS-TBL-22 追加で実際に 13 になった）。
Alembic は `Base.metadata` を参照する。
"""

from app.models.base import Base
from app.models.cart import Cart, CartItem, CartStatus
from app.models.catalog import (
    Category,
    Gender,
    Product,
    ProductCategory,
    ProductImage,
    Variant,
)
from app.models.content import Content, ContentKind
from app.models.order import (
    Order,
    OrderItem,
    OrderStatus,
    Payment,
    PaymentProvider,
    PaymentResult,
    ReceiveMethod,
)
from app.models.system import ActorType, AuditLog, SystemSetting

__all__ = [
    "ActorType",
    "AuditLog",
    "Base",
    "Cart",
    "CartItem",
    "CartStatus",
    "Category",
    "Content",
    "ContentKind",
    "Gender",
    "Order",
    "OrderItem",
    "OrderStatus",
    "Payment",
    "PaymentProvider",
    "PaymentResult",
    "Product",
    "ProductCategory",
    "ProductImage",
    "ReceiveMethod",
    "SystemSetting",
    "Variant",
]

# P1 で作った 12 表の名前（テストと Alembic 確認用。変更しない）
P1_TABLES: frozenset[str] = frozenset(
    {
        "categories",
        "products",
        "product_categories",
        "product_images",
        "variants",
        "carts",
        "cart_items",
        "orders",
        "order_items",
        "payments",
        "system_settings",
        "audit_logs",
    }
)

# P2-a で追加した表（設計仕様書 P2 追補a 5.1 DS-TBL-22）
P2A_TABLES: frozenset[str] = frozenset({"contents"})

# 全表（P1 + P2-a）
ALL_TABLES: frozenset[str] = P1_TABLES | P2A_TABLES
