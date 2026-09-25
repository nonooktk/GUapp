"""コンテンツ（DS-TBL-22）の読み出し（DS-API-005・006）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Content, ContentKind

# 一覧・詳細どちらも「掲載期間内」の絞り込みに使う（DS-PRC-005・006 で共通の判定式）
_STATIC_DETAIL_KINDS = (ContentKind.faq, ContentKind.static)


def _published_at(now: datetime):
    """`publish_from <= now AND (publish_to IS NULL OR publish_to >= now)`。"""
    return (Content.publish_from <= now) & (
        or_(Content.publish_to.is_(None), Content.publish_to >= now)
    )


async def list_by_kind(
    session: AsyncSession, *, kind: ContentKind, now: datetime, limit: int
) -> list[Content]:
    """DS-PRC-005。`news` は publish_from 降順、`feature` は sort_order 昇順。"""
    stmt = select(Content).where(Content.kind == kind, _published_at(now))
    if kind == ContentKind.news:
        stmt = stmt.order_by(Content.publish_from.desc(), Content.id.desc())
    else:
        stmt = stmt.order_by(Content.sort_order.asc(), Content.id.asc())
    stmt = stmt.limit(limit)
    rows = await session.execute(stmt)
    return list(rows.scalars().all())


async def get_by_slug(session: AsyncSession, slug: str) -> Content | None:
    """DS-PRC-006 手順1。`kind IN ('faq','static')` かつ slug 一致。掲載期間はサービス層で判定。"""
    stmt = select(Content).where(Content.slug == slug, Content.kind.in_(_STATIC_DETAIL_KINDS))
    return (await session.execute(stmt)).scalar_one_or_none()
