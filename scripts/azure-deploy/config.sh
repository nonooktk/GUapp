#!/usr/bin/env bash
# scripts/azure-deploy 共通設定（ADR-0004・設計仕様書公開追補 8 章）。
#
# 他のスクリプトはこのファイルを `source` して使う。単体では何もしない。
#   source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"
#
# 値は環境変数で上書きできる（例: 名前が衝突した場合に GUAPP_NAME_SUFFIX="-1" を指定）。
# サブスクリプション・リソースグループ・リージョンは統括決定（2026-09-25）の固定値を既定にする。
#
# 配備先の切り替え（2026-10-10 追加）:
#   GUAPP_TARGET=nonooktk（既定）: 従来の app-guapp-web/api-nonooktk（B1）。値は従来と同じ。
#   GUAPP_TARGET=tech0          : 既存の app-tech0-gen12-01-fe / -be（F1 無料プラン）へ配備する。
#                                 Basic 認証と期間限定バナーは付けない。
# 個別の環境変数（GUAPP_PLAN_NAME など）を指定した場合は、ターゲット既定値より優先する。

set -euo pipefail

# --- 配備先ターゲット ---
export GUAPP_TARGET="${GUAPP_TARGET:-nonooktk}"
case "$GUAPP_TARGET" in
  nonooktk)
    _GUAPP_D_PLAN="asp-guapp-nonooktk"
    _GUAPP_D_WEB="app-guapp-web-nonooktk"
    _GUAPP_D_API="app-guapp-api-nonooktk"
    _GUAPP_D_SKU="B1"
    _GUAPP_D_CA_PATH="/home/site/wwwroot/certs/azure-mysql-ca.pem"
    _GUAPP_D_WORKERS="2"
    _GUAPP_D_FW_INDEX="1"
    _GUAPP_D_BASIC_AUTH="1"
    _GUAPP_D_DEMO_UNTIL="2026-10-09"
    _GUAPP_USE_SUFFIX=1
    ;;
  tech0)
    _GUAPP_D_PLAN="asp-tech0-gen12-01"
    _GUAPP_D_WEB="app-tech0-gen12-01-fe"
    _GUAPP_D_API="app-tech0-gen12-01-be"
    _GUAPP_D_SKU="F1"
    # 新しい Kudu は配備物を圧縮して /tmp に展開するため wwwroot に certs/ が無い。配備で消えない /home/site/certs に置く（01b が置く）
    _GUAPP_D_CA_PATH="/home/site/certs/azure-mysql-ca.pem"
    # F1 は 1 GB メモリ・1 日の CPU 時間上限があるためワーカーは 1
    _GUAPP_D_WORKERS="1"
    # 並行運用中は既存の guapp-appsvc-1〜25 を残すため 26 から
    _GUAPP_D_FW_INDEX="26"
    _GUAPP_D_BASIC_AUTH="0"
    _GUAPP_D_DEMO_UNTIL=""
    _GUAPP_USE_SUFFIX=0
    ;;
  *)
    echo "[config] エラー: GUAPP_TARGET は nonooktk または tech0 を指定してください: '$GUAPP_TARGET'" >&2
    exit 1
    ;;
esac

# --- サブスクリプション・リソースグループ・リージョン（統括決定。原則変更しない） ---
export GUAPP_SUBSCRIPTION_ID="${GUAPP_SUBSCRIPTION_ID:-9b680e6d-e5a6-4381-aad5-a30afcbc8459}"
export GUAPP_RESOURCE_GROUP="${GUAPP_RESOURCE_GROUP:-rg-001-gen12}"
export GUAPP_LOCATION="${GUAPP_LOCATION:-japaneast}"

# --- リソース名 ---
# App Service 名は *.azurewebsites.net でグローバルに一意。衝突した場合は
# GUAPP_NAME_SUFFIX="-1" のように設定して再実行する（設計仕様書公開追補 8.1・DS-DEC-55）。
GUAPP_NAME_SUFFIX="${GUAPP_NAME_SUFFIX:-}"
# tech0 ターゲットは既存アプリへの配備のため GUAPP_NAME_SUFFIX は付けない。
if [[ "$_GUAPP_USE_SUFFIX" != "1" ]]; then GUAPP_NAME_SUFFIX=""; fi
export GUAPP_PLAN_NAME="${GUAPP_PLAN_NAME:-${_GUAPP_D_PLAN}${GUAPP_NAME_SUFFIX}}"
export GUAPP_WEB_APP_NAME="${GUAPP_WEB_APP_NAME:-${_GUAPP_D_WEB}${GUAPP_NAME_SUFFIX}}"
export GUAPP_API_APP_NAME="${GUAPP_API_APP_NAME:-${_GUAPP_D_API}${GUAPP_NAME_SUFFIX}}"

export GUAPP_SKU="${GUAPP_SKU:-$_GUAPP_D_SKU}"
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

# App Service 上の CA 証明書ファイルの配置先（設計仕様書公開追補 8.4・DS-DEC-52・11.5）
# 既定はターゲットごとに異なる（nonooktk は wwwroot 配下、tech0 は /home/site/certs）。
export GUAPP_DB_SSL_CA_PATH_ON_APPSERVICE="${GUAPP_DB_SSL_CA_PATH_ON_APPSERVICE:-$_GUAPP_D_CA_PATH}"

# 講義サーバー接続時の DB プール推奨値（DS-DEC-46）
export GUAPP_DB_POOL_SIZE="${GUAPP_DB_POOL_SIZE:-5}"
export GUAPP_DB_MAX_OVERFLOW="${GUAPP_DB_MAX_OVERFLOW:-5}"

# --- 期間限定バナー（ADR-0004・DS-DEC-50） ---
# 空にすると DEMO_PUBLIC_UNTIL を設定せず、帯を出さない（tech0 の既定）。
export GUAPP_DEMO_PUBLIC_UNTIL="${GUAPP_DEMO_PUBLIC_UNTIL-$_GUAPP_D_DEMO_UNTIL}"

# --- Basic 認証（1: 設定する / 0: 設定しない。tech0 の既定は 0） ---
export GUAPP_ENABLE_BASIC_AUTH="${GUAPP_ENABLE_BASIC_AUTH:-$_GUAPP_D_BASIC_AUTH}"

# --- MySQL ファイアウォール規則名（guapp-appsvc-<連番>）の開始番号（03-db-firewall.sh） ---
export GUAPP_FIREWALL_START_INDEX="${GUAPP_FIREWALL_START_INDEX:-$_GUAPP_D_FW_INDEX}"

# --- api の起動コマンド（DS-DEC-54。gunicorn 未導入のため暫定は uvicorn --workers） ---
export GUAPP_API_STARTUP_COMMAND="${GUAPP_API_STARTUP_COMMAND:-uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${_GUAPP_D_WORKERS} --no-server-header}"
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

# --- P2（会員・管理画面・AI アシスタント）の配備で使う手元のファイル（2026-10-21 追加） ---
# OpenAI のキーを読む元のファイル。02-settings.sh が OPENAI_API_KEY= の行だけを読む（値は表示しない）。
export GUAPP_OPENAI_ENV_FILE="${GUAPP_OPENAI_ENV_FILE:-$HOME/GUapp/apps/api/.env}"
# 管理者の初期パスワード（SEED_STAFF_PASSWORD=）を置くファイル。02-settings.sh が未作成のときだけ作り、
# 06-migrate-seed.sh --seed-p2 が読む。App Service には入れない。.gitignore の .env.* で除外される。
export GUAPP_ADMIN_ENV_FILE="${GUAPP_ADMIN_ENV_FILE:-$GUAPP_API_DIR/.env.admin}"

echo "[config] サブスクリプション: $GUAPP_SUBSCRIPTION_ID / リソースグループ: $GUAPP_RESOURCE_GROUP / リージョン: $GUAPP_LOCATION" >&2
echo "[config] target=$GUAPP_TARGET sku=$GUAPP_SKU basic_auth=$GUAPP_ENABLE_BASIC_AUTH" >&2
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
unset _GUAPP_D_CA_PATH _GUAPP_D_PLAN _GUAPP_D_WEB _GUAPP_D_API _GUAPP_D_SKU _GUAPP_D_WORKERS _GUAPP_D_FW_INDEX _GUAPP_D_BASIC_AUTH _GUAPP_D_DEMO_UNTIL _GUAPP_USE_SUFFIX
