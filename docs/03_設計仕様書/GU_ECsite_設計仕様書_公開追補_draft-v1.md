# GU EC サイト 設計仕様書（公開追補）

| 項目 | 内容 |
| --- | --- |
| 文書番号 | GUEC-SD-01-PUB |
| 版 | draft-v1 |
| 作成者 | タキシードサム／キャタピー（Claude） |
| 作成日 | 2026-09-25 |
| 入力 | 本編 `GU_ECsite_設計仕様書_P1_draft-v3.md`、P2 追補a `GU_ECsite_設計仕様書_P2追補a_draft-v1.md`、ADR-0002〜0004、`02_プロジェクト/GUapp/技術選定_実績調査_2026-09-06.md`、Next.js 16 同梱ドキュメント（`apps/web/node_modules/next/dist/docs/`）、実装（`apps/web/`・`apps/api/`） |
| 対象 | ADR-0004：Tech0 講義レビュー期間限定の Azure App Service 公開（Basic 認証・期間限定バナー・デプロイ構成） |

## 改訂履歴

| 版 | 日付 | 内容 | 作成 | 承認 |
| --- | --- | --- | --- | --- |
| draft-v1 | 2026-09-25 | 初稿。ADR-0004 の実装詳細（Basic 認証・期間限定バナー・App Service 構成・環境変数・デプロイ手順・本番設定）を本編・P2 追補a の差分として作成 | タキシードサム／キャタピー | — |

## 0. 本書の位置づけ

本書は本編（`GU_ECsite_設計仕様書_P1_draft-v3.md`、以下「本編」）および P2 追補a の追補であり、**ADR-0004 に伴う差分だけ**を書く。章番号は本編の構成（1 構成／6 画面／7 セキュリティ／8 インフラ／9 設計判断）に対応させる。本編・P2 追補a に既に書かれていて変わらない事項（BFF と FastAPI の 2 層構成、App Service Plan B1・Always On、`gunicorn` を基本とする起動コマンドの方針、DB 接続の SSL 方式そのもの等）は再掲しない。

### 0.1 対象範囲

ADR-0004 の決定に基づき、次の 4 点を設計する。

1. サイト全体・BFF `/api/*` への HTTP Basic 認証（Next.js 16 の `proxy.ts`）
2. 全ページ上部の期間限定バナー
3. Azure App Service への実デプロイ構成（リソース名・環境変数・デプロイ手順）
4. 本番設定の確認（`APP_ENV=production` による Secure Cookie・Swagger 非表示。既存実装の再確認であり新規実装ではない）

**本タスクでは Azure リソースの作成・変更・デプロイは行わない。** 8 章のデプロイ手順・スクリプトは統括承認後に別途実行する準備として作成する。

### 0.2 設計 ID の追加

| 種別 | ID | 備考 |
| --- | --- | --- |
| 判断 | DS-DEC-48〜55 | 本書 9.1 に一覧 |

## 6. 画面設計（本編・P2 追補a との差分）

### 6.1 期間限定バナー（共通レイアウト差分。DS-DEC-50）

- 位置: 全ページ共通。ヘッダーの直上（`apps/web/app/layout.tsx` の `<body>` 内、`HeaderWithCart` より前）
- 文言: 「講義レビュー用のデモとして、`YYYY/MM/DD` まで期間限定で公開しています」（`YYYY/MM/DD` は `DEMO_PUBLIC_UNTIL` から変換した終了日）
- 表示条件: `DEMO_PUBLIC_UNTIL`（環境変数、`YYYY-MM-DD`）が設定され、かつ実在する日付として解釈できる場合のみ表示する。未設定・形式不正・実在しない日付（例: `2026-13-01`）は**表示せず**、サーバーログに警告を出す（例外は投げない。1 件の環境変数ミスでサイト全体が落ちないようにするため）
- 色だけで意味を伝えない: 帯の意味（デモ・期間限定であること）は文言そのもので明示する。背景・文字色は基準トークン `--color-line`（背景）・`--color-fg`（文字）を流用し、新しいトークンは追加しない（付録デザイン基準 v1 の色は `@theme` で `initial` 化され、定義済みトークン以外を Tailwind ユーティリティとして使えないため）
- 375px 幅での可読性: 固定の 1 行文言で、375px では折り返して 2〜3 行になる（`text-sm`・`px-4`・`text-center`）。切り詰め（`line-clamp` 等）はしない
- 本番・開発の出し分けをしない: `DS-DEC-47`（デモの個人情報対策）と同じ考え方で、本番（Azure 公開後）でも常時表示する。環境分岐を増やすと「本番だけ消し忘れる」事故の余地が生まれるため（DS-DEC-47 の理由をそのまま踏襲）
- 実装: 純粋関数 `apps/web/lib/demo-banner.ts` の `parseDemoPublicUntil()` が検証・変換を行い、`apps/web/components/DemoPeriodBanner.tsx`（Server Component、`role="status"`）が描画する。`layout.tsx` が `process.env.DEMO_PUBLIC_UNTIL` を読んで渡す（`NEXT_PUBLIC_` を付けない。付けるとビルド時に値が埋め込まれ、再デプロイなしの延長ができなくなるため）

## 7. セキュリティ設計（本編・P2 追補a との差分）

### 7.1 Basic 認証の処理仕様（DS-DEC-48・49）

| 項目 | 設計 |
| --- | --- |
| 方式 | Next.js 16 の `proxy.ts`（`apps/web/proxy.ts`。旧 `middleware.ts` は v16 で非推奨・改称済み。`apps/web/node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/proxy.md` で確認済み） |
| 対象 | `matcher: ["/((?!_next/static|_next/image|favicon.ico|sitemap.xml|robots.txt).*)"]`。全ページ・BFF `/api/*`（`/api/health` を含む）が対象。理由は「対象外の判断」参照 |
| 対象外 | `_next/static`・`_next/image`・`favicon.ico`・`sitemap.xml`・`robots.txt` |
| 認証情報 | 実行時の環境変数 `BASIC_AUTH_USER`・`BASIC_AUTH_PASSWORD`（`NEXT_PUBLIC_` を付けない。サーバーだけが読む） |
| 両方未設定 | 認証なし（ローカル開発を妨げない） |
| 片方だけ設定 | `apps/web/lib/basic-auth.ts` の `parseBasicAuthConfig()` が `BasicAuthConfigError` を投げる。`proxy.ts` はモジュール読み込み時（サーバー起動〜最初のリクエストの間）にこれを評価するため、設定ミスのまま無防備に公開されることはなく、代わりに全リクエストが失敗する形で気づける |
| 比較方式 | SHA-256 ダイジェスト化してから `crypto.timingSafeEqual` で比較する時間一定比較（`verifyBasicAuthHeader()`）。ID・パスワードそれぞれを別々に固定長ダイジェスト化してから比較するため、入力長の違いによる早期リターンが起きない |
| 401 応答 | `WWW-Authenticate: Basic realm="GUapp demo", charset="UTF-8"` を付けて 401（本文なし） |
| ランタイム | Next.js 16 で `proxy` の既定ランタイムが Node.js になった（v16 の変更点。同ドキュメントの Version history で確認済み）ため、`node:crypto` をそのまま使える。Edge ランタイム特有の制約を考慮する必要がない |

**対象外（静的アセット）の判断根拠**: `_next/static`・`_next/image` はビルド時にハッシュ付きファイル名で生成される。ファイル名を知るには、まず認証済みの HTML・RSC ペイロードを取得する必要があり、Basic 認証を通過していない第三者がファイル名を推測することは実務上困難である。内容もアプリのコード・画像などのビルド成果物であり、個人情報・非公開の業務データ（商品の非公開在庫数・注文内容等）を含まない。これらを対象外にすることで、`next build` が生成する静的アセットの配信をキャッシュ・CDN 等で最適化する余地を残す（今回は使わないが、将来の変更を妨げない）。一方で `/api/*`（BFF）は個人情報アクセスではない検索・商品閲覧 API も含めて全て保護対象にする（ADR-0004・ADR-0003 参照）。

**ADR-0003 との関係（DS-DEC-48 の補足）**: 検索 API（DS-API-004）へのレート制限は、ADR-0004 の判断により本公開でも実装しない。Basic 認証を知らない第三者は `/api/*` に到達できないため、ADR-0003 が懸念する不特定多数からの大量呼び出しは、この前提の下では発生しない。

### 7.2 既存のセキュリティ設計との重複確認（新規実装なし）

次は本編・P2 追補a で既に設計・実装済みであり、本書では変更しない。統括承認事項の確認のため一覧化する。

| 項目 | 既存の設計・実装 | 確認方法 |
| --- | --- | --- |
| Swagger 非表示 | `apps/api/app/main.py` の `create_app()` が `settings.is_production` で `docs_url=None, redoc_url=None, openapi_url=None` にする（本編 4.1・7.1） | 本番相当（`APP_ENV=production`）起動で `/docs`・`/redoc`・`/openapi.json` が 404 になることを ST で確認（8 章テスト設計書追補） |
| Cookie の Secure 属性 | `apps/web/lib/cookie.ts` の `buildSetCookie()` が `appEnv === "production"` のときだけ `Secure` を付ける（本編 7.3・DS-DEC-14。既存テスト `tests/st-sec-07.cookie.test.ts` で確認済み） | 本番相当の standalone 起動で Cookie に `Secure` が付くことを curl で確認（8.6） |
| CORS | `apps/api/app/core/security.py` の `install_cors()` が `CORS_ALLOW_ORIGIN`（web の URL 1 つ）だけを許可し、ワイルドカードを禁止（本編 7.1） | `CORS_ALLOW_ORIGIN` に web の App Service URL を設定する運用を 8.2 に明記 |
| 内部認証 | `apps/api/app/core/security.py` の `verify_internal_token()` が `X-Internal-Token` を検証。BFF を経由しない直接アクセスは 401（本編 4.1・DS-DEC-27） | api の URL を直接叩くと 401 になることを ST で確認 |
| HTTPS | App Service の「HTTPS Only」設定（本編 7.6）。HTTP でのアクセスは HTTPS へリダイレクトされる | `01-create.sh` で `--https-only true` を設定する |

## 8. インフラ・デプロイ設計（本編・P2 追補a との差分。ADR-0004）

### 8.1 Azure リソース（実デプロイ向けの命名）

| リソース | 名前（既定） | 備考 |
| --- | --- | --- |
| リソースグループ | `rg-001-gen12` | 既存（受講生で共用。新規作成しない） |
| App Service Plan | `asp-guapp-nonooktk` | Linux・B1。既存の `TV_MVP`・`POS` と名前が衝突しないよう `guapp-nonooktk` を含める |
| App Service（web） | `app-guapp-web-nonooktk` | Node 24。`https://app-guapp-web-nonooktk.azurewebsites.net` |
| App Service（api） | `app-guapp-api-nonooktk` | Python 3.13 |
| Azure Database for MySQL | `gen12-mysql-pos`（`guapp_nonooktk`） | 既存（ADR-0002。新規作成しない） |

**命名衝突時の方針（DS-DEC-55）**: App Service 名は Azure 全体で一意（`*.azurewebsites.net` のグローバル DNS 名のため）。`az webapp show`（読み取りのみ）で名前の空き状況を事前確認し、衝突した場合は末尾に短い連番（`-1`・`-2`）を付けて再試行する。`config.sh` の変数を書き換えるだけで済むようにし、他のスクリプトには固定名を直書きしない。

### 8.2 環境変数一覧

| 名前 | 置き場 | 用途 | 秘密か |
| --- | --- | --- | --- |
| `APP_ENV` | api | `production` に設定し Swagger 非表示・Secure Cookie を有効化 | いいえ |
| `DATABASE_URL` | api | 講義 MySQL への接続文字列（ADR-0002・本編 8.1）。`apps/api/.env.azure` の資格情報から `with-azure-db.sh` と同じ方式で組み立てる | **はい** |
| `DB_POOL_SIZE` | api | `5`（DS-DEC-46 の講義サーバー向け推奨値） | いいえ |
| `DB_MAX_OVERFLOW` | api | `5`（同上） | いいえ |
| `DB_SSL_CA_PATH` | api | CA 証明書ファイルの絶対パス（本番は `/home/site/wwwroot/certs/azure-mysql-ca.pem`。8.4 参照） | いいえ（公開情報の証明書） |
| `INTERNAL_TOKEN` | web・api | BFF → FastAPI の内部認証共有シークレット。web・api で同じ値にする | **はい** |
| `CORS_ALLOW_ORIGIN` | api | web の App Service URL（例 `https://app-guapp-web-nonooktk.azurewebsites.net`） | いいえ |
| `IMAGE_BASE_URL` | web | 商品画像の配信ベース URL（既存） | いいえ |
| `API_BASE_URL` | web | api の App Service URL | いいえ |
| `BASIC_AUTH_USER` | web | Basic 認証の ID（ランダム生成） | **はい** |
| `BASIC_AUTH_PASSWORD` | web | Basic 認証のパスワード（ランダム生成） | **はい** |
| `DEMO_PUBLIC_UNTIL` | web | 期間限定バナーの終了日（既定 `2026-10-09`） | いいえ |
| `WEBSITES_PORT` | web | `3000`（standalone の `server.js` の既定ポート） | いいえ |
| `PORT` | web | `3000`（Next.js standalone がこの値で listen する） | いいえ |
| `WEBSITES_CONTAINER_START_TIME_LIMIT` | web | `600`（実績調査どおり。起動失敗の緩和） | いいえ |

「秘密」欄が「はい」の項目は `scripts/azure-deploy/02-settings.sh` が生成・設定するが、値をターミナル・ログに出力しない（8.5 参照）。

### 8.3 デプロイ手順の概要

1. `config.sh` でリソース名・リージョン・SKU・ランタイムを読み込む
2. `01-create.sh`: App Service Plan（B1）と web・api の 2 App Service を作成し、Always On・HTTPS Only・最小 TLS 1.2、起動コマンド、`WEBSITES_PORT`／`PORT`／`WEBSITES_CONTAINER_START_TIME_LIMIT` を設定する
3. `02-settings.sh`: アプリ設定（8.2 の環境変数）を投入する。秘密は生成してそのまま設定に渡し、画面には出さない
4. `03-db-firewall.sh`: api の送信 IP を取得し、講義 MySQL のファイアウォールに `guapp-appsvc-<連番>` の規則で追加する
5. `06-migrate-seed.sh`: `with-azure-db.sh` 経由で `alembic upgrade head` を実行する（seed は統括の指示があるときだけ）
6. `04-deploy-api.sh`・`05-deploy-web.sh`: それぞれビルドして `az webapp deploy` で zip デプロイする
7. 動作確認（Basic 認証・帯表示・API 疎通）を統括が実施し、問題なければレビュワーに ID・パスワードを共有する
8. 期間終了後は `90-stop.sh` で停止、不要になれば `99-delete.sh` で削除する

各スクリプトは冪等に作る（既存リソースがあれば設定を上書きするだけで、エラーにしない）。作成系コマンドの前に `az account show` でサブスクリプション・リソースグループを表示し、確認を求める（本タスクでは Azure 操作を行わないため、スクリプトの実行はしない）。

### 8.4 CA 証明書の配置方針（DB_SSL_CA_PATH。DS-DEC-52）

App Service Linux のシステムの信頼ストア（例 `/etc/ssl/certs/ca-certificates.crt`）に DigiCert Global Root G2 等が含まれているかは、実際に App Service にデプロイしてみないと確認できない（未検証）。

- **方針（採用）**: P2 追補a 8.7 で既に決定済みの方式をそのまま踏襲する。CA 証明書（DigiCert Global Root CA・DigiCert Global Root G2・Microsoft RSA Root Certificate Authority 2017 の 3 証明書束ね。`scripts/azure-db/fetch-ca.sh` で取得済みの方式と同じ）をデプロイ成果物に同梱し、`apps/api/certs/azure-mysql-ca.pem` に配置する。`DB_SSL_CA_PATH` は App Service 上のパス `/home/site/wwwroot/certs/azure-mysql-ca.pem` を指す。この方式は既にローカルから講義サーバーへの実接続で検証済み（P2 追補a 9.2 要検証 #2）であり、App Service でもホストパスが変わるだけで同じ仕組みがそのまま動く見込みが高い
- **代替（不採用・参考記載）**: `DB_SSL_CA_PATH` を空にし、asyncmy／Python 標準 `ssl` にシステム既定の CA ストアを使わせる方法もあり得るが、システムストアに必要な CA が含まれているかは未検証であり、実接続で確認済みの方式（採用案）より不確実性が高い。採用案で接続できない場合の切り分け用にこの代替を残す
- CA 証明書は秘密情報ではない（公開されている公的認証局の証明書）ため、リポジトリへのコミットは禁止事項に抵触しない。ただし証明書のローテーションが起こり得るため、`apps/api/certs/azure-mysql-ca.pem` は `scripts/azure-db/fetch-ca.sh` の出力をデプロイ直前にコピーする運用とし、リポジトリに固定コミットはしない（`04-deploy-api.sh` がコピーしてから zip する）

### 8.5 秘密情報の扱い（スクリプト共通方針）

`scripts/azure-db/with-azure-db.sh` と同じ考え方をデプロイスクリプトにも適用する。

- 生成した秘密（`INTERNAL_TOKEN`・`BASIC_AUTH_USER`・`BASIC_AUTH_PASSWORD`・DB パスワード）は `echo`・`print`・ログ出力しない
- Basic 認証の ID・パスワードだけは、統括が後で確認できるよう `apps/web/.env.basic-auth`（権限 600）にスクリプトが書き込む。画面には「このファイルに書きました」とだけ表示する。同ファイルは `.gitignore` 対象であることを `git check-ignore` で確認してからスクリプトを完了させる
- `az webapp config appsettings set` へは環境変数経由で値を渡し、コマンドライン引数の値を `ps` 等で見えるようにしない

### 8.6 起動コマンド・依存関係（DS-DEC-53・54）

| 項目 | 方針 |
| --- | --- |
| web の起動 | `output: "standalone"`（`apps/web/next.config.ts` に設定済み）。`node server.js` を起動コマンドにする。`public/`・`.next/static` を `.next/standalone/` 配下にコピーするのはデプロイスクリプト（`05-deploy-web.sh`）が行う（Next.js の self-hosting ガイドどおり） |
| api の requirements.txt | **コミットしない**。`04-deploy-api.sh` がデプロイ直前に `uv export --format requirements-txt --no-hashes --no-dev -o requirements.txt` を実行して生成し、zip に含める（`uv.lock` との二重管理・ドリフトを避けるため。DS-DEC-53） |
| api の起動コマンド | 設計（本編 8.1・実績調査）では `gunicorn -w 2 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000 app.main:app` が基本だが、**`gunicorn` は `apps/api/pyproject.toml` の依存に含まれていない**（`uv export` の出力 45 パッケージで確認済み）。依存追加は統括承認が必要な事項のため、本タスクでは追加しない。暫定の起動コマンドは `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2`（`uvicorn[standard]` に含まれる `--workers` オプションで複数ワーカーを賄う）とし、`gunicorn` を追加してよいと承認が出た時点で本編どおりのコマンドに切り替える（DS-DEC-54） |

## 9. 設計上の決定・申し送り

### 9.1 設計判断（DS-DEC-48〜55）

| DS-DEC | 決定 | 理由 | 次善策 |
| --- | --- | --- | --- |
| 48 | サイト全体・BFF `/api/*`（`/api/health` 含む）に HTTP Basic 認証をかける。`_next/static`・`_next/image`・favicon 等は対象外 | レビュー期間限定で不特定多数に公開しない目的に対し、実装コストが最小でスコープ全体を一括保護できる（ADR-0004）。静的アセットはハッシュ付きファイル名で第三者が推測しづらく、個人情報・非公開データを含まないため対象外にした | Route Handler ごとに個別の認証を実装する（実装量が多く、新設 API を保護し忘れるリスクがある） |
| 49 | Basic 認証の設定は「両方未設定→認証なし」「片方だけ→起動時（モジュール読み込み時）に例外で失敗」「比較は SHA-256 ダイジェスト化してからの時間一定比較」とする | ローカル開発を妨げない・設定ミスを無防備な公開にしない・タイミング攻撃を避ける、の 3 点を同時に満たす最小の実装 | パスワードハッシュ（bcrypt 等）を使う（Basic 認証はリクエスト毎に平文相当の値を送るため、保存側のハッシュ強度を上げても攻撃面は変わらず、依存追加のコストに見合わない） |
| 50 | 期間限定バナーの終了日は実行時環境変数 `DEMO_PUBLIC_UNTIL`（`YYYY-MM-DD`）。未設定・形式不正・実在しない日付は警告ログを出し帯を表示しない。本番でも常時表示する | コード変更なしでの期間延長（`NEXT_PUBLIC_` を使わない）と、1 件の設定ミスでサイト全体が落ちない安全側動作を両立する。本番だけ帯を消す環境分岐は DS-DEC-47 と同じ理由（消し忘れ事故の余地）で避けた | ビルド時に日付を埋め込む（`NEXT_PUBLIC_DEMO_PUBLIC_UNTIL`）。延長のたびに再ビルド・再デプロイが必要になるため不採用 |
| 51 | 検索 API（DS-API-004）のレート制限は、ADR-0003 の見送りを本公開でも維持する | Basic 認証を通過できない第三者は `/api/*` に到達できず、ADR-0003 が懸念する大量呼び出しの前提が成立しないため（ADR-0004） | Basic 認証と併用でレート制限も入れる（多層防御にはなるが、レビュー期間限定という目的に対しては過剰でスコープ増になるため見送り） |
| 52 | `DB_SSL_CA_PATH` は App Service でも CA 証明書ファイルを明示指定する（`/home/site/wwwroot/certs/azure-mysql-ca.pem`）。システム既定の信頼ストアには頼らない | ローカルから講義サーバーへの実接続で既に検証済みの方式（P2 追補a 9.2）をそのまま使う方が、未検証のシステムストア依存より確実性が高い | システム既定の CA ストアに任せる（`DB_SSL_CA_PATH` 未設定）。App Service Linux の CA ストア構成が確認できた時点で切替を検討する |
| 53 | api の `requirements.txt` はリポジトリにコミットせず、デプロイ直前に `uv export` で生成する | `uv.lock` が正であり、`requirements.txt` を別途コミットすると更新忘れによるドリフト（本番だけ古い依存で動く）が起きうるため | `requirements.txt` をコミットし、CI で `uv export` の出力と一致するか検証する（今回は自動デプロイ〈GitHub Actions〉が未整備のため、検証の仕組みまで作るのは Week7 に送る） |
| 54 | api の起動コマンドは暫定で `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2` とし、`gunicorn` の追加は統括承認を得てから本編どおりの起動コマンドに切り替える | `gunicorn` は現在の依存に含まれておらず、依存追加は本タスクの禁止事項（統括承認が要る事項）に該当するため、承認を待たずに追加しない | 承認を待たず `gunicorn` を追加する（禁止事項に反するため不採用） |
| 55 | App Service 名は `asp-guapp-nonooktk` 等、`guapp-nonooktk` を含む名前にし、衝突時は末尾に連番を付けて `config.sh` の変数だけを変える | 共用リソースグループ内の既存リソース（`TV_MVP`・`POS`）およびグローバルに一意な `*.azurewebsites.net` 名前空間との衝突を避ける | 生成 UUID を含む名前にする（一意性は高いが、統括が名前から用途を判別しづらくなるため不採用） |

### 9.2 P2 事前レビュー観点（8 問）記入表

| 観点 # | 該当 | 確認方法 | 結果・備考 |
| --- | --- | --- | --- |
| 1 数字と列挙の一致 | あり | DS-DEC の連番（48〜55 で 8 件）、環境変数一覧（8.2、15 行）を本文の記載と突き合わせ | 一致を確認 |
| 2 ロック表と同時実行 | なし | Basic 認証・バナーとも読み取り専用の判定処理で、DB 行の排他制御を伴わない | 該当なし |
| 3 実接続で表れる依存 | あり | `proxy.ts` が `node:crypto` を使うために必要なランタイムを確認 | Next.js 16 で `proxy` の既定ランタイムが Node.js になったことをドキュメントで確認済み（7.1）。追加パッケージは不要 |
| 4 開発 OS と本番 OS の差 | あり | 開発（Mac）と本番（App Service Linux）で `DB_SSL_CA_PATH` のパス表記が異なる（既存 P2 追補a 8.7 の枠組みをそのまま使う） | 8.4 に記載。新たな差異はない（既存方針の再確認） |
| 5 正規表現と文字種 | あり | `DEMO_PUBLIC_UNTIL` の日付形式検証（`YYYY-MM-DD`）の正規表現が全角数字を誤って通さないか確認 | `\d{4}-\d{2}-\d{2}` は JavaScript の `\d` が半角数字のみに一致するため、全角数字は形式不一致として弾かれる（UT-WEB-10 で確認） |
| 6 表示書式の文字コード | あり | 帯の日付表示 `YYYY/MM/DD` の区切り文字（全角スラッシュにならないか） | 固定文字列 `"/"` を使うテンプレートリテラルで組み立てており、`Intl` 等の環境依存フォーマッタを使わないため文字化けの余地がない |
| 7 フレームワークの制約 | あり | Next.js 16 で `middleware.ts` が `proxy.ts` に改称された変更が、既存実装に影響しないか確認 | 影響なし（`middleware.ts` は存在しなかったため新規追加のみ）。`apps/web/AGENTS.md` の指示に従い、実装前に同梱ドキュメントを確認済み |
| 8 ビルド時の外部到達 | なし | Basic 認証・バナーとも新規の外部到達（フォント・レジストリ等）を増やしていない | 該当なし |

### 9.3 テスト設計書への申し送り

- Basic 認証・期間限定バナーの UT は `apps/web/tests/ut-web-09.*`・`ut-web-10.*` として実装済み（TDD で先にテストを書き、赤を確認してから実装した）
- ST（401／200 の実地確認、`/docs` 404、CORS、HTTPS リダイレクト等）は Azure 環境が無いと実施できない項目を含むため、テスト設計書追補に「実施時期: Azure デプロイ後」として記載する
- IT-AZ-01・02（P2 追補a）と同様、Basic 認証・帯表示の Azure 上での確認も自動化せず手動実施とする

## 10. トレーサビリティ表（公開追補分）

| 対象 | DS | ST | UT |
| --- | --- | --- | --- |
| Basic 認証（サイト全体・BFF） | DS-DEC-48・49、7.1 | ST-SEC-16〜18 | UT-WEB-09 |
| 期間限定バナー | DS-DEC-50、6.1 | ST-SEC-19・20 | UT-WEB-10 |
| 本番設定（既存実装の再確認） | 7.2 | ST-SEC-21〜24 | — |
| App Service 構成・デプロイ（HTTPS リダイレクト含む） | DS-DEC-52〜55、8 章 | ST-SEC-25（Azure 環境要） | — |
| 検索 API レート制限見送りの継続 | DS-DEC-51、ADR-0003・0004 | — | — |
