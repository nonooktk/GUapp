#!/usr/bin/env bash
# 公開期間終了後、web・api の 2 App Service を停止する（削除はしない。ADR-0004 停止手順）。
# 再開は `az webapp start` またはポータルから行える。
#
# 冪等: 既に停止済みの App Service に対して実行してもエラーにならない。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./config.sh
source "$SCRIPT_DIR/config.sh"

guapp_confirm_azure_context
az account set --subscription "$GUAPP_SUBSCRIPTION_ID"

for app_name in "$GUAPP_WEB_APP_NAME" "$GUAPP_API_APP_NAME"; do
  echo "[90-stop] $app_name を停止します..."
  az webapp stop --name "$app_name" --resource-group "$GUAPP_RESOURCE_GROUP" --output none
done

echo "[90-stop] 完了。停止中は課金が抑えられるが、App Service Plan（$GUAPP_PLAN_NAME）自体の基本料金は発生し続ける。"
echo "[90-stop] 完全に不要になった場合は 99-delete.sh を実行すること（要事前承認・確認プロンプトあり）。"
echo "[90-stop] 再開する場合: az webapp start --name <app名> --resource-group $GUAPP_RESOURCE_GROUP"
