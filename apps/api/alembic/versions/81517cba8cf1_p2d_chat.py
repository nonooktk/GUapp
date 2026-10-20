"""P2-d マイグレーション: chat_sessions・chat_messages 表（設計仕様書 P2 追補d 5.1・5.2）。

`alembic revision --autogenerate` の生成物を目視点検し、以下を確認済み:
`chat_sessions.token_hash` の UNIQUE（SHA-256 の 16 進。CHAR(64)）、`ix_chat_sessions_updated_at`、
`chat_messages` の FK（`chat_session_id` → `chat_sessions.id`）と索引
`(chat_session_id, id)`・`created_at`、utf8mb4 / utf8mb4_0900_ai_ci / InnoDB。
他の表（members・orders・sessions を含む）には触れない。

統合: 当初の `down_revision` は origin/main の head（`ad00074244c2`）だったが、P2-b・P2-c の
リビジョンと head が分かれるため、P2-c の head（`14aa9b4157c2`）につなぎ直した
（P2 追補d 0.3・11.3）。

ロールバック: `alembic downgrade -1`（`chat_messages` → `chat_sessions` の順の DROP のみ）。

Revision ID: 81517cba8cf1
Revises: 14aa9b4157c2
Create Date: 2026-10-20 (JST)
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# リビジョン識別子（Alembic が使う）
revision: str = "81517cba8cf1"  # pragma: allowlist secret（Alembic のリビジョン ID。秘密ではない）
down_revision: str | Sequence[str] | None = "14aa9b4157c2"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """スキーマを進める。"""
    op.create_table(
        "chat_sessions",
        sa.Column("token_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("turns", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("handoff_at", sa.DateTime(), nullable=True),
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_chat_sessions_token_hash")),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index("ix_chat_sessions_updated_at", "chat_sessions", ["updated_at"], unique=False)
    op.create_table(
        "chat_messages",
        sa.Column(
            "chat_session_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False
        ),
        sa.Column(
            "role",
            sa.Enum("user", "assistant", name="chat_role", native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column("body_masked", sa.Text(), nullable=False),
        sa.Column("product_ids", sa.JSON(), nullable=True),
        sa.Column("intent", sa.String(length=20), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            autoincrement=True,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["chat_session_id"],
            ["chat_sessions.id"],
            name=op.f("fk_chat_messages_chat_session_id_chat_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_messages")),
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_0900_ai_ci",
        mysql_engine="InnoDB",
    )
    op.create_index("ix_chat_messages_created_at", "chat_messages", ["created_at"], unique=False)
    op.create_index(
        "ix_chat_messages_session_id_id", "chat_messages", ["chat_session_id", "id"], unique=False
    )


def downgrade() -> None:
    """スキーマを戻す（ロールバック手順）。

    索引は表と一緒に消える（`(chat_session_id, id)` は FK の支えを兼ねるため、
    先に索引だけを DROP すると MySQL が拒否する）。
    """
    op.drop_table("chat_messages")
    op.drop_table("chat_sessions")
