"""P2-c マイグレーション（1 本）: staff のロール制約と audit_logs の索引。

設計仕様書 P2 追補c 5.2・5.5（DS-DEC-111・123）。新しい表・列はない。

| 表         | 変更                                                                       |
| ---------- | -------------------------------------------------------------------------- |
| staff      | CHECK `ck_staff_role_allowed`（`role IN ('staff')`）。ロールは 1 つ（DS-DEC-111） |
| audit_logs | 索引 `ix_audit_logs_target_type_target_id_at`（target_type, target_id, at） |

`staff` の既存の行は P2-b で 0 件のため、制約の追加は失敗しない（行があっても `role` の既定は
`staff`）。`audit_logs` の索引追加は既存の行に影響しない。既存の `at` の索引は残す。
データを変える処理（管理者の seed）はここに入れない（本編 5.3。`app.seed --only-p2c`）。

ロールバック: `alembic downgrade -1`。索引、CHECK 制約の順に削除する。
`audit_logs` には外部キーがなく、この索引を使う外部キーもないため、そのまま削除できる。

Revision ID: 14aa9b4157c2
Revises: f16be26dc48a
Create Date: 2026-10-20 (JST)
"""

from collections.abc import Sequence

from alembic import op

# リビジョン識別子（Alembic が使う）
revision: str = "14aa9b4157c2"  # pragma: allowlist secret（Alembic のリビジョン ID。秘密ではない）
down_revision: str | Sequence[str] | None = "f16be26dc48a"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """スキーマを進める。CHECK 制約 → 索引の順に足す。"""
    op.create_check_constraint(op.f("ck_staff_role_allowed"), "staff", "role IN ('staff')")
    op.create_index(
        "ix_audit_logs_target_type_target_id_at",
        "audit_logs",
        ["target_type", "target_id", "at"],
    )


def downgrade() -> None:
    """スキーマを戻す（ロールバック手順）。索引 → CHECK 制約の順に削除する。"""
    op.drop_index("ix_audit_logs_target_type_target_id_at", table_name="audit_logs")
    op.drop_constraint(op.f("ck_staff_role_allowed"), "staff", type_="check")
