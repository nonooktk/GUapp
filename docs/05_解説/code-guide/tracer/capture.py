"""コードトレーサー用の素材（画面写真・hotspot・BFF 通信・DB の変化）を、手元で動いているアプリから記録する。

前提:
  - web（http://127.0.0.1:3000）と api（http://127.0.0.1:8000）、ローカル MySQL が起動済み
  - Playwright（Python）と Chromium が入っている
使い方（再実行できる。capture/ 配下を作り直す）:
  python3 ~/GUapp/docs/05_解説/code-guide/tracer/capture.py
注意:
  - 入力欄はダミー初期値（apps/web/lib/demo-defaults.ts）のまま使う。値は書き換えない
  - ローカル DB にダミーの注文が 1 件できる
  - DB は SELECT のみ（db_snapshot.py）。接続文字列・.env の中身は出力しない
  - Cookie 値・CSRF トークン・cart_token・idempotency_key は種類と長さだけに伏せて記録する
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image
from playwright.async_api import async_playwright

BASE_URL = "http://127.0.0.1:3000"
VIEWPORT = {"width": 390, "height": 844}
SCALE = 2
HERE = Path(__file__).resolve().parent
OUT = HERE / "capture"
API_DIR = Path.home() / "GUapp" / "apps" / "api"
JPEG_MAX_BYTES = 250 * 1024

SECRET_KEYS = {"cart_token", "csrf_token", "idempotency_key"}


# ---------------------------------------------------------------- 伏せ字・整形
def mask(kind: str, value: str) -> str:
    return f"<{kind} {len(value)} 文字>"


def redact(obj):
    """辞書のキーが cart_token / csrf_token / idempotency_key なら値を伏せ、長い配列は先頭 3 件に切り詰める。"""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in SECRET_KEYS and isinstance(v, str):
                out[k] = mask(k, v)
            else:
                out[k] = redact(v)
        return out
    if isinstance(obj, list):
        items = [redact(v) for v in obj[:3]]
        if len(obj) > 3:
            items.append(f"…（残り {len(obj) - 3} 件）")
        return items
    return obj


def redact_cookie(cookie: str) -> str:
    parts = []
    for c in cookie.split(";"):
        c = c.strip()
        if not c:
            continue
        name, _, val = c.partition("=")
        parts.append(f"{name} {len(val)} 文字")
    return "<" + "・".join(parts) + ">" if parts else ""


# ---------------------------------------------------------------- 通信の記録
class Recorder:
    """ブラウザが出す BFF（/api/...）へのリクエストを、操作ごとにまとめて記録する。"""

    def __init__(self, page):
        self.page = page
        self.records: list[dict] = []
        self.tasks: list[asyncio.Task] = []
        page.on("response", lambda r: self.tasks.append(asyncio.create_task(self._on_response(r))))

    async def _on_response(self, response):
        req = response.request
        parts = urlsplit(req.url)
        if not parts.path.startswith("/api/"):
            return
        headers = await req.all_headers()
        rec_headers = {}
        if "content-type" in headers:
            rec_headers["content-type"] = headers["content-type"]
        if "x-csrf-token" in headers:
            rec_headers["x-csrf-token"] = mask("csrf_token", headers["x-csrf-token"])
        if "cookie" in headers:
            rec_headers["cookie"] = redact_cookie(headers["cookie"])
        rec = {
            "method": req.method,
            "path": parts.path + (f"?{parts.query}" if parts.query else ""),
            "status": response.status,
            "request_headers": rec_headers,
        }
        post = req.post_data
        if post:
            try:
                rec["request_body"] = redact(json.loads(post))
            except ValueError:
                rec["request_body"] = "<JSON 以外の本文>"
        try:
            rec["response_body"] = redact(await response.json())
        except Exception:  # 本文なし・JSON 以外
            rec["response_body"] = None
        self.records.append(rec)

    async def drain(self):
        await asyncio.sleep(0.3)
        while self.tasks:
            tasks, self.tasks = self.tasks, []
            await asyncio.gather(*tasks)

    async def take(self) -> list[dict]:
        """ここまでに溜まった記録を取り出して空にする。"""
        await self.drain()
        out, self.records = self.records, []
        return out


# ---------------------------------------------------------------- DB（読み取り専用）
def db_snapshot(product_id: int, cart_token: str) -> dict:
    env = {**os.environ, "PRODUCT_ID": str(product_id), "CART_TOKEN": cart_token}
    r = subprocess.run(
        ["uv", "run", "--env-file", ".env", "python", str(HERE / "db_snapshot.py")],
        cwd=API_DIR,
        env=env,
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        print("db_snapshot 失敗:\n" + r.stderr[-1500:], file=sys.stderr)
        raise RuntimeError("db_snapshot failed")
    return json.loads(r.stdout.strip().splitlines()[-1])


# ---------------------------------------------------------------- 画面写真と hotspot
STATES: list[dict] = []
_seq = [0]


async def wait_images(page):
    await page.evaluate(
        """async () => {
          const imgs = Array.from(document.images);
          await Promise.all(imgs.map(i => i.complete ? null : new Promise(r => { i.onload = i.onerror = r; setTimeout(r, 4000); })));
        }"""
    )


async def wait_toasts_gone(page):
    """前の操作のトーストが残っていると画面が隠れるので、消えるまで待つ（最大 10 秒）。"""
    try:
        await page.wait_for_function(
            "() => { const c = document.querySelector('div.fixed[role=status]'); return !c || c.children.length === 0; }",
            timeout=10000,
        )
    except Exception:
        pass


async def snap(page, state_id: str, title: str, hotspots: list[dict] | None = None, toast_ok: bool = False):
    """全体が 1 枚に入るようビューポートの高さを伸ばして撮り、hotspot の座標（CSS px、画像左上が原点）を測る。

    hotspots: [{"action", "label", "locator", "next"}]
    """
    await page.wait_for_load_state("load")
    if not toast_ok:
        await wait_toasts_gone(page)
    await wait_images(page)
    await page.evaluate("window.scrollTo(0, 0)")
    height = await page.evaluate("document.documentElement.scrollHeight")
    for _ in range(3):
        await page.set_viewport_size({"width": VIEWPORT["width"], "height": height})
        await page.wait_for_timeout(250)
        h2 = await page.evaluate("document.documentElement.scrollHeight")
        if h2 == height:
            break
        height = h2

    measured = []
    for hs in hotspots or []:
        box = await hs["locator"].evaluate(
            "e => { const r = e.getBoundingClientRect(); return {x: r.x + scrollX, y: r.y + scrollY, w: r.width, h: r.height}; }"
        )
        measured.append(
            {
                "action": hs["action"],
                "label": hs["label"],
                "x": round(box["x"]),
                "y": round(box["y"]),
                "w": round(box["w"]),
                "h": round(box["h"]),
                "next": hs["next"],
            }
        )

    _seq[0] += 1
    fname = f"{_seq[0]:02d}-{state_id}.jpg"
    png = OUT / f"_{state_id}.png"
    await page.screenshot(path=str(png), type="png", full_page=True)
    await page.set_viewport_size(VIEWPORT)

    # JPEG 化（品質 80 から、250KB を超えたら少しずつ下げる）
    im = Image.open(png).convert("RGB")
    q = 80
    while True:
        im.save(OUT / fname, "JPEG", quality=q, optimize=True)
        if (OUT / fname).stat().st_size <= JPEG_MAX_BYTES or q <= 55:
            break
        q -= 5
    png.unlink()

    path = urlsplit(page.url)
    STATES.append(
        {
            "id": state_id,
            "title": title,
            "path": path.path + (f"?{path.query}" if path.query else ""),
            "image": fname,
            "width": VIEWPORT["width"],
            "height": height,
            "hotspots": measured,
            "_jpeg_quality": q,
            "_image_px": list(im.size),
        }
    )
    print(f"  撮影 {fname}: {VIEWPORT['width']}x{height} CSS px, {(OUT / fname).stat().st_size // 1024}KB (q={q})")


async def settle(page, ms=600):
    try:
        await page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass
    await page.wait_for_timeout(ms)


# ---------------------------------------------------------------- 本体
async def main():
    if OUT.exists():
        for f in OUT.iterdir():
            if f.is_file():
                f.unlink()
    OUT.mkdir(parents=True, exist_ok=True)

    actions: dict[str, dict] = {}
    problems: list[str] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        ctx = await browser.new_context(viewport=VIEWPORT, device_scale_factor=SCALE, locale="ja-JP")
        # Next.js 開発モードの「N」バッジ（開発用オーバーレイ）は写真に写さない
        await ctx.add_init_script(
            "document.addEventListener('DOMContentLoaded', () => {"
            " const s = document.createElement('style'); s.textContent = 'nextjs-portal{display:none!important}';"
            " document.head.appendChild(s); });"
        )
        page = await ctx.new_page()
        rec = Recorder(page)

        # ---- 1. list
        print("1. 商品一覧")
        await page.goto(f"{BASE_URL}/products")
        await settle(page)
        await rec.take()  # 最初の読み込みで出た通信は捨てる（操作ではない）

        # 通常商品（在庫あり・テスト用の【】付きではない）を 1 つ選ぶ
        listing = await (await page.request.get(f"{BASE_URL}/api/products")).json()
        product = next(i for i in listing["items"] if not i["sold_out"] and "【" not in i["name"])
        pid = product["id"]
        print(f"  対象商品: id={pid} {product['name']}")
        card = page.locator(f'a[href="/products/{pid}"]').first
        await card.wait_for(state="visible")
        await snap(page, "list", "商品一覧", [{"action": "open-product", "label": "商品カード", "locator": card, "next": "detail"}])

        # ---- 2. detail
        await card.click()
        await page.wait_for_url(f"**/products/{pid}")
        await page.get_by_role("group", name="色を選択").wait_for(state="visible")
        await settle(page)
        actions["open-product"] = {
            "title": "商品を選ぶ",
            "from": "list",
            "to": "detail",
            "network": await rec.take(),
            "note": "画面のサーバー側で FastAPI を直接呼ぶため、ブラウザからは通信が見えない",
        }
        color_chip = page.get_by_role("group", name="色を選択").get_by_role("button").first
        size_chip = page.get_by_role("group", name="サイズを選択").get_by_role("button", name=re.compile(r"^サイズ M")).first
        if await size_chip.count() == 0:
            size_chip = page.get_by_role("group", name="サイズを選択").get_by_role("button").first
        color_label = (await color_chip.inner_text()).strip()
        size_label = (await size_chip.inner_text()).strip()
        await snap(
            page,
            "detail",
            "商品詳細（色・サイズ未選択）",
            [
                {"action": "select-variant", "label": f"色（{color_label}）", "locator": color_chip, "next": "detail-selected"},
                {"action": "select-variant", "label": f"サイズ（{size_label}）", "locator": size_chip, "next": "detail-selected"},
            ],
        )

        # ---- 3. detail-selected
        await color_chip.click()
        await size_chip.click()
        await page.get_by_text("在庫あり").wait_for(state="visible")
        await settle(page, 300)
        actions["select-variant"] = {
            "title": "色とサイズを選ぶ",
            "from": "detail",
            "to": "detail-selected",
            "network": await rec.take(),
            "note": "色・サイズのボタンは画面の中（ブラウザ上の state）で完結する操作で、通信は起きない。選んだ色とサイズの組み合わせから variant を決める",
        }
        add_btn = page.get_by_role("button", name="カートに入れる")
        await add_btn.wait_for(state="visible")
        await snap(
            page,
            "detail-selected",
            "商品詳細（色・サイズ選択済み）",
            [{"action": "add-to-cart", "label": "カートに入れる", "locator": add_btn, "next": "detail-added"}],
        )

        # ---- 4. detail-added
        await rec.take()
        await add_btn.click()
        await page.get_by_text("カートに追加しました").wait_for(state="visible")
        await page.get_by_role("link", name=re.compile(r"カート（1点）")).wait_for(state="visible")
        await page.wait_for_timeout(300)
        actions["add-to-cart"] = {
            "title": "カートに入れる",
            "from": "detail-selected",
            "to": "detail-added",
            "network": await rec.take(),
            "note": "ブラウザが BFF（/api/cart/items）を呼ぶ。状態変更なので X-CSRF-Token（Cookie の csrf_token と同じ値）を付ける。成功するとトーストとヘッダーのバッジが更新される",
        }
        cart_link = page.get_by_role("link", name=re.compile(r"カート（\d+点）"))
        await snap(
            page,
            "detail-added",
            "商品詳細（カートに追加後）",
            [{"action": "open-cart", "label": "ヘッダーのカートアイコン", "locator": cart_link, "next": "cart"}],
            toast_ok=True,
        )

        # ---- 5. cart
        await rec.take()
        await cart_link.click()
        await page.wait_for_url("**/cart")
        qty = page.get_by_role("combobox", name=re.compile(r"の数量"))
        await qty.wait_for(state="visible")
        await settle(page)
        actions["open-cart"] = {
            "title": "カートを開く",
            "from": "detail-added",
            "to": "cart",
            "network": await rec.take(),
            "note": "画面のサーバー側で FastAPI を直接呼ぶため、ブラウザからは通信が見えない",
        }
        await snap(
            page,
            "cart",
            "カート",
            [{"action": "change-qty", "label": "数量のセレクト", "locator": qty, "next": "cart-updated"}],
        )

        # ---- 6. cart-updated
        await rec.take()
        await qty.select_option("2")
        await page.get_by_text("数量を変更しました").wait_for(state="visible")
        await page.wait_for_timeout(200)
        actions["change-qty"] = {
            "title": "数量を変える",
            "from": "cart",
            "to": "cart-updated",
            "network": await rec.take(),
            "note": "セレクトを変えた瞬間に BFF（/api/cart/items/{item_id}）へ PATCH する。応答のカートで画面の明細・小計・合計・ヘッダーのバッジをまとめて置き換える",
        }
        go_checkout = page.get_by_role("link", name="レジへ進む")
        await go_checkout.wait_for(state="visible")
        await snap(
            page,
            "cart-updated",
            "カート（数量変更後）",
            [{"action": "go-checkout", "label": "レジへ進む", "locator": go_checkout, "next": "checkout"}],
            toast_ok=True,
        )

        # ---- 7. checkout
        await rec.take()
        await go_checkout.click()
        await page.wait_for_url("**/checkout")
        name_input = page.get_by_label("氏名")
        await name_input.wait_for(state="visible")
        await settle(page)
        actions["go-checkout"] = {
            "title": "レジに進む",
            "from": "cart-updated",
            "to": "checkout",
            "network": await rec.take(),
            "note": "画面のサーバー側で FastAPI を直接呼ぶため、ブラウザからは通信が見えない",
        }
        print(f"  氏名の初期値: {await name_input.input_value()!r}（書き換えない）")
        to_confirm = page.get_by_role("button", name="確認画面へ")
        await snap(
            page,
            "checkout",
            "注文手続き（ダミー初期値入り）",
            [{"action": "go-confirm", "label": "確認画面へ", "locator": to_confirm, "next": "confirm"}],
        )

        # ---- 8. confirm
        await rec.take()
        await to_confirm.click()
        await page.wait_for_url("**/checkout/confirm")
        place = page.get_by_role("button", name="注文を確定する")
        await place.wait_for(state="visible")
        await settle(page)
        actions["go-confirm"] = {
            "title": "確認画面へ",
            "from": "checkout",
            "to": "confirm",
            "network": await rec.take(),
            "note": "入力検証を通ったら、ブラウザが BFF（/api/checkout/prepare）を呼んで金額と冪等キー（注文の二重送信防止用）を受け取り、確認画面へ移る",
        }
        await snap(
            page,
            "confirm",
            "注文内容の確認",
            [{"action": "place-order", "label": "注文を確定する", "locator": place, "next": "confirm-dialog"}],
        )

        # ---- 9. confirm-dialog
        cookies = {c["name"]: c["value"] for c in await ctx.cookies()}
        cart_token = cookies.get("cart_token", "")
        if not cart_token:
            problems.append("cart_token Cookie が見つからず、carts 行の status を取得できなかった")
        db_before = db_snapshot(pid, cart_token)
        await rec.take()
        await place.click()
        dialog = page.get_by_role("dialog")
        await dialog.wait_for(state="visible")
        await page.wait_for_timeout(300)
        confirm_btn = dialog.get_by_role("button", name="確定する")
        await snap(
            page,
            "confirm-dialog",
            "注文確定の確認ダイアログ",
            [{"action": "place-order-confirm", "label": "確定する", "locator": confirm_btn, "next": "complete"}],
        )

        # ---- 10. complete
        await confirm_btn.click()
        await page.wait_for_url("**/orders/complete**")
        await page.get_by_role("heading").first.wait_for(state="visible")
        await settle(page, 800)
        net = await rec.take()
        db_after = db_snapshot(pid, cart_token)
        actions["place-order"] = {
            "title": "注文を確定する",
            "from": "confirm",
            "to": "complete",
            "network": net,
            "note": "「注文を確定する」ボタンでダイアログを開き、ダイアログの「確定する」で BFF（/api/orders）へ POST する。通信はこの 1 回にまとめて記録（ダイアログを開くだけでは通信しない）。冪等キーは確認画面に入った時点で受け取ったものを送る",
            "db": {"before": db_before, "after": db_after},
        }
        await snap(page, "complete", "注文完了", [], toast_ok=True)

        await browser.close()

    # 並び順を約束の順にそろえる
    order = ["open-product", "select-variant", "add-to-cart", "open-cart", "change-qty", "go-checkout", "go-confirm", "place-order"]
    actions = {k: actions[k] for k in order}

    jst = timezone(timedelta(hours=9))
    for s in STATES:
        s.pop("_jpeg_quality", None)
        s.pop("_image_px", None)
    data = {
        "captured_at": datetime.now(jst).replace(microsecond=0).isoformat(),
        "base_url": BASE_URL,
        "viewport": {"width": VIEWPORT["width"], "height": VIEWPORT["height"], "scale": SCALE},
        "states": STATES,
        "actions": actions,
    }
    (OUT / "capture.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"capture.json を書いた（状態 {len(STATES)} 枚・操作 {len(actions)} 件）")
    for p in problems:
        print("問題:", p)


if __name__ == "__main__":
    asyncio.run(main())
