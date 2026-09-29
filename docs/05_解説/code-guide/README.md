# GUapp コード解説書・リポジトリ地図 組み立て基盤

コードレビュー中に読む解説書 HTML を、`content/*.html`（本文）と `template.html`（外枠・CSS・JS）から組み立てる。
本文中のコード参照（関数名など）をクリックすると、右からドロワーが開き、該当コードを行番号付きで表示する。
フロー図の各ステップも同様にクリックでコードが開く。「流れを再生」で処理の順番がアニメーションで追える。

同じ `build.py` に `--map` を付けると、IDE の横に開いて「どこに何があって、どういう中身か」を引く **リポジトリ地図**（`GU_ECsite_リポジトリ地図.html`）を組み立てる。作り方は末尾の「リポジトリ地図」を参照。

## 使い方

リポジトリルートから実行する（スクリプト位置からルートを解決するので、どこから実行しても動く）。

```bash
python3 docs/05_解説/code-guide/build.py                    # origin/main の完全 SHA で組み立て
python3 docs/05_解説/code-guide/build.py --check            # 出力を書かず、参照と構造だけ検証
python3 docs/05_解説/code-guide/build.py --commit <SHA>     # 対象コミットを指定
python3 docs/05_解説/code-guide/build.py --include-sample   # content/00-*.html（サンプル）も取り込む
```

- 出力: `docs/05_解説/GU_ECsite_コード解説.html`
- コードは作業ツリーではなく `git show <sha>:<path>` で読む。GitHub のパーマリンクと中身が一致する
- 解決できない参照が 1 つでもあれば、`ファイル:行: 参照 → 理由` の一覧を出して exit 1
- `content/00-` で始まるファイルは `--include-sample` のときだけ取り込む
- 標準出力に章数・参照数・ユニークスニペット数・出力サイズを出す
- 検証用の追加オプション: `--content-dir <dir>`（本文ディレクトリの差し替え）、`--out <path>`（出力先の差し替え）
- `--map-url <URL>`: ヘッダーの「リポジトリ地図」リンクの向き先（既定: `GU_ECsite_リポジトリ地図.html`。同じフォルダ）

本番の再ビルド前には `git fetch origin` で `origin/main` を最新にする。

## ファイル構成

| パス | 役割 |
|---|---|
| `build.py` | 組み立てスクリプト（標準ライブラリのみ） |
| `template.html` | 解説書の外枠。CSS・JS・ヘッダー・目次。プレースホルダは `{{CONTENT}}` `{{TOC}}` `{{SNIPPETS_JSON}}` `{{SNIPPETS_CODE}}` `{{COMMIT}}` `{{COMMIT_FULL}}` `{{BUILD_DATE}}` `{{MAP_URL}}`。`{{PARTIAL:名前}}` は `partials/名前` の中身に置き換わる |
| `content/NN-*.html` | 本文。ファイル名順に連結される |
| `content/00-sample.html` | 動作確認用サンプル（`--include-sample` のときだけ入る） |
| `partials/tokens.css` | デザイントークン（ライト/ダークの色・フォント）。解説書と地図で共通 |
| `partials/drawer.css` | コード参照チップ・コードドロワー・hljs の CSS。共通 |
| `partials/drawer.js` | コード参照・ドロワー・ホバーのツールチップ・hljs 読み込みの JS。共通（IIFE の中に差し込む） |
| `map/template-map.html` | 地図の外枠（CSS・JS・ヘッダー・全体図・ツリー・説明パネル） |
| `map/descriptions.json` | 地図の説明データの本番ファイル（説明担当が作る） |
| `map/sample.json` | 地図の動作確認用サンプル（最終出力には使わない） |

## 本文の書き方の約束

### 章の構造

各ファイルは `<section id="sNN" data-title="章タイトル">` で始め、`<h2>` と `<h3 id="...">` を含める。
目次は section の `data-title` と、`id` 付きの `<h3>` から自動生成される。`id` は全ファイルを通して重複させない（重複はビルドエラー）。
章番号は本文側の `<h2>` に書く（例: `<h2>3. 注文確定の流れ</h2>`）。装飾で番号は付かない。

```html
<section id="s03" data-title="注文確定">
<h2>3. 注文確定</h2>
<h3 id="s03-flow">処理の流れ</h3>
…
</section>
```

### data-ref 構文

| 形式 | 意味 |
|---|---|
| `path::Symbol` | シンボル単位 |
| `path#L10-40` / `path#L10` | 行範囲 |
| `path` | ファイル全体（YAML・シェル・md も可） |

`path` はリポジトリルートからの相対パス（例: `apps/api/app/services/orders.py`）。

**Python（.py）**: ast でトップレベルの `def` / `async def` / `class` を解決する。`Class.method` も可（`AppError.to_body`）。範囲はデコレータ行から `end_lineno` まで。拡張としてトップレベルの定数代入（`NAME = ...`）も引ける。

**TS / TSX / JS**: 次の宣言を行頭（先頭の空白可）で探す。

- `export default function Name`（`async` 可）
- `export function Name` / `export async function Name` / `function Name` / `async function Name`
- `const Name` / `let Name`（`export` 可）
- `interface` / `type` / `class` / `enum` の `Name`（`export` 可）

終わりの決め方は次のとおり。

- 宣言以降で最初に現れる本体の `{` から波括弧の対応を取った行。関数の引数の分割代入 `({ a, b }: Props)`、戻り値型の `{...}`、ジェネリクス内の `{...}` は本体とみなさない
- 波括弧が無い 1 文（`const X = "..."`）は `;` で終わる行。`;` が無い書き方は、行末が式の途中でなければ次行で打ち切る
- 文字列・テンプレートリテラル・コメント・正規表現リテラル内の括弧は無視する
- 同名が複数ある場合は、行頭（インデント 0）の宣言のうち最初のもの。無ければ最初のもの

`export default proxy;` のように後段で default export している場合は、宣言側の名前（`proxy`）で引く。

**拡張子 → lang**: py→python, ts/tsx→typescript, js/mjs→javascript, yml/yaml→yaml, sh→bash, sql→sql, json→json, toml→ini, md→markdown, css→css, html→xml。それ以外は plaintext。

**スニペット**: `path, symbol, start, end, lang, code, url, note` を持つ。`url` は `https://github.com/nonooktk/GUapp/blob/<SHA>/<エンコード済み path>#L<start>-L<end>`。同じ参照は 1 回だけ保持する。`data-note` は最初に現れたものが既定の見どころになり、クリックした要素自身の `data-note` があればそれを優先して表示する。

### インライン参照

```html
<a class="ref" data-ref="apps/api/app/services/orders.py::_confirm" data-note="見どころの一言">_confirm</a>
```

Tab で移動し、Enter / Space で開ける（JS が `role="button" tabindex="0"` を付ける）。リンクテキストはシンボル名などの短い名前にする。

### フロー図

```html
<div class="flow" data-title="注文確定の流れ">
  <div class="flow-step" data-ref="apps/web/proxy.ts::proxy" data-layer="bff">
    <strong>見出し</strong>
    <p>説明</p>
  </div>
  …
</div>
```

- `data-layer`: `screen` / `bff` / `api` / `service` / `repo` / `db` / `ci` / `infra`。左端の色、レイヤー名、凡例（図の上に自動表示）に使われる
- `data-ref` は省略可。あればクリックでドロワーが開き、カードにシンボル名が出る
- 見出し横の「流れを再生」ボタン、番号、ステップ間の線は JS が付ける。本文側では書かない
- 再生中にステップをクリックすると停止してそのコードを開く

### 構成図

```html
<div class="arch">
  <div class="arch-node" data-layer="browser"><strong>ブラウザ</strong><p>説明</p></div>
  <div class="arch-link">HTTPS</div>
  <div class="arch-node" data-layer="web" data-ref="apps/web/proxy.ts::proxy">…</div>
  <div class="arch-link">内部 HTTP</div>
  <div class="arch-node" data-layer="api">…</div>
</div>
```

`arch-node` と `arch-link` を交互に並べる。`data-layer` は `browser` / `web` / `api` / `db` / `infra`（フロー図のレイヤー名も使える）。横並びで、幅 640px 未満は縦並び。矢印は CSS が描く。`data-ref` を付けたノードはクリックでコードが開く。

### 注記

```html
<div class="note fact"><p>事実の記述</p></div>
<div class="note opinion"><p>意見の記述</p></div>
<div class="note warn"><p>注意の記述</p></div>
```

「事実」「意見」「注意」のラベルは CSS が自動で付ける。本文に「事実:」と書き足さない。

### バッジ

```html
<span class="sev high">高</span> <span class="sev mid">中</span> <span class="sev low">低</span>
<span class="status fix">当日までに直す</span>
<span class="status oral">口頭で返す</span>
<span class="status known">設計書で既知</span>
<span class="status todo">未着手</span>
<span class="status done">実装済み</span>
<span class="req">F-012</span> <span class="tid">IT-014-03</span>
<span class="layer" data-layer="api">API</span>
```

### 表

```html
<div class="table-wrap">
<table class="filterable">…</table>
</div>
```

`class="filterable"` を付けると、表の直前（`.table-wrap` があればその直前）に絞り込み入力欄（`id="filter-<n>"`）を自動で挿入し、行を `hidden` で絞る。スペース区切りは AND 検索。狭い画面では表が `.table-wrap` の中だけで横スクロールする。

### Q&A

```html
<details class="qa">
  <summary><span class="qa-time">0〜1分</span>質問</summary>
  <div class="qa-body">
    <p>回答</p>
    <div class="followup"><p class="followup-q">追撃: …</p><p>回答</p></div>
  </div>
</details>
```

### 直書きコード

参照ではなく本文に直接書く短い例（SQL など）。`<` `&` は HTML エスケープする。

```html
<pre class="code" data-lang="sql">SELECT 1;</pre>
```

### そのほか使える部品（姉妹文書と共通）

`.metaphor`（たとえ話）、`.why`（なぜ）、`.grid2` と `.box`、`dl.glossary`、`td.num`。いずれも `<div class="metaphor"><div class="tag">たとえるなら</div><p>…</p></div>` の形。

## ドロワーの操作

- 参照をクリック → 右から（幅 720px 未満は下から）パネルが開く。パス・シンボル・行範囲・見どころ・GitHub リンクを表示
- 「パスをコピー」: クリップボードに失敗したらパスを選択状態にする
- Esc、背景クリック、×で閉じる。閉じるとフォーカスは元の参照に戻る
- ドロワーが開いている間に背景の下にある別の参照をクリックすると、閉じずに切り替わる。「戻る」で直前の参照へ戻れる
- 開いている参照にはリンク側にも印が付く。PC ではホバー 250ms 後に `path:L10-40` のツールチップが出る

## 既知の制限

- ハイライトは cdnjs の highlight.js 11.9.0 を使う。読み込めない環境（オフライン等）ではハイライトなしの素のテキストで表示する
- TS の終端検出は字句レベルの近似。JSX 本文中の `'` `"` は行末で打ち切って読み進める。正規表現リテラルは直前の記号による判定なので、特殊な書き方では外れる可能性がある（本リポジトリの `apps/web` の宣言 435 件は実際に検証済み）
- TS のシンボル指定は、宣言の直前の JSDoc・コメントを範囲に含めない
- TS の `Class.method`、Python 以外のシンボル指定（yaml 等）は未対応。必要なら `#L` 範囲で指定する
- `type X = {...} | {...}` のように波括弧の後ろへ式が続く型は、最初の `}` の行で終わる
- スニペットは全件を HTML に埋め込むため、参照数が増えるとファイルが大きくなる
- スニペットのコード本体は JSON に入れず、`<script type="text/plain" data-snippet="キー">` に原文のまま置く（JSON 化すると `"` が `\"` になるなど原文と違う文字列になり、detect-secrets がリポジトリ本体では出ない誤検知を出したため）。メタ情報（path・行範囲・URL など）は `<script type="application/json" id="snippets-data">` に 1 件ずつ改行して置く。script の終端・HTML コメントに見える並びだけ、`<` の直後にバックスラッシュを 1 つ足して埋め込み、ページ側で 1 つ引いて戻す（可逆）
- ヘッダーの目次（狭い画面）は全 h3 を展開する。広い画面のサイドバーは現在の章の h3 だけを展開する

---

# リポジトリ地図（`--map`）

IDE のエクスプローラーの横に開いて、フォルダ・ファイルごとに「何が入っていて、どう使うか」を引く HTML。ツリーは git から自動で作り、説明は JSON から差し込む。

## 作り方

```bash
python3 docs/05_解説/code-guide/build.py --map                                   # 説明は map/descriptions.json
python3 docs/05_解説/code-guide/build.py --map --map-data docs/05_解説/code-guide/map/sample.json   # 動作確認（サンプル）
python3 docs/05_解説/code-guide/build.py --map --check                          # 出力を書かず検証だけ
python3 docs/05_解説/code-guide/build.py --map --tree-commit HEAD --commit <SHA> --guide-url GU_ECsite_コード解説.html
```

- 出力: `docs/05_解説/GU_ECsite_リポジトリ地図.html`（`--out` で差し替え可）
- `--map-data`: 説明データ。既定 `code-guide/map/descriptions.json`。無ければ exit 1
- `--tree-commit`: ツリー（フォルダ・ファイルの一覧）を作るコミット。既定 `HEAD`（ブランチ上の新しい docs も載る）。`git ls-tree -r -l -z` で読むので日本語パスもそのまま扱える
- `--commit`: プレビュー（中身）を読むコミット。既定 `origin/main` の完全 SHA。`--tree-commit` にだけあって `--commit` に無いファイルは、ツリー側のコミットから読む（GitHub リンクもそのコミットを指す）
- `--guide-url`: 地図から解説書へのリンク先。既定 `GU_ECsite_コード解説.html`（同じフォルダ）。説明データの `guide` の値（例 `s03-cart`）は `<guide-url>#<id>` のリンクになる
- `--content-dir`: `guide` の id を照合する解説書の本文（既定 `code-guide/content`）
- 解説書のヘッダーから地図へ飛ぶリンクは、解説書のビルドで `--map-url` を指定する。地図を先に作り、解説書も作り直すと両方向でつながる

標準出力に、ディレクトリ数・ファイル数・説明ありのディレクトリ数/全体・プレビュー埋め込みファイル数・出力サイズを出す。

## 検証

| 種別 | 内容 | 結果 |
|---|---|---|
| エラー | `nodes` のキーがツリーに無い | exit 1（一覧を表示） |
| エラー | `blocks` の `path` がツリーに無い、`layer` が値の候補外、`id` が空・重複 | exit 1 |
| エラー | `ref`（`nodes[*].ref` と、説明 HTML 中の `data-ref`）が解決できない | exit 1 |
| 警告 | 説明の無いディレクトリ（件数つき。`collapse` 配下は除く） | exit 0 |
| 警告 | `key_files` がツリーに無い、`collapse` の `path` がディレクトリに無い、`guide` の id が解説書に無い | exit 0 |

パスは前後の `/` と先頭の `./` を取って解釈する。

## descriptions.json のスキーマ

```json
{
  "intro_html": "<p>ページ冒頭のリード（任意）</p>",
  "blocks": [
    {"id": "web", "path": "apps/web", "title": "apps/web", "subtitle": "画面と BFF（Next.js）", "summary": "1〜2 文", "layer": "web"}
  ],
  "nodes": {
    "apps/web": {
      "role": "一言の役割（ツリーの行の右に薄く出す。20 字以内目安）",
      "body_html": "<p>中身の説明。HTML 可（p, ul, li, code, strong, a.ref）</p>",
      "open_when": ["こういうときに開く", "..."],
      "key_files": ["apps/web/proxy.ts", "apps/web/lib/server/api.ts"],
      "guide": ["s01", "s03-cart"]
    },
    "apps/web/proxy.ts": {"role": "...", "body_html": "...", "ref": "apps/web/proxy.ts::proxy"}
  },
  "collapse": [{"path": "apps/web/public/products", "label": "商品画像 31 枚（ファイル名は商品 ID）"}],
  "tips_html": "<h3>IDE で探すときのコツ</h3><p>...</p>"
}
```

| キー | 意味 |
|---|---|
| `intro_html` | ページ冒頭のリード。省略時は既定の一文 |
| `blocks[]` | 全体図のカード。IDE のルートの並び（フォルダ→名前順）に自動で並べ替える。`path` が `""`（または `.`）のブロックはルート直下のファイル用で、最後に置く。`layer` は `web` `api` `docs` `scripts` `ci` `root`（色分け）。中身の小さなラベル（サブフォルダ名）はツリーから自動で取る。ファイル 60 件以上のブロックは大きめに表示する |
| `nodes{パス}` | フォルダ・ファイルの説明。キーはリポジトリルートからの相対パス。全項目が任意 |
| `nodes.*.role` | 一言の役割。ツリーの行に薄く出る。説明パネルでは見出し的に出る |
| `nodes.*.body_html` | 本文の HTML。`<a class="ref" data-ref="path::Symbol">名前</a>` は解説書と同じ記法で解決され、クリックでコードドロワーが開く |
| `nodes.*.open_when` | 「こういうときに開く」の箇条書き（プレーンテキスト） |
| `nodes.*.key_files` | 「主なファイル」。押すとツリーでそのファイルを選択する。ツリーに無いパスはリンク無しで出す |
| `nodes.*.guide` | 解説書の id（章 `sNN`、見出し `sNN-xxx`）。「解説書の関連章」に新しいタブのリンクで出る |
| `nodes.*.ref` | ファイルの「主な関数を見る」ボタンで開く `data-ref` 記法の参照 |
| `collapse[]` | 子を展開せず 1 行（ラベル＋件数）にまとめるディレクトリ |
| `tips_html` | ページ下部のコツ。省略可 |

説明の無いノードでも、件数・拡張子の内訳・行数は自動集計して出す。

## ページの動き

- 全体図のカード（とサブフォルダの小さなラベル）を押すと、下のツリーで該当フォルダまで開いてスクロール・選択し、右パネルに説明を出す
- ツリー: フォルダ→ファイルの順、名前順。先頭ドットのファイルも出る。↑↓ で移動、← で閉じる（閉じていれば親へ）、→ で開く（開いていれば最初の子へ）、Enter で選択、Home/End で先頭・末尾。行の右に `role` と、フォルダは配下のファイル数
- 絞り込み: パスの部分一致（スペース区切りは AND、全角半角・大文字小文字を区別しない）。ヒットした行とその祖先だけ表示し、Esc で解除
- 説明パネル: パンくず（各段を押すとその階層を選択）、`role`、本文、こういうときに開く、主なファイル、解説書の関連章、件数・拡張子の内訳（フォルダ）または行数・サイズ（ファイル）、中身を見る・主な関数を見る・GitHub・パスをコピー。760px 未満はパネルがツリーの下に来るので、ツリー上部の「説明へ ↓」で移動できる
- 選択状態はページ内だけで持つ。URL のハッシュにパスは入れない

## プレビュー（中身を見る）の対象

ファイルの中身を埋め込むのは、テキストで 200KB 以下の次のもの。

- `apps/**`（ただし `apps/api/tests/**`・`apps/web/tests/**`・`apps/web/public/**` を除く）、`scripts/**`、`tools/**`、`.github/**`
- `docs/**/*.md`
- ルートの `README.md`・`docker-compose.yml`・`.pre-commit-config.yaml`・`.gitignore`・`.gitattributes`

対象外（説明と行数だけ表示し、理由を出す）: `.env*`（中身は読まず、行数も出さない）、`.secrets.baseline`・`.gitleaks.toml`・`.gitleaksignore`、テスト、画像、docx などのバイナリ、`.html`（解説書・地図の出力）、200KB 超（例: `uv.lock`）、上記以外のファイル（`.claude/` など）。

## 秘密検査

出力 HTML は `gitleaks detect --no-git --source <file> --redact` と `pre-commit run detect-secrets --files <file>` を通す。埋め込みコードを原文のまま置く理由は、上の「既知の制限」のとおり。40 桁の SHA 単体も検知されるため、地図のデータでは GitHub の URL の形で持つ。説明データに新しい文字列を足して検出が出たら、まず誤検知かどうかを確認し、プレビュー対象から外す（`PREVIEW_*` 定数と `preview_reason()`）。

## 既知の制限（地図）

- ツリーは `--tree-commit` の内容、プレビューは `--commit` の内容で、作業ツリーの未コミットの変更は載らない
- `collapse` したディレクトリの中は、ツリーからは辿れない（絞り込みで中のパスにヒットすると、その 1 行が出る）
- 行数はテキストファイルのみ。`.env*` と画像・バイナリは出さない
- ブロックの並びは「フォルダ→名前順」の近似（IDE 側の並べ替え設定が違うと一致しない）
- ハイライトは cdnjs の highlight.js 11.9.0 に依存する（読み込めない環境では素のテキスト）
