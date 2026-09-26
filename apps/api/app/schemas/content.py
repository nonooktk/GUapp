"""コンテンツ系の応答（DS-API-005・006。設計仕様書 P2 追補a 4.2・4.3）。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

# 一覧の kind（feature／news のみ。faq／static は一覧化しない設計）
ContentListKindLiteral = Literal["feature", "news"]
# 応答に載せる kind（4 値）
ContentKindLiteral = Literal["feature", "news", "faq", "static"]

# DS-API-005 の limit（既定5・最大20）
CONTENT_LIMIT_DEFAULT = 5
CONTENT_LIMIT_MAX = 20


class ContentListItemOut(BaseModel):
    slug: str
    title: str
    kind: ContentKindLiteral
    publish_from: datetime


class ContentsResponse(BaseModel):
    items: list[ContentListItemOut]


class ContentDetailOut(BaseModel):
    slug: str
    kind: ContentKindLiteral
    title: str
    body: str
