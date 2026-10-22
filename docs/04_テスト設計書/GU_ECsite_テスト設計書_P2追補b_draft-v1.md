# GU EC サイト テスト設計書（P2 追補b）

| 項目 | 内容 |
| --- | --- |
| 文書番号 | GUEC-TD-01-P2b |
| 版 | draft-v1 |
| 作成者 | Claude |
| 作成日 | 2026-10-20 |
| 入力 | 本編 `GU_ECsite_テスト設計書_P1_draft-v2.md`（2026-10-19 追補まで）、P2 追補a `GU_ECsite_テスト設計書_P2追補a_draft-v1.md`、設計仕様書追補 `GU_ECsite_設計仕様書_P2追補b_draft-v1.md`、要求仕様書 with_ai v2.4、要件定義書 with_ai v1.3、`セキュリティ点検記録_20261019.md` |
| 対象 | P2-b：F-024 会員登録・認証、F-017 注文履歴、F-013／F-014 の店舗受け取りと受け取りコード、F-007 再入荷通知の申込、F-005 サイズ感の集計 |

## 改訂履歴

| 版 | 日付 | 内容 | 作成 | 承認 |
| --- | --- | --- | --- | --- |
| draft-v1 | 2026-10-20 | 初稿。設計仕様書 P2 追補b の設計 ID に対応する AT／ST／IT／UT を新設した。件数は 10 章の冒頭に示す。実施結果と関数名の対応は、実装の検収後に 10・11 章へ転記する | Claude | — |
| draft-v1.1 | 2026-10-20 | 実装と手元の検収で見つかった食い違いを修正。ST-SEC-56 の未ログインの `/mypage` を「302 または 307」にした（Next.js 16 の `redirect` の既定は 307） | Claude | — |
| draft-v1.2 | 2026-10-22 | セキュリティ点検 2026-10-21 の G-16・G-17・G-19 に合わせて更新。IT-032-13 を新しい処理順（設計仕様書 P2 追補b の DS-PRC-032）に合わせて書き換え、IT-032-17・IT-032-18・IT-034-06・IT-030-05b・IT-035-03b・UT-AUTH-06b・UT-SEC-05 を追加した。禁止語は 20 語から 236 語に広げた | Claude | — |

## 0. 本書の位置づけ

本書は本編（以下「本編」）と P2 追補a の追補であり、**P2-b で追加・変更した設計 ID に対応するテストだけ**を新設する。ID 体系（`AT-nn`／`ST-F<機能番号>-nn`／`ST-SEC-nn`／`IT-<DS 番号>-nn`／`UT-<略称>-nn`）、正常・異常・境界の 3 区分、4 レベルの対応は本編 0 章のとおり。既存の ID は番号を変えない。番号は既存の最大値の続きから振った。

| 種別 | 既存の最大 | 本書で振る範囲 |
| --- | --- | --- |
| AT | AT-12 | AT-13〜AT-21 |
| ST-F | ST-F001〜F036（機能別の連番） | 新規の機能は ST-F024・ST-F017。既存の機能は連番の続き（ST-F013-03〜、ST-F014-07〜、ST-F007-02〜、ST-F005-04〜） |
| ST-NFR | ST-NFR-02 | ST-NFR-03・04 |
| ST-SEC | ST-SEC-35 | ST-SEC-36〜59 |
| IT | 機能別 | IT-030〜036、IT-024・024a、IT-026、IT-007・007a、IT-003-03〜、IT-021-03〜、IT-014-10〜、IT-023-03、IT-SCHEMA-09〜、IT-BFF-030a〜 ほか |
| UT | 機能別 | UT-AUTH・UT-SESS・UT-LOCK・UT-PICK・UT-PRC・UT-STATUS・UT-FIT・UT-RESTOCK・UT-VAL-03〜、UT-SEED-08〜、UT-WEB-13〜 |

## 1. テスト方針（差分）

本編 1 章の方針をそのまま使う。差分は次のとおり。

| # | 差分 | 内容 |
| --- | --- | --- |
| 1 | 認証系の結合テストは MySQL 必須 | ロック・同時ログイン・同時登録は READ COMMITTED・UNIQUE・ギャップロックの挙動に依存するため、SQLite では確かめられない（本編 1.4 #3 と同じ理由）。`DATABASE_URL_TEST` が無いと全件 skip になる既存の仕組みをそのまま使う |
| 2 | 同時実行テストの条件 | IT-030-08（同じメールの同時登録）、IT-032-13（同じ会員の同時ログイン）、IT-035-06（同じトークンの同時確定）、IT-007-09（同じ申込の同時送信）、IT-014-19（同じ会員の別カートの同時注文）は、本編 1.4 の条件（#1 プール 20 以上、#2 同時処理中カウンタの最大値が 2 以上、#3 MySQL、#4 `alembic upgrade head`、#5 失敗側の `code` まで assert）を満たさない実行は合格と見なさない。反復回数は 10 回（有効試行）とする |
| 3 | メールの取り出し | 結合テストでは `get_mail_adapter` を `dependency_overrides` で**記録用アダプタ**に差し替え、送信した種別・宛先・リンクをメモリで読む。AT・ST の手動確認では、開発環境の `apps/api/.mail-outbox/` のファイル（名前は `<種別>-<日時>-<乱数>.txt`）を開く。本番設定（`APP_ENV=production`）ではファイルに書かず、トークンを読めない（設計仕様書 DS-DEC-89） |
| 4 | 時刻の操作 | 期限（ロック 15 分、セッション 24 時間、確認 24 時間、再設定 1 時間）のテストは、待たずに DB の時刻列（`login_attempts.at`・`sessions.expires_at`・`email_tokens.expires_at`）を直接更新して境界の前後を作る。UT は時計を引数で渡せる関数に対して行う |
| 5 | パスワードのコスト | argon2id は 1 回数十ミリ秒かかる。IT は既定のパラメータのまま実行する（コストを下げたハッシュ器に差し替えない。差し替えると本番の挙動を検証できないため）。UT-AUTH-01 だけパラメータの値そのものを検証する |
| 6 | ダミーデータ | 氏名・メールは `example.com` などのダミーに限る。パスワードは seed の `DEMO_MEMBER_PASSWORD`（ダミー値）、テスト内で作る会員のパスワードはテストコード内の固定のダミー値とする。本書には値を書かない |
| 7 | 実施環境 | AT・ST の手動確認はローカル（`pnpm dev` と `uvicorn`）。ST-SEC のうち公開環境が要るもの（Secure 属性）は、公開環境への能動テストを避ける方針（点検記録 1 章）に従い、コードの条件とユニットテストで代える |

## 2. 受け入れテスト（AT）追加分

要件定義書 7 章のユーザーストーリーのうち、US-03（再購入）は P4、US-04（キャンセル）は P3。本書は REQ ごとに AT を起こす。

| ID | 対象 | 区分 | 手順 | 期待結果 |
| --- | --- | --- | --- | --- |
| AT-13 | F-024／REQ-FR-801・807 | 正常 | `/register` で新しいダミーのメール、パスワード、氏名を入力して登録する。`/login` でログインする。ヘッダーのアイコンの変化を見る。`/mypage` を開き、ログアウトする | 登録直後は未ログインのまま、「登録を受け付けました」の案内が出る。ログインすると `/mypage` に移り、ヘッダーのアイコンが「マイページ」になる。マイページに氏名とメールが出る。ログアウトすると `/` へ移り、アイコンが「ログイン」に戻り、`/mypage` を開くと `/login` に移る。DB の `members` に 1 行、`password_hash` は `$argon2id$` で始まる |
| AT-14 | F-017／REQ-FR-601・602 | 正常 | seed の会員 `demo-member1@example.com` でログインする。商品をカートに入れ、`/checkout` を開く。配送で注文を確定する。完了画面から `/mypage` を開き、先頭の注文の詳細を開く | `/checkout` に「ログイン中」の表示が出て、氏名とメールが入っている。完了画面に「注文履歴で確認できます」が出る。マイページの先頭に今の注文が出て、状態は「受付済」。詳細に明細・金額（小計・送料・合計・うち消費税）・お届け先が出る。DB の `orders.member_id` が会員の ID |
| AT-15 | F-013・F-014・F-017／REQ-FR-501・508 | 正常 | ログインせずに商品をカートに入れ、注文手続きで「店舗受け取り」を選び、受け取り店舗に「デモ店 東京」、受け取る方の氏名・電話・メールを入れる。確認画面で金額を見て確定する。完了画面の受け取りコードを控え、注文番号とメールで注文照会する | 郵便番号・住所の欄が消える。確認画面の送料は ¥0（「店舗受け取りのため送料はかかりません」）。完了画面に 8 文字の受け取りコード（`ABCD-EFGH` の形）と店舗名・住所が出る。注文照会の結果にも同じコードと店舗が出る。DB の `orders.receive_method` は `store`、`pickup_code` は 8 文字、`ship_postal_code`・`ship_address` は店舗の値 |
| AT-16 | F-007／REQ-FR-205 | 正常 | 商品 29「リブレギンス」の色ブラック・サイズ M（在庫 0。V-STOCK0）を選び、再入荷のお知らせにダミーのメールを入れて申し込む。DB で当該バリエーションの在庫を 5 にし、`uv run python -m app.restock_notify --sku GU-029-BK-M` を実行する | 申込後に「申し込みました」が出る。コマンド実行後、`.mail-outbox/` に再入荷のメール（商品名・色・サイズ・商品ページのリンク）が 1 通できる。`restock_notifications.notified_at` に時刻が入る。同じコマンドをもう一度実行してもメールは増えない |
| AT-17 | F-005／US-06・REQ-FR-208 | 正常 | 商品 1「スムースコットンT（レディース）」の詳細を開く。次に商品 9「シアーロングワンピース」を開く | 商品 1 は「全 10 件」「小さめ 2／ちょうどよい 6／大きめ 2」と棒が出る（未承認の 1 件は数えない）。商品 9 は「サイズ感のレビューはまだありません」。商品説明の後・関連商品の前に出る |
| AT-18 | REQ-NFR-10・F-024 | 異常 | 会員 `demo-member2@example.com` のメールに、誤ったパスワードで 5 回ログインを試みる。6 回目に正しいパスワードで試みる | 1〜5 回目は「メールアドレスまたはパスワードが違います」。6 回目は正しいパスワードでも「ログインを一時的に止めています」が出てログインできない。登録していないメールで同じ操作をしても、同じ文言・同じ順序（5 回目まで同一、6 回目からロック）になる |
| AT-19 | F-024／REQ-FR-803 | 正常 | ブラウザ A で会員にログインしておく。ブラウザ B で `/password-reset` からメールを入力し、`.mail-outbox/` のリンクを開いて新しいパスワードを設定する。旧パスワードと新パスワードでログインを試み、ブラウザ A で `/mypage` を開く | 再設定の要求画面は、登録の有無にかかわらず同じ案内を出す。新パスワードでログインでき、旧パスワードでは「違います」。ブラウザ A の `/mypage` は `/login` に移る（旧セッションが失効）。同じリンクをもう一度開いて送信すると「リンクが無効か、期限が切れています」 |
| AT-20 | F-024／REQ-FR-802 | 正常 | AT-13 で登録した会員でログインし、マイページの「未確認」表示を確認する。`.mail-outbox/` の確認メールのリンクを開き、「メールアドレスを確認する」を押す。マイページを開き直す | 確認前は「確認が済んでいません」のバナーが出る。リンクを開いただけでは確認されず、ボタンを押すと「確認が完了しました」が出る。マイページの表示が「確認済み」に変わる |
| AT-21 | REQ-NFR-09 | 正常 | AT-13・AT-14・AT-15 を画面幅 375px で行う | すべての操作が完了できる。横スクロールが出ない。ログイン・登録・注文手続き（店舗受け取りの選択）・マイページ・注文詳細（受け取りコード）の各ボタンとリンクが 44px 以上で押せる |

## 3. システムテスト（ST）追加分

### 3.1 機能要件

#### F-024 会員登録・認証

| ID | 対象 F／DS | 区分 | 観点・手順 | 期待結果 |
| --- | --- | --- | --- | --- |
| ST-F024-01 | F-024／DS-API-030 | 正常 | 新しいメール・パスワード（10 文字）・氏名で登録する | 202 `{"status":"accepted"}`。`members` が 1 行増え、`password_hash` は argon2id、`email_verified_at` は NULL。`email_tokens` に verify_email が 1 行。確認メールが outbox に 1 通。`audit_logs` に `member.register`。`Set-Cookie` は出ない（自動ログインしない） |
| ST-F024-02 | F-024／DS-API-030 | 異常 | メールに `abc`・`a@`・全角のみの不正形式、パスワードを空、氏名を空白のみ（全角含む）、生年月日を明日にして登録する | いずれも 400 `validation_error`。`fields` に項目名と reason。`members` は増えない |
| ST-F024-03 | F-024／DS-API-030・DS-DEC-69 | 境界 | パスワードを 7 文字、8 文字、128 文字、129 文字にする。全角英数 8 文字（例：`ｘｋｐｑｔｒｗｍ`）で登録し、半角の `xkpqtrwm` でログインする | 7 と 129 は 400（`out_of_range`／`too_long`）、8 と 128 は 202。全角で登録した値は NFKC 正規化で半角と同じになり、半角でログインできる。`xkpqtrwm` は禁止語でも連番・繰り返しでもないため登録できる（旧版の例 `abcdefgh` は、G-17 で連番が弱いパスワードになったため変えた） |
| ST-F024-04 | F-024／DS-API-032 | 正常 | 登録済みの会員でログインする | 200。`sid` Cookie が付く（属性は ST-SEC-44）。ブラウザへの本文に `session_token` が無い。`sessions` に 1 行（`token_hash` は 64 桁の 16 進で、Cookie 値そのものではない）。ヘッダーのアイコンが「マイページ」になる |
| ST-F024-05 | F-024／DS-API-032 | 異常 | 誤ったパスワード、登録していないメールでログインする | どちらも 401 `invalid_credentials` で本文が同一。`Set-Cookie` に `sid` は無い。`login_attempts` に失敗が 1 行ずつ増える。画面の文言は同一 |
| ST-F024-06 | F-024／DS-API-033 | 正常 | ログイン中にログアウトする。直後に旧 `sid` の値で `GET /mypage` を開く | 204。`sessions` の当該行が消える。`sid` は削除される。旧 `sid` で `/mypage` を開くと `/login` に移る。ログアウトを 2 回続けて呼んでも 2 回目も 204 |
| ST-F024-07 | F-024／DS-API-031 | 正常 | 登録直後の会員で、outbox の確認メールのリンクを開き、ボタンを押す | 200 `{"verified":true}`。`email_verified_at` に時刻が入る。`email_tokens.used_at` が入る。マイページが「確認済み」になる |
| ST-F024-08 | F-024／DS-API-031・DS-DEC-74 | 異常・境界 | 同じトークンで 2 回確認する。`expires_at` を 1 秒前にしたトークン、1 秒後にしたトークンで確認する。トークンの形が違う値（42 文字）で確認する | 2 回目は 404。期限の 1 秒前（未到来）は成功、期限切れは 404。形が違う値は 400。ページを開いただけでは `email_verified_at` は変わらない |
| ST-F024-09 | F-024／DS-API-034・035 | 正常 | 再設定を要求し、outbox のリンクから新パスワードを設定する | 要求は 200。トークンは `reset_password` の 1 行。確定は 200。パスワードのハッシュが変わり、当該会員の `sessions` が 0 行、失敗行が 0 行になる。`audit_logs` に `member.password_reset` |
| ST-F024-10 | F-024／DS-API-034・035 | 異常・境界 | 登録していないメールで要求する。確定で弱いパスワード（`password123`）を送る。トークンの期限を 1 時間 1 秒前と直後にして確定する。同じ会員で要求を 2 回して古いリンクで確定する | 未登録のメールでも 200 で本文は同一（`email_tokens` は増えない）。弱いパスワードは 422 `weak_password` で、このときトークンは消費されない（同じトークンで正しい値を送ると成功）。期限の前は成功、後は 404。古いリンクは 404（新しい要求で使用済みにされる） |
| ST-F024-11 | F-024／DS-DEC-73 | 正常 | ゲストでカートに商品を入れてからログインする。ログアウトし、別のブラウザで同じ会員にログインする | ログイン直後も同じブラウザのカートの中身は変わらない（`cart_token` は変わらない）。別のブラウザのカートは空（引き継ぎは P3。F-010） |
| ST-F024-12 | F-024／DS-DEC-86 | 正常 | 未ログイン、ログイン中、`sid` だけが残って失効した状態で、ヘッダーのアイコンと遷移先を見る | 未ログインは `ログイン`→`/login`、ログイン中は `マイページ`→`/mypage`。失効した `sid` ではアイコンは「マイページ」のままで、押すと `/login?next=/mypage` に移る |

#### F-017 注文履歴・状況確認

| ID | 対象 F／DS | 区分 | 観点・手順 | 期待結果 |
| --- | --- | --- | --- | --- |
| ST-F017-01 | F-017／DS-API-024 | 正常 | 会員が配送 1 件・店舗受け取り 1 件を注文し、`/mypage` を開く | 新しい注文が先頭。各行に注文日（JST）、注文番号、状態名、先頭の商品名、受け取り方法、合計が出る。金額の通貨記号は `¥`（U+00A5）で、全角 `￥` でない |
| ST-F017-02 | F-017／DS-API-024 | 正常 | 注文が 0 件の会員（`demo-member4`）で `/mypage` を開く | 200 の空配列。「まだご注文がありません」とホームへのリンクが出る |
| ST-F017-03 | F-017／DS-API-024 | 境界 | 同じ会員の注文を 10 件、11 件にして `/mypage` と `/mypage?page=2` を開く。`per_page=50`、`51`、`page=0` を API へ送る | 10 件のときは 1 ページに 10 件で「次へ」なし。11 件のときは 1 ページ目に 10 件・2 ページ目に 1 件。`per_page=51`・`page=0` は 400 |
| ST-F017-04 | F-017／DS-API-024a | 正常 | 履歴から注文詳細を開く（配送・店舗受け取りの 2 種類） | 明細（商品名・色・サイズ・単価 × 数量）、小計・送料・合計・うち消費税、状態と進捗バーが出る。店舗受け取りは店舗名・住所・受け取りコード、配送はお届け先が出る |
| ST-F017-05 | F-017／DS-API-024a・REQ-NFR-07 | 異常 | 会員 A でログインし、会員 B の注文番号、ゲスト注文の注文番号、存在しない番号、形が不正な番号で `/mypage/orders/<番号>` を開く | いずれも同じ 404 ページ（区別できない）。会員 B の注文の内容は一切出ない |
| ST-F017-06 | F-017／DS-DEC-77 | 正常 | ゲストで注文した後、同じメールで会員登録・ログインして `/mypage` を開く | ゲスト時代の注文は履歴に出ない（後付けの紐づけはしない）。注文照会（番号＋メール）では引き続き見られる |
| ST-F017-07 | F-017／DS-PRC-024a | 正常 | 配送と店舗受け取りの注文の状態を DB で `accepted`→`preparing`→`shipped`→`delivered` と変え、各段階の詳細を開く | 状態名は設計の 4 表のとおり（配送：受付済／出荷準備中／出荷済（配送中）／配達完了、店舗：受付済／店舗へ準備中／店舗に到着（受け取り可能）／受け渡し済）。進捗バーの完了段数が 1・2・3・4 と進む |
| ST-F017-08 | F-017／REQ-FR-508・DS-PRC-024a | 境界 | 店舗受け取りの注文の状態を `pending_payment`・`accepted`・`shipped`・`delivered`・`cancelled`・`pickup_expired` にして詳細の受け取りコードを見る。配送の注文の追跡番号を `shipped`・`delivered`・`preparing` で見る（追跡番号は DB に入れておく） | 受け取りコードは `accepted`・`preparing`・`shipped` のときだけ出て、それ以外は枠ごと出ない。追跡番号は `shipped`・`delivered` のときだけ出る |

#### F-013・F-014 店舗受け取り

| ID | 対象 F／DS | 区分 | 観点・手順 | 期待結果 |
| --- | --- | --- | --- | --- |
| ST-F013-03 | F-013／DS-SCR-005 | 正常 | 注文手続きで「店舗受け取り」を選ぶ。「配送」に戻す | 店舗受け取りでは郵便番号・都道府県・市区町村・番地・建物の欄が消え、受け取り店舗のセレクトが出る（選択肢に店名と住所）。配送に戻すと住所の欄が戻り、入力済みの値は残る |
| ST-F013-04 | F-013／DS-SCR-005 | 異常 | 店舗受け取りで店舗を選ばずに「確認画面へ」を押す。API へ存在しない店舗コード `no-such-store` で注文を送る | 画面では店舗欄が赤字になり、確認画面へ進めない。API は 409 `invalid_reference`（`field: "store_code"`）で注文は作られない |
| ST-F013-05 | F-013／DS-API-021・DS-PRC-021a | 境界 | 小計 4,980 円と 4,990 円のカートで、配送と店舗受け取りの確認画面の送料を見る | 配送は 4,980 円で送料 550 円、4,990 円で 0 円（従来どおり）。店舗受け取りはどちらも 0 円。「うち消費税」は合計 × 10 ÷ 110 の円未満切り捨て |
| ST-F013-06 | F-013／DS-SCR-005 | 正常 | ログイン中に `/checkout` を開く。未ログインで開く | ログイン中は氏名とメールが会員情報で入り、「ログイン中」のカードが出る（ゲストのカードは出ない）。未ログインは「ログイン」のボタンが `/login?next=/checkout` に移り、ログイン後に `/checkout` へ戻る |
| ST-F014-07 | F-014／DS-PRC-014-3 | 正常 | 店舗受け取りで注文を確定する（ゲスト） | 201。応答に `receive_method:"store"`、`store`（店名・都道府県・住所）、`pickup_code`（8 文字）、`is_member_order:false`。DB：`orders.store_id` が店舗、`ship_postal_code`・`ship_address` が店舗の値、`shipping_fee` が 0、`total` が小計と等しい。`audit_logs` の `order.confirm` の `detail` に `receive_method:"store"` |
| ST-F014-08 | F-014／DS-DEC-79 | 境界 | 受け取りコードの形式と一意性：店舗受け取りの注文を 20 件作って `pickup_code` を見る | すべて `^[A-HJ-NP-Z2-9]{8}$`（I・O・0・1 を含まない）。重複なし。配送の注文の `pickup_code` は NULL |
| ST-F014-09 | F-014／DS-DEC-77 | 正常 | ログイン中に注文する。応答と DB を見る | `is_member_order:true`、`orders.member_id` が会員の ID。完了画面に「注文履歴で確認できます」 |
| ST-F014-10 | F-014／DS-DEC-77 | 異常 | `sid` を期限切れ、不明な値、スタッフ種別のセッションにして注文する | いずれも注文は成立し（201）、`member_id` は NULL、`is_member_order:false`。API は 401 を返さない |
| ST-F014-11 | F-014／DS-PRC-014-3 手順 7 | 正常 | 店舗受け取りの注文確認メール（outbox）の本文を見る。配送の注文のメールと比べる | 店舗受け取りは、受け取り方法として店舗名・住所と受け取りコードが書かれる。配送のメールは従来と同じ（受け取りコードの行がない）。どちらもクレジットカード番号を含まない |
| ST-F014-12 | F-014／DS-PRC-014-3・DS-API-022 | 異常 | 確認画面は店舗受け取り（送料 0）で、`display.shipping_fee` を 550 に改ざんして確定する。配送のカートで `display.shipping_fee` を 0 にして確定する | どちらも 409 `price_changed`（再計算後の金額を添える）。注文は作られない。`store` の注文で `ship_postal_code`・`ship_address` に任意の値を付けて送っても、DB には店舗の値が入る（要求の値は無視） |

#### F-007 再入荷通知・F-005 サイズ感

| ID | 対象 F／DS | 区分 | 観点・手順 | 期待結果 |
| --- | --- | --- | --- | --- |
| ST-F007-02 | F-007／DS-API-007 | 正常 | 在庫 0 のバリエーション（V-STOCK0）にダミーのメールで申し込む | 200 `{"status":"registered"}`。`restock_notifications` に 1 行（`notified_at` は NULL）。ログイン中なら `member_id` が入る |
| ST-F007-03 | F-007／DS-API-007 | 異常 | 在庫のあるバリエーション、非公開商品（P-UNPUB）のバリエーション、存在しない variant_id、不正なメールで申し込む | 在庫あり：409 `in_stock`。非公開・存在しない：404。不正なメール：400。いずれも行は増えない |
| ST-F007-04 | F-007／DS-DEC-80 | 境界 | 同じ（variant, email）で 2 回申し込む。同じメールで 10 件、11 件の異なるバリエーションに申し込む | 2 回目も 200 で行は 1 行のまま。10 件目まで 200、11 件目は 422 `limit_exceeded`（`field:"email"`、`limit:10`）。既に申し込んだ variant への再申込は上限に数えない（同じ行の更新のため） |
| ST-F007-05 | F-007／DS-PRC-007a | 正常 | 2 人が同じバリエーションに申し込み、在庫を 5 にして通知の関数（または CLI）を実行する | 2 通のメールが outbox に出て（宛先ごと）、2 行とも `notified_at` に時刻が入る。`audit_logs` に `restock.notified`（`detail` の件数が 2） |
| ST-F007-06 | F-007／DS-PRC-007a | 境界 | 通知後に同じ（variant, email）で再申込し、もう一度通知を実行する。在庫 0 のまま通知を実行する | 再申込で `notified_at` が NULL に戻り、通知を実行するとメールが 1 通できる。在庫 0 のまま実行したときは何も送らず、`notified_at` も変わらない |
| ST-F005-04 | F-005／DS-API-003・DS-PRC-003a | 正常 | 商品 1〜8 の詳細の `fit_summary` を見る | 設計仕様書 5.8 の表のとおり（商品 1：10／2／6／2、商品 2：6／0／5／1、商品 3：7／4／3／0、商品 4：3／1／1／1、商品 5：7／0／2／5、商品 6：3／3／0／0、商品 7：5／1／4／0、商品 8：1／0／1／0。書式は total／small／just／large）。`total` は 3 つの合計に等しい |
| ST-F005-05 | F-005／DS-SCR-003 | 境界 | レビューが 0 件の商品（商品 9）、1 件の商品（商品 8）の詳細を開く | 0 件は「サイズ感のレビューはまだありません」。1 件は「全 1 件」と件数が出て、棒が欠けずに描かれる |
| ST-F005-06 | F-005／DS-DEC-81 | 異常 | 商品 1 の未承認のレビュー 1 件（`approved=false`、`fit=large`）が集計に入らないことを確かめる。`approved` を真にすると変わることも確かめる | 未承認は数えない（large は 2 のまま）。承認すると large が 3、total が 11 になる（確認後に元へ戻す） |
| ST-F005-07 | F-005／REQ-NFR-09 | 正常 | 375px で商品 1 の詳細を開き、サイズ感の欄と、在庫切れ選択時の再入荷の欄を見る | 横スクロールなし。固定の購入バーに隠れない。件数の文字が読める |

### 3.2 非機能・セキュリティ

#### 非機能

| ID | 対象 | 区分 | 観点・手順 | 期待結果 |
| --- | --- | --- | --- | --- |
| ST-NFR-03 | DS-DEC-68 | 正常・境界 | 開発機で argon2id のハッシュ化と検証を各 20 回計測する（パラメータは time_cost=2・memory_cost=19456・parallelism=1）。同時に 10 件のログインを送り、プロセスのメモリの増加を見る | 1 回あたりの中央値が 10 ms 以上 300 ms 以下（下限は設定の取り違え、上限は F1 の CPU 時間の見積もりのため）。10 件の同時ログインでもすべて成功し、同時のハッシュ計算は 2 本までに抑えられる（メモリの増加が 19 MiB × 2 に収まる）。結果は検収記録に残し、公開環境（F1）での計測は P2-d で行う |
| ST-NFR-04 | REQ-NFR-09 | 正常 | 画面幅 375px・768px・1280px で、`/login`・`/register`・`/password-reset`・`/mypage`・`/mypage/orders/<番号>`・`/checkout`（店舗受け取り選択時）を表示する | レイアウトの崩れ・横スクロールなし。フォームの入力欄とボタンが 44px 以上。注意書き（デモ）が折り返して読める |

#### セキュリティ（ST-SEC-36〜59）

設計仕様書 7 章の対策に対応する。区分と手順は本編 3.3 の前提（CSRF トークンを付ける、回数制限は窓を空けて始める）に従う。ログイン系は IP 単位の制限（15 分に 30 回失敗）に当たらないよう、メールを替えながら 29 回以内にとどめるか、`login_attempts` を削除して始める。

| ID | 対象 | 区分 | 観点・手順 | 期待結果 |
| --- | --- | --- | --- | --- |
| ST-SEC-36 | 7 章 E-03・DS-DEC-68 | 正常 | 登録後に `members.password_hash` を確認する。`password_hash` に平文・SHA-256・bcrypt が使われていないこと、同じパスワードで 2 人登録してハッシュが異なること | `$argon2id$v=19$m=19456,t=2,p=1$…` の形式。2 人のハッシュは異なる（ソルトが別）。DB・ログ・outbox のどこにも平文のパスワードが無い |
| ST-SEC-37 | B-03・DS-DEC-71 | 異常 | 登録済みのメール（誤パスワード）と未登録のメールでログインし、ステータス・本文・ヘッダーを比べる | どちらも 401 `{"code":"invalid_credentials"}` で本文が一字一句同じ。`Set-Cookie`・`Retry-After` などのヘッダーにも差がない |
| ST-SEC-38 | B-03・DS-DEC-71 | 境界 | ST-SEC-37 の 2 条件で、各 10 回の応答時間を測り、中央値を比べる（IP 制限に達しないよう `login_attempts` を適宜削除する） | 中央値の差が 25 ms 以内（登録済みの誤パスワードも未登録も argon2id の検証 1 回分をかけるため）。差が大きい場合は不合格とし、ダミー検証が呼ばれているかを UT-AUTH-11 で調べる |
| ST-SEC-39 | B-03・DS-DEC-71 | 異常 | 登録済みと未登録のメールで、会員登録とパスワード再設定の要求を送り、応答を比べる | 登録は 202 `{"status":"accepted"}`、再設定の要求は 200 `{"status":"accepted"}` で、登録済み・未登録の本文とヘッダーが同じ。中央値の差が 25 ms 以内（メールは後処理で送るため） |
| ST-SEC-40 | B-04・DS-DEC-70 | 境界 | 同じメールで誤パスワードを 4 回、5 回送り、6 回目に正しいパスワードを送る。登録していないメールでも同じ手順をする | 5 回目まで 401。6 回目は正しいパスワードでも 403 `account_locked`。未登録のメールでも 6 回目から 403（登録の有無が分からない）。ロックのときは `Retry-After` 以外に残り時間・回数を返さない |
| ST-SEC-41 | B-04・DS-DEC-70 | 境界 | 同じ IP から、31 個の異なるメールに誤パスワードを 1 回ずつ送る。続けて 32 個目に正しい会員のパスワードを送る | 30 回目まで 401、31 回目以降は 429 `rate_limited`（`Retry-After: 900`）。IP が制限に達している間は、正しいパスワードでも 429。`X-Forwarded-For` を毎回変えても枠を回避できない（`TRUSTED_PROXY_HOPS` の設定どおり） |
| ST-SEC-42 | B-04・DS-DEC-70 | 境界 | ロック中の `login_attempts.at` を 14 分 59 秒前、15 分 1 秒前に書き換えて、正しいパスワードでログインする。ロックされる前に 4 回失敗した後に成功し、その後に再び 4 回失敗する | 14 分 59 秒前はロックのまま（403）、15 分 1 秒前は成功する。成功した時点で失敗行が消え、その後の 4 回の失敗ではロックされない（成功で数え直す） |
| ST-SEC-43 | B-06・DS-DEC-72 | 異常 | ログイン前に `sid` Cookie へ攻撃者が選んだ値（43 文字の任意文字列）を入れてからログインする | ログイン後の `sid` は新しい値で、攻撃者が選んだ値は採用されない。攻撃者の値で `GET /mypage` を開くと `/login` に移る。`X-Session-Token` として古い値を渡した場合、その行があれば消える |
| ST-SEC-44 | B-01・DS-DEC-72 | 正常 | ログイン応答の `Set-Cookie` の `sid`、ブラウザの `document.cookie`、応答本文を確認する | `sid` は `HttpOnly`・`SameSite=Lax`・`Path=/`・`Max-Age=86400`（`APP_ENV=production` の起動では `Secure` も付く。ユニットテストで確認）。`document.cookie` に `sid` が出ない。応答本文に `session_token` が無い。`csrf_token` はログイン前と値が異なる（発行し直し） |
| ST-SEC-45 | J-04・DS-DEC-72 | 異常・境界 | ログアウト後に旧 `sid` で `GET /api/v1/me`（FastAPI を内部トークンつきで直接）と `/mypage` を呼ぶ。`sessions.expires_at` を過去にして同じことをする。同じ会員で 11 回ログインする | どれも 401（画面は `/login` へ）。11 回目のログインで、最も古いセッションが消え、有効なセッションは 10 件以内 |
| ST-SEC-46 | C-03・DS-DEC-85 | 異常 | 認証系の 6 本と `POST /api/restock-notifications` を、CSRF トークンなし、不一致、`Origin: https://evil.example` で送る | すべて 403 `forbidden` で、FastAPI に届かない。ログアウトを `GET` で呼ぶと 405（GET の窓口が無い） |
| ST-SEC-47 | A-01・DS-API-024a | 異常 | 会員 A の `sid` で、会員 B の注文番号、ゲスト注文の番号の `GET /api/v1/me/orders/<番号>` を内部トークンつきで呼び、存在しない番号の応答と比べる | すべて 404 `{"code":"not_found"}` で本文が同一。会員 A の一覧（`/me/orders`）に B の注文・ゲスト注文は含まれない |
| ST-SEC-48 | A-01・DS-DEC-79 | 異常 | 店舗受け取りの注文の受け取りコードが、他人に渡らないことを確かめる。ゲスト照会で、番号は正しくメールが違う場合に応答を見る。会員 B の `sid` で A の店舗注文の詳細を開く | 照会は 404 でコードを含まない。B の詳細は 404。`pickup_code` は注文確定の応答、本人の詳細、番号＋メールの照会の 3 経路以外に出ない（注文履歴の一覧にも出ない） |
| ST-SEC-49 | A-03・DS-DEC-77 | 異常 | 会員登録に `role`・`is_admin`・`email_verified_at`・`id`・`anonymized_at` を付けて送る。`POST /orders` に `member_id`・`status`・`pickup_code`・`store_id` を付けて、ゲストで送る。`POST /restock-notifications` に `member_id`・`notified_at` を付けて送る | 余計な項目は無視される（400 でも成功でもよいが、値は反映されない）。作られた会員の `email_verified_at` は NULL。注文の `member_id` は NULL、`pickup_code` はサーバーが作った値、`store_id` は `store_code` から決まった値。申込の `member_id` はセッションから、`notified_at` は NULL |
| ST-SEC-50 | M-01・DS-DEC-75 | 異常・境界 | 再設定のトークンについて、①使用済みの再利用 ②期限（1 時間）の前後 ③同じ会員の新しい要求で古いトークンが無効になること ④確定後に旧セッションが失効すること ⑤ログと outbox ファイル名にトークンが出ないこと ⑥再設定要求時の `Host` ヘッダを `evil.example` にしてもメールのリンクが `PUBLIC_WEB_BASE_URL` のままであること を確かめる | ①②③④は ST-F024-09・10 と AT-19 のとおり。⑤アプリのログに `token=` の値が無く、outbox のファイル名は `<種別>-<日時>-<乱数>.txt`（メール・トークンを含まない）。⑥リンクのホストは `PUBLIC_WEB_BASE_URL` の値 |
| ST-SEC-51 | M-01・DS-DEC-74 | 異常・境界 | メール確認のトークンについて、再利用、期限（24 時間）の前後、別の会員のトークンで確認できないことを確かめる | 再利用・期限切れは 404。確認される会員はトークンの持ち主だけ |
| ST-SEC-52 | C-04・DS-DEC-85 | 異常 | `/login?next=` に `//evil.example`、`/\evil.example`、`https://evil.example`、`javascript:alert(1)`、`/%2F%2Fevil.example`、`/products/12abc`、`/admin`、空文字、5000 文字の値を入れてログインする。`next=/checkout`・`/cart`・`/mypage`・`/products/12` でもログインする | 前者はすべてログイン後に `/mypage` へ移る（外部サイトへは移らない）。後者の 4 つはそのパスへ移る |
| ST-SEC-53 | F-05・DS-DEC-89 | 正常 | 登録・ログイン失敗・ロック・再設定・再入荷の各操作のあとに、アプリのログ、`audit_logs`、outbox のファイル名を調べる | パスワード・トークン・平文のメールがログと `audit_logs` と outbox のファイル名に無い（ログのメールは `t***@example.com` の形に隠す）。`audit_logs` の `detail` にメール・氏名・受け取りコードが無い。本番設定（`APP_ENV=production`）では outbox にファイルが作られず、ログに種別だけが出る |
| ST-SEC-54 | C-01・C-02 | 異常 | 会員登録の氏名と、再入荷のメール欄に `' OR 1=1 --`、`<script>alert(1)</script>`、`"><img src=x onerror=alert(1)>` を入れる。登録した氏名がマイページ、注文詳細に出る場面を確認する | SQL エラーが出ない。氏名は文字列として保存され、マイページと注文詳細の HTML ではエスケープされて表示される（スクリプトが動かない）。メール欄の不正値は 400 |
| ST-SEC-55 | A-07・DS-DEC-12 | 正常 | `/me`・`/me/orders`・`/me/orders/<番号>`・店舗一覧・商品詳細・再入荷の応答の全キーを調べる | 内部 ID（`id`・`member_id`・`order_id`・`store_id`）、`password_hash`、`token_hash`、生年月日、性別が無い。例外は `variant_id`（本編 7.5） |
| ST-SEC-56 | D-01〜D-03・DS-DEC-61 | 正常 | `/login`・`/register`・`/mypage`・`/mypage/orders/<番号>` の応答ヘッダーを確認する。`/mypage` を未ログインで開く | ST-SEC-30 のヘッダー（`nosniff`・`X-Frame-Options`・CSP・HSTS・`Referrer-Policy`・`Permissions-Policy`）が付く。ログイン後のページは `Cache-Control` が `no-store` を含み、共有キャッシュに残らない。未ログインの `/mypage` は 302 または 307 で `/login?next=/mypage`（Next.js 16 の `redirect` の既定は 307） |
| ST-SEC-57 | B-07・DS-DEC-88 | 異常・境界 | `DEMO_EMAIL_DOMAINS=example.com` で api を起動し、`@example.com`、`@sub.example.com`、`@example.org`、`@EXAMPLE.COM` のメールで、登録・再設定の要求・再入荷の申込を送る。未設定で起動して同じことをする | 設定ありでは `@example.com` と `@EXAMPLE.COM`（小文字化後に一致）が通り、`@sub.example.com`・`@example.org` は 422 `unsupported_value`（`field:"email"`）。サブドメインは一致とみなさない。未設定では制限なし |
| ST-SEC-58 | B-04・DS-DEC-84 | 境界 | 同じ IP から会員登録を 10 回、11 回、再入荷の申込を 20 回、21 回、再設定の要求を 5 回、6 回（メール替え）、同じメールで再設定の要求を 3 回、4 回送る | 10 回目・20 回目・5 回目・3 回目まで通り、次の 1 回が 429 `rate_limited`（`Retry-After` つき）。窓（1 時間）が過ぎると通る。登録の 11 回目は、メールが新規でも既登録でも同じ 429 |
| ST-SEC-59 | A-02・DS-DEC-72 | 異常 | `subject_type=staff` の `sessions` 行（管理者は P2-c で作るため、テストでは行だけを直接作る）のトークンで、`GET /me`・`GET /me/orders`・`POST /orders` を呼ぶ | `/me` と `/me/orders` は 401。`POST /orders` はゲスト扱いで成立し、`member_id` は NULL（スタッフのセッションは会員として通らない） |

## 4. 結合テスト（IT）追加分

FastAPI と MySQL を実際に起動し、pytest から HTTP で呼ぶ（本編 4 章と同じ）。ID は `IT-<DS-API または DS-PRC の番号>-<連番>`。内部トークンを付けて FastAPI を直接呼ぶものは「FastAPI」、BFF（Next.js の Route Handler）を通すものは IT-BFF とする。メールは記録用アダプタで読む（1 章 #3）。

### 4.1 認証（IT-030〜036）

| ID | 対象 DS | 区分 | 前提・入力 | 期待結果 |
| --- | --- | --- | --- | --- |
| IT-030-01 | DS-API-030 | 正常 | 正しい入力で `POST /auth/register` | 202 `{"status":"accepted"}`。`members` 1 行、`email_tokens`（verify_email）1 行、記録用アダプタに確認メール 1 通（リンクは `PUBLIC_WEB_BASE_URL` から始まる）。`audit_logs` に `member.register` |
| IT-030-02 | DS-API-030・DS-DEC-71 | 正常 | 既登録のメール（同じ・別のパスワード）で登録する | 202 で本文が IT-030-01 と同一。`members`・`email_tokens` は増えない。記録用アダプタに「すでに登録されています」のメールが 1 通 |
| IT-030-03 | DS-API-030 | 異常 | メール形式不正（`abc`・`a@`・空）、パスワード空、氏名が空・全角空白のみ・51 文字、生年月日が明日・1899-12-31、gender が不正値 | 400 `validation_error`。`fields` に該当項目の名前と reason（`required`・`format`・`too_long`・`out_of_range`）。DB は変わらない |
| IT-030-04 | DS-API-030 | 境界 | パスワードが 7・8・128・129 文字（絵文字 1 字を含む 8 文字を含む） | 7 と 129 は 400、8 と 128 は 202。文字数は NFKC 正規化後のコードポイント数で数える |
| IT-030-05 | DS-API-030・DS-DEC-69 | 異常 | 禁止語（旧 20 語。大文字・全角を混ぜた表記を含む。236 語への拡張は IT-030-05b・UT-AUTH-06b）、正規化後にメールアドレスと同一のパスワード、同一文字 8 文字（`aaaaaaaa`・`ああああああああ`）。同じ値を**既登録のメール**でも送る | 422 `weak_password`（`field:"password"`）。既登録のメールでも同じ 422（検査が DB に依存しない） |
| IT-030-05b | DS-API-030・DS-DEC-69（G-17） | 異常 | 禁止語の前後に数字・記号を足したもの（`password2`・`Password123!`・`2024qwerty`・`P@ssw0rd!`）、連番（`bcdefghi`・`98765432`）、短い単位の繰り返し（`abababab`）、キーボード配列（`asdfghjk`）、メールの `@` より前の部分を含むもの。メール `weakpw@example.com` に対して送る | 422 `weak_password`（`field:"password"`）。会員は増えない |
| IT-030-06 | DS-API-030・DS-DEC-69 | 境界 | メールを全角（`ＤＥＭＯ＠ＥＸＡＭＰＬＥ．ＣＯＭ`）、前後に空白、大文字で送る。ゼロ幅スペース（U+200B）を含むメールを送る。全角英数のパスワードで登録し、半角でログインする | 全角・前後空白・大文字は `demo@example.com` として保存される。ゼロ幅スペースを含むメールは 400。全角パスワードで登録した会員は半角の同じ文字列でログインできる |
| IT-030-07 | DS-API-030・A-03 | 異常 | 本文に `id`・`role`・`is_admin`・`email_verified_at`・`anonymized_at` を足して登録する | 余計な項目は無視される。作られた会員の `email_verified_at` は NULL |
| IT-030-08 | DS-DEC-71・5.6 | 異常 | **同じメールで 10 並列**に登録する（asyncio.gather。1 章 #2 の条件） | 全応答が 202 で本文が同一。`members` は 1 行、`email_tokens` は 1 行、500 とタイムアウトなし。UNIQUE 違反（1062）が「既登録」の枝に入ったことをログで確認する |
| IT-030-09 | DS-API-030・DS-DEC-88 | 異常・境界 | `DEMO_EMAIL_DOMAINS=example.com` で起動し、`@example.com`・`@EXAMPLE.COM`・`@sub.example.com`・`@example.org` で登録する。環境変数なしで起動して同じことをする | 設定ありは前の 2 つが 202、後の 2 つは 422 `unsupported_value`（`field:"email"`）。設定なしはすべて 202 |
| IT-031-01 | DS-API-031 | 正常 | 登録で作られたトークン（記録用アダプタのリンクから取り出す）で `POST /auth/verify-email` | 200 `{"verified":true}`。`email_verified_at` が入り、`used_at` が入る。`audit_logs` に `member.email_verified` |
| IT-031-02 | DS-API-031 | 異常 | 使用済みのトークン、存在しない 43 文字、形が違う値（42 文字・記号入り）、別の会員のトークンの流用 | 使用済み・不存在は 404 `not_found`。形が違う値は 400。別会員のトークンで確認されるのは、そのトークンの持ち主だけ |
| IT-031-03 | DS-API-031 | 境界 | `expires_at` を現在の 1 秒後、1 秒前にして確認する | 1 秒後は 200、1 秒前は 404 |
| IT-032-01 | DS-API-032 | 正常 | seed の会員で正しくログイン | 200。`session_token`（43 文字）と `member`。`sessions` に 1 行で `token_hash` は SHA-256（16 進 64 桁）、`expires_at` は約 24 時間後（±5 秒）、`subject_type=member`。`audit_logs` に `member.login`。`members.email_verified_at` は変わらない |
| IT-032-02 | DS-API-032・DS-DEC-71 | 異常 | 登録済みの会員に誤パスワード、未登録のメールで、それぞれログイン | どちらも 401 `invalid_credentials` で本文が同一。`login_attempts` に失敗が 1 行ずつ。`identifier` は SHA-256 の 16 進で、平文のメールが DB に無い |
| IT-032-03 | DS-API-032・DS-DEC-70 | 境界 | 誤パスワード 4 回の後に正しい値 → 成功。別の会員で誤パスワード 5 回の後に 6 回目 | 4 回の後の成功は 200。5 回目までは 401、6 回目は 403 `account_locked`。ロック通知メールが 5 回目の失敗の時点で 1 通だけ送られる（記録用アダプタ） |
| IT-032-04 | DS-API-032・DS-DEC-71 | 異常 | 未登録のメールで誤パスワード 5 回の後に 6 回目 | 6 回目は 403 `account_locked`（会員の有無が分からない）。ロック通知メールは送られない（会員がいないため）が、応答には差が出ない |
| IT-032-05 | DS-API-032・DS-DEC-70 | 境界 | ロックされた会員の `login_attempts.at` を 14 分 59 秒前、15 分 1 秒前に書き換えて、正しいパスワードで試す | 14 分 59 秒前は 403、15 分 1 秒前は 200 |
| IT-032-06 | DS-API-032・DS-DEC-70 | 境界 | 同じ `X-Forwarded-For` の IP から、30 個の異なるメールに失敗を記録し、31 個目と、正しい会員の正しいパスワードを送る | 30 回目までは 401、31 回目以降は 429 `rate_limited`（`Retry-After: 900`）。正しい会員の正しいパスワードも 429。別の IP からは通る |
| IT-032-07 | DS-API-032・DS-DEC-72 | 正常 | ログインして得た旧トークンを `X-Session-Token` に付けて、もう一度ログインする | 旧トークンの `sessions` 行が消え、新しい行ができる（トークンもハッシュも別）。旧トークンで `GET /me` は 401 |
| IT-032-08 | DS-API-032・DS-DEC-68 | 正常 | time_cost=1 など現行と違うパラメータで作った argon2id ハッシュで保存された会員でログインする | 200。`password_hash` が現行のパラメータ（`m=19456,t=2,p=1`）のハッシュに更新される。同じパスワードでもう一度ログインできる |
| IT-032-09 | DS-API-032・DS-DEC-72 | 境界 | 同じ会員で 9 回、10 回、11 回ログインする（旧トークンは渡さない） | 有効なセッションは 9 件、10 件、10 件。11 回目では最も古い行だけが消える |
| IT-032-10 | DS-API-032・DS-DEC-70 | 正常 | 失敗 3 回の後に成功する | 失敗行が 0 件になり、成功が 1 件記録される。その後の失敗は 1 から数え直す |
| IT-032-11 | DS-API-032 | 異常 | ロック中に正しいパスワードで試す | 403 `account_locked`。`sessions` は増えない |
| IT-032-12 | DS-API-032 | 異常 | 本文の必須欠落、パスワード 129 文字、匿名化済み（`anonymized_at` あり）の会員 | 欠落・129 文字は 400。匿名化済みは 401 `invalid_credentials`（会員がいない場合と同じ） |
| IT-032-13 | DS-API-032・5.6 | 異常 | **同じ会員で、正しいパスワード 3 本と誤パスワード 2 本を同時に送る波を 3 回**（1 波 5 本。波ごとに `login_attempts` を空にする。1 章 #2）。G-16 以降、同じメールで同時に検証まで進めるのは上限の 5 本までなので、旧版（正しい 10 本と誤り 3 本）から変えた | 500・タイムアウトなし。各波で正しい 3 本はすべて 200、誤パスワードの 2 本は 401。有効な `sessions` は 10 件以内（3 波で 9 件）。デッドロック（1213）が起きた場合は再試行で成功する（再試行の回数をログから数えて記録する） |
| IT-032-17 | DS-API-032・DS-PRC-032 手順 3・DS-DEC-70（G-16） | 境界・異常 | ①同じメールへ誤パスワードを 12 本同時に送る（IP は別々）。②同じ IP から別々のメール 40 本へ同時に誤パスワードを送る。③上限ちょうど（同じメールに 5 本、同じ IP から別々のメール 30 本）を同時に送り、続けて 1 本送る。④ロック中に誤パスワードを 3 回送る。別の会員で成功する（IT-032-14〜16 は実装側で別の試験に使われている番号） | 同時性が成立している（`claim_login_attempt` の同時処理中の最大が 2 以上）。①照合まで進むのは 5 本以下で、401 は照合まで進んだ数と同じ、残りは 403 `account_locked`。失敗行は照合まで進んだ数だけ残る。ロック通知メールは 1 通以下。②照合は 30 本以下で、401 と一致し、残りは 429（`Retry-After: 900`）。③すべて照合まで進んで 401。続く 1 本は 403（メール）または 429（IP）で、ロック後は照合しない。④拒否分の行は残らない（失敗行は 5 件のまま）。成功した会員は成功の行が 1 件だけで、失敗の行は残らない |
| IT-032-18 | DS-PRC-032 手順 10・DS-DEC-70（G-19） | 正常 | 誤パスワードで 401 を 5 回、ロック後の 403、同じ IP から 31 通りのメールを送って 429 を起こし、拒否ログ（`request_rejected`）を読む | 401・403・429 のすべてで `subject` が付き、正規化したメールの SHA-256 の先頭 12 桁と一致する。メールと SHA-256 の全桁はログに無い |
| IT-033-01 | DS-API-033 | 正常 | ログインして得たトークンで `POST /auth/logout` | 204。`sessions` の当該行が消える。続けて `GET /me` は 401 |
| IT-033-02 | DS-API-033 | 異常 | `X-Session-Token` なし、不明な値、形が違う値でログアウトする | すべて 204（冪等）。他のセッションは消えない |
| IT-033-03 | DS-API-033 | 境界 | 同じ会員の有効なセッションが 2 つある状態で、片方をログアウトする | もう一方は有効のまま（`GET /me` が 200） |
| IT-034-01 | DS-API-034 | 正常 | 登録済みの会員のメールで要求する | 200 `{"status":"accepted"}`。`email_tokens`（reset_password、有効期限は約 1 時間）が 1 行。再設定メールが 1 通で、リンクは `PUBLIC_WEB_BASE_URL` 起点。同じ会員の未使用の再設定トークンは使用済みになる |
| IT-034-02 | DS-API-034・DS-DEC-71 | 正常 | 未登録のメールで要求する | 200 で本文が IT-034-01 と同一。`email_tokens` は増えず、メールも送られない |
| IT-034-03 | DS-API-034 | 異常 | メール形式不正。`DEMO_EMAIL_DOMAINS` 外のメール | 400 `validation_error`／422 `unsupported_value` |
| IT-034-04 | DS-API-034・DS-DEC-84 | 境界 | 同じ IP から 5 回、6 回（メールを替える）。同じメールで 3 回、4 回 | 5 回目・3 回目まで 200、次の 1 回が 429 `rate_limited` |
| IT-034-06 | DS-API-034・DS-PRC-032 手順 10（G-19） | 異常 | 同じメールで再設定の要求を 3 回（200）。4 回目は別の IP から送る。その拒否ログを読む | 4 回目は 429 `rate_limited` で、ログに `subject`（メールの SHA-256 の先頭 12 桁）が付く。IP 単位の 429 には `subject` が付かない（キーが IP のため）。メールはログに無い（IT-034-05 は実装側で別の試験に使われている番号） |
| IT-035-01 | DS-API-035 | 正常 | 有効なトークンと新しいパスワードで確定する | 200。ハッシュが更新され、`used_at` が入り、当該会員の `sessions` が 0 行、失敗行が 0 行。`audit_logs` に `member.password_reset`。旧パスワードでのログインは 401、新パスワードは 200 |
| IT-035-02 | DS-API-035 | 異常 | 使用済み、存在しない 43 文字、形が違う値、別目的（verify_email）のトークン | 使用済み・不存在・別目的は 404、形が違う値は 400。パスワードは変わらない |
| IT-035-03 | DS-API-035 | 異常 | 弱いパスワード（`password123`）で確定する。続けて同じトークンで正しいパスワードを送る | 前者は 422 `weak_password` でトークンは未使用のまま。後者は 200 |
| IT-035-03b | DS-API-035・DS-DEC-69（G-17） | 異常 | 有効なトークンで、`password2`・`Password123!`・`87654321`・メールの `@` より前の部分を含むパスワードを順に送って確定する | すべて 422 `weak_password` で、トークンは消費されない（その後の正しいパスワードで確定できる） |
| IT-035-04 | DS-API-035 | 境界 | `expires_at` を 1 秒後、1 秒前にして確定する | 1 秒後は 200、1 秒前は 404 |
| IT-035-05 | DS-API-035・DS-DEC-75 | 境界 | 同じ会員で要求を 2 回行い、1 回目のトークンで確定する | 1 回目のトークンは 404（2 回目の要求で使用済みになった）。2 回目のトークンは 200 |
| IT-035-06 | DS-API-035・5.6 | 異常 | **同じトークンで 10 並列**に確定する（1 章 #2） | 1 本が 200、残りは 404。500・タイムアウトなし。`sessions` は 0 行、ハッシュの更新は 1 回 |
| IT-036-01 | DS-API-036 | 正常 | ログインで得たトークンで `GET /me` | 200 `{"name","email","email_verified","personalize_opt_in"}` のみ。seed の `demo-member3` は `email_verified:false` |
| IT-036-02 | DS-API-036・DS-PRC-035 | 異常 | ヘッダーなし、形が違う値、不明な値、`expires_at` が過去のセッション | すべて 401 `unauthorized` |
| IT-036-03 | DS-API-036・DS-PRC-035 | 異常 | 匿名化済みの会員のセッション、`subject_type=staff` のセッションで `GET /me` | どちらも 401 |

### 4.2 注文履歴・店舗・注文確定の変更（IT-024・026・021・014・023）

| ID | 対象 DS | 区分 | 前提・入力 | 期待結果 |
| --- | --- | --- | --- | --- |
| IT-024-01 | DS-API-024 | 正常 | 会員 A が配送 1 件・店舗 1 件を注文し、`GET /me/orders` | 200。2 件が新しい順。`item_count`（数量の合計）・`first_item_name`・`status_label`・`receive_method` が正しい。`total` は 2、`has_more` は偽 |
| IT-024-02 | DS-API-024 | 正常 | 注文のない会員で呼ぶ | 200 `{"items":[],"total":0,"has_more":false}` |
| IT-024-03 | DS-API-024 | 境界 | 注文 11 件の会員で `page=1`・`page=2`・`page=3`、`per_page=1`・`50`・`51`・`0`、`page=0` | page=1 は 10 件で `has_more` 真、page=2 は 1 件、page=3 は空配列で 200。`per_page=1`・`50` は成功、`51`・`0`、`page=0` は 400 |
| IT-024-04 | DS-API-024 | 異常 | `X-Session-Token` なし・不正 | 401 `unauthorized` |
| IT-024-05 | DS-API-024・DS-DEC-77 | 異常 | 会員 A で呼ぶ。DB には会員 B の注文とゲスト注文（`member_id` NULL、A と同じ `guest_email`）がある | A の一覧に B の注文もゲスト注文も出ない |
| IT-024-06 | DS-API-024・7.5 | 正常 | 応答の全キーを走査する | `id`・`member_id`・`order_id`・`store_id`・`cart_id`・`idempotency_key` が無い |
| IT-024a-01 | DS-API-024a | 正常 | 会員 A の配送注文の詳細を取る | 200。`OrderOut` の全項目（明細・金額・お届け先・`ordered_at`）が注文時の値。商品価格を後から変更しても金額は変わらない（確定時単価） |
| IT-024a-02 | DS-API-024a | 異常 | 会員 B の注文番号、ゲスト注文の番号、存在しない正しい形の番号、形が不正な文字列 | すべて 404 `not_found` で本文が同一 |
| IT-024a-03 | DS-API-024a・DS-PRC-024a | 境界 | 店舗注文の状態を `pending_payment`・`accepted`・`preparing`・`shipped`・`delivered`・`pickup_expired`・`cancelled`・`payment_failed` に変えて詳細を取る | `pickup_code` は `accepted`・`preparing`・`shipped` のときだけ 8 文字、他は null |
| IT-024a-04 | DS-API-024a・DS-PRC-024a | 境界 | 配送注文に追跡番号を入れ、状態を `preparing`・`shipped`・`delivered` にして詳細を取る | `tracking_number` は `shipped`・`delivered` のときだけ値、`preparing` は null |
| IT-024a-05 | DS-API-024a | 正常 | 店舗注文の詳細の `store` | `{"name","prefecture","address"}` の 3 つだけ（郵便番号・店舗 ID・コードなし）。配送注文は `store` が null |
| IT-026-01 | DS-API-026 | 正常 | `GET /stores` | 200。seed の 3 店舗が `sort_order` 順。各要素のキーは `code`・`name`・`prefecture`・`address` のみ |
| IT-026-02 | DS-API-026 | 境界 | 1 店舗の `pickup_enabled` を偽にして呼ぶ。全店舗を偽にして呼ぶ | 偽の店舗は一覧に出ない。全店舗が偽でも 200 の空配列 |
| IT-003-03 | DS-API-003・DS-PRC-003a | 正常 | 商品 1〜8 の詳細を取る | `fit_summary` が設計仕様書 5.8 の表と一致する。`total` は 3 つの合計。商品 1 の未承認の 1 行は数えない |
| IT-003-04 | DS-API-003 | 境界 | レビューのない商品 9、1 件だけの商品 8 | 商品 9 は `{"total":0,"small":0,"just":0,"large":0}`（キーは必ず出る）。商品 8 は total 1 |
| IT-003-05 | DS-API-003 | 異常 | 非公開商品（P-UNPUB）、存在しない商品。`fit` が NULL のレビューを足した商品 | 前 2 つは従来どおり 404。`fit` が NULL のレビューは `total` に入らない |
| IT-021-03 | DS-API-021・DS-PRC-021a | 正常 | 小計 1,490 円・4,980 円・4,990 円のカートで `receive_method=store` の prepare | `shipping_fee` は 0、`total` は小計に等しい、`receive_method` は `store` |
| IT-021-04 | DS-API-021 | 境界 | 本文なし、`{"receive_method":"delivery"}`、`{}` の prepare（小計 4,980 円・4,990 円） | 従来どおり（4,980 円は送料 550、4,990 円は 0）。応答の `receive_method` は `delivery` |
| IT-021-05 | DS-API-021 | 異常 | `receive_method` が `pickup`・空文字・数値 | 400 `validation_error`（reason `format`） |
| IT-014-10 | DS-API-022・DS-PRC-014-3 | 正常 | 店舗受け取り（`store_code=demo-tokyo`、`ship_postal_code`・`ship_address` なし）で注文する | 201。`orders.store_id` が店舗、`ship_postal_code`・`ship_address` が店舗の値、`shipping_fee` 0、`pickup_code` が 8 文字、`status=accepted`。応答の `store`・`pickup_code`・`is_member_order:false`。`order_items`・`payments`・`audit_logs` が 1 件ずつ。在庫が数量分減る |
| IT-014-11 | DS-API-022 | 異常 | 存在しない `store_code`、`pickup_enabled` が偽の店舗 | 409 `invalid_reference`（`field:"store_code"`）。`orders` に行が残らず、在庫は不変、カートは `active` のまま |
| IT-014-12 | DS-API-022 | 異常 | `receive_method=store` で `store_code` を付けない／空文字／大文字／33 文字／全角 | 400 `validation_error`（欠落は `required`、その他は `format`）。注文は作られない |
| IT-014-13 | DS-API-022 | 異常 | `receive_method=delivery` で `store_code` を付ける | 422 `unsupported_value`（`field:"store_code"`）。未知の `receive_method` も 422 |
| IT-014-14 | DS-API-022・DS-DEC-77 | 正常 | 有効な `X-Session-Token` つきで配送注文する | 201。`orders.member_id` が会員の ID、`is_member_order:true`。`GET /me/orders` にその注文が出る |
| IT-014-15 | DS-API-022・DS-DEC-77 | 異常 | `X-Session-Token` が不明、期限切れ、`subject_type=staff`、形が不正 | いずれも 201 でゲスト扱い（`member_id` NULL、`is_member_order:false`）。401 を返さない |
| IT-014-16 | DS-PRC-014-3 | 異常 | `pickup_code` の生成関数を差し替え、1 回目に既存の注文と同じ値を返させる | 1 回だけ再生成して注文が成立する（2 回目も衝突するなら 500 `internal_error`。UT-PICK-02 と対） |
| IT-014-17 | DS-API-022・DS-PRC-014-3 | 正常 | 店舗受け取りの注文を同じ冪等キーで再送する | 200 で、注文番号と `pickup_code` が 1 回目と同一。`orders` は 1 行 |
| IT-014-18 | DS-API-022 | 異常 | `PAYMENT_STUB_RESULT=ng` で店舗受け取りの注文を確定する | 409 `payment_failed`。`orders` は `payment_failed` で残り、在庫は戻り、カートは `active`。その注文を会員の詳細で見ると `pickup_code` は null |
| IT-014-19 | DS-PRC-014-3・5.6 | 異常 | **同じ会員の別カート 2 つ**から、冪等キーを替えて同時に注文する（1 章 #2。10 回反復） | 2 本とも 201。デッドロックによる 500 なし（1213 は再試行で成功してよい。再試行回数を記録）。`orders` は 2 行で、どちらも同じ `member_id` |
| IT-023-03 | DS-API-023 | 正常 | 店舗受け取りの注文を注文番号＋メールで照会する。メールを違えて照会する | 一致は 200 で `pickup_code` と `store` が返る。不一致は 404 で、コードを含まない |

### 4.3 再入荷通知（IT-007・007a）

| ID | 対象 DS | 区分 | 前提・入力 | 期待結果 |
| --- | --- | --- | --- | --- |
| IT-007-01 | DS-API-007 | 正常 | V-STOCK0 の `variant_id` とダミーのメールで申し込む | 200 `{"status":"registered"}`。`restock_notifications` に 1 行（`notified_at` NULL、`member_id` NULL）。メールは小文字化して保存 |
| IT-007-02 | DS-API-007 | 異常 | 在庫のある `variant_id` | 409 `in_stock`。行は増えない |
| IT-007-03 | DS-API-007 | 異常 | 非公開商品（P-UNPUB）の `variant_id`、存在しない `variant_id` | どちらも 404 `not_found` |
| IT-007-04 | DS-API-007 | 境界 | 同じ（variant, email）で 2 回申し込む。1 回通知済みにした後で再申込する | 2 回目も 200 で行は 1 行。通知済みの後の再申込で `notified_at` が NULL に戻る |
| IT-007-05 | DS-API-007 | 異常 | `variant_id` が 0・-1・9223372036854775808・文字列、メールが形式不正・255 文字以上 | 400 `validation_error`。行は増えない |
| IT-007-06 | DS-API-007・DS-DEC-84 | 境界 | 同じ IP から 20 回、21 回 | 20 回目まで 200、21 回目は 429 `rate_limited` |
| IT-007-07 | DS-API-007・DS-DEC-80 | 境界 | 同じメールで未通知の申込が 9 件、10 件の状態から、新しい variant に申し込む。既に申し込んだ variant への再申込もする | 9 件の状態からの申込は 200（10 件目）、10 件の状態からの新しい variant は 422 `limit_exceeded`（`limit:10`）。既存 variant への再申込は件数に数えず 200 |
| IT-007-08 | DS-API-007 | 正常 | 有効な `X-Session-Token` つきで申し込む。無効なトークンで申し込む | 前者は `member_id` が会員の ID、後者は NULL（申込は成立する） |
| IT-007-09 | DS-API-007・5.6 | 異常 | **同じ（variant, email）で 10 並列**に申し込む（1 章 #2） | 全応答が 200、`restock_notifications` は 1 行、500 なし |
| IT-007a-01 | DS-PRC-007a | 正常 | 3 人が申し込んだ V-STOCK0 の在庫を 5 にして `notify_restock` を呼ぶ | 記録用アダプタに 3 通（宛先ごと）。3 行とも `notified_at` が入る。`audit_logs` に `restock.notified`（件数 3）。メールに商品名・色・サイズ・`PUBLIC_WEB_BASE_URL` 起点の商品ページのリンク |
| IT-007a-02 | DS-PRC-007a・5.6 | 異常 | **`notify_restock` を 2 本同時に**呼ぶ（1 章 #2） | 送信の合計が 3 通（二重送信なし）。`notified_at` は 3 行とも入る |
| IT-007a-03 | DS-PRC-007a | 境界 | 在庫 0 のまま呼ぶ。申込が 0 件の variant で呼ぶ | どちらも送信 0 通で例外なし。`notified_at` は変わらない |
| IT-007a-04 | DS-PRC-007a | 異常 | 記録用アダプタが 1 件目の宛先で例外を出す | 残りの宛先には送信される。`audit_logs` に `restock.mail_failed`（宛先は含まない）。例外は呼び出し元に伝わらない |
| IT-007a-05 | DS-PRC-007a | 正常 | 通知済みの行に再申込し、在庫を一度 0 に戻してから再び正の値にして呼ぶ | 再度 1 通送られる |

### 4.4 スキーマ・BFF（IT-SCHEMA・IT-BFF）

IT-SCHEMA の 01〜08 は本編と 2026-10-04 追補に既にある。09 以降を足す。

| ID | 対象 | 区分 | 前提・入力 | 期待結果 |
| --- | --- | --- | --- | --- |
| IT-SCHEMA-09 | DS-TBL・5.1 | 正常 | `alembic upgrade head` 後の `information_schema` | 表は 21（P1 の 12 ＋ P2-a の 1 ＋ P2-b の 8）。P2-b の 8 表は `members`・`sessions`・`staff`・`stores`・`reviews`・`restock_notifications`・`login_attempts`・`email_tokens` |
| IT-SCHEMA-10 | 5.5 | 正常 | `alembic heads`、`alembic history` | head が 1 本。`ad00074244c2` → `p2b_auth_tables` → `p2b_orders_pickup_fk` の順（接尾辞は実装後のリビジョン ID に置き換えて確認） |
| IT-SCHEMA-11 | 5.5 | 正常 | P1 相当の注文・カートの行を入れたまま、`ad00074244c2` へ downgrade し、head へ upgrade し直す | 既存の行が失われない。downgrade で P2-b の 8 表と外部キー・UNIQUE・索引が消え、upgrade で戻る |
| IT-SCHEMA-12 | 5.2・5.3 | 異常 | 制約を直接 INSERT で確かめる：`members.email` 重複、`sessions.token_hash` 重複、`restock_notifications (variant_id, email)` 重複、`reviews.rating` が 0・6、`orders.member_id` が存在しない会員、`orders.store_id` が存在しない店舗、`orders.pickup_code` の重複と NULL の複数行 | 重複・範囲外・存在しない参照は拒否される。`pickup_code` の NULL は複数行入る |
| IT-SCHEMA-13 | 5.8 | 正常 | `seed` 後の件数 | `members` 5、`stores` 3、`reviews` 43（`approved` 真が 42）。商品 1 に未承認が 1 行。`seed --only-p2b` は各表が空のときだけ投入し、2 回目は何もしない |
| IT-BFF-030a | DS-API-032・4.7 | 正常 | BFF の `POST /api/auth/login`（`fetch` のモックで FastAPI の応答を返す）。成功応答に `session_token` を含める | ブラウザへの本文に `session_token` が無い。`Set-Cookie` に `sid`（`HttpOnly`・`SameSite=Lax`・`Path=/`・`Max-Age=86400`、production 設定では `Secure`）と新しい `csrf_token`。FastAPI へは `X-Forwarded-For` に利用者の IP が付き、利用者が送った `X-Forwarded-For` は転送されない |
| IT-BFF-030b | 4.0・DS-DEC-85 | 異常 | CSRF トークンなし、不一致、`Origin: https://evil.example` で `login`・`logout`・`register`・`password-reset/request`・`password-reset/confirm`・`verify-email` を呼ぶ | すべて 403 `forbidden`。FastAPI（モック）は呼ばれない |
| IT-BFF-030c | DS-API-033 | 正常 | `POST /api/auth/logout`（`sid` Cookie つき）。FastAPI が 204 を返す場合と、失敗を返す場合 | `X-Session-Token` に `sid` の値が載る。どちらでもブラウザへ `sid` の削除 Cookie（`Max-Age=0`）と新しい `csrf_token`。成功は 204 |
| IT-BFF-030d | DS-API-032 | 異常 | FastAPI が 401 `invalid_credentials`・403 `account_locked`・429（`Retry-After: 900`）・422・503 相当（接続不可）を返す | ステータスと `{code}` がそのまま透過される（許可した詳細キーのみ）。429 は `Retry-After` を透過。`Set-Cookie` に `sid` が出ない。接続不可は 503 `upstream_unavailable` |
| IT-BFF-030e | 4.0 | 異常 | 9000 バイトの本文を `login` に送る。`Content-Length` を付けない 9000 バイトの本文も送る | どちらも 413 `payload_too_large`。FastAPI は呼ばれない |
| IT-BFF-030f | 4.0 | 異常 | `login` の本文に `role`・`is_admin`・`session_token` を足して送る | FastAPI（モック）に渡る本文は `email`・`password` だけ |
| IT-BFF-031 | DS-API-030・031・034・035 | 正常・異常 | `register`・`verify-email`・`password-reset/request`・`password-reset/confirm` の本文の白リスト。余計な項目を足す。必須項目が文字列でない | 余計な項目は FastAPI に渡らない。型が違う項目は 400 `validation_error`（FastAPI を呼ばない）。成功応答の `cart_token`・`session_token` 相当の項目は本文から除かれる |
| IT-BFF-007 | DS-API-007 | 正常・異常 | `POST /api/restock-notifications`：有効な `sid` つき・なし、余計な項目、`variant_id` が文字列 | `sid` があれば `X-Session-Token` が付く。`variant_id` は整数だけ通す。余計な項目は落とす。CSRF なしは 403 |
| IT-BFF-021 | DS-API-021 | 正常・異常 | `POST /api/checkout/prepare` に `receive_method:"store"`、本文なし、`receive_method:"pickup"` | `store` はそのまま FastAPI に渡る。本文なしは従来どおり。`pickup` は 400（FastAPI を呼ばない） |
| IT-BFF-022 | DS-API-022 | 正常・異常 | `POST /api/orders` に `store_code` つき、`receive_method:"store"` で `ship_postal_code` なし。`sid` つき。`member_id` を足す | `store_code` が白リストを通る。店舗受け取りで住所の項目が無くても FastAPI へ取り次ぐ。`sid` があれば `X-Session-Token` が付く。`member_id` は落ちる |

## 5. 単体テスト（UT）追加分

### 5.1 FastAPI（pytest）

DB を要する関数は SQLite インメモリで実行する（本編 1.1）。MySQL 固有の挙動は IT で担保する。

| ID | 対象 | 区分 | 入力 | 期待結果 |
| --- | --- | --- | --- | --- |
| UT-AUTH-01 | パスワードのハッシュ化（DS-DEC-68） | 正常 | `hash_password("…")` の結果 | `$argon2id$v=19$m=19456,t=2,p=1$` で始まる。同じ入力で 2 回呼ぶと別のハッシュ（ソルトが別）。平文が含まれない |
| UT-AUTH-02 | パスワードの検証 | 正常・異常 | 正しい値、誤った値、空文字、壊れたハッシュ文字列（`not-a-hash`・空文字）、別アルゴリズムのハッシュ | 正しい値は真、他はすべて偽（例外を投げない） |
| UT-AUTH-03 | 再ハッシュの要否 | 境界 | 現行のパラメータ、time_cost=1、memory_cost=8192 のハッシュ | 現行は不要、他は要 |
| UT-AUTH-04 | パスワードの正規化（DS-DEC-69） | 正常 | `ａｂｃｄｅｆｇｈ`（全角）と `abcdefgh`、`Ａ１２３４５６７８` と `A12345678`、結合文字を含む表記 | NFKC で同じ値になり、同じ検証結果になる。前後の空白は**除去しない**（空白もパスワードの一部） |
| UT-AUTH-05 | パスワードの長さ（DS-DEC-69） | 境界 | 7・8・128・129 文字（正規化後。絵文字は 1 文字、全角は 1 文字と数える） | 7 と 129 は拒否、8 と 128 は可。`required`（空）・`out_of_range`（短い）・`too_long`（長い）の reason |
| UT-AUTH-06 | 禁止語（DS-DEC-69。G-17 で 236 語に拡張） | 異常 | 旧 20 語（`password`・`password1`・`password12`・`password123`・`12345678`・`123456789`・`1234567890`・`12341234`・`01234567`・`qwertyui`・`qwerty123`・`abcd1234`・`abc12345`・`iloveyou`・`letmein1`・`welcome1`・`admin123`・`guapp123`・`パスワード1234`・`ぱすわーど1234`）を、大文字・全角にして | すべて `weak_password`。リストに無い `password-ok-2026` は可 |
| UT-AUTH-06b | 禁止語の拡張規則（DS-DEC-69。G-17） | 正常・異常・境界 | ①禁止語リストの語数（150〜300 語。比較用に NFKC・小文字化済みで旧 20 語を含む）。②禁止語の前後に数字・記号を足したもの。③leet 表記（`p@ssw0rd` など）。④連番・繰り返し・キーボード配列。⑤メールの `@` より前の部分（4 文字以上）を含むもの。3 文字以下は対象外。⑥普通の合言葉（弱くないもの） | ①は 236 語。②〜⑤は `weak_password` と判定する。⑥は判定しない。対象外（禁止語の前に文字を足したもの、連番の折り返し、5 文字以上の単位の繰り返し）は設計どおり通る |
| UT-AUTH-07 | メールと同一のパスワード | 異常 | メール `demo@example.com` とパスワード `demo@example.com`、`DEMO@EXAMPLE.COM`、全角 | すべて拒否。メールの局所部だけ（`demo`）は 8 文字未満のため長さで拒否される |
| UT-AUTH-08 | 同一文字の繰り返し | 境界 | `aaaaaaaa`・`あああああああ`（7）・`ああああああああ`（8）・`aaaaaaab` | 8 文字以上で全文字が同じなら拒否。`aaaaaaab` は可 |
| UT-AUTH-09 | メールの正規化（DS-DEC-69） | 正常・異常 | 全角、前後空白、大文字、全角空白、ゼロ幅スペース、制御文字、`a@b`、254 文字・255 文字 | 全角・前後空白・大文字は小文字の半角に整う。ゼロ幅・制御文字を含む値、形式不正は拒否。254 は可、255 は拒否 |
| UT-AUTH-10 | ログインの識別子（DS-DEC-70） | 正常 | 同じメールの全角・半角・大文字違い | 正規化後に同じ SHA-256 の 16 進（64 桁）になる。別のメールは別の値 |
| UT-AUTH-11 | 会員がいないときのダミー検証（DS-DEC-71） | 正常 | 検証関数を差し替えて呼び出し回数を数える。会員あり・なしでログイン処理を呼ぶ | どちらも検証関数が 1 回呼ばれる（なしのときはダミーのハッシュに対して） |
| UT-AUTH-12 | トークンの生成・保存形式 | 正常 | 10,000 回生成 | 43 文字で `^[A-Za-z0-9_-]{43}$`。重複なし。保存用の値は SHA-256 の 16 進 64 桁で、元の値と異なる |
| UT-AUTH-13 | `DEMO_EMAIL_DOMAINS` の判定（DS-DEC-88） | 境界 | 未設定、`example.com`、`example.com, example.net`（空白つき）、メールが `a@example.com`・`a@EXAMPLE.com`・`a@sub.example.com`・`a@example.org` | 未設定は常に可。設定ありはドメインが完全一致（小文字化後）のときだけ可。サブドメインは不可。空白は無視する |
| UT-SESS-01 | セッションの有効性（DS-PRC-035） | 境界 | `expires_at` が現在の 1 秒後・ちょうど現在・1 秒前、`subject_type` が member・staff、会員が匿名化済み | 1 秒後の member だけが有効。ちょうど現在は無効（`expires_at > now`）。staff は無効。匿名化済みは無効 |
| UT-SESS-02 | セッション上限の削除対象（DS-DEC-72） | 境界 | 同じ会員の有効なセッションが 9・10・12 件ある状態で新規発行する | 9 件は削除なし、10 件は最古 1 件、12 件は最古 3 件を削除して新規を足し、10 件になる。他の会員のセッションは対象外 |
| UT-SESS-03 | トークンの形の検査 | 異常 | 42・43・44 文字、`=` や空白を含む値、空文字、None | 43 文字で `[A-Za-z0-9_-]` のみ可。他は「セッションなし」として扱う（例外を投げない） |
| UT-LOCK-01 | メール単位のロック判定（DS-DEC-70） | 境界 | 同じ識別子の失敗が 4 件・5 件、最古の失敗が 14 分 59 秒前・15 分 1 秒前 | 4 件は未ロック、5 件で直近 15 分以内ならロック。15 分を過ぎた失敗は数えない |
| UT-LOCK-02 | IP 単位の制限判定 | 境界 | 同じ IP の失敗が 29・30 件 | 29 件は可、30 件で拒否。別の IP は数えない |
| UT-LOCK-03 | 数える対象の絞り込み | 正常 | 成功の行、`subject_type=staff` の行、別の識別子の行が混ざる | 失敗かつ同じ `subject_type` かつ同じ識別子（または同じ IP）の行だけを数える |
| UT-SEC-05 | 拒否ログの `subject`（G-19。`reject_log`） | 正常・異常 | ①`subject` に SHA-256 の 16 進を渡す。②渡さない。③SHA-256 の形でない値を渡す。④再設定の要求のメール単位の制限と IP 単位の制限 | ①ログに先頭 12 桁だけが出る。②ログは従来と同じ。③書かない。④メール単位の 429 にだけ `subject` が付く |
| UT-PICK-01 | 受け取りコードの生成（DS-DEC-79） | 正常 | 10,000 回生成 | 8 文字で `^[A-HJ-NP-Z2-9]{8}$`。I・O・0・1 が一度も出ない。重複 0 |
| UT-PICK-02 | 受け取りコードの衝突 | 異常 | 登録処理の中で UNIQUE 違反を 1 回、2 回続けて起こす | 1 回目の衝突は 1 回だけ再生成して成功。2 回続けて衝突したら 500 `internal_error` |
| UT-PICK-03 | 受け取りコードの表示条件（DS-PRC-024a） | 境界 | 状態 8 値 × 受け取り方法 2 値の全 16 組 | `store` かつ `accepted`・`preparing`・`shipped` の 3 組だけが「表示する」 |
| UT-PRC-01 | 送料の差分（DS-PRC-021a） | 境界 | `receive_method="store"` で小計 1,490・4,980・4,990 | 送料は常に 0、合計は小計に等しい、内税は合計 × 10 ÷ 110 の切り捨て |
| UT-PRC-02 | 配送の送料（従来どおり） | 境界 | `receive_method` を省略／`"delivery"` で小計 4,989・4,990・4,991 | 550／0／0（UT-021-02 と同じ結果） |
| UT-PRC-03 | 不正な受け取り方法 | 異常 | `"pickup"`・空文字・None・数値 | `ValueError`（業務エラーではなく、呼び出し側の不具合として扱う） |
| UT-STATUS-01 | 状態の表示名（DS-PRC-024a） | 正常 | 状態 8 値 × 受け取り方法 2 値の全 16 組 | 設計仕様書 4.8 の表と一致する。未知の状態はテストで検出できる（網羅の確認） |
| UT-STATUS-02 | 追跡番号の表示条件 | 境界 | 状態 8 値 × 受け取り方法 2 値の全 16 組、追跡番号あり・なし | `delivery` かつ `shipped`・`delivered` かつ追跡番号ありのときだけ値を返す |
| UT-FIT-01 | サイズ感の集計（DS-PRC-003a） | 正常・境界 | レビュー 0 件、1 件、混在（small 2・just 6・large 2）、`fit` が NULL の行、`approved` が偽の行 | 件数が正しい。NULL と未承認は数えない。`total` は 3 つの合計 |
| UT-FIT-02 | 集計の応答の型 | 正常 | 0 件の商品 | `{"total":0,"small":0,"just":0,"large":0}`。キーが欠けない |
| UT-RESTOCK-01 | 申込の上限判定（DS-DEC-80） | 境界 | 同じメールの未通知が 9・10・11 件、既に申し込んだ variant への再申込 | 9 件は新規可、10 件は新規不可（422）、再申込は件数に数えず可 |
| UT-RESTOCK-02 | 通知対象の選択 | 正常 | 未通知 3 行、通知済み 2 行 | 未通知の 3 行だけが対象 |
| UT-RESTOCK-03 | 通知まわりのログ・監査 | 正常 | 通知の実行とメール失敗 | ログと `audit_logs` の `detail` にメールアドレスが含まれない（失敗時は件数のみ） |
| UT-VAL-03 | 注文入力：受け取り方法の条件（DS-API-022） | 異常・境界 | `store` で `store_code` なし、`delivery` で郵便番号なし、`store` で郵便番号・住所なし、`store_code` が `demo-tokyo`・`DEMO`・`demo_tokyo`・全角・33 文字・空文字 | `store` で `store_code` なしは 400（`required`）。`delivery` で郵便番号なしは 400。`store` で郵便番号・住所なしは可（無視）。`store_code` は `^[a-z0-9-]{1,32}$` に合うものだけ可 |
| UT-VAL-04 | 注文入力：店舗受け取りの連絡先 | 異常 | `store` の電話に全角数字（`０９０…`）・英字、氏名が全角空白のみ、メールが `@` なし | 電話の全角数字は 400（ASCII 数字に限る。UT-VAL-01 と同じ）、氏名は `required`、メールは `format` |
| UT-SEED-08 | seed の会員（DS-DEC-87） | 正常・境界 | `seed_data.MEMBERS` と、`APP_ENV=production` で `SEED_MEMBER_PASSWORD` がある場合・ない場合 | 5 件。メールは `demo-member1`〜`5@example.com`。`demo-member3` だけ未確認。production で環境変数がなければ会員を投入しない（0 件）。ある場合は投入し、ハッシュは argon2id |
| UT-SEED-09 | seed の店舗 | 正常 | `seed_data.STORES` | 3 件。`code` は `^[a-z0-9-]{1,32}$`、郵便番号は ASCII 数字 7 桁でハイフンなし、`pickup_enabled` は真 |
| UT-SEED-10 | seed のレビュー | 正常 | `seed_data.REVIEWS` | 43 行（承認済み 42・未承認 1）。商品 1〜8 の件数が設計仕様書 5.8 の表と一致。商品 9 以降は 0 件。`rating` は 3〜5、`member_id` は None |
| UT-SEED-11 | seed のダミー性 | 正常 | 会員・店舗・レビューの全文字列 | メールは `@example.com` のみ。実在らしき電話番号・郵便番号（`0000001` 以外の実在の番号）・実在の店舗名を含まない |

### 5.2 Next.js（Vitest）

| ID | 対象 | 区分 | 入力 | 期待結果 |
| --- | --- | --- | --- | --- |
| UT-WEB-13 | Header のログイン状態（DS-SCR 共通・DS-DEC-86） | 正常 | `signedIn` を偽・真で描画 | 偽は `aria-label="ログイン"`・リンク先 `/login`、真は `aria-label="マイページ"`・リンク先 `/mypage`。アイコンは 44px 以上 |
| UT-WEB-14 | `safeNext`（DS-DEC-85） | 異常・正常 | `//evil.example`・`/\evil.example`・`https://evil.example`・`javascript:alert(1)`・`/%2F%2Fevil.example`・`/products/12abc`・`/admin`・空文字・undefined・5000 文字、`/checkout`・`/cart`・`/mypage`・`/products/12`・`/mypage?x=1` | 前者はすべて `/mypage`。後者はクエリを除いたそのパス（`/mypage?x=1` は `/mypage`） |
| UT-WEB-15 | `sid` Cookie の組み立て（DS-DEC-72） | 正常・境界 | 通常値、`production` の設定、削除用、使えない文字を含む値 | `HttpOnly; SameSite=Lax; Path=/; Max-Age=86400`、`production` のとき `Secure`。削除用は `Max-Age=0` で値が空。使えない文字（改行・`;`）を含む値は例外 |
| UT-WEB-16 | ログインフォーム（DS-SCR-007） | 正常・異常 | 401・403・429・503 の応答、送信中、成功 | 状態別の文言（6.3 の表）。入力済みのメールは残りパスワードは空。送信中はボタン無効で二重送信されない。成功で `next`（`safeNext`）へ `router.replace` と `router.refresh` |
| UT-WEB-17 | 登録フォーム | 正常・異常・境界 | パスワード 7・8・128・129 文字、氏名空、メール形式不正、202、400 の `fields`、422 `weak_password`・`unsupported_value` | クライアント検査と項目ごとのエラー表示。202 のあとはフォームが消えて案内と `/login` へのリンク。デモの注意書きが常に出る |
| UT-WEB-18 | パスワード再設定フォーム | 正常・異常 | 要求の送信（200）、確定でパスワードと確認が不一致、404、422、成功 | 要求の後は常に同一の案内。確認入力の不一致は送信しない。404 は「無効か期限切れ」と再要求へのリンク。成功は `/login?reset=1` へ移る |
| UT-WEB-19 | メール確認ページ | 正常 | `?token=` つきで描画する | ボタンを押すまで POST が発生しない（マウント時に自動送信しない）。押すと 1 回だけ送る。200 と 404 で文言が変わる |
| UT-WEB-20 | 注文手続きの受け取り方法（DS-SCR-005） | 正常・異常 | 配送・店舗を切り替える。店舗未選択で「確認画面へ」。ログイン中の props を渡す | 店舗では住所の欄が消え、送信本文（prepare・保存値）に郵便番号・住所を含めない。店舗を選ぶまでエラー。配送に戻すと入力済みの値が残る。ログイン中は氏名とメールが初期値になり、ゲストのカードが出ない。店舗の取得に失敗した props（null）では店舗受け取りが選べない |
| UT-WEB-21 | 注文完了の受け取りコード（DS-SCR-006） | 正常 | `receive_method=store` の応答、`delivery` の応答、`is_member_order` 真・偽 | 店舗はコードを `ABCD-EFGH` の形で大きく表示し、店舗名・住所を出す。配送はコードの枠が出ない。`is_member_order` で案内文が切り替わる |
| UT-WEB-22 | 注文履歴の一覧・詳細（DS-SCR-008・009） | 正常・境界 | 注文 0 件・1 件・複数件、`item_count` 1 と 3、状態 8 値、店舗・配送、`pickup_code` あり・なし、ページ範囲外 | 空は「まだご注文がありません」。「ほか N 点」は `item_count - 1`（1 点なら付かない）。進捗バーの完了段数が設計どおり。取消・期限切れ・決済失敗は進捗バーなし。コードは API が返したときだけ表示。範囲外のページは案内と 1 ページ目へのリンク |
| UT-WEB-23 | 再入荷のお知らせの申込（DS-SCR-003） | 正常・異常 | 在庫あり／在庫切れの組み合わせを選ぶ。200・409・404・422・400・429 の応答 | 在庫切れの組み合わせを選んだときだけ表示。応答ごとに 6.6 の文言。送信中は無効。成功後は欄を消す |
| UT-WEB-24 | サイズ感の表示（DS-SCR-003） | 正常・境界 | `fit_summary` が total 0、1、10（2／6／2） | 0 は「まだありません」。それ以外は件数 3 つと「全 N 件」。棒の幅は件数の比（合計 100%）。ラベルの文字が棒の中または下に出る |
| UT-WEB-25 | 認証系のエラー文言の対応表 | 正常 | コード 401 `invalid_credentials`・403 `account_locked`・429・422 `weak_password`・422 `unsupported_value`・404・400・503・未知のコード | 画面の文言が 6 章どおり。未知のコードは汎用の文言（内部のコードを画面に出さない） |
| UT-WEB-26 | 認証 BFF の共通処理（`auth-proxy`） | 正常・異常 | FastAPI の応答に `session_token` を含める。`Retry-After` つきの 429。接続不可 | `session_token` を本文から除いて `sid` の Set-Cookie にする。`Retry-After` は数字のときだけ透過。接続不可は 503。`csrf_token` はログイン・ログアウト成功時に発行し直す |

## 6. テストデータ

| データ | 用途 | 対応テスト |
| --- | --- | --- |
| seed の会員 5 件（`demo-member1`〜`5@example.com`。3 番目だけメール未確認） | ログイン、マイページ、未確認バナー | AT-14・AT-18、ST-F024、IT-032、IT-036 |
| `demo-member4`（注文 0 件の会員） | 履歴の空表示 | ST-F017-02、IT-024-02 |
| テスト内で作る会員（M-NEW、ロック検証用の M-LOCK、並行ログイン用の M-CONC） | 登録・ロック・同時実行 | AT-13・AT-18、IT-030、IT-032-03・13 |
| seed のパスワード `DEMO_MEMBER_PASSWORD`（ダミー値。本書には書かない） | ログインの正常系 | AT・ST・IT 全般 |
| seed の店舗 3 件：`demo-tokyo`・`demo-osaka`・`demo-fukuoka` | 店舗受け取り | AT-15、ST-F013-03、IT-014-10、IT-026 |
| 存在しない店舗コード `no-such-store`、`pickup_enabled` を偽にした店舗 | 店舗の異常系 | ST-F013-04、IT-014-11、IT-026-02 |
| V-STOCK0（商品 29 の色ブラック・サイズ M。SKU `GU-029-BK-M`。在庫 0） | 再入荷の申込 | AT-16、ST-F007-02〜06、IT-007 |
| 在庫のあるバリエーション、P-UNPUB（非公開商品）のバリエーション | 再入荷の異常系 | ST-F007-03、IT-007-02・03 |
| seed のレビュー 43 行（商品 1〜8 に承認済み 42、商品 1 に未承認 1） | サイズ感の集計 | AT-17、ST-F005-04〜06、IT-003-03、UT-FIT、UT-SEED-10 |
| レビュー 0 件の商品 9、1 件の商品 8 | サイズ感の境界 | ST-F005-05、IT-003-04 |
| 配送の注文・店舗受け取りの注文（テスト内で作り、状態を DB で変える） | 履歴・状態・表示条件 | ST-F017-04〜08、IT-024a |
| 小計 1,490・4,980・4,990 のカート（商品 1 または 25＋…で組む） | 送料の境界 | ST-F013-05、IT-021-03、UT-PRC |
| 禁止語 236 語（旧 20 語を含む。G-17） | パスワードポリシー | IT-030-05・05b、IT-035-03b、UT-AUTH-06・06b |
| `DEMO_EMAIL_DOMAINS=example.com` の起動設定 | メール制限 | IT-030-09、ST-SEC-57、UT-AUTH-13 |

## 7. 実施計画

| 時期 | 内容 |
| --- | --- |
| 実装と同時（10/23〜25） | UT・IT を各レーンが書く（設計仕様書 11 章のレーンごとの担当）。CI（`pytest`・`vitest`・`ruff`・lint・型検査）を毎回緑にする |
| 10/25 | 結合した状態で IT を全件実行。同時実行テスト（IT-030-08・032-13・035-06・007-09・014-19）は 1 章 #2 の条件で反復し、無効試行の数を記録する。防御を 1 つずつ外して赤くなることを確認する（下の 8 章 #6） |
| 10/26（検収） | AT-13〜21 を PC 幅と 375px で実施。ST-F024・F017・F013・F014・F007・F005 と ST-SEC-36〜59、ST-NFR-03・04 を実施。結果を `docs/05_検収/` に記録し、10 章へ転記する |
| P2 全体の検収（10/31） | 公開環境（F1）での ST-NFR-03 の計測、`Secure` 属性の確認（コードの条件とユニットテストで代える）、AT の再実施 |

## 8. 申し送り

1. **メールの実送信（IF-02）を削った場合**：AT-19（再設定）・AT-20（確認）・AT-16（再入荷）は、本番のスタブ設定（`APP_ENV=production`）ではリンクを読めないため、公開環境では実施できない。ローカルで実施した結果を検収記録に残し、公開環境は「未実施（IF-02 未実装のため）」と明記する（ADR-0006）。
2. **受け取りコードの照合（F-038）は P3**：P2-b のテストは「顧客がコードを確認できる」（REQ-FR-508 の前半）まで。店舗スタッフがコードを照合して引き渡しを記録する後半は対象外。
3. **カートの引き継ぎ（F-010）は P3**：ST-F024-11 は「ログインしてもカートが消えない」ことだけを確かめる。別の端末への引き継ぎは期待しない。
4. **ロック解除（F-039）は P3**：ロックは時間経過（15 分）でのみ解ける。手動解除のテストは無い。
5. **回数制限はプロセス内メモリ**：登録・再設定・再入荷の個別制限は、複数ワーカーや再起動で共有されない（本編 9.4 と同じ）。F1 は 1 インスタンス・1 ワーカー（ADR-0005）で許容する。ログインの制限だけは DB で数えるため、再起動をまたいでも有効。
6. **防御外し確認（本編 1.4 #8）の対象を足す**：①`sessions.token_hash` の UNIQUE を外す→IT-SCHEMA-12 ②ログインのロック判定（失敗 5 件）を外す→IT-032-03・ST-SEC-40 ③未登録メールのダミー検証を外す→UT-AUTH-11・ST-SEC-38 ④ログイン時の旧セッション削除を外す→IT-032-07・ST-SEC-43 ⑤注文履歴の `member_id` 条件を外す→IT-024-05・ST-SEC-47 ⑥`pickup_code` の UNIQUE を外す→IT-SCHEMA-12。`scripts/mutation-check/cases.json` に 6 件を足し、結果表を実施記録に転記する。
7. **argon2 のコスト**：テストが遅い場合でもコストを下げて検証しない（1 章 #5）。CI の所要時間が問題になったときは、並列実行の設定で対処する。

## 9. 講義の必須観点との対応（P2-b 分）

| 講義の観点 | 対応するテスト |
| --- | --- |
| パスワードハッシュ（E-03） | ST-SEC-36、UT-AUTH-01〜03、ST-NFR-03 |
| ユーザー列挙（B-03） | ST-SEC-37〜39、IT-030-02、IT-032-02・04、IT-034-02 |
| 総当たり対策・ロック（B-04） | ST-SEC-40〜42・58、IT-032-03〜06・032-17・032-18、UT-LOCK、UT-SEC-05 |
| パスワードポリシー（B-05） | IT-030-03〜06・030-05b・035-03b、UT-AUTH-04〜08・06b |
| セッション固定・Cookie 属性（B-06・B-01） | ST-SEC-43・44、IT-032-07、UT-WEB-15 |
| ログアウト・失効（J-04） | ST-SEC-45、IT-033、IT-036 |
| IDOR（A-01） | ST-SEC-47・48、IT-024-05、IT-024a-02 |
| mass assignment（A-03） | ST-SEC-49、IT-030-07、IT-BFF-030f |
| CSRF（C-03） | ST-SEC-46、IT-BFF-030b |
| オープンリダイレクト（C-04） | ST-SEC-52、UT-WEB-14 |
| 権限の分離（A-02 の準備） | ST-SEC-59、IT-036-03 |
| ログの個人情報（F-05） | ST-SEC-53、UT-RESTOCK-03 |
| テスト用アカウントの残存（B-07） | ST-SEC-57、UT-SEED-08 |

## 10. トレーサビリティ表（P2-b 追加分）

件数（本書の表の ID を機械的に数えた値）：AT 9（AT-13〜21）、ST-F 39、ST-NFR 2（ST-NFR-03・04）、ST-SEC 24（ST-SEC-36〜59）、IT 100、UT 52（API 側 38・Web 側 14）。合計 226 件。

| REQ | F／SCR | DS | AT | ST | IT | UT |
| --- | --- | --- | --- | --- | --- | --- |
| REQ-FR-801 | F-024／SCR-007・008 | DS-API-030・032・033・036、DS-PRC-030・032・035、DS-TBL-01・03・26、DS-DEC-68〜72・76 | AT-13、AT-18 | ST-F024-01〜06・11・12、ST-SEC-36〜46・59 | IT-030-01〜08、IT-032-01〜13・17・18、IT-033、IT-036 | UT-AUTH-01〜12、UT-SESS、UT-LOCK、UT-WEB-13〜17 |
| REQ-FR-802 | F-024／SCR-007 | DS-API-031、DS-PRC-031、DS-TBL-27、DS-DEC-74 | AT-20 | ST-F024-07・08、ST-SEC-51 | IT-031 | UT-AUTH-12、UT-WEB-19 |
| REQ-FR-803 | F-024／SCR-007 | DS-API-034・035、DS-PRC-034、DS-DEC-75 | AT-19 | ST-F024-09・10、ST-SEC-50 | IT-034、IT-035 | UT-AUTH-04〜08、UT-WEB-18 |
| REQ-FR-807 | F-024／SCR-007 | DS-API-030、DS-DEC-76 | AT-13 | ST-F024-01〜03 | IT-030-03〜06 | UT-AUTH-04〜09 |
| REQ-FR-601・602 | F-017／SCR-008・009 | DS-API-024・024a、DS-PRC-024・024a、DS-DEC-77・78 | AT-14 | ST-F017-01〜08、ST-SEC-47・55 | IT-024、IT-024a | UT-STATUS、UT-WEB-22 |
| REQ-FR-501 | F-013／SCR-005 | DS-API-021・026、DS-PRC-021a、DS-TBL-10、DS-DEC-79 | AT-15 | ST-F013-03〜06 | IT-021-03〜05、IT-026、IT-BFF-021 | UT-PRC、UT-VAL-03・04、UT-WEB-20 |
| REQ-FR-508（顧客が確認する部分） | F-014・F-017／SCR-006・009 | DS-API-022・023・024a、DS-PRC-014-3、DS-DEC-79 | AT-15 | ST-F014-07〜12、ST-F017-08、ST-SEC-48 | IT-014-10〜19、IT-023-03、IT-BFF-022 | UT-PICK、UT-WEB-21 |
| REQ-FR-205 | F-007／SCR-003 | DS-API-007、DS-PRC-007・007a、DS-TBL-20、DS-DEC-80 | AT-16 | ST-F007-02〜06、ST-SEC-58 | IT-007、IT-007a、IT-BFF-007 | UT-RESTOCK、UT-WEB-23 |
| REQ-FR-208 | F-005／SCR-003 | DS-API-003、DS-PRC-003a、DS-TBL-19、DS-DEC-81 | AT-17 | ST-F005-04〜07 | IT-003-03〜05 | UT-FIT、UT-SEED-10、UT-WEB-24 |
| REQ-FR-504（店舗の確認メール） | F-014 | DS-PRC-014-3 手順 7、DS-DEC-89 | AT-15 | ST-F014-11 | IT-014-10 | — |
| REQ-NFR-07・08 | — | 7 章、DS-DEC-72・77・85・89 | AT-18 | ST-SEC-43〜49・52〜56・59 | IT-BFF-030a〜f、IT-BFF-031 | UT-WEB-14・15・26 |
| REQ-NFR-10 | — | DS-DEC-70・84 | AT-18 | ST-SEC-40〜42・58 | IT-032-03〜06 | UT-LOCK |
| REQ-NFR-09 | — | 6 章 | AT-21 | ST-NFR-04、ST-F005-07 | — | UT-WEB-13・17・20〜24 |
| REQ-NFR-04 | — | DS-TBL-23（`audit_logs` の新しい action） | — | ST-SEC-53 | IT-030-01、IT-031-01、IT-032-01、IT-035-01、IT-007a-01 | UT-RESTOCK-03 |
| REQ-NFR-05 | — | 5.8 seed | — | — | IT-SCHEMA-13 | UT-SEED-08〜11 |
| （構造） | — | DS-TBL 8 表、5.5 | — | — | IT-SCHEMA-09〜12 | — |
| REQ-NFR-06（パスワード保存・通信） | — | DS-DEC-68 | — | ST-SEC-36、ST-NFR-03 | IT-032-08 | UT-AUTH-01〜03 |

## 11. テスト関数との対応（実装後に転記）

本書の ID と、実装で書いたテスト関数の対応表は、実装レーンの報告を受けた後に本章へ転記する（本編 12 章と同じ運用）。転記前の時点では、全項目が実施前である。

| 区分 | ID の範囲 | テストファイル（予定） | 転記状況 |
| --- | --- | --- | --- |
| IT（認証） | IT-030〜036 | `apps/api/tests/integration/test_it_030_036_auth.py` | 未 |
| IT（履歴・店舗・注文） | IT-024・024a・026・021-03〜・014-10〜・023-03 | `test_it_024_026_orders_stores.py`、`test_it_014_p2b_orders.py` | 未 |
| IT（再入荷・サイズ感） | IT-007・007a・003-03〜 | `test_it_007_restock.py`、`test_it_003_fit.py` | 未 |
| IT（スキーマ） | IT-SCHEMA-09〜13 | `test_it_schema_p2b.py` | 未 |
| IT（BFF） | IT-BFF-030a〜、031、007、021、022 | `apps/web/tests/it-bff-030.auth-routes.test.ts` ほか | 未 |
| UT（API） | UT-AUTH・SESS・LOCK・PICK・PRC・STATUS・FIT・RESTOCK・VAL-03〜・SEED-08〜 | `apps/api/tests/unit/test_ut_*.py` | 未 |
| UT（Web） | UT-WEB-13〜26 | `apps/web/tests/ut-web-13-26.*.test.ts(x)` | 未 |
| ST-SEC の自動化 | ST-SEC-36〜59 のうち HTTP で再現できるもの | `st-sec-p2b-*.test.ts`、`test_st_sec_p2b_*.py` | 未 |
