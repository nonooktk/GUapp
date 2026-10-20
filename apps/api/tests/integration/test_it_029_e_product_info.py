"""IT-029-31〜34: 文脈の商品への質問（intent=product_info。DS-DEC-107）。

商品詳細の「この商品について質問する」から `product_id` 付きで送ったとき、DB の情報が資料として
渡り、資料に基づく回答だけが通ること。MySQL（guapp_test）＋ seed 必須。LLM は台本つきのアダプタ。
"""

from __future__ import annotations

from app.services import chat_guard, chat_prompt
from tests.integration.chat_helpers import ChatCtx, send
from tests.unit.scripted_llm import ScriptedLLMAdapter, out

DESCRIPTION = "やわらかい綿100%のTシャツです。手洗いはできません。"


async def _prepare(chat_ctx: ChatCtx) -> tuple[int, int]:
    """文脈にする商品を、素材・説明が決まった状態にして (id, 税込価格) を返す。"""
    pid = (await chat_ctx.published_ids())[0]
    await chat_ctx.execute(
        "UPDATE products SET material='綿100%', description=:d, price_incl_tax=1490 WHERE id=:i",
        d=DESCRIPTION,
        i=pid,
    )
    return pid, 1490


async def test_it_029_31_viewing_product_carries_db_facts(chat_ctx: ChatCtx) -> None:
    pid, _ = await _prepare(chat_ctx)
    adapter = ScriptedLLMAdapter(out("product_info", "素材は綿100%です。"))
    _, client = chat_ctx.build(adapter)

    res = await send(client, "この商品の洗濯方法と素材を教えて", product_id=pid)
    assert res.status_code == 200, res.text
    request = adapter.requests[0]
    viewing = request.input[1]
    assert viewing.role == "developer" and viewing.content.startswith("<viewing_product>")
    name = await chat_ctx.scalar("SELECT name FROM products WHERE id=:i", i=pid)
    for fragment in (
        f"id {pid}、{name}",
        "税込価格: 1490円",
        "素材: 綿100%",
        f"説明: {DESCRIPTION}",
        "在庫: あり",
    ):
        assert fragment in viewing.content, fragment
    # 固定指示は定数のまま（質問・商品の資料を入れない）
    assert request.instructions == chat_prompt.SYSTEM_PROMPT
    assert DESCRIPTION not in request.instructions

    reply = res.json()["reply"]
    assert reply["intent"] == "product_info"
    assert reply["message"] == "素材は綿100%です。"
    assert reply["products"] == [] and reply["guide"] is None
    assert reply["sources"] == [{"title": "商品ページ", "href": f"/products/{pid}"}]
    stored = await chat_ctx.rows(
        "SELECT intent, product_ids FROM chat_messages WHERE role='assistant'"
    )
    assert [row[0] for row in stored] == ["product_info"]


async def test_it_029_32_info_missing_from_the_facts_is_not_invented(chat_ctx: ChatCtx) -> None:
    pid, _ = await _prepare(chat_ctx)
    guidance = "洗濯方法は、こちらでは確認できません。商品ページの記載をご確認ください。"
    adapter = ScriptedLLMAdapter(
        out("product_info", guidance),  # 資料に無いと答える
        out("product_info", "40度以下の水で、洗濯ネットを使って洗えます。"),  # 作った数値
        out("product_info", "ご家庭の洗濯機で洗えます。"),  # 数値は無い（数値の検査では止まらない）
    )
    _, client = chat_ctx.build(adapter)

    ok = (await send(client, "洗濯方法を教えて", product_id=pid)).json()["reply"]
    assert ok["intent"] == "product_info" and ok["message"] == guidance

    made_up = (await send(client, "洗濯方法を教えて", product_id=pid)).json()["reply"]
    assert made_up["intent"] == "product_info"
    assert made_up["message"] == chat_guard.PRODUCT_INFO_FALLBACK_MESSAGE
    assert "40" not in made_up["message"]
    assert made_up["sources"][0]["href"] == f"/products/{pid}"

    # 数値を含まない創作は、決定的なコードでは止められない
    # （固定指示の R12 とモデルで防ぐ。DS-DEC-107 の割り切り）
    unchecked = (await send(client, "洗濯方法を教えて", product_id=pid)).json()["reply"]
    assert unchecked["intent"] == "product_info"


async def test_it_029_33_numbers_in_the_facts_pass_and_others_fall(chat_ctx: ChatCtx) -> None:
    pid, price = await _prepare(chat_ctx)
    adapter = ScriptedLLMAdapter(
        out("product_info", "素材は綿100%です。"),  # 資料の数値（100）
        out("product_info", f"税込{price:,}円です。"),  # DB の価格
        out("product_info", "素材は綿80%、ポリエステル20%です。"),  # 資料に無い数値
        out("product_info", "税込1,990円です。"),  # DB と違う価格
        out("product_info", "在庫は残り3点です。"),  # 在庫の数
        out("product_info", "在庫あり、3色展開です。"),  # 有無と 1 桁
    )
    _, client = chat_ctx.build(adapter)
    expected = [
        "素材は綿100%です。",
        f"税込{price:,}円です。",
        chat_guard.PRODUCT_INFO_FALLBACK_MESSAGE,
        chat_guard.PRODUCT_INFO_FALLBACK_MESSAGE,
        chat_guard.PRODUCT_INFO_FALLBACK_MESSAGE,
        "在庫あり、3色展開です。",
    ]
    token = None
    for message in expected:
        res = await send(client, "この商品について教えて", product_id=pid, token=token)
        assert res.status_code == 200, res.text
        token = token or res.json()["chat_token"]
        reply = res.json()["reply"]
        assert reply["intent"] == "product_info"
        assert reply["message"] == message
        assert "1,990" not in res.text and "80%" not in res.text


async def test_it_029_34_unpublished_or_unknown_context_is_ignored(chat_ctx: ChatCtx) -> None:
    unpublished = await chat_ctx.product_id_by_name("P-UNPUB")
    adapter = ScriptedLLMAdapter(out("product_info", "素材は綿です。"))
    _, client = chat_ctx.build(adapter)

    for bad in (unpublished, 987654321):
        res = await send(client, "この商品の素材を教えて", product_id=bad)
        assert res.status_code == 200  # エラーにしない（存在の有無を教えない）
        request = adapter.requests[-1]
        assert not any("<viewing_product>" in m.content for m in request.input)
        reply = res.json()["reply"]
        # 文脈が無いので product_info は通らず、範囲外の定型文になる
        assert reply["intent"] == "out_of_scope"
        assert reply["message"] == chat_guard.OUT_OF_SCOPE_MESSAGE
        assert reply["sources"] == [] and reply["guide"] is not None
