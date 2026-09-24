# GU EC サイト 設計仕様書（P2 追補a）

| 項目 | 内容 |
| --- | --- |
| 文書番号 | GUEC-SD-01-P2a |
| 版 | draft-v1 |
| 作成者 | キャタピー（Claude） |
| 作成日 | 2026-09-24 |
| 入力 | 本編 `GU_ECsite_設計仕様書_P1_draft-v3.md`、テスト設計書 `GU_ECsite_テスト設計書_P1_draft-v2.md`、要求仕様書 with_ai v2.4、要件定義書 with_ai v1.3、`実装フェーズ計画.md`、`P2_事前レビュー観点_v1.md`、`付録_デザイン基準_v1.md`、`付録_GUサイト調査_20260918.md`、`引継ぎメモ_20260924.md`、実装（`apps/api/app/`・`apps/web/`） |
| 対象 | ADR-0001 の P2-a：F-003 商品検索、F-028 FAQ・静的ページ、F-030 コンテンツ・お知らせ、および ADR-0002 の Azure Database for MySQL 接続切り替え |

## 改訂履歴

| 版 | 日付 | 内容 | 作成 | 承認 |
| --- | --- | --- | --- | --- |
| draft-v1 | 2026-09-24 | 初稿。ADR-0001（P2-a 機能 3 件）・ADR-0002（Azure MySQL 接続）を本編差分として作成 | キャタピー | — |
| draft-v1（差し戻し1回目反映） | 2026-09-24 | コーディネーターからの差し戻し（1 回目）を反映。実機確認により初稿の「`utf8mb4_0900_ai_ci` は全角半角を吸収しない」という前提が誤りと判明したため DS-DEC-34・37 と 4.4 の該当段落を書き直し（案A: DB 照合任せを仕様として受容）。Azure 接続（DS-DEC-42・44・45）を「検証済み」から「実接続で確かめる仮説＋具体的なフォールバック」に格下げし、新規 DS-DEC-46（DB 接続プールの環境変数化）を追加。本編 8.2 の 1 行と改訂履歴を統括承認のうえ訂正。ADR-0003（検索 API のレート制限見送り）を新規作成し 9.3 に反映。9.5「覆りうる判断の申し送り」を新設 | キャタピー | Oya |

## 0. 本書の位置づけ

本書は本編（`GU_ECsite_設計仕様書_P1_draft-v3.md`、以下「本編」）の追補であり、**本編との差分だけ**を書く。本編の章構成（1 構成／2 版・依存／3 UML／4 API／5 DB／6 画面／7 セキュリティ／8 インフラ／9 設計判断／10 トレーサビリティ）に対応する番号で章を立てる。本編に書かれていて変わらない事項（例: BFF と FastAPI の 2 層構成、エラー応答の判定順序そのもの）は再掲しない。

### 0.1 対象範囲

本編 9.4「テスト設計書への申し送り」と実装フェーズ計画 4 章の割り当てに従い、ADR-0001 の P2-a として次の 3 機能を対象にする。

1. **F-003 商品検索**（REQ-FR-105 Must・106 Could・107 Should）: DS-API-004 の詳細化、ヘッダーの検索欄、SCR-002 の検索モード
2. **F-028 FAQ・静的ページ**（REQ-FR-903 Must）: DS-API-006 の詳細化、SCR-012、フッター・オールメニューのリンク先確定
3. **F-030 コンテンツ・お知らせ**（REQ-FR-1001 Should・1002 Must）: DS-API-005 の詳細化、SCR-011、ホームのお知らせ欄

これに加え、ADR-0002 として**講義の Azure MySQL への接続切り替え**（サーバー `gen12-mysql-pos`、スキーマ `guapp_nonooktk`／`guapp_nonooktk_test`）を 8 章に設計する。ADR-0001・ADR-0002 とも、本書の起票時点でリポジトリのブランチ `docs/p2a-design` にはまだコードとして反映されていないが、統括承認済みの決定として扱う。

### 0.2 設計 ID の追加

本編の ID 体系（DS-SCR・DS-API・DS-TBL・DS-PRC・DS-IF・DS-DEC）をそのまま使う。本書で新規に詳細化する ID は次のとおり。

| 種別 | ID | 備考 |
| --- | --- | --- |
| API | DS-API-004 | 本編に概要のみ記載済み。本書 4.1 で詳細化 |
| API | DS-API-004a | 新設（検索サジェスト、REQ-FR-106 Could）。本編には無い枝番のため `a` を付け、DS-API-004 の子として扱う |
| API | DS-API-005 | 本編に概要のみ記載済み。本書 4.2 で詳細化 |
| API | DS-API-006 | 本編に概要のみ記載済み。本書 4.3 で詳細化 |
| 処理 | DS-PRC-004 | 検索処理仕様（新設） |
| 処理 | DS-PRC-004a | サジェスト処理仕様（新設） |
| 処理 | DS-PRC-005 | コンテンツ一覧処理仕様（新設） |
| 処理 | DS-PRC-006 | コンテンツ詳細処理仕様（新設） |
| 画面 | DS-SCR-002 | 本編は一覧モードのみ記述。本書 6.2 で検索モードを追加（枝番なし、同じ画面の追加状態として書く） |
| 画面 | DS-SCR-011・012 | 本編は概要行のみ。本書 6.3・6.4 でワイヤーを新設 |
| 判断 | DS-DEC-33〜46 | 本書 9.1 に一覧（2026-09-24 差し戻しで 46 を追加） |

## 1. 構成への影響（本編 1 章の差分）

システム構成図（本編 1 章の Mermaid 図）そのものは変わらない。差分は次の 2 点のみ。

1. `Azure Database for MySQL` の接続が、ローカル開発の平文 TCP から **SSL 必須の接続**に変わる（ADR-0002。8 章）。App Service ②（FastAPI）から見ると接続文字列（`DATABASE_URL`）のクエリ文字列が変わるだけで、構成要素・矢印は本編のままである。
2. App Service ①（Next.js）に新規ページが 2 種類増える：`/search`（検索結果。DS-SCR-002 の検索モード）と `/contents`・`/contents/[slug]`（DS-SCR-011・012）。BFF 層には検索の「もっと見る」用に 1 本（`/api/search`）追加する。コンテンツ系は Server Component から FastAPI を直接呼ぶため（本編 4.3 の原則）BFF は追加しない。

## 2. 版・依存の追加（本編 2 章の差分）

**新規の外部パッケージは追加しない**（DS-DEC-38・DS-DEC-42、根拠は各節参照）。ただし **Azure 接続まわりは `apps/api/app/core/config.py`・`core/db.py` へのコード変更（新規環境変数の読み取り）を伴う**（DS-DEC-42・45・46。2026-09-24 訂正: draft-v1 は「コード変更不要」としていたが、統括レビューで接続方式そのものを仮説として扱う方針に変わったため、変更前提に書き直した）。

| 領域 | 追加・変更 | 根拠 |
| --- | --- | --- |
| バックエンド（検索） | 追加ライブラリなし。`unicodedata`（標準ライブラリ）で正規化（DS-DEC-34。一致判定用ではなく整形・辞書引き当て用）、SQLAlchemy 2.0 の `ColumnOperators.contains(..., autoescape=True)`／`startswith(..., autoescape=True)` で LIKE ワイルドカードを自動エスケープする | `apps/api/.venv/lib/python3.13/site-packages/sqlalchemy/sql/operators.py`（`startswith`/`contains` の `autoescape` 引数の実装）を確認済み。DS-DEC-35 |
| バックエンド（コンテンツ） | 追加ライブラリなし。本文はプレーンテキストとして扱い、Markdown・HTML レンダリングは行わない | DS-DEC-38 |
| バックエンド（Azure 接続） | 追加ライブラリは無いが、**コード変更あり**。`core/config.py` に `DB_SSL_CA_PATH`（CA 証明書ファイルの絶対パス）・`DB_POOL_SIZE`・`DB_MAX_OVERFLOW` の 3 設定を追加し、`core/db.py` の `build_engine()` を「まず `DATABASE_URL` に `ssl_ca=` クエリを付ける方式を試し、接続できなければ `connect_args={"ssl": <ssl.SSLContext>}` を明示的に組み立てて渡す方式に切り替えられる」実装にする（8.1・DS-DEC-42） | `apps/api/.venv/lib/python3.13/site-packages/asyncmy/connection.pyx` の `_create_ssl_ctx()` を確認済み（`ssl.create_default_context(cafile=...)` を使用）。SSL 自体は Python 標準の `ssl` モジュールと既存依存（asyncmy・cryptography）で完結する |
| フロントエンド | 追加ライブラリなし。検索サジェストの入力欄・一覧表示は既存の `useState`／`fetch` の範囲で実装できる | `apps/web/package.json` に markdown・sanitize 系の依存が無いことを確認済み |

P2 事前レビュー観点 **#3（実接続で初めて要る依存）**は 9.2 の記入表で扱う。結論（訂正後）: 新規パッケージは要らないが、**接続方式（クエリパラメータ方式かコード直書き方式か）は実接続してみるまで確定しない仮説**であり、実装の最初の作業を「講義サーバーへの実接続の試行」とする（DS-DEC-42）。

## 3. シーケンス／アクティビティ（本編 3 章の差分）

### 3.1 商品検索（DS-PRC-004）

```mermaid
sequenceDiagram
    participant B as ブラウザ
    participant W as Next.js（Server Component / BFF）
    participant API as FastAPI
    participant DB as MySQL
    B->>W: GET /search?q=パーカー
    W->>API: GET /api/v1/search?q=パーカー&page=1
    API->>API: 入力検証（1〜100文字）→ trim → NFKC 正規化
    API->>DB: products.name/description・categories.name を LIKE（autoescape）で検索（公開商品のみ）
    DB-->>API: 0 件以上の商品行
    alt 0 件
        API->>API: 固定言い換え辞書を正規化後の語で引く（DS-DEC-37）
        API->>DB: 候補語ごとに再検索し 1 件以上ヒットするものだけ残す
        API->>DB: おすすめカテゴリ（公開商品数上位）を取得
    end
    API-->>W: 商品一覧 or 空＋類似キーワード＋おすすめカテゴリ
    W-->>B: SCR-002（検索モード）を描画
```

### 3.2 検索サジェスト（DS-PRC-004a・REQ-FR-106 Could）

```mermaid
sequenceDiagram
    participant B as ブラウザ（入力中）
    participant W as Next.js BFF（/api/search/suggest）
    participant API as FastAPI
    participant DB as MySQL
    B->>W: GET /api/search/suggest?q=パー（300ms デバウンス）
    W->>API: GET /api/v1/search/suggest?q=パー
    API->>DB: 商品名の前方一致（autoescape）を優先して最大5件
    API->>DB: 5件未満なら部分一致で補充（重複除去）
    API-->>W: 商品名候補（最大5件）
    W-->>B: 入力欄の下にドロップダウン表示
```

### 3.3 コンテンツ取得（DS-PRC-005・006）

```mermaid
sequenceDiagram
    participant B as ブラウザ
    participant W as Next.js（Server Component）
    participant API as FastAPI
    participant DB as MySQL
    B->>W: GET / （ホーム）
    W->>API: GET /api/v1/contents?kind=news&limit=3
    API->>DB: publish_from<=now<=publish_to（NULL可）で絞り込み
    API-->>W: お知らせ最大3件
    B->>W: GET /contents/faq
    W->>API: GET /api/v1/contents/faq
    API->>DB: slug一致 かつ 掲載期間内
    API-->>W: 200 本文 or 404 not_found（存在しない・期間外を区別しない）
    W-->>B: SCR-012 を描画
```

### 3.4 Azure MySQL への接続確立（起動時・DS-PRC-Azure-01。2026-09-24 訂正: 仮説→検証→フォールバックの 2 段構えに書き直し）

```mermaid
sequenceDiagram
    participant P as gunicorn/uvicorn プロセス起動
    participant CFG as Settings（core/config.py。DB_SSL_CA_PATH・DB_POOL_SIZE・DB_MAX_OVERFLOW を追加）
    participant ENG as SQLAlchemy AsyncEngine
    participant TLS as TLS ハンドシェイク
    participant AZ as Azure Database for MySQL
    P->>CFG: 環境変数 DATABASE_URL・DB_SSL_CA_PATH・DB_POOL_SIZE・DB_MAX_OVERFLOW を読む
    CFG->>ENG: create_async_engine(DATABASE_URL, pool_size=DB_POOL_SIZE, max_overflow=DB_MAX_OVERFLOW)
    Note over ENG: 【仮説・第1案】DATABASE_URL のクエリに ssl_ca=<DB_SSL_CA_PATH> を含める運用（実装コード変更なしで済む案。8.1）
    ENG->>TLS: asyncmy.connect(..., ssl={"ca": <DB_SSL_CA_PATH の値>})
    alt 接続成功（要検証で確認できた場合）
        TLS->>AZ: TLS 1.2 以上でハンドシェイク（CA 検証）
        AZ-->>TLS: 証明書チェーン（DigiCert Global Root G2 ／ Microsoft RSA Root CA 2017 系。9.2 の要検証参照）
        TLS-->>ENG: 暗号化コネクション確立
    else 接続失敗（クエリパラメータ方式が通らない場合）
        Note over CFG,ENG: 【第2案・具体的なフォールバック】core/db.py の build_engine() で\nssl.create_default_context(cafile=DB_SSL_CA_PATH) を明示的に生成し、\ncreate_async_engine(..., connect_args={"ssl": <SSLContext インスタンス>}) として渡す
        ENG->>TLS: asyncmy.connect(..., ssl=<SSLContext インスタンス>)
        TLS->>AZ: TLS 1.2 以上でハンドシェイク（CA 検証）
        AZ-->>TLS: 証明書チェーン
        TLS-->>ENG: 暗号化コネクション確立
    end
    ENG-->>P: 通常のクエリ実行が可能に
```

実装の最初の作業は、この図の分岐がどちらに転ぶかを**講義サーバーに実接続して確かめること**（DS-DEC-42）。`DB_SSL_CA_PATH` は Mac・Windows・App Service（Linux）で値（パスの形式）が異なる（8.7）。

## 4. API 設計（本編 4 章の差分）

### 4.0 命名・契約の共通方針

- 検索・コンテンツ系はすべて公開情報の読み取りであり、認証は不要（内部トークンは本編 4.1 のとおり BFF→FastAPI 間で必須のまま）。
- ページングは本編 `PER_PAGE_DEFAULT=24`／`PER_PAGE_MAX=48`（`apps/api/app/schemas/catalog.py`）の値をそのまま再利用する。検索結果一覧・コンテンツ一覧も同じ値域に合わせる。
- 応答フィールドは「存在するときだけキーを付ける」のではなく、**常にキーを持たせて空配列・null で表す**（フロント側の分岐を単純にするための統一。DS-DEC-46 は設けず本節の申し合わせとする）。

### 4.1 DS-API-004 商品検索（詳細化）

`GET /api/v1/search`

| 区分 | 内容 |
| --- | --- |
| クエリ | `q`（必須・文字列 1〜100文字）、`page`（既定1）、`per_page`（既定24・最大48） |
| 前提 | `q` は Pydantic `Query(min_length=1, max_length=100)` で受け、サービス層で strip → NFKC 正規化する（DS-PRC-004 手順 1〜2） |
| 応答 200 | `{ "query": "<正規化後の語>", "items": [ProductListItemOut...], "page", "per_page", "total", "has_more", "similar_keywords": [<string>], "recommended_categories": [{"slug","name","product_count"}] }`。`similar_keywords`・`recommended_categories` は `total>0` のときは空配列を返す（4.0 の方針） |
| 400 | `q` が空文字・100文字超（Pydantic の長さ制約）、strip 後に空文字（空白のみ入力。reason は `format`） |
| 404/409/422 | 無し（読み取り専用で、DB の状態や存在確認に依存する業務ルールが無いため。4.5 節に追記） |

`similar_keywords` は固定の言い換え辞書（DS-DEC-37）を正規化後の語で引き、辞書に候補があってもその語で検索して 0 件になるものは含めない（「候補を出したのにまた 0 件」を避けるため）。`recommended_categories` は公開商品数の多い子カテゴリ上位 3 件（0 件のカテゴリは除く）。

#### DS-API-004a 検索サジェスト（新設・REQ-FR-106 Could）

`GET /api/v1/search/suggest`

| 区分 | 内容 |
| --- | --- |
| クエリ | `q`（DS-API-004 と同じ検証規則） |
| 応答 200 | `{ "items": [{"id": <int>, "name": <string>}] }` 最大 5 件 |
| 優先順位 | 商品名の前方一致（DS-PRC-004a）を優先し、5 件に満たなければ部分一致で補充。公開商品のみ |
| 位置づけ | 優先度 Could。31 商品規模の LIKE 前方一致で十分に軽いため「見送り」にはせず設計・実装対象に含める（DS-DEC-36）。ただし実装順は F-003 の他要素より後でよい |

### 4.2 DS-API-005 コンテンツ一覧（詳細化）

`GET /api/v1/contents`

| 区分 | 内容 |
| --- | --- |
| クエリ | `kind`（必須。`feature`／`news` の 2 値のみ受け付ける。`faq`／`static` は一覧化しない設計。理由は 4.3 参照）、`limit`（既定5・最大20） |
| 応答 200 | `{ "items": [{"slug","title","kind","publish_from"}] }`。一覧では `body` を含めない（ホームの見出し表示に本文全文は不要なため。詳細は DS-API-006 で取得する想定だが、本演習では feature/news も本文まで一覧応答に含めてよい） |
| 並び順 | `news` は `publish_from` 降順（新しい順）、`feature` は `sort_order` 昇順 |
| 掲載判定 | DS-PRC-005（3.3 節） |
| 400 | `kind` が列挙外、`limit` が範囲外 |

### 4.3 DS-API-006 FAQ・静的ページ（詳細化）

`GET /api/v1/contents/{slug}`

| 区分 | 内容 |
| --- | --- |
| パス | `slug`（`^[a-z0-9-]{1,100}$`。本編 4.5 の 400/404 判定順序に従い、パターン外は 400、パターン内で対象が無ければ 404） |
| 対象 | `kind IN ('faq','static')` のみ。`feature`／`news` は一覧経由のみで個別 URL を持たない設計とする（意図的な制約。理由: 特集・お知らせは一覧からの導線だけで足り、FAQ・規約等は footer/AllMenu から直接リンクする固定ページのため） |
| 応答 200 | `{"slug","kind","title","body"}` |
| 404 | 存在しない slug・`kind` が対象外・掲載期間外のいずれも区別せず `not_found`（本編 7.5 の「404 は 3 者を区別しない」方針を踏襲） |

FAQ・静的ページの `slug` は 5 種固定とする（DS-DEC-39）。

| slug | kind | 画面上のリンク元 | 内容 |
| --- | --- | --- | --- |
| `faq` | faq | フッター「FAQ」、AllMenu「FAQ」 | よくある質問（Q&A をプレーンテキストで列挙） |
| `terms` | static | フッター「利用規約」 | 利用規約（ダミー） |
| `privacy` | static | フッター「プライバシー」 | プライバシーポリシー（ダミー） |
| `tokushoho` | static | フッター「特商法」 | 特定商取引法に基づく表記（ダミー・架空事業者。9.3 参照） |
| `company` | static | フッター「企業情報」、AllMenu「INFO」 | 企業情報（ダミー・架空事業者） |

### 4.4 処理仕様（DS-PRC-004・004a・005・006）

#### DS-PRC-004 商品検索

入力: `q`（1〜100 文字）、`page`、`per_page`。

0. Pydantic が `q` の長さ（1〜100）を検査。違反は 400 `validation_error`（`too_long`／`out_of_range`。本編 `map_reason` の分類に従う）
1. `term = q.strip()`。空文字なら 400 `validation_error`（reason `format`。カスタムバリデータで送出した `ValueError` は本編 `map_reason` の既定分岐で `format` になる）
2. `term = unicodedata.normalize("NFKC", term)` のうえ、前後の空白・全角空白・連続する空白を整理する。正規化後に再度空文字チェック（ゼロ幅文字等が正規化で消えるケースへの備え）。**この正規化は検索の一致判定のためではない**（一致判定は手順3の DB 照合に委ねる。DS-DEC-34・9.2 観点#5 参照）。正規化の目的は (a) 前後・連続空白の整理、(b) 長さ上限（100文字）判定を正規化後の文字数で行うこと、(c) 言い換え辞書（DS-DEC-37）のキー引き当てを 1 通りの表記に統一すること、の 3 点に限る
3. 公開商品（`Product.published.is_(True)`）のうち、`Product.name.contains(term, autoescape=True)` **OR** `Product.description.contains(term, autoescape=True)` **OR**（`ProductCategory`／`Category` を経由して）`Category.name.contains(term, autoescape=True)` のいずれかに一致する商品を `DISTINCT` で取得する
4. 新着順（`created_at DESC, id DESC`）で `page`／`per_page` によりページングし、`total` を別途 COUNT する（本編 `list_published` と同じ形）
5. `total == 0` のとき:
   1. `SEARCH_SYNONYMS`（DS-DEC-37 の固定辞書）を `term` で引く。ヒットした候補語ごとに手順 3 と同じ検索を行い、1 件以上ヒットする候補だけを `similar_keywords` に採用する（最大 5 件）
   2. `recommended_categories` は `list_categories_with_counts`（本編 `products.py`）の結果から子カテゴリを `product_count` 降順に並べ、0 件を除いた上位 3 件。**`product_count` が同数のときは `categories.sort_order` 昇順、さらに同じなら `categories.id` 昇順**で決める（本編 `list_categories_with_counts` が返す並び順の既定＝`sort_order, id` と揃え、新しい判定基準を増やさない）
6. 応答を返す

**LIKE ワイルドカードのエスケープ（DS-DEC-35）**: `%`・`_` を利用者が入力した場合、SQLAlchemy の `ColumnOperators.contains(value, autoescape=True)` が自動でエスケープ文字（既定 `/`）を用いてエスケープし、`LIKE :param ESCAPE '/'` を生成する（`sqlalchemy/sql/operators.py` の `startswith`/`contains` 実装で確認済み）。自前のエスケープ関数は書かず、この標準機能を使う。手で `re.sub` 等によるエスケープを実装すると、エスケープ文字自体のエスケープ順序を誤るリスクがあるため（P2 事前レビュー観点の趣旨と同種の失敗パターン）。

**NFKC 正規化と DB 照合順序の関係（観点#5 への回答。2026-09-24 訂正）**: draft-v1 では「`utf8mb4_0900_ai_ci` の `_ai_` はアクセント無視の意味で、全角・半角の区別は吸収しない」と書いたが、**これは誤りだった**。コーディネーターがローカル MySQL 8.4・`utf8mb4_0900_ai_ci` で実際に比較演算を確認した結果、次がすべて「同一」と判定された。

- `'ｼｬﾂ' = 'シャツ'`（半角カナ＝全角カナ）
- `'Ｔシャツ' = 'tシャツ'`（全角英字＝半角英字、大文字小文字も無視）
- `'あ' = 'ア'`（ひらがな＝カタカナ）
- `'ハハ' = 'パパ'`、`'バッグ' = 'パック'`（清音・濁音・半濁音を無視）
- `'ジーンズ' = 'シーンス'`（長音・かな種別を含めて無視）
- `name LIKE '%ハンツ%'` はパンツ系商品 4 件にヒットする（部分一致でも同じ吸収が起きる）

つまり `utf8mb4_0900_ai_ci` は全角半角・ひらがなカタカナ・清濁音まで同一視する、想定より大幅に寛容な照合順序だった。**統括判断（案 A）**: この挙動を「仕様」としてそのまま受け入れる（寛容な検索）。濁点・半濁点を無視した拾いすぎ（例: 「ハンツ」で「パンツ」がヒットする）は既知の制限として設計・テストの両方に明記し、DB 照合任せの実装を変えない（アプリ側で表記ゆれを吸収する追加ロジックを持たない）。

この事実を受け、**検索の一致判定は手順3の DB 照合（`.contains(term, autoescape=True)`）に全面的に委ね**、NFKC 正規化を「一致判定のため」に使うのはやめる。NFKC 正規化は次の 3 目的だけのために残す（DS-DEC-34）。

1. 入力の前後・連続する空白（全角空白を含む）の整理
2. 長さ上限（100 文字）判定を正規化後の文字数で行うこと
3. 言い換え辞書（DS-DEC-37）のキー引き当てを 1 通りの表記に統一すること

**F-031（管理：商品・在庫）実装時の申し送りの書き直し**: draft-v1 では「商品名を自由入力できるようになったら書き込み時に NFKC 正規化する」としていたが、DB 照合が全角半角・かな種別・清濁音まで吸収するため、**検索の一致という目的のためには書き込み時正規化は不要になった**。表記ゆれの吸収は書く側でなく照合側（DB）が担うため、この申し送りは取り下げる。ただし、一覧・詳細画面での「見た目」の統一（商品名の表示が全角半角混在で揃わない、といった別の課題）は検索とは別軸の課題であり、F-031 の画面設計時に改めて要否を判断する（表示統一のためのデータ品質チェックは検索設計の対象外）。

#### DS-PRC-004a 検索サジェスト

0.〜2. は DS-PRC-004 と同じ入力検証・正規化
3. 公開商品のうち `Product.name.startswith(term, autoescape=True)` を `id` 昇順で最大 5 件取得
4. 件数が 5 未満なら、`Product.name.contains(term, autoescape=True)` から手順 3 で取得済みの `id` を除いたものを補充し、合計 5 件まで
5. `{id, name}` の配列を返す（価格・画像は返さない。軽量化のため）

#### DS-PRC-005 コンテンツ一覧

0. `kind` は `feature`／`news` のいずれか（Pydantic `Literal`）。それ以外は 400
1. `now = datetime.now(timezone.utc)`
2. `WHERE kind = :kind AND publish_from <= :now AND (publish_to IS NULL OR publish_to >= :now)`
3. `news` は `publish_from DESC`、`feature` は `sort_order ASC` で並べ `limit` 件（既定5・最大20）取得

**掲載期間の判定は UTC のみで行い、JST への変換はしない**（DS-DEC-40）。本編 DS-DEC-16「時刻は UTC・表示は JST」は「利用者に見せる時刻表示」の話であり、`publish_from`／`publish_to` はサーバー内部の比較にしか使わないため JST 変換は不要。将来 F-034（管理：コンテンツ、P3）で運用担当者が JST で掲載日時を入力する画面ができた時点で、入力→UTC 変換の実装が必要になる（申し送り）。

#### DS-PRC-006 コンテンツ詳細

0. `slug` のパターン検査（`^[a-z0-9-]{1,100}$`）。不一致は 400
1. `kind IN ('faq','static')` かつ `slug` 一致の行を取得。無ければ 404
2. 掲載期間（DS-PRC-005 と同じ判定式）に入っていなければ 404（存在しないのと同じ扱い）
3. `{slug, kind, title, body}` を返す

### 4.5 エラー応答（追加分。本編 4.5 の表への追記）

判定順序・コード形式は本編 DS-DEC-32 のまま変わらない。P2-a の API を本編の適用例表に追加する形で示す。

| API | 400 | 422 | 409 |
| --- | --- | --- | --- |
| DS-API-004 検索 | `q` 空文字・101文字以上・strip 後空文字 | — | — |
| DS-API-004a サジェスト | 同上 | — | — |
| DS-API-005 コンテンツ一覧 | `kind` が列挙外、`limit` 範囲外 | — | — |
| DS-API-006 コンテンツ詳細 | `slug` がパターン外 | — | —（404 で表現するため 409 は無し） |

検索・コンテンツ系はいずれも「DB の今の状態と衝突する」という業務ルールを持たない（在庫や冪等キーのような排他制御が無い）ため、422・409 に該当するケースが無い。これは本編 4.5 の判定順序（3. 存在確認 → 4. 業務ルール → 5. DB 状態）のうち 4・5 を素通りする API として明記しておく。

## 5. DB 設計（本編 5 章の差分）

### 5.1 DS-TBL-22 contents（列定義の肉付け）

本編 5.2 は `kind(feature/news/faq/static), slug(UNIQUE), title, body, publish_from, publish_to, sort_order` とだけ書かれている。本書で型・制約・索引まで詳細化する。

| 列 | 型 | 制約 | 備考 |
| --- | --- | --- | --- |
| id | BIGINT AUTO_INCREMENT | PK | 共通（IdMixin） |
| kind | ENUM 相当（`native_enum=False`, length=20） | NOT NULL | `feature`／`news`／`faq`／`static` の 4 値。本編モデルの `Gender`・`CartStatus` 等と同じ実装方式（`sqlalchemy.Enum(..., native_enum=False)`） |
| slug | VARCHAR(100) | NOT NULL, UNIQUE | 英数字・ハイフンのみ（DS-PRC-006 の検証パターンと一致させる） |
| title | VARCHAR(200) | NOT NULL | 商品名の上限（`products.name` VARCHAR(200)）に合わせる |
| body | TEXT | NOT NULL, デフォルト `''` | プレーンテキスト（DS-DEC-38）。段落は空行区切り |
| publish_from | DATETIME | NOT NULL | UTC。過去日時を入れれば「即時公開」 |
| publish_to | DATETIME | NULL 可 | UTC。NULL は「無期限」 |
| sort_order | INTEGER | NOT NULL, デフォルト 0 | `feature` の並び順にのみ使う |
| created_at / updated_at | DATETIME | NOT NULL | 共通（TimestampMixin） |

索引: `slug` の UNIQUE（既定で索引を兼ねる）に加え、一覧クエリ（DS-PRC-005）が `kind` と `publish_from` で絞り込むため **複合索引 `(kind, publish_from)`** を追加する（本編の他表が一覧クエリの絞り込み列に索引を張る方針＝`products.published`、`categories.parent_id` 等＝に合わせる）。

`published` という真偽列は追加しない（本編 5.2 が列挙していない列を増やすと本編との差分が生まれるため）。非公開にしたい場合は `publish_from` を未来日時にする運用で表現する（DS-DEC-40 に付記）。

マイグレーションは Alembic の新規リビジョン `0002_p2a_contents.py`（`down_revision = "6659ce6c5164"`）として設計する。`upgrade()` は `contents` テーブルの `CREATE TABLE`（本編 `MYSQL_TABLE_ARGS` と同じ `utf8mb4`／`utf8mb4_0900_ai_ci`／`InnoDB`）と複合索引の作成、`downgrade()` は `DROP TABLE contents` のみ（他表への外部キーを持たないため単純）。実装（コードを書く作業）は本書の対象外。

### 5.2 初期データ（seed）

P1 の seed（`app/seed_data.py`）に `CONTENTS` 定数を追加する設計とする。件数は次の **8 件**（本節の列挙件数と一致させる。観点#1）。

| # | slug | kind | 用途 |
| --- | --- | --- | --- |
| 1 | faq | faq | よくある質問（配送・返品・支払い方法など、演習用の一般的な Q&A） |
| 2 | terms | static | 利用規約（ダミー） |
| 3 | privacy | static | プライバシーポリシー（ダミー） |
| 4 | tokushoho | static | 特定商取引法に基づく表記（ダミー・架空事業者。9.3） |
| 5 | company | static | 企業情報（ダミー・架空事業者） |
| 6 | news-001 | news | お知らせ例 1（例: 「サイトオープンのお知らせ」） |
| 7 | news-002 | news | お知らせ例 2（例: 「送料無料キャンペーンのお知らせ」。日付は seed 実行時点から見て過去〜近未来になるよう相対日付で生成する） |
| 8 | feature-001 | feature | 特集例 1（REQ-FR-1001 Should の充足分。ホームの特集枠に 1 件だけ用意） |

`news`・`feature` の `publish_from`/`publish_to` は固定日付ではなく **seed 実行時刻からの相対値**（例: `news-001` は 30 日前〜無期限、`news-002` は 7 日前〜30 日後）で生成する設計とする。固定日付にすると、演習を続けるうちに「掲載期間外で表示されない」という事故が起きるため（本編の教訓＝実装時に初めて表面化する類の不具合を避ける）。

## 6. 画面設計（本編 6 章の差分）

### 6.1 ヘッダーの検索欄（本編 6.2 共通レイアウトの差分）

現状の実装（`apps/web/components/Header.tsx`）は検索アイコンが `href="#"` のリンクのみ。これを実際の検索導線に変える。

**1280px（デスクトップ）**:

```
┌──────────────────────────────────────────────┐
│ [≡ メニュー]  GU   [🔍 商品を探す        ][♡][🛒 3][👤] │
└──────────────────────────────────────────────┘
```

ロゴと右側アイコン群の間に、幅 240px 程度の検索入力（角丸は `--radius-sm`、デザイン基準 3 章「入力欄」に準拠）を常設する。入力中は DS-API-004a のサジェストをドロップダウン表示し、Enter またはサジェスト選択で `/search?q=...` へ遷移する。

**375px（モバイル）**:

```
┌──────────────────────────────────────────────┐
│ [≡]        GU          [🔍][♡][🛒 3][👤]       │
├──────────────────────────────────────────────┤
│ （🔍 タップで下から検索パネルが開く）             │
│ [ 商品を探す                          ] [x]     │
│ サジェスト候補 1                                │
│ サジェスト候補 2                                │
└──────────────────────────────────────────────┘
```

375px では常設の入力欄を置く横幅が無いため、AllMenu と同じ「オーバーレイ＋フォーカストラップ＋Escape で閉じる」パターン（`apps/web/components/AllMenu.tsx` の実装を流用）で検索パネルを開閉する。閉じたら検索アイコンにフォーカスを戻す（AllMenu と同じ規則）。

### 6.2 DS-SCR-002 商品一覧（検索モードの追加）

本編 6.4 のワイヤーは「カテゴリ一覧モード」のみを描いている。検索結果表示は同じ画面の別モードとして、次のワイヤーを追加する。

```
┌──────────────────────────────────────────────┐
│ 「パーカー」の検索結果            12 件         │
│ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐   │
│ │ 画像    │ │ 画像    │ │ 画像    │ │ 画像    │   │
│ │ 商品名  │ │ 商品名  │ │ 商品名  │ │ 商品名  │   │
│ │ ¥2,990  │ │ ¥2,990  │ │ ¥1,990  │ │ 在庫切れ │   │
│ └────────┘ └────────┘ └────────┘ └────────┘   │
│               [もっと見る]                       │
└──────────────────────────────────────────────┘
```

0 件時（REQ-FR-107）:

```
┌──────────────────────────────────────────────┐
│ 「ｽﾆｰｶｰ」の検索結果            0 件              │
│ 該当する商品が見つかりませんでした。               │
│ もしかして: [パーカー] [スニーカー(語尾ゆれ例)]     │ ← similar_keywords（無ければ非表示）
│ おすすめのカテゴリ:                              │
│ [トップス 24件] [アウター 10件] [ボトムス 18件]    │ ← recommended_categories
└──────────────────────────────────────────────┘
```

`similar_keywords` が空配列のときは「もしかして」の行自体を描画しない（デザイン基準 6 章のアクセシビリティ方針＝空のセクションを読み上げさせない、に合わせる）。商品グリッドの列数・ギャップは本編 6.4／デザイン基準 4 章の一覧と同じ（1280px:4列／768px:3列／375px:2列）。

**既知の制限（DS-DEC-34・統括承認済みの受容事項）**: DB の照合順序が濁点・半濁点を無視するため、「ハンツ」で検索すると「パンツ」系の商品まで一致する、といった**拾いすぎ**が起きる。これは案 A（寛容な検索をそのまま受け入れる）の副作用であり、不具合ではない。画面上でこれを取り立てて注記する UI（「もしかしてこの検索結果には表記ゆれによる候補が含まれます」等の注意書き）は P2-a では設けない。検索結果が想定より広い、という問い合わせが来た場合の一次回答として、この節を参照する。

### 6.3 DS-SCR-011 コンテンツ・お知らせ（新設）

一覧ページ `/contents`（クエリ `?kind=news` でお知らせのみ、無指定は特集＋お知らせを両方表示）。

```
┌──────────────────────────────────────────────┐
│ お知らせ・特集                                  │
│ ── 特集 ──────────────────────────────────────│
│ [ 特集バナー（プレースホルダー） ]  特集タイトル    │
│ ── お知らせ ────────────────────────────────── │
│ 2026-09-01  サイトオープンのお知らせ              │
│ 2026-09-10  送料無料キャンペーンのお知らせ         │
└──────────────────────────────────────────────┘
```

日付表示は JST に変換して `YYYY-MM-DD` 形式（本編 DS-DEC-16「表示は JST」を踏襲。ここは「利用者に見せる」表示なので JST 変換の対象になる。DS-PRC-005 の掲載判定＝サーバー内部比較＝が UTC のままなのと矛盾しない）。ホーム（SCR-001）の「お知らせ」欄（本編 6.3）は、この一覧の `news` 上位 3 件を埋め込みで表示する形に変える（現状の seed 固定文を置き換える）。

### 6.4 DS-SCR-012 FAQ・静的ページ（新設）

`/contents/[slug]` で 5 種の slug を共通レイアウトで表示する。

```
┌──────────────────────────────────────────────┐
│ FAQ                                             │
│                                                  │
│ Q. 注文後にキャンセルできますか？                  │
│ A. 出荷準備前であればマイページから取り消せます。    │
│    （ダミー本文。段落は空行区切りのプレーンテキスト）│
│                                                  │
│ Q. 送料はいくらですか？                            │
│ A. 4,990円以上のご注文で送料無料です。              │
└──────────────────────────────────────────────┘
```

本文は `white-space: pre-line` で改行を保持しつつ、React の既定エスケープのみで描画する（`dangerouslySetInnerHTML` を使わない。DS-DEC-38）。特商法表記ページ（`tokushoho`）は 375px・1280px とも同じ 1 カラムの定義リスト（項目名→内容）で表示する。

### 6.5 フッター・AllMenu のリンク先確定

| 箇所 | 現状 | 変更後 |
| --- | --- | --- |
| フッター「企業情報」 | `href="#"` | `/contents/company` |
| フッター「利用規約」 | `href="#"` | `/contents/terms` |
| フッター「プライバシー」 | `href="#"` | `/contents/privacy` |
| フッター「特商法」 | `href="#"` | `/contents/tokushoho` |
| フッター「FAQ」 | `href="#"` | `/contents/faq` |
| AllMenu「お知らせ」 | `href="#"`（P2 ラベル付き） | `/contents?kind=news` |
| AllMenu「FAQ」 | 同上 | `/contents/faq` |
| AllMenu「INFO」 | 同上 | `/contents/company`（本編・要件定義書に INFO の定義が無いため企業情報ページへの導線として割り当てた設計。9.3 のとおり統括確認済み・2026-09-24） |
| ヘッダー「検索」アイコン | `href="#"` | 6.1 のとおり入力欄・パネルに変更 |

## 7. セキュリティ設計（本編 7 章の差分）

| 項目 | 設計 | 検証 |
| --- | --- | --- |
| LIKE ワイルドカード注入 | 利用者入力を `.contains(term, autoescape=True)` 経由でのみ SQL に渡す。文字列連結でクエリを組まない（本編 7.1「型定義」の方針をそのまま適用） | ST: `%`・`_` を含む語で検索しても全件検索や意図しない大量ヒットにならない |
| 検索語の長さ・空文字 | 1〜100 文字。空白のみは 400 | UT: 100 文字超・空文字・空白のみの 3 パターン |
| コンテンツの XSS | 本文はプレーンテキストとして描画し、`dangerouslySetInnerHTML` を使わない（React の既定エスケープに全面的に依拠。DS-DEC-38） | ST: 本文に `<script>` 等を含む値を投入し、タグとして解釈されないことを確認 |
| 未公開・掲載期間外コンテンツの非表示 | `publish_from`／`publish_to` の判定を通らない行は一覧・詳細のどちらからも取得できない（DS-PRC-005・006） | IT: 期間外データを直接 slug 指定しても 404 |
| Azure MySQL の SSL 必須 | サーバー側で SSL 必須設定（Azure の既定）。クライアント側も `ssl_ca` を指定して検証付きで接続する（8.1） | IT: SSL 無しの接続文字列では接続がエラーになることを確認（要検証。9.2） |
| 検索 API のレート制限 | **P2-a では設計しない（ADR-0003・2026-09-24 承認）**。ゲスト注文照会（DS-API-023）のような個人情報アクセスではなく公開商品検索のため、本編 6 章の非機能要件（不正検知 100 件/時/ID）の対象外と判断した。P2-d（Azure 公開）着手前に要否を再判断する。詳細は `docs/00_計画/ADR/ADR-0003_検索APIのレート制限の見送り.md` | — |

## 8. インフラ・接続設計（本編 8 章の差分。ADR-0002）

### 8.1 DATABASE_URL の書式（仮説。実装の最初の作業は実接続の試行）

**2026-09-24 訂正**: draft-v1 では本節を「検証済み」としていたが、根拠は SQLAlchemy／asyncmy の**ソースコードを読んで導いた設計**であり、講義サーバーへの実接続では確認していなかった。統括レビューでこれを「未検証の仮説」として扱う方針に改め、**実装の最初の作業を「講義サーバーへの実接続の試行」に変更する**（DS-DEC-42）。以下は「まず試す第1案」と「ダメだった場合の第2案（フォールバック）」の 2 段構えで書く。

**第1案（コード変更なしで済む案）**: `mysql+asyncmy://` の接続文字列に **`ssl_ca=<CA証明書ファイルの絶対パス>`** をクエリパラメータとして付ける。

```
mysql+asyncmy://<DBユーザー名>:<URLエンコード済みパスワード>@gen12-mysql-pos.mysql.database.azure.com:3306/guapp_nonooktk?ssl_ca=<CA証明書ファイルの絶対パス>
```

**根拠（推測ではなく実装・ライブラリの中身を確認した結果）**:

1. SQLAlchemy の MySQL 系ダイアグレクト（`mysqldb`／`pymysql`／`asyncmy` は継承関係にあり、`asyncmy.py` は `pymysql.py` を、`pymysql.py` は `mysqldb.py` を継承する）は、接続 URL のクエリ文字列から `ssl_ca`・`ssl_key`・`ssl_cert`・`ssl_capath`・`ssl_cipher`・`ssl_check_hostname` の 6 キーだけを拾って `{"ssl": {"ca": ..., "key": ..., ...}}` という辞書に組み立て、それ以外のクエリキーは DBAPI の `connect()` へそのまま渡す（`apps/api/.venv/lib/python3.13/site-packages/sqlalchemy/dialects/mysql/mysqldb.py` の `create_connect_args()`、197〜242 行目付近を確認）。
2. asyncmy 0.2.14（本編 2 章の実装版）の `connect()` は `ssl` 引数を受け取り、`True`／`dict`／`ssl.SSLContext` のいずれかであることを要求する。`dict` の場合は `ca`／`capath`／`cert`／`key`／`cipher`／`check_hostname`／`verify_mode` を読み、標準ライブラリの `ssl.create_default_context(cafile=ca, capath=capath)` で `SSLContext` を作る（`apps/api/.venv/lib/python3.13/site-packages/asyncmy/connection.pyx` 530〜570 行目付近の `_create_ssl_ctx()` を確認）。
3. 1・2 の組み合わせにより、`?ssl_ca=<path>` を付けるだけで asyncmy 側に検証付きの TLS コンテキストが渡る**はず**（ソースコード上の推論。実接続は未確認）。もしこの第1案で接続できれば、**アプリのコード（`apps/api/app/core/db.py`）は変更不要**（`build_engine()` は接続文字列をそのまま `create_async_engine()` に渡すだけの実装のため）。

**第2案（フォールバック。第1案が通らなかった場合の具体策）**: `core/db.py` の `build_engine()` を、`ssl.create_default_context(cafile=settings.DB_SSL_CA_PATH)` で `ssl.SSLContext` を明示的に生成し、`create_async_engine(database_url, connect_args={"ssl": ctx}, pool_size=..., max_overflow=...)` として渡す実装に変更する。asyncmy の `connect()` は `ssl.SSLContext` を直接受け取れることが `_create_ssl_ctx()` の 1 行目（`isinstance(sslp, ssl.SSLContext): return sslp`）で確認できているため、こちらは URL クエリの解釈に依存しない分、確実性が高い。`DB_SSL_CA_PATH` は `core/config.py` に新設する設定項目とする（DS-DEC-45・46）。

**本編 8.2 の記載を実装で確認した結果、修正が必要と判明した点（→ 統括承認により本編修正済み）**: 本編 8.2 の環境変数表にはもともと `DATABASE_URL | api | mysql+asyncmy://...?ssl=true` という例が書かれていた。しかし 1 の `create_connect_args()` は `ssl_ca` 等の **`ssl_` で始まる個別キー**しか拾わず、単なる `ssl` というキーは特別扱いされない。この場合 `url.query` の生の値（文字列 `"true"`）がそのまま `opts["ssl"] = "true"` として残り、asyncmy の `connect(ssl="true")` に渡る。`_create_ssl_ctx()` は文字列を `ssl.SSLContext` でも `True`（bool）でも `dict` でもないと判定し、`ValueError("ssl argument must be True, a dict of ssl options, or an ssl.SSLContext, got 'str'")` を送出すると推定される（`asyncmy` 側のコードから読み取れる分岐であり、実接続で確かめてはいないため「推定」のまま。IT-AZ-02 で裏取りする）。この指摘は統括に確認済みで、**本編 8.2 の該当行は 1 行だけ訂正した**（9.3 参照。本編の改訂履歴にも記録済み）。

### 8.2 パスワードの記号エンコード

DB パスワードに `@`・`:`・`/`・`?`・`#` 等の記号が含まれると接続文字列の区切りと衝突するため、`urllib.parse.quote(password, safe="")` で URL エンコードしてから `DATABASE_URL` に埋め込む。

```bash
# パスワードを画面に表示せず URL エンコードする例（統括の作業端末で実行）
python3 -c "import urllib.parse, getpass; print(urllib.parse.quote(getpass.getpass('DB password: '), safe=''))"
```

出力された文字列を `DATABASE_URL` の `<URLエンコード済みパスワード>` 部分に貼り付ける。生パスワードや接続文字列そのものは本書には書かない（禁止事項）。

### 8.3 Alembic・seed の実行手順（Azure 向け）

```bash
cd apps/api
export DATABASE_URL="<8.1の書式で組み立てた値。ここに直接貼らず、別途安全な場所から貼り付ける>"
uv run alembic upgrade head
uv run python -m app.seed --reset --yes
```

PowerShell（Windows 作業端末の場合）:

```powershell
cd apps\api
$env:DATABASE_URL = "<同上>"
uv run alembic upgrade head
uv run python -m app.seed --reset --yes
```

手順自体はローカル MySQL のとき（本編 8.3、引継ぎメモの再開手順）と同じで、`DATABASE_URL` の中身だけが変わる。`.env` に書く場合も同様。

### 8.4 テスト用スキーマの扱い（2026-09-24 訂正: 結合テストは講義サーバーでは流さない）

**方針変更（DS-DEC-44・統括承認）**: 結合テスト（現状 213 件）は**講義サーバー（Azure）では実行しない**。これまでどおりローカル DB（Docker／zip 版の MySQL 8.4）で全件回す。講義サーバーに対しては、**IT-AZ-01・IT-AZ-02 の接続確認 2 件だけを手動で実行する**（テスト設計書追補 4.3 参照）。

この方針により、講義サーバー側に `guapp_nonooktk_test` スキーマを**作らない**（`DATABASE_URL_TEST` を使った pytest の自動実行が発生しないため、既存の安全装置＝`apps/api/tests/integration/conftest.py` の「DB 名が `_test` で終わっていなければ中止」という検査を Azure 側で使う機会が無い）。IT-AZ-01（疎通確認）は、本番／開発用のスキーマ `guapp_nonooktk` に対する**読み取り専用**の確認（`SELECT 1` 等、書き込みを伴わない）として実施する。

これは「サーバー用に `guapp_nonooktk`・テスト用に `guapp_nonooktk_test` の 2 スキーマを用意する」という 0.1 節・8.6 節のもともとの想定（ローカル開発と対称な構成）からの縮小であり、**ADR-0002 原案との差分**として 9.3 に記載する。将来、講義サーバーで結合テストを自動実行する必要が生じた場合は、その時点で `guapp_nonooktk_test` を作成する（8.6 の SQL 例を再利用できる）。

### 8.5 ローカル MySQL との切替

`.env` の `DATABASE_URL` を差し替えるだけで、ローカル MySQL（`mysql+asyncmy://root:...@127.0.0.1:3306/guapp`）と Azure MySQL（8.1 の書式）を切り替えられる。**コードに環境分岐は作らないが、設定項目は増える**（DS-DEC-45）。新設する環境変数は次の 3 つ。

| 環境変数 | 用途 | ローカルの既定値 | 講義サーバー接続時の推奨値 |
| --- | --- | --- | --- |
| `DB_SSL_CA_PATH` | CA 証明書ファイルの絶対パス（8.1 第2案で使用。第1案のみで足りる場合は未使用） | 未設定（ローカルは SSL 不要） | Mac／Windows／App Service（Linux）でそれぞれ異なるパスを設定（8.7） |
| `DB_POOL_SIZE` | `create_async_engine` の `pool_size` | 20（本編の既定値を維持） | 5（DS-DEC-46。共用サーバーの接続上限を圧迫しないため） |
| `DB_MAX_OVERFLOW` | `create_async_engine` の `max_overflow` | 10（本編の既定値を維持） | 5（同上） |

ローカル用の `docker-compose.yml`（本編 8.3）はそのまま残す。

### 8.6 統括向け手順（付録）

以下は統括が Azure ポータル・MySQL クライアントで実施する手順。値は全てプレースホルダで、本書には実値を書かない。

**(1) ファイアウォールへの IP 追加**: Azure ポータルの `gen12-mysql-pos` リソース → 「ネットワーク」→「ファイアウォール規則」に、作業端末の現在のグローバル IP（`<統括の作業PCのグローバルIP>`）を追加する。App Service ②（本番）からの接続は、本編 8.1 の「App Service の送信 IP のみ許可」の方針を Azure MySQL のファイアウォールにも適用する（App Service の送信 IP は Azure ポータルの App Service「プロパティ」→「送信 IP アドレス」で確認できる）。

**(2) 管理者での接続**: Azure ポータルの「接続」タブのクラウドシェル、または手元の `mysql` クライアントで管理者アカウント（Azure MySQL 作成時に設定した管理者ユーザー）で接続する。

```bash
mysql -h gen12-mysql-pos.mysql.database.azure.com -u <管理者ユーザー名> -p --ssl-mode=REQUIRED
```

**(3) スキーマとアプリ専用ユーザーの作成 SQL**（最小権限。ホストは Azure 側のファイアウォールで絞られているため `%` のままで運用する。本編 8.1 の DB Firewall 方針が主防御、ここは補助。**2026-09-24 訂正**: 8.4 の方針変更により `guapp_nonooktk_test` は当面作らない。結合テストを講義サーバーで自動実行する運用に変える場合は、下のコメントアウト部分を有効にする）:

```sql
CREATE DATABASE IF NOT EXISTS guapp_nonooktk
  CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

-- 講義サーバーでは結合テストを自動実行しない方針のため、テスト用スキーマは当面作らない（8.4・DS-DEC-44）。
-- 将来必要になった場合は次の 1 行を有効にする:
-- CREATE DATABASE IF NOT EXISTS guapp_nonooktk_test
--   CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

-- パスワードはここに書かず、実行時に別途安全な方法で埋める
CREATE USER IF NOT EXISTS 'guapp_app'@'%' IDENTIFIED BY '<統括が生成するパスワード>';

-- Alembic のマイグレーション（CREATE/ALTER/DROP TABLE）も同じユーザーで実行するため DDL 権限を含める
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, INDEX, REFERENCES
  ON guapp_nonooktk.* TO 'guapp_app'@'%';
-- guapp_nonooktk_test を作った場合は同じ GRANT をもう 1 行追加する
FLUSH PRIVILEGES;
```

`guapp_app` に `guapp_nonooktk`（および将来作る場合の `guapp_nonooktk_test`）以外のデータベースへの権限を与えない（`ON *.*` にしない）ことが最小権限の核心で、パスワード強度・ホスト制限はファイアウォールと合わせた多層防御の一部と位置づける。

**(4) `.env` の書式例**（値は全て `<...>` のプレースホルダ。`apps/api/.env` に統括が自分で値を書き込む）:

```
APP_ENV=production
DATABASE_URL=mysql+asyncmy://<DBユーザー名>:<URLエンコード済みパスワード>@gen12-mysql-pos.mysql.database.azure.com:3306/guapp_nonooktk?ssl_ca=<CA証明書ファイルの絶対パス>
# DB_SSL_CA_PATH は 8.1 第2案（フォールバック）を使う場合のみ設定する。第1案（DATABASE_URL の ssl_ca クエリ）で接続できれば不要
DB_SSL_CA_PATH=<CA証明書ファイルの絶対パス。OS ごとに書式が異なる（8.7）>
DB_POOL_SIZE=5
DB_MAX_OVERFLOW=5
INTERNAL_TOKEN=<web と同じ値>
CORS_ALLOW_ORIGIN=<本番の web オリジン>
```

**CA 証明書の入手**: 2026-09 時点で Microsoft Learn の記載（「Azure Database for MySQL の証明書のローテーション」）によれば、Azure Database for MySQL Flexible Server は DigiCert Global Root G2 と Microsoft RSA Root CA 2017 のチェーンを提示しており、検証を厳密に行う場合は DigiCert Global Root CA・DigiCert Global Root G2・Microsoft RSA Root Certificate Authority 2017 の 3 証明書を束ねたファイルを使うことが案内されている（`curl -sS https://cacerts.digicert.com/DigiCertGlobalRootCA.crt.pem` 等で個別取得可）。証明書のローテーションは今後も起こり得るため、**統括が実際に接続する時点で Microsoft Learn の最新ページを確認**してから証明書ファイルを作成すること（9.2 の要検証 #1）。

### 8.7 本番 OS・開発 OS の差（観点#4）

| 項目 | 差 | 対応 |
| --- | --- | --- |
| CA 証明書ファイルのパス表記 | Windows は `C:\Users\...\azure-mysql-ca.pem` のようにバックスラッシュとドライブ文字（`:`）を含む。接続文字列のクエリ値として扱えるが、スペースを含む場合は URL エンコードが必要 | パスにスペースを含めない。Windows でもフォワードスラッシュ表記（`C:/Users/.../azure-mysql-ca.pem`）で問題なく解釈される（Python の `open()`／`ssl.create_default_context(cafile=...)` は OS のパス区切りをどちらでも受け付ける） |
| App Service（Linux）でのファイル配置 | デプロイのたびにコンテナが作り直されるため、任意の一時パスに証明書を置く運用は壊れやすい | CA 証明書は秘密情報ではない（公開されている公的認証局の証明書）ため、リポジトリ内の固定パス（例: `apps/api/certs/azure-mysql-ca.pem`）にコミットしてよい。`core/config.py`・`core/db.py` の変更（`DB_SSL_CA_PATH` 等の追加）と合わせて実装時に対応する。実際のコード編集は本タスク（設計文書の作成）の対象外であり、別途実装作業として申し送る |
| `DB_SSL_CA_PATH` の値（新規。DS-DEC-42・45） | Mac／Windows／App Service（Linux）で場所が異なる | Mac: `/Users/<ユーザー名>/azure-mysql-ca.pem`。Windows: `C:/Users/<ユーザー名>/azure-mysql-ca.pem`（フォワードスラッシュ推奨）。App Service（Linux・本番）: `/home/site/wwwroot/certs/azure-mysql-ca.pem`（上記のとおりリポジトリに同梱してデプロイする） |
| 実接続で新たに要る依存（観点#3） | SSL 接続そのものは asyncmy・cryptography（既存依存）と Python 標準の `ssl` モジュールだけで完結し、新規パッケージは不要と判断した（2 章参照） | 追加インストール作業は無い想定。ただし「要検証」（9.2）が解消するまでは仮の結論として扱う |

## 9. 設計上の決定・申し送り

### 9.1 設計判断（DS-DEC-33〜46）

| DS-DEC | 決定 | 理由 | 次善策 |
| --- | --- | --- | --- |
| 33 | 検索の一致方法は商品名・説明・カテゴリ名の**部分一致**（OR 条件） | 統括決定（本タスクの指示）。31 商品規模で全文検索エンジンは過剰 | 商品名のみの部分一致（説明・カテゴリを含めない簡易版） |
| 34 | **（2026-09-24 訂正）** 検索の一致判定は DB の照合順序（`utf8mb4_0900_ai_ci`）にすべて委ね、アプリ側で表記ゆれの同一視を行わない（案A・統括承認）。入力の NFKC 正規化は残すが、目的を「前後・連続空白の整理」「長さ上限判定」「言い換え辞書のキー引き当て」の3点に限定する | コーディネーターがローカル MySQL 8.4・`utf8mb4_0900_ai_ci` で確認した事実により、draft-v1 の前提（全角半角は吸収しない）が誤りと判明した。`'ｼｬﾂ'='シャツ'`・`'Ｔシャツ'='tシャツ'`・`'あ'='ア'`・`'ハハ'='パパ'`・`'バッグ'='パック'`・`'ジーンズ'='シーンス'` が同一判定、`LIKE '%ハンツ%'` がパンツ系4件にヒットすることを確認済み。DB 照合が表記ゆれを吸収するため、アプリ側で二重に正規化・同一視のロジックを持つ必要が無い（F-031 実装時の書き込み時正規化も、検索目的では不要と判断し取り下げ） | DB 照合に加えてアプリ側でも正規化した生成列を持つ（二重管理になり、案Aの「DB 任せ」という利点が消えるため不採用） |
| 35 | LIKE のワイルドカードは SQLAlchemy の `contains(..., autoescape=True)` に任せ、自前のエスケープ関数を書かない | 標準機能で足りる場合に独自実装を増やすと、エスケープ順序のバグ（エスケープ文字自体のエスケープ漏れ等）を新たに作り込むリスクがある | `re.sub` による手動エスケープ（`\`→`%`→`_` の順で `\` を先に処理） |
| 36 | 検索サジェスト（106 Could）は「見送り」にせず、商品名の前方一致優先・部分一致補充の軽量方式として設計・実装対象に含める | 商品 31 点規模であれば LIKE 前方一致で応答時間の懸念が無い | Could のまま P2-a では設計のみに留め、実装は P3 に送る |
| 37 | **（2026-09-24 訂正）** 検索 0 件時の代替導線は「固定の言い換えリスト」＋「おすすめカテゴリ（公開商品数上位3件。同数時は `categories.sort_order` 昇順→`id` 昇順）」。言い換えリストの対象は **DB 照合では吸収されない「別語」の表記ゆれに絞る**（例:「ティーシャツ」／「Tシャツ」、「デニム」／「ジーンズ」のような、綴りが別物の同義語）。DB 照合が既に吸収する全角半角・かな種別・清濁音違いは辞書に入れない（入れても無意味なため） | DS-DEC-34 の訂正を受け、辞書の役割を「DB 照合で拾えない同義語の補完」に純化した。おすすめカテゴリの同数時の並び順は、本編 `list_categories_with_counts` の既定の並び順（`sort_order, id`）と揃え、新しい判定基準を増やさないため | シソーラス API 等の外部辞書を使う（演習規模には過剰） |
| 38 | コンテンツ本文はプレーンテキストのみとし、Markdown・HTML レンダリングは行わない | Markdown 描画には別途サニタイズ処理（許可要素の限定）が必要になり、現状 `apps/web` に Markdown・サニタイズ系の依存が無い。React の既定エスケープ（`{value}` 展開）だけで XSS を防げる範囲に留める方が安全側に振れる | Markdown 対応ライブラリ＋サニタイザ（例: `remark`＋`rehype-sanitize`）を追加する |
| 39 | FAQ・静的ページは `contents` の 5 行（`faq`×1、`static`×4）で表現し、`slug` ごとに 1 ページとする | REQ-FR-903 が要求する 5 到達先（FAQ・利用規約・プライバシー・特商法・企業情報）と 1 対 1 に対応させ、管理のしやすさを優先した | FAQ を質問単位で複数行に分割する（Q&A の個別管理は F-034 の管理画面実装後に検討） |
| 40 | `contents` の掲載期間判定はサーバー内部で UTC のまま比較し、JST 変換はしない。表示（お知らせの日付）は JST に変換する | 判定はサーバー内部の処理であり、本編 DS-DEC-16「表示は JST」の対象は利用者向け表示に限られるため | 判定自体も JST に寄せる（タイムゾーン変換の手間が増えるだけで利益が無いため不採用） |
| 41 | 特定商取引法表記・企業情報は架空の事業者名・住所・電話番号を用いるダミーとし、「本サイトは講義演習用のデモです」と明記する | 実在の GU・株式会社ジーユー・ファーストリテイリングになりすまさないため（禁止事項） | — |
| 42 | **（2026-09-24 訂正）** Azure MySQL への SSL 接続方式は「`DATABASE_URL` に `ssl_ca=<path>` を付けるだけ」を**未検証の仮説**として扱い、実装の最初の作業を「講義サーバーへの実接続の試行」にする。CA 証明書ファイルの場所は環境変数 `DB_SSL_CA_PATH` に持たせ、Mac／Windows／App Service（Linux）で値を変える（8.7）。接続できなかった場合の代替は、`core/db.py` の `build_engine()` で `ssl.create_default_context(cafile=settings.DB_SSL_CA_PATH)` を明示的に生成し `connect_args={"ssl": ctx}` として渡す実装に切り替える（8.1 第2案） | draft-v1 の「検証済み」はソースコードを読んだ設計であり、実接続では確認していなかった。統括レビューでこれを仮説として明示し、検証と代替策をセットで持つ方針に改めた | 最初から `connect_args` 方式（第2案）だけを設計する（クエリパラメータ方式が通るなら不要な実装を先に決め打ちすることになるため、まず軽い方を試す順序にした） |
| 43 | パスワードに記号を含む場合は `urllib.parse.quote(password, safe="")` で URL エンコードしてから `.env` に書く | 接続文字列の区切り文字（`@`・`:`・`/` 等）との衝突を避けるため | パスワードに記号を使わない運用にする（強度が下がるため不採用） |
| 44 | **（2026-09-24 訂正）** 結合テスト（現状213件）は講義サーバー（Azure）では実行せず、引き続きローカル DB（Docker／zip版）で全件回す。講義サーバーに対しては IT-AZ-01・02 の接続確認2件だけを手動で実行する。これに伴い、講義サーバー側に `guapp_nonooktk_test` スキーマは当面作らない（IT-AZ-01 は `guapp_nonooktk` への読み取り専用確認で足りる） | 講義サーバーは共用リソースであり、pytest の結合テスト（同時実行テストや大量の INSERT/DELETE を含む）を自動実行する必要性・安全性が無いと判断した。テスト用スキーマも使う予定が無いなら先に作らない（8.4） | 当初案（`guapp_nonooktk`・`guapp_nonooktk_test` の2面構成）どおり両方作り、結合テストも Azure で回せるようにする（共用サーバーへの負荷・データ汚染のリスクを理由に不採用） |
| 45 | **（2026-09-24 訂正）** ローカル MySQL と Azure MySQL の切替は `.env` の値の差し替えのみで行い、**コードに環境分岐は作らないが、設定項目（環境変数）は増える**（`DB_SSL_CA_PATH`・`DB_POOL_SIZE`・`DB_MAX_OVERFLOW`。8.5） | 本編 DS-DEC-25「ローカル DB は Docker MySQL 8.4」を維持しつつ Azure にも対応できる最小差分。「コード変更なし」という draft-v1 の言い方は、DS-DEC-42・46 で設定項目が増えたことと整合しないため「分岐は作らない」に限定して書き直した | 環境ごとに接続設定ファイルを分ける（オーバーエンジニアリング） |
| 46 | `core/db.py` の `POOL_SIZE=20`・`MAX_OVERFLOW=10`（モジュール定数）を環境変数 `DB_POOL_SIZE`・`DB_MAX_OVERFLOW` で上書きできるようにする。**既定値は現状どおり 20／10**（ローカル・本番 App Service は変更なし）。**講義サーバー接続時の推奨値は 5／5** | gunicorn 2 ワーカー×既定値では最大60コネクションになり、共用の講義サーバー（Azure MySQL）の接続上限を他の受講者と食い潰す恐れがある（9.2 要検証#4）。既定値は変えず、講義サーバー接続時だけ環境変数で絞れるようにするのが最小変更 | モジュール定数のまま環境ごとに値をハードコードする分岐を書く（環境変数化より変更箇所が増える） |

### 9.2 P2 事前レビュー観点（8 問）記入表

| 観点 # | 該当 | 確認方法 | 結果・備考 |
| --- | --- | --- | --- |
| 1 数字と列挙の一致 | あり | 本書中の「N 件」「N 表」等の数字を、対応する列挙・表の行数と突き合わせ | 5.2 の seed 初期データ「8 件」は表の行数 8 と一致。4.3 の「5 種固定」は表の行数 5 と一致。9.1 の DS-DEC は 33〜46 の連番で 14 件、本表（9.2）は事前レビュー観点の 8 問固定で一致（2026-09-24 差し戻しで DS-DEC-46 を追加し 13→14 件に更新） |
| 2 ロック表と同時実行 | なし | 検索・コンテンツ・Azure 接続のいずれも、同一トランザクション内で複数行を排他的に更新する処理を持たない（全て読み取り専用 API） | 該当なし。F-003・028・030 は書き込みを伴わないため DS-DEC-07 のような多重防御は不要と判断した |
| 3 実接続で表れる依存 | あり | asyncmy・SQLAlchemy の実装コードを直接確認し、SSL 接続に新規パッケージが要るかを検証 | 2 章・8.1 のとおり新規パッケージは不要と判断した。ただし**接続方式そのもの**（クエリパラメータ方式かコード直書き方式か）は実接続してみるまで確定しない仮説であり（2026-09-24 訂正）、実装の最初の作業を実接続の試行にする（下記「要検証 #2・#3」） |
| 4 開発 OS と本番 OS の差 | あり | CA 証明書パス（`DB_SSL_CA_PATH`）の表記・App Service のファイル配置を検討 | 8.7 に記載。Mac・Windows・App Service（Linux）で値を変える前提の環境変数にした。パスにスペースを含めなければ OS 間の表記差は吸収できる（Python 標準 `ssl`／`asyncmy` の実装から判断） |
| 5 正規表現と文字種 | あり | 検索語の全角・半角・ひらがなカタカナ・濁点半濁点・前後空白の扱いを検討 | **（2026-09-24 訂正）** 4.4「NFKC 正規化と DB 照合順序の関係」に記載。コーディネーターの実機確認により、`utf8mb4_0900_ai_ci` は全角半角・ひらがなカタカナ・清濁音まで同一視する寛容な照合順序であると判明（draft-v1 の「吸収しない」という前提は誤りだった）。この挙動を仕様として受け入れ（案A）、一致判定は DB 照合に一任、NFKC 正規化は整形・辞書引き当て用途に限定した。濁点無視による拾いすぎ（例:「ハンツ」→「パンツ」）は既知の制限としてテスト設計書追補 ST-F003-07 に明記した |
| 6 表示書式の文字コード | なし | 金額表示（`Intl.NumberFormat` 等）を新規に増やしていない。検索結果・コンテンツの金額表示は既存の `Price`／`formatYen` をそのまま再利用する設計のため、新しい文字コード起因の不具合は生まれない | 該当なし |
| 7 フレームワークの制約 | あり | Next.js の Server Component の制約（Cookie 発行不可等）が新規ページに影響するか確認 | `/search`・`/contents/[slug]` はいずれも読み取り専用の Server Component で Cookie を発行しない。検索欄の状態保持（開閉・入力値）はクライアントコンポーネント側で行うため、本編 P1 で確認済みの制約（P2 事前レビュー観点 #7）と同じ回避策（Client Component 化）をそのまま使う |
| 8 ビルド時の外部到達 | なし | フォント・外部レジストリへの新規到達を増やしていない（`next/font/google` の利用は本編・デザイン基準 v1 で確認済みの Noto Sans JP のみ） | 該当なし |

**要検証（本書内で解決できず、実施を IT・Wave 0 に送る事項）**:

| # | 内容 | 確認方法（予定） |
| --- | --- | --- |
| 1 | Azure Database for MySQL Flexible Server の CA 証明書チェーンの現行構成（8.6 に記載の DigiCert／Microsoft RSA の組み合わせ）は、証明書ローテーションにより変わり得る | 統括が接続作業を行う直前に Microsoft Learn の「Azure Database for MySQL の証明書のローテーション」ページを確認し、案内どおりの証明書ファイルを用意する |
| 2 | `?ssl_ca=<path>` を付けた `DATABASE_URL` で実際に Azure へ接続できるか（8.1 は SQLAlchemy／asyncmy のソースコードから導いた設計であり、実機での接続確認はまだ行っていない） | P2 Wave 0（接続の素振り）で `uv run python -c "..."` の最小コードにより疎通確認する。テスト設計書 IT-AZ-01 |
| 3 | 本編 8.2 の `?ssl=true` という書式が実際に接続エラーになるか（8.1 の「推定」の裏取り） | 同上。あえて `?ssl=true` で接続を試み、`ValueError` になることを確認してから本編修正案（9.3）を統括に提示する。テスト設計書 IT-AZ-02 |
| 4 | 講義サーバー接続時の推奨値 `DB_POOL_SIZE=5`／`DB_MAX_OVERFLOW=5`（DS-DEC-46）で十分か、それとも講義サーバー側の `max_connections` がさらに厳しいか | Azure 側で `SHOW VARIABLES LIKE 'max_connections'` を実行して確認する。想定より厳しければ推奨値をさらに下げる（環境変数を変えるだけで対応でき、コード変更は不要） |
| 5 | Windows のローカル開発環境から Azure MySQL への接続で、ファイアウォールの動的 IP（自宅・移動先で変わる IP）が接続の安定性に影響しないか | 実際に複数の作業場所から接続を試し、都度 IP 追加が必要になる運用上の負荷を確認する |

### 9.3 本編との差分・矛盾（2026-09-24 統括判断反映）

| # | 本編（または前回 draft-v1）の記載 | 本書での指摘 | 結論・状態 |
| --- | --- | --- | --- |
| 1 | 本編 8.2「DATABASE_URL \| api \| `mysql+asyncmy://...?ssl=true`」 | 8.1 で示したとおり、SQLAlchemy の MySQL ダイアレクトは `ssl_ca` 等の個別キーしか解釈せず、単独の `ssl=true` は文字列のまま asyncmy に渡り接続エラーになると推定される（実接続未確認。9.2 要検証 #3） | **本編も訂正済み**。統括承認のうえ、本編 `GU_ECsite_設計仕様書_P1_draft-v3.md` 8.2 の該当行を「`?ssl_ca=<CA証明書ファイルの絶対パス>`（詳細は P2 追補a 8 章）」に 1 行だけ修正し、改訂履歴に 2026-09-24 の訂正を 1 行追加した（本編の差分は本セクション末尾の diff、および本編ファイル自体を参照） |
| 2 | 本編 5.2 DS-TBL-22「kind(feature/news/faq/static), slug(UNIQUE), title, body, publish_from, publish_to, sort_order」 | 型・制約・索引が未記載だったため本書 5.1 で肉付けした。`published` 列を追加せず掲載期間のみで公開・非公開を表す設計にした点は本編に明記が無かった判断だった | **統括確認済み（2026-09-24）**。`published` 列を追加しない設計のまま確定。本編には手を入れず、本書 5.1・DS-DEC-40 の詳細化を正とする |
| 3 | 本編 4.2 DS-API-004 の概要「キーワード検索。0 件時は代替導線（類似語・おすすめカテゴリ）」 | サジェスト（DS-API-004a）を新しい枝番として追加した。本編の表には無い ID だった | **統括確認済み（2026-09-24）**。DS-API-004a を追補限りの ID として確定（本編は改訂しない）。本編の次回改訂（本編と追補を統合する版）が出るタイミングで、本編 4.2 表に正式な行として追記することとする |
| 4 | AllMenu の「INFO」リンクの遷移先 | 要件定義書・本編のどちらにも INFO の定義が無く、本書では企業情報ページへの導線として割り当てた（6.5） | **統括確認済み（2026-09-24）**。「INFO」→`/contents/company`（企業情報ページ）の割り当てで確定 |
| 5 | 検索 API へのレート制限（旧: 統括判断を仰ぐ事項） | 本編 9.4 はゲスト照会（DS-API-023）のレート制限のみ申し送っている。検索 API（DS-API-004）の大量呼び出し対策（スクレイピング対策）は未設計だった | **ADR で見送りを正式決定（2026-09-24）**。P2-a では実装せず、Azure で公開する P2-d の前に判断する。決定内容は `docs/00_計画/ADR/ADR-0003_検索APIのレート制限の見送り.md` を参照 |
| 6 | ADR-0002（`docs/00_計画/ADR/ADR-0002_講義MySQLへのスキーマ追加と資格情報の管理.md`）の原案: 講義サーバー側にも `guapp_nonooktk`・`guapp_nonooktk_test` の 2 スキーマを用意し、ローカル開発と対称な構成にする想定だった | 統括レビューで「結合テストは講義サーバーでは流さない」方針（DS-DEC-44）に変わったため、`guapp_nonooktk_test` を当面作らない設計に縮小した（8.4・8.6） | **ADR-0002 側にも反映済み（2026-09-24）**。ADR-0002 は `docs/00_計画/ADR/` の一覧（ADR-0001〜0003）に含まれる既存のファイルであり、末尾の「変更履歴」に本件（`guapp_nonooktk_test` を当面作らない）を追記した。本書側は本節と DS-DEC-44 に同じ内容を記録する |

### 9.4 テスト設計書への申し送り

- IT-AZ-01・02（9.2 要検証 #2・#3）は Azure 環境が無いと実施できないため、P2 Wave 0（接続の素振り）まで実施を送る。**2026-09-24 訂正**: 213 件の結合テストとは別枠の**手動実行**とし、講義サーバーの `guapp_nonooktk`（読み取り専用の確認のみ）に対して行う。`guapp_nonooktk_test` は作らない（DS-DEC-44）
- 検索・コンテンツ系のセキュリティ試験（LIKE ワイルドカード注入・XSS・掲載期間外の非表示）はローカルで実施可能なため、P2-a のテスト設計に含める（テスト設計書追補 参照）
- **2026-09-24 追加**: DB 照合順序が全角半角・かな種別・清濁音を吸収する挙動（DS-DEC-34）を「仕様」として確認するテスト、および濁点無視による拾いすぎ（既知の制限）を観測するテストをテスト設計書追補に追加する
- **2026-09-24 追加**: `DB_POOL_SIZE`／`DB_MAX_OVERFLOW` の環境変数上書き（DS-DEC-46）の UT を追加する
- Azure 側のプールサイズ上限（9.2 要検証 #4）は `DB_POOL_SIZE`／`DB_MAX_OVERFLOW`（DS-DEC-46）で対応済みのため、結果次第で推奨値（既定 5／5）を調整するだけで済み、追加の設計判断は不要になった

### 9.5 覆りうる判断の申し送り（2026-09-24 追加）

次の決定は、状況が変わった場合に見直す前提で確定していることを明記する。

| DS-DEC | 覆りうる条件 | 見直しの方向 |
| --- | --- | --- |
| DS-DEC-38（コンテンツ本文はプレーンテキストのみ） | 特商法表記など、表形式（項目名→内容の対応）での表示が必須と判断された場合 | Markdown 描画対応（許可要素を限定したレンダラー＋サニタイズ）を追加する。現状は React の既定エスケープのみで足りると判断しているため、表が必要になった時点で再検討する |
| DS-DEC-39（FAQ は `slug=faq` の 1 行にまとめる） | P2-d（AI アシスタント、F-029）で FAQ を回答の知識源として使う際、質問単位で検索・引用したいという要件が出た場合 | FAQ を質問単位で複数行（`contents.kind='faq'` を複数行に分割し、`slug` を `faq-001` 等に変える）に再設計する。P2-a 時点では 1 行で十分なため据え置く |
| DS-DEC-36（検索サジェスト DS-API-004a を設計・実装対象に含める） | 9/30（Week7 デプロイ）までの実装が他機能で遅延し、優先度を下げる必要が生じた場合 | Could 優先度のとおり**最初に削る候補**とする。DS-API-004a を実装せず、DS-API-004（検索本体、Must 相当の REQ-FR-105）を優先する。設計自体は本書に残すため、P3 以降での実装再開は容易 |

## 10. トレーサビリティ表（P2-a 追加分）

本編 10 章の表に、P2-a で追加した行を積み足す形。テスト ID は追補テスト設計書のものを参照する。

| REQ | F / SCR | DS | AT | ST | IT | UT |
| --- | --- | --- | --- | --- | --- | --- |
| REQ-FR-105 | F-003 / SCR-002 | DS-API-004・DS-PRC-004・DS-SCR-002（検索モード） | AT-09 | ST-F003-01〜04・07 | IT-004-01〜05・07・08 | UT-SEARCH-01〜04・07 |
| REQ-FR-106 | F-003 / ヘッダー | DS-API-004a・DS-PRC-004a | — | ST-F003-05 | IT-004a-01/02 | UT-SEARCH-05 |
| REQ-FR-107 | F-003 / SCR-002 | DS-API-004・DS-PRC-004 手順5 | AT-10 | ST-F003-06 | IT-004-06 | UT-SEARCH-06 |
| REQ-FR-903 | F-028 / SCR-012 | DS-API-006・DS-PRC-006・DS-TBL-22 | AT-11 | ST-F028-01〜03 | IT-006-01〜04 | UT-CONTENT-03 |
| REQ-FR-1001 | F-030 / SCR-011 | DS-API-005・DS-PRC-005・DS-TBL-22 | — | ST-F030-02 | IT-005-03 | — |
| REQ-FR-1002 | F-030 / SCR-011・ホーム | DS-API-005・DS-PRC-005・DS-TBL-22 | AT-12 | ST-F030-01 | IT-005-01/02 | UT-CONTENT-01/02 |
| （ADR-0002） | — インフラ | 8 章・DS-DEC-42〜46 | — | ST-SEC-15 | IT-AZ-01/02（手動実行。8.4） | UT-DBCONF-01 |

P1 本編のトレーサビリティ表（REQ-FR-101〜1205 等）は変更しない。上表は本編表への追加分のみを示す（2026-09-24 差し戻しでテスト ID を更新。件数は 9.1〜9.5 および本表の内容と一致させた）。
