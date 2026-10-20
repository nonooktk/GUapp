"""更新前の値の照合（DS-PRC-055。設計仕様書 P2 追補c 4.0・4.6・DS-DEC-113）。

担当レーン: C-1（部品）。使うのは C-2（商品・在庫・設定の更新）。C-3（注文状態）は
`expected_*` を使わない（更新先の状態から更新前の状態が一意に決まるため。DS-DEC-113）。

更新系の要求は、更新する値と、画面が表示していた更新前の値（`expected_<項目名>`）を一組で送る。
呼び出し側は対象の行を `SELECT … FOR UPDATE` で読んだ**あとに**この関数を呼ぶ（照合と更新の間に
他の更新が入らない）。本編 4.5 の「楽観ロック `updated_at`」は使わない（秒精度で同じ秒の更新を
区別できないため）。
"""

from __future__ import annotations

from typing import Any

from app.core.errors import AppError


def ensure_expected(field: str, expected: Any, current: Any) -> None:
    """`expected` と `current` が**型を含めて**厳密に等しいときだけ通す。

    違えば `AppError(409, "stale_data", field=field, current=current)`。
    `True` と `1`、`0` と `False`、`"0.10"` と `0.1`、`"550"` と `550` は等しくない。

    担当レーン: C-1。呼ぶのは C-2。`field` は応答の `field`（例: `"stock"`・`"published"`・
    `"price_incl_tax"`・`"tax_rate"`）。`current` は現在の値で、BFF が許可する詳細キー
    `current` として画面に返る（JSON にできる値を渡す）。
    """
    if type(expected) is type(current) and expected == current:
        return
    raise AppError(409, "stale_data", field=field, current=current)
