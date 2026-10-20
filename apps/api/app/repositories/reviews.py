"""レビューの読み出し（DS-TBL-19 reviews。サイズ感の集計 DS-PRC-003a・DS-DEC-81）。"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Review, ReviewFit


async def fit_counts(session: AsyncSession, product_id: int) -> dict[ReviewFit, int]:
    """承認済み（`approved` が真）で `fit` が NULL でないレビューを、`fit` ごとに数える。

    `SELECT fit, COUNT(*) FROM reviews WHERE product_id = :p AND approved = 1
    AND fit IS NOT NULL GROUP BY fit`（索引 `(product_id, approved)`）。1 回の実行で済ませる。
    """
    rows = await session.execute(
        select(Review.fit, func.count())
        .where(
            Review.product_id == product_id,
            Review.approved.is_(True),
            Review.fit.is_not(None),
        )
        .group_by(Review.fit)
    )
    return {ReviewFit(fit): int(n) for fit, n in rows.all()}
