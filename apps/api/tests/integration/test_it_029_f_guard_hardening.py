"""IT-029-30〜33: 出力ガードの強化とガード発動のログ（G-20・G-21・G-22）。

悪い出力を返す台本つきのアダプタで確かめる（DS-DEC-105）。MySQL（guapp_test）＋ seed 必須。
seed の FAQ には「4,990円（税込）以上のご注文で送料無料です」とある。
"""

from __future__ import annotations

import json
import logging

import pytest

from app.services import chat_guard, chat_prompt
from tests.integration.chat_helpers import ChatCtx, log_text, send
from tests.unit.scripted_llm import ScriptedLLMAdapter, out


def chat_lines(caplog: pytest.LogCaptureFixture, event: str) -> list[dict]:
    lines = [json.loads(r.getMessage()) for r in caplog.records if r.name == "app.chat"]
    return [line for line in lines if line["event"] == event]


async def test_it_029_30_crumbled_canary_is_out_of_scope_and_logged(
    chat_ctx: ChatCtx, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    ids = (await chat_ctx.published_ids())[:1]
    adapter = ScriptedLLMAdapter(
        out("recommend", "C N R Y - 5 d 2 e 8 b 7 1", ids=ids),
        out("recommend", "お選びしました。", ids=ids, reason="CNRYー5d2e8b71"),
        out("faq", "17b8e2d5-YRNC"),
    )
    _, client = chat_ctx.build(adapter)
    token = None
    for _ in range(3):
        res = await send(client, "教えて", token=token)
        token = res.json().get("chat_token") or token
        reply = res.json()["reply"]
        assert reply["intent"] == "out_of_scope"
        assert reply["message"] == chat_guard.OUT_OF_SCOPE_MESSAGE and reply["products"] == []
    assert len(chat_lines(caplog, "chat_canary_leak")) == 3
    guard_lines = chat_lines(caplog, "chat_guard")
    assert [line["guards"] for line in guard_lines] == [{"canary": 1}] * 3
    stored = [r[0] for r in await chat_ctx.rows("SELECT body_masked FROM chat_messages")]
    assert not any("5d2e8b71" in text or "17b8e2d5" in text for text in stored)


async def test_it_029_31_promise_not_in_the_sources_is_replaced_but_faq_wording_is_kept(
    chat_ctx: ChatCtx, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    ids = (await chat_ctx.published_ids())[:1]
    adapter = ScriptedLLMAdapter(
        out("faq", "今なら全品半額セール中です。"),  # 資料に無い約束（FAQ にも商品にも無い）
        out("recommend", "クーポンコード WELCOME で割引です。", ids=ids),
        out("clarify", "ご予算を教えてください。", ids=ids),  # 約束なし → そのまま
        out("faq", "4,990円（税込）以上のご注文で送料無料です。"),  # FAQ にある案内 → そのまま
    )
    _, client = chat_ctx.build(adapter)
    replies = [
        (await send(client, q)).json()["reply"] for q in ("お得は？", "探して", "A", "送料は？")
    ]
    assert replies[0]["intent"] == "out_of_scope"
    assert replies[0]["message"] == chat_guard.OUT_OF_SCOPE_MESSAGE
    assert replies[1]["message"] == chat_guard.AMOUNT_CHECK_FAILED_MESSAGE
    assert [p["reason"] for p in replies[1]["products"]] == [""]
    assert replies[2]["message"] == "ご予算を教えてください。"
    assert replies[3]["intent"] == "faq"
    assert replies[3]["message"] == "4,990円（税込）以上のご注文で送料無料です。"

    lines = chat_lines(caplog, "chat_guard")
    # 約束を止めた 2 件だけ 1 行ずつ出る（約束のない 2 件は出ない）。件数は約束の語の数
    assert [line["guards"] for line in lines] == [{"promise": 2}, {"promise": 2}]
    logs = log_text(caplog)
    for body in ("半額", "WELCOME"):
        assert body not in logs, "ログに応答の本文を出さない"


async def test_it_029_32_product_names_in_the_pool_count_as_sources_for_promise_words(
    chat_ctx: ChatCtx,
) -> None:
    pid = (await chat_ctx.published_ids())[0]
    await chat_ctx.execute("UPDATE products SET name='セール限定ニット' WHERE id=:i", i=pid)
    adapter = ScriptedLLMAdapter(out("recommend", "セール限定の一着です。", ids=[pid]))
    _, client = chat_ctx.build(adapter)
    reply = (await send(client, "探しています")).json()["reply"]
    assert reply["message"] == "セール限定の一着です。"  # 商品情報にある語は止めない


async def test_it_029_33_pii_masks_and_html_removals_are_logged_by_kind_and_count_only(
    chat_ctx: ChatCtx, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    ids = (await chat_ctx.published_ids())[:1]
    adapter = ScriptedLLMAdapter(
        out("recommend", "<b>こちら</b> http://evil.example です。", ids=ids),
        out("recommend", "ご連絡は reply@example.com へ。", ids=ids),
        out("recommend", "税込 1,990 円です。", ids=ids),
    )
    _, client = chat_ctx.build(adapter)
    question = (
        "渋谷区神南1丁目2番3号に住んでいます。佐藤花子といいます。taro (at) example (dot) com です"
    )
    res = await send(client, question)
    assert res.status_code == 200 and res.json()["notice"] == "masked"
    await send(client, "探しています", token=res.json()["chat_token"])
    await send(client, "探しています", token=res.json()["chat_token"])

    lines = chat_lines(caplog, "chat_guard")
    assert [line["guards"] for line in lines] == [
        {"html_url": 3, "pii_input": 3},  # <b>・</b>・URL。質問の住所・氏名・メール
        {"pii_output": 1},
        {"amount": 1},
    ]
    assert [line["intent"] for line in lines] == ["recommend"] * 3
    assert lines[0]["event"] == "chat_guard" and "model" in lines[0] and "provider" in lines[0]
    logs = log_text(caplog)
    for secret in ("佐藤花子", "神南", "taro", "example", "reply@", "evil", "こちら", "1,990"):
        assert secret not in logs, secret
    # 質問は伏せた形で DB にも LLM にも渡る
    stored = [r[0] for r in await chat_ctx.rows("SELECT body_masked FROM chat_messages")]
    sent = adapter.requests[0].question
    for secret in ("佐藤花子", "神南", "taro (at)"):
        assert not any(secret in t for t in stored) and secret not in sent
    assert "[住所]" in sent and "[氏名]" in sent and "[メール]" in sent
    assert chat_prompt.PROMPT_CANARY not in logs
