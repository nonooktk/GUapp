#!/usr/bin/env python3
"""トップページ NEW ARRIVALS の帯に敷く「秋らしい」背景画像（3 案）を作る道具。

generate.py（商品画像用）の費用見積もり・実費計算・キー伏せ字の関数を流用し、ログと予算は別管理にする
（out/hero/log.jsonl。商品画像のログとは混ぜない）。既存の generate.py / process.py は変更しない。

3 つの段階（サブコマンド）:
  gen      OpenAI で 1 案 1 枚を作り、out/hero/raw/{a,b,c}.png に保存する
  process  中央基準で 2.4:1 に切り抜き、幅 1920（元が小さければ元の幅）の JPEG にして
           apps/web/public/hero/autumn-{a,b,c}.jpg に書く（1 枚 250KB 以下を目安に品質を下げる）
  sheet    3 案を横に並べた確認画像 out/hero/contact_sheet.jpg を作る

実行例（キーは --env-file で渡す。このスクリプトはキーの値を表示も保存もしない）:
  # API を呼ばずに依頼文と見積もりだけ見る
  uv run --with openai --with pillow python scripts/images/generate_hero.py gen --dry-run
  # 生成（累計の上限は --budget-usd。既にある画像は飛ばす。作り直しは --force）
  uv run --env-file /Users/mitsuru/GUapp/apps/api/.env --with openai --with pillow \
    python scripts/images/generate_hero.py gen --budget-usd 0.6
  uv run --with openai --with pillow python scripts/images/generate_hero.py process
  uv run --with openai --with pillow python scripts/images/generate_hero.py sheet
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import generate as g  # 同じディレクトリの generate.py（費用見積もり・実費計算・伏せ字を流用する）

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
OUT_DIR = HERE / "out" / "hero"
RAW_DIR = OUT_DIR / "raw"
LOG_PATH = OUT_DIR / "log.jsonl"
SHEET_PATH = OUT_DIR / "contact_sheet.jpg"
DEST_DIR = REPO_ROOT / "apps" / "web" / "public" / "hero"

DEFAULT_MODEL = g.DEFAULT_MODEL
DEFAULT_QUALITY = g.DEFAULT_QUALITY
# 2.4:1 ぴったり。幅・高さが 16 の倍数、縦横比 1:3〜3:1、総画素数 655,360〜8,294,400 の範囲内。
# 拒否されたら --size 1536x1024 にして、process が中央基準で 2.4:1 に切り抜く
DEFAULT_SIZE = "1920x800"

RATIO_W, RATIO_H = 12, 5  # 2.4:1
OUT_WIDTH = 1920
JPEG_Q_START, JPEG_Q_MIN = 80, 50
MAX_BYTES = 250_000

# すべての案に入れる共通条件
COMMON = (
    "Photorealistic photograph, wide horizontal banner for the top page of a fashion e-commerce site, "
    "autumn mood with a warm palette of brown, mustard, burgundy and muted orange. "
    "White text and a button will be placed over the center of the image, so keep the center area calm and uncluttered "
    "(soft, low-detail, no strong focal point) and place the main subjects toward the left and right sides. "
    "Overall tone slightly dark and moody. "
    "No text, no letters, no logos, no brand names, no watermarks, no signage. "
    "Nothing that resembles any real fashion brand."
)

IDEAS: dict[str, dict[str, str]] = {
    "a": {
        "name": "紅葉の並木道",
        "scene": (
            "A tree-lined avenue in full autumn colors with dappled sunlight filtering through red and orange leaves, "
            "fallen leaves covering the ground. No people. Trees frame the left and right edges, "
            "with a softly lit, open road in the middle."
        ),
    },
    "b": {
        "name": "ニットとコートの平置き",
        "scene": (
            "Top-down flat lay on a wooden floor: a knit sweater, a wool coat and a scarf laid out neatly on the left and right sides, "
            "with scattered autumn leaves. The center of the wooden floor stays mostly empty."
        ),
    },
    "c": {
        "name": "夕暮れの街角",
        "scene": (
            "A city street corner at dusk. A person in a coat seen from behind (face not visible) stands on one side, "
            "a street lamp glows warmly on the other side, fallen leaves on the pavement. "
            "The center is a soft, blurred, quiet street in twilight."
        ),
    },
}


def build_prompt(key: str) -> str:
    return f"{IDEAS[key]['scene']} {COMMON}"


def spent_so_far() -> float:
    """out/hero/log.jsonl の過去分の費用合計（成功のみ。実費があれば実費、無ければ推定）。"""
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


def parse_only(only: str | None) -> list[str]:
    if not only:
        return list(IDEAS)
    keys = [s.strip().lower() for s in only.split(",") if s.strip()]
    bad = [k for k in keys if k not in IDEAS]
    if bad:
        raise SystemExit(f"案は a,b,c のどれか: {bad}")
    return keys


# ---------- gen ----------


def generate_one(client, args, key: str, est: float) -> dict:
    """1 案を生成して保存し、ログ用の dict を返す。失敗は 1 回だけ再試行。認証エラーは即止める。"""
    import openai  # 遅延 import（--dry-run を軽くする）

    rec = {
        "ts": g.now_iso(),
        "id": key,
        "model": args.model,
        "quality": args.quality,
        "size": args.size,
        "est_usd": est,
    }
    last_err = ""
    for attempt in (1, 2):
        t0 = time.time()
        try:
            resp = client.images.generate(
                model=args.model,
                prompt=build_prompt(key),
                size=args.size,
                quality=args.quality,
                n=1,
                output_format="png",
            )
            png = base64.b64decode(resp.data[0].b64_json)
            RAW_DIR.mkdir(parents=True, exist_ok=True)
            dest = RAW_DIR / f"{key}.png"
            tmp = dest.with_suffix(".png.tmp")
            tmp.write_bytes(png)
            tmp.replace(dest)
            usage = resp.usage.model_dump() if getattr(resp, "usage", None) else None
            real = g.actual_usd(usage)
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
            rec.update(status="auth_error", attempt=attempt, cost_usd=0.0, error=g.scrub(str(e))[:300])
            append_log(rec)
            raise SystemExit("認証エラーのため停止（キーを確認する）") from None
        except Exception as e:  # noqa: BLE001  API 側の各種エラーをまとめて 1 回だけ再試行する
            last_err = f"{type(e).__name__}: {g.scrub(str(e))[:400]}"
            if attempt == 1:
                time.sleep(5)
    rec.update(status="error", attempt=2, cost_usd=0.0, error=last_err)
    return rec


def cmd_gen(args) -> None:
    keys = parse_only(args.only)
    est = g.estimate_usd(args.model, args.quality, args.size)
    todo = [k for k in keys if args.force or not (RAW_DIR / f"{k}.png").exists()]
    skipped = [k for k in keys if k not in todo]
    spent = spent_so_far()

    print(f"model={args.model} quality={args.quality} size={args.size}")
    print(f"1 枚あたり推定 ${est:.4f} / 対象 {len(keys)} 件 / 生成 {len(todo)} 件 / 既存で飛ばす {len(skipped)} 件 {skipped}")
    print(f"推定費用（今回）${est * len(todo):.3f} / 過去の累計 ${spent:.3f} / 上限 ${args.budget_usd:.2f}")

    if args.dry_run:
        for k in todo or keys:
            print("-" * 72)
            print(f"[{k}] {IDEAS[k]['name']}  推定 ${est:.4f}")
            print(build_prompt(k))
        print("-" * 72)
        print("dry-run のため API は呼んでいない")
        return

    if not todo:
        print("生成するものが無い（--force で作り直せる）")
        return
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise SystemExit("OPENAI_API_KEY が未設定。uv run --env-file <.env> で渡す")

    from openai import OpenAI

    client = OpenAI(api_key=key, timeout=args.timeout, max_retries=0)  # 再試行は自前で 1 回だけ

    ok = ng = 0
    for k in todo:
        if spent + est > args.budget_usd:
            print(f"[{k}] 予算上限に達するため停止（累計 ${spent:.3f} + 見込み ${est:.3f} > ${args.budget_usd:.2f}）")
            ng += 1
            break
        print(f"[{k}] 生成中 {IDEAS[k]['name']} ...", flush=True)
        rec = generate_one(client, args, k, est)
        append_log(rec)
        spent += float(rec.get("cost_usd") or 0)
        if rec["status"] == "ok":
            ok += 1
            print(f"[{k}] OK {rec['bytes'] // 1024}KB 実費 ${rec['cost_usd']:.4f}（{rec['cost_source']}）{rec['seconds']}s")
        else:
            ng += 1
            print(f"[{k}] NG {rec.get('error', '')}")
    print(f"完了: 成功 {ok} / 失敗 {ng} / 今回までの累計費用 ${spent:.3f}")
    if ng:
        sys.exit(1)


# ---------- process ----------


def crop_ratio(im: Image.Image) -> Image.Image:
    """中央を基準に 2.4:1 へ切り抜く。"""
    im = im.convert("RGB")
    w, h = im.size
    if w * RATIO_H >= h * RATIO_W:  # 横に長すぎる → 左右を切る
        nw, nh = round(h * RATIO_W / RATIO_H), h
    else:  # 縦に長い → 上下を切る
        nw, nh = w, round(w * RATIO_H / RATIO_W)
    left, top = (w - nw) // 2, (h - nh) // 2
    return im.crop((left, top, left + nw, top + nh))


def encode(im: Image.Image) -> tuple[bytes, int]:
    """250KB 以下になる最大の品質で JPEG にする。メタデータは付けない。収まらなければ品質 -1 を返す。"""
    clean = Image.new("RGB", im.size)
    clean.paste(im)
    last = b""
    for q in range(JPEG_Q_START, JPEG_Q_MIN - 1, -2):
        buf = io.BytesIO()
        clean.save(buf, "JPEG", quality=q, optimize=True, progressive=True, subsampling="4:2:0")
        last = buf.getvalue()
        if len(last) <= MAX_BYTES:
            return last, q
    return last, -1


def cmd_process(args) -> None:
    keys = parse_only(args.only)
    ng = 0
    print(f"{'案':<4}{'元サイズ':<12}{'出力':<12}{'JPEG':<10}{'品質':<6}結果")
    for k in keys:
        src = RAW_DIR / f"{k}.png"
        if not src.exists():
            print(f"{k:<4}{'-':<12}{'-':<12}{'-':<10}{'-':<6}元画像なし")
            ng += 1
            continue
        with Image.open(src) as im:
            src_size = f"{im.size[0]}x{im.size[1]}"
            cropped = crop_ratio(im)
        if cropped.size[0] > OUT_WIDTH:
            cropped = cropped.resize((OUT_WIDTH, round(OUT_WIDTH * RATIO_H / RATIO_W)), Image.LANCZOS)
        data, q = encode(cropped)
        out_size = f"{cropped.size[0]}x{cropped.size[1]}"
        if q < 0:
            print(f"{k:<4}{src_size:<12}{out_size:<12}{len(data) / 1000:<10.1f}{'q<' + str(JPEG_Q_MIN):<6}NG: {MAX_BYTES // 1000}KB 超え")
            ng += 1
            continue
        dest = DEST_DIR / f"autumn-{k}.jpg"
        if not args.dry_run:
            DEST_DIR.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        result = "dry-run" if args.dry_run else f"書き込み {dest.relative_to(REPO_ROOT)}"
        print(f"{k:<4}{src_size:<12}{out_size:<12}{f'{len(data) / 1000:.1f}KB':<10}{'q' + str(q):<6}{result}")
    if ng:
        print(f"NG {ng} 件", file=sys.stderr)
        sys.exit(1)


# ---------- sheet ----------


def cmd_sheet(args) -> None:
    keys = parse_only(args.only)
    cell_w = 640
    label_h = 56
    gap = 16
    images: list[tuple[str, Image.Image]] = []
    for k in keys:
        path = DEST_DIR / f"autumn-{k}.jpg"
        if not path.exists():
            raise SystemExit(f"{path} が無い。先に process を実行する")
        with Image.open(path) as im:
            im = im.convert("RGB")
            h = round(cell_w * im.size[1] / im.size[0])
            images.append((k, im.resize((cell_w, h), Image.LANCZOS)))
    cell_h = max(im.size[1] for _, im in images)
    width = cell_w * len(images) + gap * (len(images) + 1)
    height = cell_h + label_h + gap * 2
    sheet = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=22)
    for i, (k, im) in enumerate(images):
        x = gap + i * (cell_w + gap)
        sheet.paste(im, (x, gap))
        size_kb = (DEST_DIR / f"autumn-{k}.jpg").stat().st_size / 1000
        draw.text((x, gap + cell_h + 8), f"{k.upper()}  autumn-{k}.jpg  {size_kb:.0f}KB", fill=(34, 34, 34), font=font)
    SHEET_PATH.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(SHEET_PATH, "JPEG", quality=85)
    print(f"{len(images)} 案を {SHEET_PATH} に書いた（{width}x{height}）")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="トップの NEW ARRIVALS 帯用の秋の背景画像（3 案）を作る",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_gen = sub.add_parser("gen", help="OpenAI で生成して out/hero/raw/ に保存する")
    p_gen.add_argument("--only", help="作る案をカンマ区切りで（a,b,c）。省略時は全件")
    p_gen.add_argument("--force", action="store_true", help="既にある画像も作り直す")
    p_gen.add_argument("--dry-run", action="store_true", help="API を呼ばず、依頼文と推定費用だけ表示する")
    p_gen.add_argument("--budget-usd", type=float, default=0.6, help="累計費用の上限（USD）。out/hero/log.jsonl の過去分を含む")
    p_gen.add_argument("--model", default=DEFAULT_MODEL)
    p_gen.add_argument("--quality", default=DEFAULT_QUALITY, help="low / medium / high（2.5 系は xhigh / max も）")
    p_gen.add_argument("--size", default=DEFAULT_SIZE, help="WxH。2.4:1 は 1920x800。拒否されたら 1536x1024")
    p_gen.add_argument("--timeout", type=float, default=240.0, help="1 リクエストの待ち秒数")
    p_gen.set_defaults(func=cmd_gen)

    p_proc = sub.add_parser("process", help="2.4:1 に切り抜き、JPEG にして apps/web/public/hero/ に書く")
    p_proc.add_argument("--only", help="処理する案をカンマ区切りで。省略時は全件")
    p_proc.add_argument("--dry-run", action="store_true", help="書き込まず、サイズの一覧だけ出す")
    p_proc.set_defaults(func=cmd_process)

    p_sheet = sub.add_parser("sheet", help="3 案を横に並べた確認画像 out/hero/contact_sheet.jpg を作る")
    p_sheet.add_argument("--only", help="載せる案をカンマ区切りで。省略時は全件")
    p_sheet.set_defaults(func=cmd_sheet)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
