#!/usr/bin/env bash
# 公開前にマイグレーションを適用する（設計仕様書公開追補 8.3）。
# `scripts/azure-db/with-azure-db.sh` をそのまま使い、資格情報の扱いはそちらに一任する。
#
# **seed（初期データ投入）は既定では実行しない。** 付けたときだけ実行する。
#
# 使い方:
#   scripts/azure-deploy/06-migrate-seed.sh              # alembic upgrade head のみ
#   scripts/azure-deploy/06-migrate-seed.sh --seed-p2    # 上記に加えて P2 の seed（会員・店舗・レビューと管理者）を投入
#   scripts/azure-deploy/06-migrate-seed.sh --seed       # 上記に加えて全件 seed（--reset --yes。既存データが消える。使わない）
#
# --seed-p2（2026-10-21 追加）: APP_ENV=production で `python -m app.seed --only-p2b` と `--only-p2c` を実行する。
#   どちらも各表が空のときに限って投入するため、共用 DB の既存データを消さない。
#   --only-p2c の管理者パスワードは apps/api/.env.admin の SEED_STAFF_PASSWORD を環境変数で渡す（値は表示しない。
#   ファイルは 02-settings.sh が未作成のときだけ作る）。同じファイルに SEED_STAFF_LOGIN_ID があれば、それも
#   環境変数で渡す（値は表示しない。無ければ seed の既定値のまま）。
#   SEED_MEMBER_PASSWORD は渡さない（本番に会員のダミーは入れない）。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./config.sh
source "$SCRIPT_DIR/config.sh"

WITH_AZURE_DB="$GUAPP_REPO_ROOT/scripts/azure-db/with-azure-db.sh"
if [[ ! -x "$WITH_AZURE_DB" ]]; then
  echo "[06-migrate-seed] エラー: $WITH_AZURE_DB が見つからない、または実行権限がありません。" >&2
  exit 1
fi

MODE=""
for arg in "$@"; do
  case "$arg" in
    --seed|--seed-p2)
      if [[ -n "$MODE" && "$MODE" != "$arg" ]]; then
        echo "[06-migrate-seed] エラー: --seed と --seed-p2 は同時に指定できません。" >&2
        exit 64
      fi
      MODE="$arg"
      ;;
    *)
      echo "[06-migrate-seed] エラー: 不明なオプション: $arg（使えるのは --seed-p2 または --seed）" >&2
      exit 64
      ;;
  esac
done

# --seed-p2 は管理者のパスワード（と、あればログイン ID）を先に読む（無ければ、DB に触る前に止める。値は表示しない）
SEED_STAFF_PASSWORD=""
SEED_STAFF_LOGIN_ID=""
if [[ "$MODE" == "--seed-p2" ]]; then
  if [[ ! -r "$GUAPP_ADMIN_ENV_FILE" ]]; then
    echo "[06-migrate-seed] エラー: $GUAPP_ADMIN_ENV_FILE が読めません。先に 02-settings.sh を実行してください。" >&2
    exit 1
  fi
  SEED_STAFF_PASSWORD="$(grep -E '^SEED_STAFF_PASSWORD=' "$GUAPP_ADMIN_ENV_FILE" | head -n1 | cut -d= -f2- | tr -d '\r' || true)"
  if [[ -z "$SEED_STAFF_PASSWORD" ]]; then
    echo "[06-migrate-seed] エラー: $GUAPP_ADMIN_ENV_FILE から SEED_STAFF_PASSWORD を読み取れませんでした。" >&2
    exit 1
  fi
  # ログイン ID は任意（無ければ seed の既定値）。あるなら形を確かめる（値は表示しない）
  SEED_STAFF_LOGIN_ID="$(grep -E '^SEED_STAFF_LOGIN_ID=' "$GUAPP_ADMIN_ENV_FILE" | head -n1 | cut -d= -f2- | tr -d '\r' || true)"
  if [[ -n "$SEED_STAFF_LOGIN_ID" ]] && [[ ! "$SEED_STAFF_LOGIN_ID" =~ ^[a-z0-9][a-z0-9._-]{2,49}$ ]]; then
    echo "[06-migrate-seed] エラー: $GUAPP_ADMIN_ENV_FILE の SEED_STAFF_LOGIN_ID が形式に合いません（[a-z0-9][a-z0-9._-]{2,49}）。" >&2
    exit 1
  fi
fi

echo "[06-migrate-seed] 講義サーバー（guapp_nonooktk）に対して alembic upgrade head を実行します。"
echo "[06-migrate-seed] 対象は共用サーバーです。実行前に統括の承認を得てください。"
guapp_confirm_azure_context

(cd "$GUAPP_API_DIR" && "$WITH_AZURE_DB" uv run alembic upgrade head)

if [[ "$MODE" == "--seed-p2" ]]; then
  echo "[06-migrate-seed] --seed-p2: P2 の seed を APP_ENV=production で投入します（各表が空のときに限る）。"
  (cd "$GUAPP_API_DIR" && APP_ENV=production "$WITH_AZURE_DB" uv run python -m app.seed --only-p2b)
  # 管理者のパスワードとログイン ID は環境変数にだけ載せる（引数・ログには出さない）。
  # ログイン ID が空なら変数ごと渡さず、seed の既定値を使う
  export SEED_STAFF_PASSWORD
  if [[ -n "$SEED_STAFF_LOGIN_ID" ]]; then export SEED_STAFF_LOGIN_ID; else unset SEED_STAFF_LOGIN_ID; fi
  (cd "$GUAPP_API_DIR" && APP_ENV=production "$WITH_AZURE_DB" uv run python -m app.seed --only-p2c)
  unset SEED_STAFF_PASSWORD SEED_STAFF_LOGIN_ID
  echo "[06-migrate-seed] 管理者のパスワードは $GUAPP_ADMIN_ENV_FILE を本人が開いて確かめてください。"
elif [[ "$MODE" == "--seed" ]]; then
  echo "[06-migrate-seed] --seed が指定されました。全件 seed（--reset）は既存データが消えるため、P2 の配備では使わず --seed-p2 を使ってください。"
  read -r -p "seed（--reset --yes）を本当に実行しますか？ 既存データが消えます (y/N): " REPLY
  case "$REPLY" in
    y|Y|yes|YES)
      (cd "$GUAPP_API_DIR" && "$WITH_AZURE_DB" uv run python -m app.seed --reset --yes)
      ;;
    *)
      echo "[06-migrate-seed] seed の実行を中止しました。"
      ;;
  esac
else
  echo "[06-migrate-seed] seed は実行しません（P2 の配備は --seed-p2 を付けて実行してください）。"
fi

echo "[06-migrate-seed] 完了。"
