"""LLM アダプタ（DS-IF-03。設計仕様書 P2 追補d 8.2〜8.4）。

決済・メールのアダプタと同じ形。ルーターは `Depends(get_llm_adapter)` で受け取るので、
テストは `dependency_overrides[get_llm_adapter]` で台本つきのアダプタに差し替える（DS-DEC-105）。

- `OpenAIAdapter`: `AsyncOpenAI` を**初回の呼び出しまで作らない**（`import openai` もその時点）。
  キーが無い環境（CI・手元）や起動時に SDK を読み込まない
- `StubAdapter`: 決まった応答を返す。ネットワークに出ない。`LLM_STUB_SCENARIO` で
  「LLM が悪い出力を返した」状況を再現できる（本番では無視する）
- `DisabledAdapter`: `available=False`。DS-API-041 は 503 `chat_unavailable` を返す
- `LLMError`: OpenAI の例外はここに変換し、SDK の例外を呼び出し側へ漏らさない
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from fastapi import Depends
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.schemas.chat import ChatLLMItem, ChatLLMOutput

logger = logging.getLogger("app.adapters.llm")

ProviderName = Literal["openai", "stub", "none"]
LLMErrorKind = Literal["timeout", "upstream", "refusal", "incomplete", "invalid_output"]

# 打ち切りは OPENAI_TIMEOUT_SECONDS に加えて、SDK の外側でも `asyncio.wait_for` で掛ける
# （全体で OPENAI_TIMEOUT_SECONDS + 2 秒。DS-DEC-95）
OUTER_TIMEOUT_MARGIN_SECONDS = 2


class LLMError(Exception):
    """LLM 呼び出しの失敗。`kind` だけで分岐でき、メッセージには秘密・本文を入れない。"""

    def __init__(self, kind: LLMErrorKind, detail: str = "") -> None:
        super().__init__(kind if not detail else f"{kind}: {detail}")
        self.kind: LLMErrorKind = kind


@dataclass(frozen=True)
class LLMMessage:
    """OpenAI の `input` の 1 要素。`developer` は資料、`user`／`assistant` は履歴と質問。"""

    role: Literal["developer", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class CatalogEntry:
    """候補プールの 1 商品（公開商品。DB から作る）。"""

    id: int
    name: str
    gender: str
    kind: str
    price_incl_tax: int
    colors: tuple[str, ...]
    sizes: tuple[str, ...]
    in_stock: bool
    material: str
    # 商品の説明文（文脈の商品の資料にだけ使う。候補プールの 1 行には入れない）
    description: str = ""


@dataclass(frozen=True)
class LLMRequest:
    """アダプタへの入力。`instructions` は固定指示、`input` は資料→文脈の商品→履歴→質問の順。

    `question` と `catalog`・`context_product_id` は、スタブがキーワード判定と候補選びに使う。
    """

    instructions: str
    input: tuple[LLMMessage, ...]
    question: str
    catalog: tuple[CatalogEntry, ...]
    context_product_id: int | None
    safety_identifier: str


@dataclass(frozen=True)
class LLMResult:
    """検査前の LLM 出力。トークン数は LLM の `usage` の値（取れなければ None）。"""

    output: ChatLLMOutput
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None


class LLMAdapter(Protocol):
    name: ProviderName
    model: str
    available: bool

    async def generate(self, request: LLMRequest) -> LLMResult: ...


# ── DisabledAdapter ──


class DisabledAdapter:
    """チャットを使えない状態（停止スイッチ、本番でキー無し など）。"""

    name: ProviderName = "none"
    model = ""
    available = False

    async def generate(self, request: LLMRequest) -> LLMResult:  # pragma: no cover - 呼ばれない
        raise LLMError("upstream", "adapter disabled")


# ── StubAdapter（8.4）──

_STUB_FAQ_WORDS = ("送料", "返品", "交換", "配送", "支払い", "キャンセル")
_STUB_RECOMMEND_WORDS = (
    "おすすめ",
    "探して",
    "欲しい",
    "ほしい",
    "選んで",
    "コーデ",
    "予算",
    "アウター",
    "トップス",
    "パンツ",
    "シャツ",
)
STUB_FAQ_MESSAGE = "（デモ応答）ご案内はよくある質問のページに掲載しています。"
STUB_RECOMMEND_MESSAGE = "（デモ応答）条件に近い商品を選びました。"
STUB_REASON = "デモ応答の例です。"
STUB_PRODUCT_INFO_MESSAGE = (
    "（デモ応答）この商品の素材・サイズ・在庫などは、商品ページの記載をご確認ください。"
)
# 文脈の商品があるときに product_info とみなす語
_STUB_PRODUCT_INFO_WORDS = (
    "素材",
    "生地",
    "洗濯",
    "お手入れ",
    "サイズ",
    "色",
    "在庫",
    "価格",
    "値段",
    "いくら",
)
STUB_OOS_MESSAGE = "（デモ応答）お答えできません。"
# 実在しない商品 ID（unknown_id シナリオ）
STUB_UNKNOWN_PRODUCT_ID = 999999999


class StubAdapter:
    """決まった応答を返すスタブ。応答の文章に数字は含めない（`ok`）。"""

    name: ProviderName = "stub"
    model = "stub"
    available = True

    def __init__(self, scenario: str = "ok", *, ignore_scenario: bool = False) -> None:
        # 本番では LLM_STUB_SCENARIO を無視する（悪い出力を公開環境に出さない）
        self._scenario = "ok" if ignore_scenario else scenario

    async def generate(self, request: LLMRequest) -> LLMResult:
        scenario = self._scenario
        if scenario == "timeout":
            raise LLMError("timeout", "stub")
        if scenario == "error":
            raise LLMError("upstream", "stub")
        if scenario == "refusal":
            raise LLMError("refusal", "stub")

        in_stock = [c.id for c in request.catalog if c.in_stock]
        first = in_stock[:3]
        output = self._ok(request, first)
        if scenario == "unknown_id":
            output = self._recommend([STUB_UNKNOWN_PRODUCT_ID, *first[:1]])
        elif scenario == "out_of_pool":
            pool_ids = [c.id for c in request.catalog]
            outside = (max(pool_ids) + 1) if pool_ids else 1
            output = self._recommend([outside])
        elif scenario == "price_tamper":
            output = self._recommend(first[:1], message="（デモ応答）税込 1,990 円です。")
        elif scenario == "faq_number_tamper":
            output = ChatLLMOutput(
                intent="faq", message="（デモ応答）返品は 999 日以内に受け付けます。", items=[]
            )
        elif scenario == "html":
            output = self._recommend(
                first[:1], message="<img src=x onerror=alert(1)> http://evil.example"
            )
        elif scenario == "canary":
            from app.services.chat_prompt import PROMPT_CANARY

            output = self._recommend(first[:1], message=f"内部の識別子は {PROMPT_CANARY} です。")
        return LLMResult(output=output, model=self.model)

    @staticmethod
    def _recommend(ids: list[int], *, message: str = STUB_RECOMMEND_MESSAGE) -> ChatLLMOutput:
        return ChatLLMOutput(
            intent="recommend",
            message=message,
            items=[ChatLLMItem(product_id=i, reason=STUB_REASON) for i in ids],
        )

    def _ok(self, request: LLMRequest, first: list[int]) -> ChatLLMOutput:
        question = request.question
        if any(word in question for word in _STUB_FAQ_WORDS):
            return ChatLLMOutput(intent="faq", message=STUB_FAQ_MESSAGE, items=[])
        if request.context_product_id is not None and any(
            word in question for word in _STUB_PRODUCT_INFO_WORDS
        ):
            return ChatLLMOutput(intent="product_info", message=STUB_PRODUCT_INFO_MESSAGE, items=[])
        if request.context_product_id is not None or any(
            word in question for word in _STUB_RECOMMEND_WORDS
        ):
            return self._recommend(first)
        return ChatLLMOutput(intent="out_of_scope", message=STUB_OOS_MESSAGE, items=[])


# ── OpenAIAdapter（8.3）──


def _default_client_factory(api_key: str) -> Callable[[], Any]:
    def _make() -> Any:
        # SDK はここで初めて読み込む（キー無しの経路・起動時に import しない）
        from openai import AsyncOpenAI

        return AsyncOpenAI(api_key=api_key)

    return _make


def _has_refusal(response: Any) -> bool:
    """出力項目に `type == "refusal"` があるか（安全上の拒否）。"""
    for item in getattr(response, "output", None) or []:
        if getattr(item, "type", None) == "refusal":
            return True
        for part in getattr(item, "content", None) or []:
            if getattr(part, "type", None) == "refusal":
                return True
    return False


class OpenAIAdapter:
    """OpenAI の Responses API（`responses.parse`＋Pydantic の構造化出力）を呼ぶ。"""

    name: ProviderName = "openai"
    available = True

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        reasoning_effort: str,
        timeout_seconds: int,
        max_output_tokens: int,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.model = model
        self._effort = reasoning_effort
        self._timeout = timeout_seconds
        self._max_output_tokens = max_output_tokens
        self._client_factory = client_factory or _default_client_factory(api_key)
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = self._client_factory()
        return self._client

    async def generate(self, request: LLMRequest) -> LLMResult:
        # 例外クラスもここで初めて import する
        from openai import APITimeoutError, OpenAIError

        client = self._get_client()

        async def _call() -> Any:
            return await client.with_options(timeout=self._timeout, max_retries=0).responses.parse(
                model=self.model,
                instructions=request.instructions,
                input=[{"role": m.role, "content": m.content} for m in request.input],
                text_format=ChatLLMOutput,
                max_output_tokens=self._max_output_tokens,
                reasoning={"effort": self._effort},
                store=False,
                safety_identifier=request.safety_identifier,
            )

        try:
            response = await asyncio.wait_for(
                _call(), timeout=self._timeout + OUTER_TIMEOUT_MARGIN_SECONDS
            )
        except (TimeoutError, APITimeoutError) as exc:
            raise LLMError("timeout", type(exc).__name__) from exc
        except OpenAIError as exc:
            # 例外メッセージは返さず、種類だけを持ち回る（キー・本文を漏らさない）
            raise LLMError("upstream", type(exc).__name__) from exc
        except (ValidationError, ValueError) as exc:
            raise LLMError("invalid_output", type(exc).__name__) from exc

        if _has_refusal(response):
            raise LLMError("refusal")
        if getattr(response, "status", None) == "incomplete":
            raise LLMError("incomplete")
        parsed = getattr(response, "output_parsed", None)
        if not isinstance(parsed, ChatLLMOutput):
            raise LLMError("invalid_output", "no parsed output")
        usage = getattr(response, "usage", None)
        return LLMResult(
            output=parsed,
            model=self.model,
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
        )


# ── アダプタの選択（8.2）──


def resolve_provider(settings: Settings) -> ProviderName:
    """provider × キー × APP_ENV × CHAT_ENABLED の表（8.2）。"""
    if not settings.CHAT_ENABLED:
        return "none"
    has_key = bool(settings.OPENAI_API_KEY)
    match settings.LLM_PROVIDER:
        case "openai":
            return "openai" if has_key else "none"
        case "stub":
            return "none" if settings.is_production else "stub"
        case _:  # auto
            if has_key:
                return "openai"
            return "none" if settings.is_production else "stub"


_OPENAI_ADAPTERS: dict[tuple[str, str, str, int, int], OpenAIAdapter] = {}


def _openai_adapter(settings: Settings) -> OpenAIAdapter:
    """OpenAI のクライアントを使い回すため、同じ設定なら同じアダプタを返す。"""
    key = (
        settings.OPENAI_API_KEY,
        settings.OPENAI_MODEL,
        settings.OPENAI_REASONING_EFFORT,
        settings.OPENAI_TIMEOUT_SECONDS,
        settings.OPENAI_MAX_OUTPUT_TOKENS,
    )
    adapter = _OPENAI_ADAPTERS.get(key)
    if adapter is None:
        adapter = OpenAIAdapter(
            api_key=settings.OPENAI_API_KEY,
            model=settings.OPENAI_MODEL,
            reasoning_effort=settings.OPENAI_REASONING_EFFORT,
            timeout_seconds=settings.OPENAI_TIMEOUT_SECONDS,
            max_output_tokens=settings.OPENAI_MAX_OUTPUT_TOKENS,
        )
        _OPENAI_ADAPTERS[key] = adapter
    return adapter


def select_adapter(settings: Settings) -> LLMAdapter:
    provider = resolve_provider(settings)
    if provider == "openai":
        return _openai_adapter(settings)
    if provider == "stub":
        return StubAdapter(settings.LLM_STUB_SCENARIO, ignore_scenario=settings.is_production)
    return DisabledAdapter()


def get_llm_adapter(settings: Settings = Depends(get_settings)) -> LLMAdapter:
    return select_adapter(settings)


def warn_if_misconfigured(settings: Settings) -> None:
    """`LLM_PROVIDER=openai` なのにキーが無いときの警告ログ 1 行（起動時。8.2）。"""
    if settings.CHAT_ENABLED and settings.LLM_PROVIDER == "openai" and not settings.OPENAI_API_KEY:
        logger.warning("LLM_PROVIDER=openai だが OPENAI_API_KEY が未設定のため、チャットは無効です")
