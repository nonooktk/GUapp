#!/usr/bin/env bash
# 01-create.sh と同じ設定を、既存アプリに適用する版。プランと Always On は扱わない。
#
# プラン・App Service の作成はしない。既存の web・api（tech0 ターゲットなら
# app-tech0-gen12-01-fe / -be、F1 無料プラン）に対して次だけ行う。
#   - HTTPS Only・最小 TLS 1.2（Always On は F1 では設定できないため付けない）
#   - ランタイム（linux-fx-version）の明示（api は PYTHON|3.13、web は NODE|24-lts）
#   - 起動コマンド（api・web）
#   - api: SCM_DO_BUILD_DURING_DEPLOYMENT=true
#   - web: WEBSITES_PORT=3000・PORT=3000・WEBSITES_CONTAINER_START_TIME_LIMIT
#
# 使い方:
#   GUAPP_TARGET=tech0 scripts/azure-deploy/01b-configure-existing.sh
#
# 実行前に az account show を表示して確認を求める。2 つのアプリが存在しなければ止まる。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./config.sh
source "$SCRIPT_DIR/config.sh"

guapp_confirm_azure_context
az account set --subscription "$GUAPP_SUBSCRIPTION_ID"

echo "[01b] 既存アプリの存在を確認します（作成はしない）..."
for app_name in "$GUAPP_WEB_APP_NAME" "$GUAPP_API_APP_NAME"; do
  if ! az webapp show --name "$app_name" --resource-group "$GUAPP_RESOURCE_GROUP" --output none 2>/dev/null; then
    echo "[01b] エラー: App Service '$app_name' が見つかりません（リソースグループ: $GUAPP_RESOURCE_GROUP）。" >&2
    echo "[01b] 本スクリプトはアプリを作成しません。名前と GUAPP_TARGET を確認してください。" >&2
    exit 1
  fi
done

# config.sh の "PYTHON:3.13" 形式を az の linux-fx-version 形式 "PYTHON|3.13" に変換する
WEB_FX_VERSION="${GUAPP_WEB_RUNTIME//:/|}"
API_FX_VERSION="${GUAPP_API_RUNTIME//:/|}"

echo "[01b] 共通設定（HTTPS Only・最小 TLS 1.2）を適用します（Always On は付けません）..."
for app_name in "$GUAPP_WEB_APP_NAME" "$GUAPP_API_APP_NAME"; do
  az webapp update \
    --name "$app_name" \
    --resource-group "$GUAPP_RESOURCE_GROUP" \
    --https-only true \
    --output none
  az webapp config set \
    --name "$app_name" \
    --resource-group "$GUAPP_RESOURCE_GROUP" \
    --min-tls-version 1.2 \
    --output none
done

echo "[01b] ランタイムを明示します（api=$API_FX_VERSION / web=$WEB_FX_VERSION）..."
az webapp config set \
  --name "$GUAPP_API_APP_NAME" \
  --resource-group "$GUAPP_RESOURCE_GROUP" \
  --linux-fx-version "$API_FX_VERSION" \
  --output none
az webapp config set \
  --name "$GUAPP_WEB_APP_NAME" \
  --resource-group "$GUAPP_RESOURCE_GROUP" \
  --linux-fx-version "$WEB_FX_VERSION" \
  --output none

echo "[01b] api の起動コマンドを設定します（$GUAPP_API_STARTUP_COMMAND）..."
az webapp config set \
  --name "$GUAPP_API_APP_NAME" \
  --resource-group "$GUAPP_RESOURCE_GROUP" \
  --startup-file "$GUAPP_API_STARTUP_COMMAND" \
  --output none

echo "[01b] api のビルド自動化（Oryx による pip install）を有効にします..."
az webapp config appsettings set \
  --name "$GUAPP_API_APP_NAME" \
  --resource-group "$GUAPP_RESOURCE_GROUP" \
  --settings SCM_DO_BUILD_DURING_DEPLOYMENT=true \
  --output none

echo "[01b] web の起動コマンドと PORT 関連の設定をします（standalone の server.js）..."
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

echo "[01b] 完了。web: $GUAPP_WEB_URL / api: $GUAPP_API_URL"
echo "[01b] 次は 02-settings.sh でアプリ設定（環境変数・秘密）を投入してください。"
