# scripts/azure-db — 講義の Azure MySQL への接続

講義サーバー `gen12-mysql-pos.mysql.database.azure.com`（スキーマ `guapp_nonooktk`）に、
ローカルの `apps/api` から SSL 接続するための手順・スクリプト集（設計仕様書追補
`GU_ECsite_設計仕様書_P2追補a_draft-v1.md` 8 章・ADR-0002）。

**このディレクトリのスクリプトは、資格情報を画面・ログに一切出さない設計になっている。**
`apps/api/.env.azure`（`DB_USER`・`DB_PASSWORD` の2行、権限600）を編集・コピー・
移動しないこと。値を `cat`・`echo` で見ようとしないこと。

## 前提

- `apps/api/.env.azure` に、統括が用意した `DB_USER=`・`DB_PASSWORD=` の2行がある
  （無ければ先に統括に確認する。このリポジトリでは作れない）
- この Mac の IP がサーバー側ファイアウォールに登録済みであること（**IP が変わったら
  繋がらなくなる**。その場合は統括に「現在のグローバル IP をファイアウォールに
  追加してほしい」と依頼する。自分のグローバル IP は `curl https://ifconfig.me`
  等で確認できる）
- `openssl`・`curl`・`python3`・`uv` が使えること（Mac 標準＋Homebrew の `uv` で足りる）

## 手順（上から順に実行する）

### 1. CA 証明書を取得する（初回のみ、または証明書ローテーション後）

```bash
cd /path/to/GUapp
scripts/azure-db/fetch-ca.sh
```

`~/.config/guapp/azure-mysql-ca.pem`（リポジトリの外）に、Azure Database for MySQL
Flexible Server が提示する証明書チェーンに対応する CA 証明書（DigiCert Global Root CA・
DigiCert Global Root G2・Microsoft RSA Root Certificate Authority 2017 の3つを
束ねたもの）が作られる。取得元・確認日はスクリプト冒頭のコメントを参照。

証明書は公開情報（秘密ではない）だが、リポジトリにはコミットしない。**Microsoft は
証明書をローテーションすることがある**ので、しばらく経ってから接続エラーが出た場合は
まずこのスクリプトを再実行してみること。

### 2. 疎通確認（IT-AZ-01・02 相当）

```bash
cd apps/api
../../scripts/azure-db/with-azure-db.sh uv run python ../../scripts/azure-db/check_connection.py
```

`SELECT 1` と `SHOW STATUS LIKE 'Ssl_cipher'` を実行するだけの読み取り専用の確認。
成功すると次のように出る（数値は変わりうる）。

```
[check_connection] SELECT 1 -> 1
[check_connection] Ssl_cipher -> TLS_AES_256_GCM_SHA384
[check_connection] Ssl_version -> TLSv1.3
[check_connection] 接続成功
```

失敗する場合によくある原因:

| 症状 | 原因 | 対処 |
| --- | --- | --- |
| 接続がタイムアウトする | この Mac の IP がファイアウォール未登録、または IP が変わった | 統括に現在のグローバル IP の追加を依頼する |
| `CA 証明書が見つかりません` | 手順1を実行していない | `scripts/azure-db/fetch-ca.sh` を実行する |
| 証明書検証エラー | 証明書がローテーションされた | `scripts/azure-db/fetch-ca.sh` を再実行する |
| `.env.azure から DB_USER または DB_PASSWORD を読み取れませんでした` | `.env.azure` が無い・書式が違う | 統括に確認する（このリポジトリでは値を作れない） |

### 3. マイグレーション・seed の投入

**`--reset` は破壊的操作（既存データを全部消して入れ直す）。** 講義サーバーの
`guapp_nonooktk` に対して実行する前に、本当に消してよいデータか確認すること。

```bash
cd apps/api
../../scripts/azure-db/with-azure-db.sh uv run alembic upgrade head
../../scripts/azure-db/with-azure-db.sh uv run python -m app.seed --reset --yes
```

`--yes` を付けなければ確認プロンプトが出る（対話実行の場合はそちらでもよい）。

### 4. API を Azure 接続で起動して確認する

```bash
cd apps/api
../../scripts/azure-db/with-azure-db.sh uv run uvicorn app.main:app --port 8000 \
  > /tmp/guapp-api-azure.log 2>&1 &
```

```bash
curl -s http://127.0.0.1:8000/api/v1/health
#  {"status":"ok","db":"ok"} なら成功
```

web（`http://localhost:3000`。`apps/web` を別途 `pnpm dev` 等で起動しておく）で
商品一覧・検索（`/search?q=シャツ` 等）・お知らせ（ホーム下部）が表示されることを
確認する。

### 5. ローカル DB 接続に戻す

確認が終わったら、Azure 接続の API プロセスを止め、ローカル DB 接続で起動し直す。

```bash
# Azure 接続版のプロセスを止める（ポート 8000 の PID を調べて kill）
lsof -i :8000 -sTCP:LISTEN
kill <PID>

# ローカル DB 接続で起動し直す（apps/api/.env の DATABASE_URL を使う）
cd apps/api
nohup uv run uvicorn app.main:app --port 8000 > /tmp/guapp-api.log 2>&1 &

curl -s http://127.0.0.1:8000/api/v1/health   # {"status":"ok","db":"ok"}
```

## スクリプトの説明

| ファイル | 役割 |
| --- | --- |
| `fetch-ca.sh` | CA 証明書を取得し `~/.config/guapp/azure-mysql-ca.pem` に束ねる |
| `with-azure-db.sh` | `.env.azure` の資格情報から `DATABASE_URL` を組み立て、環境変数として渡して指定したコマンドを実行する。ホスト・DB 名は固定値（`gen12-mysql-pos.mysql.database.azure.com` / `guapp_nonooktk`）で、それ以外には接続できない安全装置付き |
| `check_connection.py` | `SELECT 1` 等の読み取り専用の疎通確認（IT-AZ-01・02 相当） |

`with-azure-db.sh` は `DB_POOL_SIZE=5`・`DB_MAX_OVERFLOW=5`（共用の講義サーバー向け
推奨値。DS-DEC-46）を自動的に設定する。他のコマンドに使い回せる（例:
`../../scripts/azure-db/with-azure-db.sh uv run pytest -q tests/unit` のように
unit テストを Azure 接続で走らせることもできるが、**結合テスト（`tests/integration`）
は講義サーバーに対しては実行しないこと**（DS-DEC-44。共用サーバーへの負荷・
データ汚染を避けるため）。

## 設計との差分

設計仕様書追補 8.5・DS-DEC-45 は「`.env` の値の差し替えだけで切り替える」想定
だったが、本実装は `.env.azure`（資格情報のみを含む別ファイル）から実行時に
`DATABASE_URL` を組み立て、環境変数としてだけ子プロセスに渡す方式にした。
理由は次の2点を両立させるため。

1. `.env.azure` を編集・コピーしない（今回の作業指示の禁止事項）
2. 資格情報を含む `DATABASE_URL` をファイルに書き残さない（`.env` に貼り付けると
   ファイルに残ってしまう）

`.env` そのものは変更していない。ローカル開発に戻すときは、単に `with-azure-db.sh`
を経由せずに通常どおり起動すればよい（`.env` の `DATABASE_URL` がそのまま使われる）。
