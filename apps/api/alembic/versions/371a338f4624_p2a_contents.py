"""P2-a マイグレーション: contents 表（設計仕様書 P2 追補a 5.1 DS-TBL-22）。

`alembic revision --autogenerate` の生成物を目視点検し、以下を確認済み:
UNIQUE（slug）、複合索引 `(kind, publish_from)`（一覧クエリ DS-PRC-005 の絞り込み列）、
utf8mb4 / utf8mb4_0900_ai_ci / InnoDB。他表への外部キーを持たないため downgrade は単純。

ロールバック: `alembic downgrade -1`（`DROP TABLE contents` のみ）。

Revision ID: 371a338f4624
Revises: 6659ce6c5164
Create Date: 2026-09-24 23:58:45 (JST)
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# リビジョン識別子（Alembic が使う）
revision: str = "371a338f4624"  # pragma: allowlist secret（Alembic のリビジョン ID。秘密ではない）
down_revision: str | Sequence[str] | None = "6659ce6c5164"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """スキーマを進める。"""
    op.create_table(
        "contents",
        sa.Column(
            "kind",
            sa.Enum(
                "feature",
                "news",
                "faq",
                "static",
                name="content_kind",
                native_enum=False,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("publish_from", sa.DateTime(), nullable=False),
        sa.Column("publish_to", sa.DateTime(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contents")),
        sa.UniqueConstraint("slug", name=op.f("uq_contents_slug")),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index(
        "ix_contents_kind_publish_from", "contents", ["kind", "publish_from"], unique=False
    )


def downgrade() -> None:
    """スキーマを戻す（ロールバック手順）。`DROP TABLE` が索引も一緒に落とす。"""
    op.drop_table("contents")
