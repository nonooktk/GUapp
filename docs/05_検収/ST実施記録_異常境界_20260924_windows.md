# GU EC サイト P1 ST 実施記録（異常・境界・セキュリティ）

| 項目 | 内容 |
| --- | --- |
| 実施日 | 2026-09-24（JST 10:32〜11:20） |
| 実施者 | バッドばつ丸（QA 悲観視点） |
| 対象 | テスト設計書 GUEC-TD-01 draft-v2: 3.1 の区分「異常」「境界」全件、ST-F032-01/02（ペックルから委譲）、3.2 の ST-SEC-02〜06・08・10・11 |
| 環境（共用） | web `http://localhost:3000`、FastAPI `http://127.0.0.1:8000`（`APP_ENV=development`・`INTERNAL_TOKEN=dev-local-token`・`PAYMENT_STUB_RESULT` 未設定＝ok）、MySQL 8.4.11 開発 DB `guapp`（開始時 orders 5 件・V-STOCK1 stock 1・V-STOCK0 stock 0・tax_rate "0.10"／shipping_fee 550／free_shipping_threshold 4990） |
| 環境（自前・終了時に停止） | FastAPI 8020（`PAYMENT_STUB_RESULT=ng`、後半は `ok` で再起動）、FastAPI 8021（`APP_ENV=production`。ST-SEC-11 では `DATABASE_URL` を到達不能な `127.0.0.1:3307` に差し替えて再起動）、web 3020（`apps/web` を scratchpad に複製し独立 `node_modules` で `pnpm dev -p 3020`、`API_BASE_URL=http://127.0.0.1:8020`） |
| ブラウザ | Claude Code 内蔵ブラウザ（Chromium、1024×768）。スクリーンショット取得可。加えて DOM・`sessionStorage`・fetch 応答を JavaScript で読み取った値、curl のステータス／本文／ヘッダ、DB の SELECT 結果を証拠とする |
| 独立性 | ペックルの記録（`ST-AT実施記録_正常系_20260918.md`）は対象の重複回避のために読んだが、判定のすり合わせはしていない |
| DB 変更 | 開発 DB `guapp` のみ。`guapp_test` は触っていない。変更した値はすべて元に戻し、5 章の SELECT で確認 |

ルール: 期待結果の文言をそのまま観測できたときだけ「合格」。設計書 4.5 の `code` と HTTP ステータスまで確認する。観測できなかったものは「未実施（理由）」。

記録した注文番号（本作業で生成）: **GU-260924-2YS3MV7G**（ST-F014-04・決済 NG・`payment_failed`）、**GU-260924-UDX4Q6MQ**（ST-F014-02 の「別ブラウザ」側・V-STOCK1 を購入・`accepted`）、**GU-260924-DX56JE6Z**（ST-SEC-05・氏名に攻撃文字列・`accepted`）

## 0. 事故報告（環境）— 共用 web 3000 を壊した 🔴（環境。成果物のバグではない）

| 項目 | 内容 |
| --- | --- |
| 何が起きたか | 10:56 に共用 web `http://localhost:3000` の全ページが 500（Next.js dev overlay「Runtime Error: An unexpected Turbopack error occurred」。詳細 `TurbopackInternalError: Failed to write app endpoint /page … [project]/app/globals.css [app-client] (css) … PostCssTransformedAsset::process failed`）。`/api/*`（BFF Route Handler）は 200 で生きている。FastAPI 8000・MySQL は無事 |
| 原因（オレさまのミス。確定） | 第 2 インスタンス用に `apps/web` を scratchpad `…\scratchpad\web3020\` に複製したとき、`node_modules` を**ジャンクション（`mklink /J`）で本物の `apps/web/node_modules` に向けた**まま `pnpm dev -p 3020` を実行した（10:56）。pnpm が起動前に依存の整合を走らせ、ジャンクション越しに本物の `apps/web/node_modules` 内の **パッケージ用ジャンクション 18 本（next・react・react-dom・tailwindcss・eslint・jsdom・server-only ほか）の向き先を、複製側の絶対パス `…\scratchpad\web3020\node_modules\.pnpm\…` に書き換えた**（`dir /AL` で確認。作成時刻 10:56）。この時点では複製側がジャンクションで本物を指していたので実体は同じで、3000 は 11:03 まで正常に描画していた（ST-F032-01/02・F014-03 は 10:57〜11:03 に 3000 で合格）。11:04 にオレさまが複製側のジャンクションを外して独立 `pnpm install` を行った瞬間、本物の 18 本が**別ディレクトリの実体**を指すことになり、Turbopack が `globals.css` の Tailwind 解決で `FileSystemPath("").join("../../../../../../AppData/Local/Temp/claude/…/web3020/node_modules/.pnpm/tailwindcss@4.3.3/node_modules/tailwindcss/index.css") leaves the filesystem root` を出して全ページ 500 になった（エラー本文にこのパスが出ているので因果は確定） |
| 影響 | 3000 でのブラウザ確認が 11:04 以後不能。ST-F009-05・F014-02・F014-04・SEC-05 は自前の 3020（独立 `node_modules`）で実施した。`apps/web` の**ソース・`package.json`・`pnpm-lock.yaml`・`.next` は変更していない**。変わったのは `node_modules/` 配下のみ（ジャンクション 18 本の向き先と `.modules.yaml`・`.pnpm/lock.yaml`）。**scratchpad の `web3020/` は消していない**（消すと 18 本が宙に浮いて 3000 の `/api/*` も壊れうる。修復後に消すこと） |
| 修復手順（コーディネーター／担当へ依頼。オレさまは `apps/web` で `pnpm install` を実行しようとしたが、共有リソース変更として権限ポリシーに止められたのでそこで手を止めた。3000 の再起動も指示どおり行っていない） | 1. `apps/web` で `pnpm install --frozen-lockfile --prefer-offline`（lockfile どおりにジャンクションを `apps\web\node_modules\.pnpm\…` へ張り直す。数十秒） 2. `apps/web/node_modules` で `cmd /c "dir /AL /S" \| findstr scratchpad` が 0 件になることを確認 3. 稼働中の `pnpm dev`（3000）を再起動（Turbopack が旧パスをキャッシュしている可能性があるため） 4. 3000 が 200 になったら scratchpad の `web3020/` を削除してよい |
| 再発防止 | 第 2 インスタンスは「複製ディレクトリで `pnpm install` して独立 `node_modules` を持たせる」だけにする。**`node_modules` のジャンクション／シンボリックリンク共有は禁止**（pnpm はジャンクションの向き先を絶対パスで書き換え、Turbopack はプロジェクト外のリンクを拒否する）。手順を `apps/web/README.md` か wiki に残すのを提案 |
| Slack | 11:06 に【ブロック】報告（この時点の原因記述は「メタデータ書き換え」で不正確）→ 終了報告で原因の確定版と修復手順を訂正 |

## 1. システムテスト 3.1 機能要件（区分「異常」「境界」＋委譲分）

| ID | 手順（実施したこと） | 期待結果 | 観測結果 | 判定 | 証拠 |
| --- | --- | --- | --- | --- | --- |
| ST-F001-02 | FastAPI `GET /api/v1/products?page=1,2`（全件 29 件・24＋5）と BFF `GET /api/products?page=1,2` の `items[].id` を列挙。`GET /api/v1/products/30` と web `/products/30` を直打ち | 一覧に出ない。URL 直打ちの商品詳細は 404 | 一覧 id は 1〜29（30 なし。P-ALL0 の 28 は在庫 0 でも公開なので含む）。FastAPI 30 → `404 {"code":"not_found"}`。web `/products/30` → HTTP 404、本文「ページが見つかりません」 | 合格 | curl |
| ST-F001-03 | — | 24 件区切り | — | 重複・省略（ペックルが全件 29 件で 24／29 → 29／29 を確認済み） | — |
| ST-F007-01 | web `/products/29` でブラック → M（`GU-029-BK-M`・V-STOCK0）。BFF `POST /api/cart/items {variant_id:170}`（CSRF 付き）と FastAPI 直叩き | ボタン無効。API 直叩きでも 409 `out_of_stock` | ボタン文言「在庫切れ」`disabled=true`、`aria-live` 領域「在庫切れ」、サイズボタンの名前も「サイズ M（在庫切れ）」。BFF・FastAPI とも `409 {"code":"out_of_stock","items":[170]}` | 合格 | ブラウザ DOM・curl |
| ST-F009-03 | 新カートに variant 26 を数量 10 で追加 → 別 variant 27 を数量 11 で追加 → 既存明細 26 に +1（10→11）→ `PATCH` で数量 11 → `PATCH` で 10 | 10 は成功、11 は 422 でエラー表示 | 10 → `201 Created`。11（新規・加算・PATCH の 3 経路）すべて `422 {"code":"limit_exceeded","field":"quantity","limit":10}`。PATCH 10 → 200 | 合格（API。画面の数量セレクトは 1〜10 しか出ないため 11 は UI から入力不能＝設計どおり） | curl |
| ST-F009-04 | 同カートに variant 26〜30 を各 10（5 明細・合計 50）→ 51 点目に variant 31 を 1 | 50 は成功、51 は 422 | 50 点まで全 201、`item_count 50`。51 点目 → `422 {"code":"limit_exceeded","field":"quantity","limit":50}`、`item_count` は 50 のまま | 合格 | curl |
| ST-F009-05 | カート（variant 68 × 2）を作り、DB で `variants.stock`（id 68）を 28 → 0 に UPDATE → web 3020 `/cart` を再表示。続けて stock=1（数量 2 に対し不足）でも再表示。終了後 28 に戻す | 該当明細に警告が出て「レジへ進む」が無効 | stock 0: 明細に `role=alert`「⚠ 在庫切れのため購入できません」、金額欄に「⚠ 在庫切れ・在庫不足の商品があるためレジへ進めません」、「レジへ進む」`disabled=true aria-disabled=true`。stock 1: 「⚠ 在庫が不足しています」＋同じく無効。追加確認: ボタン無効を無視して `POST /api/checkout/prepare` を直叩き → `409 {"code":"out_of_stock","items":[68]}`（画面側だけの防御ではない） | 合格 | スクリーンショット・DOM・curl。復元: stock 68 = 28 |
| ST-F013-02 | web `/checkout` で (a) 全項目空で「確認画面へ」 (b) 氏名・電話・住所は正しく、郵便番号 `100000`（6 桁）・メール `not-an-email` で「確認画面へ」。fetch をフックし prepare 呼び出し回数を数える。API 側は `POST /api/orders` に `ship_name:""`・`ship_postal_code:"100000"`・`guest_email:"not-an-email"` | 400 `validation_error` の項目が画面で赤字表示され、確認画面へ進めない | (a) 7 項目に赤字（`color rgb(196,35,43)`＝`--color-danger`）「入力してください」／「選択してください」、`aria-invalid=true`、フォーカスは先頭の氏名、URL は `/checkout` のまま。(b) 郵便番号「郵便番号は 7 桁の数字で入力してください」・メール「メールアドレスの形式が正しくありません」の 2 項目のみ赤字、prepare 呼び出し 0 回、`/checkout` のまま。API: `400 {"code":"validation_error","fields":[{"name":"ship_name","reason":"out_of_range"},{"name":"ship_postal_code","reason":"format"},{"name":"guest_email","reason":"format"}]}` | 合格（注記: 氏名空の `reason` が `out_of_range`。4.5 の固定語なら `required` が自然。利用者にはクライアント検査が先に効くので影響なし → 6.3 #3） | スクリーンショット・DOM・curl |
| ST-F014-02 | web 3020: カート（68×2・**158**×1＝V-STOCK1）で確認画面を表示（prepare: 小計 6,470／送料 0／合計 6,470、158 は `stock_status ok`）→ 別 Cookie（curl・jarC）で 158 を 1 点購入 → `201` **GU-260924-UDX4Q6MQ**、stock 158: 1 → 0 → 元の画面で「注文を確定する」→「確定する」 | 注文は成立せずカート画面に戻り、該当明細に在庫切れ表示。在庫は減らない | `POST /api/orders` → `409 {"code":"out_of_stock","items":[158]}` → `/cart?oos=158` に遷移、トースト「在庫切れの商品があります」、158 の明細が強調（枠・「⚠ 在庫切れのため購入できません」）、「レジへ進む」無効、`sessionStorage.guapp.checkout` 削除。DB: cart 23 の注文は増えていない（orders 7 件のまま）、cart 23 `active`、stock 68 = 28（不変）・158 = 0（先の注文の 1 のみ） | 合格 | スクリーンショット・DOM・SELECT。**復元: stock 158 を 1 に UPDATE（5 章）** |
| ST-F014-03 | web 3000: 確認画面表示（prepare 小計 1,990／送料 550／合計 2,540）→ DB `UPDATE products SET price_incl_tax=1991 WHERE id=12` → 「注文を確定する」→「確定する」→ 戻された SCR-005 で「確認画面へ」 | 409 で注文手続きに戻り、金額が再表示される。注文は作られない | `409 {"code":"price_changed","amounts":{"subtotal":1991,"shipping_fee":550,"total":2541}}` → `/checkout` に遷移、トースト「金額が変わりました。内容をご確認のうえ、もう一度お進みください」、`guapp.checkout.prepare` が `null`（旧キー破棄）。「確認画面へ」で新キー（`LHPMpYSC…`）の prepare が走り、確認画面に「単価 ¥1,991 × 1／小計 ¥1,991／送料 ¥550／合計 ¥2,541／うち消費税 ¥231」。DB: orders 5 件のまま、cart 23 `active`、stock 68 不変 | 合格 | スクリーンショット・fetch フック・SELECT。復元: price 1990 |
| ST-F014-04 | web 3020（API 8020 `PAYMENT_STUB_RESULT=ng`）: カート 68×2 → 注文手続き → 確認画面（合計 4,530）→ 確定 | 注文手続きの支払い方法へ戻る。DB: orders 決済失敗、payments に ng、在庫は元に戻り、カートは active に戻る | `409 {"code":"payment_failed","order_number":"GU-260924-2YS3MV7G"}` → `/checkout` に遷移、トースト「決済に失敗しました。支払い方法をご確認ください」、フォーカスが `section[aria-labelledby=payment-heading]`（支払い方法）に移動、`prepare` は `null`。DB: orders id 10 `payment_failed` total 4530 cart 23、payments `stub/ng/4530`、order_items 0 行（補足どおり）、audit_logs `order.payment_failed`、stock 68 = 28（元どおり）、carts 23 `active`。8020 ログ「決済スタブ authorize … result=ng」 | 合格 | スクリーンショット・fetch フック・SELECT・uvicorn ログ |
| ST-F014-06 | — | 注文成立＋監査ログ `mail.failed` | — | 未実施（メールスタブを失敗させる注入点が無く、IT-014-09 で自動テスト済み） | — |
| ST-F025-02 | FastAPI・BFF（CSRF 付き）とも `POST /orders/GU-260918-GX7EB5VV/lookup {"guest_email":"other@example.com"}`。対照で正しいメール、存在しない番号 | 404（存在自体を隠す） | 不一致メール → `404 {"code":"not_found"}`（FastAPI・BFF 同じ）。正しいメール → 200。存在しない番号 `GU-260918-ZZZZZZZZ` → 同じ `404 {"code":"not_found"}`（番号不存在とメール不一致を区別しない） | 合格 | curl |
| ST-F025-03 | FastAPI 8000 に `X-Forwarded-For: 203.0.113.9` を付けて lookup（不一致メール）を 101 回連続 | 100 回目は応答、101 回目は 429 | 1〜100 回目: すべて 404、**101 回目: `429 {"code":"rate_limited"}`・`retry-after: 3589`**。直後に `203.0.113.10` → 404（別 IP は影響なし）、XFF 無し（接続元 127.0.0.1）で正しいメール → 200（影響なし） | 合格（注記: 制限はプロセス内メモリ。8000 の 203.0.113.9 は 1 時間後に自然解除。他 IP への影響なしを確認済み） | `rl.txt`（101 行のステータス）・ヘッダ |
| ST-F032-01 | 確認画面（合計 2,540・うち消費税 ¥230）表示後、DB `UPDATE system_settings SET value='"0.08"' WHERE key='tax_rate'` → 「戻る」→「確認画面へ」で再表示 | 「うち消費税」が新税率で再計算される。商品価格は変わらない | `GET /api/v1/settings/public` → `tax_rate "0.08"`（再起動なし）。確認画面「小計 ¥1,990／送料 ¥550／合計 ¥2,540（税込）／**うち消費税 ¥188**」（2540×8÷108=188.1→188）、prepare の `tax_rate "0.08"`、単価 ¥1,990・`products.price_incl_tax` 1990 は不変 | 合格 | スクリーンショット・sessionStorage。復元: `"0.10"` |
| ST-F032-02 | 同じ手順で (a) `shipping_fee=800`・`free_shipping_threshold=100000` (b) `free_shipping_threshold=1000`（小計 1,990 が閾値以上になる側） | 変更後の値で送料が計算される。再デプロイ不要 | (a) 「送料（100,000 円以上で無料） ¥800／合計 ¥2,790／うち消費税 ¥253」 (b) 「送料（1,000 円以上で無料） 無料／合計 ¥1,990／うち消費税 ¥180」。いずれもプロセス再起動なし（settings/public も即反映） | 合格 | スクリーンショット・sessionStorage。復元: 550／4990 |

## 2. システムテスト 3.2 セキュリティ

| ID | 手順 | 期待結果 | 観測結果 | 判定 | 証拠 |
| --- | --- | --- | --- | --- | --- |
| ST-SEC-02 | 8021 を `APP_ENV=production` で起動し `GET /docs`・`/redoc`・`/openapi.json`。対照 8000（development） | すべて 404 | 8021: 3 つとも **404**（本文 `{"detail":"Not Found"}`）。8000: 3 つとも 200 | 合格（注記: 未定義ルートの 404 本文が FastAPI 既定形で、4.5 の `{"code":"not_found"}` と揃っていない → 6.3 #2） | curl |
| ST-SEC-03 | 8000 に `OPTIONS /api/v1/orders` を `Origin: https://evil.example.com`＋`Access-Control-Request-Method: POST` で送る。対照 `Origin: http://localhost:3000`。通常 GET に evil Origin | 許可オリジン以外は拒否。`Access-Control-Allow-Origin: *` が出ない | evil の preflight → `400 Bad Request` 本文「Disallowed CORS origin」、**`access-control-allow-origin` ヘッダ無し**、`*` 無し。許可オリジン → 200・`access-control-allow-origin: http://localhost:3000`。evil の通常 GET → `access-control-allow-origin` 無し（`access-control-allow-credentials: true` だけは付くが、ACAO 無しではブラウザは応答を渡さない＝Starlette の既定挙動） | 合格 | curl ヘッダ |
| ST-SEC-04 | BFF: `GET /api/cart` → 68 を追加 → `POST /api/checkout/prepare`（合計 2,540）→ `POST /api/orders`（CSRF 付き）で `display.total` を 2,539 に。続けて `display.subtotal` だけ -1 | 409（金額変更）。注文は作られない | 2 回とも `409 {"code":"price_changed","amounts":{"subtotal":1990,"shipping_fee":550,"total":2540}}`。DB: orders 5 件のまま、stock 68 = 28 不変、カート `active` | 合格 | curl・SELECT |
| ST-SEC-05 | web 3020 `/checkout` の氏名に **`' OR 1=1 --<script>alert(1)</script>`**（両方を 1 本の 36 文字で）→ 確認画面 → 確定 → 完了画面。`window.alert` をフックし呼び出しを記録。`sessionStorage.guapp.lastOrder` を消して照会フォーム（注文番号＋メール）からも再表示。メール欄には API 直叩きで `' OR 1=1 --` と `<script>alert(1)</script>@example.com` | 文字列として保存・表示され、SQL エラーやスクリプト実行が起きない | 確認・完了・照会の 3 画面とも「' OR 1=1 --<script>alert(1)</script> 様」と**テキストで表示**、`main` 内 `<script>` 要素 0、`alert` 呼び出し 0 回。注文 **GU-260924-DX56JE6Z** `accepted`。DB `orders.ship_name` に同じ文字列がそのまま保存、orders 全 8 行残存（`OR 1=1` が効いていない）、8020 ログに Traceback／OperationalError 0 件。メールスタブ出力にも同文字列がテキストで出る。メール欄は 2 通りとも `400 {"code":"validation_error","fields":[{"name":"guest_email","reason":"format"}]}` で保存に至らない | 合格 | スクリーンショット・DOM・SELECT・`.mail-outbox/GU-260924-DX56JE6Z.txt` |
| ST-SEC-06 | BFF に Cookie 付き・`X-CSRF-Token` 無しで `POST /api/orders`。不一致トークン `bogus` でも | 403 | 2 回とも `403 {"code":"forbidden"}`。FastAPI 到達の有無: 8000 のアクセスログは共用で読めないため、代替として 8020 側で同じ手順を実施 → `uvicorn8020b.log` に `POST /api/v1/orders` の行が増えない（BFF で止まっている） | 合格 | curl・uvicorn ログ |
| ST-SEC-08 | ペックルの注文 `GU-260918-GX7EB5VV` を `other@example.com` で照会（FastAPI・BFF） | メール不一致なら 404 | `404 {"code":"not_found"}`（ST-F025-02 と同じ観測。正しいメールでは 200 なので番号は有効） | 合格 | curl |
| ST-SEC-10 | 8000 `GET /api/v1/products` をヘッダ無し／`X-Internal-Token: wrong-token`／正しい値 | 401 | 無し → `401 {"code":"unauthorized"}`、不正値 → `401 {"code":"unauthorized"}`、正しい値 → 200 | 合格 | curl |
| ST-SEC-11 | 8021 を `APP_ENV=production`・`DATABASE_URL=mysql+asyncmy://qa_dummy:qa_dummy@127.0.0.1:3307/nonexistent_db`（未使用ポート）で起動 → `GET /api/v1/products`・`POST /orders/…/lookup`・`GET /cart` | 本文は固定文言。スタックトレース・SQL・接続文字列が出ない | 3 つとも `500 {"code":"internal_error","message":"処理中にエラーが発生しました"}`（content-length 80）。本文に traceback／select／mysql／asyncmy／qa_dummy／3307／`File "` の出現 0。`/api/v1/health` は `503 {"code":"db_unavailable"}`（仕様どおり）。サーバーログ側は `ERROR app.errors: 未捕捉例外 GET /api/v1/products: OperationalError` ＋ Traceback（詳細はログのみ）。ログ中にダミーパスワード `qa_dummy` の平文 0 件 | 合格 | curl・`uvicorn8021b.log` | <!-- pragma: allowlist secret（qa_dummy はダミー。到達不能 DB の検証用） -->

## 3. 悲観視点の追加攻撃（設計書のケース外。判定は参考）

| # | 攻撃 | 観測 | 評価 |
| --- | --- | --- | --- |
| A | 「レジへ進む」無効を無視して prepare を直叩き（在庫 0 明細あり） | `409 out_of_stock {items:[68]}` | 画面だけの防御ではない。良い |
| B | **BFF にクライアントが `X-Forwarded-For` を付けて lookup** | `X-Forwarded-For: 203.0.113.9`（FastAPI 側で 429 中の IP）を BFF `POST /api/orders/…/lookup` に付けると **429 が返る**（＝BFF がクライアントのヘッダをそのまま FastAPI へ転送している）。`203.0.113.77` に変えると 404（＝別 IP として数えられる）。`apps/web/lib/server/order-proxy.ts` `clientIp()` は受信リクエストの `x-forwarded-for` 先頭を採用 | **🟡** 6.3 #1（レート制限のバイパス、および任意 IP を名指しで 429 にする嫌がらせが可能） |
| C | メール欄に SQLi／XSS 文字列 | 形式検査で 400 | 保存に至らない。良い |
| D | 数量上限の 3 経路（新規追加・加算・PATCH） | 3 経路とも 422 `limit_exceeded` | 抜け道なし。良い |

## 4. 総括

### 4.1 件数

| 判定 | 件数 | ID |
| --- | --- | --- |
| 合格 | 21 | ST-F001-02, F007-01, F009-03, F009-04, F009-05, F013-02, F014-02, F014-03, F014-04, F025-02, F025-03, F032-01, F032-02, SEC-02, SEC-03, SEC-04, SEC-05, SEC-06, SEC-08, SEC-10, SEC-11 |
| 不合格 | 0 | — |
| 未実施 | 2 | ST-F001-03（重複・省略）, ST-F014-06（注入点なし。IT-014-09 で自動テスト済み） |

合計 23 件（3.1 異常・境界 13＋委譲 2、3.2 セキュリティ 8）。設計書 4.5 の `code`・HTTP ステータスは全件で期待どおり（400 validation_error／401 unauthorized／403 forbidden／404 not_found／409 out_of_stock・price_changed・payment_failed／422 limit_exceeded／429 rate_limited／500 internal_error）。

### 4.2 不合格の一覧

なし。成果物（アプリ）の不合格は 0 件。環境事故（0 章・3000 の 500）は成果物のバグではなくオレさまの操作ミス。

### 4.3 設計書に無いが危ない点（3 件まで）

| # | 重大度 | 内容 | 再現手順 | 該当箇所・対策案 |
| --- | --- | --- | --- | --- |
| 1 | 🟡 要修正 | **BFF がクライアント送信の `X-Forwarded-For` を信用してレート制限の IP に使う**。攻撃者はヘッダを毎回変えるだけで 100 回/時の総当たり制限を無効化でき、逆に被害者の IP を書けばその IP を 429 にできる。本番の Azure App Service（ARR）は既存の XFF に**追記**するため、先頭＝クライアント値が採用されるこの実装では本番でも成立する | 1. `curl -c jar http://localhost:3000/api/cart` で Cookie 取得 2. 同じ lookup を `-H "X-Forwarded-For: 203.0.113.N"` の N を変えながら 101 回以上送る → 429 にならない 3. FastAPI 側で 429 中の IP（例 203.0.113.9）を XFF に書くと即 429（転送の証明。本記録 3 章 B） | `apps/web/lib/server/order-proxy.ts` `clientIp()`。対策案: (a) BFF はクライアントの XFF を**無視**し、信頼できる前段が付ける値だけ使う（App Service なら `X-Forwarded-For` の**末尾**（直前ホップ）か `X-Client-IP`／`X-Azure-ClientIP`、ローカルは接続元） (b) 設計書 7.5 に「IP の決め方（信頼境界）」を 1 行追記。P2 の Azure 前に直す |
| 2 | 🟢 提案 | 未定義ルート（`/docs` 等を含む）の 404 本文が FastAPI 既定 `{"detail":"Not Found"}` で、4.5 の `{"code":"not_found"}` と揃っていない。フレームワークの指紋にもなる | `curl http://127.0.0.1:8021/docs`（production）→ `{"detail":"Not Found"}` | `app/core/errors.py` に `StarletteHTTPException` のハンドラを足し `{code:"not_found"}` に統一 |
| 3 | 🟢 提案 | `ship_name:""`（空文字）の 400 `reason` が `out_of_range`（`string_too_short` の対応付け）。4.5 の固定語の意味なら `required` が自然。UI はクライアント検査が先に効くため利用者影響なし | `POST /api/v1/orders` に `ship_name:""` → `fields[0].reason == "out_of_range"` | `app/core/errors.py` `map_reason()` で `string_too_short`＋`min_length==1` を `required` へ、または 4.5 に「空文字は out_of_range」と明記 |

補足（バグではない観測）: 409／400 で ROLLBACK した `INSERT orders` が AUTO_INCREMENT を消費し、orders.id に欠番（7・8・9・12）が出る。内部 ID は応答に出さない設計なので影響なし。

### 4.4 良かった点（悲観視点でも認める）

- 戻し先が設計（PR #10・`lib/order-errors.ts`）どおりに 4 系統すべて切り替わる: out_of_stock → `/cart?oos=`（明細強調）、price_changed → SCR-005（prepare 破棄・新キー）、payment_failed → SCR-005 支払い方法にフォーカス、validation → 赤字。
- 金額改ざん・在庫 0 明細・数量上限は、画面を飛ばして API を直叩きしても同じコードで弾かれる。
- 攻撃文字列は 3 画面＋メールでテキストとして出て、ORM のバインドで SQL に混ざらない。
- 500 の本文は 80 バイトの固定文言で、ログにも接続文字列の平文が残らない。
- system_settings の 3 キーは再起動なしで確認画面に反映される（税率・送料・閾値の 3 通りで確認）。

## 5. 復元確認（終了時 SELECT・11:18）

| 対象 | 変更前 | 変更内容 | 終了時の値 | 確認 |
| --- | --- | --- | --- | --- |
| `system_settings.tax_rate` | `"0.10"` | `"0.08"`（ST-F032-01） | `"0.10"` | 復元済み |
| `system_settings.shipping_fee` | 550 | 800（ST-F032-02） | 550 | 復元済み |
| `system_settings.free_shipping_threshold` | 4990 | 100000 → 1000（ST-F032-02） | 4990 | 復元済み |
| `products.price_incl_tax`（id 12） | 1990 | 1991（ST-F014-03） | 1990 | 復元済み |
| `variants.stock`（id 158・`GU-027-NV-M`・V-STOCK1） | 1 | 注文 GU-260924-UDX4Q6MQ で 1 → 0（ST-F014-02） | **1**（UPDATE で復元） | 復元済み |
| `variants.stock`（id 68・`GU-012-NV-M`） | 28 | 0 → 1 → 28（ST-F009-05） | 26 | 復元済み（0／1 は 28 に戻した。26 は ST-SEC-05 の注文 GU-260924-DX56JE6Z が正規に 2 点消費した結果。ペックルの注文と同じ扱い） |
| `variants.stock`（id 170・V-STOCK0） | 0 | 変更なし | 0 | 不変 |
| `guapp_test` | — | 触っていない | — | — |

DB に残る本作業の痕跡（意図した正規の注文・失敗記録）: orders id 10（payment_failed）・11・13（accepted）、carts 23・24（ordered）、audit_logs 3 行、`.mail-outbox` 2 ファイル。

自前インスタンスの停止: `taskkill /T /F` でプロセスツリーごと停止 → `netstat` で 8020・8021・3020 の LISTENING なし、curl も接続不可（000）を確認。共用 8000 は 200。共用 3000 は `/api/health` 200・ページ 500（0 章）。

## 6. 未実施の理由

| ID | 理由 |
| --- | --- |
| ST-F001-03 | ペックルが全件 29 件で 24 件区切りを確認済み（重複・省略） |
| ST-F014-06 | メールスタブを失敗させる注入点が P1 の実行環境に無い（`.mail-outbox/` への書き込みを人為的に失敗させる手段が無い）。IT-014-09 で例外注入による自動テスト済み |

代替した項目: ST-F009-05・F014-02・F014-04・SEC-05 は共用 3000 が 500 のため自前 3020（同一ソースの複製・同一 DB）で実施。ST-SEC-06 の「FastAPI に到達しない」は 8000 のログが読めないため 8020 のログで代替。

## 7. 環境の後片付け確認

- `apps/web` 配下でオレさまが変えたのは `node_modules/` の中だけ（0 章。ジャンクション 18 本の向き先・`.modules.yaml`・`.pnpm/lock.yaml`）。`package.json`・`pnpm-lock.yaml`・`next.config.ts`・`app/globals.css`・`.next` は触っていない。
- 11:04:43 に `app/layout.tsx`・`components/AllMenu.tsx`・`Header.tsx`・`HeaderWithCart.tsx`・`tests/at-07.all-menu.test.tsx`・`public/products/031/1.jpg` が同時刻で更新されている（`.git/index` も同時刻、`.git/logs/HEAD` 末尾に `merge origin/main`）。これはオレさまの操作ではなく、コーディネーター側の `origin/main` 取り込み（AT-07 のオールメニュー修正）と見られる。本記録のテストは 11:04 以前のソース（3000）と、その時点の複製（3020。10:52 時点の `app/`・`components/`・`lib/` を複製）で実施しており、オールメニュー修正は対象外。
- scratchpad の複製（`web3020/`）は 0 章の修復が終わるまで残す。作業ファイル（`qa/`）はセッション用一時領域。リポジトリへの書き込みは本ファイルのみ。git 操作なし。
