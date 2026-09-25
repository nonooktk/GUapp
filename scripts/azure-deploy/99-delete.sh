#!/usr/bin/env bash
# GUapp のレビュー用リソース（App Service Plan・web・api）を削除する。
# 講義 MySQL 側の DB ファイアウォール規則（guapp-appsvc-*）も削除する。
# 講義 MySQL 自体・スキーマ（guapp_nonooktk）・共用のリソースグループは削除しない。
#
# **破壊的操作。実行前に必ず確認プロンプトを出す。** GUAPP_ASSUME_YES=1 でもこのスクリプトの
# 確認だけは省略しない（誤操作防止のため guapp_confirm_azure_context とは別に確認する）。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./config.sh
source "$SCRIPT_DIR/config.sh"

guapp_confirm_azure_context
az account set --subscription "$GUAPP_SUBSCRIPTION_ID"

echo "[99-delete] 次を削除します:"
echo "[99-delete]   - App Service: $GUAPP_WEB_APP_NAME"
echo "[99-delete]   - App Service: $GUAPP_API_APP_NAME"
echo "[99-delete]   - App Service Plan: $GUAPP_PLAN_NAME"
echo "[99-delete]   - MySQL ファイアウォール規則: guapp-appsvc-*（$GUAPP_DB_SERVER_NAME 上）"
echo "[99-delete] 削除しないもの: リソースグループ $GUAPP_RESOURCE_GROUP 自体、講義 MySQL サーバー・スキーマ"
read -r -p "本当に削除しますか？ この操作は取り消せません。'delete' と入力してください: " CONFIRM_TEXT
if [[ "$CONFIRM_TEXT" != "delete" ]]; then
  echo "[99-delete] 入力が一致しないため中止しました。"
  exit 1
fi

for app_name in "$GUAPP_WEB_APP_NAME" "$GUAPP_API_APP_NAME"; do
  if az webapp show --name "$app_name" --resource-group "$GUAPP_RESOURCE_GROUP" --output none 2>/dev/null; then
    echo "[99-delete] App Service '$app_name' を削除します..."
    az webapp delete --name "$app_name" --resource-group "$GUAPP_RESOURCE_GROUP"
  else
    echo "[99-delete] App Service '$app_name' は既に存在しません（スキップ）。"
  fi
done

if az appservice plan show --name "$GUAPP_PLAN_NAME" --resource-group "$GUAPP_RESOURCE_GROUP" --output none 2>/dev/null; then
  echo "[99-delete] App Service Plan '$GUAPP_PLAN_NAME' を削除します..."
  az appservice plan delete --name "$GUAPP_PLAN_NAME" --resource-group "$GUAPP_RESOURCE_GROUP" --yes
else
  echo "[99-delete] App Service Plan '$GUAPP_PLAN_NAME' は既に存在しません（スキップ）。"
fi

echo "[99-delete] MySQL ファイアウォール規則 guapp-appsvc-* を削除します..."
RULE_NAMES="$(az mysql flexible-server firewall-rule list \
  --resource-group "$GUAPP_DB_RESOURCE_GROUP" \
  --name "$GUAPP_DB_SERVER_NAME" \
  --query "[?starts_with(name, 'guapp-appsvc-')].name" \
  --output tsv || true)"

if [[ -z "$RULE_NAMES" ]]; then
  echo "[99-delete] guapp-appsvc-* の規則は見つかりませんでした（スキップ）。"
else
  while IFS= read -r rule_name; do
    [[ -z "$rule_name" ]] && continue
    echo "[99-delete] ファイアウォール規則 '$rule_name' を削除します..."
    az mysql flexible-server firewall-rule delete \
      --resource-group "$GUAPP_DB_RESOURCE_GROUP" \
      --name "$GUAPP_DB_SERVER_NAME" \
      --rule-name "$rule_name" \
      --yes
  done <<< "$RULE_NAMES"
fi

echo "[99-delete] 完了。"
