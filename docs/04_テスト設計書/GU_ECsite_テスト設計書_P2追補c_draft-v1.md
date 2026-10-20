# GU EC サイト テスト設計書（P2 追補c）

| 項目 | 内容 |
| --- | --- |
| 文書番号 | GUEC-TD-01-P2c |
| 版 | draft-v1 |
| 作成者 | Claude |
| 作成日 | 2026-10-20 |
| 入力 | 本編 `GU_ECsite_テスト設計書_P1_draft-v2.md`（2026-10-19 追補まで）、P2 追補a・追補b（`GU_ECsite_テスト設計書_P2追補a_draft-v1.md`・`GU_ECsite_テスト設計書_P2追補b_draft-v1.md`）、設計仕様書追補 `GU_ECsite_設計仕様書_P2追補c_draft-v1.md`、要求仕様書 with_ai v2.4、要件定義書 with_ai v1.3、`セキュリティ点検記録_20261019.md` |
| 対象 | P2-c：F-035 管理認証と分離、F-031 管理：商品・在庫（再入荷通知の送信側を含む）、F-033 管理：注文、F-032 管理：設定、管理操作の監査ログ |

## 改訂履歴

| 版 | 日付 | 内容 | 作成 | 承認 |
| --- | --- | --- | --- | --- |
| draft-v1 | 2026-10-20 | 初稿。設計仕様書 P2 追補c の設計 ID に対応する AT／ST／IT／UT を新設した。件数は 10 章の冒頭に示す。実施結果と関数名の対応は、実装の検収後に 10・11 章へ転記する | Claude | — |
| draft-v1.1 | 2026-10-20 | 実装と手元の検収で見つかった食い違いを修正。ST-F031-01・IT-051-01 の seed の商品数を 30 から 31 にした（1 ページ目 20 件＋2 ページ目 11 件）。ST-F033-03・IT-053-07 の期間は「両端を含む暦日数で 366 日まで、367 日以上は 422」と明記した | Claude | — |

## 0. 本書の位置づけ

本書は本編・P2 追補a・P2 追補b の追補であり、**P2-c で追加・変更した設計 ID に対応するテストだけ**を新設する。ID 体系（`AT-nn`／`ST-F<機能番号>-nn`／`ST-SEC-nn`／`IT-<DS 番号>-nn`／`UT-<略称>-nn`）、正常・異常・境界の 3 区分、4 レベルの対応は本編 0 章のとおり。既存の ID は番号を変えない。

並行して進む F-029（AI アシスタント）の追補と ID が重ならないよう、AT・ST-SEC・IT-SCHEMA・UT-WEB・ST-NFR は、P2-b の最大値から間を空けた番号から振る。F-029 の追補が使う範囲を確認できていないため、空けた範囲を後から詰めない。

| 種別 | 既存の最大 | 本書で振る範囲 |
| --- | --- | --- |
| AT | AT-21（P2-b） | AT-30〜AT-37 |
| ST-F | ST-F036（本編）まで機能別の連番 | 新規の機能：ST-F035・ST-F031・ST-F033・ST-F032（各 01 から。F-031・F-033 は本編・追補に ID が無いため新規の連番） |
| ST-NFR | ST-NFR-04（P2-b） | ST-NFR-10・11 |
| ST-SEC | ST-SEC-59（P2-b） | ST-SEC-80〜95 |
| IT | 機能別 | IT-050・050a・050b、IT-051・051a・051b・051c、IT-052・052a、IT-053・053a・053b、IT-ADM-01〜（管理 API の共通）、IT-SCHEMA-20〜、IT-BFF-050〜 |
| UT | 機能別 | UT-ADM-01〜、UT-SEED-20〜、UT-WEB-40〜 |

## 1. テスト方針（差分）

本編 1 章の方針をそのまま使う。差分は次のとおり。

| # | 差分 | 内容 |
| --- | --- | --- |
| 1 | 管理 API の結合テストは MySQL 必須 | `FOR UPDATE` による直列化、READ COMMITTED、UNIQUE、CHECK 制約の挙動に依存するため、SQLite では確かめられない（本編 1.4 #3 と同じ理由）。`DATABASE_URL_TEST` が無いと全件 skip になる既存の仕組みをそのまま使う |
| 2 | 同時実行テストの条件 | IT-050-10（同じ管理者の同時ログイン）、IT-051b-09（同じ商品の同時更新）、IT-051c-07（同じバリエーションの同時更新）、IT-051c-08（在庫の更新と注文確定の並行）、IT-052a-06（同じ設定の同時更新）、IT-053b-07（同じ注文の同時更新）は、本編 1.4 の条件（#1 プール 20 以上、#2 同時処理中カウンタの最大値が 2 以上、#3 MySQL、#4 `alembic upgrade head`、#5 失敗側の `code` まで assert）を満たさない実行は合格と見なさない。反復回数は 10 回（有効試行）とする |
| 3 | 管理者の資格情報の作り方 | 結合テストは、テスト内で `staff` の行を作り（`tests/integration/admin_helpers.py` の `create_staff`）、`/auth/login` を呼ぶか `sessions` の行を直接作ってトークンを得る。seed の管理者（`demo-staff`）を使うのは seed の確認（IT-050-01・UT-SEED）と AT・ST だけ。パスワードはテストコード内の固定のダミー値で、本書には値を書かない |
| 4 | メールの取り出しと後処理 | 再入荷通知は `BackgroundTasks` で動く。結合テストは `httpx` の ASGI 経由で呼ぶため、応答が返る前に後処理が終わる。メールは `get_mail_adapter` を `dependency_overrides` で**記録用アダプタ**に差し替えて読む。後処理の完了前の状態を作る IT-051c-06 は、`notify_restock` を保留するフィクスチャを使う |
| 5 | 時刻の操作 | 期間（ロック 15 分、セッション 8 時間、注文日時の JST 境界）のテストは、待たずに DB の時刻列（`login_attempts.at`・`sessions.expires_at`・`orders.created_at`）を直接更新して境界の前後を作る。UT は時計を引数で渡せる関数に対して行う |
| 6 | 注文の状態の用意 | 状態遷移のテストで、`pending_payment`・`cancelled`・`payment_failed`・`pickup_expired` などの注文は、DB の `orders.status` を直接更新して作る（これらの状態へ進める管理操作は P2 に無い） |
| 7 | BFF の IT | 追補b と同じく、FastAPI を `fetch` のモックに置き換えて Route Handler を呼ぶ。管理用の Cookie（`asid`）は `Cookie` ヘッダに載せて渡す |
| 8 | ブラウザの実機確認 | `SameSite=Strict`・`Path=/admin` の Cookie がどのリクエストに付くかは、ユニットテストでは確かめきれない。AT-30 と ST-SEC-83 で DevTools の Request Headers を見る |
| 9 | 実施環境 | AT・ST の手動確認はローカル（`pnpm dev` と `uvicorn`）。公開環境が要るもの（`Secure` 属性）は、公開環境への能動テストを避ける方針（点検記録 1 章）に従い、コードの条件とユニットテストで代える |
| 10 | ダミーデータ | 氏名・メールは `example.com` などのダミーに限る。実在の電話番号・住所を使わない |

## 2. 受け入れテスト（AT）追加分

要件定義書 7 章のユーザーストーリー US-05（運用担当者として、税率やクーポンを管理画面から変えたい）に AT-35 が対応する。

| ID | 対象 | 区分 | 手順 | 期待結果 |
| --- | --- | --- | --- | --- |
| AT-30 | F-035／REQ-FR-1105 | 正常 | 未ログインで `/admin/products` を開く。seed の管理者でログインする。画面上部の表示を見る。ログアウトし、ブラウザの「戻る」で `/admin/products` を開く。公開サイトのトップ・商品一覧・マイページのリンクを見る | 未ログインは `/admin/login` に移る。ログイン後は `/admin/products` が開き、右上に login_id とログアウトが出る（顧客向けのヘッダー・フッター・カートは出ない）。ログアウト後に `/admin/products` を開くと `/admin/login` に移る。DB の `sessions` に `subject_type=staff` の行が 1 → 0 行、`audit_logs` に `admin.login`・`admin.logout`。公開サイトのどのページにも管理画面へのリンクがない |
| AT-31 | F-031／REQ-FR-1101・205 | 正常 | 公開サイトで、商品 29（V-STOCK0。在庫 0）の色ブラック・サイズ M の再入荷のお知らせにダミーのメールで 2 件申し込む。管理画面で商品 29 を開き、該当 SKU の在庫を 5 にして保存する。同じ値のまま、もう一度保存する。公開サイトの商品 29 を開く | トーストに「在庫を 0 から 5 に更新しました。再入荷通知の対象は 2 件です」。`.mail-outbox/` に再入荷メール（商品名・色・サイズ・商品ページのリンク）が 2 通。`restock_notifications.notified_at` が 2 行とも入る。2 回目の保存は変更なしで、メールは増えない。公開サイトでは当該色・サイズをカートに入れられる。`audit_logs` に `admin.stock.set`（before 0・after 5）と `restock.notified`（件数 2） |
| AT-32 | F-031／REQ-FR-1101 | 正常 | 管理画面で商品 1 を「非公開にする」（確認ダイアログで OK）。公開サイトで `/products/1`・商品一覧・検索を見る。管理画面で「公開する」に戻す。価格を 1,990 円から 2,490 円に保存し、公開サイトの商品詳細とカートを見る。価格を元に戻す | 非公開の間、公開サイトの `/products/1` は 404 で、一覧・検索に出ない（管理画面の一覧には出る）。公開に戻すと表示される。価格の変更は公開サイトの商品詳細・カートに反映される。変更のたびに `audit_logs` に `admin.product.update` |
| AT-33 | F-033／REQ-FR-1103・602 | 正常 | 公開サイトで配送の注文を 1 件作る（状態は受付済）。管理画面で注文番号を検索し、詳細を開いて「出荷準備中にする」→「出荷済にする」（追跡番号を入力）→「配達完了にする」の順に操作する。各段階で、顧客としてマイページの注文詳細を開く | 管理画面の「次の操作」は各段階で 1 つだけ出て、配達完了のあとは「画面で更新できる操作はありません」。顧客の注文詳細の状態は「出荷準備中」→「出荷済（配送中）」→「配達完了」と変わり、追跡番号は「出荷済」以降に表示される |
| AT-34 | F-033／REQ-FR-508・1103 | 正常 | 公開サイトで店舗受け取りの注文を 1 件作る。管理画面で「店舗へ準備中」にし、「受け取り可能にする」、「受け渡し済にする」の順に操作する。各段階で、顧客として注文詳細を開く。管理画面の注文詳細を見る | 顧客の状態名は「店舗へ準備中」→「店舗に到着（受け取り可能）」→「受け渡し済」。受け取りコードは顧客側で「店舗に到着」まで表示される。管理画面の注文詳細には、受け取りコードも追跡番号の欄も出ない |
| AT-35 | F-032／REQ-FR-1102・US-05 | 正常・異常 | 管理画面の設定で、送料を 550 円から 660 円、送料無料の下限を 4,990 円から 5,990 円に保存する。公開サイトで小計 4,990 円のカートの金額を見る。設定の税率に 0.35 を入れて保存する。設定を元に戻す | 保存したあと、公開サイトのカート・確認画面は次のアクセスから送料 660 円・下限 5,990 円で計算される（小計 4,990 円は送料 660 円）。税率 0.35 は「0.00 以上 0.30 以下で入力してください」と出て、保存されない（DB の値は 0.10 のまま）。`audit_logs` に `admin.settings.update`（前後の値） |
| AT-36 | REQ-NFR-04 | 正常 | AT-30〜35 の操作のあとに、DB の `audit_logs` を `actor_type='staff'` で時刻順に見る | 操作ごとに 1 行（誰が：`actor_id`、いつ：`at`、何を：`action`・`target_type`・`target_id`、前後の値：`detail`）が残る。値が変わらなかった保存の行はない。`detail` にメールアドレス・氏名・電話・住所・受け取りコードが無い |
| AT-37 | REQ-NFR-09 | 正常 | AT-30〜35 を画面幅 1280px・768px・375px で行う | 1280px・768px：すべての操作が完了でき、レイアウトが崩れない。375px：ページ全体の横スクロールが出ず、表は枠の中だけ横にスクロールし、ボタンと入力欄に触れて操作が完了できる（PC 向けの画面のため、375px で見た目の最適化は求めない） |

## 3. システムテスト（ST）追加分

### 3.1 機能要件

#### F-035 管理認証と分離

| ID | 対象 F／DS | 区分 | 観点・手順 | 期待結果 |
| --- | --- | --- | --- | --- |
| ST-F035-01 | F-035／DS-API-050 | 正常 | seed の管理者でログインする | 200。`asid` Cookie が付く（属性は ST-SEC-83）。ブラウザへの本文に `session_token` が無い。`sessions` に 1 行（`subject_type=staff`、`token_hash` は 64 桁の 16 進で Cookie 値そのものではない、`expires_at` は約 8 時間後）。`audit_logs` に `admin.login`（`detail` は丸めた IP だけ）。右上に login_id が出る |
| ST-F035-02 | F-035／DS-API-050 | 異常 | 誤ったパスワード、登録していない ID でログインする | どちらも 401 `invalid_credentials` で本文が同一。`Set-Cookie` に `asid` は無い。`login_attempts` に `subject_type=staff` の失敗が 1 行ずつ増える。画面の文言も同一 |
| ST-F035-03 | F-035／DS-DEC-110 | 境界 | 同じ ID で誤パスワードを 4 回、5 回送り、6 回目に正しいパスワードを送る。登録していない ID でも同じ手順をする。ロック中の `login_attempts.at` を 14 分 59 秒前、15 分 1 秒前に書き換えて正しいパスワードで試す | 5 回目まで 401。6 回目は正しいパスワードでも 403 `account_locked`。未登録の ID でも 6 回目から 403。14 分 59 秒前はロックのまま、15 分 1 秒前は成功する。成功で失敗行が消える |
| ST-F035-04 | F-035／DS-DEC-110 | 境界 | 同じ IP から、10 個の異なる ID に誤パスワードを 1 回ずつ送る。続けて 11 個目と、正しい管理者の正しいパスワードを送る。別の IP から正しい管理者でログインする | 10 回目まで 401、11 回目以降は 429 `rate_limited`（`Retry-After: 900`）。IP が制限に達している間は正しい管理者でも 429。別の IP からは成功する |
| ST-F035-05 | F-035／DS-API-050a | 正常 | ログイン中にログアウトする。直後に旧 `asid` の値で `/admin/products` を開く。ログアウトをもう一度呼ぶ | 204。`sessions` の当該行が消える。`asid` は削除される。旧 `asid` で `/admin/products` を開くと `/admin/login` に移る。2 回目のログアウトも 204 |
| ST-F035-06 | F-035／REQ-FR-1105 | 異常 | 未ログインで `/admin`・`/admin/products`・`/admin/products/1`・`/admin/orders`・`/admin/orders/<注文番号>`・`/admin/settings` を開く。`asid` なしで、変更系の BFF（商品・在庫・設定・注文状態の 4 本）を CSRF つきで呼ぶ | ページはすべて `/admin/login` に移る（内容を一切表示しない）。BFF は 401 `unauthorized` で、FastAPI に届かない |
| ST-F035-07 | F-035／DS-DEC-108 | 境界 | `sessions.expires_at` を 1 秒後、1 秒前に書き換えて `/admin/products` と管理 API を呼ぶ。作成直後の `expires_at` を確認する | 1 秒後は有効。1 秒前は無効で、ページは `/admin/login` に、API は 401。作成直後の `expires_at` は作成から 8 時間（±5 秒）で、アクセスしても延長されない |
| ST-F035-08 | F-035／DS-DEC-108 | 境界 | 同じ管理者で、旧トークンを渡さずに 3 回、4 回ログインする | 3 回目までは 3 つとも有効。4 回目で最も古いセッションが消え、有効なセッションは 3 件。最古の `asid` では 401 |
| ST-F035-09 | F-035／DS-DEC-121 | 正常 | ログイン済みで `/admin/login` を開く。ログイン前後の `csrf_token` Cookie の値を比べる | `/admin/products` に移る。`csrf_token` はログインの成功時に発行し直され、値が変わる |
| ST-F035-10 | F-035／DS-DEC-108 | 正常 | 同じブラウザで、会員（`sid`）と管理者（`asid`）の両方でログインする。会員をログアウトし、管理者の操作を続ける。管理者をログアウトし、会員の操作を続ける | 互いに独立している。会員をログアウトしても `/admin/products` は開ける。管理者をログアウトしても `/mypage` は開ける。DevTools で、`/mypage` などのリクエストに `asid` が付かない |

#### F-031 管理：商品・在庫

| ID | 対象 F／DS | 区分 | 観点・手順 | 期待結果 |
| --- | --- | --- | --- | --- |
| ST-F031-01 | F-031／DS-API-051 | 正常 | `/admin/products` を開く。2 ページ目を開く | seed の商品 31 点（非公開の商品 30 を含む）のうち 1 ページ目に 20 件、「全 31 件」、2 ページ目に 11 件。各行に商品 ID・商品名・価格（`¥`）・公開状態・在庫合計・在庫 0 の SKU 数。商品 ID の昇順 |
| ST-F031-02 | F-031／DS-PRC-051 | 境界 | キーワードに、商品名の一部、SKU の前方一致（小文字で `gu-029`）、`%`、`_`、`\`、50 文字、51 文字を入れて検索する | 商品名の部分一致、SKU の前方一致で該当する商品が出る（小文字の SKU も一致）。`%`・`_`・`\` はそのままの文字として扱われ、全件にならない（0 件）。50 文字は検索でき、51 文字は 400 |
| ST-F031-03 | F-031／DS-API-051 | 正常 | 商品 1 を非公開にしたうえで、公開状態「公開」「非公開」と、在庫「在庫 0 あり」で絞り込む | 「公開」に商品 1 は出ず、「非公開」には商品 1 だけが出る。「在庫 0 あり」には在庫 0 の SKU がある商品（商品 29 など）が出る。条件の組み合わせは AND |
| ST-F031-04 | F-031／DS-API-051a | 正常 | 商品 29 の編集画面を開く | バリエーションごとに SKU・色・サイズ・在庫・再入荷待ちの件数が出る。待ちの人のメールアドレスは画面にも応答にも出ない |
| ST-F031-05 | F-031／DS-API-051c | 正常 | 在庫 0 の V-STOCK0 に 2 件の再入荷申込がある状態で、在庫を 5 にして保存する | 200。`changed:true`、`previous_stock:0`、`restock_waiting:2`。`variants.stock` が 5。`audit_logs` に `admin.stock.set`。応答のあとの後処理でメールが 2 通できて `notified_at` が入り、`restock.notified`（件数 2）が残る |
| ST-F031-06 | F-031／DS-DEC-114 | 境界 | 在庫に -1、0、9999、10000、5.5、"5"（文字列）、true、null、2147483648 を送る（API を直接呼ぶ。画面は入力欄で止まる） | -1 は 422 `unsupported_value`。0 と 9999 は成功。10000 は 422 `limit_exceeded`（`limit: 9999`）。5.5・"5"・true・null・2147483648 は 400。失敗したときは DB が変わらない |
| ST-F031-07 | F-031／DS-DEC-113 | 異常 | 同じ商品の編集画面を 2 つ開く（A・B）。A で在庫を 5 から 7 に保存したあと、B（表示は 5）で 9 に保存する。別に、画面を開いたあとで顧客が 1 個購入して在庫が減った場合に保存する | B の保存は 409 `stale_data`（`current: 7`）。画面は 7 に更新され、案内が出る。DB は 7 のまま。購入のあとの保存も 409（`current` は減ったあとの値）で、購入による減少を上書きしない |
| ST-F031-08 | F-031／DS-DEC-115 | 正常 | 在庫を 5→0、3→8、0→0 と変える | 5→0 と 3→8 は `changed:true` で監査ログに残るが、再入荷通知は送られない。0→0 は `changed:false`（更新・監査・通知なし） |
| ST-F031-09 | F-031／DS-API-051b | 正常 | 商品 1 を非公開にし、公開サイトの `/products/1`・商品一覧・検索・カテゴリを見る。管理画面の一覧と編集画面を見る。公開に戻す | 非公開の間、公開サイトで商品 1 は 404 または一覧に出ない。管理画面では一覧にも編集画面にも出る。公開に戻すと公開サイトに出る。変更ごとに `admin.product.update` |
| ST-F031-10 | F-031／DS-DEC-116 | 境界 | 価格に 0、1、1000000、1000001、1990.5、"1990"（文字列）、-1 を送る。成功した価格の商品を、公開サイトで買い、価格をもう一度変える | 0 と -1 は 422 `unsupported_value`。1 と 1000000 は成功。1000001 は 422 `limit_exceeded`（`limit: 1000000`）。1990.5 と "1990" は 400。変更は公開サイトの商品詳細・カートに反映される。すでに確定した注文の単価（`order_items.unit_price_at_order`）は変わらない（REQ-FR-505） |
| ST-F031-11 | F-031／DS-API-051a・051c | 異常 | 存在しない product_id・variant_id で詳細・更新を呼ぶ。product_id に 0、-1、`abc`、9223372036854775808 を使う | 存在しない ID は 404 `not_found`。0・-1・`abc`・桁あふれの ID は 400 `validation_error` |

#### F-033 管理：注文

| ID | 対象 F／DS | 区分 | 観点・手順 | 期待結果 |
| --- | --- | --- | --- | --- |
| ST-F033-01 | F-033／DS-API-053 | 正常 | 配送・店舗受け取り・会員・ゲストの注文がある状態で `/admin/orders` を開く | 新しい順。各行に注文番号・注文日時（JST）・状態名・受け取り方法・合計（`¥`）・点数・連絡先（`t***@example.com` の形）。氏名・電話・住所は出ない |
| ST-F033-02 | F-033／DS-DEC-125 | 境界 | 状態、受け取り方法、注文番号（小文字で入力）、メール（大文字・全角で入力）で絞る。注文日時が 2026-10-27 23:59:59（JST）と 2026-10-28 00:00:00（JST）の 2 件で、期間を 10/27 だけ、10/28 だけにする。注文番号・メールを部分的な文字列にする | 状態・受け取り方法で絞れる。期間は JST の暦日：23:59:59 は 10/27 に、00:00:00 は 10/28 に入る。注文番号は大文字化して完全一致。メールは正規化して完全一致。部分的な文字列は 0 件 |
| ST-F033-03 | F-033／DS-DEC-124 | 異常・境界 | 期間の開始が終了より後。期間が 366 日、367 日（両端を含む暦日数。例：2025-10-01〜2026-09-30 が 365 日、2025-10-01〜2026-10-01 が 366 日、2025-10-01〜2026-10-02 が 367 日）。日付に `2026-13-01`・`2026/10/01`。注文番号に `GU-1`・I や O を含む番号 | 開始が後は 422 `unsupported_value`。366 日は成功、367 日は 422 `limit_exceeded`（`limit: 366`）。日付と注文番号の形の違いは 400 |
| ST-F033-04 | F-033／DS-DEC-118 | 正常 | 配送の注文の詳細を開く。同じ詳細を 2 回開く | 明細（商品名・色・サイズ・単価 × 数量）、小計・送料・値引き・合計・うち消費税、状態、次の操作が出る。氏名・郵便番号・住所は全文、電話は末尾 4 桁だけ（他は `*`）、メールはマスク。受け取りコードの欄はない。開くたびに `audit_logs` に `admin.order.view` が 1 行ずつ増える |
| ST-F033-05 | F-033／DS-DEC-118 | 正常 | 店舗受け取りの注文の詳細を開く | 受け取り店舗（店名・都道府県・住所）が出る。お届け先（郵便番号・住所）の欄はない。受け取りコードが画面にも応答にも無い。追跡番号の欄はない |
| ST-F033-06 | F-033／DS-API-053b | 正常 | 配送の注文を、受付済から「出荷準備中」→「出荷済」（追跡番号を入力）→「配達完了」へ進める | 各段階で 200。状態名は「出荷準備中」→「出荷済（配送中）」→「配達完了」。追跡番号が保存される。`audit_logs` に `admin.order.status` が 3 行（from・to）。次の操作は各段階で 1 つ、最後はなし |
| ST-F033-07 | F-033／DS-DEC-117 | 正常 | 店舗受け取りの注文を同様に進める | 状態名は「店舗へ準備中」→「店舗に到着（受け取り可能）」→「受け渡し済」。ボタンの名前も同じ言葉になる。追跡番号の欄は出ない |
| ST-F033-08 | F-033／DS-API-053b | 異常 | 遷移表に無い更新を送る：受付済→出荷済、受付済→配達完了、出荷準備中→配達完了、出荷済→出荷準備中、配達完了→出荷済、キャンセル済→出荷準備中、決済待ち→出荷準備中、決済失敗→出荷済、受取期限切れ→配達完了（状態は DB で用意する） | すべて 409 `invalid_transition`（`from`・`to`）。状態と追跡番号は変わらず、`audit_logs` に残らない |
| ST-F033-09 | F-033／DS-DEC-117 | 異常 | 更新先に `cancelled`・`pickup_expired`・`payment_failed`・`accepted`・`pending_payment` を送る。更新先に `foo`、空文字、`SHIPPED` を送る | 前者は 422 `unsupported_value`（`field: "status"`）。後者は 400 `validation_error`。どちらも DB は変わらない |
| ST-F033-10 | F-033／DS-API-053b | 境界 | 配送の出荷（`shipped`）の更新で、追跡番号を 50 文字、51 文字、全角、空白入り、ハイフン入りにする。店舗の注文、出荷準備中への更新に追跡番号を付ける。追跡番号なしで出荷にする | 50 文字・ハイフン入りは成功。51 文字・全角・空白入りは 400。店舗の注文や出荷以外への更新に付けると 422 `unsupported_value`（`field: "tracking_number"`）。追跡番号なしの出荷は成功（顧客側では追跡番号が出ない） |
| ST-F033-11 | F-033／REQ-FR-602 | 正常 | 管理画面で状態を進めるたびに、顧客として `/mypage/orders/<注文番号>` と注文照会を見る | 状態名は追補b の DS-PRC-024a の表どおり。店舗受け取りは「受け取り可能」まで受け取りコードが出て、受け渡し済で出なくなる。配送の追跡番号は出荷済・配達完了で出る |
| ST-F033-12 | F-033／DS-DEC-113 | 異常 | 同じ注文の詳細を 2 つのタブで開き、両方で「出荷準備中にする」を押す | 一方が 200、他方は 409 `invalid_transition`。画面は「この注文の状態はすでに変わっています」と出して更新される。`audit_logs` の `admin.order.status` は 1 行 |
| ST-F033-13 | F-033／DS-API-053a・053b | 異常 | 存在しない注文番号、形が不正な番号（`GU-1`、小文字、`../`）で詳細の取得と状態の更新を呼ぶ | どちらも 404 `not_found` で本文が同一。`audit_logs` に `admin.order.view` は残らない |

#### F-032 管理：設定

| ID | 対象 F／DS | 区分 | 観点・手順 | 期待結果 |
| --- | --- | --- | --- | --- |
| ST-F032-01 | F-032／DS-API-052 | 正常 | `/admin/settings` を開く | 消費税率 0.10、送料 550、送料無料の下限 4990、決済待ちの期限 30（変更できません）が出る。各項目に範囲の説明 |
| ST-F032-02 | F-032／DS-API-052a | 正常 | 送料を 660、下限を 5990、税率を 0.08 にして保存する。公開サイトのカート・確認画面の金額を見る | 200。公開サイトの金額が新しい送料・下限で計算され、内税の額は税率 0.08 で求まる。`audit_logs` に `admin.settings.update`（変更したキーの前後の値） |
| ST-F032-03 | F-032／DS-DEC-119 | 境界 | 税率に `0.00`・`0.30`・`0.31`・`1.00`・`0.1`・`10%`・`abc`・数値の 0.1、送料に 0・5000・5001・-1・"550"・5.5、下限に 0・100000・100001・-1 を送る | 税率：`0.00`・`0.30` は成功。`0.31`・`1.00` は 422 `limit_exceeded`（`limit: "0.30"`）。`0.1`・`10%`・`abc`・数値の 0.1 は 400。送料：0・5000 は成功。5001 は 422 `limit_exceeded`、-1 は 422 `unsupported_value`、"550"・5.5 は 400。下限：0・100000 は成功。100001 は 422 `limit_exceeded`、-1 は 422 `unsupported_value`。失敗したときは DB が変わらない |
| ST-F032-04 | F-032／DS-DEC-113 | 異常 | 設定画面を 2 つ開く（A・B）。A で送料を 660 に保存したあと、B（表示は 550）で 770 に保存する | B の保存は 409 `stale_data`（`field: "shipping_fee"`、`current: 660`）。DB は 660 のまま。画面は 660 に更新される |
| ST-F032-05 | F-032／DS-DEC-119 | 異常 | 要求の本文に `payment_timeout_minutes` と `foo` を付けて、送料を更新する | 送料だけが更新される。`payment_timeout_minutes` は 30 のまま。`system_settings` に新しいキーが増えない |
| ST-F032-06 | F-032／本編 DS-PRC-014-1 | 正常 | 注文手続きの確認画面を開いたまま、管理画面で送料を変更し、元の画面で注文を確定する。確認画面からやり直す | 確定は 409 `price_changed`（既存の挙動）。やり直すと新しい金額で成立する |

### 3.2 非機能・セキュリティ

#### 非機能

| ID | 対象 | 区分 | 観点・手順 | 期待結果 |
| --- | --- | --- | --- | --- |
| ST-NFR-10 | REQ-NFR-09 | 正常 | `/admin/login`・`/admin/products`・`/admin/products/<id>`・`/admin/orders`・`/admin/orders/<注文番号>`・`/admin/settings` を画面幅 1280px・768px・375px で表示する | 1280px・768px：レイアウトの崩れなし。375px：ページ全体の横スクロールなし、表は枠の中だけ横にスクロールし、入力欄とボタンに触れる |
| ST-NFR-11 | 6 章・DS-PRC-051・053 | 境界 | 商品 30 点の一覧と、注文 200 件の一覧を表示し、実行された SQL の数を数える。注文を 50 件、200 件にして比べる | 商品一覧は本体 1 回と件数 1 回。注文一覧は本体 1 回・件数 1 回・点数の集計 1 回の合計 3 回（管理セッションの検証を除く）。件数を増やしても SQL の数が増えない（N+1 なし）。開発機で 200 件の一覧が 1 秒以内（目安。意見） |

#### セキュリティ（ST-SEC-80〜95）

設計仕様書 P2 追補c の 7 章の対策に対応する。区分と手順は本編 3.3 の前提（CSRF トークンを付ける、回数制限は窓を空けて始める）に従う。ログイン系は IP 単位の制限（15 分に 10 回失敗）に当たらないよう、ID を替えながら 9 回以内にとどめるか、`login_attempts` を削除して始める。

| ID | 対象 | 区分 | 観点・手順 | 期待結果 |
| --- | --- | --- | --- | --- |
| ST-SEC-80 | A-02・DS-DEC-109 | 異常 | ①会員 `demo-member1` でログインし、DevTools で Cookie `asid`（Path=`/admin`）を作って値に会員の `sid` の値を入れる。②`/admin/products`・`/admin/orders` を開く。③`PATCH /admin/api/variants/<id>/stock` を CSRF つきで呼ぶ。④内部トークンつきで FastAPI の `GET /api/v1/admin/me` を、`X-Admin-Session-Token` に会員のトークンを付けて呼ぶ。⑤同じ呼び出しを `X-Session-Token` だけで行う | ②は `/admin/login` に移る。③と④は 403 `forbidden` で、在庫は変わらない。アプリのログに拒否が 1 行（path・status・code・丸めた IP。トークンと会員の情報は無い）。⑤は 401 `unauthorized` |
| ST-SEC-81 | A-02・A-04・DS-DEC-109 | 異常 | アプリに登録された `/api/v1/admin` 配下の全ルート（ログイン以外）を列挙し、内部トークンだけ（管理用セッションなし）で呼ぶ。管理用ルーターにテスト用のルートを、認証の依存関数を書かずに 1 つ足して同じように呼ぶ | すべて 401 `unauthorized`。依存関数を書かずに足したルートも 401（ルーター単位で既定拒否になっている）。管理用セッションなしで通るのはログイン（本文の検証は別）だけ |
| ST-SEC-82 | C-03・DS-DEC-121 | 異常 | 変更系の BFF 6 本（ログイン・ログアウト・商品・在庫・設定・注文状態）を、CSRF トークンなし、不一致、`Origin: https://evil.example`、`Sec-Fetch-Site: cross-site` で送る | すべて 403 `forbidden` で、FastAPI に届かない。DB・セッションは変わらない |
| ST-SEC-83 | B-01・DS-DEC-108 | 正常 | ログイン応答の `Set-Cookie`、ブラウザの `document.cookie`、応答本文を確認する。DevTools で、`/`・`/mypage`・`/api/cart` と `/admin/products` のリクエストの `Cookie` を比べる | `asid` は `HttpOnly`・`SameSite=Strict`・`Path=/admin`・`Max-Age=28800`（`APP_ENV=production` の起動では `Secure` も付く。ユニットテストで確認）。`document.cookie` に `asid` が出ない。応答本文に `session_token` が無い。`/`・`/mypage`・`/api/cart` のリクエストに `asid` は付かず、`/admin/*` には付く |
| ST-SEC-84 | B-06・DS-DEC-108 | 異常 | ログイン前に `asid` Cookie へ攻撃者が選んだ値（43 文字の任意文字列）を入れてログインする。古い `asid` が残ったままもう一度ログインする | ログイン後の `asid` は新しい値で、攻撃者の値は採用されない。攻撃者の値で `/admin/products` を開くと `/admin/login` に移る。再ログインで古い `sessions` の行が消える |
| ST-SEC-85 | B-03・DS-DEC-110 | 境界 | 登録済みの ID（誤パスワード）と未登録の ID でログインし、ステータス・本文・ヘッダー・応答時間（各 10 回の中央値）を比べる | どちらも 401 `{"code":"invalid_credentials"}` で本文が一字一句同じ。ヘッダーにも差がない。中央値の差が 25 ms 以内（登録済みの誤パスワードも未登録も argon2id の検証 1 回分をかけるため） |
| ST-SEC-86 | B-04・DS-DEC-110 | 境界 | ①同じ ID に誤パスワード 5 回→6 回目に正しい値 ②同じ IP から異なる 10 個の ID に失敗→11 個目 ③同じ IP から会員のログイン失敗を 20 回行ってから、管理者でログイン ④管理者のログイン失敗を 9 回行ってから、会員でログイン | ① 6 回目は 403 `account_locked`。② 11 回目は 429（`Retry-After: 900`）。③と④は成功する（会員と管理者の失敗は、互いの IP 単位・ID 単位の集計に入らない） |
| ST-SEC-87 | C-01・C-02・DS-DEC-118 | 異常 | 氏名・住所に `<script>alert(1)</script>`、`"><img src=x onerror=alert(1)>`、`' OR 1=1 --` を入れた注文（DB に直接入れてよい）を管理画面の一覧・詳細で見る。商品検索のキーワードと注文のメール検索に同じ文字列を入れる | 詳細に文字列としてそのまま表示される（ページのソースで `<script>` が未エスケープで出ない。スクリプトは動かない）。キーワード・メールに入れても SQL エラーや 500 は出ず、0 件になる |
| ST-SEC-88 | A-07・REQ-NFR-07・DS-DEC-118 | 正常 | 管理 API の全応答（商品の一覧・詳細、在庫、設定、注文の一覧・詳細・状態更新、`/me`）の全キーを調べる | 内部 ID（`id`・`member_id`・`order_id`・`store_id`・`staff_id`）、`password_hash`、`token_hash`、`pickup_code`、完全な電話番号・メールアドレスが無い。例外は `product_id`・`variant_id`。一覧に氏名・電話・住所が無い。詳細の電話は末尾 4 桁以外が `*` |
| ST-SEC-89 | F-05・REQ-NFR-04・DS-DEC-120 | 正常 | AT-30〜35 の操作のあとに `audit_logs` を確認する。アプリのソースで `audit_logs` に対する UPDATE・DELETE を検索する | 操作ごとに 1 行（`actor_type=staff`、`actor_id`、`action`、`target_type`・`target_id`、前後の値）。`detail` にメール・氏名・電話・住所・受け取りコード・トークンが無い。値が変わらなかった更新は行が増えない。UPDATE・DELETE を書いたコードが無い（UT-ADM-18 と同じ検査） |
| ST-SEC-90 | A-03・C-01・DS-DEC-124 | 異常 | 商品の更新に `name`・`id`・`description`・`role` を付ける。在庫の更新に `sku`・`variant_id` を付ける。設定に `payment_timeout_minutes`・`foo` を付ける。注文状態に `receive_method`・`total`・`member_id` を付ける。整数に 9007199254740993・`1e3`・`"1_0"` を使う。本文が配列、文字列、JSON でない値 | 余計な項目は無視され、反映されない。桁あふれ・型違い・JSON でない本文は 400。500 は出ない |
| ST-SEC-91 | D-01〜D-03・REQ-FR-1105・DS-DEC-122 | 正常 | `/admin/login`・`/admin/products`・`/admin/api/csrf` の応答ヘッダーを確認する。公開サイトの主要ページ（ホーム・商品一覧・商品詳細・カート・マイページ・フッターのリンク先）の HTML の `href`・`action` を調べる | `Cache-Control: no-store`、`X-Robots-Tag: noindex, nofollow`、ST-SEC-30 のセキュリティヘッダー（`X-Frame-Options: DENY`・CSP・HSTS・`nosniff` など）が付く。公開サイトの HTML に `/admin` へのリンクが 0 件 |
| ST-SEC-92 | B-07・DS-DEC-112 | 異常 | `APP_ENV=production` で seed の管理者を、①`SEED_STAFF_PASSWORD` なし ②11 文字 ③12 文字で実行する。③のあとで、開発用の既定パスワードでログインを試す | ①②は管理者が 0 件で、標準エラーに理由が出て、他の seed は続く。③は 1 件投入され、ハッシュは argon2id。既定のダミーパスワードではログインできない。平文のパスワードがログ・DB に無い |
| ST-SEC-93 | A-02・DS-DEC-109 | 異常 | 管理者でログインし、Cookie `sid` に `asid` の値を入れて `/mypage` を開く。内部トークンつきで `GET /api/v1/me` と `POST /api/v1/orders` を、`X-Session-Token` に管理者のトークンを付けて呼ぶ | `/mypage` は `/login` に移る。`/me` は 401。注文はゲスト扱いで成立し、`member_id` は NULL（追補b の ST-SEC-59 と同じ） |
| ST-SEC-94 | G-07・DS-DEC-107 | 異常 | 内部トークンなしで FastAPI の `/api/v1/admin/*`（ログインを含む）を直接呼ぶ。内部トークンだけで、管理用セッションなしの管理操作を試す | すべて 401 `unauthorized`。内部トークンが漏れても、管理用セッション（別の秘密）がなければ管理操作はできない（設計仕様書 7.4 #9 の残余リスクは、セッションまで漏れた場合） |
| ST-SEC-95 | G-01・DS-DEC-126 | 境界 | 同じ IP から `GET /admin/api/csrf` を 120 回、121 回送る | 120 回目まで 204、121 回目は 429 `rate_limited`（`Retry-After` つき）。`/admin/api/*` が `/api/*` と同じ「API」の枠で数えられる |

## 4. 結合テスト（IT）追加分

FastAPI と MySQL を実際に起動し、pytest から HTTP で呼ぶ（本編 4 章と同じ）。ID は `IT-<DS-API または DS-PRC の番号>-<連番>`。内部トークンを付けて FastAPI を直接呼ぶものは「FastAPI」、BFF（Next.js の Route Handler）を通すものは IT-BFF とする。管理者のトークンは `admin_helpers.py`（1 章 #3）で用意し、メールは記録用アダプタで読む（1 章 #4）。

### 4.1 管理認証（IT-050・050a・050b・ADM）

| ID | 対象 DS | 区分 | 前提・入力 | 期待結果 |
| --- | --- | --- | --- | --- |
| IT-050-01 | DS-API-050 | 正常 | seed の管理者で正しくログイン | 200。`session_token`（43 文字）と `staff: {login_id, role: "staff"}`。`sessions` に 1 行で `token_hash` は SHA-256（16 進 64 桁）、`subject_type=staff`、`subject_id` は管理者の ID、`expires_at` は約 8 時間後（±5 秒）。`audit_logs` に `admin.login`（`detail` は丸めた IP だけ） |
| IT-050-02 | DS-API-050・DS-DEC-110 | 異常 | 登録済みの管理者に誤パスワード、未登録の ID で、それぞれログイン | どちらも 401 `invalid_credentials` で本文が同一。`login_attempts` に `subject_type=staff` の失敗が 1 行ずつ。`identifier` は SHA-256 の 16 進で、平文の login_id が DB に無い。`sessions` は増えない |
| IT-050-03 | DS-API-050・DS-DEC-110 | 境界 | 誤パスワード 4 回のあとに正しい値。別の管理者で誤パスワード 5 回のあとに 6 回目。未登録の ID で 5 回のあとに 6 回目 | 4 回のあとの成功は 200。5 回目までは 401、6 回目は 403 `account_locked`。未登録の ID でも 6 回目は 403。ロック通知のメールは送られない（記録用アダプタに 0 通） |
| IT-050-04 | DS-API-050 | 境界 | ロックされた管理者の `login_attempts.at` を 14 分 59 秒前、15 分 1 秒前に書き換えて、正しいパスワードで試す | 14 分 59 秒前は 403、15 分 1 秒前は 200 |
| IT-050-05 | DS-API-050・DS-DEC-110 | 境界 | 同じ `X-Forwarded-For` の IP から、10 個の異なる ID に失敗を記録し、11 個目と、正しい管理者の正しいパスワードを送る。別の IP から送る。同じ IP の会員の失敗行（29 件）がある状態でも送る | 10 回目までは 401、11 回目以降は 429 `rate_limited`（`Retry-After: 900`）。正しい管理者の正しいパスワードも 429。別の IP からは通る。会員の失敗行は数えない |
| IT-050-06 | DS-API-050・DS-DEC-108 | 正常 | ログインして得た旧トークンを `X-Admin-Session-Token` に付けて、もう一度ログインする | 旧トークンの `sessions` 行が消え、新しい行ができる（トークンもハッシュも別）。旧トークンで `GET /me` は 401 |
| IT-050-07 | DS-API-050・DS-DEC-108 | 境界 | 同じ管理者で 2 回、3 回、4 回ログインする（旧トークンは渡さない） | 有効なセッションは 2 件、3 件、3 件。4 回目では最も古い行だけが消える |
| IT-050-08 | DS-API-050 | 異常 | login_id が 2 文字・51 文字・空・記号入り（`a b`）。password が欠落・空・129 文字。全角・大文字の login_id（正規化で正しい ID になるもの） | 形式不正・欠落・長さ違反は 400 `validation_error`（`fields` に項目名と reason）。`login_attempts` に記録しない。全角・大文字は正規化されて成功する |
| IT-050-09 | DS-API-050・DS-DEC-68 | 正常 | time_cost=1 など現行と違うパラメータの argon2id ハッシュで保存された管理者でログインする | 200。`password_hash` が現行のパラメータ（`m=19456,t=2,p=1`）のハッシュに更新される。同じパスワードでもう一度ログインできる |
| IT-050-10 | DS-API-050・5.6 | 異常 | **同じ管理者で 10 並列**に正しいパスワードでログインし、同時に誤パスワードを 3 本送る（1 章 #2） | 500・タイムアウトなし。正しい 10 本はすべて 200、誤パスワードは 401。有効な `sessions` は 3 件以内。デッドロック（1213）が起きた場合は再試行で成功する（再試行の回数をログから数えて記録する） |
| IT-050-11 | DS-API-050・DS-DEC-110 | 正常 | 管理者に誤パスワードを 5 回送って ID をロックし、同じ IP の会員が正しくログインする。会員を 5 回失敗でロックし、同じ IP の管理者が正しくログインする | どちらも成功する（会員と管理者のロック・IP 制限は互いに影響しない） |
| IT-050-12 | DS-API-050・DS-PRC-050 手順 8 | 正常 | 24 時間より古い `login_attempts` の行を 1001 件作ってから、ログインに成功する | 古い行が最大 1000 件削除される（1 件残る）。24 時間以内の行は削除されない |
| IT-050a-01 | DS-API-050a | 正常 | ログインして得たトークンで `POST /auth/logout` | 204。`sessions` の当該行が消える。`audit_logs` に `admin.logout`。続けて `GET /me` は 401 |
| IT-050a-02 | DS-API-050a | 異常 | `X-Admin-Session-Token` なし、不明な値、形が違う値、会員の有効なトークンでログアウトする | すべて 204（冪等）。他の管理者のセッションは消えない。会員のセッションの行も消えない（`subject_type=staff` の行だけを削除する）。`audit_logs` は増えない |
| IT-050a-03 | DS-API-050a | 境界 | 同じ管理者の有効なセッションが 2 つある状態で、片方をログアウトする | もう一方は有効のまま（`GET /me` が 200） |
| IT-050b-01 | DS-API-050b | 正常 | ログインで得たトークンで `GET /me` | 200 `{"login_id", "role"}` のみ（`id`・`password_hash` が無い） |
| IT-050b-02 | DS-API-050b・DS-PRC-050b | 異常 | ヘッダーなし、形が違う値、不明な値、`expires_at` が過去のセッション | すべて 401 `unauthorized` |
| IT-050b-03 | DS-API-050b・DS-DEC-109 | 異常 | 会員の有効なセッションのトークンを `X-Admin-Session-Token` に付ける。会員のトークンを `X-Session-Token` だけに付ける | 前者は 403 `forbidden`（拒否ログが 1 行）。後者は 401 `unauthorized` |
| IT-050b-04 | DS-PRC-050b | 異常 | 有効な管理者のセッションがあるまま、`staff` の行を削除する | 401 `unauthorized`（管理者の行が無い） |
| IT-ADM-01 | DS-DEC-109・4.0 | 異常 | アプリに登録された `/api/v1/admin` 配下の全ルート（ログイン以外）を `app.routes` から列挙し、内部トークンだけで呼ぶ | すべて 401。ルートを足したときも自動で対象になる（列挙は実行時に行う） |
| IT-ADM-02 | DS-DEC-109 | 異常 | 上のすべてのルートを、会員の有効なトークンを `X-Admin-Session-Token` に付けて呼ぶ | すべて 403 `forbidden`。DB は変わらない |
| IT-ADM-03 | 4.0・DS-DEC-107 | 異常 | 内部トークンなし、不一致で、すべての管理ルート（ログインを含む）を呼ぶ。管理用セッションが有効な場合も試す | すべて 401 `unauthorized` |
| IT-ADM-04 | 4.0・本編 7.7 S5 | 正常 | 管理 API の 200・401・403・404・409・422 の応答ヘッダーを見る | すべてに `Cache-Control: no-store`、`X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY` が付く |
| IT-ADM-05 | 本編 7.7 S9 | 正常 | 管理 API で 401・403 を起こしたときのアプリのログを読む | `request_rejected` の 1 行（path・method・status・code・丸めた IP）。トークン・login_id・会員の情報・個人情報が無い |

### 4.2 商品・在庫（IT-051・051a・051b・051c）

| ID | 対象 DS | 区分 | 前提・入力 | 期待結果 |
| --- | --- | --- | --- | --- |
| IT-051-01 | DS-API-051 | 正常 | seed の 31 商品で `GET /products` | 200。`total` 31、`items` は `per_page` 20 件、`product_id` の昇順。各項目に `product_id`・`name`・`price_incl_tax`・`published`・`variant_count`・`total_stock`・`out_of_stock_variants`。`has_more` が真 |
| IT-051-02 | DS-API-051 | 正常 | `q` に商品名の一部、SKU の前方一致（小文字）、一致しない文字列、空文字 | 商品名の部分一致と SKU の前方一致で該当する。小文字の SKU も一致。一致しないときは空。空文字は条件なし（全件） |
| IT-051-03 | DS-PRC-051 | 異常 | 商品名に `%`・`_` を含む商品を追加し、`q` に `%`、`_`、`\`、`%%`、`a%b` を送る | ワイルドカードとして働かず、追加した商品（文字として含むもの）だけが一致するか 0 件。SQL エラーなし |
| IT-051-04 | DS-API-051 | 正常 | `visibility=public／private／all`、`stock=out／all`、組み合わせ。`visibility=foo` | 絞り込みが正しい（組み合わせは AND）。列挙外は 400 |
| IT-051-05 | DS-API-051 | 境界 | `per_page` を 1、100、101、`page` を 0、最終ページの次 | 1・100 は 200。101 と `page=0` は 400。最終ページの次は 200 で `items` が空、`total` は保たれる |
| IT-051-06 | DS-PRC-051・ST-NFR-11 | 境界 | 商品を 30 点、300 点にして一覧を呼び、SQL の数を数える | 管理セッションの検証を除き 2 回（本体と件数）。商品数に比例しない |
| IT-051-07 | DS-API-051 | 境界 | 一致する商品がない条件 | 200。`items` は空、`total` 0、`has_more` 偽 |
| IT-051a-01 | DS-API-051a | 正常 | 再入荷の申込が未通知 2 件・通知済み 1 件ある商品の詳細 | 200。`variants` は `variant_id` の昇順。`restock_waiting` は未通知の件数（2）だけで、通知済みは数えない。応答にメールアドレスのキーが無い |
| IT-051a-02 | DS-API-051a | 正常・異常 | 存在しない `product_id`。非公開の商品 | 存在しないものは 404 `not_found`。非公開の商品は 200（管理者には見える） |
| IT-051a-03 | DS-API-051a | 異常 | `product_id` に 0、-1、`abc`、9223372036854775808 | すべて 400 `validation_error` |
| IT-051b-01 | DS-API-051b | 正常 | 公開の商品の `published` を偽にする（`expected_published` は真） | 200 `changed:true`。DB が更新される。`audit_logs` に `admin.product.update`（`published` の before 真・after 偽）。公開側の `GET /products/{id}` が 404 になる。真に戻すと 200 |
| IT-051b-02 | DS-API-051b | 正常 | 価格を 1990 から 2490 にする | 200。公開側の商品詳細の価格が 2490。`audit_logs` に前後の値。すでにある注文の `unit_price_at_order` は変わらない |
| IT-051b-03 | DS-PRC-055 | 異常 | `expected_published`・`expected_price_incl_tax` を現在の値と違う値にする。両方を送り、片方だけ違う | 409 `stale_data`（`field`・`current`）。DB は変わらず、`audit_logs` に残らない。片方だけ違うときも、もう一方を更新しない |
| IT-051b-04 | DS-API-051b | 異常 | `expected_*` の欠落、変更する項目なし（`{}`）、`published` が文字列 "true"、価格が文字列 "1990"・小数 1990.5、価格 2147483648 | すべて 400 `validation_error`（`required`・`format`・`out_of_range`） |
| IT-051b-05 | DS-DEC-116 | 境界 | 価格を 0、1、1000000、1000001 にする | 0 は 422 `unsupported_value`（`field: "price_incl_tax"`）。1 と 1000000 は 200。1000001 は 422 `limit_exceeded`（`limit: 1000000`） |
| IT-051b-06 | DS-PRC-051b | 境界 | 現在と同じ値で、`expected_*` も一致させて送る | 200 `changed:false`。`audit_logs` は増えず、`updated_at` は変わらない |
| IT-051b-07 | DS-API-051b・A-03 | 異常 | 本文に `name`・`id`・`description`・`role` を足して送る | 無視され、商品の名前・説明などは変わらない |
| IT-051b-08 | DS-API-051b | 異常 | 存在しない `product_id`。`product_id` が 0 | 存在しないものは 404、0 は 400 |
| IT-051b-09 | DS-API-051b・5.6 | 異常 | **同じ商品の `published` を真から偽へ、10 並列**で更新する（`expected_published` は真。1 章 #2） | 1 本が 200、9 本が 409 `stale_data`。`audit_logs` は 1 行。500 なし |
| IT-051b-10 | 4.7・本編 4.5 | 異常 | 存在しない商品に価格 0 を送る。管理用セッションなしで不正な本文を送る | 前者は 404（存在確認が業務の範囲の検査より先）。後者は 401（認証が最初） |
| IT-051c-01 | DS-API-051c | 正常 | 申込のないバリエーションで 0→5 | 200 `changed:true`、`previous_stock:0`、`restock_waiting:0`。DB の在庫が 5。`audit_logs` に `admin.stock.set`（`sku`・`before:0`・`after:5`・`restock_waiting:0`）。通知は 0 通 |
| IT-051c-02 | DS-PRC-051c・DS-DEC-115 | 正常 | V-STOCK0 に 3 件申し込んである状態で 0→5 | 200 `restock_waiting:3`。記録用アダプタに 3 通（宛先ごと。リンクは `PUBLIC_WEB_BASE_URL` 起点）。3 行とも `notified_at` が入る。`audit_logs` に `restock.notified`（件数 3） |
| IT-051c-03 | DS-DEC-115 | 境界 | 在庫 5→0、3→8、0→0、8→8（申込を用意しておく） | 通知は 0 通。0→0 と 8→8 は `changed:false`（`audit_logs` に増えない）。5→0 と 3→8 は `changed:true` |
| IT-051c-04 | DS-PRC-055 | 異常 | `expected_stock` を現在の在庫と違う値にする | 409 `stale_data`（`field: "stock"`、`current`）。DB は変わらず、通知もしない |
| IT-051c-05 | DS-DEC-114・124 | 境界 | `stock` に -1、0、9999、10000、5.5、"5"、true、null、2147483648。`expected_stock` の欠落、-1 | -1 は 422 `unsupported_value`。0 と 9999 は 200。10000 は 422 `limit_exceeded`（`limit: 9999`）。型違い・桁あふれ・`expected_stock` の欠落や -1 は 400 |
| IT-051c-06 | DS-PRC-051c 手順 11 | 境界 | 0→5 の更新で、後処理が動く前に在庫を 0 へ戻し（後処理を保留するフィクスチャを使う）、後処理を動かす。そのあと 0→3 にする | 1 回目の後処理は何も送らず、申込の `notified_at` は NULL のまま。0→3 の更新のあとの後処理で、申込者に送信される |
| IT-051c-07 | DS-API-051c・5.6 | 異常 | 申込が 3 件ある同じバリエーションに、`expected_stock: 0`・`stock: 5` を **10 並列**で送る（1 章 #2） | 1 本が 200（`changed:true`）、9 本が 409 `stale_data`。`audit_logs` の `admin.stock.set` は 1 行。メールは 3 通だけ（二重送信なし）。500・タイムアウトなし |
| IT-051c-08 | DS-DEC-113・5.6 | 異常 | 在庫 3 のバリエーションに、注文確定（数量 1）と、管理者の更新（`expected_stock: 3`・`stock: 10`）を同時に送る。これを 10 回繰り返す（1 章 #2） | 500 なし。結果は「注文が先：管理者は 409、在庫 2」または「管理者が先：在庫 10 から注文で 9」のどちらか。注文が成立したのに在庫が 10 のまま（更新の消失）となる回が 0 |
| IT-051c-09 | DS-PRC-051c 手順 10 | 異常 | 記録用アダプタが 1 件目の宛先で例外を出す | 在庫の更新は 200 のまま。残りの宛先には送信される。`audit_logs` に `restock.mail_failed`（宛先は含まない）。例外は応答に出ない |
| IT-051c-10 | DS-API-051c | 異常 | 存在しない `variant_id`。`variant_id` が 0・-1・`abc`・9223372036854775808。管理用セッションなしで存在しない `variant_id` | 存在しないものは 404、不正な ID は 400、管理用セッションなしは 401 |
| IT-051c-11 | DS-API-051c・A-03 | 異常 | 本文に `sku`・`variant_id`・`product_id` を足して送る | 無視され、SKU・商品との対応は変わらない |

### 4.3 設定（IT-052・052a）

| ID | 対象 DS | 区分 | 前提・入力 | 期待結果 |
| --- | --- | --- | --- | --- |
| IT-052-01 | DS-API-052 | 正常 | `GET /settings` | 200。`items` は 4 件で、順序は `tax_rate`・`shipping_fee`・`free_shipping_threshold`・`payment_timeout_minutes`。`tax_rate` は文字列、他は整数。`payment_timeout_minutes` だけ `editable:false`。`min`・`max` が付く |
| IT-052-02 | DS-API-052 | 異常 | `system_settings` から `shipping_fee` の行を消す | 500 `internal_error`（固定文言。詳細はログのみ。設定の投入漏れ） |
| IT-052a-01 | DS-API-052a | 正常 | 3 つのキーを個別に、また同時に更新する | 200。`changed` が更新したキーの配列。DB が更新される。`audit_logs` に `admin.settings.update`（変更したキーの before・after）が 1 行（同時でも 1 行） |
| IT-052a-02 | DS-DEC-119 | 境界 | ST-F032-03 と同じ値（税率・送料・下限の境界と型違い） | ST-F032-03 の期待結果と同じ（成功・422・400 の別、`limit` の値）。失敗時は DB が変わらない |
| IT-052a-03 | DS-PRC-055 | 異常 | `expected_*` が現在の値と違う（複数のキーのうち 1 つだけ違う場合を含む） | 409 `stale_data`（最初に不一致だったキー、`current`）。DB は変わらない |
| IT-052a-04 | DS-API-052a | 異常 | `expected_*` の欠落。変更するキーなし（`{}`）。`payment_timeout_minutes` だけ | すべて 400 `validation_error`。`payment_timeout_minutes` だけの場合は変更するキーなしとして 400 |
| IT-052a-05 | DS-DEC-119 | 異常 | `payment_timeout_minutes` と `foo` を付けて `shipping_fee` を更新する | `shipping_fee` だけ更新される。`payment_timeout_minutes` は 30 のまま。`system_settings` に新しいキーが増えない |
| IT-052a-06 | DS-API-052a・5.6 | 異常 | **同じ `expected_shipping_fee` で送料を 10 並列**に更新する（値は互いに違う。1 章 #2） | 1 本が 200、9 本が 409 `stale_data`。`audit_logs` は 1 行。500 なし |
| IT-052a-07 | DS-PRC-052 手順 7 | 正常 | 更新のあと、`GET /settings/public` と `POST /checkout/prepare` の金額を見る | 新しい税率・送料・下限で計算される（小計が新しい下限の前後で送料が変わる。内税は新しい税率） |
| IT-052a-08 | DS-PRC-052 手順 2 | 異常 | `tax_rate` は有効、`shipping_fee` は範囲外の値を同時に送る | 422。`tax_rate` も更新されない。`audit_logs` に残らない（全か無か） |

### 4.4 注文（IT-053・053a・053b）

| ID | 対象 DS | 区分 | 前提・入力 | 期待結果 |
| --- | --- | --- | --- | --- |
| IT-053-01 | DS-API-053 | 正常 | 配送・店舗受け取り・会員・ゲストの注文を用意して `GET /orders` | 200。`ordered_at` の新しい順（同時刻は `id` の降順）。各項目に `order_number`・`ordered_at`・`status`・`status_label`・`receive_method`・`total`・`item_count`（数量の合計）・`customer_type`・`email_masked`。氏名・電話・住所のキーが無い |
| IT-053-02 | DS-API-053 | 正常 | `status` を 8 値と `all`、`receive_method` を `delivery`・`store`・`all`、`status=foo` | 絞り込みが正しい。列挙外は 400 |
| IT-053-03 | DS-DEC-125 | 境界 | `created_at` を 2026-10-27 14:59:59（UTC。JST では 23:59:59）と 15:00:00（UTC。JST では 10/28 00:00:00）にした 2 件で、`from`・`to` を 10/27 と 10/28 の組み合わせ（片方だけを含む） | 14:59:59 の注文は 10/27 の期間に入り、15:00:00 の注文は 10/28 の期間に入る。`from` だけ、`to` だけの指定も動く |
| IT-053-04 | DS-API-053 | 境界 | 注文番号の完全一致、小文字、一部だけ、`GU-1`、I・O・0・1 を含む番号 | 完全一致と小文字（大文字化して一致）は該当する。一部だけは 0 件。形が不正なものは 400 |
| IT-053-05 | DS-API-053 | 境界 | メールの完全一致、大文字・全角・前後の空白、一部だけ、255 文字、形式不正 | 正規化して完全一致する注文だけが該当する。一部だけは 0 件。255 文字と形式不正は 400 |
| IT-053-06 | DS-API-053 | 正常 | 状態・期間・受け取り方法・メールを組み合わせる | すべて AND で絞られる |
| IT-053-07 | DS-DEC-124・125 | 境界 | `from` が `to` より後。期間が 366 日、367 日。実在しない日付（2026-02-30） | 後は 422 `unsupported_value`（`field: "to"`）。366 日は 200、367 日は 422 `limit_exceeded`（`limit: 366`）。実在しない日付は 400 |
| IT-053-08 | DS-API-053 | 境界 | `per_page` を 1、100、101、`page` を 0、最終ページの次 | IT-051-05 と同じ |
| IT-053-09 | DS-PRC-053・ST-NFR-11 | 境界 | 注文を 50 件、200 件にして一覧を呼び、SQL の数を数える | 管理セッションの検証を除き 3 回（本体・件数・点数の集計）。注文数に比例しない |
| IT-053-10 | DS-API-053 | 境界 | 一致する注文がない条件 | 200。`items` は空、`total` 0 |
| IT-053a-01 | DS-API-053a | 正常 | 配送の注文の詳細 | 200。`items`・金額（`tax_included` は DS-PRC-021 の計算と一致）・`payment`・`customer`（`name`・`email_masked`・`phone_masked`・`postal_code`・`address`）・`tracking_number`・`available_transitions`。`pickup_code`・`id`・`member_id` のキーが無い |
| IT-053a-02 | DS-DEC-118 | 正常 | 店舗受け取りの注文（DB に `pickup_code` がある）の詳細 | `store`（`name`・`prefecture`・`address`）が出る。`customer` に `postal_code`・`address` が無い。`pickup_code` のキーが無い |
| IT-053a-03 | DS-API-053a | 異常 | 存在しない注文番号。形が不正な番号（小文字、短い、`../`） | すべて 404 `not_found` で本文が同一。`audit_logs` に `admin.order.view` が残らない |
| IT-053a-04 | DS-DEC-118 | 正常・異常 | 詳細を 2 回取得する。`audit_logs` への INSERT を失敗させて取得する | `admin.order.view` が 2 行（`target_id` は注文番号、`detail` は `receive_method` だけ）。INSERT の失敗時は 500 で、個人情報を返さない |
| IT-053a-05 | DS-PRC-053c | 境界 | 電話 `00000005678`、`1234`、`123`、空。メール `taro@example.com`、`@` なし | `*******5678`、`****`、`***`、空。`t***@example.com`、`***` |
| IT-053a-06 | DS-PRC-053b | 正常 | 状態 8 値 × 受け取り方法 2 値の `available_transitions` | 4.6 の表のとおり（`accepted`→`preparing`、`preparing`→`shipped`、`shipped`→`delivered`、他は空）。ラベルは配送と店舗で異なる。`accepts_tracking_number` は配送で更新先が `shipped` のときだけ真 |
| IT-053b-01 | DS-API-053b | 正常 | 配送の `accepted` の注文を `preparing`→`shipped`（追跡番号つき）→`delivered` と進める | 各段階で 200。`status_label` と `tracking_number` が応答に出る。`audit_logs` に `admin.order.status` が 3 行（`from`・`to`・`receive_method`・`tracking_number_set`）。会員の注文なら `GET /me/orders/{n}` の状態名・追跡番号が変わる |
| IT-053b-02 | DS-API-053b | 正常 | 店舗受け取りの注文を同様に進める（追跡番号は付けない） | 各段階で 200。顧客側の `pickup_code` は `shipped` まで返り、`delivered` で null になる（追補b の DS-PRC-024a） |
| IT-053b-03 | DS-API-053b | 異常 | ST-F033-08 の組み合わせ（`accepted`→`shipped` ほか 9 通りと、`preparing`→`preparing`） | すべて 409 `invalid_transition`（`from`・`to`）。DB は変わらず、`audit_logs` に残らない |
| IT-053b-04 | DS-DEC-117 | 異常 | 更新先に `cancelled`・`pickup_expired`・`payment_failed`・`accepted`・`pending_payment`（現在の状態は `accepted` と `shipped` の注文で試す） | すべて 422 `unsupported_value`（`field: "status"`）。現在の状態に関係なく同じ（遷移の判定より前） |
| IT-053b-05 | DS-API-053b | 異常 | `status` が `foo`、空文字、`SHIPPED`、null、数値 | すべて 400 `validation_error` |
| IT-053b-06 | DS-API-053b | 境界 | 追跡番号が 50 文字、51 文字、全角、空白入り、ハイフン入り。店舗の注文、`preparing` への更新に付ける。付けずに `shipped` | ST-F033-10 と同じ結果 |
| IT-053b-07 | DS-API-053b・5.6 | 異常 | **同じ `accepted` の注文に `preparing` を 10 並列**で送る（1 章 #2） | 1 本が 200、9 本が 409 `invalid_transition`。`audit_logs` は 1 行。500・タイムアウトなし |
| IT-053b-08 | 4.7 | 異常 | 存在しない注文番号に未対応の更新先（`cancelled`）を送る。管理用セッションなしで送る | 前者は 404（存在確認が先）。後者は 401（認証が最初） |
| IT-053b-09 | DS-API-053b | 異常 | `shipped` への更新を、別の追跡番号で 2 回送る | 2 回目は 409。追跡番号は 1 回目のまま |
| IT-053b-10 | DS-API-053b・A-03 | 異常 | 本文に `receive_method`・`total`・`member_id`・`pickup_code` を足して送る | 無視され、注文の他の列は変わらない |

### 4.5 スキーマ・BFF（IT-SCHEMA・IT-BFF）

IT-SCHEMA の 01〜13 は本編・追補b にある。20 以降を足す。

| ID | 対象 | 区分 | 前提・入力 | 期待結果 |
| --- | --- | --- | --- | --- |
| IT-SCHEMA-20 | 5.5 | 正常 | `alembic heads`、`alembic history` | head が 1 本。`ad00074244c2` → `13e0c198634f`（`p2b_auth_tables`）→ `f16be26dc48a`（`p2b_orders_pickup_fk`）→ `p2c_admin_constraints` の順（接尾辞は実装後のリビジョン ID に置き換えて確認） |
| IT-SCHEMA-21 | 5.5 | 正常 | 管理者とセッションの行を入れたまま、`f16be26dc48a` へ downgrade し、head へ upgrade し直す | 既存の行が失われない。downgrade で CHECK 制約と索引が消え、upgrade で戻る |
| IT-SCHEMA-22 | 5.2 | 異常 | `staff.role` に `staff`・`admin`・空文字を INSERT／UPDATE する。`information_schema.statistics` で `audit_logs` の索引を調べる | `staff` は入る。`admin`・空文字は拒否される。`ix_audit_logs_target_type_target_id_at` が存在する（列の順序は target_type・target_id・at） |
| IT-BFF-050 | DS-API-050・4.5 | 正常 | BFF の `POST /admin/api/auth/login`（`fetch` のモックで FastAPI の応答を返す）。成功応答に `session_token` を含める | ブラウザへの本文に `session_token` が無い。`Set-Cookie` に `asid`（`HttpOnly`・`SameSite=Strict`・`Path=/admin`・`Max-Age=28800`、production 設定では `Secure`）と新しい `csrf_token`（`Path=/`・HttpOnly なし）。FastAPI へは `X-Forwarded-For` に利用者の IP が付き、利用者が送った `X-Forwarded-For` は転送されない。`asid` があれば `X-Admin-Session-Token` に載り、会員の `sid` は渡らない。`Cache-Control: no-store` |
| IT-BFF-051 | 4.0・DS-DEC-121 | 異常 | 変更系 6 本（ログイン・ログアウト・商品・在庫・設定・注文状態）を CSRF トークンなし、不一致、`Origin: https://evil.example` で呼ぶ | すべて 403 `forbidden`。FastAPI（モック）は呼ばれない。拒否ログが 1 行（本文・Cookie を含まない） |
| IT-BFF-052 | DS-API-050a | 正常 | `POST /admin/api/auth/logout`（`asid` つき）。FastAPI が 204 を返す場合、失敗を返す場合、接続できない場合 | どれでも `asid` の削除 Cookie（`Max-Age=0`・`Path=/admin`）と新しい `csrf_token`。成功は 204 |
| IT-BFF-053 | 4.5 | 異常・正常 | 変更系 4 本（商品・在庫・設定・注文状態）を、`asid` なし、形が違う `asid`、正しい形の `asid` で呼ぶ | `asid` が無い・形が違うものは 401 `unauthorized`（FastAPI を呼ばない）。正しい形のものは `X-Admin-Session-Token` に `asid` の値が載り、`X-Session-Token` は載らない |
| IT-BFF-054 | 4.5 | 異常 | 本文に余計な項目（`name`・`role`・`member_id`）を足す。型違い（`stock` が "5"、`published` が "true"）。9000 バイトの本文（`Content-Length` あり・なし） | 余計な項目は FastAPI に渡らない（白リスト）。型違いは 400 `validation_error`（FastAPI を呼ばない）。9000 バイトは 413 `payload_too_large` |
| IT-BFF-055 | 4.5・DS-DEC-124 | 異常 | FastAPI が 401、403、409 `stale_data`（`field`・`current`）、409 `invalid_transition`（`from`・`to`）、422（`field`・`limit`）、429（`Retry-After`）、接続不可を返す | ステータスと `{code}` と許可した詳細キー（`field`・`current`・`from`・`to`・`limit`・`fields`）がそのまま返る。`current` が落ちない。429 は `Retry-After` を透過。接続不可は 503 `upstream_unavailable` |
| IT-BFF-056 | DS-DEC-121 | 正常 | `GET /admin/api/csrf`（`csrf_token` 未発行・発行済みの 2 通り） | 204。未発行なら `Set-Cookie` で発行し、発行済みなら出さない。`Cache-Control: no-store`。FastAPI は呼ばれない |

## 5. 単体テスト（UT）追加分

### 5.1 FastAPI（pytest）

DB を要する関数は SQLite インメモリで実行する（本編 1.1）。MySQL 固有の挙動（`FOR UPDATE`・READ COMMITTED・CHECK 制約）は IT で担保する。

| ID | 対象 | 区分 | 入力 | 期待結果 |
| --- | --- | --- | --- | --- |
| UT-ADM-01 | 管理セッションの有効性（DS-PRC-050b） | 境界 | `expires_at` が現在の 1 秒後・ちょうど現在・1 秒前、`subject_type` が staff・member、管理者の行が無い | 1 秒後の staff だけが有効。ちょうど現在は無効（`expires_at > now`）。管理者の行が無ければ無効 |
| UT-ADM-02 | セッションの分類（DS-PRC-050b） | 正常・異常 | 有効な staff、有効な member、期限切れ、不明、形が違う値（42・44 文字、`=` や空白入り）、None | 分類は「管理者」「会員」「無効」の 3 つ。形が違う値と None は DB を引かずに「無効」。例外を投げない |
| UT-ADM-03 | `require_staff` の状態コード（DS-DEC-109・111） | 異常 | 分類ごとの結果。`ALLOWED_ROLES` を空に差し替えて有効な staff を通す | 無効は 401、会員は 403、管理者は通る。許可外のロールは 403。依存関数は読み取りの `rollback()` を呼んで終わる |
| UT-ADM-04 | login_id の正規化（DS-API-050） | 正常・異常 | 全角、大文字、前後空白、全角空白、ゼロ幅スペース、制御文字、2 文字・3 文字・50 文字・51 文字、先頭が `.` や `-`、記号入り | 全角・大文字・前後空白は半角の小文字に整う。ゼロ幅・制御文字・記号入り・先頭が記号・2 文字以下・51 文字以上は拒否。3 文字と 50 文字は可 |
| UT-ADM-05 | 管理ログインの識別子と閾値（DS-DEC-110） | 境界 | 同じ login_id の全角・半角・大文字違い。失敗が ID 単位で 4・5 件、IP 単位で 9・10 件。会員の行（`subject_type=member`）と成功の行が混ざる | 識別子は正規化後に同じ SHA-256（64 桁）。ID 単位は 5 件でロック、IP 単位は 10 件で拒否。数えるのは失敗かつ `subject_type=staff` の行だけ |
| UT-ADM-06 | 管理者がいないときのダミー検証（DS-DEC-110） | 正常 | 検証関数を差し替えて呼び出し回数を数える。管理者あり・なしでログイン処理を呼ぶ | どちらも検証関数が 1 回呼ばれる（なしのときはダミーのハッシュに対して） |
| UT-ADM-07 | 更新前の値の照合（DS-PRC-055） | 境界 | 一致、不一致、`True` と `1`、`0` と `False`、`"0.10"` と `0.1`、`"550"` と `550`、None | 型を含めて厳密に等しいときだけ通る。不一致は 409 `stale_data`（`field`・`current`） |
| UT-ADM-08 | 在庫の検査（DS-DEC-114） | 境界 | 0・1・9999・10000・-1・2147483647・2147483648、真偽値、小数、文字列、None | 0〜9999 は可。-1 は業務の範囲（`unsupported_value`）、10000 以上 2147483647 以下は `limit_exceeded`。型違い・2147483648 以上は形の違反（400） |
| UT-ADM-09 | 価格の検査（DS-DEC-116） | 境界 | 0・1・1000000・1000001・-1・桁あふれ・型違い | 1〜1000000 は可。0 以下は `unsupported_value`、1000001 以上は `limit_exceeded`。型違い・桁あふれは 400 |
| UT-ADM-10 | 設定の検査（DS-DEC-119） | 境界 | `tax_rate` の `0.00`・`0.30`・`0.31`・`1.00`・`0.1`・`10%`・`abc`、送料 0・5000・5001・-1、下限 0・100000・100001・-1 | `tax_rate` の形は `^[0-9]\.[0-9]{2}$`。範囲は ST-F032-03 のとおり（可・`limit_exceeded`・`unsupported_value`・形の違反）。範囲の判定は `tax_rate_basis_points` と矛盾しない（0.30 は 30） |
| UT-ADM-11 | LIKE のエスケープ（DS-PRC-051） | 異常 | `%`・`_`・`\`・`a%b`・日本語・SKU の小文字 | 生成された条件でワイルドカードが働かない（`autoescape`）。SKU の前方一致は大文字に直して照合する |
| UT-ADM-12 | JST の暦日から UTC の範囲への変換（DS-DEC-125） | 境界 | `from`・`to` が 2026-10-27、月末（10/31→11/1）、閏日（2028-02-29）、年末、`from` だけ、`to` だけ | 開始は JST 0:00 を UTC に直した値（前日 15:00）、終了は `to` の翌日の JST 0:00（排他）。月や年をまたぐ。実在しない日付は拒否 |
| UT-ADM-13 | マスク（DS-PRC-053c） | 境界 | 電話：11 桁、5 桁、4 桁、3 桁、空。メール：通常、`@` なし、局所部が空、ドメインが空 | 電話は 5 桁以上で末尾 4 桁だけ残して `*`、4 桁以下は全部 `*`、空は空。メールは `t***@example.com`、崩れていれば `***` |
| UT-ADM-14 | 更新先の判定（DS-PRC-053b） | 異常・境界 | 現在の状態 8 値 × 更新先 8 値（64 通り） | 更新先が `preparing`・`shipped`・`delivered` 以外は 422 `unsupported_value`（現在の状態に関係なく 40 通り）。残り 24 通りのうち遷移表にあるもの（`accepted`→`preparing`、`preparing`→`shipped`、`shipped`→`delivered`）の 3 通りだけ成功、21 通りは 409 `invalid_transition` |
| UT-ADM-15 | 次の操作（`available_transitions`） | 正常 | 状態 8 値 × 受け取り方法 2 値 | 4.6 の表のとおり。ラベルは追補b の `status_label` と一致。`accepts_tracking_number` は配送で更新先が `shipped` のときだけ真 |
| UT-ADM-16 | 追跡番号の検査（DS-API-053b） | 境界 | 1・50・51 文字、全角、空白入り、ハイフン入り、空文字。受け取り方法 2 値 × 更新先 | 形は `^[A-Za-z0-9-]{1,50}$`。付けてよいのは配送で更新先が `shipped` のときだけ（他は 422） |
| UT-ADM-17 | 監査ログの禁止キー（DS-PRC-054） | 異常 | `detail` に `email`・`name`・`phone`・`address`・`postal_code`・`pickup_code`・`password`・`token`・`guest_email`・`ship_name` を、入れ子の中も含めて入れる。許可するキー（`sku`・`before`・`after`）だけの `detail` | 禁止キーがあれば `RuntimeError`（入れ子でも検出）。許可するキーだけなら通る。`actor_type` は staff、`actor_id` は管理者の ID |
| UT-ADM-18 | 監査ログの改変が無いこと（DS-DEC-120） | 異常 | `apps/api/app` 配下のソースを走査し、`audit_logs`／`AuditLog` に対する `update(`・`delete(`・`UPDATE`・`DELETE` を探す | 0 件（INSERT だけ）。検出したら失敗し、場所を表示する |
| UT-ADM-19 | 再入荷の起動条件（DS-DEC-115） | 境界 | (更新前, 更新後) が (0, 5)・(0, 1)・(0, 0)・(3, 5)・(5, 0)・(5, 5) | (0, 5)・(0, 1) だけが真。他は偽 |
| UT-SEED-20 | seed の管理者（DS-DEC-112） | 正常 | `seed_data.STAFF` | 1 件。login_id が `demo-staff` で DS-API-050 の形式に合う。`role` は `staff`。パスワードの定数はテストが値を読むだけで、他のファイルに値を書かない |
| UT-SEED-21 | production の seed（DS-DEC-112） | 異常 | `APP_ENV=production` で `SEED_STAFF_PASSWORD` が未設定、11 文字、空文字 | 管理者を 0 件にする。理由を標準エラーに出す。会員・店舗・商品の seed は続く |
| UT-SEED-22 | production の seed（正常） | 正常 | `APP_ENV=production` で 12 文字の `SEED_STAFF_PASSWORD`、`SEED_STAFF_LOGIN_ID` あり・なし・形式不正 | 1 件投入する。ハッシュは argon2id で、NFKC 正規化後のパスワードで検証できる。login_id は環境変数の値（形式不正は投入しない）。既定のダミーパスワードでは検証できない |
| UT-SEED-23 | `--only-p2c`（DS-DEC-112） | 正常 | `staff` 表が空のとき、1 行あるとき、`--update-staff-password` あり・なし | 空のときだけ 1 件投入し、2 回目は何もしない。`--update-staff-password` は同じ login_id のハッシュだけを更新する（他の列は変えない） |

### 5.2 Next.js（Vitest）

| ID | 対象 | 区分 | 入力 | 期待結果 |
| --- | --- | --- | --- | --- |
| UT-WEB-40 | `asid` Cookie の組み立て（DS-DEC-108） | 正常・境界 | 通常値、`production` の設定、削除用、使えない文字を含む値 | `HttpOnly; SameSite=Strict; Path=/admin; Max-Age=28800`、`production` のとき `Secure`。削除用は `Max-Age=0` で値が空で、`Path=/admin`。使えない文字（改行・`;`）を含む値は例外。会員の `sid` の組み立て（UT-WEB-15）は変わらない |
| UT-WEB-41 | 管理シェル（DS-SCR 6.2） | 正常 | 描画する。現在のパスを `/admin/products`・`/admin/orders`・`/admin/settings` にする。設定の画面を有効・無効にする | メニューの現在のページに `aria-current="page"`。右上に login_id とログアウト。顧客向けのヘッダー・フッター・カート表示が出ない。設定の画面が無効のときはメニューに「設定」が出ない |
| UT-WEB-42 | 管理ログインフォーム（DS-SCR-014） | 正常・異常 | 401・403・429・503 の応答、送信中、成功、`?expired=1` | 状態別の文言（6.7 の表）。送信中はボタン無効で二重送信されない。成功で `/admin/products` へ `router.replace` と `router.refresh`（遷移先の指定を受けない）。`expired` のときは有効期限切れの案内 |
| UT-WEB-43 | 商品一覧の検索条件（DS-SCR-015-1） | 異常・境界 | `visibility`・`stock` に列挙外、`q` が 51 文字、`page` が 0・文字列・7 桁、配列で渡された値 | 列挙外は既定に戻す。`q` は 50 文字までに切る（またはエラー表示）。`page` は 1 以上の整数以外なら 1。FastAPI へ渡すクエリは検査済みの値だけ |
| UT-WEB-44 | 在庫の行（DS-SCR-015-2） | 正常・異常・境界 | 保存の成功（0→5 で待ち 2 件）、同値、409 `stale_data`、422、入力が空・負・10000・小数 | 0 から 1 以上にする前に「再入荷待ちの N 件にメールを送ります」を出す。成功のトーストに前後の値と待ち件数。同値では保存ボタンが無効。409 は `current` で行を更新して案内。範囲外は送信せず入力欄の下に表示。`expected_stock` には画面が表示していた値を入れる |
| UT-WEB-45 | 公開切替と価格（DS-SCR-015-2） | 正常・異常 | 公開の切り替え（確認ダイアログの OK・キャンセル）、価格の保存、両方を変えた保存、409、422 | 公開切り替えは確認ダイアログを経る（キャンセルで送らない）。送るのは変更した項目と対応する `expected_*` だけ。409・422 は項目の近くに文言を出す |
| UT-WEB-46 | 注文一覧の検索条件（DS-SCR-015-3） | 異常・境界 | 状態・受け取り方法の列挙外、日付が実在しない・逆順、注文番号の形違い、メール 255 文字 | 列挙外は既定に戻す。日付の逆順はエラー表示。形が違う注文番号・メールは FastAPI に渡さない（画面のエラー）。入力は URL のクエリに反映される |
| UT-WEB-47 | 注文詳細（DS-SCR-015-4） | 正常・異常 | `available_transitions` が 0 件・1 件の状態、更新先が `shipped`（`accepts_tracking_number` が真・偽）、`customer.name` に `<script>…</script>` | ボタンは `available_transitions` の件数だけ描画（画面に遷移表を置かない）。追跡番号の欄は `accepts_tracking_number` が真のときだけ。0 件は「画面で更新できる操作はありません」。受け取りコードの要素が無い。氏名はテキストとして表示され、HTML として解釈されない。押すと確認ダイアログを経る |
| UT-WEB-48 | 設定フォーム（DS-SCR-016） | 正常・異常 | 変更なし、1 項目だけ変更、範囲外、409、`payment_timeout_minutes` | 変更がなければ保存ボタンが無効。送るのは変更した項目と `expected_*`。範囲外は範囲を示す文言。`payment_timeout_minutes` は入力欄がなく表示のみ |
| UT-WEB-49 | 管理画面のエラー文言の対応表 | 正常 | コード 401 `invalid_credentials`・403 `account_locked`・429・403 `forbidden`・409 `stale_data`・409 `invalid_transition`・422・400・503・未知のコード | 画面の文言が 6.7 の表どおり。`stale_data` の文言に `current` の値が入る。未知のコードは汎用の文言（内部のコードを画面に出さない） |
| UT-WEB-50 | 管理 BFF の共通処理（`admin-proxy`） | 正常・異常 | `asid` あり・なし・形違い。FastAPI の応答に `session_token`。`Retry-After` つきの 429。接続不可 | `asid` の値だけを `X-Admin-Session-Token` に載せ、会員の `sid`・`cart_token` は渡さない。`session_token` は本文から除いて `asid` の Set-Cookie にする。`Retry-After` は数字のときだけ透過。接続不可は 503。許可した詳細キー（`current` を含む）だけ返す |
| UT-WEB-51 | 管理データの読み込み（`lib/server/admin.ts`） | 正常・異常 | `asid` なし、FastAPI が 200・401・403・404・500・接続不可 | `asid` が無い・401・403 は `redirect("/admin/login")`。404 は `notFound`。500・接続不可はエラー表示（`LoadError`）。`redirect` は try/catch の外で呼ぶ |
| UT-WEB-52 | ルートレイアウトの分離（DS-DEC-122） | 正常 | リクエストヘッダー `x-admin-area` が `1`、無し、`0`、`1` 以外の値で描画する | `1` のときだけ顧客向けのヘッダー・フッター・カート・カテゴリの取得を省く。それ以外は従来どおり顧客向けの枠を出す |
| UT-WEB-53 | `proxy.ts` と `classifyPath`（DS-DEC-122・126） | 正常・異常 | `/admin/login`・`/admin/products`・`/admin/api/csrf`・`/api/cart`・`/mypage` のリクエスト。利用者が `x-admin-area: 1` を付けて `/mypage` を呼ぶ | `/admin` 配下のリクエストにだけ `x-admin-area: 1` が付く。それ以外では利用者が付けた値が取り除かれる。`/admin/api/*` は種類が「api」で、`/api/*` と同じ上限（120 回/分）で数えられる。`/admin` のページは「page」 |
| UT-WEB-54 | ページ送り（`AdminPager`） | 境界 | 1 ページだけ、先頭、中間、最終、`has_more` が偽、総件数 0 | 先頭は「前へ」なし、最終は「次へ」なし。1 ページだけなら出さない。総件数 0 は「該当なし」。リンクの `page` は 1 以上の整数で、他の検索条件を保つ |

## 6. テストデータ

| データ | 用途 | 対応テスト |
| --- | --- | --- |
| seed の管理者 `demo-staff`（パスワードは `seed_data.py` の定数。本書には書かない） | ログイン、AT・ST | AT-30〜37、ST-F035、IT-050-01、UT-SEED-20 |
| テスト内で作る管理者（S-OTHER：2 人目、S-LOCK：ロック検証用、S-CONC：並行ログイン用、S-OLD：旧パラメータのハッシュ） | ロック、並行、再ハッシュ、セッション上限 | IT-050-03〜12、IT-050a、IT-ADM |
| seed の会員 `demo-member1`・`demo-member2`（`sid` を使う） | 会員のセッションを管理 API に提示 | ST-SEC-80・86・93、IT-050b-03、IT-ADM-02 |
| seed の商品 31 点、商品 1（公開切替・価格）、商品 29（V-STOCK0：色ブラック・サイズ M。SKU `GU-029-BK-M`。在庫 0） | 一覧、公開、価格、在庫、再入荷 | AT-31・32、ST-F031、IT-051、IT-051c |
| 再入荷の申込 2 件・3 件（`example.com` のダミーのメール）、通知済みの申込 1 件 | 再入荷通知の送信側 | AT-31、ST-F031-05、IT-051a-01、IT-051c-02・07 |
| 名前に `%`・`_` を含む商品（テスト内で追加） | LIKE のエスケープ | ST-F031-02、IT-051-03、UT-ADM-11 |
| 在庫 3 のバリエーション（テスト内で作る） | 注文確定との並行 | IT-051c-08 |
| 配送の注文（状態 `accepted`）、店舗受け取りの注文（`accepted`）、会員の注文、ゲストの注文 | 一覧、詳細、状態更新 | AT-33・34、ST-F033、IT-053 |
| 状態を DB で `pending_payment`・`cancelled`・`payment_failed`・`pickup_expired`・`delivered` にした注文 | 不正な遷移、未対応の更新先 | ST-F033-08・09、IT-053b-03・04、UT-ADM-14 |
| 注文日時を 2026-10-27 14:59:59 と 15:00:00（UTC）にした注文 | 期間の JST 境界 | ST-F033-02、IT-053-03、UT-ADM-12 |
| 氏名・住所に `<script>alert(1)</script>` などを入れた注文（DB に直接入れる） | 管理画面での XSS、SQL 文字列 | ST-SEC-87 |
| 注文 50 件・200 件、商品 300 点 | SQL の数（N+1 なし） | ST-NFR-11、IT-051-06、IT-053-09 |
| 変更前後の設定値（税率 0.10・送料 550・下限 4990・決済待ち 30） | 設定の更新と復元 | AT-35、ST-F032、IT-052a |
| `APP_ENV=production` の起動設定、`SEED_STAFF_PASSWORD`（11 文字・12 文字のダミー） | seed の production 規則 | ST-SEC-92、UT-SEED-21・22 |

## 7. 実施計画

| 時期 | 内容 |
| --- | --- |
| 実装と同時（10/26〜29） | UT・IT を各レーンが書く（設計仕様書 11 章のレーンごとの担当）。CI（`pytest`・`vitest`・`ruff`・lint・型検査）を毎回緑にする。優先順位は設計仕様書 11.1（F-035 → F-031・F-033 → F-032） |
| 10/29 | 結合した状態で IT を全件実行。同時実行テスト（IT-050-10・051b-09・051c-07・051c-08・052a-06・053b-07 の 6 本）は 1 章 #2 の条件で反復し、無効試行の数を記録する。防御を 1 つずつ外して赤くなることを確認する（下の 8 章 #1） |
| 10/30（P2-c の検収） | AT-30〜37 を PC 幅と 375px で実施。ST-F035・F031・F033・F032 と ST-SEC-80〜95、ST-NFR-10・11 を実施。結果を `docs/05_検収/` に記録し、10 章へ転記する |
| 10/31（P2 全体の検収） | 公開環境で、管理者の seed（`--only-p2c`）を実行し、管理画面のログイン・ログアウトと、公開サイトに管理画面へのリンクがないことを確認する。`Secure` 属性の確認は、コードの条件とユニットテストで代える |

## 8. 申し送り

1. **防御外し確認（本編 1.4 #8）の対象を足す**：①`require_staff` の「会員のセッションは 403」の分岐を外す→IT-050b-03・ST-SEC-80 ②管理 API のルーター単位の認証（既定拒否）を外す→IT-ADM-01・ST-SEC-81 ③更新前の値の照合（`ensure_expected`）を外す→IT-051c-04・IT-051c-07 ④行の `FOR UPDATE` を外す→IT-051c-07・IT-051c-08・IT-053b-07 ⑤`assert_transition` を外す→IT-053b-03 ⑥管理操作の `audit_logs` の INSERT を外す→IT-051c-01・ST-SEC-89 ⑦注文詳細の `pickup_code` を応答に足す→IT-053a-02・ST-SEC-88 ⑧管理者の ID 単位のロック判定を外す→IT-050-03・ST-SEC-86 ⑨`asid` の `Path=/admin`・`SameSite=Strict` を外す→UT-WEB-40・ST-SEC-83。`scripts/mutation-check/cases.json` に 9 件を足し、結果表を実施記録に転記する。
2. **F-032 の設定の画面を削った場合（ADR-0006 の削る順番の④）**：AT-35、ST-F032-01〜06、IT-052・052a、UT-ADM-10、UT-WEB-48 を「未実装」として実施せず、検収記録に未実装と明記する。F-035・F-031・F-033 のテストには影響しない（ファイルを分けてある）。
3. **要求との差分を検証しないテスト**：商品の新規登録・画像・カテゴリ割当の編集（設計仕様書 DS-DEC-116）、注文のキャンセル・返品・返金、クーポン・キャンペーンには、テストを置かない。検収記録に未実装と書く。
4. **90 日削除ジョブは未実装（DS-DEC-120）**：90 日を過ぎた `audit_logs` の削除を確かめるテストは無い。検収記録に未実装と書く。
5. **コード照合（F-038）は P3**：ST-F033-07・AT-34 の「受け渡し済」は、店舗スタッフの本人確認なしに管理者が更新する。コード照合のテストは P3。
6. **IF-02 の実送信を別に実装した場合**：再入荷メールのテスト（AT-31・IT-051c-02）は、記録用アダプタと outbox のままでよい。実送信の確認は IF-02 側の検収で行い、本書のテストは変えない。
7. **ブラウザの実機確認**：`asid` の Cookie が `/admin/*` にだけ付くこと（ST-SEC-83）と、`SameSite=Strict` の挙動は、AT-30 の手順で DevTools を見て確認する。自動テストはヘッダー文字列までを確かめる。
8. **回数制限はプロセス内メモリ**：BFF の全体制限（S1）は複数インスタンスで共有されない（本編 9.4 と同じ）。F1 は 1 インスタンス・1 ワーカー（ADR-0005）で許容する。管理ログインの制限は DB で数えるため、再起動をまたいでも有効。

## 9. 講義の必須観点との対応（P2-c 分）

| 講義の観点 | 対応するテスト |
| --- | --- |
| 管理権限・BFLA（A-02） | ST-SEC-80・81・93、IT-050b-03、IT-ADM-01〜03、UT-ADM-03 |
| 未ログインでの保護ページ・API（A-04） | ST-F035-06、ST-SEC-81・94、IT-ADM-01・03 |
| 総当たり対策・ロック（B-04）と列挙（B-03） | ST-SEC-85・86、ST-F035-02〜04、IT-050-02〜05・11、UT-ADM-05・06 |
| セッション固定・Cookie 属性（B-06・B-01） | ST-SEC-83・84、IT-050-06・07、IT-BFF-050、UT-WEB-40 |
| ログアウト・失効（J-04） | ST-F035-05・07・08、IT-050a、IT-050b |
| CSRF（C-03） | ST-SEC-82、IT-BFF-051 |
| インジェクション・XSS（C-01・C-02） | ST-SEC-87、IT-051-03、UT-ADM-11、UT-WEB-47 |
| mass assignment（A-03） | ST-SEC-90、IT-051b-07、IT-051c-11、IT-053b-10 |
| 内部 ID の秘匿・個人情報の最小表示（A-07・REQ-NFR-07） | ST-SEC-88、ST-F033-04・05、IT-053a-01・02、UT-ADM-13 |
| 監査ログ（F-05・REQ-NFR-04） | ST-SEC-89、AT-36、UT-ADM-17・18 |
| セキュリティヘッダー・キャッシュ・検索避け（D-01〜D-03） | ST-SEC-91、IT-ADM-04 |
| テスト用アカウントの残存（B-07） | ST-SEC-92、UT-SEED-21・22 |
| 同時実行（整合性） | IT-051b-09、IT-051c-07・08、IT-052a-06、IT-053b-07、IT-050-10 |
| 回数制限（G-01） | ST-SEC-95 |

## 10. トレーサビリティ表（P2-c 追加分）

件数（本書の表の ID を機械的に数えた値）：AT 8（AT-30〜37）、ST-F 40（ST-F035 10・ST-F031 11・ST-F033 13・ST-F032 6）、ST-NFR 2（ST-NFR-10・11）、ST-SEC 16（ST-SEC-80〜95）、IT 101、UT 38（API 側 23・Web 側 15）。合計 205 件。

| REQ | F／SCR | DS | AT | ST | IT | UT |
| --- | --- | --- | --- | --- | --- | --- |
| REQ-FR-1105 | F-035／SCR-014 | DS-API-050・050a・050b、DS-PRC-050・050b、DS-DEC-107〜112・121・122・126 | AT-30 | ST-F035-01〜10、ST-SEC-80〜86・91〜95 | IT-050、IT-050a、IT-050b、IT-ADM-01〜05、IT-BFF-050〜053・056 | UT-ADM-01〜06、UT-SEED-20〜23、UT-WEB-40〜42・51〜53 |
| REQ-FR-1101 | F-031／SCR-015-1・015-2 | DS-API-051・051a・051b・051c、DS-PRC-051・051b・051c、DS-DEC-113〜116 | AT-31・32 | ST-F031-01〜11 | IT-051、IT-051a、IT-051b、IT-051c、IT-BFF-053〜055 | UT-ADM-07〜09・11・19、UT-WEB-43〜45 |
| REQ-FR-205（送信側） | F-007／SCR-015-2 | DS-PRC-051c 手順 10・11、DS-DEC-115 | AT-31 | ST-F031-05・08 | IT-051c-02・03・06・07・09 | UT-ADM-19 |
| REQ-FR-1103 | F-033／SCR-015-3・015-4 | DS-API-053・053a・053b、DS-PRC-053・053b・053c、DS-DEC-117・118・124・125 | AT-33・34 | ST-F033-01〜13 | IT-053、IT-053a、IT-053b | UT-ADM-12〜16、UT-WEB-46・47 |
| REQ-FR-602（管理側の更新が顧客の表示に出る） | F-017／SCR-009 | DS-PRC-053b 手順 8、追補b DS-PRC-024a | AT-33・34 | ST-F033-11 | IT-053b-01・02 | UT-ADM-15 |
| REQ-FR-1102 | F-032／SCR-016 | DS-API-052・052a、DS-PRC-052、DS-DEC-113・119 | AT-35 | ST-F032-01〜06 | IT-052、IT-052a | UT-ADM-10、UT-WEB-48 |
| REQ-NFR-04 | — | DS-PRC-054、5.4、DS-DEC-120 | AT-36 | ST-SEC-89 | IT-050-01、IT-050a-01、IT-051b-01・02、IT-051c-01、IT-052a-01、IT-053a-04、IT-053b-01 | UT-ADM-17・18 |
| REQ-NFR-07・08 | — | 7 章、DS-DEC-109・118 | AT-30 | ST-SEC-80・81・87・88・93 | IT-ADM-01〜05、IT-053a | UT-ADM-02・03・13 |
| REQ-NFR-10（管理ログイン） | — | DS-DEC-110・126 | — | ST-F035-03・04、ST-SEC-85・86・95 | IT-050-03〜05・11 | UT-ADM-05 |
| REQ-NFR-09 | — | 6 章 | AT-37 | ST-NFR-10 | — | UT-WEB-41・54 |
| REQ-NFR-05 | — | 5.7 seed、DS-DEC-112 | — | ST-SEC-92 | — | UT-SEED-20〜23 |
| （構造） | — | 5.2・5.5、DS-DEC-123 | — | — | IT-SCHEMA-20〜22 | — |
| REQ-NFR-02（性能の目安） | — | DS-PRC-051・053 | — | ST-NFR-11 | IT-051-06、IT-053-09 | — |

## 11. テスト関数との対応（実装後に転記）

本書の ID と、実装で書いたテスト関数の対応表は、実装レーンの報告を受けた後に本章へ転記する（本編 12 章と同じ運用）。転記前の時点では、全項目が実施前である。

| 区分 | ID の範囲 | テストファイル（予定） | 転記状況 |
| --- | --- | --- | --- |
| IT（管理認証・共通） | IT-050・050a・050b、IT-ADM | `apps/api/tests/integration/test_it_050_admin_auth.py`、`test_it_adm_common.py`（共有の補助：`admin_helpers.py`） | 未 |
| IT（商品・在庫） | IT-051・051a・051b・051c | `test_it_051_admin_products.py` | 未 |
| IT（設定） | IT-052・052a | `test_it_052_admin_settings.py` | 未 |
| IT（注文） | IT-053・053a・053b | `test_it_053_admin_orders.py` | 未 |
| IT（スキーマ） | IT-SCHEMA-20〜22 | `test_it_schema_p2c.py` | 未 |
| IT（BFF） | IT-BFF-050〜056 | `apps/web/tests/it-bff-050.admin-routes.test.ts` ほか | 未 |
| UT（API） | UT-ADM・UT-SEED-20〜 | `apps/api/tests/unit/test_ut_adm_*.py`、`test_ut_seed_p2c.py` | 未 |
| UT（Web） | UT-WEB-40〜54 | `apps/web/tests/ut-web-40-54.*.test.ts(x)` | 未 |
| ST-SEC の自動化 | ST-SEC-80〜95 のうち HTTP で再現できるもの | `st-sec-p2c-*.test.ts`、`test_st_sec_p2c_*.py` | 未 |
