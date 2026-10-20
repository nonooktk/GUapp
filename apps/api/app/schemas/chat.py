"""AI アシスタントの入出力（DS-API-040・041。設計仕様書 P2 追補d 4.2・4.3・付録 B）。

- `ChatMessageIn`: 質問。前後の空白を除いて 1〜300 文字（コードポイント数）。
  空・空白のみは 400 `required`、301 文字以上は 400 `too_long`（`map_reason` が変換する）
- `ChatLLMOutput`: LLM の構造化出力（付録 B）。Structured Outputs の制約（全プロパティ必須、
  `additionalProperties: false`）に合わせ、長さの制約はスキーマに入れず検査（DS-PRC-029-3）で行う
- 応答に含めないもの: セッションの内部 ID、`token_hash`、LLM の生の出力、モデル名、トークン数
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

CHAT_MESSAGE_MAX_CHARS = 300
PRODUCT_ID_MAX = 9223372036854775807

Intent = Literal["recommend", "faq", "clarify", "out_of_scope"]


# ── LLM の出力（付録 B）──
class ChatLLMItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: int
    reason: str


class ChatLLMOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Intent
    message: str
    items: list[ChatLLMItem]


# ── API の入力 ──
class ChatMessageIn(BaseModel):
    message: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=CHAT_MESSAGE_MAX_CHARS),
    ]
    # 商品詳細から開いたときの文脈。存在しない・非公開の ID はエラーにせず無視する（本編 7.5）
    product_id: Annotated[int, Field(ge=1, le=PRODUCT_ID_MAX)] | None = None


# ── API の出力 ──
class ChatStatusOut(BaseModel):
    available: bool
    reason: Literal["disabled", "daily_limit"] | None
    provider: Literal["openai", "stub", "none"]
    turns_limit: int
    message_max_chars: int


class ChatProductOut(BaseModel):
    """商品カード。名称・価格・画像・在庫切れは DB の値。`reason` だけ LLM の文章（検査済み）。"""

    id: int
    name: str
    price_incl_tax: int
    image_path: str | None
    sold_out: bool
    reason: str


class ChatSourceOut(BaseModel):
    title: str
    href: str


class ChatGuideLinkOut(BaseModel):
    label: str
    href: str


class ChatGuideOut(BaseModel):
    links: list[ChatGuideLinkOut]


class ChatReplyOut(BaseModel):
    intent: Intent
    message: str
    products: list[ChatProductOut]
    sources: list[ChatSourceOut]
    guide: ChatGuideOut | None


class ChatMessageOut(BaseModel):
    chat_token: str | None = Field(description="新規セッションのときだけ値が入る（BFF が除く）")
    reply: ChatReplyOut
    turns_used: int
    turns_limit: int
    notice: Literal["masked"] | None
