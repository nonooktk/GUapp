"""P1・P2-a・P2-b・P2-d のテーブル（設計仕様書 5.2: DS-TBL-05〜09・12〜16・21・23 の 12 表、
P2 追補a 5.1: DS-TBL-22 contents を加えた 13 表、
P2 追補b 5.1: DS-TBL-01・03・04・10・19・20・26・27 の 8 表を加えた 21 表、
P2 追補d 5 章: DS-TBL-24・25 chat_sessions／chat_messages を加えた 23 表。P2-c は表を増やさない）。

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
from app.models.chat import ChatMessage, ChatRole, ChatSession
from app.models.content import Content, ContentKind
from app.models.member import EmailToken, EmailTokenPurpose, Member, MemberGender
from app.models.order import (
    Order,
    OrderItem,
    OrderStatus,
    Payment,
    PaymentProvider,
    PaymentResult,
    ReceiveMethod,
)
from app.models.restock import RestockNotification
from app.models.review import Review, ReviewFit
from app.models.session import AuthSession, LoginAttempt, SubjectType
from app.models.staff import Staff
from app.models.store import Store
from app.models.system import ActorType, AuditLog, SystemSetting

__all__ = [
    "ActorType",
    "AuditLog",
    "AuthSession",
    "Base",
    "Cart",
    "CartItem",
    "CartStatus",
    "Category",
    "ChatMessage",
    "ChatRole",
    "ChatSession",
    "Content",
    "ContentKind",
    "EmailToken",
    "EmailTokenPurpose",
    "Gender",
    "LoginAttempt",
    "Member",
    "MemberGender",
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
    "RestockNotification",
    "Review",
    "ReviewFit",
    "Staff",
    "Store",
    "SubjectType",
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

# P2-b で追加した 8 表（設計仕様書 P2 追補b 5.1）
P2B_TABLES: frozenset[str] = frozenset(
    {
        "members",
        "sessions",
        "staff",
        "stores",
        "reviews",
        "restock_notifications",
        "login_attempts",
        "email_tokens",
    }
)

# P2-d で追加した表（設計仕様書 P2 追補d 5 章 DS-TBL-24・25）
P2D_TABLES: frozenset[str] = frozenset({"chat_sessions", "chat_messages"})

# 全表（P1 + P2-a + P2-b + P2-d = 23 表）
ALL_TABLES: frozenset[str] = P1_TABLES | P2A_TABLES | P2B_TABLES | P2D_TABLES
