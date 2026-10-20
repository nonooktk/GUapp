"""AI アシスタントの入出力の検査（純粋関数。設計仕様書 P2 追補d 4.6・付録 C・付録 D）。

- DS-PRC-029-2 `mask_pii`: 個人情報のマスク（保存する前・LLM へ送る前・LLM の出力にも掛ける）
- DS-PRC-029-3: LLM 出力の検査と商品カードの組み立て（創作防止）。
  `sanitize_text`・`contains_canary`・`find_foreign_amounts`・`numbers_not_in_sources`・
  `validate_items`・`finalize_reply`。検査はすべて決定的なコードで行い、LLM に再質問しない
- DS-PRC-029-4 `jst_day_start_utc`: 日次上限の「今日（JST）」の開始

正規表現は NFKC 後の文字列に `re.ASCII` で当てる（全角数字・各種ハイフンを先にそろえる）。
DB・ネットワーク・設定に依存しない。
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from app.schemas.chat import (
    ChatGuideLinkOut,
    ChatGuideOut,
    ChatLLMItem,
    ChatLLMOutput,
    ChatProductOut,
    ChatReplyOut,
    ChatSourceOut,
    Intent,
)

if TYPE_CHECKING:
    from app.repositories.products import ProductSummary

JST = ZoneInfo("Asia/Tokyo")

MAX_PRODUCTS = 3
MESSAGE_MAX_CHARS = 300
REASON_MAX_CHARS = 40

# ── サーバーの定型文（付録 C）──
OUT_OF_SCOPE_MESSAGE = (
    "申し訳ありません。そのご質問には、こちらではお答えできません。"
    "よくある質問と企業情報のページをご覧ください。"
)
NO_PRODUCTS_MESSAGE = (
    "条件に合う商品を確認できませんでした。"
    "用途・季節・予算・サイズ・色のうち、教えていただける条件はありますか。"
)
AMOUNT_CHECK_FAILED_MESSAGE = (
    "ご希望に近い商品をご紹介します。価格と在庫は、各商品の表示をご確認ください。"
)

FAQ_SOURCE = ChatSourceOut(title="よくある質問", href="/contents/faq")
GUIDE_LINKS = (
    ChatGuideLinkOut(label="よくある質問", href="/contents/faq"),
    ChatGuideLinkOut(label="企業情報", href="/contents/company"),
)

# ══════════════════════════════════════════════════════════════════════════
# DS-PRC-029-2 個人情報のマスク
# ══════════════════════════════════════════════════════════════════════════

MASK_EMAIL = "[メール]"
MASK_CARD = "[カード番号]"
MASK_PHONE = "[電話番号]"
MASK_POSTAL = "[郵便番号]"
MASK_ADDRESS = "[住所]"
MASK_NAME = "[氏名]"

# 数字の間にあるハイフンの異体字（長音「ー」を含む）。数字に挟まれたときだけ `-` にする
# （全体を置換すると「スムース」などの通常の日本語が壊れるため）
_HYPHEN_VARIANTS_BETWEEN_DIGITS = re.compile(r"(?<=\d)[‐‑‒–—−―ー─━－](?=\d)", re.ASCII)

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", re.ASCII)
_CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)", re.ASCII)
_PHONE_RE = re.compile(r"(?<!\d)(?:\+81[ -]?|0)\d{1,4}[ -]?\d{1,4}[ -]?\d{3,4}(?!\d)", re.ASCII)
_POSTAL_RE = re.compile(r"(?<!\d)\d{3}-?\d{4}(?!\d)", re.ASCII)
_ADDRESS_RE = re.compile(
    r"(?:北海道|東京都|(?:京都|大阪)府|.{2,3}県).{1,20}?[0-9]+(?:丁目|番地?|-)[0-9]*", re.ASCII
)
# 氏名は「名前は〇〇」「〇〇と申します」「私は〇〇です」の申告の形に限る（DS-DEC-99）。
# 〇〇に当たる文字は、文を区切る記号・空白を含まない 1〜20 文字
_NAME_CHARS = r"[^\s、。,.!?！？「」『』()（）]"
_NAME_RE = re.compile(
    rf"(?:名前は|氏名は|私は)\s*(?P<a>{_NAME_CHARS}{{1,20}}?)(?:です|と申します|といいます)"
    rf"|(?P<b>{_NAME_CHARS}{{1,20}}?)と申します",
    re.ASCII,
)
# 「私は黒いパーカーが欲しいです」のように、買い物の希望文を氏名と誤認しないための除外。
# 設計書の正規表現そのままだと、この文が「私は[氏名]です」になり相談が成り立たない
_NOT_A_NAME_FRAGMENTS = ("が", "を", "に", "で", "は", "へ", "たい", "ほしい", "欲しい", "ます")


def normalize_text(text: str) -> str:
    """NFKC で全角の数字・英字・ハイフンを半角にそろえ、数字間のハイフンの異体字を `-` にする。"""
    normalized = unicodedata.normalize("NFKC", text)
    return _HYPHEN_VARIANTS_BETWEEN_DIGITS.sub("-", normalized)


def luhn_valid(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


@dataclass(frozen=True)
class MaskResult:
    """`counts` は置換した種類（email／card／phone／postal／address／name）ごとの件数。"""

    text: str
    counts: Mapping[str, int]

    @property
    def masked(self) -> bool:
        return bool(self.counts)


def mask_pii(text: str) -> MaskResult:
    """個人情報らしき文字列を置換語に置き換える。順序が重要（長い数字列を先に処理する）。

    1 つも置換しなかったときは、入力をそのまま（NFKC を掛けずに）返す。
    """
    counts: Counter[str] = Counter()
    t = normalize_text(text)

    def _email(m: re.Match[str]) -> str:
        counts["email"] += 1
        return MASK_EMAIL

    def _card(m: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", m.group(0))
        # Luhn に通るものだけ（注文番号などの誤検出を避ける）
        if 13 <= len(digits) <= 19 and luhn_valid(digits):
            counts["card"] += 1
            return MASK_CARD
        return m.group(0)

    def _phone(m: re.Match[str]) -> str:
        raw = m.group(0)
        digits = re.sub(r"\D", "", raw)
        # 国番号 +81 の形は先頭の 0 が落ちるので、国番号を除いた桁数で見る
        ok = 9 <= len(digits) - 2 <= 10 if raw.startswith("+81") else 10 <= len(digits) <= 11
        if ok:
            counts["phone"] += 1
            return MASK_PHONE
        return raw

    def _postal(m: re.Match[str]) -> str:
        counts["postal"] += 1
        return MASK_POSTAL

    def _address(m: re.Match[str]) -> str:
        counts["address"] += 1
        return MASK_ADDRESS

    def _name(m: re.Match[str]) -> str:
        group = "a" if m.group("a") is not None else "b"
        name = m.group(group)
        if any(fragment in name for fragment in _NOT_A_NAME_FRAGMENTS):
            return m.group(0)
        counts["name"] += 1
        start = m.start(group) - m.start()
        end = m.end(group) - m.start()
        whole = m.group(0)
        return whole[:start] + MASK_NAME + whole[end:]

    t = _EMAIL_RE.sub(_email, t)
    t = _CARD_RE.sub(_card, t)
    t = _PHONE_RE.sub(_phone, t)
    t = _POSTAL_RE.sub(_postal, t)
    t = _ADDRESS_RE.sub(_address, t)
    t = _NAME_RE.sub(_name, t)
    if not counts:
        return MaskResult(text=text, counts={})
    return MaskResult(text=t, counts=dict(counts))


# ══════════════════════════════════════════════════════════════════════════
# DS-PRC-029-3 LLM 出力の検査
# ══════════════════════════════════════════════════════════════════════════

_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>]*|[A-Za-z][A-Za-z0-9+.\-]*://[^\s<>]*", re.I)
_TAG_RE = re.compile(r"<[^>]*>")
_REMOVED_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co"})


def sanitize_text(text: str, max_len: int) -> str:
    """手順 1・9: HTML のタグ、URL、Markdown のリンク・画像、制御文字を取り除き、`max_len` に切る。

    リンクは見出しの文字だけ残す。通常の日本語・記号（「！」「、」）は変えない。
    """
    t = _MD_IMAGE_RE.sub("", text)
    t = _MD_LINK_RE.sub(r"\1", t)
    t = _URL_RE.sub("", t)
    t = _TAG_RE.sub("", t)
    t = t.replace("<", "").replace(">", "")
    out: list[str] = []
    for ch in t.replace("\t", " "):
        if ch in "  ":
            out.append("\n")
        elif ch == "\n" or unicodedata.category(ch) not in _REMOVED_CATEGORIES:
            out.append(ch)
    return "".join(out).strip()[:max_len]


def contains_canary(text: str, canary: str) -> bool:
    """手順 2: canary（固定指示の合言葉）が含まれるか。NFKC 後に大文字小文字を区別せず比べる。"""
    needle = unicodedata.normalize("NFKC", canary).casefold()
    return bool(needle) and needle in unicodedata.normalize("NFKC", text).casefold()


_AMOUNT_RE = re.compile(r"[¥￥]\s*\d[\d,]*|\d[\d,]*\s*円|税込\s*\d[\d,]*", re.ASCII)
_THOUSANDS_COMMA_RE = re.compile(r"(?<=\d),(?=\d{3}(?!\d))", re.ASCII)


def digit_strings(text: str) -> set[str]:
    """NFKC 後の数字列（3 桁区切りのカンマを除く）の集合。"""
    t = _THOUSANDS_COMMA_RE.sub("", unicodedata.normalize("NFKC", text))
    return set(re.findall(r"\d+", t, flags=re.ASCII))


def find_foreign_amounts(text: str, allowed: Collection[int]) -> list[int]:
    """手順 3: 金額らしき表記（¥1,990・1,990円・税込1990 など）のうち、`allowed` に無い数値。

    `allowed` は利用者の今回の質問に含まれる数値の集合。3色・2WAY・100%綿・S〜L は金額でない。
    """
    found: list[int] = []
    for m in _AMOUNT_RE.finditer(unicodedata.normalize("NFKC", text)):
        digits = re.sub(r"\D", "", m.group(0))
        if digits and int(digits) not in allowed:
            found.append(int(digits))
    return found


def numbers_not_in_sources(text: str, sources: Iterable[str]) -> list[str]:
    """手順 4: `text` の 2 桁以上の数字列のうち、`sources`（資料・質問）のどこにも無いもの。"""
    allowed: set[str] = set()
    for source in sources:
        allowed |= digit_strings(source)
    return sorted(n for n in digit_strings(text) if len(n) >= 2 and n not in allowed)


def validate_items(
    items: Sequence[ChatLLMItem], pool_ids: Collection[int], *, limit: int = MAX_PRODUCTS
) -> list[ChatLLMItem]:
    """手順 5: プール内の ID だけを、重複を除いて先頭から `limit` 件。`reason` は 40 文字に切る。"""
    seen: set[int] = set()
    kept: list[ChatLLMItem] = []
    for item in items:
        if item.product_id in seen:
            continue
        seen.add(item.product_id)
        if item.product_id not in pool_ids:
            continue
        kept.append(
            ChatLLMItem(
                product_id=item.product_id, reason=sanitize_text(item.reason, REASON_MAX_CHARS)
            )
        )
        if len(kept) >= limit:
            break
    return kept


@dataclass(frozen=True)
class Finalized:
    reply: ChatReplyOut
    canary_leak: bool
    dropped_ids: int


def _clean(text: str, max_len: int) -> str:
    """サニタイズ → 個人情報のマスク（LLM が個人情報を創作・復元する経路を作らない）。"""
    return mask_pii(sanitize_text(text, max_len)).text[:max_len]


def finalize_reply(
    output: ChatLLMOutput,
    *,
    question: str,
    sources: Sequence[str],
    canary: str,
    pool_ids: Collection[int],
    cards: Mapping[int, ProductSummary],
) -> Finalized:
    """手順 1〜9 を通して、画面に出す応答を組み立てる。

    `cards` は、DB から再取得した公開商品（名称・税込価格・画像・在庫切れの出どころ）。
    ここに無い ID は捨てる。価格・在庫は LLM の文章を使わず、カードの DB 値だけで示す。
    """
    intent: Intent = output.intent
    message = _clean(output.message, MESSAGE_MAX_CHARS)

    # 手順 5・6 の対象（recommend のときだけ）
    unique_ids = list(dict.fromkeys(i.product_id for i in output.items))
    in_pool = [i for i in unique_ids if i in pool_ids]
    candidates = validate_items(output.items, pool_ids) if intent == "recommend" else []
    reasons = {c.product_id: _clean(c.reason, REASON_MAX_CHARS) for c in candidates}

    # 手順 2: canary（message・reason のどれにあっても範囲外にする）
    canary_leak = contains_canary(message, canary) or any(
        contains_canary(r, canary) for r in reasons.values()
    )
    if canary_leak:
        intent = "out_of_scope"

    # 手順 3: 金額らしき表記（利用者の質問にある数値だけ許す）
    if intent in ("recommend", "clarify"):
        allowed = {int(n) for n in digit_strings(question)}
        if find_foreign_amounts(message, allowed) or any(
            find_foreign_amounts(r, allowed) for r in reasons.values()
        ):
            message = AMOUNT_CHECK_FAILED_MESSAGE
            reasons = {pid: "" for pid in reasons}

    # 手順 4: FAQ の回答の数値は、資料か質問にあるものだけ
    if intent == "faq" and numbers_not_in_sources(message, [*sources, question]):
        intent = "out_of_scope"

    products: list[ChatProductOut] = []
    if intent == "recommend":
        for cand in candidates:
            card = cards.get(cand.product_id)
            if card is None:
                continue
            products.append(
                ChatProductOut(
                    id=card.id,
                    name=card.name,
                    price_incl_tax=card.price_incl_tax,
                    image_path=card.image_path,
                    sold_out=card.sold_out,
                    reason=reasons.get(cand.product_id, ""),
                )
            )
        # 手順 7: 全滅したら条件を聞き返す
        if not products:
            intent = "clarify"
            message = NO_PRODUCTS_MESSAGE
        elif not message:
            message = AMOUNT_CHECK_FAILED_MESSAGE
    if intent in ("faq", "clarify") and not message:
        intent = "out_of_scope"

    # 手順 8: 範囲外は常に定型文
    guide: ChatGuideOut | None = None
    reply_sources: list[ChatSourceOut] = []
    if intent == "out_of_scope":
        message = OUT_OF_SCOPE_MESSAGE
        products = []
        guide = ChatGuideOut(links=list(GUIDE_LINKS))
    elif intent == "faq":
        reply_sources = [FAQ_SOURCE]

    dropped = 0
    if output.intent == "recommend" and not canary_leak:
        dropped = (len(unique_ids) - len(in_pool)) + (len(candidates) - len(products))
    return Finalized(
        reply=ChatReplyOut(
            intent=intent,
            message=message[:MESSAGE_MAX_CHARS],
            products=products,
            sources=reply_sources,
            guide=guide,
        ),
        canary_leak=canary_leak,
        dropped_ids=dropped,
    )


# ══════════════════════════════════════════════════════════════════════════
# DS-PRC-029-4 日次上限の「今日（JST）」
# ══════════════════════════════════════════════════════════════════════════


def jst_day_start_utc(now: datetime | None = None) -> datetime:
    """今日（JST）の 0 時を UTC に直した naive な日時（DB の `created_at` と比べる値）。

    境界は UTC の 15:00。`ZoneInfo("Asia/Tokyo")` を使う（Windows は `tzdata` が要る）。
    """
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    jst_now = current.astimezone(JST)
    start_jst = jst_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start_jst.astimezone(UTC).replace(tzinfo=None)


__all__ = [
    "AMOUNT_CHECK_FAILED_MESSAGE",
    "FAQ_SOURCE",
    "GUIDE_LINKS",
    "NO_PRODUCTS_MESSAGE",
    "OUT_OF_SCOPE_MESSAGE",
    "Finalized",
    "MaskResult",
    "contains_canary",
    "digit_strings",
    "finalize_reply",
    "find_foreign_amounts",
    "jst_day_start_utc",
    "luhn_valid",
    "mask_pii",
    "normalize_text",
    "numbers_not_in_sources",
    "sanitize_text",
    "validate_items",
]
