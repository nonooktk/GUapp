#!/usr/bin/env python3
"""prompts.json の依頼文から OpenAI の画像生成で商品画像を作り、out/raw/NNN.png に保存する。

実行例（キーは --env-file で渡す。このスクリプトはキーの値を表示も保存もしない）:
  uv run --env-file /Users/mitsuru/GUapp/apps/api/.env --with openai --with pillow \
    python scripts/images/generate.py --only 011,004,027
  # API を呼ばずに依頼文と推定費用だけ見る
  uv run --with openai --with pillow python scripts/images/generate.py --only 011,004,027 --dry-run

主な仕様:
- --only 001,014 で一部だけ作る。省略時は prompts.json の全件。
- out/raw/NNN.png が既にあれば飛ばす。--force で作り直す。
- 1 枚ごとに推定費用を足し上げ、累計（log.jsonl の過去分を含む）+ 推定が --budget-usd を超えるなら止める。
- 費用と結果を out/log.jsonl に 1 行ずつ追記（キーは書かない）。成功時は応答の usage から実費も計算して記録。
- 失敗は 1 回だけ再試行。認証エラーは再試行せず即止める。
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROMPTS_PATH = HERE / "prompts.json"
OUT_DIR = HERE / "out"
RAW_DIR = OUT_DIR / "raw"
LOG_PATH = OUT_DIR / "log.jsonl"

DEFAULT_MODEL = "gpt-image-2.5-flare"
DEFAULT_QUALITY = "medium"
# 4:5 ぴったり（1024:1280）。幅・高さが 16 の倍数、総画素数 655,360〜8,294,400 の範囲内で、
# 公式ガイドの「カスタムサイズ」に該当する。拒否されたら --size 1024x1536 にして process.py の中央切り抜きに任せる
DEFAULT_SIZE = "1024x1280"

# 1 枚あたりの推定費用（USD）の上限寄りの見積もり。
# gpt-image-2 / 1.5 は公式の per-image 表（1024x1024 / 1024x1536 / 1536x1024 の最大値）。
# gpt-image-2.5-* は公式に per-image 表が無く（トークン課金: 出力 $30/1M）、
# gpt-image-2 の値を上限として流用する（2.5 は同じ品質段階で出力トークンが少ない、という第三者情報あり。公式未確認）。
# xhigh / max は価格情報が無いため high の 2 倍・4 倍を仮置き。
BASE_PRICES: dict[str, dict[str, float]] = {
    "gpt-image-2": {"low": 0.006, "medium": 0.053, "high": 0.211},
    "gpt-image-1.5": {"low": 0.013, "medium": 0.050, "high": 0.200},
    "gpt-image-1-mini": {"low": 0.006, "medium": 0.015, "high": 0.052},
}
BASE_PRICES["gpt-image-2.5-flare"] = {
    **BASE_PRICES["gpt-image-2"],
    "xhigh": BASE_PRICES["gpt-image-2"]["high"] * 2,
    "max": BASE_PRICES["gpt-image-2"]["high"] * 4,
}
BASE_PRICES["gpt-image-2.5-sunburst"] = BASE_PRICES["gpt-image-2.5-flare"]
REF_PIXELS = 1536 * 1024  # 上の表の最大サイズの画素数。これを超えるサイズは画素数に比例して増やす

# トークン単価（USD / 100 万トークン）。gpt-image-2 / 2.5 の公式値。usage からの実費計算に使う
USD_PER_M = {"text_in": 5.0, "image_in": 8.0, "image_out": 30.0}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def estimate_usd(model: str, quality: str, size: str) -> float:
    table = BASE_PRICES.get(model)
    if table is None or quality not in table:
        raise SystemExit(
            f"費用表に無い組み合わせ: model={model} quality={quality}。"
            "generate.py の BASE_PRICES を見直す（費用を確かめられないまま走らせない）"
        )
    w, h = (int(x) for x in size.split("x"))
    scale = max(1.0, (w * h) / REF_PIXELS)
    return round(table[quality] * scale, 4)


def actual_usd(usage: dict | None) -> float | None:
    if not usage:
        return None
    out_tok = usage.get("output_tokens")
    if out_tok is None:
        return None
    det = usage.get("input_tokens_details") or {}
    text_in = det.get("text_tokens", usage.get("input_tokens", 0)) or 0
    image_in = det.get("image_tokens", 0) or 0
    usd = (
        text_in * USD_PER_M["text_in"]
        + image_in * USD_PER_M["image_in"]
        + out_tok * USD_PER_M["image_out"]
    ) / 1_000_000
    return round(usd, 5)


def spent_so_far() -> float:
    """log.jsonl の過去分の費用合計（成功のみ。実費があれば実費、無ければ推定）。"""
    total = 0.0
    if LOG_PATH.exists():
        for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("status") == "ok":
                total += float(rec.get("cost_usd") or 0)
    return total


def append_log(rec: dict) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def scrub(text: str) -> str:
    key = os.environ.get("OPENAI_API_KEY", "")
    if key:
        text = text.replace(key, "***")
    return text


def load_items(only: str | None) -> list[dict]:
    if not PROMPTS_PATH.exists():
        raise SystemExit("prompts.json が無い。先に build_prompts.py を実行する")
    items = json.loads(PROMPTS_PATH.read_text(encoding="utf-8"))
    if only:
        wanted = [s.strip().zfill(3) for s in only.split(",") if s.strip()]
        by_id = {it["id"]: it for it in items}
        missing = [w for w in wanted if w not in by_id]
        if missing:
            raise SystemExit(f"prompts.json に無い番号: {missing}")
        items = [by_id[w] for w in wanted]
    return items


class AuthFailure(Exception):
    pass


def call_once(client, args, prompt: str):
    return client.images.generate(
        model=args.model,
        prompt=prompt,
        size=args.size,
        quality=args.quality,
        n=1,
        output_format="png",
    )


def generate_one(client, args, item: dict, est: float) -> dict:
    """1 件生成して保存し、ログ用の dict を返す。失敗は 1 回だけ再試行。"""
    import openai  # 遅延 import（--help / --dry-run を軽くする）

    rec = {
        "ts": now_iso(),
        "id": item["id"],
        "model": args.model,
        "quality": args.quality,
        "size": args.size,
        "est_usd": est,
    }
    last_err = ""
    for attempt in (1, 2):
        t0 = time.time()
        try:
            resp = call_once(client, args, item["prompt"])
            b64 = resp.data[0].b64_json
            png = base64.b64decode(b64)
            RAW_DIR.mkdir(parents=True, exist_ok=True)
            dest = RAW_DIR / f"{item['id']}.png"
            tmp = dest.with_suffix(".png.tmp")
            tmp.write_bytes(png)
            tmp.replace(dest)
            usage = resp.usage.model_dump() if getattr(resp, "usage", None) else None
            real = actual_usd(usage)
            rec.update(
                status="ok",
                attempt=attempt,
                seconds=round(time.time() - t0, 1),
                bytes=len(png),
                usage=usage,
                cost_usd=real if real is not None else est,
                cost_source="usage" if real is not None else "estimate",
            )
            return rec
        except openai.AuthenticationError as e:
            rec.update(status="auth_error", attempt=attempt, cost_usd=0.0, error=scrub(str(e))[:300])
            raise AuthFailure(rec) from None
        except Exception as e:  # noqa: BLE001  API 側の各種エラーをまとめて 1 回だけ再試行する
            last_err = f"{type(e).__name__}: {scrub(str(e))[:400]}"
            if attempt == 1:
                time.sleep(5)
    rec.update(status="error", attempt=2, cost_usd=0.0, error=last_err)
    return rec


def main() -> None:
    ap = argparse.ArgumentParser(
        description="prompts.json から OpenAI で商品画像を生成して out/raw/NNN.png に保存する",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--only", help="作る番号をカンマ区切りで（例 001,014,027）。省略時は全件")
    ap.add_argument("--force", action="store_true", help="既にある画像も作り直す")
    ap.add_argument("--dry-run", action="store_true", help="API を呼ばず、依頼文と推定費用だけ表示する")
    ap.add_argument("--budget-usd", type=float, default=5.0, help="累計費用の上限（USD）。log.jsonl の過去分を含む")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--quality", default=DEFAULT_QUALITY, help="low / medium / high（2.5 系は xhigh / max も）")
    ap.add_argument("--size", default=DEFAULT_SIZE, help="WxH。4:5 は 1024x1280")
    ap.add_argument("--workers", type=int, default=1, help="同時に投げる数（既定 1。上げすぎると 429 になる）")
    ap.add_argument("--timeout", type=float, default=240.0, help="1 リクエストの待ち秒数")
    args = ap.parse_args()

    items = load_items(args.only)
    est = estimate_usd(args.model, args.quality, args.size)
    todo = [it for it in items if args.force or not (RAW_DIR / f"{it['id']}.png").exists()]
    skipped = [it["id"] for it in items if it not in todo]
    spent = spent_so_far()

    print(f"model={args.model} quality={args.quality} size={args.size}")
    print(f"1 枚あたり推定 ${est:.4f} / 対象 {len(items)} 件 / 生成 {len(todo)} 件 / 既存で飛ばす {len(skipped)} 件 {skipped}")
    print(f"推定費用（今回）${est * len(todo):.3f} / 過去の累計 ${spent:.3f} / 上限 ${args.budget_usd:.2f}")

    if args.dry_run:
        for it in todo or items:
            print("-" * 72)
            print(f"[{it['id']}] {it['name']}  ({it['color_en']}, {it['material_en']})  推定 ${est:.4f}")
            print(it["prompt"])
        print("-" * 72)
        print("dry-run のため API は呼んでいない")
        return

    if not todo:
        print("生成するものが無い（--force で作り直せる）")
        return
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise SystemExit("OPENAI_API_KEY が未設定。uv run --env-file <.env> で渡す")
    if spent + est > args.budget_usd:
        raise SystemExit(f"予算超過のため開始しない: 累計 ${spent:.3f} + 1 枚 ${est:.3f} > ${args.budget_usd:.2f}")

    from openai import OpenAI

    client = OpenAI(api_key=key, timeout=args.timeout, max_retries=0)  # 再試行は自前で 1 回だけ

    lock = threading.Lock()
    state = {"reserved": 0.0, "stop": False, "ok": 0, "ng": 0, "spent": spent}

    def worker(item: dict) -> None:
        with lock:
            if state["stop"]:
                return
            if state["spent"] + state["reserved"] + est > args.budget_usd:
                state["stop"] = True
                print(f"[{item['id']}] 予算上限に達するため停止（累計 ${state['spent']:.3f} + 見込み ${est:.3f} > ${args.budget_usd:.2f}）")
                return
            state["reserved"] += est
        print(f"[{item['id']}] 生成中 {item['name']} ...", flush=True)
        try:
            rec = generate_one(client, args, item, est)
        except AuthFailure as e:
            rec = e.args[0]
            with lock:
                state["stop"] = True
                state["reserved"] -= est
                state["ng"] += 1
            append_log(rec)
            print(f"[{item['id']}] 認証エラーのため停止（キーを確認する）")
            return
        with lock:
            state["reserved"] -= est
            state["spent"] += float(rec.get("cost_usd") or 0)
            state["ok" if rec["status"] == "ok" else "ng"] += 1
            append_log(rec)
        if rec["status"] == "ok":
            print(f"[{item['id']}] OK {rec['bytes'] // 1024}KB 実費 ${rec['cost_usd']:.4f}（{rec['cost_source']}）{rec['seconds']}s")
        else:
            print(f"[{item['id']}] NG {rec.get('error', '')}")

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        list(ex.map(worker, todo))

    print(f"完了: 成功 {state['ok']} / 失敗 {state['ng']} / 今回までの累計費用 ${state['spent']:.3f}")
    if state["ng"] or state["stop"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
