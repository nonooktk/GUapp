# GUapp API（FastAPI・P1）

GU EC サイト P1 のバックエンド。設計仕様書 `docs/03_設計仕様書/GU_ECsite_設計仕様書_P1_draft-v3.md` に従う。

## 前提

- Python 3.13（uv 管理）。`uv` が PATH に無い場合はフルパスで呼ぶ
- MySQL 8.4（ローカルは `scripts/mysql-local/` で 127.0.0.1:3306 に起動）

## セットアップ

```powershell
cd apps\api
uv sync            # uv.lock に固定された版を .venv に入れる
```

DB の初期化（MySQL は `scripts/mysql-local/README.md` の手順で起動しておく）:

```powershell
$env:DATABASE_URL = "<credentials.txt の DATABASE_URL>"   # 値は書き写さず、ファイルから読む
uv run alembic upgrade head        # 12 表を作る（alembic/versions/0001_p1_initial.py）
uv run python -m app.seed          # 商品 30 点・テスト用データ・system_settings 4 キーを投入
```

seed は冪等で、既に商品があれば何もしない。作り直すときだけ `--reset`（確認プロンプトあり。`--yes` で省略）。
`alembic.ini` は cp932 で読まれるため ASCII のみ。接続 URL は書かず環境変数 `DATABASE_URL` から取る。

## 環境変数

リポジトリルートの `.env.example` の api 部分を参照。値は環境変数か、この
ディレクトリの `.env`（gitignore 済み・コミット禁止）で与える。

| 名前 | 意味 |
| --- | --- |
| `APP_ENV` | development / test / production（production で /docs 無効） |
| `DATABASE_URL` | SQLAlchemy URL（スキーム `mysql+asyncmy`。実値はここに書かない） |
| `INTERNAL_TOKEN` | BFF → API の内部認証。`/api/v1/health` 以外はこのヘッダ必須 |
| `CORS_ALLOW_ORIGIN` | 許可オリジン 1 つ（BFF の URL）。未設定なら CORS を一切許可しない |
| `PAYMENT_STUB_RESULT` | ok / ng（P1 のみ。未設定は ok） |
| `IMAGE_BASE_URL` | 商品画像の配信ベース URL |
| `TEST_RESERVE_DELAY_MS` | テスト専用。`APP_ENV=test` のときだけ、注文確定の金額照合と在庫引当の間に入れる待ち（ms） |

## 起動

```powershell
uv run uvicorn app.main:app --reload --port 8000
# 動作確認
curl http://127.0.0.1:8000/api/v1/health
#   DB 到達可: 200 {"status":"ok","db":"ok"}
#   DB 不達:   503 {"code":"db_unavailable"}
```

## テスト

```powershell
uv run pytest -q             # unit（DB 不要）＋ integration（条件を満たす場合のみ）
uv run ruff check .
```

integration は次の安全装置を通った場合だけ走る（`tests/integration/conftest.py`）:

1. 環境変数 `DATABASE_URL_TEST` が無ければ全件 skip
2. URL の DB 名が `_test` で終わらなければ即中止（開発 DB を壊さない）
3. dialect が `mysql` でなければ即中止（SQLite での偽陽性防止）

例（PowerShell。値は自分の環境のものを入れる）:

```powershell
$env:DATABASE_URL_TEST = "mysql+asyncmy://<user>:<pass>@127.0.0.1:3306/guapp_test"
uv run pytest -q tests/integration
```

## 構成

```
app/
  main.py            create_app()。エラーハンドラ・CORS・ルーター登録
  core/
    config.py        Settings（pydantic-settings）
    errors.py        AppError と例外ハンドラ（設計書 4.5）
    logging.py       秘密マスクフィルタ
    security.py      X-Internal-Token 検証・CORS
    db.py            async engine（pool 20 + overflow 10）・get_session
    testing_hooks.py APP_ENV=test 限定の同時性フック
    rate_limit.py    ゲスト注文照会のレート制限（100 回/時/IP・プロセス内メモリ）
  adapters/          外部接続。payment（StubPaymentAdapter）・mail（OutboxMailAdapter → .mail-outbox/）
  models/            SQLAlchemy 2.0 モデル（P1 の 12 表）
  schemas/           Pydantic 要求／応答（契約の正本は openapi.json）
  routers/           入出力のみ。health（061）・catalog（001〜003）・cart（010〜013）・settings（020）・
                     checkout（021）・orders（022・023）・testing（/_test。APP_ENV=test 限定）
  services/          業務規則（422／409）。pricing（DS-PRC-021）・cart_rules（DS-PRC-011）・cart・catalog・settings・
                     checkout（021）・orders（DS-PRC-014-1）・order_number・order_state（遷移表）
  repositories/      SQL（Core／ORM）。公開商品の条件は products.published_filter() の 1 か所。
                     orders.py に引当（条件付き UPDATE）・カート状態の条件付き UPDATE
tests/
  unit/              DB 不要
  integration/       MySQL 必須（安全装置付き）。live_server.py は同時実行テスト用に uvicorn を子プロセスで起動
openapi.json         API 契約（create_app().openapi() の出力。BFF はこれと突き合わせる）
.mail-outbox/        P1 のメールアダプタの出力先（gitignore 済み）
```

## Wave 1 の API（DS-API-001〜003・010〜013・020）

- base `/api/v1`。`/health` 以外は `X-Internal-Token` 必須
- カートの識別は **ヘッダ `X-Cart-Token`**（BFF が Cookie から移す。URL・クエリには載せない）。
  無し／未知なら新カートを作りトークンを発行して応答の `cart_token` に返す。
  `ordered` のカートのトークンなら旧カートの token を NULL にし同じトークンで新 active カートを返す
- 商品一覧・詳細・関連・カート追加は公開商品（`published=true`）のみ。非公開・不存在は 404
- カート追加は 在庫 0 → 409 `out_of_stock`、1 明細 > 10 または合計 > 50 → 422 `limit_exceeded`。
  数量 > 在庫 は許し、応答の `stock_status`（ok／insufficient／out_of_stock）で示す
- 契約を更新したら `openapi.json` を再出力する:

```powershell
uv run python -c "from app.main import create_app; import json; print(json.dumps(create_app().openapi(), ensure_ascii=False, indent=2))" > openapi.json
```

## Wave 2 の API（DS-API-021〜023・DS-PRC-014-1）

- `POST /checkout/prepare`（body 無し・`X-Cart-Token`）→ 200 `{idempotency_key(43 文字), items, subtotal, shipping_fee, total, tax_included, tax_rate, free_shipping_threshold}`。
  カート不明 404／空カート 409 `empty_cart`／`stock_status` が ok 以外の明細 409 `out_of_stock {items}`／注文済みカート 409 `already_ordered`
- `POST /orders`（`X-Cart-Token`）body `{idempotency_key, ship_name, ship_postal_code, ship_address, ship_phone, guest_email, receive_method:"delivery", payment_method:"card", display:{subtotal, shipping_fee, total}}`
  → **201**（新規）／**200**（同じカートの同じキー＝既存注文）で注文応答。
  郵便番号・電話はハイフン・空白を除いてから検査（`100-0001` 可）。
  エラー: 400 `validation_error`／404 `not_found`（カート不明・他人のカートの冪等キー）／409 `already_ordered {order_number}`・`price_changed {amounts}`・`out_of_stock {items}`・`payment_failed {order_number}`／422 `unsupported_value {field}`
- `POST /orders/{order_number}/lookup` body `{guest_email}` → 200 注文応答。番号不存在・メール不一致は区別せず 404。同一 IP 100 回/時を超えると 429 `rate_limited` ＋ `Retry-After`（IP は `X-Forwarded-For` 先頭、無ければ接続元）
- 注文応答: `{order_number, status, items:[{product_name, color, size, unit_price, quantity, line_total}], subtotal, shipping_fee, total, tax_included, tax_rate, ship_*, guest_email, receive_method, payment_method, ordered_at(UTC)}`。内部 ID は出さない
- 注文確定の手順（`app/services/orders.py` の docstring が正）: INSERT orders（冪等キー UNIQUE）→ carts を `active→ordered` 条件付き UPDATE → 金額再計算・照合 → variant_id 昇順に `UPDATE variants SET stock=stock-q WHERE id=? AND stock>=q` → 決済スタブ → COMMIT → メール（失敗しても注文成立、audit_logs `mail.failed`）。
  決済 NG は注文を `payment_failed` で残し、別トランザクションで在庫とカートを戻す。同じカートへの同時確定で InnoDB のデッドロック（1213）が出た側は ROLLBACK して 1 回やり直す
- 注文番号 `GU-YYMMDD-XXXXXXXX`（日付は JST、8 文字は I/O/0/1 を除く 32 文字。UNIQUE 衝突は 1 回再生成）。Windows では tz データベースが無いため `tzdata` を依存に含む
- テスト専用ルート（`APP_ENV=test` のみ）: `GET /_test/metrics` `{inflight_now, inflight_max}`、`POST /_test/reset`

同時実行テスト（IT-014-02〜04）は `tests/integration/live_server.py` が空きポートで uvicorn を起動し、`TEST_RESERVE_DELAY_MS=30` で回す。IT-014-03／04 は同時性が成立しなかった試行（`/_test/metrics` の `inflight_max < 2`）を無効試行として数え、同じ反復を最大 3 回までやり直す（3 回とも不成立なら赤）。無効試行の回数は pytest の terminal summary に「同時実行 IT の無効試行」として出る（`tests/integration/concurrency_helpers.py`）。

## エラー応答（設計書 4.5 の要約）

- 400 `validation_error` `{code, fields:[{name, reason}]}`（reason: required / format / too_long / out_of_range）
- 401 `unauthorized`、404 `not_found`、409 業務コード `{code, ...}`、422 `{code, field, limit}`
- 500 `{code:"internal_error", message:"処理中にエラーが発生しました"}`（詳細はログのみ）
- ルーターでは `HTTPException` を使わず `AppError(status, code, **detail)` を投げる
