# 商品画像の差し替え（OpenAI 画像生成）

仮の商品画像（8x8 の単色、31 点）を、OpenAI の画像生成で作った絵に差し替えるための道具一式である。
パスは今と同じ `apps/web/public/products/NNN/1.jpg` のままで、DB とコードは変えない。

## 1. 下調べ（確認日 2026-10-20）

事実（公式ドキュメントで確認）:

| 項目 | 内容 | 出典 |
|---|---|---|
| 推奨モデル | 新規の組み込みには GPT Image 2.5 系（`gpt-image-2.5-flare`: 速くて高品質な日常用途／`gpt-image-2.5-sunburst`: 編集精度重視）。旧世代に `gpt-image-2`、`gpt-image-1.5`、`gpt-image-1`、`gpt-image-1-mini` | [Image generation guide](https://developers.openai.com/api/docs/guides/image-generation) |
| エンドポイント | `POST https://api.openai.com/v1/images/generations`（生成）、`/v1/images/edits`（編集）。Batch も可。2.5-flare は Responses / Chat Completions には非対応（Responses の image_generation ツールのモデルとしては使える） | 同上、[gpt-image-2.5-flare](https://developers.openai.com/api/docs/models/gpt-image-2.5-flare) |
| 主なパラメータ | `model`、`prompt`、`n`、`size`、`quality`、`output_format`（png / jpeg / webp。既定 png）、`output_compression`（jpeg・webp のみ 0〜100）、`background`、`moderation` | Image generation guide |
| size | 推奨 `1024x1024` / `1536x1024` / `1024x1536` / `auto`。カスタム `WxH` も可: 幅・高さが 16 の倍数、縦横比 1:3〜3:1、一辺 3840 以下、総画素数 655,360〜8,294,400 | 同上 |
| quality | `low` / `medium` / `high` / `auto`。2.5 系は `xhigh` / `max` も | 同上 |
| 単価（トークン課金・100 万トークンあたり） | 2.5-flare・2.5-sunburst・gpt-image-2 は画像出力 $30、画像入力 $8、テキスト入力 $5（Batch の画像出力は $15） | [gpt-image-2.5-flare](https://developers.openai.com/api/docs/models/gpt-image-2.5-flare)、[Pricing](https://developers.openai.com/api/docs/pricing) |
| 1 枚あたり（公式表。gpt-image-2、1024x1536） | low $0.005 / medium $0.041 / high $0.165（1024x1024 は $0.006 / $0.053 / $0.211） | Image generation guide |
| 1 枚あたり（gpt-image-1.5、1024x1536） | low $0.013 / medium $0.05 / high $0.20 | 同上 |

未確認（意見・推測を含む）:
- 2.5 系の「1 枚あたり」の表は、公式には見つからなかった。公式は「トークン消費は品質で変わるので応答の `usage` で測る」としている。
- 第三者サイトの情報では、2.5 の medium は 1 枚 $0.01 前後（出力 約 340〜440 トークン）だという。この数字は公式のものではないため採用せず、費用の見積もりは gpt-image-2 の表を使って安全側に倒した。実費は、`generate.py` が応答の `usage` から計算して記録する。
- 2.5 系の画質が商品写真として足りるかどうかは、試作 3 枚を見て決める。

## 2. 選んだ設定と 5 ドルの内訳

- モデルは `gpt-image-2.5-flare`、品質は `medium`、サイズは `1024x1280` を選んだ（カスタムサイズで、4:5 ちょうど）。
- サイズの理由: 最終的な大きさが 800x1000（4:5）なので、切り抜きで無駄になる部分が出ない。1024x1536 と比べると、画素数が約 17% 少ない。
- 品質の理由: 最終的には、画像を 800x1000・80KB 以下の JPEG に縮めるため、high の細部は活きない。
- 見積もりの置き方（安全側）: 1 枚あたり $0.053 とする（gpt-image-2 の medium、1024x1024 の値。表のなかで最大）。

| 項目 | 枚数 | 単価（見積） | 小計 |
|---|---|---|---|
| 試作（良ければそのまま採用） | 3 | $0.053 | $0.159 |
| 残りの本番 | 28 | $0.053 | $1.484 |
| 作り直し | 15 | $0.053 | $0.795 |
| 合計 | 46 | | 約 $2.44 |

- 上限 $5.00 に対して、費用が見積もりの約 2.0 倍になるまでは収まる。
- 出力トークンが想定の 2.0 倍まで増えても、上限内に収まる。
- 品質を high にする場合は、見積もりが $0.211 × 46 = 約 $9.7 となり、上限に収まらない。試作で medium では足りなかったときは、気になる商品だけを high にして（`--only` と `--quality high --force` を使う）、上限の管理は予算ガード（`--budget-usd`）に任せる。

## 3. 使い方

作業ディレクトリはリポジトリのルートにする。キーは `--env-file` で渡す（`.env` は開かない）。

```bash
# 1) 依頼文を作る（prompts.json に 31 件）
uv run --with openai --with pillow python scripts/images/build_prompts.py

# 2) 試作 3 件（011 メンズ白Tシャツ / 004 レディースジーンズ / 027 キッズ ウィンドブレーカー）。まず API を呼ばない確認
uv run --with openai --with pillow python scripts/images/generate.py --only 011,004,027 --dry-run

# 3) 試作を生成（API を呼ぶ）
uv run --env-file /Users/mitsuru/GUapp/apps/api/.env --with openai --with pillow python scripts/images/generate.py --only 011,004,027

# 4) 生成したままの絵を確認（HTML を開く）
uv run --with openai --with pillow python scripts/images/contact_sheet.py --source raw --only 011,004,027
open scripts/images/out/contact_sheet.html

# 5) 良ければ残りを生成（既にあるものは飛ばす）。作り直しは --force
uv run --env-file /Users/mitsuru/GUapp/apps/api/.env --with openai --with pillow python scripts/images/generate.py
uv run --env-file /Users/mitsuru/GUapp/apps/api/.env --with openai --with pillow python scripts/images/generate.py --only 014 --force

# 6) 800x1000・80KB 以下の JPEG にして商品フォルダへ書く
uv run --with openai --with pillow python scripts/images/process.py

# 7) 最終の確認シート
uv run --with openai --with pillow python scripts/images/contact_sheet.py
```

- API に `size 1024x1280` を拒否されたら、`--size 1024x1536` を指定して作る。`process.py` が中央を基準にして 4:5 に切り抜く。
- 費用は 1 枚ごとに `out/log.jsonl` へ追記される（`cost_source` が `usage` なら実費）。`--budget-usd` は、過去の累計も含めて上限を超えるかどうかを判定する。`log.jsonl` を消すと、累計が 0 に戻る。
- 生の PNG（`out/raw/`）と `log.jsonl` は `.gitignore` で除外してある。コミットするのは最終の JPEG だけだ。

## 4. ファイル

| ファイル | 役割 |
|---|---|
| `build_prompts.py` | seed_data.py から 31 件の英語の依頼文を作り `prompts.json` に出す。商品ごとの服の説明は `GARMENTS` に持つ（seed の名前と照合） |
| `generate.py` | 画像生成。`--only` / `--force` / `--dry-run` / `--budget-usd` / 1 回だけ再試行 / ログ追記 |
| `process.py` | 切り抜き・縮小・JPEG 化（80KB 以下）・メタデータなし |
| `contact_sheet.py` | 番号と商品名つきの確認用 HTML |
