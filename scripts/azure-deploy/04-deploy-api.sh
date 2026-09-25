#!/usr/bin/env bash
# api（FastAPI）をビルドして zip デプロイする（設計仕様書公開追補 8.3・8.4・8.6）。
#
# 手順:
#   1. CA 証明書束ね（scripts/azure-db/fetch-ca.sh の出力）を apps/api/certs/ にコピーする
#      （DS-DEC-52。DB_SSL_CA_PATH は App Service 上のパスを指すよう 02-settings.sh で設定済み）
#   2. `uv export` で requirements.txt を生成する（コミットしない。DS-DEC-53）
#   3. 不要ファイルを除いた zip を作り、`az webapp deploy` で配置する
#
# 冪等: 毎回ゼロから requirements.txt・zip を作り直すため、何度実行しても同じ結果になる。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./config.sh
source "$SCRIPT_DIR/config.sh"

guapp_confirm_azure_context
az account set --subscription "$GUAPP_SUBSCRIPTION_ID"

if [[ ! -r "$GUAPP_CA_FILE" ]]; then
  echo "[04-deploy-api] エラー: CA 証明書が見つかりません: $GUAPP_CA_FILE" >&2
  echo "[04-deploy-api] 先に scripts/azure-db/fetch-ca.sh を実行してください。" >&2
  exit 1
fi

echo "[04-deploy-api] CA 証明書を apps/api/certs/ にコピーします（秘密情報ではない。8.4 参照）..."
mkdir -p "$GUAPP_API_DIR/certs"
cp "$GUAPP_CA_FILE" "$GUAPP_API_DIR/certs/azure-mysql-ca.pem"
chmod 644 "$GUAPP_API_DIR/certs/azure-mysql-ca.pem"

echo "[04-deploy-api] requirements.txt を生成します（uv export。コミットしない。DS-DEC-53）..."
(cd "$GUAPP_API_DIR" && uv export --format requirements-txt --no-hashes --no-dev -o requirements.txt)

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
ZIP_PATH="$TMP_DIR/guapp-api.zip"

echo "[04-deploy-api] デプロイ用 zip を作成します: $ZIP_PATH"
(
  cd "$GUAPP_API_DIR"
  zip -rq "$ZIP_PATH" . \
    -x '.venv/*' \
    -x 'tests/*' \
    -x '.pytest_cache/*' \
    -x '.ruff_cache/*' \
    -x '.mail-outbox/*' \
    -x '__pycache__/*' \
    -x '*/__pycache__/*' \
    -x '.git/*' \
    -x '.env' \
    -x '.env.*'
)

echo "[04-deploy-api] $GUAPP_API_APP_NAME へデプロイします..."
az webapp deploy \
  --name "$GUAPP_API_APP_NAME" \
  --resource-group "$GUAPP_RESOURCE_GROUP" \
  --src-path "$ZIP_PATH" \
  --type zip

echo "[04-deploy-api] 完了。ヘルスチェック（/api/v1/health は内部トークン不要。本編 4.1）:"
echo "[04-deploy-api]   curl -i ${GUAPP_API_URL}/api/v1/health"
echo "[04-deploy-api] それ以外の api エンドポイントは X-Internal-Token が無いと 401 になる（想定どおり。7.2 参照）。"
