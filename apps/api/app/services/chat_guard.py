"""AI アシスタントの入出力の検査（純粋関数。設計仕様書 P2 追補d 4.6・付録 C・付録 D）。

- DS-PRC-029-2 `mask_pii`: 個人情報のマスク（保存する前・LLM へ送る前・LLM の出力にも掛ける）
- DS-PRC-029-3: LLM 出力の検査と商品カードの組み立て（創作防止）。
  `sanitize_text`・`contains_canary`・`find_foreign_amounts`・`find_unsupported_promises`・
  `numbers_not_in_sources`・`validate_items`・`finalize_reply`。検査はすべて決定的なコードで行い、
  LLM に再質問しない。ガードが動いた種類と件数は `Finalized.guards` に入れ、呼び手が 1 行ログに出す
  （本文は含めない。G-22）
- DS-PRC-029-4 `jst_day_start_utc`: 日次上限の「今日（JST）」の開始

正規表現は NFKC 後の文字列に `re.ASCII` で当てる（全角数字・各種ハイフンを先にそろえる）。
DB・ネットワーク・設定に依存しない。
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
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

PRODUCT_INFO_FALLBACK_MESSAGE = (
    "申し訳ありません。その点は、こちらでは確認できませんでした。商品ページの記載をご確認ください。"
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
MASK_NUMBER = "[番号]"

# 数字の間にあるハイフンの異体字（長音「ー」を含む）。数字に挟まれたときだけ `-` にする
# （全体を置換すると「スムース」などの通常の日本語が壊れるため）
_HYPHEN_VARIANTS_BETWEEN_DIGITS = re.compile(r"(?<=\d)[‐‑‒–—−―ー─━－](?=\d)", re.ASCII)

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", re.ASCII)
# `(at)`・` at `・`(dot)`・` dot ` で崩したメール（`taro (at) example (dot) com`、
# `taro at example.com`）。前後が ASCII の語（ローカル部とドメイン）のときだけ。
# ドメインには 1 つ以上の区切りが要る
_AT = r"(?:[(\[{<]\s*(?:at|アット|アットマーク)\s*[)\]}>]|\s+at\s+)"
_DOT = r"(?:[(\[{<]\s*(?:dot|ドット)\s*[)\]}>]|\s+dot\s+|\.)"
_OBFUSCATED_EMAIL_RE = re.compile(
    rf"[A-Za-z0-9._%+-]+\s*{_AT}\s*[A-Za-z0-9-]+(?:\s*{_DOT}\s*[A-Za-z0-9-]+)+", re.ASCII | re.I
)
_CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)", re.ASCII)
_PHONE_RE = re.compile(r"(?<!\d)(?:\+81[ -]?|0)\d{1,4}[ -]?\d{1,4}[ -]?\d{3,4}(?!\d)", re.ASCII)
# 漢数字（`零九零 一二三四 五六七八`）を含む電話番号。算用数字との混在も見る。
# 漢数字を 1 つも含まない並びは `_PHONE_RE` に任せる。先頭は 0（〇・零）、全体で 10〜11 桁
_KANJI_DIGITS = "〇零一二三四五六七八九"
_KANJI_DIGIT_TABLE = str.maketrans(_KANJI_DIGITS, "00123456789")
_KANJI_PHONE_RE = re.compile(
    rf"(?<![0-9{_KANJI_DIGITS}])[0〇零](?:[ \-‐‑–—−ーの]?[0-9{_KANJI_DIGITS}]){{9,10}}"
    rf"(?![0-9{_KANJI_DIGITS}])"
)
# 連続 12 桁の数字（マイナンバー風。4 桁ごとの空白・ハイフン区切りも含む）。
# 13 桁以上の数字列（カードなど）の一部を拾わないよう、前後に数字が続くものは除く
_NUMBER12_RE = re.compile(r"(?<!\d)(?<!\d[ -])\d{4}[ -]?\d{4}[ -]?\d{4}(?![ -]?\d)", re.ASCII)
_POSTAL_RE = re.compile(r"(?<!\d)\d{3}-?\d{4}(?!\d)", re.ASCII)
# 番地の部分（`1丁目2番3号`・`1-2-3`・`12-3`）。区切りで終わる断片（`-3` など）を残さないよう、
# 数字と区切りの繰り返しをひとまとめにして取る
_ADDRESS_TAIL = r"[0-9]+(?:(?:丁目|番地?|号|-)[0-9]*)+"
_ADDRESS_RE = re.compile(
    rf"(?:北海道|東京都|(?:京都|大阪)府|.{{2,3}}県).{{1,20}}?{_ADDRESS_TAIL}", re.ASCII
)
# 県名の無い住所（`渋谷区神南1丁目2番3号`・`横浜市中区山下町12-3`）。市区郡町村の前に漢字が要り、
# 番地までの間は漢字・カタカナだけ（ひらがなの助詞をはさむ普通の文を拾わない）
_KANJI = r"[一-鿿々〆ヶ]"
_CITY_ADDRESS_RE = re.compile(
    rf"{_KANJI}{{1,6}}[市区郡町村](?:{_KANJI}|[ァ-ヺー・])*?{_ADDRESS_TAIL}"
)
# 氏名は「名前は〇〇」「〇〇と申します／といいます」「私は〇〇です」の申告の形に限る（DS-DEC-99）。
# 〇〇に当たる文字は、文を区切る記号・空白を含まない 1〜20 文字（姓名の間の空白 1 つは許す）。
# 助詞なしで「〇〇です」だけは広すぎるため、姓と名を空白で分けた漢字の氏名（`山田 太郎 です`）に絞る
_NAME_CHARS = r"[^\s、。,.!?！？「」『』()（）]"
_NAME_BODY = rf"{_NAME_CHARS}{{1,20}}?(?:\s{_NAME_CHARS}{{1,20}}?)?"
_NAME_RE = re.compile(
    rf"(?:名前は|氏名は|私は|わたしは|僕は|俺は)\s*(?P<a>{_NAME_BODY})"
    rf"(?:です|と申します|といいます|と言います)"
    rf"|(?P<b>{_NAME_BODY})(?:と申します|といいます|と言います)"
    rf"|(?P<c>[一-鿿々]{{1,4}}\s[一-鿿々ぁ-んァ-ヶー]{{1,4}})\s?です",
    re.ASCII,
)
# 「私は黒いパーカーが欲しいです」のように、買い物の希望文を氏名と誤認しないための除外。
# 設計書の正規表現そのままだと、この文が「私は[氏名]です」になり相談が成り立たない
_NOT_A_NAME_FRAGMENTS = ("が", "を", "に", "で", "は", "へ", "たい", "ほしい", "欲しい", "ます")
# 助詞なしの「漢字 漢字 です」（`山田 太郎 です`）だけに掛ける除外。「春物 全部です」のような
# 買い物の語（物・全・色・柄・丈・型・品・着・服・商・庫・数）を含むものは氏名としない
_NOT_A_NAME_CHARS_BARE = frozenset("物全色柄丈型品着服商庫数")


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
    """`counts` は置換した種類（email／card／phone／number／postal／address／name）ごとの件数。"""

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

    def _kanji_phone(m: re.Match[str]) -> str:
        raw = m.group(0)
        if not any(ch in _KANJI_DIGITS for ch in raw):
            return raw  # 算用数字だけの並びは `_PHONE_RE` に任せる
        digits = re.sub(r"\D", "", raw.translate(_KANJI_DIGIT_TABLE))
        if 10 <= len(digits) <= 11:
            counts["phone"] += 1
            return MASK_PHONE
        return raw

    def _number12(m: re.Match[str]) -> str:
        counts["number"] += 1
        return MASK_NUMBER

    def _postal(m: re.Match[str]) -> str:
        counts["postal"] += 1
        return MASK_POSTAL

    def _address(m: re.Match[str]) -> str:
        counts["address"] += 1
        return MASK_ADDRESS

    def _name(m: re.Match[str]) -> str:
        group = next(g for g in ("a", "b", "c") if m.group(g) is not None)
        name = m.group(group)
        if any(fragment in name for fragment in _NOT_A_NAME_FRAGMENTS):
            return m.group(0)
        if group == "c" and _NOT_A_NAME_CHARS_BARE & set(name):
            return m.group(0)
        counts["name"] += 1
        start = m.start(group) - m.start()
        end = m.end(group) - m.start()
        whole = m.group(0)
        return whole[:start] + MASK_NAME + whole[end:]

    t = _OBFUSCATED_EMAIL_RE.sub(_email, t)
    t = _EMAIL_RE.sub(_email, t)
    t = _CARD_RE.sub(_card, t)
    t = _KANJI_PHONE_RE.sub(_kanji_phone, t)
    t = _PHONE_RE.sub(_phone, t)
    t = _NUMBER12_RE.sub(_number12, t)
    t = _POSTAL_RE.sub(_postal, t)
    t = _ADDRESS_RE.sub(_address, t)
    t = _CITY_ADDRESS_RE.sub(_address, t)
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


def sanitize_text_counted(text: str, max_len: int) -> tuple[str, int]:
    """`sanitize_text` と同じ処理で、取り除いた HTML・URL・Markdown のリンク／画像の個数も返す。

    個数は、画像・リンク・URL・タグの一致数に、単独の `<` `>` があれば 1 を足した値（ガードの
    発動ログ用。G-22）。制御文字の除去は数えない。
    """
    removed = 0

    def _drop(pattern: re.Pattern[str], replacement: str, value: str) -> str:
        nonlocal removed
        result, n = pattern.subn(replacement, value)
        removed += n
        return result

    t = _drop(_MD_IMAGE_RE, "", text)
    t = _drop(_MD_LINK_RE, r"\1", t)
    t = _drop(_URL_RE, "", t)
    t = _drop(_TAG_RE, "", t)
    if "<" in t or ">" in t:
        removed += 1
    t = t.replace("<", "").replace(">", "")
    out: list[str] = []
    for ch in t.replace("\t", " "):
        if ch in "\u2028\u2029":  # 行・段落の区切り文字は改行にする
            out.append("\n")
        elif ch == "\n" or unicodedata.category(ch) not in _REMOVED_CATEGORIES:
            out.append(ch)
    return "".join(out).strip()[:max_len], removed


def sanitize_text(text: str, max_len: int) -> str:
    """手順 1・9: HTML のタグ、URL、Markdown のリンク・画像、制御文字を取り除き、`max_len` に切る。

    リンクは見出しの文字だけ残す。通常の日本語・記号（「！」「、」）は変えない。
    """
    return sanitize_text_counted(text, max_len)[0]


def _squash(text: str) -> str:
    """表記ゆれを除いた比較用の文字列。

    NFKC（全角半角）・大文字小文字をそろえたうえで、空白・句読点・記号・制御文字（ゼロ幅を含む）・
    結合文字・長音「ー」を取り除く。`C N R Y - 5d…`・`CNRYー5d…`・`CNRY…5d…` を同じ並びにする。
    """
    folded = unicodedata.normalize("NFKC", text).casefold()
    return "".join(
        ch
        for ch in folded
        if ch != "ー" and unicodedata.category(ch)[0] not in ("Z", "P", "S", "C", "M")
    )


def contains_canary(text: str, canary: str) -> bool:
    """手順 2: canary（固定指示の合言葉）が含まれるか。

    表記ゆれに強くする（G-20）。空白・記号・長音・全角半角を取り除いて小文字にしてから比べ、
    逆順（`17b8e2d5-YRNC`）も見る。
    """
    needle = _squash(canary)
    if not needle:
        return False
    haystack = _squash(text)
    return needle in haystack or needle[::-1] in haystack


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


# ── 約束の言葉（G-20）──
# 数字を含まない約束（「今なら全品送料無料」「クーポンコード WELCOME で割引」）は、金額・数字の
# 照合では止まらない。応答に約束の言葉があり、その語が LLM に渡した資料（FAQ・特商法・商品情報）に
# 無いときは、サイトの約束ではないものとして止める。資料にある語（FAQ の「送料無料」の条件など）は
# 止めない。
# 比較は NFKC・小文字化・空白除去のあとの部分一致。`OFF` だけは英字の語として単独のときに限る
# （`coffee` などに当てない）。`ポイント` は「ポイント還元・5 ポイント・ポイントが貯まる」のように
# 特典の意味で使う形に限る（「着回しのポイント」の意味の語に当てない）
_PROMISE_TERMS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("送料無料", re.compile("送料無料")),
    ("無料", re.compile("無料")),
    ("クーポン", re.compile("クーポン")),
    ("割引", re.compile("割引")),
    ("値引", re.compile("値引")),
    ("半額", re.compile("半額")),
    ("セール", re.compile("セール")),
    ("特典", re.compile("特典")),
    ("還元", re.compile("還元")),
    ("返金", re.compile("返金")),
    ("保証", re.compile("保証")),
    ("キャッシュバック", re.compile("キャッシュバック")),
    ("プレゼント", re.compile("プレゼント")),
    (
        "ポイント",
        re.compile(
            r"ポイント(?:還元|付与|進呈|アップ|バック|倍|プレゼント|\d|がたま|が貯|がつ|が付|が使|を使|を貯|を利用)"
            r"|(?:\d|倍|全品|今なら)ポイント"
        ),
    ),
)
_OFF_RE = re.compile(r"(?<![a-z])off(?![a-z])")


def _promise_fold(text: str) -> tuple[str, str]:
    """約束の語の照合用に畳んだ 2 つの文字列。(空白を除いたもの, 空白を残したもの)。"""
    spaced = unicodedata.normalize("NFKC", text).casefold()
    return "".join(spaced.split()), spaced


def _promise_words(text: str) -> set[str]:
    squeezed, spaced = _promise_fold(text)
    found = {label for label, pattern in _PROMISE_TERMS if pattern.search(squeezed)}
    if _OFF_RE.search(spaced):
        found.add("OFF")
    return found


def find_unsupported_promises(text: str, sources: Iterable[str]) -> list[str]:
    """応答 `text` にある約束の言葉のうち、資料 `sources` に無いもの（出現順ではなく名前順）。

    `sources` は LLM に渡した資料（FAQ・特商法・商品情報）。利用者の質問は資料に含めない
    （質問の言葉を応答がなぞるだけでは、サイトの約束にならない）。
    """
    wanted = _promise_words(text)
    if not wanted:
        return []
    supported: set[str] = set()
    for source in sources:
        supported |= _promise_words(source)
    unsupported = wanted - supported
    if "送料無料" in unsupported:
        unsupported.discard("無料")  # 「送料無料」の中の「無料」は別に数えない
    return sorted(unsupported)


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


# 在庫の数・残りの数（「残り3点」「在庫は5点」など）。資料には在庫の有無しか無い
_STOCK_COUNT_RE = re.compile(
    r"(?:残り|在庫)[^。\d]{0,6}\d+\s*[点個枚着]|\d+\s*[点個枚着]\s*(?:のみ|だけ|残)", re.ASCII
)


@dataclass(frozen=True)
class ProductContext:
    """文脈の商品（`product_info` の照合先）。`facts` は LLM に渡した資料と同じ文字列。"""

    id: int
    price_incl_tax: int
    facts: str


def product_info_is_grounded(message: str, ctx: ProductContext, question: str) -> bool:
    """`product_info` の本文が資料の範囲に収まっているか。

    金額は DB の税込価格だけ許す（利用者の質問にある金額は許さない）。2 桁以上の数値は資料か質問に
    あるものだけ。在庫の数・残りは書かせない。
    """
    if find_foreign_amounts(message, {ctx.price_incl_tax}):
        return False
    if numbers_not_in_sources(message, [ctx.facts, question]):
        return False
    return _STOCK_COUNT_RE.search(unicodedata.normalize("NFKC", message)) is None


@dataclass(frozen=True)
class Finalized:
    """`guards` は、動いたガードの種類 → 件数（G-22。本文は含めない）。

    種類: `html_url`（除去した HTML・URL・リンク）／`pii_output`（出力のマスク）／`canary`／
    `amount`（金額の置き換え）／`promise`（資料に無い約束の置き換え）／`product_info`
    （資料の範囲外の product_info を定型文にした）／`faq_number`（FAQ の数値不一致で範囲外にした）。
    """

    reply: ChatReplyOut
    canary_leak: bool
    dropped_ids: int
    guards: Mapping[str, int] = field(default_factory=dict)


def _clean_counted(text: str, max_len: int) -> tuple[str, int, int]:
    """サニタイズ → 個人情報のマスク（LLM が個人情報を創作・復元する経路を作らない）。

    (整えた文字列, 除去した HTML・URL の個数, マスクした個人情報の個数)。
    """
    sanitized, removed = sanitize_text_counted(text, max_len)
    masked = mask_pii(sanitized)
    return masked.text[:max_len], removed, sum(masked.counts.values())


def _clean(text: str, max_len: int) -> str:
    return _clean_counted(text, max_len)[0]


def finalize_reply(
    output: ChatLLMOutput,
    *,
    question: str,
    sources: Sequence[str],
    canary: str,
    pool_ids: Collection[int],
    cards: Mapping[int, ProductSummary],
    context: ProductContext | None = None,
    promise_sources: Sequence[str] = (),
) -> Finalized:
    """手順 1〜9 を通して、画面に出す応答を組み立てる。

    `cards` は、DB から再取得した公開商品（名称・税込価格・画像・在庫切れの出どころ）。
    ここに無い ID は捨てる。価格・在庫は LLM の文章を使わず、カードの DB 値だけで示す。
    `context` は文脈の商品。`product_info` は、これがあるときだけ通す（無ければ範囲外）。
    `promise_sources` は、約束の言葉の照合先に足す資料（商品の一覧・設定の値など、LLM に渡した
    ほかの資料。G-20）。`sources`（FAQ・特商法）と文脈の商品の資料も照合先になる。
    """
    intent: Intent = output.intent
    guards: Counter[str] = Counter()
    message, removed, masked_n = _clean_counted(output.message, MESSAGE_MAX_CHARS)
    guards["html_url"] += removed
    guards["pii_output"] += masked_n
    promise_pool = [*sources, *promise_sources, *([context.facts] if context is not None else [])]

    # 手順 5・6 の対象（recommend のときだけ）
    unique_ids = list(dict.fromkeys(i.product_id for i in output.items))
    in_pool = [i for i in unique_ids if i in pool_ids]
    candidates = validate_items(output.items, pool_ids) if intent == "recommend" else []
    # 理由は、`validate_items` が整えたものでなく LLM が書いた元から整える（除去数を数えるため）
    raw_reasons: dict[int, str] = {}
    for item in output.items:
        raw_reasons.setdefault(item.product_id, item.reason)
    reasons: dict[int, str] = {}
    for c in candidates:
        reason, removed, masked_n = _clean_counted(raw_reasons[c.product_id], REASON_MAX_CHARS)
        reasons[c.product_id] = reason
        guards["html_url"] += removed
        guards["pii_output"] += masked_n

    # 手順 2: canary（message・reason のどれにあっても範囲外にする）
    canary_leak = contains_canary(message, canary) or any(
        contains_canary(r, canary) for r in reasons.values()
    )
    if canary_leak:
        intent = "out_of_scope"
        guards["canary"] += 1

    # 手順 3: 金額らしき表記（利用者の質問にある数値だけ許す）と、資料に無い約束の言葉（G-20）
    if intent in ("recommend", "clarify"):
        allowed = {int(n) for n in digit_strings(question)}
        amounts = find_foreign_amounts(message, allowed)
        for r in reasons.values():
            amounts += find_foreign_amounts(r, allowed)
        promises = find_unsupported_promises(" ".join([message, *reasons.values()]), promise_pool)
        if amounts or promises:
            message = AMOUNT_CHECK_FAILED_MESSAGE
            reasons = {pid: "" for pid in reasons}
            guards["amount"] += len(amounts)
            guards["promise"] += len(promises)

    # 手順 3b: product_info は文脈の商品があるときだけ。本文は資料の範囲に収まるものだけ
    if intent == "product_info":
        if context is None or not message:
            intent = "out_of_scope"
        elif not product_info_is_grounded(message, context, question):
            message = PRODUCT_INFO_FALLBACK_MESSAGE
            guards["product_info"] += 1
        elif promises := find_unsupported_promises(message, promise_pool):
            message = PRODUCT_INFO_FALLBACK_MESSAGE
            guards["promise"] += len(promises)

    # 手順 4: FAQ の回答の数値は、資料か質問にあるものだけ。約束の言葉も資料にあるものだけ
    if intent == "faq":
        if numbers_not_in_sources(message, [*sources, question]):
            intent = "out_of_scope"
            guards["faq_number"] += 1
        elif promises := find_unsupported_promises(message, promise_pool):
            intent = "out_of_scope"
            guards["promise"] += len(promises)

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
    elif intent == "product_info" and context is not None:
        reply_sources = [ChatSourceOut(title="商品ページ", href=f"/products/{context.id}")]

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
        guards={kind: n for kind, n in guards.items() if n > 0},
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
    "PRODUCT_INFO_FALLBACK_MESSAGE",
    "Finalized",
    "MaskResult",
    "ProductContext",
    "contains_canary",
    "digit_strings",
    "finalize_reply",
    "find_foreign_amounts",
    "find_unsupported_promises",
    "jst_day_start_utc",
    "luhn_valid",
    "mask_pii",
    "normalize_text",
    "numbers_not_in_sources",
    "product_info_is_grounded",
    "sanitize_text",
    "sanitize_text_counted",
    "validate_items",
]
