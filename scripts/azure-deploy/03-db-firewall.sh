#!/usr/bin/env bash
# api の送信 IP（possibleOutboundIpAddresses）を、講義 MySQL（gen12-mysql-pos）の
# ファイアウォールに追加する（設計仕様書公開追補 8 章・ADR-0002 の方針を継続）。
#
# 「Azure サービスからのアクセスをすべて許可」は共用サーバーの設定全体を変えてしまうため
# 使わない。api の送信 IP だけを 1 つずつ、専用の規則名（guapp-appsvc-<連番>）で追加する。
# 他の受講生の規則には一切触れない。
#
# 冪等: 同じ規則名に対する再実行は上書きになるだけで、規則が増殖しない。
# IP の数が減った場合に古い規則（例: guapp-appsvc-2 が不要になった）を消す処理はしない
# （共用サーバーの規則を誤って消すリスクを避けるため。不要な規則は統括が手動で確認して消す）。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./config.sh
source "$SCRIPT_DIR/config.sh"

guapp_confirm_azure_context
az account set --subscription "$GUAPP_SUBSCRIPTION_ID"

echo "[03-db-firewall] api ($GUAPP_API_APP_NAME) の送信可能 IP を取得します..."
IPS_CSV="$(az webapp show \
  --name "$GUAPP_API_APP_NAME" \
  --resource-group "$GUAPP_RESOURCE_GROUP" \
  --query "possibleOutboundIpAddresses" \
  --output tsv)"

if [[ -z "$IPS_CSV" ]]; then
  echo "[03-db-firewall] エラー: possibleOutboundIpAddresses が取得できませんでした。" >&2
  exit 1
fi

IFS=',' read -r -a IPS <<< "$IPS_CSV"
echo "[03-db-firewall] ${#IPS[@]} 件の IP を取得しました。講義 MySQL '$GUAPP_DB_SERVER_NAME' に規則を追加します..."

index=1
for ip in "${IPS[@]}"; do
  rule_name="guapp-appsvc-${index}"
  echo "[03-db-firewall] ${rule_name}: ${ip}"
  az mysql flexible-server firewall-rule create \
    --resource-group "$GUAPP_DB_RESOURCE_GROUP" \
    --name "$GUAPP_DB_SERVER_NAME" \
    --rule-name "$rule_name" \
    --start-ip-address "$ip" \
    --end-ip-address "$ip" \
    --output none
  index=$((index + 1))
done

echo "[03-db-firewall] 完了。追加・更新した規則: guapp-appsvc-1 〜 guapp-appsvc-$((index - 1))"
echo "[03-db-firewall] 確認: az mysql flexible-server firewall-rule list --resource-group $GUAPP_DB_RESOURCE_GROUP --name $GUAPP_DB_SERVER_NAME --query \"[?starts_with(name, 'guapp-appsvc-')]\" --output table"
