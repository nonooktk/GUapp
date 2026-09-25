#!/usr/bin/env bash
# App Service Plan（B1）と web・api の 2 App Service を作成する（設計仕様書公開追補 8.1・8.3）。
#
# 冪等: 既存のリソースがあれば作成をスキップし、設定（Always On・HTTPS Only・
# 最小 TLS・起動コマンド・アプリ設定の一部）だけを毎回上書きする。
#
# 使い方:
#   scripts/azure-deploy/01-create.sh
#
# 前提: `az login --tenant admintech0jp.onmicrosoft.com` 済みであること。
# このスクリプトは作成・変更系の `az` コマンドを含むため、実行前に必ず
# Azure のコンテキスト（サブスクリプション・リソースグループ）を表示して確認を求める。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./config.sh
source "$SCRIPT_DIR/config.sh"

guapp_confirm_azure_context

az account set --subscription "$GUAPP_SUBSCRIPTION_ID"

echo "[01-create] リソースグループ '$GUAPP_RESOURCE_GROUP' の存在を確認します（作成はしない。既存の共用リソースグループのため）..."
if ! az group show --name "$GUAPP_RESOURCE_GROUP" --output none 2>/dev/null; then
  echo "[01-create] エラー: リソースグループ '$GUAPP_RESOURCE_GROUP' が見つかりません。" >&2
  echo "[01-create] このリソースグループは受講生で共用のため、本スクリプトでは作成しません。統括に確認してください。" >&2
  exit 1
fi

echo "[01-create] App Service Plan '$GUAPP_PLAN_NAME' を確認します..."
if az appservice plan show --name "$GUAPP_PLAN_NAME" --resource-group "$GUAPP_RESOURCE_GROUP" --output none 2>/dev/null; then
  echo "[01-create] 既存のプランを使用します（作成をスキップ）。"
else
  echo "[01-create] プランを作成します（Linux・$GUAPP_SKU）..."
  az appservice plan create \
    --name "$GUAPP_PLAN_NAME" \
    --resource-group "$GUAPP_RESOURCE_GROUP" \
    --location "$GUAPP_LOCATION" \
    --sku "$GUAPP_SKU" \
    --is-linux
fi

create_or_reuse_webapp() {
  local app_name="$1" runtime="$2"
  if az webapp show --name "$app_name" --resource-group "$GUAPP_RESOURCE_GROUP" --output none 2>/dev/null; then
    echo "[01-create] 既存の App Service '$app_name' を使用します（作成をスキップ）。"
  else
    echo "[01-create] App Service '$app_name'（runtime=$runtime）を作成します..."
    az webapp create \
      --name "$app_name" \
      --resource-group "$GUAPP_RESOURCE_GROUP" \
      --plan "$GUAPP_PLAN_NAME" \
      --runtime "$runtime"
  fi
}

create_or_reuse_webapp "$GUAPP_WEB_APP_NAME" "$GUAPP_WEB_RUNTIME"
create_or_reuse_webapp "$GUAPP_API_APP_NAME" "$GUAPP_API_RUNTIME"

echo "[01-create] 共通設定（Always On・HTTPS Only・最小 TLS 1.2）を適用します..."
for app_name in "$GUAPP_WEB_APP_NAME" "$GUAPP_API_APP_NAME"; do
  az webapp update \
    --name "$app_name" \
    --resource-group "$GUAPP_RESOURCE_GROUP" \
    --https-only true \
    --output none
  az webapp config set \
    --name "$app_name" \
    --resource-group "$GUAPP_RESOURCE_GROUP" \
    --always-on true \
    --min-tls-version 1.2 \
    --output none
done

echo "[01-create] api の起動コマンドを設定します（DS-DEC-54: gunicorn 未導入のため uvicorn --workers を暫定使用）..."
az webapp config set \
  --name "$GUAPP_API_APP_NAME" \
  --resource-group "$GUAPP_RESOURCE_GROUP" \
  --startup-file "$GUAPP_API_STARTUP_COMMAND" \
  --output none

echo "[01-create] web の起動コマンドと PORT 関連の設定をします（standalone の server.js）..."
az webapp config set \
  --name "$GUAPP_WEB_APP_NAME" \
  --resource-group "$GUAPP_RESOURCE_GROUP" \
  --startup-file "$GUAPP_WEB_STARTUP_COMMAND" \
  --output none
az webapp config appsettings set \
  --name "$GUAPP_WEB_APP_NAME" \
  --resource-group "$GUAPP_RESOURCE_GROUP" \
  --settings \
    WEBSITES_PORT=3000 \
    PORT=3000 \
    WEBSITES_CONTAINER_START_TIME_LIMIT="$GUAPP_WEBSITES_CONTAINER_START_TIME_LIMIT" \
  --output none

echo "[01-create] 完了。web: $GUAPP_WEB_URL / api: $GUAPP_API_URL"
echo "[01-create] 次は 02-settings.sh でアプリ設定（環境変数・秘密）を投入してください。"
