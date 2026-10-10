"""categories.kind 列の追加（商品一覧で ALL ＋ 種類を選んだとき、全性別の商品を出すため）。

カテゴリは性別ごとに別の行（slug 例: women-tops・men-tops・kids-teen-tops）なので、
slug 一致では「ALL のトップス」を表せなかった。性別をまたいで同じ種類を束ねる軸として
`kind`（VARCHAR(32)・NULL 可）を足す。親（性別）の行は NULL、子は tops / bottoms / outer /
dresses / inner-goods など。

upgrade では既存の子カテゴリ行に、slug から親（性別）slug と区切りの `-` を除いた値を入れる
（women-tops → tops、kids-teen-inner-goods → inner-goods）。接頭辞は親 slug（women / men /
kids-teen）から導くので、性別の追加があっても UPDATE を書き換えなくてよい。

索引は付けない: categories は十数行で、絞り込みは product_categories.category_id（索引あり）から
引いた後に categories を主キーで 1 行ずつ見る形のため、kind の索引は使われない。

ロールバック: `alembic downgrade -1`（`DROP COLUMN kind` のみ。他の列・データには影響しない）。

Revision ID: ad00074244c2
Revises: 371a338f4624
Create Date: 2026-10-04 (JST)
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# リビジョン識別子（Alembic が使う）
revision: str = "ad00074244c2"  # pragma: allowlist secret（Alembic のリビジョン ID。秘密ではない）
down_revision: str | Sequence[str] | None = "371a338f4624"  # pragma: allowlist secret
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """スキーマを進める。列を足し、既存の子カテゴリへ kind を入れる。"""
    op.add_column("categories", sa.Column("kind", sa.String(length=32), nullable=True))
    # 子の slug が「親 slug + '-' + 種類」の形のものだけ対象。親の行は parent_id が NULL なので
    # 結合に出ず、kind は NULL のまま
    op.execute(
        sa.text(
            "UPDATE categories AS c JOIN categories AS p ON c.parent_id = p.id "
            "SET c.kind = SUBSTRING(c.slug, CHAR_LENGTH(p.slug) + 2) "
            "WHERE c.slug LIKE CONCAT(p.slug, '-%')"
        )
    )


def downgrade() -> None:
    """スキーマを戻す（ロールバック手順）。"""
    op.drop_column("categories", "kind")
