"""コンテンツ系（DS-API-005・006）のサービス。

DS-PRC-005 コンテンツ一覧・DS-PRC-006 コンテンツ詳細（設計仕様書 P2 追補a 4.4）。

- 掲載期間の判定は UTC のみで行い、JST 変換はしない（DS-DEC-40）。`is_within_publish_window` は
  DB に依存しない純粋関数として切り出し、UT-CONTENT-01/02 で境界（等号を含む）を確認する。
- slug のパターン検証（`^[a-z0-9-]{1,100}$`）も純粋関数 `is_valid_slug` に切り出し、
  UT-CONTENT-03 で確認する。FastAPI 側は同じパターン文字列を `Path(pattern=...)` に渡し、
  不一致は既存の RequestValidationError ハンドラ（4.5・DS-DEC-32）経由で
  400 validation_error になる。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import ContentKind
from app.repositories import contents as contents_repo
from app.schemas.content import ContentDetailOut, ContentListItemOut, ContentsResponse

# DS-API-006: slug は英小文字・数字・ハイフンのみ、1〜100 文字
CONTENT_SLUG_PATTERN = re.compile(r"^[a-z0-9-]{1,100}$")


def is_valid_slug(slug: str) -> bool:
    """DS-PRC-006 手順0。パターン外は呼び出し側で 400 として扱う。"""
    return bool(CONTENT_SLUG_PATTERN.fullmatch(slug))


def is_within_publish_window(
    now: datetime, publish_from: datetime, publish_to: datetime | None
) -> bool:
    """DS-PRC-005 手順2 / DS-PRC-006 手順2。`<=`／`>=` の等号を含む（UT-CONTENT-02）。"""
    if now < publish_from:
        return False
    if publish_to is not None and now > publish_to:
        return False
    return True


def _utc_now_naive() -> datetime:
    """MySQL の DATETIME 列（naive・UTC）と比較できる形の現在時刻。"""
    return datetime.now(UTC).replace(tzinfo=None)


async def list_contents(session: AsyncSession, *, kind: str, limit: int) -> ContentsResponse:
    """DS-API-005。`kind` は Literal で受けているため列挙外は呼び出し前に 400 になっている。"""
    now = _utc_now_naive()
    rows = await contents_repo.list_by_kind(session, kind=ContentKind(kind), now=now, limit=limit)
    return ContentsResponse(
        items=[
            ContentListItemOut(
                slug=r.slug, title=r.title, kind=r.kind.value, publish_from=r.publish_from
            )
            for r in rows
        ]
    )


async def get_content_detail(session: AsyncSession, slug: str) -> ContentDetailOut:
    """DS-API-006。存在しない・対象外 kind・掲載期間外のいずれも 404 `not_found`（区別しない）。"""
    now = _utc_now_naive()
    row = await contents_repo.get_by_slug(session, slug)
    if row is None or not is_within_publish_window(now, row.publish_from, row.publish_to):
        raise AppError(404, "not_found")
    return ContentDetailOut(slug=row.slug, kind=row.kind.value, title=row.title, body=row.body)
