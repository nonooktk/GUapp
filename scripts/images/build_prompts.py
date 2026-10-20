#!/usr/bin/env python3
"""商品画像の依頼文（英語）を 31 件作り、prompts.json に出す。

入力: apps/api/app/seed_data.py の PRODUCTS（番号・名前・性別・カテゴリ・1 色目・素材）
出力: scripts/images/prompts.json（1 商品 1 件）

使い方:
  uv run --with openai --with pillow python scripts/images/build_prompts.py
  （標準ライブラリだけで動く。--with は他スクリプトと揃えるための記載）

商品の「何を描くか」は seed の日本語名からは機械的に決められないため、
GARMENTS に商品番号ごとの英語の説明を手で持つ。seed の名前が変わったら
EXPECTED_NAMES の照合で止まる（説明の取り違えを防ぐ）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from app.seed_data import COLORS, PRODUCTS  # noqa: E402

OUT_PATH = Path(__file__).resolve().parent / "prompts.json"

# 色コード → 英語の色の言い方（1 色目だけを使う）
COLOR_EN: dict[str, str] = {
    "BK": "black",
    "WH": "white",
    "NV": "navy blue",
    "GY": "heather gray",
    "BE": "beige",
    "KH": "khaki olive green",
    "BL": "light blue",
    "PK": "soft pink",
}

# 素材の日本語 → 英語
MATERIAL_EN: dict[str, str] = {
    "綿": "cotton",
    "ポリエステル": "polyester",
    "ポリウレタン": "spandex",
    "ナイロン": "nylon",
    "レーヨン": "rayon",
}

# 商品番号 → (seed の名前の確認用, 英語の服の説明)。人物なし・文字なしで描ける形にする
GARMENTS: dict[int, tuple[str, str]] = {
    1: ("スムースコットンT（レディース）", "women's short-sleeve crew-neck t-shirt in smooth cotton jersey, plain, no print"),
    2: ("ソフトリブタンクトップ", "women's soft ribbed tank top, fitted, plain"),
    3: ("オーバーサイズシャツ", "women's oversized long-sleeve button-up shirt with a collar, plain"),
    4: ("ハイウエストストレートジーンズ", "women's high-waisted straight-leg jeans in denim, five-pocket, plain stitching"),
    5: ("イージーワイドパンツ", "women's easy wide-leg pants with an elastic waistband, plain"),
    6: ("フレアロングスカート", "women's long flared skirt, ankle length, plain"),
    7: ("ライトダウンジャケット", "women's lightweight quilted down jacket with a zip front and a stand collar, no hood"),
    8: ("カットソーワンピース", "women's knee-length jersey dress with short sleeves and a round neck, plain"),
    9: ("シアーロングワンピース", "women's long sheer dress with long sleeves and a relaxed fit, plain, lightweight and semi-transparent fabric"),
    10: ("ブラフィールタンクトップ", "women's smooth camisole tank top with a built-in bra, plain, seamless look"),
    11: ("ヘビーウェイトT（メンズ）", "men's heavyweight short-sleeve crew-neck t-shirt in thick cotton jersey, boxy fit, plain, no print"),
    12: ("ドライポロシャツ", "men's short-sleeve polo shirt with a collar and a three-button placket, quick-dry knit"),
    13: ("オックスフォードシャツ", "men's long-sleeve oxford button-down shirt with a plain front and no chest pocket"),
    14: ("スウェットプルパーカ", "men's pullover sweat hoodie with a kangaroo pocket and a drawstring hood, plain, no print"),
    15: ("スリムテーパードジーンズ", "men's slim tapered jeans in denim, five-pocket, plain stitching"),
    16: ("チノショートパンツ", "men's chino shorts, knee length, plain, with side pockets"),
    17: ("ストレッチイージーパンツ", "men's stretch easy pants with an elastic waistband and a drawcord, tapered leg, plain"),
    18: ("MA-1ブルゾン", "men's MA-1 flight bomber jacket with ribbed collar, cuffs and hem, zip front, plain, no patches"),
    19: ("ボアフリースジャケット", "men's zip-front fleece jacket in fluffy sherpa pile, plain"),
    20: ("ドライボクサーブリーフ 2枚組", "a pair of men's boxer briefs, two pieces neatly folded and laid side by side, plain waistband with no text"),
    21: ("プリントT（キッズ）", "child-sized short-sleeve crew-neck t-shirt with one small simple abstract shape print (stars and dots), no letters, no characters"),
    22: ("ボーダーロンT（キッズ）", "child-sized long-sleeve crew-neck t-shirt with horizontal stripes in navy blue and off-white"),
    23: ("スウェットトレーナー（キッズ）", "child-sized crew-neck sweatshirt, long sleeves with ribbed cuffs and hem, plain, no print"),
    24: ("ストレッチデニム（キッズ）", "child-sized stretch denim jeans, five-pocket, plain stitching"),
    25: ("イージーショートパンツ（キッズ）", "child-sized easy shorts with an elastic waistband and a drawcord, plain"),
    26: ("ウルトラライトダウン（キッズ）", "child-sized ultra-light quilted down jacket with a zip front and a stand collar, no hood"),
    27: ("ウィンドブレーカー（キッズ）【V-STOCK1あり】", "child-sized zip-front windbreaker jacket with a hood, plain, no reflective prints"),
    28: ("【P-ALL0】撥水パーカ（キッズ）", "child-sized water-repellent zip-front hooded parka, plain, no prints"),
    29: ("リブレギンス（キッズ）【V-STOCK0あり】", "child-sized ribbed leggings, full length, plain, laid flat"),
    30: ("【P-UNPUB】非公開サンプル商品", "child-sized basic cotton undershirt with short sleeves and a round neck, plain"),
    31: ("ライトジャケット（メンズ）", "men's lightweight zip-front jacket with a stand collar and two welt pockets, plain"),
}

# 全商品に共通のスタイル指定。ここを変えれば 31 件すべてに反映される
STYLE = (
    "Professional e-commerce product photo, flat lay: the single garment is laid flat and "
    "photographed straight from above, front side up, centered, fully visible with no part "
    "cropped, filling about 75 percent of the frame height with even margins. "
    "Background: seamless plain solid light gray (#F2F2F2) surface, no texture, no gradient. "
    "Lighting: soft diffused studio light, gentle natural soft shadow under the garment, "
    "true-to-life fabric texture and color; light-colored garments stay clearly visible against the background thanks to the soft shadow. Portrait composition, 4:5 aspect ratio. "
    "The same photographic style for every item in the catalog."
)

# ブランド・文字の禁止。全件に必ず入れる
FORBIDDEN = (
    "Strict rules: no people, no model, no mannequin, no hands, no body parts, no props, "
    "no hanger, no other garments. Absolutely no text, no letters, no numbers, no logos, "
    "no brand marks, no labels, no tags, no tag stitching, no patches, no emblems, no watermark, "
    "no signature. The design must be generic and must not imitate or resemble any real "
    "clothing brand."
)


def material_en(material_ja: str) -> str:
    """'綿95%・ポリウレタン5%' → '95% cotton, 5% spandex'。'ナイロン100%・中綿ダウン' → '100% nylon, down fill'"""
    parts: list[str] = []
    for chunk in material_ja.split("・"):
        m = re.fullmatch(r"(\D+?)(\d+)%", chunk)
        if m:
            name, pct = m.group(1), m.group(2)
            if name not in MATERIAL_EN:
                raise ValueError(f"未対応の素材名: {name}（MATERIAL_EN に追加する）")
            parts.append(f"{pct}% {MATERIAL_EN[name]}")
        elif chunk == "中綿ダウン":
            parts.append("down fill")
        else:
            raise ValueError(f"素材を解釈できない: {chunk}")
    return ", ".join(parts)


def build_prompt(garment: str, color_en: str, material: str) -> str:
    return (
        f"{STYLE} Subject: {garment}. Main color: {color_en}. "
        f"Fabric: {material}. {FORBIDDEN}"
    )


def build_all() -> list[dict]:
    items: list[dict] = []
    for p in PRODUCTS:
        if p.number not in GARMENTS:
            raise SystemExit(f"GARMENTS に商品 {p.number:03d} の説明が無い")
        expected_name, garment = GARMENTS[p.number]
        if p.name != expected_name:
            raise SystemExit(
                f"商品 {p.number:03d} の名前が seed と合わない: seed={p.name!r} / GARMENTS={expected_name!r}。"
                "説明を見直して GARMENTS を直す"
            )
        color_code = p.colors[0]
        color_en = COLOR_EN[color_code]
        mat = material_en(p.material)
        items.append(
            {
                "id": f"{p.number:03d}",
                "number": p.number,
                "name": p.name,
                "gender": p.gender,
                "category": p.category,
                "color_code": color_code,
                "color_name_ja": COLORS[color_code],
                "color_en": color_en,
                "material_ja": p.material,
                "material_en": mat,
                "prompt": build_prompt(garment, color_en, mat),
            }
        )
    return items


def main() -> None:
    ap = argparse.ArgumentParser(description="商品画像の依頼文（英語）を作って prompts.json に出す")
    ap.add_argument("--out", type=Path, default=OUT_PATH, help=f"出力先（既定 {OUT_PATH}）")
    args = ap.parse_args()

    items = build_all()
    extra = set(GARMENTS) - {p.number for p in PRODUCTS}
    if extra:
        raise SystemExit(f"seed に無い番号が GARMENTS にある: {sorted(extra)}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(items)} 件を {args.out} に書いた")
    for it in items:
        print(f"  {it['id']} {it['name']} / {it['color_en']} / {it['material_en']}")


if __name__ == "__main__":
    main()
