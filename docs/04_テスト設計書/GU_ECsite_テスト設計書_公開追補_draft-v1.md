# GU EC サイト テスト設計書（公開追補）

| 項目 | 内容 |
| --- | --- |
| 文書番号 | GUEC-TD-01-PUB |
| 版 | draft-v1 |
| 作成者 | タキシードサム／キャタピー（Claude） |
| 作成日 | 2026-09-25 |
| 入力 | 本編 `GU_ECsite_テスト設計書_P1_draft-v2.md`、P2 追補a `GU_ECsite_テスト設計書_P2追補a_draft-v1.md`、設計仕様書公開追補 `GU_ECsite_設計仕様書_公開追補_draft-v1.md`、ADR-0004 |
| 対象 | ADR-0004：Basic 認証・期間限定バナー・Azure App Service 公開に伴うテスト |

## 改訂履歴

| 版 | 日付 | 内容 | 作成 | 承認 |
| --- | --- | --- | --- | --- |
| draft-v1 | 2026-09-25 | 初稿。Basic 認証・期間限定バナーの UT／ST を新設 | タキシードサム／キャタピー | — |

## 0. 本書の位置づけ

本書は本編・P2 追補a の追補であり、本編の ID 体系（`ST-SEC-nn`／`UT-nnn-nn`）をそのまま使う。P2 追補a の `ST-SEC-15` に続けて `ST-SEC-16` から採番する。UT は `apps/web` の命名慣行（`ut-web-nn.<対象>.test.ts`）に合わせ `UT-WEB-09`・`UT-WEB-10` とする。

## 1. テスト方針（差分）

- Basic 認証・期間限定バナーの UT は TDD で実施した（先にテスト、赤の確認、その後実装）。実装は `apps/web/lib/basic-auth.ts`・`apps/web/lib/demo-banner.ts`・`apps/web/proxy.ts`・`apps/web/components/DemoPeriodBanner.tsx`
- ST のうち、Azure App Service 上でしか確認できない項目（ST-SEC-25 の HTTPS リダイレクト等）は「実施時期: Azure デプロイ後」として未実施のまま記録する。それ以外（ST-SEC-16〜24）はローカルの standalone 起動で実施可能なため、本タスク中に実施した

## 2. システムテスト（ST）追加分

### 2.1 Basic 認証

| ID | 対象 | 区分 | 観点・手順 | 期待結果 | 実施結果 |
| --- | --- | --- | --- | --- | --- |
| ST-SEC-16 | DS-DEC-48・49 | 異常 | `Authorization` ヘッダを付けずに `/`・`/products`・`/api/health` を開く | いずれも 401。`WWW-Authenticate: Basic realm="GUapp demo", charset="UTF-8"` が付く | **実施済み（ローカル standalone）**。`curl -s -o /dev/null -w "%{http_code}"` で 401、ヘッダも一致を確認 |
| ST-SEC-17 | DS-DEC-48・49 | 異常 | 誤った ID・パスワードで `Authorization: Basic ...` を付けて開く | 401 | **実施済み**。`curl -u reviewer:wrong` で 401 を確認 |
| ST-SEC-18 | DS-DEC-48・49 | 正常 | 正しい ID・パスワードで `/`・`/api/health` を開く | 200（`/api/health` は BFF 配下として同じ扱いで 200） | **実施済み**。`curl -u reviewer:s3cret-demo` で `/`・`/api/health` とも 200 を確認 |
| ST-SEC-16a | DS-DEC-48 | 正常 | `BASIC_AUTH_USER`／`BASIC_AUTH_PASSWORD` を両方未設定にして起動する | 401 にならない（認証なしでローカル開発が続けられる） | **実施済み**。`pnpm test`（UT-WEB-09）で確認。standalone でも未設定起動で 200 になることを確認済み |
| ST-SEC-16b | DS-DEC-49 | 異常 | 片方だけ設定（例: `BASIC_AUTH_USER` のみ）して起動する | 起動時（モジュール読み込み時）に失敗する | **実施済み（UT レベル）**。`proxy.ts` の動的 import が `BasicAuthConfigError` で reject することを確認（UT-WEB-09）。実際の App Service 起動での失敗挙動は Azure デプロイ後に確認する（未実施） |
| ST-SEC-16c | 7.1 | 正常 | ハッシュ付き静的ファイル（`_next/static/...`）を認証なしで取得する | 200（対象外のため Basic 認証を要求しない） | **実施済み**。standalone 起動で該当パスを認証なし curl して 200 を確認 |

### 2.2 期間限定バナー

| ID | 対象 | 区分 | 観点・手順 | 期待結果 | 実施結果 |
| --- | --- | --- | --- | --- | --- |
| ST-SEC-19 | DS-DEC-50 | 正常 | `DEMO_PUBLIC_UNTIL=2026-10-09` で起動し、任意のページを開く | ヘッダー上部に「講義レビュー用のデモとして、2026/10/09 まで期間限定で公開しています」が表示される | **実施済み**。standalone 起動＋curl で本文中に文言（RSC のコメントノードを含む）を確認 |
| ST-SEC-20 | DS-DEC-50 | 正常 | 稼働中のサーバーを `DEMO_PUBLIC_UNTIL` の値だけ変えて再起動する（再ビルドしない） | 再ビルドなしで表示される終了日が変わる | **実施済み**。同じ `.next` ビルド成果物のまま `DEMO_PUBLIC_UNTIL=2026-11-30` で再起動し、表示が `2026/11/30` に変わることを確認 |
| ST-SEC-20a | DS-DEC-50 | 異常 | `DEMO_PUBLIC_UNTIL` を不正な形式（`2026/11/30`）にして起動する | 帯が表示されない。サーバーログに警告が出る | **実施済み**。standalone 起動ログに `[demo-banner] DEMO_PUBLIC_UNTIL の形式が不正です...` が出力され、本文に帯の文言が含まれないことを確認 |
| ST-SEC-20b | DS-DEC-50 | 正常 | `DEMO_PUBLIC_UNTIL` を未設定にする | 帯が表示されない（警告も出ない） | **実施済み**（UT-WEB-10 で確認。standalone でも未設定時に帯が出ないことを確認） |

### 2.3 本番設定（既存実装の再確認）

| ID | 対象 | 区分 | 観点・手順 | 期待結果 | 実施結果 |
| --- | --- | --- | --- | --- | --- |
| ST-SEC-21 | 7.2・DS-DEC-14 | 正常 | `APP_ENV=production` で web を起動し、カート等の Cookie 発行を伴う操作をする | `Set-Cookie` に `Secure` が付く | 実施済み（既存の `tests/st-sec-07.cookie.test.ts` で UT レベル確認済み。本番相当 standalone での curl 確認は本タスクの標準確認手順に含める） |
| ST-SEC-22 | 7.2 | 異常 | `APP_ENV=production` で api を起動し `/docs`・`/redoc`・`/openapi.json` を開く | いずれも 404 | 既存実装済み（`apps/api/app/main.py`）。api 側の pytest（既存 279 件）に含まれる想定機能の再確認であり、本書で新規テストは追加しない |
| ST-SEC-23 | 7.2 | 異常 | `CORS_ALLOW_ORIGIN` に設定していないオリジンから api へ preflight (`OPTIONS`) を送る | CORS ヘッダが付かず拒否される | 既存実装済み（`install_cors()`）。新規テストなし |
| ST-SEC-24 | 7.2・DS-DEC-27 | 異常 | `X-Internal-Token` を付けずに api の URL を直接叩く | 401 `unauthorized`（`/api/v1/health` を除く） | 既存実装済み（`verify_internal_token()`）。新規テストなし |

### 2.4 デプロイ環境（Azure 環境が必要。未実施）

| ID | 対象 | 区分 | 観点・手順 | 期待結果 | 実施結果 |
| --- | --- | --- | --- | --- | --- |
| ST-SEC-25 | 8 章・HTTPS Only | 異常 | Azure App Service に対して `http://` でアクセスする | `https://` へリダイレクトされる | **未実施**（Azure 環境が必要。デプロイ後に実施） |

## 3. 単体テスト（UT）追加分

### 3.1 Next.js（Vitest）

実装場所は `apps/web/tests/`。TDD で先に作成し、実装前に赤（モジュール未解決エラー）を確認済み。

| ID | 対象 | 区分 | ファイル | 主な確認内容 |
| --- | --- | --- | --- | --- |
| UT-WEB-09 | `lib/basic-auth.ts`・`proxy.ts`（DS-DEC-48・49） | 正常・異常・境界 | `tests/ut-web-09.basic-auth.test.ts`、`tests/ut-web-09.proxy-basic-auth.test.ts` | 両方未設定→null、片方のみ→`BasicAuthConfigError`、正しい／誤った ID・パスワード、scheme の大文字小文字、コロンを含むパスワード、不正な base64、`proxy()` の 401／通過、`config.matcher` の形 |
| UT-WEB-10 | `lib/demo-banner.ts`・`components/DemoPeriodBanner.tsx`（DS-DEC-50） | 正常・異常・境界 | `tests/ut-web-10.demo-banner.test.ts`、`tests/ut-web-10.demo-period-banner.test.tsx` | 未設定・空文字・空白のみ→null（警告なし）、正しい形式→`YYYY/MM/DD` 変換、形式不正・実在しない日付・うるう年境界→null＋警告、コンポーネントの表示・非表示、`role="status"` |

**新規テスト件数（`pnpm test` 実測）**: UT は `it()` 単位で 35 件（`ut-web-09.basic-auth` 15 件・`ut-web-09.proxy-basic-auth` 6 件・`ut-web-10.demo-banner` 11 件・`ut-web-10.demo-period-banner` 3 件）。既存 163 件と合わせて web 合計 198 件（`pnpm test` で全件緑を確認済み）。ST は 16 件（SEC-16・16a・16b・16c・17・18・19・20・20a・20b・21〜25 の 16 件、うち SEC-25 のみ未実施）。

## 4. 実施計画

| 時期 | 内容 |
| --- | --- |
| 本タスク中 | UT 全件（TDD）、ST-SEC-16〜24 をローカル standalone ビルドで実施 |
| Azure デプロイ後（統括承認後の別タスク） | ST-SEC-25（HTTPS リダイレクト）、ST-SEC-16b の実機起動確認、実際のレビュワー動線での最終確認 |

## 5. 申し送り

- ST-SEC-22〜24 は新規実装を伴わない既存機能の確認であり、既存の pytest／Vitest スイート（api 279 件・web 198 件）に含まれる。本タスクでは api 側のコード変更を行っていないため、新規テストファイルは追加していない
- Basic 認証・帯の Azure 上での最終確認（ST-SEC-25 含む）は、デプロイ後に統括が `scripts/azure-deploy/README.md` の確認手順に従って実施すること
- 検索 API のレート制限（ADR-0003）は本公開でも見送りのままのため、追加テストは無い。ADR-0003 が再訪された場合はテスト設計を別途起こすこと

## 6. トレーサビリティ表（公開追補分）

| 対象 | DS | ST | UT |
| --- | --- | --- | --- |
| Basic 認証 | DS-DEC-48・49 | ST-SEC-16・16a・16b・16c・17・18 | UT-WEB-09 |
| 期間限定バナー | DS-DEC-50 | ST-SEC-19・20・20a・20b | UT-WEB-10 |
| 本番設定（既存） | 7.2 | ST-SEC-21〜24 | — |
| HTTPS リダイレクト | 8 章 | ST-SEC-25（未実施） | — |
