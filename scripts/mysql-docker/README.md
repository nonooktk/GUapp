# scripts/mysql-docker — Mac（Docker Desktop）でのローカル MySQL 8.4

Docker Desktop がある Mac 向けの起動・停止手順。設定値はリポジトリ直下の `docker-compose.yml`（DS-DEC-25 準拠。utf8mb4 / UTC）そのものを使う。`guapp_test`（IT 用）の作成は既存の `scripts/mysql-local/docker-init/01_create_test_db.sql` が `docker-compose.yml` の初期化 SQL として流用されている（Windows 版と Mac 版で同じ初期化 SQL を共有するため、`scripts/mysql-docker/` に SQL を複製していない）。

## 前提

- Docker Desktop が起動していること
- リポジトリルートに `.env` があり `MYSQL_PASSWORD=<任意の値>` が書かれていること（`.env` はコミット禁止・gitignore 済み）

```bash
# 初回のみ: リポジトリルートに .env を作る
cd /path/to/GUapp
echo "MYSQL_PASSWORD=<任意のローカル専用パスワード>" > .env
```

## 起動

```bash
cd /path/to/GUapp
docker compose up -d
docker compose ps          # guapp-mysql が healthy になるまで待つ（初回は数十秒）
```

`apps/api/.env` の `DATABASE_URL` / `DATABASE_URL_TEST` は次の形にする（`<MYSQL_PASSWORD>` は `.env` の値）:

```
DATABASE_URL=mysql+asyncmy://guapp:<MYSQL_PASSWORD>@127.0.0.1:3306/guapp
DATABASE_URL_TEST=mysql+asyncmy://guapp:<MYSQL_PASSWORD>@127.0.0.1:3306/guapp_test
```

## 停止

```bash
docker compose stop      # コンテナを止める（データは volume に残る）
```

## 完全に作り直す（データを消す）

```bash
docker compose down -v   # コンテナ削除 + guapp-mysql-data ボリューム削除
docker compose up -d     # 作り直し（初期化 SQL が再実行される）
```

## 再開（PC 再起動後など）

```bash
docker compose up -d     # 既存コンテナ・データを使って再起動
```

## ポート衝突時（3306 が使用中）

`docker-compose.yml` の `ports` を `"127.0.0.1:3307:3306"` に変更し、`DATABASE_URL`（api）のポートも 3307 に合わせる。

## トラブルシュート

| 症状 | 対処 |
| --- | --- |
| `docker compose up -d` が `MYSQL_PASSWORD を .env に設定してください` で止まる | リポジトリルートに `.env` が無い、または `MYSQL_PASSWORD` 未設定 |
| `docker compose ps` の STATUS がいつまでも `starting` | `docker compose logs mysql` でエラーを確認。初回はイメージ pull とデータディレクトリ初期化で時間がかかる |
| `guapp_test` に接続できない | 初期化 SQL は初回起動時のみ実行される。既存ボリュームがある状態で SQL を変えても反映されないため、反映するには `docker compose down -v` してから起動し直す |
