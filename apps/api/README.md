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
| `PAYMENT_STUB_RESULT` | ok / ng（P1 のみ） |
| `IMAGE_BASE_URL` | 商品画像の配信ベース URL |

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
  models/            SQLAlchemy 2.0 モデル（P1 の 12 表）
  routers/health.py  DS-API-061
tests/
  unit/              DB 不要
  integration/       MySQL 必須（安全装置付き）
```

## エラー応答（設計書 4.5 の要約）

- 400 `validation_error` `{code, fields:[{name, reason}]}`（reason: required / format / too_long / out_of_range）
- 401 `unauthorized`、404 `not_found`、409 業務コード `{code, ...}`、422 `{code, field, limit}`
- 500 `{code:"internal_error", message:"処理中にエラーが発生しました"}`（詳細はログのみ）
- ルーターでは `HTTPException` を使わず `AppError(status, code, **detail)` を投げる
