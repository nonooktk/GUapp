# GUapp コード解説書 組み立て基盤

コードレビュー中に読む解説書 HTML を、`content/*.html`（本文）と `template.html`（外枠・CSS・JS）から組み立てる。
本文中のコード参照（関数名など）をクリックすると、右からドロワーが開き、該当コードを行番号付きで表示する。
フロー図の各ステップも同様にクリックでコードが開く。「流れを再生」で処理の順番がアニメーションで追える。

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

本番の再ビルド前には `git fetch origin` で `origin/main` を最新にする。

## ファイル構成

| パス | 役割 |
|---|---|
| `build.py` | 組み立てスクリプト（標準ライブラリのみ） |
| `template.html` | 外枠。CSS・JS・ヘッダー・目次。プレースホルダは `{{CONTENT}}` `{{TOC}}` `{{SNIPPETS_JSON}}` `{{COMMIT}}` `{{COMMIT_FULL}}` `{{BUILD_DATE}}` |
| `content/NN-*.html` | 本文。ファイル名順に連結される |
| `content/00-sample.html` | 動作確認用サンプル（`--include-sample` のときだけ入る） |

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
- ヘッダーの目次（狭い画面）は全 h3 を展開する。広い画面のサイドバーは現在の章の h3 だけを展開する
