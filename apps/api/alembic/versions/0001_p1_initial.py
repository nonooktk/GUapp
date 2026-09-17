"""P1 初回マイグレーション: 12 表（設計仕様書 5.2 DS-TBL-05〜09・12〜16・21・23）。

`alembic revision --autogenerate` の生成物を目視点検し、以下を確認済み:
UNIQUE（slug / sku / anonymous_token / order_number / idempotency_key / stripe_session_id /
system_settings.key / 複合 (product_id, category_id)・(cart_id, variant_id)）、
CHECK（price_incl_tax >= 0 / stock >= 0 / quantity > 0）、索引、FK の ondelete、
utf8mb4 / utf8mb4_0900_ai_ci / InnoDB。手で補った点は downgrade() の docstring を参照。

ロールバック: `alembic downgrade base`（downgrade() が FK 依存の逆順で全表を drop する）。

Revision ID: 6659ce6c5164
Revises: -
Create Date: 2026-09-18 01:10:14 (JST)
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# リビジョン識別子（Alembic が使う）
revision: str = "6659ce6c5164"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """スキーマを進める。"""
    op.create_table(
        "audit_logs",
        sa.Column(
            "actor_type",
            sa.Enum("member", "staff", "system", name="actor_type", native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column("actor_id", sa.BigInteger(), nullable=True),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("target_type", sa.String(length=50), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(op.f("ix_audit_logs_at"), "audit_logs", ["at"], unique=False)
    op.create_table(
        "carts",
        sa.Column("member_id", sa.BigInteger(), nullable=True),
        sa.Column("anonymous_token", sa.String(length=64), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "active", "ordered", "merged", name="cart_status", native_enum=False, length=20
            ),
            nullable=False,
        ),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_carts")),
        sa.UniqueConstraint("anonymous_token", name=op.f("uq_carts_anonymous_token")),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(op.f("ix_carts_member_id"), "carts", ["member_id"], unique=False)
    op.create_table(
        "categories",
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "gender",
            sa.Enum(
                "women",
                "men",
                "kids_teen",
                "all",
                name="category_gender",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["categories.id"],
            name=op.f("fk_categories_parent_id_categories"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categories")),
        sa.UniqueConstraint("slug", name=op.f("uq_categories_slug")),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(op.f("ix_categories_parent_id"), "categories", ["parent_id"], unique=False)
    op.create_table(
        "products",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("material", sa.String(length=500), nullable=False),
        sa.Column("price_incl_tax", sa.Integer(), nullable=False),
        sa.Column("published", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("price_incl_tax >= 0", name=op.f("ck_products_price_non_negative")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_products")),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(op.f("ix_products_published"), "products", ["published"], unique=False)
    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(length=50), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_system_settings")),
        sa.UniqueConstraint("key", name=op.f("uq_system_settings_key")),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_table(
        "orders",
        sa.Column("order_number", sa.String(length=20), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("member_id", sa.BigInteger(), nullable=True),
        sa.Column("guest_email", sa.String(length=254), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending_payment",
                "accepted",
                "preparing",
                "shipped",
                "delivered",
                "pickup_expired",
                "cancelled",
                "payment_failed",
                name="order_status",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column(
            "receive_method",
            sa.Enum("delivery", "store", name="receive_method", native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column("store_id", sa.BigInteger(), nullable=True),
        sa.Column("pickup_code", sa.String(length=20), nullable=True),
        sa.Column("tracking_number", sa.String(length=50), nullable=True),
        sa.Column("subtotal", sa.Integer(), nullable=False),
        sa.Column("shipping_fee", sa.Integer(), nullable=False),
        sa.Column("discount", sa.Integer(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("tax_rate_at_order", sa.String(length=10), nullable=False),
        sa.Column("ship_name", sa.String(length=50), nullable=False),
        sa.Column("ship_postal_code", sa.String(length=7), nullable=False),
        sa.Column("ship_address", sa.String(length=200), nullable=False),
        sa.Column("ship_phone", sa.String(length=11), nullable=False),
        sa.Column("cart_id", sa.BigInteger(), nullable=False),
        sa.Column("stripe_session_id", sa.String(length=255), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["cart_id"], ["carts.id"], name=op.f("fk_orders_cart_id_carts"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orders")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_orders_idempotency_key")),
        sa.UniqueConstraint("order_number", name=op.f("uq_orders_order_number")),
        sa.UniqueConstraint("stripe_session_id", name=op.f("uq_orders_stripe_session_id")),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(op.f("ix_orders_cart_id"), "orders", ["cart_id"], unique=False)
    op.create_index(op.f("ix_orders_member_id"), "orders", ["member_id"], unique=False)
    op.create_index(op.f("ix_orders_status"), "orders", ["status"], unique=False)
    op.create_table(
        "product_categories",
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("category_id", sa.BigInteger(), nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_product_categories_category_id_categories"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_product_categories_product_id_products"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_categories")),
        sa.UniqueConstraint(
            "product_id", "category_id", name=op.f("uq_product_categories_product_id_category_id")
        ),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        op.f("ix_product_categories_category_id"),
        "product_categories",
        ["category_id"],
        unique=False,
    )
    op.create_table(
        "product_images",
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("path", sa.String(length=500), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_product_images_product_id_products"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_images")),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        op.f("ix_product_images_product_id"), "product_images", ["product_id"], unique=False
    )
    op.create_table(
        "variants",
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("color", sa.String(length=50), nullable=False),
        sa.Column("size", sa.String(length=20), nullable=False),
        sa.Column("sku", sa.String(length=50), nullable=False),
        sa.Column("stock", sa.Integer(), nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("stock >= 0", name=op.f("ck_variants_stock_non_negative")),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_variants_product_id_products"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_variants")),
        sa.UniqueConstraint("sku", name=op.f("uq_variants_sku")),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(op.f("ix_variants_product_id"), "variants", ["product_id"], unique=False)
    op.create_table(
        "cart_items",
        sa.Column("cart_id", sa.BigInteger(), nullable=False),
        sa.Column("variant_id", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_cart_items_quantity_positive")),
        sa.ForeignKeyConstraint(
            ["cart_id"], ["carts.id"], name=op.f("fk_cart_items_cart_id_carts"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"],
            ["variants.id"],
            name=op.f("fk_cart_items_variant_id_variants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cart_items")),
        sa.UniqueConstraint("cart_id", "variant_id", name=op.f("uq_cart_items_cart_id_variant_id")),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(op.f("ix_cart_items_variant_id"), "cart_items", ["variant_id"], unique=False)
    op.create_table(
        "order_items",
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("variant_id", sa.BigInteger(), nullable=False),
        sa.Column("product_name_at_order", sa.String(length=200), nullable=False),
        sa.Column("color", sa.String(length=50), nullable=False),
        sa.Column("size", sa.String(length=20), nullable=False),
        sa.Column("unit_price_at_order", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("discount", sa.Integer(), nullable=False),
        sa.Column("coupon_id", sa.BigInteger(), nullable=True),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_order_items_order_id_orders"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"],
            ["variants.id"],
            name=op.f("fk_order_items_variant_id_variants"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_items")),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(op.f("ix_order_items_order_id"), "order_items", ["order_id"], unique=False)
    op.create_index(op.f("ix_order_items_variant_id"), "order_items", ["variant_id"], unique=False)
    op.create_table(
        "payments",
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "provider",
            sa.Enum("stub", "stripe", name="payment_provider", native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column("provider_ref", sa.String(length=255), nullable=True),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column(
            "result",
            sa.Enum("ok", "ng", "refunded", name="payment_result", native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column("refunded_amount", sa.Integer(), nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_payments_order_id_orders"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payments")),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(op.f("ix_payments_order_id"), "payments", ["order_id"], unique=False)


def downgrade() -> None:
    """スキーマを戻す（ロールバック手順）。

    autogenerate は FK 列の索引を `drop_index` してから `drop_table` する順を出すが、
    MySQL は FK が参照する索引を単独では落とせない（error 1553）。`drop_table` が索引も
    一緒に落とすので、`drop_index` は手で削除した（依存の逆順で表だけ drop する）。
    """
    op.drop_table("payments")
    op.drop_table("order_items")
    op.drop_table("cart_items")
    op.drop_table("variants")
    op.drop_table("product_images")
    op.drop_table("product_categories")
    op.drop_table("orders")
    op.drop_table("system_settings")
    op.drop_table("products")
    op.drop_table("categories")
    op.drop_table("carts")
    op.drop_table("audit_logs")
