"""UT-AI-10〜16: LLM アダプタ・設定・秘密マスク・ネットワーク遮断。

P2 追補d テスト設計 5.1。OpenAI は実際に呼ばない（SDK のクライアントをモックに差し替える）。
UT-AI-10 select_adapter／11 StubAdapter／12 OpenAIAdapter の呼び出し引数／13 例外の変換／
14 SecretMaskFilter／15 Settings／16 キー無しの経路とネットワーク遮断
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import os
import socket
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx2
import openai
import pytest
from pydantic import ValidationError

from app.adapters.llm import (
    CatalogEntry,
    DisabledAdapter,
    LLMError,
    LLMMessage,
    LLMRequest,
    OpenAIAdapter,
    StubAdapter,
    select_adapter,
)
from app.core.config import Settings
from app.core.logging import MASK, SecretMaskFilter
from app.schemas.chat import ChatLLMOutput
from app.services import chat_prompt

API_ROOT = Path(__file__).resolve().parents[2]


def settings(**kwargs: Any) -> Settings:
    """`.env` と環境変数を読まない設定（init 引数が最優先）。"""
    return Settings(_env_file=None, **kwargs)  # type: ignore[call-arg]


# ── UT-AI-10 select_adapter ──


def _expected_provider(provider: str, has_key: bool, env: str, enabled: bool) -> str:
    """8.2 の表を、実装とは別に書き下したもの。"""
    if not enabled:
        return "none"
    if provider == "openai":
        return "openai" if has_key else "none"
    if provider == "stub":
        return "none" if env == "production" else "stub"
    if has_key:  # auto
        return "openai"
    return "none" if env == "production" else "stub"


@pytest.mark.parametrize(
    ("provider", "has_key", "env", "enabled"),
    list(
        itertools.product(
            ["auto", "openai", "stub"],
            [True, False],
            ["development", "test", "production"],
            [True, False],
        )
    ),
)
def test_ut_ai_10_select_adapter_all_36_combinations(
    provider: str, has_key: bool, env: str, enabled: bool
) -> None:
    adapter = select_adapter(
        settings(
            LLM_PROVIDER=provider,
            OPENAI_API_KEY="dummy-key-for-test" if has_key else "",  # pragma: allowlist secret
            APP_ENV=env,
            CHAT_ENABLED=enabled,
        )
    )
    expected = _expected_provider(provider, has_key, env, enabled)
    assert adapter.name == expected
    assert adapter.available is (expected != "none")
    assert {"openai": OpenAIAdapter, "stub": StubAdapter, "none": DisabledAdapter}[
        expected
    ] is type(adapter)


def test_ut_ai_10_openai_adapter_is_reused_for_the_same_settings() -> None:
    s = settings(OPENAI_API_KEY="dummy-key-for-test")
    assert select_adapter(s) is select_adapter(s)


# ── UT-AI-11 StubAdapter ──


def _entry(pid: int, in_stock: bool = True) -> CatalogEntry:
    return CatalogEntry(
        id=pid,
        name=f"商品{pid}",
        gender="women",
        kind="tops",
        price_incl_tax=1490,
        colors=("ホワイト",),
        sizes=("M",),
        in_stock=in_stock,
        material="綿",
    )


def _request(question: str, *, context: int | None = None, catalog=None) -> LLMRequest:
    catalog = (
        catalog
        if catalog is not None
        else (_entry(1, False), _entry(2), _entry(3), _entry(4), _entry(5))
    )
    return LLMRequest(
        instructions=chat_prompt.SYSTEM_PROMPT,
        input=(LLMMessage("user", question),),
        question=question,
        catalog=tuple(catalog),
        context_product_id=context,
        safety_identifier="a" * 32,
    )


@pytest.mark.parametrize("production", [False, True])
async def test_ut_ai_11_stub_ok_routes_by_keyword(production: bool) -> None:
    stub = StubAdapter("ok", ignore_scenario=production)

    faq = (await stub.generate(_request("送料はいくらですか"))).output
    assert faq.intent == "faq" and faq.items == []
    assert "（デモ応答）" in faq.message

    rec = (await stub.generate(_request("黒のパーカーが欲しいです"))).output
    assert rec.intent == "recommend"
    # 候補プールの先頭から、在庫のある商品を最大 3 件（在庫なしの 1 は飛ばす）
    assert [i.product_id for i in rec.items] == [2, 3, 4]
    assert {i.reason for i in rec.items} == {"デモ応答の例です。"}

    ctx = (await stub.generate(_request("これは？", context=3))).output
    assert ctx.intent == "recommend"

    oos = (await stub.generate(_request("今日の天気は"))).output
    assert oos.intent == "out_of_scope" and oos.items == []

    for output in (faq, rec, oos):  # ok の応答の文章に数字は含めない
        assert not any(ch.isdigit() for ch in output.message)


@pytest.mark.parametrize("production", [False, True])
async def test_ut_ai_11_stub_scenarios_run_only_outside_production(production: bool) -> None:
    async def run(scenario: str):
        return await StubAdapter(scenario, ignore_scenario=production).generate(
            _request("おすすめを教えて")
        )

    if production:
        # 本番ではシナリオを無視して ok と同じ
        for scenario in ("unknown_id", "price_tamper", "html", "canary", "timeout", "error"):
            result = await run(scenario)
            assert result.output.intent == "recommend"
            assert [i.product_id for i in result.output.items] == [2, 3, 4]
        return

    unknown = (await run("unknown_id")).output
    assert [i.product_id for i in unknown.items] == [999999999, 2]
    out_of_pool = (await run("out_of_pool")).output
    assert [i.product_id for i in out_of_pool.items] == [6]  # プール（1〜5）に無い ID
    assert "1,990" in (await run("price_tamper")).output.message
    faq_tamper = (await run("faq_number_tamper")).output
    assert faq_tamper.intent == "faq" and "999" in faq_tamper.message
    html = (await run("html")).output.message
    assert "<img" in html and "http://evil.example" in html
    assert chat_prompt.PROMPT_CANARY in (await run("canary")).output.message
    for scenario, kind in (("timeout", "timeout"), ("error", "upstream"), ("refusal", "refusal")):
        with pytest.raises(LLMError) as exc:
            await run(scenario)
        assert exc.value.kind == kind


async def test_ut_ai_11_stub_does_not_touch_the_network_or_sdk() -> None:
    # socket は conftest の no_external_network で遮断済み。SDK の読み込みは UT-AI-16 で確認する
    result = await StubAdapter().generate(_request("送料は？"))
    assert result.model == "stub" and result.input_tokens is None


# ── UT-AI-12 / 13 OpenAIAdapter（SDK をモック）──


class FakeClient:
    """`AsyncOpenAI` の代わり。`with_options(...).responses.parse(...)` の引数を記録する。"""

    def __init__(self, response: Any = None, raises: BaseException | None = None) -> None:
        self.response = response
        self.raises = raises
        self.with_options_kwargs: dict[str, Any] = {}
        self.parse_kwargs: dict[str, Any] = {}
        self.responses = SimpleNamespace(parse=self._parse)

    def with_options(self, **kwargs: Any) -> FakeClient:
        self.with_options_kwargs = kwargs
        return self

    async def _parse(self, **kwargs: Any) -> Any:
        self.parse_kwargs = kwargs
        if self.raises is not None:
            raise self.raises
        return self.response


def _ok_response(**over: Any) -> Any:
    fields: dict[str, Any] = {
        "status": "completed",
        "output": [],
        "output_parsed": ChatLLMOutput(
            intent="faq", message="よくある質問をご覧ください。", items=[]
        ),
        "usage": SimpleNamespace(input_tokens=321, output_tokens=54),
    }
    fields.update(over)
    return SimpleNamespace(**fields)


def _adapter(client: FakeClient, **over: Any) -> OpenAIAdapter:
    kwargs: dict[str, Any] = {
        "api_key": "dummy-key-for-test",
        "model": "gpt-6-luna",
        "reasoning_effort": "none",
        "timeout_seconds": 10,
        "max_output_tokens": 600,
        "client_factory": lambda: client,
    }
    kwargs.update(over)
    return OpenAIAdapter(**kwargs)


async def test_ut_ai_12_openai_call_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient(_ok_response())
    waits: list[float] = []
    real_wait_for = asyncio.wait_for

    async def recording_wait_for(aw: Any, timeout: float | None = None) -> Any:
        waits.append(timeout)  # type: ignore[arg-type]
        return await real_wait_for(aw, timeout)

    monkeypatch.setattr(asyncio, "wait_for", recording_wait_for)

    question = "黒のパーカーが欲しいです"
    request = chat_prompt.build_llm_request(
        faq_body="FAQ",
        tokushoho_body="特商法",
        pool=chat_prompt.CandidatePool(entries=(_entry(2),), context=None),
        history=[],
        question=question,
        safety_identifier="0123456789abcdef0123456789abcdef",  # pragma: allowlist secret
    )
    result = await _adapter(client).generate(request)

    kw = client.parse_kwargs
    assert kw["model"] == "gpt-6-luna"
    assert kw["instructions"] == chat_prompt.SYSTEM_PROMPT
    assert question not in kw["instructions"]
    assert [m["role"] for m in kw["input"]] == ["developer", "user"]
    assert kw["input"][-1]["content"] == f"<user_message>{question}</user_message>"
    assert kw["text_format"] is ChatLLMOutput
    assert kw["max_output_tokens"] == 600
    assert kw["reasoning"] == {"effort": "none"}
    assert kw["store"] is False
    assert kw["safety_identifier"] == "0123456789abcdef0123456789abcdef"
    assert len(kw["safety_identifier"]) == 32
    assert "temperature" not in kw
    assert client.with_options_kwargs == {"timeout": 10, "max_retries": 0}
    assert waits == [12]  # SDK の外側でも 10 + 2 秒で打ち切る
    assert (result.input_tokens, result.output_tokens) == (321, 54)
    assert result.output.intent == "faq" and result.model == "gpt-6-luna"


async def test_ut_ai_12_client_is_created_lazily_and_once() -> None:
    created: list[FakeClient] = []

    def factory() -> FakeClient:
        created.append(FakeClient(_ok_response()))
        return created[-1]

    adapter = _adapter(FakeClient(), client_factory=factory)
    assert created == []  # 初回の呼び出しまで作らない
    request = _request("送料は？")
    await adapter.generate(request)
    await adapter.generate(request)
    assert len(created) == 1


def _http_error(cls: type[openai.APIStatusError], status: int) -> openai.APIStatusError:
    req = httpx2.Request("POST", "https://api.openai.com/v1/responses")
    return cls("boom", response=httpx2.Response(status, request=req), body=None)


@pytest.mark.parametrize(
    ("raises", "kind"),
    [
        (openai.APITimeoutError(httpx2.Request("POST", "https://x.example")), "timeout"),
        (TimeoutError(), "timeout"),
        (
            openai.APIConnectionError(request=httpx2.Request("POST", "https://x.example")),
            "upstream",
        ),
        (_http_error(openai.RateLimitError, 429), "upstream"),
        (_http_error(openai.AuthenticationError, 401), "upstream"),
        (_http_error(openai.InternalServerError, 500), "upstream"),
        (_http_error(openai.BadRequestError, 400), "upstream"),
        (ValueError("bad json"), "invalid_output"),
    ],
)
async def test_ut_ai_13_exceptions_are_converted(raises: BaseException, kind: str) -> None:
    adapter = _adapter(FakeClient(raises=raises))
    with pytest.raises(LLMError) as exc:
        await adapter.generate(_request("送料は？"))
    assert exc.value.kind == kind
    assert not isinstance(exc.value, openai.OpenAIError)
    assert "boom" not in str(exc.value)  # SDK のメッセージを持ち回らない


@pytest.mark.parametrize(
    ("response", "kind"),
    [
        (_ok_response(status="incomplete"), "incomplete"),
        (_ok_response(output_parsed=None), "invalid_output"),
        (
            _ok_response(
                output_parsed=None,
                output=[SimpleNamespace(type="message", content=[SimpleNamespace(type="refusal")])],
            ),
            "refusal",
        ),
        (_ok_response(output=[SimpleNamespace(type="refusal")]), "refusal"),
    ],
)
async def test_ut_ai_13_unusable_responses_are_converted(response: Any, kind: str) -> None:
    with pytest.raises(LLMError) as exc:
        await _adapter(FakeClient(response)).generate(_request("送料は？"))
    assert exc.value.kind == kind


async def test_ut_ai_13_outer_wait_for_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    class Slow(FakeClient):
        async def _parse(self, **kwargs: Any) -> Any:
            await asyncio.sleep(5)

    client = Slow()
    client.responses = SimpleNamespace(parse=client._parse)
    with pytest.raises(LLMError) as exc:
        await _adapter(client, timeout_seconds=1).generate(_request("送料は？"))  # 1 + 2 秒
    assert exc.value.kind == "timeout"


async def test_ut_ai_13_missing_usage_is_none() -> None:
    result = await _adapter(FakeClient(_ok_response(usage=None))).generate(_request("送料は？"))
    assert result.input_tokens is None and result.output_tokens is None


# ── UT-AI-14 SecretMaskFilter ──


def _emit(f: SecretMaskFilter, message: str, *args: object) -> str:
    logger = logging.getLogger("test.mask.ai")
    record = logger.makeRecord("test.mask.ai", logging.INFO, __file__, 1, message, args, None)
    assert f.filter(record) is True
    return record.getMessage()


def test_ut_ai_14_masks_openai_key_shape_and_actual_value() -> None:
    key_like = "sk-" + "proj-abcdefghijklmnopqrstuvwxyz0123456789"  # gitleaks:allow  # noqa: E501
    out = _emit(SecretMaskFilter(), "key=%s done", key_like)
    assert key_like not in out
    assert f"sk-{MASK}" in out and "done" in out

    actual = "dummy-actual-key-0123456789"  # 実在しない値
    out = _emit(SecretMaskFilter(extra_secrets=[actual]), f"value={actual}")
    assert actual not in out and MASK in out


def test_ut_ai_14_short_sk_strings_are_not_masked_and_args_keep_structure() -> None:
    f = SecretMaskFilter()
    assert _emit(f, "id=sk-1 and sk-abc") == "id=sk-1 and sk-abc"
    logger = logging.getLogger("test.mask.ai")
    record = logger.makeRecord("t", logging.INFO, __file__, 1, "%s %d", ("sk-1", 5), None)
    f.filter(record)
    assert record.args == ("sk-1", 5)


# ── UT-AI-15 Settings ──


def test_ut_ai_15_defaults() -> None:
    s = settings()
    assert s.OPENAI_MODEL == "gpt-6-luna"
    assert s.OPENAI_REASONING_EFFORT == "none"
    assert s.OPENAI_TIMEOUT_SECONDS == 10
    assert s.OPENAI_MAX_OUTPUT_TOKENS == 600
    assert s.CHAT_DAILY_LIMIT == 300
    assert s.CHAT_IP_LIMIT_PER_HOUR == 30
    assert s.CHAT_TURN_LIMIT == 10
    assert s.LLM_PROVIDER == "auto"
    assert s.LLM_STUB_SCENARIO == "ok"
    assert s.CHAT_ENABLED is True
    assert s.OPENAI_API_KEY == ""
    assert "OPENAI_API_KEY" not in repr(s)


@pytest.mark.parametrize(
    ("field", "value", "ok"),
    [
        ("OPENAI_TIMEOUT_SECONDS", 0, False),
        ("OPENAI_TIMEOUT_SECONDS", 1, True),
        ("OPENAI_TIMEOUT_SECONDS", 60, True),
        ("OPENAI_TIMEOUT_SECONDS", 61, False),
        ("OPENAI_TIMEOUT_SECONDS", "x", False),
        ("OPENAI_MAX_OUTPUT_TOKENS", 15, False),
        ("OPENAI_MAX_OUTPUT_TOKENS", 16, True),
        ("OPENAI_MAX_OUTPUT_TOKENS", 4000, True),
        ("OPENAI_MAX_OUTPUT_TOKENS", 4001, False),
        ("CHAT_DAILY_LIMIT", 0, False),
        ("CHAT_DAILY_LIMIT", 1, True),
        ("CHAT_IP_LIMIT_PER_HOUR", 0, False),
        ("CHAT_IP_LIMIT_PER_HOUR", 1, True),
        ("CHAT_TURN_LIMIT", 0, False),
        ("CHAT_TURN_LIMIT", 1, True),
        ("CHAT_TURN_LIMIT", 50, True),
        ("CHAT_TURN_LIMIT", 51, False),
        ("LLM_PROVIDER", "foo", False),
        ("LLM_PROVIDER", "stub", True),
        ("OPENAI_REASONING_EFFORT", "max", False),
        ("OPENAI_REASONING_EFFORT", "high", True),
        ("LLM_STUB_SCENARIO", "nope", False),
    ],
)
def test_ut_ai_15_boundaries(field: str, value: object, ok: bool) -> None:
    if ok:
        assert getattr(settings(**{field: value}), field) == value
    else:
        with pytest.raises(ValidationError):
            settings(**{field: value})


# ── UT-AI-16 キー無しの経路・ネットワーク遮断 ──


def test_ut_ai_16_no_external_network_guard_blocks_non_loopback() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        with pytest.raises(ConnectionRefusedError, match="外部接続は禁止"):
            s.connect(("203.0.113.9", 443))  # TEST-NET-3（実在しない）
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        # ループバックは遮断しない（接続先が無いので OS が拒否する）。遮断の例外ではない
        try:
            s.connect(("127.0.0.1", 9))
        except OSError as exc:
            assert "外部接続は禁止" not in str(exc)


_NO_KEY_SCRIPT = """
import asyncio, os, socket, sys

for key in list(os.environ):
    if key.startswith(("OPENAI", "CHAT_", "LLM_")):
        del os.environ[key]
os.environ.update(
    APP_ENV="test",
    DATABASE_URL="sqlite+aiosqlite:///:memory:",
    INTERNAL_TOKEN="test-internal-token-0123456789",
    CORS_ALLOW_ORIGIN="http://localhost:3000",
)

def _deny(self, address):
    raise AssertionError(f"外部接続の試み: {address}")

socket.socket.connect = _deny

import httpx
from app.core.db import get_engine
from app.main import create_app
from app.models import Base


async def main():
    app = create_app()
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        headers = {"X-Internal-Token": "test-internal-token-0123456789"}
        status = await client.get("/api/v1/chat/status", headers=headers)
        res = await client.post(
            "/api/v1/chat/messages", json={"message": "送料は？"}, headers=headers
        )
    print(status.json()["provider"], res.status_code, res.json()["reply"]["intent"])
    print("openai" in sys.modules)

asyncio.run(main())
"""


def test_ut_ai_16_without_key_stub_answers_and_sdk_is_not_loaded() -> None:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("OPENAI", "CHAT_", "LLM_"))}
    proc = subprocess.run(
        [sys.executable, "-c", _NO_KEY_SCRIPT],
        cwd=API_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    lines = proc.stdout.strip().splitlines()
    assert lines[-2] == "stub 200 faq", proc.stdout + proc.stderr
    assert lines[-1] == "False", "openai が import されている"
