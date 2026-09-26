#!/usr/bin/env bash
# 講義の Azure MySQL（gen12-mysql-pos / guapp_nonooktk）に接続する環境変数を
# 組み立て、指定したコマンドをその環境変数付きで実行するラッパー。
#
# 使い方:
#   scripts/azure-db/with-azure-db.sh <コマンド...>
#   例: cd apps/api && ../../scripts/azure-db/with-azure-db.sh uv run alembic upgrade head
#
# 資格情報の扱い（最重要。詳細は scripts/azure-db/README.md）:
#   - apps/api/.env.azure（DB_USER・DB_PASSWORD の2行、権限600）だけを読む
#   - 値は一切 echo/print せず、シェル変数に読み込んで環境変数としてのみ
#     子プロセス（渡されたコマンド）に渡す
#   - DATABASE_URL の組み立て・検証はすべて Python の標準入力（環境変数経由）で行い、
#     コマンドライン引数には一切乗せない（ps で見えないようにするため）
#
# 安全装置:
#   - ホスト・DB 名は環境変数で上書きできない固定値（下記参照）。組み立てた
#     DATABASE_URL のホスト・DB 名がこの固定値と食い違えば中止する
#     （URL 組み立てロジックのバグ・typo を検出するための最終確認）
#   - CA 証明書ファイルが無ければ中止（先に scripts/azure-db/fetch-ca.sh を実行するよう案内）
#
# 設計との差分（DS-DEC-45 からの実装上の変更。詳細は完了報告参照）:
#   設計は「.env の値の差し替えだけで切り替える」想定だったが、本スクリプトは
#   .env を書き換えず、.env.azure の資格情報から実行時にだけ DATABASE_URL を
#   組み立てて子プロセスに渡す方式にした（.env.azure を編集しない禁止事項と、
#   資格情報を画面・ファイルに出さない要件を同時に満たすため）。

set -euo pipefail

if [[ $# -eq 0 ]]; then
  echo "使い方: $0 <コマンド...>" >&2
  exit 64
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_AZURE_FILE="$REPO_ROOT/apps/api/.env.azure"

# ホスト・DB 名は安全装置の要である。誤って別サーバー・別スキーマに繋がないよう、
# 環境変数での上書きを許可しない固定値にする（GUAPP_AZURE_DB_HOST/NAME という
# 上書き変数を用意すると、下の検証もその変数を参照することになり安全装置が
# 意味を失うため、値そのものをここに直接書く）
readonly GUAPP_AZURE_DB_HOST="gen12-mysql-pos.mysql.database.azure.com"
readonly GUAPP_AZURE_DB_NAME="guapp_nonooktk"
export GUAPP_AZURE_DB_HOST GUAPP_AZURE_DB_NAME
GUAPP_AZURE_DB_PORT="${GUAPP_AZURE_DB_PORT:-3306}"
GUAPP_CA_DIR="${GUAPP_CA_DIR:-$HOME/.config/guapp}"
CA_PATH="$GUAPP_CA_DIR/azure-mysql-ca.pem"
GUAPP_AZURE_DB_POOL_SIZE="${GUAPP_AZURE_DB_POOL_SIZE:-5}"
GUAPP_AZURE_DB_MAX_OVERFLOW="${GUAPP_AZURE_DB_MAX_OVERFLOW:-5}"
# 第1案（DATABASE_URL の ssl_ca クエリ）で実接続に成功したため（DS-DEC-42）、
# 第2案（connect_args + ssl.SSLContext）は実装していない。このスクリプトも
# 第1案のみをサポートする

if [[ ! -r "$ENV_AZURE_FILE" ]]; then
  echo "エラー: $ENV_AZURE_FILE が読めません（存在しない、または権限不足）。" >&2
  exit 1
fi

if [[ ! -r "$CA_PATH" ]]; then
  echo "エラー: CA 証明書が見つかりません: $CA_PATH" >&2
  echo "先に scripts/azure-db/fetch-ca.sh を実行してください。" >&2
  exit 1
fi

# --- .env.azure から DB_USER・DB_PASSWORD を読む（値は表示しない） ---
DB_USER="$(grep -E '^DB_USER=' "$ENV_AZURE_FILE" | head -n1 | cut -d= -f2-)"
DB_PASSWORD="$(grep -E '^DB_PASSWORD=' "$ENV_AZURE_FILE" | head -n1 | cut -d= -f2-)"

if [[ -z "$DB_USER" || -z "$DB_PASSWORD" ]]; then
  echo "エラー: .env.azure から DB_USER または DB_PASSWORD を読み取れませんでした。" >&2
  exit 1
fi

# --- パスワードを URL エンコード（環境変数経由。標準出力には値を出さない） ---
ENCODED_PASSWORD="$(DB_PASSWORD="$DB_PASSWORD" python3 -c '
import os
import urllib.parse
print(urllib.parse.quote(os.environ["DB_PASSWORD"], safe=""))
')"

DATABASE_URL="mysql+asyncmy://${DB_USER}:${ENCODED_PASSWORD}@${GUAPP_AZURE_DB_HOST}:${GUAPP_AZURE_DB_PORT}/${GUAPP_AZURE_DB_NAME}?ssl_ca=${CA_PATH}"

# 使い終わった生パスワード・エンコード済みパスワードの変数はもう使わないので消す
unset DB_PASSWORD
unset ENCODED_PASSWORD

# --- 安全装置: 組み立てた URL のホスト・DB 名を検証する（値は表示しない）。
# GUAPP_AZURE_DB_HOST/NAME は上で export 済みの固定値（readonly）を使う ---
DATABASE_URL="$DATABASE_URL" python3 -c '
import os
import sys
from urllib.parse import urlsplit

url = os.environ["DATABASE_URL"]
parts = urlsplit(url)
host = parts.hostname or ""
db = (parts.path or "").lstrip("/").split("?")[0]

expected_host = os.environ["GUAPP_AZURE_DB_HOST"]
expected_db = os.environ["GUAPP_AZURE_DB_NAME"]

if host != expected_host:
    print(f"安全装置: ホストが {expected_host!r} ではありません: {host!r}", file=sys.stderr)
    sys.exit(1)
if db != expected_db:
    print(f"安全装置: DB 名が {expected_db!r} ではありません: {db!r}", file=sys.stderr)
    sys.exit(1)
' || { echo "安全装置により中止しました。DATABASE_URL の組み立てを見直してください。" >&2; exit 1; }

export DATABASE_URL
export DB_POOL_SIZE="$GUAPP_AZURE_DB_POOL_SIZE"
export DB_MAX_OVERFLOW="$GUAPP_AZURE_DB_MAX_OVERFLOW"
export APP_ENV="${APP_ENV:-development}"

echo "[with-azure-db] ${GUAPP_AZURE_DB_HOST}:${GUAPP_AZURE_DB_PORT}/${GUAPP_AZURE_DB_NAME} に向けて実行します（pool=${DB_POOL_SIZE}/${DB_MAX_OVERFLOW}）: $*" >&2

exec "$@"
