#!/usr/bin/env bash
# 公開前にマイグレーションを適用する（設計仕様書公開追補 8.3）。
# `scripts/azure-db/with-azure-db.sh` をそのまま使い、資格情報の扱いはそちらに一任する。
#
# **seed（初期データ投入）は statement 実行しない。** `--seed` を明示的に付けたときだけ、
# 統括の指示があることを前提に実行する（共用サーバーの既存データを壊さないため）。
#
# 使い方:
#   scripts/azure-deploy/06-migrate-seed.sh            # alembic upgrade head のみ
#   scripts/azure-deploy/06-migrate-seed.sh --seed      # 上記に加えて seed も実行（統括の指示があるときだけ）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./config.sh
source "$SCRIPT_DIR/config.sh"

WITH_AZURE_DB="$GUAPP_REPO_ROOT/scripts/azure-db/with-azure-db.sh"
if [[ ! -x "$WITH_AZURE_DB" ]]; then
  echo "[06-migrate-seed] エラー: $WITH_AZURE_DB が見つからない、または実行権限がありません。" >&2
  exit 1
fi

echo "[06-migrate-seed] 講義サーバー（guapp_nonooktk）に対して alembic upgrade head を実行します。"
echo "[06-migrate-seed] 対象は共用サーバーです。実行前に統括の承認を得てください。"
guapp_confirm_azure_context

(cd "$GUAPP_API_DIR" && "$WITH_AZURE_DB" uv run alembic upgrade head)

if [[ "${1:-}" == "--seed" ]]; then
  echo "[06-migrate-seed] --seed が指定されました。統括の指示があることを確認したうえで実行します。"
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
  echo "[06-migrate-seed] seed は実行しません（--seed を付けたときだけ、統括の指示がある場合に実行してください）。"
fi

echo "[06-migrate-seed] 完了。"
