# GUapp コード解説書・リポジトリ地図 組み立て基盤

コードレビュー中に読む解説書 HTML を、`content/*.html`（本文）と `template.html`（外枠・CSS・JS）から組み立てる。
本文中のコード参照（関数名など）をクリックすると、右からドロワーが開き、該当コードを行番号付きで表示する。
フロー図の各ステップも同様にクリックでコードが開く。「流れを再生」で処理の順番がアニメーションで追える。

同じ `build.py` に `--map` を付けると、IDE の横に開いて「どこに何があって、どういう中身か」を引く **リポジトリ地図**（`GU_ECsite_リポジトリ地図.html`）を組み立てる。作り方は末尾の「リポジトリ地図」を参照。

`--review` を付けると、コードレビュー当日に IDE と並べて使う **レビュー回答ガイド**（`GU_ECsite_レビュー回答ガイド.html`）を組み立てる。本文は `review/*.html`。作り方と本文の部品は「レビュー回答ガイド」の章を参照。

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
- `data-focus`（下の「行番号の自動挿入」）は解説書でも使える（`data-focus-line` を付けるだけで、ドロワーが注目行を強調する）。地図の `body_html` では未対応

本番の再ビルド前には `git fetch origin` で `origin/main` を最新にする。

## ファイル構成

| パス | 役割 |
|---|---|
| `build.py` | 組み立てスクリプト（標準ライブラリのみ） |
| `template.html` | 解説書の外枠。ヘッダー・目次・起動処理（CSS・JS の共通部分は `partials/guide-*` に切り出してある）。プレースホルダは `{{CONTENT}}` `{{TOC}}` `{{SNIPPETS_JSON}}` `{{SNIPPETS_CODE}}` `{{COMMIT}}` `{{COMMIT_FULL}}` `{{BUILD_DATE}}` `{{MAP_URL}}`。`{{PARTIAL:名前}}` は `partials/名前` の中身に置き換わる |
| `content/NN-*.html` | 本文。ファイル名順に連結される |
| `content/00-sample.html` | 動作確認用サンプル（`--include-sample` のときだけ入る） |
| `partials/tokens.css` | デザイントークン（ライト/ダークの色・フォント）。解説書と地図で共通 |
| `partials/drawer.css` | コード参照チップ・コードドロワー・hljs の CSS。共通 |
| `partials/drawer.js` | コード参照・ドロワー・ホバーのツールチップ・hljs 読み込みの JS。共通（IIFE の中に差し込む）。`data-focus-line` があれば注目行を強調してスクロールする |
| `partials/guide-base.css` | 本文まわり（ベース・ヘッダー・目次・表・注記・バッジ・Q&A・直書きコード）の CSS。解説書とレビュー回答ガイドで共通 |
| `partials/guide-diagrams.css` | フロー図・構成図の CSS。同上 |
| `partials/guide-widgets.js` | フロー図・表の絞り込み・目次の現在地の JS（`stopCurrent` もここ）。同上 |
| `review/template-review.html` | レビュー回答ガイドの外枠。順路・行番号・キー・テスト状態バッジ・突き合わせ表・台本ボックスの CSS と、順路の JS を持つ |
| `review/NN-*.html` | レビュー回答ガイドの本文。ファイル名順に連結される（`template*.html` は本文として扱わない） |
| `review/00-sample.html` | レビュー回答ガイドの動作確認用サンプル（`--include-sample` のときだけ入る） |
| `review/translations/*.json` | コードの日本語訳（本番は `t1.json`〜`t3.json`）。`sample.json` は動作確認用 |
| `review/glossary.json` | 用語集（`glossary.sample.json` は動作確認用） |
| `partials/review-aid.css`・`review-aid.js` | 初心者向けの補助（住所・つながり図・重なりの図・用語・対訳・初心者モード）の CSS と JS |
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

# レビュー回答ガイド（`--review`）

コードレビューで、レビュワーが機能を 1 つ指定し、レビュイー（オーナー本人）が ②画面のコードからバックエンドへのリクエストまで ③バックエンドの処理 ④応答から画面表示まで ⑤テスト仕様 1 つとテストコード ⑥テスト条件が仕様書どおりか、を説明する。本人は IDE（VS Code）を見ながら「順路」を手でたどる。そのため、各停留所に **実ファイルの `ファイル:行`** を表示する。行番号は本文に手で書かず、組み立て時に実物から自動で入れる。

## 作り方

```bash
python3 docs/05_解説/code-guide/build.py --review                    # review/*.html → GU_ECsite_レビュー回答ガイド.html
python3 docs/05_解説/code-guide/build.py --review --check            # 出力を書かず検証だけ
python3 docs/05_解説/code-guide/build.py --review --include-sample   # review/00-*.html（サンプル）も取り込む
python3 docs/05_解説/code-guide/build.py --review --list-stops       # 停留所ごとの path:行 を一覧する（突き合わせ用）
```

訳・住所・つながり図・用語集のオプション（`--allow-missing-translations` など）は、次の「初心者向けの補助」を参照。

- 出力: `docs/05_解説/GU_ECsite_レビュー回答ガイド.html`（`--out` で差し替え可。サンプルの動作確認は `--out` で別の場所に出す）
- `--commit`・`--check`・`--content-dir`・`--out`・`--include-sample` は解説書と同じ。`--content-dir` の既定だけ `code-guide/review`
- `--guide-url`（既定 `GU_ECsite_コード解説.html`）と `--map-url`（既定 `GU_ECsite_リポジトリ地図.html`）はヘッダーのリンク先
- ページの文言（タイトル・eyebrow・リード・使い方の 1 行）は `review/template-review.html` に書いてある
- 章の構造（`<section id data-title>`・`<h3 id>`・目次・id の重複検査）と `data-ref` 構文は解説書と同じ。`--map` との同時指定はエラー

## 行番号の自動挿入（`data-focus`）

`data-ref` に **`data-focus="部分文字列"`** を添えると、build.py が `data-ref` の解決範囲（シンボルなら宣言の先頭行から末尾まで、`#L` 範囲ならその範囲、ファイル全体ならファイル全体）の中で、その文字列を含む **最初の行** の実ファイルの行番号を求める。

- `data-focus` が無ければ範囲の開始行（デコレータ付きの Python 関数はデコレータ行）
- 文字列が範囲内に見つからなければ、`ファイル:行: 参照 → data-focus "…" が … の L…-L… の中に見つからない` を一覧にして exit 1
- `data-focus` が空、`data-ref` なしの `data-focus`、順路の外の `li.stop`、`span.loc` の中身が空でない、も exit 1
- 求めた行は `data-focus-line="N"` として自動で付く（本文には書かない）。ドロワーはその行を強調（背景色・左の太線・行番号の太字）し、上から 1/3 あたりにスクロールする。ヘッダーに `L34-215（182 行） ／ 注目 L65` と出る
- 行番号は `git show <commit>:<path>` の行番号と一致する（GitHub のパーマリンクと同じ）。確認は `git show <commit>:<path> | grep -n -F '<data-focus>'`（最初の一致が範囲内にあることを見る）

## 本文の部品（本文担当と共有する約束）

### 1. 順路

```html
<ol class="route" data-title="順路：購入ボタンから完了画面まで">
  <li class="stop" data-ref="apps/web/components/OrderConfirm.tsx::OrderConfirm" data-focus="inflight.current" data-layer="screen">
    <p class="stop-see">ここで見るもの（関数名・注目する行の説明）</p>
    <p class="stop-say">言うこと（台本 1〜2 文）</p>
    <p class="stop-next">次へ: <kbd>F12</kbd> で <code>createOrder</code> の定義へ</p>
  </li>
</ol>
```

- `data-ref`・`data-focus` は上のとおり。`data-note`（任意）はドロワーの「見どころ」になる
- `data-layer`: `screen` / `bff` / `api` / `service` / `repo` / `db` / `ci` / `infra`（フロー図と同じ。左線の色とレイヤー名）
- build.py が各 `li.stop` の先頭に `<div class="stop-loc">` を自動で挿入する。中身は、番号（順路ごとに 1, 2, …）、レイヤーのラベル、`path:行`（等幅。クリックで全選択）、「コピー」ボタン、「コードを見る」ボタン。本文には書かない
- 「コピー」は `path:行` を `navigator.clipboard.writeText` で書く。失敗したらパスを選択状態にする。VS Code では <kbd>⌘P</kbd> に貼って Enter で開ける
- 「コードを見る」はドロワーを開き、注目行を強調してそこまでスクロールする。停留所の全面クリックでは開かない（文字の選択を邪魔しないため）
- 順路の見出し（`data-title`）の横に、フロー図と同じ「流れを再生」ボタンが付く。停留所を 1.4 秒ごとに順に強調する。再生中に停留所をクリックすると止まる
- `stop-see` の前に「見る」、`stop-say` の前に「言う」のラベルが CSS で付く。本文に書き足さない。`stop-next` は書いたとおりに出る
- `data-ref` の無い停留所（DB など）は番号とレイヤーだけ出て、警告が 1 行出る

### 2. インラインの行番号

```html
<span class="loc" data-ref="apps/web/components/OrderConfirm.tsx::OrderConfirm" data-focus="inflight.current"></span>
```

中身は自動で `path:行` になる（空にしておく）。押すとドロワーが開く。`data-focus` は省略可（範囲の開始行）。

### 3. キー

```html
<kbd>⌘P</kbd> <kbd>F12</kbd>
```

### 4. テストの状態バッジ

```html
<span class="tstat pass">✅ 通過（ローカル）</span>
<span class="tstat ciskip">⏭ CI ではスキップ</span>
<span class="tstat fail">❌ 失敗</span>
<span class="tstat manual">🖐 手動で合格</span>
<span class="tstat none">— テストなし</span>
<span class="tstat notimpl">未実装</span>
```

色は pass が緑系、ciskip が琥珀系、fail が赤系、manual が青系、none が灰色（塗り）、notimpl が灰色（破線の枠）。ラベルの文言は本文で決める（絵文字と文字でも状態が分かる）。

### 5. 仕様書との突き合わせ表

```html
<div class="table-wrap">
<table class="compare">
<thead><tr><th>条件</th><th>仕様書</th><th>テスト</th><th>判定</th></tr></thead>
<tbody>
<tr><td>在庫が足りないとき</td><td>409 を返す</td><td>409 を確認</td><td class="ok">一致</td></tr>
<tr><td>…</td><td>…</td><td>…</td><td class="ng">不一致</td></tr>
<tr><td>…</td><td>…</td><td>…</td><td class="warn">要注意</td></tr>
</tbody>
</table>
</div>
```

`td.ok`（緑）・`td.ng`（赤）・`td.warn`（琥珀）に背景色が付く。判定の文言は本文で決める。

### 6. 台本ボックス

```html
<div class="script"><p class="script-title">30 秒版</p><p>台本の本文</p></div>
```

引用風（左の太線）で、本文より少し大きい文字。

### 7. 章の頭の「指定のされ方」

```html
<p class="asked">「購入ボタンを押す」「注文を確定する」</p>
```

「指定のされ方」のラベルは CSS が付ける。

### 8. 既存の部品

`a.ref`、`flow`、`arch`、`note`、`status`、`req`、`tid`、`layer`、`table-wrap`、`filterable`、`details.qa`、`pre.code`、`metaphor`、`why`、`grid2` はそのまま使える。`data-focus` は `a.ref` と `flow-step` にも使える。

## 初心者向けの補助（日本語訳・住所・つながり図・重なりの図・用語・初心者モード）

`--review` のときだけ、組み立て時に次を組み込む（解説書・地図の出力には入らない）。データは別担当が作り、build.py は検査と差し込みだけを行う。

```bash
python3 docs/05_解説/code-guide/build.py --review                                  # 訳・用語集が本番データで揃っていないとエラー
python3 docs/05_解説/code-guide/build.py --review --allow-missing-translations     # 訳の無い行を警告に落とす（データ作成中の確認用）
python3 docs/05_解説/code-guide/build.py --review --check --allow-missing-translations --dump-translation-scope /tmp/scope.json   # 訳の対象を書き出す
```

| オプション | 意味 |
|---|---|
| `--allow-missing-translations` | 「訳の無い行」だけを警告にする（形式の不備・はみ出し・重なり・存在しないファイルは、付けてもエラー） |
| `--dump-translation-scope PATH` | 訳の対象を `{path: {"ranges": [[a,b],...], "lines": n, "nonblank": m}}` で書き出す。`lines` は和集合の全行数、`nonblank` は空行を除く行数 |
| `--translations-dir DIR` / `--glossary PATH` | 訳・用語集の置き場の差し替え（検証用。既定は `review/translations/`・`review/glossary.json`） |

### 訳の JSON（`review/translations/*.json`）

`sample.json` 以外をすべて読み込んでマージする。本番ファイル（`t1.json` など）が 1 つも無いときだけ `sample.json` を読む（動作確認用。使ったときは警告が出る）。

```json
{
  "apps/api/app/services/orders.py": [
    {"lines": [281, 283], "ja": "注文を確定する入口の関数。カートのトークン、入力内容、決済とメールの部品を受け取る"},
    {"lines": [284, 284], "ja": "…"}
  ]
}
```

- キーはリポジトリルートからの相対パス。`lines` は実ファイル（`--commit` のコミット。既定は origin/main）の行番号で、両端を含む。`ja` は空でない文字列。`lines` と `ja` 以外のキーはエラー
- **網羅の検査**: 本文の全 `li.stop` の `data-ref` を解決し、ファイルごとに行範囲の和集合（隣接・重複は結合）を求める。その和集合の中の **空行以外のすべての行** が、ちょうど 1 つのブロックに含まれること
  - ブロックが和集合の外にはみ出す、ブロックどうしが重なる、ファイルが存在しない・停留所に出てこないファイルのブロック、JSON の形式の不備 → エラー（exit 1。ファイルと行の一覧を出す）
  - 訳の無い行 → エラー（`--allow-missing-translations` のときだけ警告）。ブロックに空行を含めるのは可（和集合の内側に限る）
- 対象は `--dump-translation-scope` で確認できる。`a.ref` や `span.loc` の範囲は対象外（`li.stop` だけ）

### 用語集の JSON（`review/glossary.json`）

```json
[
  {"term": "BFF", "aliases": ["Backend for Frontend"], "short": "2〜3 文の説明", "analogy": "身近な例え 1 文（任意）", "ref": "apps/web/lib/server/api.ts::apiFetch"}
]
```

- `term` と `short` は必須。`aliases`・`analogy`・`ref`（`data-ref` 構文）は任意。`ref` が解決できない・同じ語が重複する・未知のキーがある、はエラー。`glossary.json` が無いときだけ `glossary.sample.json` を読む
- 本文（`p`・`li`・`td`・`.stop-see`・`.stop-say`）と訳の地の文で、`term` / `aliases` に一致する語を、**各 section の中で最初の 1 回だけ**点線下線の `<button class="term">` にする（組み立て後の JS が行う。原文の文字列は変えない）。`code`・`kbd`・`pre`・`a`・見出し・既存のボタンの中は対象外。ドロワーの訳の中では、開くたびに最初の 1 回
- 照合は長い語を優先する（`CSRF トークン` は `CSRF` より先、`FastAPI` は `API` より先）。語の端が英数字のときは語の境界で照合する（前後が英数字・`-`・`_` なら一致させない。`UT-WEB-09` の `UT` には反応しない）
- 押す（PC ではホバーでも）と、説明（`short`）・たとえ（`analogy`）・「コードを見る」（`ref` があれば）のポップオーバーが出る。Esc・外側クリックで閉じる。キーボードは Tab で語に移り Enter / Space で開く

### 画面に出るもの

1. **停留所の補足**（各 `li.stop` の `stop-loc` の直下。build.py が HTML に入れる）
   - 住所: `apps › web › components › OrderConfirm.tsx › submit()` の形のパンくず。フォルダ（CSS の記号）・ファイル（拡張子のラベル）・関数（`ƒ`。クラス・型は `T`、定数は `=`、行範囲は `L`）を区別する。各段は折り返せる
   - 注目行と訳: `data-focus` の行のコード 1 行（等幅。中身は JS が埋め込み済みのスニペットから入れる）と、その行を含むブロックの訳。`data-focus` が無ければ範囲の先頭ブロック
2. **ドロワーの対訳**: 広い画面は 3 列（行番号・コード・訳）。訳はブロックの行数ぶん縦に結合し、境目に薄い線を引く。コードが長いときは横にスクロールしても訳の列は右端に残る。狭い画面（< 720px）は各ブロックのコードの直後に訳を 1 段で出す。訳のデータが無い範囲のスニペット（本文の `a.ref` で範囲外のもの）は従来の表示。ドロワー上部の「訳を表示」は初心者モードと同じ状態に連動する
3. **つながり図**（各 `ol.route` の直前に build.py が自動生成。矢印は JS が SVG で描く）
   - 停留所の順に、層（`data-layer`）→ フォルダ → ファイル → 関数（`symbol`。`#L` 範囲は `L10-40`）の入れ子の箱。同じ層・フォルダ・ファイルが続く停留所は同じ箱に並べる
   - 箱どうしを停留所の順に矢印でつなぐ。矢印のラベルは、`li.stop` の **`data-link="HTTP POST /api/orders"`**（前の停留所からこの停留所へのつながり方。任意）があればそれ。無ければ既定: 画面 → BFF「HTTP（fetch）」、BFF → API「HTTP（内部トークン付き）」、API → サービス・サービス → リポジトリ「関数の呼び出し」、リポジトリ → DB「SQL」、同じファイル内「同じファイル内」、それ以外「呼び出し」
   - 広い画面は層を縦のレーン（左から 画面・BFF・API・サービス・リポジトリ・DB。そのほかの層は右）にして上から下へ箱を置き、矢印をレーンをまたいで斜めに結ぶ。レーンが多くて入りきらないときは図の中だけ横にスクロールする。狭い画面は 1 列で、矢印は下向き
   - 箱を押すと、その停留所へスクロールしてハイライトし、ドロワーでコードを開く。「流れを再生」で箱と矢印が順に光る。SVG の色はすべてテーマトークン。`prefers-reduced-motion` では動きを付けない
4. **重なりの図**（`<div class="overlap-map" data-title="購買 7 機能が通るファイル"></div>` を置いた場所に、build.py が表を入れる）
   - 行 = 停留所に出てくるファイル（層 → フォルダの順。住所と同じ表記）、列 = 章 r01〜r07（`data-chapters="r01,r02"` で差し替え可）、セル = その章の停留所で使う関数名（押すとドロワー）。3 章以上で使うファイルの行は「共通」の印と色で強調する。`table-wrap` で横にスクロールできる
5. **初心者モード**: ヘッダーのスイッチ（既定 ON）。OFF にすると住所・注目行と訳・つながり図・用語の下線・ドロワーの訳を隠す。状態は `localStorage`（`guapp-review-beginner`）に保存し、使えない環境でも ON で動く

### 原文の保護の検査

組み立てで挿入する要素にはすべて `data-gen` を付ける。build.py は、`data-gen` の要素と `span.loc` の中身を除いた出力のテキストが、`review/*.html` の原文のテキストと（空白を除いて）一致することを検査し、食い違えばエラーにする。

### 組み込みの作り（保守用）

- 新しい partial: `partials/review-aid.css`・`partials/review-aid.js`（`review/template-review.html` だけが取り込む）
- `partials/drawer.js` には、フック 2 か所（`buildDrawerExtra`・`renderCodeTr`）だけ足してある。どちらも `typeof` で存在を確かめて呼ぶので、解説書・地図では何もしない
- 訳・用語集は `<script type="application/json" id="translations-data">`・`id="glossary-data"` に埋め込む。コード本体は従来どおり `<script type="text/plain">` のまま

## 秘密検査

出力 HTML は解説書・地図と同じく `gitleaks detect --no-git --source <file> --redact` と `pre-commit run detect-secrets --files <file>` を通す。埋め込み方式（コードは原文のまま `<script type="text/plain">`、JSON の `secret` はエスケープ）は解説書と共通。

## 既知の制限（レビュー回答ガイド）

- `data-focus` は「範囲内で最初に一致する行」。同じ文字列が範囲内に複数あるときは 2 つ目以降を指せない（文字列を長くして一意にする）
- 行は 1 行だけ強調する（複数行の範囲強調は未対応）
- 地図（`--map`）の `body_html` では `data-focus` を解決しない（ドロワーの JS は `data-focus-line` があれば効く）
- 順路の「流れを再生」は強調の移動のみ（フロー図のような動く点は無い）
- JS が無い環境では「コピー」「コードを見る」ボタンは出ない（`path:行` の文字列は出る）
- 初心者向けの補助のうち、つながり図の矢印・用語ポップアップ・ドロワーの対訳・初心者モードは JS が要る（JS が無い環境では、つながり図は出さない。住所と訳は表示される）
- 用語は「各 section の最初の 1 回」。同じ section で 2 回目以降は下線が付かない。直前の要素をまたぐ語（`<code>` の隣など）は照合しない
- ドロワーの対訳は、広い画面でコードが長いと、コードの上に訳の列が重なる（横スクロールで読める）。幅 1120px までドロワーを広げる
- つながり図の層は 5 つ以上あると、図の中だけ横にスクロールする。ラベルは箱と箱のすき間の中央に置くが、すき間が狭い入れ子ではラベルが箱の枠に少し重なる
- 重なりの図の列は章 r01〜r07（購買）。章のタイトルは 12 文字で切る
- `--include-sample` は `review/00-sample.html` の章 id が `00-intro.html` と重複するため、現状はエラーになる（本改修より前からの状態）

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
