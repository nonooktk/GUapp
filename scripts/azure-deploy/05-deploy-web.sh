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

# 実行時に判明した不具合の修正の経緯（2026-09-25・タキシードサム）:
# 1回目: `zip -rq`（-y なし）はディレクトリへのシンボリックリンクを追わず空ディレクトリとして
#   アーカイブしてしまい、pnpm の node_modules 内のリンク先実体（@swc/helpers 等）が丸ごと
#   欠落した（起動ログ: `Cannot find module '@swc/helpers/...'`）。
# 2回目: `-y`（--symlinks）でシンボリックリンクをリンクのまま格納したところ、欠落は解消したが
#   別の起動時エラーに変わった（`SyntaxError: Unexpected token '.'` が server.js の
#   `require('/node_modules/next')` で発生。エラー内容から、macOS（BSD/Info-ZIP 系）の
#   `zip -y` が格納するシンボリックリンクの形式を、Azure Kudu 側（Linux）の展開処理が
#   同じ意味で解釈できず、「リンク先パス文字列を中身とする通常ファイル」として展開して
#   しまったと推定）。
# → いずれも zip 側のシンボリックリンク対応可否に依存する方式のため不確実と判断し、
#   3回目として次の方式に変更した:
#   `rsync -a --copy-links`（macOS 標準の openrsync でも動作確認済み）で standalone・
#   `.next/static`・`public` を **Desktop の外（$TMPDIR 配下。iCloud 同期の対象外）** の
#   一時フォルダへ「シンボリックリンクを実体化してコピー」し、シンボリックリンクを
#   含まない状態で `zip -rq`（-y なし）する。これなら zip 側のシンボリックリンク対応可否に
#   依存せず OS 非依存で確実になる。
#   あわせて、リポジトリが iCloud 同期の Desktop 配下にあることに起因して standalone の中に
#   紛れ込んでいた iCloud の複製（`node_modules 3`・`.next 2` など、名前の末尾に半角スペース+
#   数字が付くもの）を `rsync --exclude='* [0-9]'` で除外し、コピー後にシンボリックリンク数と
#   複製名の件数を検査して、1つでも残っていればデプロイを中止する。
#
# 3回目の方式のローカル検証で追加判明した問題（同日）:
#   単純に `rsync -a --copy-links` で全シンボリックリンクを実体化しただけでは、
#   `node .../server.js` が `Cannot find module '@swc/helpers/...'` で起動失敗した。
#   原因: pnpm はトップレベルの `node_modules/next`（等）を
#   `node_modules/.pnpm/next@.../node_modules/next` へのシンボリックリンクにしており、
#   Node はシンボリックリンク越しに読み込んだファイルの実体パス（realpath）を基準に
#   モジュール解決するため、`next` 自身が必要とする兄弟パッケージ（`@swc/helpers` 等。
#   `.pnpm/next@.../node_modules/@swc` に実体がある）を見つけられていた。
#   ところが `node_modules/next` を独立した実体コピーとして複製すると、この realpath 経由の
#   解決が効かなくなり、複製先の親ディレクトリ（トップレベルの node_modules）には
#   `@swc` が存在しないため解決に失敗する。
#   対応: pnpm が標準で生成する共有フォルダ `node_modules/.pnpm/node_modules/`
#   （多くのパッケージ名をフラットに集約した pnpm 自身の仕組み。今回 pnpm 設定は
#   変更していない）の中身を、コピー後にトップレベルの `node_modules/` へ追加コピーで
#   統合する。Node のモジュール解決はどれだけ深い場所からでも最終的に
#   トップレベルの `node_modules` まで遡って探すため、ここに実体を置いておけば
#   シンボリックリンク無しでも解決できる。ローカルで `node server.js` を起動し
#   `curl` で `/` が 200 になることを確認して検証済み（本スクリプトの完了条件）。
echo "[05-deploy-web] デプロイ用の一時フォルダを作成します（Desktop の外・\$TMPDIR 配下）..."
DEPLOY_DIR="$(mktemp -d)"
ZIP_DIR="$(mktemp -d)"
trap 'rm -rf "$DEPLOY_DIR" "$ZIP_DIR"' EXIT
ZIP_PATH="$ZIP_DIR/guapp-web.zip"

echo "[05-deploy-web] standalone を一時フォルダへ実体化コピーします（シンボリックリンク解決・iCloud 複製を除外）: $DEPLOY_DIR"
rsync -a --copy-links --exclude='* [0-9]' "$STANDALONE_DIR/" "$DEPLOY_DIR/"

echo "[05-deploy-web] 静的ファイル・public を一時フォルダへ実体コピーします（iCloud 複製を除外）..."
mkdir -p "$DEPLOY_DIR/.next"
rm -rf "$DEPLOY_DIR/.next/static" "$DEPLOY_DIR/public"
rsync -a --copy-links --exclude='* [0-9]' "$GUAPP_WEB_DIR/.next/static/" "$DEPLOY_DIR/.next/static/"
if [[ -d "$GUAPP_WEB_DIR/public" ]]; then
  rsync -a --copy-links --exclude='* [0-9]' "$GUAPP_WEB_DIR/public/" "$DEPLOY_DIR/public/"
fi

if [[ -d "$DEPLOY_DIR/node_modules/.pnpm/node_modules" ]]; then
  echo "[05-deploy-web] pnpm の共有フォルダ（node_modules/.pnpm/node_modules）をトップレベルへ統合します..."
  rsync -a "$DEPLOY_DIR/node_modules/.pnpm/node_modules/" "$DEPLOY_DIR/node_modules/"
fi

echo "[05-deploy-web] 一時フォルダを検査します（シンボリックリンク・iCloud 複製が 0 件であること）..."
SYMLINK_COUNT="$(find "$DEPLOY_DIR" -type l | wc -l | tr -d ' ')"
DUP_COUNT="$(find "$DEPLOY_DIR" -name '* [0-9]' | wc -l | tr -d ' ')"
echo "[05-deploy-web]   シンボリックリンク: ${SYMLINK_COUNT} 件 / iCloud 複製疑い（末尾が半角スペース+数字）: ${DUP_COUNT} 件"
if [[ "$SYMLINK_COUNT" != "0" || "$DUP_COUNT" != "0" ]]; then
  echo "[05-deploy-web] エラー: 一時フォルダにシンボリックリンクまたは iCloud 複製が残っています。デプロイを中止します。" >&2
  find "$DEPLOY_DIR" -type l -o -name '* [0-9]' >&2 || true
  exit 1
fi

echo "[05-deploy-web] デプロイ用 zip を作成します: $ZIP_PATH"
(cd "$DEPLOY_DIR" && zip -rq "$ZIP_PATH" .)

echo "[05-deploy-web] $GUAPP_WEB_APP_NAME へデプロイします..."
az webapp deploy \
  --name "$GUAPP_WEB_APP_NAME" \
  --resource-group "$GUAPP_RESOURCE_GROUP" \
  --src-path "$ZIP_PATH" \
  --type zip

echo "[05-deploy-web] 完了。確認（Basic 認証の ID・パスワードは apps/web/.env.basic-auth を参照）:"
echo "[05-deploy-web]   curl -u '<user>:<password>' -i ${GUAPP_WEB_URL}/"
