"""P1 のテーブル（設計仕様書 5.2: DS-TBL-05〜09・12〜16・21・23 の 12 表）。

設計書本文は「13 表」と書くが、列挙された DS-TBL を数えると 12。
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

# P1 で作る 12 表の名前（テストとシナモロールの Alembic 確認用）
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
