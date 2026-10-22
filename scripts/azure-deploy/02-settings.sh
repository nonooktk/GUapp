#!/usr/bin/env bash
# web・api のアプリ設定（環境変数）を投入する（設計仕様書公開追補 8.2・8.5）。
#
# 秘密（INTERNAL_TOKEN・BASIC_AUTH_USER・BASIC_AUTH_PASSWORD・DATABASE_URL）は
# その場でランダム生成し、ターミナル・ログには一切表示しない
# （`scripts/azure-db/with-azure-db.sh` と同じ方針）。
#
# 冪等: 何度実行しても、既存のアプリ設定を新しい値で上書きするだけで壊れない。
# ただし再実行するたびに INTERNAL_TOKEN・BASIC_AUTH_* は新しい値に「ローテーション」される
# （ADR-0004 の「漏えい時は本スクリプトを再実行して再生成する」という運用を兼ねる）。
#
# GUAPP_ENABLE_BASIC_AUTH=0（tech0 ターゲットの既定）のときは BASIC_AUTH_USER・
# BASIC_AUTH_PASSWORD を生成も設定もせず、.env.basic-auth も書かない。設定済みの場合に
# 備えて App Service 側の両設定を削除する。GUAPP_DEMO_PUBLIC_UNTIL が空のときも
# DEMO_PUBLIC_UNTIL を設定せず、削除する（帯を出さない）。
#
# P2（会員・管理画面・AI アシスタント。2026-10-21 追加）:
#   - api に PUBLIC_WEB_BASE_URL（= web の URL）を設定する。
#   - OPENAI_API_KEY は手元のファイル（既定 $HOME/GUapp/apps/api/.env。GUAPP_OPENAI_ENV_FILE で変更可）の
#     OPENAI_API_KEY= の行だけを読み、値は表示しない。ファイルや行が無ければ設定せず、警告して続ける
#     （AI アシスタントは本番で無効になる）。OPENAI_MODEL・LLM_PROVIDER は設定しない（コードの既定値）。
#   - 管理者の初期パスワードは App Service には入れない。apps/api/.env.admin（権限600）に、
#     未作成のときだけランダムな 20 文字を SEED_STAFF_PASSWORD= として書く（06 --seed-p2 が読む）。
#   - 管理者のログイン ID も同じファイルに、未作成のときだけ `staff-` ＋ 小文字英数字 10 文字を
#     SEED_STAFF_LOGIN_ID= として書く（既定値 demo-staff を本番に残さない。06 --seed-p2 が読む。値は表示しない）。
#
# 前提: `apps/api/.env.azure`（DB_USER・DB_PASSWORD の2行、権限600）が存在すること。
# Basic 認証の ID・パスワードは実行後に `apps/web/.env.basic-auth`（権限600）に書く。
# 統括はそのファイルを見てレビュワーに Slack で個別に伝える。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./config.sh
source "$SCRIPT_DIR/config.sh"

guapp_confirm_azure_context
az account set --subscription "$GUAPP_SUBSCRIPTION_ID"

ENV_AZURE_FILE="$GUAPP_API_DIR/.env.azure"
BASIC_AUTH_FILE="$GUAPP_WEB_DIR/.env.basic-auth"

if [[ ! -r "$ENV_AZURE_FILE" ]]; then
  echo "[02-settings] エラー: $ENV_AZURE_FILE が読めません（存在しない、または権限不足）。" >&2
  echo "[02-settings] scripts/azure-db/README.md の前提どおり、統括が用意する必要があります。" >&2
  exit 1
fi

if [[ ! -r "$GUAPP_CA_FILE" ]]; then
  echo "[02-settings] エラー: CA 証明書が見つかりません: $GUAPP_CA_FILE" >&2
  echo "[02-settings] 先に scripts/azure-db/fetch-ca.sh を実行してください（DB_SSL_CA_PATH の値は" >&2
  echo "[02-settings] App Service 上のパスに変わりますが、証明書ファイル自体はこれと同じものを使います）。" >&2
  exit 1
fi

# --- .env.azure から DB_USER・DB_PASSWORD を読む（値は表示しない） ---
DB_USER="$(grep -E '^DB_USER=' "$ENV_AZURE_FILE" | head -n1 | cut -d= -f2-)"
DB_PASSWORD="$(grep -E '^DB_PASSWORD=' "$ENV_AZURE_FILE" | head -n1 | cut -d= -f2-)"
if [[ -z "$DB_USER" || -z "$DB_PASSWORD" ]]; then
  echo "[02-settings] エラー: .env.azure から DB_USER または DB_PASSWORD を読み取れませんでした。" >&2
  exit 1
fi

ENCODED_PASSWORD="$(DB_PASSWORD="$DB_PASSWORD" python3 -c '
import os
import urllib.parse
print(urllib.parse.quote(os.environ["DB_PASSWORD"], safe=""))
')"

DATABASE_URL="mysql+asyncmy://${DB_USER}:${ENCODED_PASSWORD}@${GUAPP_DB_HOST}:3306/${GUAPP_DB_NAME}?ssl_ca=${GUAPP_DB_SSL_CA_PATH_ON_APPSERVICE}"
unset DB_PASSWORD ENCODED_PASSWORD

# --- 安全装置: 組み立てた URL のホスト・DB 名を検証する（with-azure-db.sh と同じ考え方） ---
DATABASE_URL="$DATABASE_URL" python3 -c '
import os, sys
from urllib.parse import urlsplit
parts = urlsplit(os.environ["DATABASE_URL"])
host = parts.hostname or ""
db = (parts.path or "").lstrip("/").split("?")[0]
if host != os.environ["GUAPP_DB_HOST"]:
    print(f"安全装置: ホストが一致しません: {host!r}", file=sys.stderr); sys.exit(1)
if db != os.environ["GUAPP_DB_NAME"]:
    print(f"安全装置: DB 名が一致しません: {db!r}", file=sys.stderr); sys.exit(1)
' || { echo "[02-settings] 安全装置により中止しました。" >&2; exit 1; }

# --- OPENAI_API_KEY を手元のファイルから読む（値は表示しない） ---
OPENAI_API_KEY=""
if [[ -r "$GUAPP_OPENAI_ENV_FILE" ]]; then
  OPENAI_API_KEY="$(grep -E '^OPENAI_API_KEY=' "$GUAPP_OPENAI_ENV_FILE" | head -n1 | cut -d= -f2- | tr -d '\r' || true)"
  # 値を囲む引用符があれば外す
  OPENAI_API_KEY="${OPENAI_API_KEY#\"}"; OPENAI_API_KEY="${OPENAI_API_KEY%\"}"
  OPENAI_API_KEY="${OPENAI_API_KEY#\'}"; OPENAI_API_KEY="${OPENAI_API_KEY%\'}"
fi
if [[ -z "$OPENAI_API_KEY" ]]; then
  echo "[02-settings] 警告: OPENAI_API_KEY を読み取れませんでした（ファイル: $GUAPP_OPENAI_ENV_FILE）。" >&2
  echo "[02-settings] OPENAI_API_KEY は設定しません。AI アシスタントは本番で無効（chat_unavailable）になります。" >&2
  echo "[02-settings] App Service に既に入っている値があれば、そのまま残ります。" >&2
else
  echo "[02-settings] OPENAI_API_KEY を $GUAPP_OPENAI_ENV_FILE から読みました（値は表示しません）。"
fi

# --- 秘密の生成（画面には出さない） ---
INTERNAL_TOKEN="$(openssl rand -hex 32)"
BASIC_AUTH_USER=""
BASIC_AUTH_PASSWORD=""
if [[ "$GUAPP_ENABLE_BASIC_AUTH" == "1" ]]; then
  BASIC_AUTH_USER="reviewer-$(openssl rand -hex 3)"
  BASIC_AUTH_PASSWORD="$(openssl rand -base64 30 | tr -dc 'A-Za-z0-9' | head -c 24)"
  if [[ -z "$BASIC_AUTH_PASSWORD" ]]; then
    echo "[02-settings] エラー: BASIC_AUTH_PASSWORD の生成に失敗しました。" >&2
    exit 1
  fi
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
umask 077
API_SETTINGS_JSON="$TMP_DIR/api-settings.json"
WEB_SETTINGS_JSON="$TMP_DIR/web-settings.json"

# JSON はコマンドライン引数に載せず、権限 600 の一時ファイル経由で az に渡す（ps 対策）。
DATABASE_URL="$DATABASE_URL" INTERNAL_TOKEN="$INTERNAL_TOKEN" OPENAI_API_KEY="$OPENAI_API_KEY" API_SETTINGS_JSON="$API_SETTINGS_JSON" python3 -c '
import json
import os

settings = [
    {"name": "APP_ENV", "value": "production"},
    {"name": "DATABASE_URL", "value": os.environ["DATABASE_URL"]},
    {"name": "DB_POOL_SIZE", "value": os.environ["GUAPP_DB_POOL_SIZE"]},
    {"name": "DB_MAX_OVERFLOW", "value": os.environ["GUAPP_DB_MAX_OVERFLOW"]},
    {"name": "DB_SSL_CA_PATH", "value": os.environ["GUAPP_DB_SSL_CA_PATH_ON_APPSERVICE"]},
    {"name": "INTERNAL_TOKEN", "value": os.environ["INTERNAL_TOKEN"]},
    {"name": "CORS_ALLOW_ORIGIN", "value": os.environ["GUAPP_WEB_URL"]},
    # 公開環境は誰でも会員登録できるため、登録・再設定に使えるメールをダミーのドメインに限る（DS-DEC-88）
    {"name": "DEMO_EMAIL_DOMAINS", "value": "example.com"},
    # P2: 会員向けメール等に載せる web の URL（2026-10-21）
    {"name": "PUBLIC_WEB_BASE_URL", "value": os.environ["GUAPP_WEB_URL"]},
]
# OPENAI_MODEL・LLM_PROVIDER・SEED_STAFF_LOGIN_ID は設定しない（コードの既定値を使う）
if os.environ["OPENAI_API_KEY"] != "":
    settings.append({"name": "OPENAI_API_KEY", "value": os.environ["OPENAI_API_KEY"]})
with open(os.environ["API_SETTINGS_JSON"], "w") as f:
    json.dump(settings, f)
'
chmod 600 "$API_SETTINGS_JSON"

INTERNAL_TOKEN="$INTERNAL_TOKEN" BASIC_AUTH_USER="$BASIC_AUTH_USER" BASIC_AUTH_PASSWORD="$BASIC_AUTH_PASSWORD" GUAPP_ENABLE_BASIC_AUTH="$GUAPP_ENABLE_BASIC_AUTH" WEB_SETTINGS_JSON="$WEB_SETTINGS_JSON" python3 -c '
import json
import os

settings = [
    {"name": "API_BASE_URL", "value": os.environ["GUAPP_API_URL"]},
    {"name": "IMAGE_BASE_URL", "value": os.environ["GUAPP_WEB_URL"]},
    {"name": "INTERNAL_TOKEN", "value": os.environ["INTERNAL_TOKEN"]},
    {"name": "APP_ENV", "value": "production"},
    # App Service（ARR）配下は 1。未設定だと全利用者が同じ IP 扱いになり、注文照会の回数制限を共有してしまう（設計仕様書 8.2）
    {"name": "TRUSTED_PROXY_HOPS", "value": "1"},
]
if os.environ["GUAPP_ENABLE_BASIC_AUTH"] == "1":
    settings += [
        {"name": "BASIC_AUTH_USER", "value": os.environ["BASIC_AUTH_USER"]},
        {"name": "BASIC_AUTH_PASSWORD", "value": os.environ["BASIC_AUTH_PASSWORD"]},
    ]
if os.environ["GUAPP_DEMO_PUBLIC_UNTIL"] != "":
    settings.append({"name": "DEMO_PUBLIC_UNTIL", "value": os.environ["GUAPP_DEMO_PUBLIC_UNTIL"]})
with open(os.environ["WEB_SETTINGS_JSON"], "w") as f:
    json.dump(settings, f)
'
chmod 600 "$WEB_SETTINGS_JSON"

echo "[02-settings] api のアプリ設定を投入します（値は表示しません）..."
az webapp config appsettings set \
  --name "$GUAPP_API_APP_NAME" \
  --resource-group "$GUAPP_RESOURCE_GROUP" \
  --settings @"$API_SETTINGS_JSON" \
  --output none

echo "[02-settings] web のアプリ設定を投入します（値は表示しません）..."
az webapp config appsettings set \
  --name "$GUAPP_WEB_APP_NAME" \
  --resource-group "$GUAPP_RESOURCE_GROUP" \
  --settings @"$WEB_SETTINGS_JSON" \
  --output none

# --- 設定しない項目は、既に入っている場合に備えて削除する（存在しなくてもエラーにならない） ---
DELETE_NAMES=()
if [[ "$GUAPP_ENABLE_BASIC_AUTH" != "1" ]]; then
  DELETE_NAMES+=(BASIC_AUTH_USER BASIC_AUTH_PASSWORD)
fi
if [[ -z "$GUAPP_DEMO_PUBLIC_UNTIL" ]]; then
  DELETE_NAMES+=(DEMO_PUBLIC_UNTIL)
fi
if [[ ${#DELETE_NAMES[@]} -gt 0 ]]; then
  echo "[02-settings] web から次の設定を削除します（未設定なら何も起きません）: ${DELETE_NAMES[*]}"
  az webapp config appsettings delete \
    --name "$GUAPP_WEB_APP_NAME" \
    --resource-group "$GUAPP_RESOURCE_GROUP" \
    --setting-names "${DELETE_NAMES[@]}" \
    --output none
fi

# --- 管理者の初期パスワード: 未作成のときだけ作る（既にあれば変えない。値は表示しない） ---
# App Service には入れない。06-migrate-seed.sh --seed-p2 が seed の実行時に読む。
ADMIN_ENV_FILE="$GUAPP_ADMIN_ENV_FILE"
if [[ -f "$ADMIN_ENV_FILE" ]] && grep -qE '^SEED_STAFF_PASSWORD=.+' "$ADMIN_ENV_FILE"; then
  echo "[02-settings] 管理者の初期パスワードは作成済みのため変えません: $ADMIN_ENV_FILE"
else
  ADMIN_PASSWORD="$(openssl rand -base64 48 | tr -dc 'A-Za-z0-9' | head -c 20)"
  if [[ ${#ADMIN_PASSWORD} -ne 20 ]]; then
    echo "[02-settings] エラー: 管理者の初期パスワードの生成に失敗しました。" >&2
    exit 1
  fi
  umask 077
  {
    if [[ ! -f "$ADMIN_ENV_FILE" ]]; then
      echo "# scripts/azure-deploy/02-settings.sh が生成しました（$(date -u +%Y-%m-%dT%H:%M:%SZ)）"
      echo "# 管理者の初期パスワード。06-migrate-seed.sh --seed-p2 が読む。App Service には入れない。"
      echo "# このファイルは git 管理対象外（.gitignore の .env.* パターン）。"
    fi
    echo "SEED_STAFF_PASSWORD=${ADMIN_PASSWORD}"
  } >> "$ADMIN_ENV_FILE"
  chmod 600 "$ADMIN_ENV_FILE"
  unset ADMIN_PASSWORD
  echo "[02-settings] 管理者の初期パスワードを作成しました（値は表示しません）: $ADMIN_ENV_FILE"
fi

# --- 管理者のログイン ID: 未作成のときだけ作る（既にあれば変えない。値は表示しない） ---
# 形は api の login_id の規則（[a-z0-9][a-z0-9._-]{2,49}）に合わせる。`staff-` ＋ 小文字英数字 10 文字。
if [[ -f "$ADMIN_ENV_FILE" ]] && grep -qE '^SEED_STAFF_LOGIN_ID=.+' "$ADMIN_ENV_FILE"; then
  echo "[02-settings] 管理者のログイン ID は作成済みのため変えません: $ADMIN_ENV_FILE"
else
  ADMIN_LOGIN_SUFFIX="$(openssl rand -base64 48 | tr -dc 'a-z0-9' | head -c 10)"
  if [[ ${#ADMIN_LOGIN_SUFFIX} -ne 10 ]]; then
    echo "[02-settings] エラー: 管理者のログイン ID の生成に失敗しました。" >&2
    exit 1
  fi
  umask 077
  # `>>` はブロックの実行前にファイルを作るため、新規かどうかは先に判定する
  ADMIN_ENV_IS_NEW=0
  [[ -f "$ADMIN_ENV_FILE" ]] || ADMIN_ENV_IS_NEW=1
  {
    if [[ "$ADMIN_ENV_IS_NEW" == "1" ]]; then
      echo "# scripts/azure-deploy/02-settings.sh が生成しました（$(date -u +%Y-%m-%dT%H:%M:%SZ)）"
      echo "# 管理者の初期パスワードとログイン ID。06-migrate-seed.sh --seed-p2 が読む。App Service には入れない。"
      echo "# このファイルは git 管理対象外（.gitignore の .env.* パターン）。"
    fi
    echo "SEED_STAFF_LOGIN_ID=staff-${ADMIN_LOGIN_SUFFIX}"
  } >> "$ADMIN_ENV_FILE"
  chmod 600 "$ADMIN_ENV_FILE"
  unset ADMIN_LOGIN_SUFFIX
  echo "[02-settings] 管理者のログイン ID を作成しました（値は表示しません）: $ADMIN_ENV_FILE"
fi
if git -C "$GUAPP_REPO_ROOT" check-ignore -q "$ADMIN_ENV_FILE"; then
  echo "[02-settings] 確認: $ADMIN_ENV_FILE は git 管理対象外です（.gitignore の .env.* パターンに一致）。"
else
  echo "[02-settings] 警告: $ADMIN_ENV_FILE が .gitignore に無視されていません。誤ってコミットしないよう注意してください。" >&2
fi

if [[ "$GUAPP_ENABLE_BASIC_AUTH" == "1" ]]; then
  # --- Basic 認証の ID・パスワードだけ、統括が確認できるようファイルに残す ---
  umask 077
  {
    echo "# scripts/azure-deploy/02-settings.sh が生成しました（$(date -u +%Y-%m-%dT%H:%M:%SZ)）"
    echo "# レビュワーへは Slack で個別に伝える。このファイルは git 管理対象外（.gitignore の .env.* パターン）。"
    echo "BASIC_AUTH_USER=${BASIC_AUTH_USER}"
    echo "BASIC_AUTH_PASSWORD=${BASIC_AUTH_PASSWORD}"
  } > "$BASIC_AUTH_FILE"
  chmod 600 "$BASIC_AUTH_FILE"

  if git -C "$GUAPP_REPO_ROOT" check-ignore -q "$BASIC_AUTH_FILE"; then
    echo "[02-settings] 確認: $BASIC_AUTH_FILE は git 管理対象外です（.gitignore の .env.* パターンに一致）。"
  else
    echo "[02-settings] 警告: $BASIC_AUTH_FILE が .gitignore に無視されていません。誤ってコミットしないよう注意してください。" >&2
  fi
  echo "[02-settings] 完了。Basic 認証の ID・パスワードはこのファイルに書きました: $BASIC_AUTH_FILE"
else
  echo "[02-settings] 完了。Basic 認証は設定していません（GUAPP_ENABLE_BASIC_AUTH=0）。"
fi

unset INTERNAL_TOKEN BASIC_AUTH_USER BASIC_AUTH_PASSWORD DATABASE_URL OPENAI_API_KEY

echo "[02-settings] 次は 03-db-firewall.sh で講義 MySQL のファイアウォールに api の送信 IP を追加してください。"
