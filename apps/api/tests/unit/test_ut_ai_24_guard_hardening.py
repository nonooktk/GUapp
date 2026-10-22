"""UT-AI-24〜27: AI アシスタントの入出力ガードの強化（G-20・G-21・G-22）。DB・ネットワーク不要。

- UT-AI-24 canary の表記ゆれ（空白・記号・長音・全角半角・逆順）
- UT-AI-25 資料に無い約束の言葉（送料無料・クーポン・割引など）の置き換え。資料にある案内は止めない
- UT-AI-26 個人情報のマスクの漏れ（県名の無い住所・崩したメール・漢数字の電話・氏名・12 桁）
- UT-AI-27 ガードが動いた種類と件数（`Finalized.guards`）と、ログ 1 行（本文なし）
"""

from __future__ import annotations

import json
import logging

import pytest

from app.repositories.products import ProductSummary
from app.services import chat as chat_service
from app.services import chat_guard as g
from app.services import chat_prompt
from tests.unit.scripted_llm import out

CANARY = chat_prompt.PROMPT_CANARY
FAQ = "4,990円以上のご注文は送料無料です。返品は14日以内に承ります。"
CATALOG_LINE = (
    "12、スムースコットンTシャツ、メンズ、トップス、1990円、白/黒、S/M/L、在庫あり、綿100%"
)


# ── UT-AI-24 canary の表記ゆれ（G-20）──────────────────────────────────────


@pytest.mark.parametrize(
    "leaked",
    [
        f"識別子は {CANARY} です",
        "C N R Y - 5 d 2 e 8 b 7 1",  # 1 文字ずつ空白で区切る
        "CNRY‑5d2e8b71",  # 非改行ハイフン（U+2011）
        "CNRYー5d2e8b71",  # 長音
        "CNRY…5d2e…8b71",  # 途中に「…」
        "c.n.r.y/5d2e.8b71",
        "17b8e2d5-YRNC",  # 逆順
        "1 7 b 8 e 2 d 5 - Y R N C",  # 逆順＋空白
        "ＣＮＲＹ－５ｄ２ｅ８ｂ７１",  # 全角
        "CN​RY-5d2e8​b71",  # ゼロ幅スペース
        "cnry 5D2E8B71",
    ],
)
def test_ut_ai_24_crumbled_canary_is_detected(leaked: str) -> None:
    assert g.contains_canary(leaked, CANARY), leaked


@pytest.mark.parametrize(
    "text",
    ["春物のおすすめです", "CNRY", "5d2e8b71", "CNRY-5d2e", "ABCD-00000000", "", "17b8e2d5"],
)
def test_ut_ai_24_unrelated_text_is_not_a_canary(text: str) -> None:
    assert not g.contains_canary(text, CANARY)


def test_ut_ai_24_crumbled_canary_in_message_or_reason_becomes_out_of_scope() -> None:
    for message, reason in (
        ("C N R Y - 5 d 2 e 8 b 7 1", "理由です。"),
        ("お選びしました。", "CNRYー5d2e8b71"),
        ("17b8e2d5-YRNC", "理由です。"),
    ):
        final = _finalize(out("recommend", message, ids=[1], reason=reason))
        assert final.canary_leak and final.reply.intent == "out_of_scope", (message, reason)
        assert final.reply.products == [] and final.guards["canary"] == 1


# ── UT-AI-25 資料に無い約束の言葉（G-20）────────────────────────────────────


def _card(pid: int) -> ProductSummary:
    return ProductSummary(
        id=pid, name="DB の商品名", price_incl_tax=2990, image_path=f"/p/{pid}.png", sold_out=False
    )


def _finalize(
    output,
    *,
    question: str = "黒のパーカーが欲しいです",
    sources: list[str] | None = None,
    promise_sources: list[str] | None = None,
    context: g.ProductContext | None = None,
):
    return g.finalize_reply(
        output,
        question=question,
        sources=[FAQ] if sources is None else sources,
        canary=CANARY,
        pool_ids={1, 2, 3},
        cards={i: _card(i) for i in (1, 2, 3)},
        context=context,
        promise_sources=promise_sources or [],
    )


@pytest.mark.parametrize(
    "promise",
    [
        "今なら全品半額セール中です。",
        "クーポンコード WELCOME で割引になります。",
        "全品 50% OFF です。",
        "ポイント5倍キャンペーン中です。",
        "ご不満なら全額返金します。",
        "1 年間の品質保証が付きます。",
        "会員限定の特典があります。",
        "全 品 値 引 き",  # 空白を挟む
        "ｸｰﾎﾟﾝをお使いください。",  # 半角カナ
    ],
)
def test_ut_ai_25_promise_not_in_the_sources_replaces_the_message(promise: str) -> None:
    faq = _finalize(out("faq", promise), question="お得な情報は？")
    assert faq.reply.intent == "out_of_scope" and faq.reply.message == g.OUT_OF_SCOPE_MESSAGE
    assert faq.guards, "どのガードで止めたかが記録される"

    rec = _finalize(out("recommend", promise, ids=[1], reason="使いやすい一枚です。"))
    assert rec.reply.message == g.AMOUNT_CHECK_FAILED_MESSAGE
    assert rec.guards.get("promise", 0) >= 1
    assert [p.reason for p in rec.reply.products] == [""]
    assert rec.reply.products[0].price_incl_tax == 2990  # カードは DB の値

    in_reason = _finalize(out("recommend", "お選びしました。", ids=[1], reason=promise[:30]))
    assert in_reason.reply.message == g.AMOUNT_CHECK_FAILED_MESSAGE
    assert in_reason.reply.products[0].reason == ""

    clarify = _finalize(out("clarify", promise))
    assert clarify.reply.intent == "clarify"
    assert clarify.reply.message == g.AMOUNT_CHECK_FAILED_MESSAGE


def test_ut_ai_25_promise_in_a_product_info_answer_becomes_the_fixed_fallback() -> None:
    ctx = g.ProductContext(
        id=12, price_incl_tax=1990, facts="id 12、スムースコットンTシャツ\n素材: 綿100%"
    )
    final = _finalize(
        out("product_info", "この商品は今なら送料無料です。"), context=ctx, sources=[]
    )
    assert final.reply.intent == "product_info"
    assert final.reply.message == g.PRODUCT_INFO_FALLBACK_MESSAGE
    assert final.guards == {"promise": 1}  # 「送料無料」と「無料」は 1 件


def test_ut_ai_25_promise_that_the_sources_contain_is_allowed() -> None:
    # FAQ にある「送料無料」の条件は止めない
    faq = _finalize(out("faq", "4,990円以上のご注文は送料無料です。"), question="送料は？")
    assert faq.reply.intent == "faq" and faq.reply.message == "4,990円以上のご注文は送料無料です。"
    assert not faq.guards

    clarify = _finalize(
        out("clarify", "送料無料になる金額もご案内できます。ご予算を教えてください。")
    )
    assert clarify.reply.intent == "clarify"
    assert clarify.reply.message.startswith("送料無料になる金額")

    rec = _finalize(out("recommend", "送料無料の条件もあわせてご確認ください。", ids=[1]))
    assert rec.reply.message == "送料無料の条件もあわせてご確認ください。"
    assert rec.reply.products[0].reason == "使いやすい一枚です。"


def test_ut_ai_25_promise_words_in_the_product_info_or_other_sources_are_allowed() -> None:
    ctx = g.ProductContext(
        id=12, price_incl_tax=1990, facts="説明: 返品・返金は商品到着後 14 日以内です。"
    )
    final = _finalize(out("product_info", "返金は到着後 14 日以内です。"), context=ctx, sources=[])
    assert final.reply.message == "返金は到着後 14 日以内です。" and not final.guards

    listed = _finalize(
        out("recommend", "セールで人気の一着です。", ids=[1]),
        promise_sources=["12、セール限定ニット、メンズ、トップス、2990円、白、M、在庫あり、ウール"],
    )
    assert listed.reply.message == "セールで人気の一着です。"


def test_ut_ai_25_question_words_are_not_sources() -> None:
    # 利用者が「クーポンはありますか」と書いても、応答が「クーポンがあります」と言えるわけではない
    final = _finalize(out("faq", "クーポンをご用意しています。"), question="クーポンはありますか")
    assert final.reply.intent == "out_of_scope"


@pytest.mark.parametrize(
    "text",
    [
        "コーヒー色の coffee 柄です。",  # off を含む英字の語（coffee）
        "着回しのポイントは 3 つです。",  # 特典でない意味のポイント
        "素材は綿 100% で、やわらかい着心地です。",
        "春らしい一枚です。",
    ],
)
def test_ut_ai_25_ordinary_wording_is_not_a_promise(text: str) -> None:
    assert g.find_unsupported_promises(text, []) == []


def test_ut_ai_25_off_is_a_word_only_when_standing_alone() -> None:
    assert g.find_unsupported_promises("50% OFF", []) == ["OFF"]
    assert g.find_unsupported_promises("30％ｏｆｆ", []) == ["OFF"]
    assert g.find_unsupported_promises("coffee off-white offer", []) == ["OFF"]  # off-white の off
    assert g.find_unsupported_promises("coffee offer", []) == []
    assert g.find_unsupported_promises("50% OFF", ["期間中は 10% OFF です"]) == []


# ── UT-AI-26 個人情報のマスクの漏れ（G-21）──────────────────────────────────


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        # 県名の無い住所（市区町村＋番地）
        ("渋谷区神南1丁目2番3号に届けて", "address"),
        ("渋谷区神南1-2-3です", "address"),
        ("横浜市中区山下町12-3まで", "address"),
        ("大阪市北区梅田2丁目", "address"),
        ("世田谷区下馬１－２－３", "address"),  # 全角
        # 崩したメール
        ("taro (at) example (dot) com です", "email"),
        ("taro(at)example.com", "email"),
        ("taro [at] example [dot] co [dot] jp", "email"),
        ("taro at example.com です", "email"),
        ("taro＠example．com", "email"),
        ("taro (アット) example.com", "email"),
        # 漢数字・全角の電話番号
        ("零九零 一二三四 五六七八", "phone"),
        ("〇九〇-一二三四-五六七八", "phone"),
        ("〇九〇の一二三四の五六七八", "phone"),
        ("０９０－１２３４－５６７８", "phone"),
        ("090-一二三四-5678", "phone"),
        ("零三 一二三四 五六七八", "phone"),
        # 氏名
        ("佐藤花子といいます", "name"),
        ("田中と言います", "name"),
        ("山田 太郎 です", "name"),
        ("私は山田 太郎です", "name"),
        ("名前は鈴木一郎です", "name"),
        # 12 桁
        ("番号は123456789012です", "number"),
        ("1234 5678 9012", "number"),
        ("1234-5678-9012", "number"),
        ("１２３４５６７８９０１２", "number"),
    ],
)
def test_ut_ai_26_pii_that_used_to_slip_through_is_masked(text: str, kind: str) -> None:
    result = g.mask_pii(text)
    assert result.counts.get(kind) == 1, (text, result)
    assert result.text != text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("東京都渋谷区神南1-2-3", "[住所]"),
        ("東京都渋谷区神南1-2-3に住んでいます", "[住所]に住んでいます"),
        ("東京都渋谷区神南1丁目2番3号", "[住所]"),
        ("神奈川県横浜市中区山下町12-3 まで", "[住所] まで"),
        ("渋谷区神南1丁目2番3号です", "[住所]です"),
    ],
)
def test_ut_ai_26_no_fragment_of_the_address_is_left(text: str, expected: str) -> None:
    result = g.mask_pii(text)
    assert result.text == expected
    for fragment in ("神南", "-3", "2番", "3号", "山下"):
        assert fragment not in result.text


def test_ut_ai_26_each_masked_value_is_replaced_whole() -> None:
    cases = {
        "taro (at) example (dot) com": "[メール]",
        "零九零 一二三四 五六七八": "[電話番号]",
        "佐藤花子といいます": "[氏名]といいます",
        "123456789012": "[番号]",
    }
    for text, expected in cases.items():
        assert g.mask_pii(text).text == expected, text


@pytest.mark.parametrize(
    "text",
    [
        "私は黒のパーカーが欲しいです",
        "予算は3000円です",
        "サイズ100をください",
        "2026年の春物です",
        "商品番号 GU-251020 について",
        "1,990円以内で探しています",
        "この市場で3番目に人気のシャツです",  # 市場 + 番
        "渋谷区で一番人気のお店はどこですか",
        "これはスキニーパンツといいます",
        "春物 全部です",
        "秋物 セーターです",
        "注文番号 20261022001234 の件です",  # 14 桁
        "1234 5678 9012 3456 は注文番号です",  # 16 桁（Luhn 不正）
        "在庫は 12 個です",
        "七分袖の黒、一番人気はどれ",
        "5 時 at 渋谷 で待ち合わせ",
    ],
)
def test_ut_ai_26_ordinary_shopping_text_is_not_masked(text: str) -> None:
    result = g.mask_pii(text)
    assert result.text == text and not result.masked


def test_ut_ai_26_twelve_digits_do_not_break_card_or_phone_detection() -> None:
    assert g.mask_pii("4111 1111 1111 1111").text == "[カード番号]"
    assert g.mask_pii("09012345678").text == "[電話番号]"
    assert g.mask_pii("012345678901").counts.get("number") == 1  # 0 始まりの 12 桁は電話ではない
    assert g.mask_pii("1000001").text == "[郵便番号]"


# ── UT-AI-27 ガードの発動を種類と件数で記録する（G-22）─────────────────────


def test_ut_ai_27_nothing_fired_means_no_guards() -> None:
    final = _finalize(out("recommend", "お選びしました。", ids=[1]))
    assert final.guards == {}


def test_ut_ai_27_each_guard_reports_its_kind_and_count() -> None:
    amount = _finalize(out("recommend", "税込 1,990 円と 2,990 円です。", ids=[1]))
    assert amount.guards == {"amount": 2}

    html = _finalize(
        out("recommend", "<b>こちら</b> http://evil.example です", ids=[1], reason="[x](http://y)")
    )
    assert html.guards == {"html_url": 4}  # <b>・</b>・URL・Markdown のリンク

    pii = _finalize(out("recommend", "連絡は a@example.com まで", ids=[1]))
    assert pii.guards == {"pii_output": 1}

    canary = _finalize(out("recommend", f"識別子 {CANARY}", ids=[1]))
    assert canary.guards == {"canary": 1}

    promise = _finalize(out("recommend", "クーポンで割引です", ids=[1]))
    assert promise.guards == {"promise": 2}  # クーポン・割引

    free_shipping = _finalize(out("recommend", "全品送料無料です", ids=[1]), sources=[])
    assert free_shipping.guards == {"promise": 1}

    faq_number = _finalize(out("faq", "返品は999日以内です。"), question="返品は？")
    assert faq_number.guards == {"faq_number": 1}

    ctx = g.ProductContext(id=12, price_incl_tax=1990, facts="素材: 綿100%")
    info = _finalize(out("product_info", "在庫は残り3点です。"), context=ctx)
    assert info.guards == {"product_info": 1}


def test_ut_ai_27_guards_never_contain_the_text(caplog: pytest.LogCaptureFixture) -> None:
    leaky_message = "連絡は secret.person@example.com まで。クーポン XYZ-SECRET で割引。"
    final = _finalize(out("recommend", leaky_message, ids=[1]))
    assert final.guards and all(isinstance(n, int) for n in final.guards.values())
    assert "secret" not in json.dumps(final.guards).lower()

    with caplog.at_level(logging.INFO, logger="app.chat"):
        chat_service._log_guards(
            "openai", "scripted-model", final.reply.intent, final.guards, {"email": 1, "phone": 2}
        )
    (record,) = [r for r in caplog.records if r.name == "app.chat"]
    line = json.loads(record.getMessage())
    assert line["event"] == "chat_guard" and record.levelno == logging.WARNING
    assert line["guards"] == {**final.guards, "pii_input": 3}
    assert line["intent"] == final.reply.intent
    assert "secret" not in record.getMessage().lower() and "XYZ" not in record.getMessage()


def test_ut_ai_27_input_pii_only_is_info_and_quiet_when_nothing_happened(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="app.chat"):
        chat_service._log_guards("openai", "m", "recommend", {}, {})
        assert [r for r in caplog.records if r.name == "app.chat"] == []
        chat_service._log_guards("openai", "m", "recommend", {}, {"address": 1})
    (record,) = [r for r in caplog.records if r.name == "app.chat"]
    assert record.levelno == logging.INFO
    assert json.loads(record.getMessage())["guards"] == {"pii_input": 1}


# ── sanitize_text は空白を変えない（U+2028・U+2029 だけ改行にする）────────────


def test_ut_ai_24_sanitize_keeps_spaces_and_turns_line_separators_into_newlines() -> None:
    assert g.sanitize_text("返金は 14 日以内です。", 100) == "返金は 14 日以内です。"
    assert g.sanitize_text("一行目\u2028二行目\u2029三行目", 100) == "一行目\n二行目\n三行目"
    assert g.sanitize_text_counted("a <i>b</i> c", 100) == ("a b c", 2)
