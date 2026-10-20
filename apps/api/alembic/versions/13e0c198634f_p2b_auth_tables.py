"""P2-b マイグレーション 1/2: 会員・認証・店舗・再入荷・レビューの 8 表。

設計仕様書 P2 追補b 5.1・5.2・5.5（DS-DEC-83）。作る表は次の 8 つ。
外部キーで参照される順に作る（members・stores が先、email_tokens・restock_notifications・
reviews が後）。

- DS-TBL-01 members          会員。パスワードは argon2id のハッシュ
- DS-TBL-10 stores           受け取り店舗（P3 から前倒し）
- DS-TBL-04 staff            管理者（P2-c 先出し。P2-b は行も API も作らない）
- DS-TBL-03 sessions         会員と管理者の共用。`subject_type` で分ける。FK なし
- DS-TBL-26 login_attempts   ログイン試行。ロックと IP 制限の判定元。FK なし
- DS-TBL-27 email_tokens     メール確認・パスワード再設定のトークン
- DS-TBL-20 restock_notifications  再入荷通知の申込
- DS-TBL-19 reviews          サイズ感の集計の元（P2-b は seed だけが入れる）

このリビジョンだけを適用した状態でも、既存機能は動く（既存表に触らない）。
既存表（carts・orders）への外部キー・UNIQUE・索引は次のリビジョン
`f16be26dc48a`（p2b_orders_pickup_fk）で足す。

ロールバック: `alembic downgrade -1`（8 表を子 → 親の逆順に `DROP TABLE`）。
共用の講義 DB ではロールバックを試した記録を残す（ADR-0002）。

Revision ID: 13e0c198634f
Revises: ad00074244c2
Create Date: 2026-10-20 (JST)
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# リビジョン識別子（Alembic が使う）
revision: str = "13e0c198634f"  # pragma: allowlist secret（Alembic のリビジョン ID。秘密ではない）
down_revision: str | Sequence[str] | None = "ad00074244c2"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MYSQL = {
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
    "mysql_engine": "InnoDB",
}


def _common_columns() -> list[sa.Column]:
    """主キーと created_at・updated_at（本編 5.2 の共通事項）。"""
    return [
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    """スキーマを進める。8 表を外部キーの参照先から順に作る。"""
    # DS-TBL-01 members
    op.create_table(
        "members",
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column(
            "gender",
            sa.Enum(
                "female",
                "male",
                "other",
                "no_answer",
                name="member_gender",
                native_enum=False,
                length=20,
            ),
            nullable=True,
        ),
        sa.Column("personalize_opt_in", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(), nullable=True),
        sa.Column("locked_until", sa.DateTime(), nullable=True),
        sa.Column("anonymized_at", sa.DateTime(), nullable=True),
        *_common_columns(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_members")),
        sa.UniqueConstraint("email", name=op.f("uq_members_email")),
        **_MYSQL,
    )

    # DS-TBL-10 stores
    op.create_table(
        "stores",
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("prefecture", sa.String(length=20), nullable=False),
        sa.Column("postal_code", sa.CHAR(length=7), nullable=False),
        sa.Column("address", sa.String(length=200), nullable=False),
        sa.Column("pickup_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        *_common_columns(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stores")),
        sa.UniqueConstraint("code", name=op.f("uq_stores_code")),
        **_MYSQL,
    )

    # DS-TBL-04 staff（P2-c 先出し）
    op.create_table(
        "staff",
        sa.Column("login_id", sa.String(length=50), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=20), server_default="staff", nullable=False),
        sa.Column("locked_until", sa.DateTime(), nullable=True),
        *_common_columns(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_staff")),
        sa.UniqueConstraint("login_id", name=op.f("uq_staff_login_id")),
        **_MYSQL,
    )

    # DS-TBL-03 sessions（会員と管理者の共用。subject_id に FK を張らない）
    op.create_table(
        "sessions",
        sa.Column("token_hash", sa.CHAR(length=64), nullable=False),
        sa.Column(
            "subject_type",
            sa.Enum(
                "member",
                "staff",
                name="session_subject_type",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("subject_id", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        *_common_columns(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_sessions_token_hash")),
        **_MYSQL,
    )
    op.create_index(
        "ix_sessions_subject_type_subject_id",
        "sessions",
        ["subject_type", "subject_id"],
        unique=False,
    )
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"], unique=False)

    # DS-TBL-26 login_attempts（FK なし。identifier はメールまたはログイン ID の SHA-256）
    op.create_table(
        "login_attempts",
        sa.Column(
            "subject_type",
            sa.Enum(
                "member",
                "staff",
                name="login_attempt_subject_type",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("identifier", sa.CHAR(length=64), nullable=False),
        sa.Column("succeeded", sa.Boolean(), nullable=False),
        sa.Column("ip", sa.String(length=45), nullable=False),
        sa.Column("at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        *_common_columns(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_login_attempts")),
        **_MYSQL,
    )
    op.create_index(
        "ix_login_attempts_subject_type_identifier_at",
        "login_attempts",
        ["subject_type", "identifier", "at"],
        unique=False,
    )
    op.create_index("ix_login_attempts_ip_at", "login_attempts", ["ip", "at"], unique=False)
    op.create_index("ix_login_attempts_at", "login_attempts", ["at"], unique=False)

    # DS-TBL-27 email_tokens
    op.create_table(
        "email_tokens",
        sa.Column("member_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "purpose",
            sa.Enum(
                "verify_email",
                "reset_password",
                name="email_token_purpose",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("token_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        *_common_columns(),
        sa.ForeignKeyConstraint(
            ["member_id"],
            ["members.id"],
            name=op.f("fk_email_tokens_member_id_members"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_email_tokens_token_hash")),
        **_MYSQL,
    )
    op.create_index(
        "ix_email_tokens_member_id_purpose",
        "email_tokens",
        ["member_id", "purpose"],
        unique=False,
    )

    # DS-TBL-20 restock_notifications
    op.create_table(
        "restock_notifications",
        sa.Column("variant_id", sa.BigInteger(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("member_id", sa.BigInteger(), nullable=True),
        sa.Column("notified_at", sa.DateTime(), nullable=True),
        *_common_columns(),
        sa.ForeignKeyConstraint(
            ["member_id"],
            ["members.id"],
            name=op.f("fk_restock_notifications_member_id_members"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["variant_id"],
            ["variants.id"],
            name=op.f("fk_restock_notifications_variant_id_variants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_restock_notifications")),
        sa.UniqueConstraint(
            "variant_id", "email", name=op.f("uq_restock_notifications_variant_id_email")
        ),
        **_MYSQL,
    )
    op.create_index(
        "ix_restock_notifications_variant_id_notified_at",
        "restock_notifications",
        ["variant_id", "notified_at"],
        unique=False,
    )
    op.create_index(
        "ix_restock_notifications_email", "restock_notifications", ["email"], unique=False
    )

    # DS-TBL-19 reviews
    op.create_table(
        "reviews",
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("member_id", sa.BigInteger(), nullable=True),
        sa.Column("rating", sa.SmallInteger(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "fit",
            sa.Enum("small", "just", "large", name="review_fit", native_enum=False, length=20),
            nullable=True,
        ),
        sa.Column("approved", sa.Boolean(), server_default=sa.false(), nullable=False),
        *_common_columns(),
        sa.CheckConstraint("rating >= 1 AND rating <= 5", name=op.f("ck_reviews_rating_range")),
        sa.ForeignKeyConstraint(
            ["member_id"],
            ["members.id"],
            name=op.f("fk_reviews_member_id_members"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_reviews_product_id_products"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reviews")),
        **_MYSQL,
    )
    op.create_index("ix_reviews_product_id_approved", "reviews", ["product_id", "approved"])


def downgrade() -> None:
    """スキーマを戻す（ロールバック手順）。外部キーの子 → 親の逆順に `DROP TABLE`。

    `DROP TABLE` が表の索引・UNIQUE・CHECK も一緒に落とすため、個別の `drop_index` は書かない。
    """
    op.drop_table("reviews")
    op.drop_table("restock_notifications")
    op.drop_table("email_tokens")
    op.drop_table("login_attempts")
    op.drop_table("sessions")
    op.drop_table("staff")
    op.drop_table("stores")
    op.drop_table("members")
