#!/usr/bin/env python3
"""31 枚を番号と商品名つきで並べた確認用 HTML（out/contact_sheet.html）を作る。

画像は HTML からの相対パスで参照する（file:// でそのまま開ける）。
- 既定（--source final）: apps/web/public/products/NNN/1.jpg（最終の JPEG）
- --source raw: out/raw/NNN.png（process.py の前に、生成したままの絵を見る用）

実行例:
  uv run --with openai --with pillow python scripts/images/contact_sheet.py
  uv run --with openai --with pillow python scripts/images/contact_sheet.py --source raw --only 011,004,027
"""

from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
PROMPTS_PATH = HERE / "prompts.json"
OUT_HTML = HERE / "out" / "contact_sheet.html"
RAW_DIR = HERE / "out" / "raw"
FINAL_ROOT = REPO_ROOT / "apps" / "web" / "public" / "products"
MAX_BYTES = 80_000


def card(item: dict, source: str) -> str:
    pid = item["id"]
    path = RAW_DIR / f"{pid}.png" if source == "raw" else FINAL_ROOT / pid / "1.jpg"
    title = f"{pid} {html.escape(item['name'])}"
    if not path.exists():
        return f'<figure><div class="ph">未生成</div><figcaption><b>{title}</b></figcaption></figure>'
    with Image.open(path) as im:
        w, h = im.size
    size = path.stat().st_size
    notes = []
    if source == "final":
        if (w, h) == (8, 8):
            notes.append("仮画像（8x8）のまま")
        elif (w, h) != (800, 1000):
            notes.append(f"サイズ不一致 {w}x{h}")
        if size > MAX_BYTES:
            notes.append("80KB 超え")
    note_html = "".join(f'<span class="warn">{html.escape(n)}</span>' for n in notes)
    rel = os.path.relpath(path, OUT_HTML.parent).replace(os.sep, "/")
    return (
        f'<figure><a href="{html.escape(rel)}" target="_blank"><img src="{html.escape(rel)}" loading="lazy" alt="{title}"></a>'
        f"<figcaption><b>{title}</b><br>{html.escape(item['color_name_ja'])} / {html.escape(item['category'])}"
        f'<br><span class="meta">{w}x{h} / {size / 1000:.1f}KB</span>{note_html}</figcaption></figure>'
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="商品画像の確認用 HTML（コンタクトシート）を作る")
    ap.add_argument("--source", choices=["final", "raw"], default="final")
    ap.add_argument("--only", help="載せる番号をカンマ区切りで。省略時は全件")
    args = ap.parse_args()

    items = json.loads(PROMPTS_PATH.read_text(encoding="utf-8"))
    if args.only:
        wanted = {s.strip().zfill(3) for s in args.only.split(",") if s.strip()}
        items = [it for it in items if it["id"] in wanted]
    cards = "\n".join(card(it, args.source) for it in items)
    label = "最終 JPEG（apps/web/public/products）" if args.source == "final" else "生成直後の PNG（out/raw）"
    doc = f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>商品画像の確認シート</title>
<style>
body{{font-family:system-ui,sans-serif;margin:16px;background:#fff;color:#222}}
h1{{font-size:18px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:16px}}
figure{{margin:0;border:1px solid #ddd;border-radius:6px;padding:8px}}
img{{width:100%;aspect-ratio:4/5;object-fit:contain;background:#f2f2f2;display:block}}
.ph{{aspect-ratio:4/5;background:#eee;color:#999;display:flex;align-items:center;justify-content:center}}
figcaption{{font-size:12px;line-height:1.5;margin-top:6px}}
.meta{{color:#666}}
.warn{{display:block;color:#b00020;font-weight:bold}}
</style></head><body>
<h1>商品画像の確認シート（{len(items)} 件 / {label}）</h1>
<div class="grid">
{cards}
</div></body></html>
"""
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(doc, encoding="utf-8")
    print(f"{len(items)} 件を {OUT_HTML} に書いた（source={args.source}）")


if __name__ == "__main__":
    main()
