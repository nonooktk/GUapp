"""IT-029-01〜04・14・18・22〜28: DS-API-040・041 の流れ・入力・認証・マスク・応答の中身。

MySQL（guapp_test）＋ seed 必須。LLM は台本つきのアダプタ（実際の OpenAI は呼ばない）。
"""

from __future__ import annotations

import json
import logging

import pytest

from app.adapters.llm import StubAdapter
from app.services import chat_guard, chat_prompt
from tests.integration.chat_helpers import (
    HEADERS,
    MESSAGES_URL,
    STATUS_URL,
    ChatCtx,
    log_text,
    send,
    sha256_hex,
)
from tests.unit.scripted_llm import ScriptedLLMAdapter, fail, out


async def test_it_029_01_status_for_stub_and_openai_like(chat_ctx: ChatCtx) -> None:
    _, client = chat_ctx.build(StubAdapter())
    res = await client.get(STATUS_URL, headers=HEADERS)
    assert res.status_code == 200
    assert res.json() == {
        "available": True,
        "reason": None,
        "provider": "stub",
        "turns_limit": 10,
        "message_max_chars": 300,
    }

    _, client = chat_ctx.build(ScriptedLLMAdapter(name="openai"))
    res = await client.get(STATUS_URL, headers=HEADERS)
    assert res.json()["provider"] == "openai" and res.json()["available"] is True

    # DB に何も書かれない
    assert await chat_ctx.counts() == {"sessions": 0, "messages": 0, "user_messages": 0}


async def test_it_029_02_first_message_creates_session_and_returns_cards(
    chat_ctx: ChatCtx,
) -> None:
    ids = (await chat_ctx.published_ids())[:2]
    adapter = ScriptedLLMAdapter(
        out("recommend", "お選びしました。", ids=ids, reason="使いやすい。")
    )
    _, client = chat_ctx.build(adapter)

    res = await send(client, "黒のパーカーが欲しいです")
    assert res.status_code == 200, res.text
    body = res.json()
    token = body["chat_token"]
    assert isinstance(token, str) and len(token) == 43
    assert body["turns_used"] == 1 and body["turns_limit"] == 10 and body["notice"] is None
    reply = body["reply"]
    assert reply["intent"] == "recommend"
    assert [p["id"] for p in reply["products"]] == ids
    for card in reply["products"]:
        name, price = (
            await chat_ctx.rows(
                "SELECT name, price_incl_tax FROM products WHERE id=:i", i=card["id"]
            )
        )[0]
        assert card["name"] == name and card["price_incl_tax"] == price
        assert card["image_path"]
        assert card["sold_out"] is False
        assert card["reason"] == "使いやすい。"

    sessions = await chat_ctx.rows("SELECT token_hash, turns, handoff_at FROM chat_sessions")
    assert len(sessions) == 1
    token_hash, turns, handoff_at = sessions[0]
    assert turns == 1 and handoff_at is None
    assert token_hash == sha256_hex(token) and token_hash != token
    assert token not in json.dumps(sessions, default=str)

    messages = await chat_ctx.rows(
        "SELECT role, body_masked, product_ids, intent, input_tokens, output_tokens "
        "FROM chat_messages ORDER BY id"
    )
    assert [m[0] for m in messages] == ["user", "assistant"]
    assert messages[0][1] == "黒のパーカーが欲しいです"
    assert messages[0][3:] == (None, None, None)
    assert messages[1][1] == "お選びしました。"
    assert json.loads(messages[1][2]) == ids
    assert messages[1][3:] == ("recommend", 123, 45)
    # 内部の安全識別子は token_hash の先頭 32 文字
    assert adapter.requests[0].safety_identifier == token_hash[:32]


async def test_it_029_03_history_is_the_latest_six_messages_in_order(chat_ctx: ChatCtx) -> None:
    ids = (await chat_ctx.published_ids())[:1]
    adapter = ScriptedLLMAdapter(
        out("recommend", "回答1 http://evil.example", ids=ids),
        out("recommend", "回答2", ids=ids),
        out("recommend", "回答3", ids=ids),
        out("recommend", "回答4", ids=ids),
        out("recommend", "回答5", ids=ids),
    )
    _, client = chat_ctx.build(adapter)
    first = await send(client, "質問1")
    token = first.json()["chat_token"]
    for n in range(2, 5):
        res = await send(client, f"質問{n}", token=token)
        assert res.status_code == 200
        assert res.json()["chat_token"] is None
        assert res.json()["turns_used"] == n

    res = await send(client, "質問5", token=token)
    assert res.json()["turns_used"] == 5 and res.json()["chat_token"] is None
    request = adapter.requests[-1]
    history = request.input[1:-1]  # 資料と今回の質問を除く
    assert [m.role for m in history] == ["user", "assistant"] * 3
    assert [m.content for m in history] == ["質問2", "回答2", "質問3", "回答3", "質問4", "回答4"]
    # 1 回目の履歴は URL を除いた検査後の本文
    second = adapter.requests[1].input[1:-1]
    assert [m.content for m in second] == ["質問1", "回答1"]
    assert await chat_ctx.scalar("SELECT COUNT(*) FROM chat_sessions") == 1


@pytest.mark.parametrize("bad_token", ["abc", "!" * 43, "", "a" * 43, "A" * 44])
async def test_it_029_04_invalid_or_unknown_token_starts_a_new_session(
    chat_ctx: ChatCtx, bad_token: str
) -> None:
    adapter = ScriptedLLMAdapter(out("clarify", "条件を教えてください。"))
    _, client = chat_ctx.build(adapter)
    res = await send(client, "こんにちは", token=bad_token)
    assert res.status_code == 200, res.text
    new_token = res.json()["chat_token"]
    assert isinstance(new_token, str) and len(new_token) == 43 and new_token != bad_token
    assert res.json()["turns_used"] == 1
    assert await chat_ctx.scalar("SELECT COUNT(*) FROM chat_sessions") == 1


async def test_it_029_14_eleventh_message_is_409_turn_limit(chat_ctx: ChatCtx) -> None:
    adapter = ScriptedLLMAdapter(out("clarify", "条件を教えてください。"))
    _, client = chat_ctx.build(adapter)
    token = None
    for n in range(1, 11):
        res = await send(client, f"質問{n}", token=token)
        assert res.status_code == 200, f"{n} 回目: {res.text}"
        token = token or res.json()["chat_token"]
        assert res.json()["turns_used"] == n

    res = await send(client, "質問11", token=token)
    assert res.status_code == 409
    assert res.json() == {"code": "turn_limit", "limit": 10}
    assert adapter.calls == 10  # 11 回目は LLM を呼ばない
    assert await chat_ctx.scalar("SELECT turns FROM chat_sessions") == 10
    assert await chat_ctx.scalar("SELECT COUNT(*) FROM chat_messages") == 20


async def test_it_029_18_refusal_and_out_of_scope_set_handoff_once(chat_ctx: ChatCtx) -> None:
    adapter = ScriptedLLMAdapter(
        fail("refusal"), out("out_of_scope", "自由な文章1"), out("out_of_scope", "自由な文章2")
    )
    _, client = chat_ctx.build(adapter)
    res = await send(client, "危険な依頼です")
    assert res.status_code == 200
    reply = res.json()["reply"]
    assert reply["intent"] == "out_of_scope"
    assert reply["message"] == chat_guard.OUT_OF_SCOPE_MESSAGE
    assert [link["href"] for link in reply["guide"]["links"]] == [
        "/contents/faq",
        "/contents/company",
    ]
    token = res.json()["chat_token"]
    first = await chat_ctx.scalar("SELECT handoff_at FROM chat_sessions")
    assert first is not None
    assert (
        await chat_ctx.scalar("SELECT turns FROM chat_sessions") == 1
    )  # refusal は往復数を戻さない

    import asyncio

    await asyncio.sleep(1.1)  # DATETIME の秒精度を越えて、書き換わっていないことを確かめる
    res = await send(client, "もう一度", token=token)
    assert res.json()["reply"]["intent"] == "out_of_scope"
    assert res.json()["reply"]["message"] == chat_guard.OUT_OF_SCOPE_MESSAGE
    assert await chat_ctx.scalar("SELECT handoff_at FROM chat_sessions") == first
    res = await send(client, "三度目", token=token)
    assert await chat_ctx.scalar("SELECT handoff_at FROM chat_sessions") == first


@pytest.mark.parametrize(
    ("message", "status", "fields"),
    [
        ("", 400, [{"name": "message", "reason": "required"}]),
        ("   ", 400, [{"name": "message", "reason": "required"}]),
        ("　　", 400, [{"name": "message", "reason": "required"}]),
        ("a", 200, None),
        ("あ" * 300, 200, None),
        ("あ" * 301, 400, [{"name": "message", "reason": "too_long"}]),
        (123, 400, [{"name": "message", "reason": "format"}]),
        (None, 400, [{"name": "message", "reason": "format"}]),
    ],
)
async def test_it_029_22_message_validation(
    chat_ctx: ChatCtx, message: object, status: int, fields: list | None
) -> None:
    adapter = ScriptedLLMAdapter(out("clarify", "条件を教えてください。"))
    _, client = chat_ctx.build(adapter)
    res = await send(client, body={"message": message})
    assert res.status_code == status, res.text
    if fields is not None:
        assert res.json() == {"code": "validation_error", "fields": fields}
        assert adapter.calls == 0
        assert await chat_ctx.counts() == {"sessions": 0, "messages": 0, "user_messages": 0}
    else:
        assert adapter.calls == 1


async def test_it_029_22_message_key_missing_is_required(chat_ctx: ChatCtx) -> None:
    adapter = ScriptedLLMAdapter(out("clarify", "x"))
    _, client = chat_ctx.build(adapter)
    res = await send(client, body={})
    assert res.status_code == 400
    assert res.json()["fields"] == [{"name": "message", "reason": "required"}]
    assert adapter.calls == 0


@pytest.mark.parametrize(
    ("product_id", "status", "reason"),
    [
        (0, 400, "out_of_range"),
        (-1, 400, "out_of_range"),
        (1, 200, None),
        (9223372036854775807, 200, None),
        (9223372036854775808, 400, "out_of_range"),
        ("abc", 400, "format"),
        (1.5, 400, "format"),
    ],
)
async def test_it_029_22_product_id_validation(
    chat_ctx: ChatCtx, product_id: object, status: int, reason: str | None
) -> None:
    adapter = ScriptedLLMAdapter(out("clarify", "条件を教えてください。"))
    _, client = chat_ctx.build(adapter)
    res = await send(client, body={"message": "これは？", "product_id": product_id})
    assert res.status_code == status, res.text
    if reason is not None:
        assert res.json() == {
            "code": "validation_error",
            "fields": [{"name": "product_id", "reason": reason}],
        }
        assert adapter.calls == 0
        assert (await chat_ctx.counts())["messages"] == 0
    else:
        assert adapter.calls == 1  # 存在しない ID でもエラーにしない


async def test_it_029_23_product_context_is_passed_only_for_published_products(
    chat_ctx: ChatCtx, monkeypatch: pytest.MonkeyPatch
) -> None:
    published = await chat_ctx.published_ids()
    outside = published[20]  # プール（先頭 5 件）の外の公開商品
    unpublished = await chat_ctx.product_id_by_name("P-UNPUB")
    monkeypatch.setattr(chat_prompt, "CHAT_CATALOG_MAX", 5)
    adapter = ScriptedLLMAdapter(out("clarify", "条件を教えてください。"))
    _, client = chat_ctx.build(adapter)

    res = await send(client, "この商品について", product_id=outside)
    assert res.status_code == 200
    request = adapter.requests[-1]
    assert request.input[1].role == "developer"
    assert request.input[1].content.startswith("<viewing_product>")
    assert f"id {outside}、" in request.input[1].content
    assert outside in {e.id for e in request.catalog}  # プールに無くても候補に含まれる

    for bad in (unpublished, 987654321):
        res = await send(client, "この商品について", product_id=bad)
        assert res.status_code == 200
        request = adapter.requests[-1]
        assert not any("<viewing_product>" in m.content for m in request.input)
        assert request.context_product_id is None
        assert bad not in {e.id for e in request.catalog}


@pytest.mark.parametrize("headers", [{}, {"X-Internal-Token": "wrong-token"}])
@pytest.mark.parametrize("method", ["status", "messages"])
async def test_it_029_24_internal_token_required(
    chat_ctx: ChatCtx, caplog: pytest.LogCaptureFixture, method: str, headers: dict[str, str]
) -> None:
    caplog.set_level(logging.INFO)
    adapter = ScriptedLLMAdapter(out("clarify", "x"))
    _, client = chat_ctx.build(adapter)
    if method == "status":
        res = await client.get(STATUS_URL, headers=headers)
    else:
        res = await client.post(MESSAGES_URL, json={"message": "こんにちは"}, headers=headers)
    assert res.status_code == 401
    assert res.json() == {"code": "unauthorized"}
    assert adapter.calls == 0
    assert (await chat_ctx.counts())["messages"] == 0
    assert "request_rejected" in log_text(caplog) and "unauthorized" in log_text(caplog)


async def test_it_029_25_personal_information_is_masked_everywhere(
    chat_ctx: ChatCtx, caplog: pytest.LogCaptureFixture
) -> None:
    ids = (await chat_ctx.published_ids())[:1]
    adapter = ScriptedLLMAdapter(
        out("recommend", "ご連絡は reply@example.com へ、とのことです。", ids=ids)
    )
    _, client = chat_ctx.build(adapter)
    question = (
        "私は山田太郎と申します。メールは taro@example.com、"
        "電話は０９０－１２３４－５６７８、カードは 4111 1111 1111 1111、"
        "注文番号 4111 1111 1111 1112、〒100-0001 東京都千代田区千代田1-1 に届けたいです。"
        "予算は3000円、サイズ100、2026年、商品番号GU-251020 です"
    )
    res = await send(client, question)
    assert res.status_code == 200, res.text
    assert res.json()["notice"] == "masked"
    secrets = [
        "山田太郎",
        "taro@example.com",
        "090-1234-5678",
        "０９０",
        "4111 1111 1111 1111",
        "100-0001",
        "千代田",
        "reply@example.com",
    ]
    stored = [r[0] for r in await chat_ctx.rows("SELECT body_masked FROM chat_messages")]
    sent = [m.content for m in adapter.requests[0].input] + [adapter.requests[0].question]
    for secret in secrets:
        assert not any(secret in text for text in stored), secret
        assert not any(secret in text for text in sent), secret
        assert secret not in res.text
    assert "[メール]" in stored[0] and "[電話番号]" in stored[0] and "[カード番号]" in stored[0]
    assert "[郵便番号]" in stored[0] and "[住所]" in stored[0]
    assert "[氏名]" in stored[0]
    assert "[メール]" in stored[1]  # LLM の応答に含まれた個人情報も保存前にマスクされる
    # Luhn が正しくない 16 桁・価格・サイズ・年・商品番号は伏せない
    for kept in ("4111 1111 1111 1112", "3000円", "サイズ100", "2026年", "GU-251020"):
        assert kept in stored[0], kept
    # ログに本文を出さない
    logs = log_text(caplog)
    assert "chat_reply" in logs
    for secret in secrets + ["黒", "パーカー", question[:10]]:
        assert secret not in logs, secret


async def test_it_029_26_kill_switch(chat_ctx: ChatCtx) -> None:
    # 停止スイッチ（CHAT_ENABLED=false）。台本つきのアダプタは差し替えず、設定から選ばれる
    _, client = chat_ctx.build(None, CHAT_ENABLED="false")
    res = await client.get(STATUS_URL, headers=HEADERS)
    assert res.status_code == 200
    assert res.json() == {
        "available": False,
        "reason": "disabled",
        "provider": "none",
        "turns_limit": 10,
        "message_max_chars": 300,
    }
    res = await send(client, "こんにちは")
    assert res.status_code == 503
    assert res.json() == {"code": "chat_unavailable"}
    assert await chat_ctx.counts() == {"sessions": 0, "messages": 0, "user_messages": 0}

    # 利用不可のアダプタを差し込んでも LLM を呼ばず、DB に書かない
    adapter = ScriptedLLMAdapter(out("clarify", "x"))
    adapter.available = False
    _, client = chat_ctx.build(adapter)
    assert (await send(client, "こんにちは")).status_code == 503
    assert adapter.calls == 0
    assert (await chat_ctx.counts())["messages"] == 0


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        # provider × キー × APP_ENV（8.2 の表）
        ({"OPENAI_API_KEY": "dummy-key-for-test"}, ("openai", True)),  # pragma: allowlist secret
        ({"OPENAI_API_KEY": "dummy-key-for-test", "APP_ENV": "production"}, ("openai", True)),
        ({"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "dummy-key-for-test"}, ("openai", True)),
        ({"APP_ENV": "development"}, ("stub", True)),
        ({"APP_ENV": "test"}, ("stub", True)),
        ({"APP_ENV": "production"}, ("none", False)),
        ({"LLM_PROVIDER": "stub", "APP_ENV": "production"}, ("none", False)),
        ({"LLM_PROVIDER": "openai"}, ("none", False)),
        ({"LLM_PROVIDER": "stub"}, ("stub", True)),
    ],
)
async def test_it_029_27_adapter_selection_by_settings(
    chat_ctx: ChatCtx, monkeypatch: pytest.MonkeyPatch, env: dict[str, str], expected: tuple
) -> None:
    from app.adapters.llm import OpenAIAdapter

    def _forbidden(self: OpenAIAdapter) -> None:  # キー無しの経路でクライアントを作らない
        raise AssertionError("OpenAI のクライアントを作ろうとした")

    monkeypatch.setattr(OpenAIAdapter, "_get_client", _forbidden)
    _, client = chat_ctx.build(None, **env)
    res = await client.get(STATUS_URL, headers=HEADERS)
    assert res.status_code == 200, res.text
    provider, available = expected
    assert res.json()["provider"] == provider
    assert res.json()["available"] is available
    assert res.json()["reason"] == (None if available else "disabled")
    if provider == "stub":
        res = await send(client, "送料は？")
        assert res.status_code == 200 and res.json()["reply"]["intent"] == "faq"
    elif provider == "none":
        assert (await send(client, "送料は？")).status_code == 503


def _all_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _all_keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _all_keys(v)}
    return set()


async def test_it_029_28_responses_expose_only_the_designed_keys(chat_ctx: ChatCtx) -> None:
    ids = (await chat_ctx.published_ids())[:2]
    adapter = ScriptedLLMAdapter(out("recommend", "お選びしました。", ids=ids))
    _, client = chat_ctx.build(adapter)
    status = await client.get(STATUS_URL, headers=HEADERS)
    res = await send(client, "黒のパーカーが欲しいです")
    body = res.json()

    assert set(status.json()) == {
        "available",
        "reason",
        "provider",
        "turns_limit",
        "message_max_chars",
    }
    assert set(body) == {"chat_token", "reply", "turns_used", "turns_limit", "notice"}
    assert set(body["reply"]) == {"intent", "message", "products", "sources", "guide"}
    for card in body["reply"]["products"]:
        assert set(card) == {"id", "name", "price_incl_tax", "image_path", "sold_out", "reason"}

    forbidden_keys = {
        "token_hash",
        "model",
        "input_tokens",
        "output_tokens",
        "usage",
        "prompt",
        "instructions",
        "session_id",
        "chat_session_id",
        "api_key",
    }
    assert not (_all_keys(body) | _all_keys(status.json())) & forbidden_keys
    token_hash = await chat_ctx.scalar("SELECT token_hash FROM chat_sessions")
    for text in (res.text, status.text):
        assert token_hash not in text
        assert "scripted-model" not in text and "gpt-6" not in text
        assert chat_prompt.PROMPT_CANARY not in text
        assert "<faq>" not in text and "守るルール" not in text


async def test_it_029_20b_status_reports_daily_limit(chat_ctx: ChatCtx) -> None:
    adapter = ScriptedLLMAdapter(out("clarify", "条件を教えてください。"))
    _, client = chat_ctx.build(adapter, CHAT_DAILY_LIMIT="1")
    assert (await client.get(STATUS_URL, headers=HEADERS)).json()["available"] is True
    assert (await send(client, "こんにちは")).status_code == 200
    res = await client.get(STATUS_URL, headers=HEADERS)
    assert res.json()["available"] is False and res.json()["reason"] == "daily_limit"
    assert res.json()["provider"] == "openai"


async def test_it_029_stub_flow_end_to_end(chat_ctx: ChatCtx) -> None:
    """スタブ（キー無しの既定）で 4.3 の形の応答になる。"""
    _, client = chat_ctx.build(StubAdapter())
    rec = await send(client, "春に羽織れるアウターのおすすめを探して")
    assert rec.status_code == 200, rec.text
    reply = rec.json()["reply"]
    assert reply["intent"] == "recommend" and 1 <= len(reply["products"]) <= 3
    assert all(not p["sold_out"] for p in reply["products"])
    faq = await send(client, "送料はいくらですか", token=rec.json()["chat_token"])
    assert faq.json()["reply"]["intent"] == "faq"
    assert faq.json()["reply"]["sources"] == [{"title": "よくある質問", "href": "/contents/faq"}]
    oos = await send(client, "今日の天気は？", token=rec.json()["chat_token"])
    assert oos.json()["reply"]["intent"] == "out_of_scope"
