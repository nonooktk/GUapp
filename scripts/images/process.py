#!/usr/bin/env python3
"""out/raw/NNN.png を 800x1000（縦 4:5）の JPEG にして apps/web/public/products/NNN/1.jpg に書く。

- 既定は中央基準の切り抜き（cover）。--fit pad にすると切らずに背景色 #F2F2F2 で余白を埋める。
- JPEG は品質を 92 から下げながら 80KB（80,000 バイト）以下に収める。メタデータ（EXIF・ICC など）は付けない。
- 80KB に収まらない画像があれば一覧に NG と出して終了コード 1 にする（書き込みはしない）。

実行例:
  uv run --with openai --with pillow python scripts/images/process.py
  uv run --with openai --with pillow python scripts/images/process.py --only 011,004 --dry-run
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
RAW_DIR = HERE / "out" / "raw"
DEST_ROOT = REPO_ROOT / "apps" / "web" / "public" / "products"

W, H = 800, 1000
BG = (0xF2, 0xF2, 0xF2)
MAX_BYTES = 80_000
Q_START, Q_MIN = 92, 40


def fit_image(im: Image.Image, mode: str) -> Image.Image:
    im = im.convert("RGB")
    sw, sh = im.size
    if mode == "cover":
        scale = max(W / sw, H / sh)
        nw, nh = round(sw * scale), round(sh * scale)
        im = im.resize((nw, nh), Image.LANCZOS)
        left, top = (nw - W) // 2, (nh - H) // 2
        return im.crop((left, top, left + W, top + H))
    scale = min(W / sw, H / sh)
    nw, nh = round(sw * scale), round(sh * scale)
    im = im.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGB", (W, H), BG)
    canvas.paste(im, ((W - nw) // 2, (H - nh) // 2))
    return canvas


def encode(im: Image.Image) -> tuple[bytes, int]:
    """80KB 以下になる最大の品質で JPEG にする。メタデータは渡さない（Pillow は既定で付けない）。"""
    clean = Image.new("RGB", im.size)
    clean.paste(im)  # 元の info（EXIF・ICC など）を持ち越さない
    last = b""
    for q in range(Q_START, Q_MIN - 1, -2):
        buf = io.BytesIO()
        clean.save(buf, "JPEG", quality=q, optimize=True, progressive=True, subsampling="4:2:0")
        last = buf.getvalue()
        if len(last) <= MAX_BYTES:
            return last, q
    return last, -1  # 収まらなかった


def main() -> None:
    ap = argparse.ArgumentParser(description="生成画像を 800x1000 の JPEG（80KB 以下）にして商品フォルダへ書く")
    ap.add_argument("--only", help="処理する番号をカンマ区切りで（例 011,004）。省略時は out/raw の全件")
    ap.add_argument("--fit", choices=["cover", "pad"], default="cover", help="cover=中央で切り抜き / pad=余白を背景色で埋める")
    ap.add_argument("--dry-run", action="store_true", help="書き込まず、サイズの一覧だけ出す")
    args = ap.parse_args()

    if args.only:
        ids = [s.strip().zfill(3) for s in args.only.split(",") if s.strip()]
    else:
        ids = sorted(p.stem for p in RAW_DIR.glob("*.png"))
    if not ids:
        raise SystemExit(f"{RAW_DIR} に処理する PNG が無い")

    rows, ng = [], 0
    for pid in ids:
        src = RAW_DIR / f"{pid}.png"
        if not src.exists():
            rows.append((pid, "-", "-", "-", "元画像なし"))
            ng += 1
            continue
        with Image.open(src) as im:
            src_size = f"{im.size[0]}x{im.size[1]}"
            out = fit_image(im, args.fit)
        data, q = encode(out)
        if q < 0:
            rows.append((pid, src_size, f"{len(data) / 1000:.1f}KB", f"q<{Q_MIN}", f"NG: {MAX_BYTES // 1000}KB 超え"))
            ng += 1
            continue
        dest = DEST_ROOT / pid / "1.jpg"
        if not args.dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
        rows.append((pid, src_size, f"{len(data) / 1000:.1f}KB", f"q{q}", "dry-run" if args.dry_run else f"書き込み {dest.relative_to(REPO_ROOT)}"))

    print(f"{'番号':<5}{'元サイズ':<12}{'JPEG':<10}{'品質':<7}結果")
    for r in rows:
        print(f"{r[0]:<5}{r[1]:<12}{r[2]:<10}{r[3]:<7}{r[4]}")
    sizes = [float(r[2][:-2]) for r in rows if r[2].endswith("KB")]
    if sizes:
        print(f"件数 {len(sizes)} / 最大 {max(sizes):.1f}KB / 合計 {sum(sizes):.1f}KB / 出力 {W}x{H}")
    if ng:
        print(f"NG {ng} 件", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
