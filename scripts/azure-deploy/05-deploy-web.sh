#!/usr/bin/env bash
# web（Next.js）を standalone ビルドして zip デプロイする（設計仕様書公開追補 8.3・8.6）。
#
# ビルド時の環境変数（API_BASE_URL 等）はダミー値でよい。`getEnv()`（apps/web/lib/server/env.ts）は
# 実行時（App Service 上のプロセスが最初のリクエストを受けたとき）に一度だけ本物の環境変数を
# 読むため、ビルド時の値はビルドを通すためだけのプレースホルダーで構わない
# （ローカル standalone 起動での確認と同じ挙動。本タスクの完了条件の curl 確認で検証済み）。
#
# 冪等: 毎回ビルドからやり直すため、何度実行しても同じ結果になる。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./config.sh
source "$SCRIPT_DIR/config.sh"

guapp_confirm_azure_context
az account set --subscription "$GUAPP_SUBSCRIPTION_ID"

echo "[05-deploy-web] 依存関係をインストールします..."
(cd "$GUAPP_WEB_DIR" && pnpm install --frozen-lockfile)

echo "[05-deploy-web] ビルドします（standalone 出力。next.config.ts の output: \"standalone\"）..."
(
  cd "$GUAPP_WEB_DIR"
  API_BASE_URL="http://build-time-placeholder:8000" \
  INTERNAL_TOKEN="build-time-placeholder-token" \
  IMAGE_BASE_URL="http://build-time-placeholder:3000" \
  pnpm build
)

STANDALONE_DIR="$GUAPP_WEB_DIR/.next/standalone"
if [[ ! -f "$STANDALONE_DIR/server.js" ]]; then
  echo "[05-deploy-web] エラー: $STANDALONE_DIR/server.js が生成されませんでした。" >&2
  exit 1
fi

echo "[05-deploy-web] 静的ファイル・public を standalone 配下にコピーします..."
mkdir -p "$STANDALONE_DIR/.next"
rm -rf "$STANDALONE_DIR/.next/static"
cp -r "$GUAPP_WEB_DIR/.next/static" "$STANDALONE_DIR/.next/static"
if [[ -d "$GUAPP_WEB_DIR/public" ]]; then
  rm -rf "$STANDALONE_DIR/public"
  cp -r "$GUAPP_WEB_DIR/public" "$STANDALONE_DIR/public"
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
ZIP_PATH="$TMP_DIR/guapp-web.zip"

echo "[05-deploy-web] デプロイ用 zip を作成します: $ZIP_PATH"
(cd "$STANDALONE_DIR" && zip -rq "$ZIP_PATH" .)

echo "[05-deploy-web] $GUAPP_WEB_APP_NAME へデプロイします..."
az webapp deploy \
  --name "$GUAPP_WEB_APP_NAME" \
  --resource-group "$GUAPP_RESOURCE_GROUP" \
  --src-path "$ZIP_PATH" \
  --type zip

echo "[05-deploy-web] 完了。確認（Basic 認証の ID・パスワードは apps/web/.env.basic-auth を参照）:"
echo "[05-deploy-web]   curl -u '<user>:<password>' -i ${GUAPP_WEB_URL}/"
