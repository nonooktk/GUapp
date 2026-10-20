"""P2-b マイグレーション 2/2: carts・orders への外部キー・UNIQUE・索引。

設計仕様書 P2 追補b 5.3・5.5（DS-DEC-79・82・83）。既存表に触る変更だけをこのリビジョンに
分け、`downgrade` で個別に戻せるようにする。列の追加はない（`member_id`・`store_id`・
`pickup_code` は P1 から列がある）。既存の行はすべてこれらが NULL のため、
外部キーの追加は既存データを壊さない。

| 表     | 変更                                                                          |
| ------ | ----------------------------------------------------------------------------- |
| carts  | FK `fk_carts_member_id_members`（→ members.id・ON DELETE SET NULL）          |
| orders | FK `fk_orders_member_id_members`（→ members.id・ON DELETE RESTRICT）         |
| orders | FK `fk_orders_store_id_stores`（→ stores.id・ON DELETE RESTRICT）            |
| orders | UNIQUE `uq_orders_pickup_code`（NULL は重複可）                              |
| orders | 索引 `ix_orders_member_id_created_at`（member_id, created_at）。注文履歴     |
| orders | 索引 `ix_orders_created_at`・`ix_orders_guest_email`。P2-c の注文検索に先出し |

ロールバック: `alembic downgrade -1`。足したものを外部キー → 索引 → UNIQUE の順に削除する
（MySQL は外部キーが使っている索引を先に消せないため、外部キーを先に落とす）。
`orders.store_id` には明示した索引が無く、MySQL が外部キーの作成時に自動で索引
`fk_orders_store_id_stores` を作る。外部キーを落としても残るため、downgrade で併せて削除する。

Revision ID: f16be26dc48a
Revises: 13e0c198634f
Create Date: 2026-10-20 (JST)
"""

from collections.abc import Sequence

from alembic import op

# リビジョン識別子（Alembic が使う）
revision: str = "f16be26dc48a"  # pragma: allowlist secret（Alembic のリビジョン ID。秘密ではない）
down_revision: str | Sequence[str] | None = "13e0c198634f"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """スキーマを進める。外部キー → UNIQUE → 索引の順に足す。"""
    op.create_foreign_key(
        op.f("fk_carts_member_id_members"),
        "carts",
        "members",
        ["member_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_orders_member_id_members"),
        "orders",
        "members",
        ["member_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_orders_store_id_stores"),
        "orders",
        "stores",
        ["store_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(op.f("uq_orders_pickup_code"), "orders", ["pickup_code"])
    op.create_index(
        "ix_orders_member_id_created_at", "orders", ["member_id", "created_at"], unique=False
    )
    op.create_index("ix_orders_created_at", "orders", ["created_at"], unique=False)
    op.create_index("ix_orders_guest_email", "orders", ["guest_email"], unique=False)


def downgrade() -> None:
    """スキーマを戻す（ロールバック手順）。外部キー → 索引 → UNIQUE の順に削除する。"""
    op.drop_constraint(op.f("fk_orders_store_id_stores"), "orders", type_="foreignkey")
    # store_id には他に索引が無いため、MySQL が外部キーの作成時に自動で作った索引
    # （名前は外部キーと同じ）が残る。元の状態に戻すため明示的に削除する
    op.drop_index(op.f("fk_orders_store_id_stores"), table_name="orders")
    op.drop_constraint(op.f("fk_orders_member_id_members"), "orders", type_="foreignkey")
    op.drop_constraint(op.f("fk_carts_member_id_members"), "carts", type_="foreignkey")
    op.drop_index("ix_orders_guest_email", table_name="orders")
    op.drop_index("ix_orders_created_at", table_name="orders")
    op.drop_index("ix_orders_member_id_created_at", table_name="orders")
    op.drop_constraint(op.f("uq_orders_pickup_code"), "orders", type_="unique")
