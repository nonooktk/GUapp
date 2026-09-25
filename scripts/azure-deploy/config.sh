#!/usr/bin/env bash
# scripts/azure-deploy 共通設定（ADR-0004・設計仕様書公開追補 8 章）。
#
# 他のスクリプトはこのファイルを `source` して使う。単体では何もしない。
#   source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
#
# 値は環境変数で上書きできる（例: 名前が衝突した場合に GUAPP_NAME_SUFFIX="-1" を指定）。
# サブスクリプション・リソースグループ・リージョンは統括決定（2026-09-25）の固定値を既定にする。

set -euo pipefail

# --- サブスクリプション・リソースグループ・リージョン（統括決定。原則変更しない） ---
export GUAPP_SUBSCRIPTION_ID="${GUAPP_SUBSCRIPTION_ID:-9b680e6d-e5a6-4381-aad5-a30afcbc8459}"
export GUAPP_RESOURCE_GROUP="${GUAPP_RESOURCE_GROUP:-rg-001-gen12}"
export GUAPP_LOCATION="${GUAPP_LOCATION:-japaneast}"

# --- リソース名 ---
# App Service 名は *.azurewebsites.net でグローバルに一意。衝突した場合は
# GUAPP_NAME_SUFFIX="-1" のように設定して再実行する（設計仕様書公開追補 8.1・DS-DEC-55）。
GUAPP_NAME_SUFFIX="${GUAPP_NAME_SUFFIX:-}"
export GUAPP_PLAN_NAME="${GUAPP_PLAN_NAME:-asp-guapp-nonooktk${GUAPP_NAME_SUFFIX}}"
export GUAPP_WEB_APP_NAME="${GUAPP_WEB_APP_NAME:-app-guapp-web-nonooktk${GUAPP_NAME_SUFFIX}}"
export GUAPP_API_APP_NAME="${GUAPP_API_APP_NAME:-app-guapp-api-nonooktk${GUAPP_NAME_SUFFIX}}"

export GUAPP_SKU="${GUAPP_SKU:-B1}"
export GUAPP_WEB_RUNTIME="${GUAPP_WEB_RUNTIME:-NODE:24-lts}"
export GUAPP_API_RUNTIME="${GUAPP_API_RUNTIME:-PYTHON:3.13}"

export GUAPP_WEB_URL="https://${GUAPP_WEB_APP_NAME}.azurewebsites.net"
export GUAPP_API_URL="https://${GUAPP_API_APP_NAME}.azurewebsites.net"

# --- 講義 MySQL（ADR-0002。固定値。変更しない） ---
export GUAPP_DB_SERVER_NAME="gen12-mysql-pos"
export GUAPP_DB_HOST="gen12-mysql-pos.mysql.database.azure.com"
export GUAPP_DB_NAME="guapp_nonooktk"
# 講義 MySQL 自体のリソースグループ。web/api と同じ rg-001-gen12 だが、
# 将来変わった場合に備えて独立した変数にしておく
export GUAPP_DB_RESOURCE_GROUP="${GUAPP_DB_RESOURCE_GROUP:-$GUAPP_RESOURCE_GROUP}"

# App Service 上の CA 証明書ファイルの配置先（設計仕様書公開追補 8.4・DS-DEC-52）
export GUAPP_DB_SSL_CA_PATH_ON_APPSERVICE="/home/site/wwwroot/certs/azure-mysql-ca.pem"

# 講義サーバー接続時の DB プール推奨値（DS-DEC-46）
export GUAPP_DB_POOL_SIZE="${GUAPP_DB_POOL_SIZE:-5}"
export GUAPP_DB_MAX_OVERFLOW="${GUAPP_DB_MAX_OVERFLOW:-5}"

# --- 期間限定バナー（ADR-0004・DS-DEC-50） ---
export GUAPP_DEMO_PUBLIC_UNTIL="${GUAPP_DEMO_PUBLIC_UNTIL:-2026-10-09}"

# --- api の起動コマンド（DS-DEC-54。gunicorn 未導入のため暫定は uvicorn --workers） ---
export GUAPP_API_STARTUP_COMMAND="${GUAPP_API_STARTUP_COMMAND:-uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2}"
export GUAPP_WEB_STARTUP_COMMAND="${GUAPP_WEB_STARTUP_COMMAND:-node server.js}"
export GUAPP_WEBSITES_CONTAINER_START_TIME_LIMIT="${GUAPP_WEBSITES_CONTAINER_START_TIME_LIMIT:-600}"

# --- パス ---
GUAPP_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export GUAPP_SCRIPT_DIR
export GUAPP_REPO_ROOT
GUAPP_REPO_ROOT="$(cd "$GUAPP_SCRIPT_DIR/../.." && pwd)"
export GUAPP_API_DIR="$GUAPP_REPO_ROOT/apps/api"
export GUAPP_WEB_DIR="$GUAPP_REPO_ROOT/apps/web"
export GUAPP_CA_FILE="${GUAPP_CA_DIR:-$HOME/.config/guapp}/azure-mysql-ca.pem"

echo "[config] サブスクリプション: $GUAPP_SUBSCRIPTION_ID / リソースグループ: $GUAPP_RESOURCE_GROUP / リージョン: $GUAPP_LOCATION" >&2
echo "[config] plan=$GUAPP_PLAN_NAME web=$GUAPP_WEB_APP_NAME api=$GUAPP_API_APP_NAME" >&2

# 作成・変更系のスクリプトから呼ぶ確認プロンプト。read -p は非対話実行（CI 等）では
# 失敗させる（GUAPP_ASSUME_YES=1 で明示的にスキップできるようにする）。
guapp_confirm_azure_context() {
  echo "[confirm] 現在の Azure コンテキスト（az account show）:" >&2
  az account show --output table
  echo "[confirm] 上記のサブスクリプション・テナントが正しいこと、" >&2
  echo "[confirm] このあと操作するリソースグループが '$GUAPP_RESOURCE_GROUP' であることを確認してください。" >&2
  if [[ "${GUAPP_ASSUME_YES:-0}" == "1" ]]; then
    echo "[confirm] GUAPP_ASSUME_YES=1 のため確認をスキップします。" >&2
    return 0
  fi
  read -r -p "続行しますか？ (y/N): " REPLY
  case "$REPLY" in
    y|Y|yes|YES) return 0 ;;
    *) echo "[confirm] 中止しました。" >&2; exit 1 ;;
  esac
}
export -f guapp_confirm_azure_context
