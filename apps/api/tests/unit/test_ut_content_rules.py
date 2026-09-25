"""UT-CONTENT-01〜03: DS-PRC-005（掲載期間判定）・DS-PRC-006（slug 検証）の純粋関数（DB 不要）。

設計仕様書 P2 追補a 4.4「DS-PRC-005 コンテンツ一覧」「DS-PRC-006 コンテンツ詳細」、
テスト設計書 P2 追補a 5.1 UT-CONTENT-01〜03 に対応する。
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.services.content import is_valid_slug, is_within_publish_window

NOW = datetime(2026, 9, 24, 12, 0, 0)


def test_ut_content_01_indefinite_publish_to_is_published() -> None:
    """publish_from=1日前, publish_to=NULL（無期限） → 掲載対象。"""
    publish_from = NOW - timedelta(days=1)
    assert is_within_publish_window(NOW, publish_from, None) is True


@pytest.mark.parametrize(
    "publish_from,publish_to",
    [
        (NOW, NOW),  # ちょうど今（両方とも境界の等号を含む）
    ],
)
def test_ut_content_02_boundary_equal_now_is_published(
    publish_from: datetime, publish_to: datetime
) -> None:
    """publish_from=now・publish_to=now（ちょうど今） → どちらも掲載対象（<=／>= の等号を含む）。"""
    assert is_within_publish_window(NOW, publish_from, publish_to) is True


def test_ut_content_02b_before_publish_from_is_not_published() -> None:
    publish_from = NOW + timedelta(seconds=1)
    assert is_within_publish_window(NOW, publish_from, None) is False


def test_ut_content_02c_after_publish_to_is_not_published() -> None:
    publish_from = NOW - timedelta(days=10)
    publish_to = NOW - timedelta(seconds=1)
    assert is_within_publish_window(NOW, publish_from, publish_to) is False


@pytest.mark.parametrize(
    "slug",
    [
        "FAQ",  # 大文字
        "faq!",  # 記号
        "a" * 201,  # 201 文字（上限 100 超）
        "",  # 空文字
        "faq_terms",  # アンダースコアは許可しない
    ],
)
def test_ut_content_03_invalid_slugs_rejected(slug: str) -> None:
    """slug に大文字・記号・201 文字を渡す → いずれもパターン不一致。"""
    assert is_valid_slug(slug) is False


@pytest.mark.parametrize("slug", ["faq", "terms", "tokushoho-2026", "a", "a" * 100])
def test_ut_content_03b_valid_slugs_accepted(slug: str) -> None:
    assert is_valid_slug(slug) is True
