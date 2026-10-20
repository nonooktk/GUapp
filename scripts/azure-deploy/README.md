# scripts/azure-deploy — レビュー用 Azure App Service 公開

Tech0 講義レビュー期間中、レビュワーに GUapp を実際に触ってもらうための Azure App Service へのデプロイ手順（ADR-0004・設計仕様書公開追補）。**手動デプロイ**（Azure CLI）を前提にしたスクリプト群で、GitHub Actions による自動デプロイは講義 Week7 以降に別途整備する。

> [!warning] 実行前に必ず統括の承認を得ること
> このディレクトリのスクリプトは実際に Azure リソースを作成・変更する。`01-create.sh`・`01b-configure-existing.sh`・`02-settings.sh`・`03-db-firewall.sh`・`04-deploy-api.sh`・`05-deploy-web.sh`・`06-migrate-seed.sh`・`90-stop.sh`・`99-delete.sh` はいずれも実行前に `az account show` の内容を表示し、確認を求める（`GUAPP_ASSUME_YES=1` で確認をスキップできるが、`99-delete.sh` の最終確認だけは省略できない）。

## 前提

- `az login --tenant admintech0jp.onmicrosoft.com` 済みであること
- サブスクリプション `9b680e6d-e5a6-4381-aad5-a30afcbc8459`（Microsoft Azure スポンサー プラン）にアクセスできること
- `apps/api/.env.azure`（`DB_USER`・`DB_PASSWORD`、権限600）が用意されていること（`scripts/azure-db/README.md` 参照）
- `scripts/azure-db/fetch-ca.sh` を実行済みで `~/.config/guapp/azure-mysql-ca.pem` があること
- `uv`・`pnpm`・`zip`・`openssl`・`python3`・`git` が使えること
- ローカルで `pnpm test`・`pnpm build`（web）、`pytest`（api）が通っていること（本番前の動作確認）

## 実行順序

```bash
cd /path/to/GUapp

# 1. プラン・App Service を作成する（Always On・HTTPS Only・TLS 1.2・起動コマンド）
scripts/azure-deploy/01-create.sh

# 2. アプリ設定（環境変数・秘密）を投入する。Basic 認証の ID・パスワードは
#    apps/web/.env.basic-auth に書かれる（画面には出力されない）
scripts/azure-deploy/02-settings.sh
cat apps/web/.env.basic-auth   # 統括が確認し、レビュワーに Slack で個別に伝える

# 3. api の送信 IP を講義 MySQL のファイアウォールに追加する
scripts/azure-deploy/03-db-firewall.sh

# 4. マイグレーションを適用する（seed は付けない。P2 の seed は --seed-p2。全件 seed の --seed は使わない）
scripts/azure-deploy/06-migrate-seed.sh

# 5. api・web をデプロイする
scripts/azure-deploy/04-deploy-api.sh
scripts/azure-deploy/05-deploy-web.sh
```

## 既存の App Service へ配備する場合（tech0 ターゲット）

2026-10-10 以降、`rg-001-gen12` に作成済みの `app-tech0-gen12-01-fe`（web）と `app-tech0-gen12-01-be`（api）へ配備する（ADR-0005）。プラン `asp-tech0-gen12-01` は F1 無料プラン。プランとアプリは作成しない。すべてのコマンドに `GUAPP_TARGET=tech0` を付ける。

`tech0` の値: web=`app-tech0-gen12-01-fe` / api=`app-tech0-gen12-01-be` / SKU=F1 / api のワーカー数 1 / Basic 認証なし / 期間限定バナーなし / MySQL ファイアウォール規則は 26 番から。現行環境（B1）は確認が済むまで残すため、既存の `guapp-appsvc-1〜25` には触れない。

```bash
cd /path/to/GUapp
export GUAPP_TARGET=tech0

# 1. 既存アプリに設定を適用する（HTTPS Only・TLS 1.2・ランタイム PYTHON|3.13 / NODE|24-lts・起動コマンド・CA 証明書を /home/site/certs に配置）
scripts/azure-deploy/01b-configure-existing.sh

# 2. アプリ設定を投入する（BASIC_AUTH_*・DEMO_PUBLIC_UNTIL は設定せず、入っていれば削除する）
scripts/azure-deploy/02-settings.sh

# 3. be の送信 IP を講義 MySQL のファイアウォールに追加する（guapp-appsvc-26 以降）
scripts/azure-deploy/03-db-firewall.sh

# 06-migrate-seed.sh は P1 までの配備では実行しない（DB は従来と同じ guapp_nonooktk のため）。
# P2 を配備するときは、次の「P2（会員・管理画面・AI アシスタント）を配備する場合」の手順で実行する

# 4. api・web をデプロイする
scripts/azure-deploy/04-deploy-api.sh
scripts/azure-deploy/05-deploy-web.sh
```

### P2（会員・管理画面・AI アシスタント）を配備する場合（2026-10-21 追加）

順番は 02（設定）→ 06 `--seed-p2`（マイグレーションと P2 の seed）→ 04（api）→ 05（web）。01b・03 は P1 までの配備で実行済みなら不要。

```bash
cd /path/to/GUapp
export GUAPP_TARGET=tech0

# 1. アプリ設定を投入する。P2 では次が増える
#    - api: PUBLIC_WEB_BASE_URL（web の URL）
#    - api: OPENAI_API_KEY（手元の $HOME/GUapp/apps/api/.env の OPENAI_API_KEY= の行だけを読む。値は表示しない）
#    - 管理者の初期パスワード: apps/api/.env.admin に、未作成のときだけ 20 文字を作る（App Service には入れない）
#    OPENAI_API_KEY の読み元を変えるとき: GUAPP_OPENAI_ENV_FILE=/path/to/.env scripts/azure-deploy/02-settings.sh
#    キーが読めなければ、設定せず警告して続ける（AI アシスタントは本番で無効 = chat_unavailable になる）
scripts/azure-deploy/02-settings.sh

# 2. マイグレーションを適用し、P2 の seed（会員・店舗・レビュー、管理者）を投入する
#    各表が空のときに限って投入するため、共用 DB の既存データは消えない。会員のダミーは本番に入れない
scripts/azure-deploy/06-migrate-seed.sh --seed-p2

# 3. api・web をデプロイする
scripts/azure-deploy/04-deploy-api.sh
scripts/azure-deploy/05-deploy-web.sh
```

> [!warning] `--seed`（全件 seed）は使わない
> `06-migrate-seed.sh --seed` は `--reset --yes` で既存データを消してから入れ直す。共用 DB の P2 配備では必ず `--seed-p2` を使う。

管理者のパスワードの確かめ方: `apps/api/.env.admin` を本人が開き、`SEED_STAFF_PASSWORD=` の行を見る。スクリプトは値を表示しない。ログイン ID は seed の既定値。

```bash
open -e apps/api/.env.admin
```

管理者のパスワードを変えるとき: `.env.admin` の行を書き換えてから、次を実行する（DB の管理者だけ更新する）。

```bash
cd apps/api
SEED_STAFF_PASSWORD="$(grep '^SEED_STAFF_PASSWORD=' .env.admin | cut -d= -f2-)" APP_ENV=production \
  ../../scripts/azure-db/with-azure-db.sh uv run python -m app.seed --only-p2c --update-staff-password
```

### CA 証明書の置き場所（2026-10-10 の不具合と対応）

- 不具合: 新しい Kudu/Oryx は、ビルド結果を `/home/site/wwwroot/output.tar.zst` に圧縮し、起動時に `/tmp/<ランダム>/` に展開して動かす（`oryx-manifest.toml` の `CompressDestinationDir="true"`）。そのため `/home/site/wwwroot/certs/azure-mysql-ca.pem` が存在せず、`DATABASE_URL` の `ssl_ca=` と `DB_SSL_CA_PATH` が指す先が無くなり、`/api/v1/health` が 503 `db_unavailable` を返した。従来の `app-guapp-api-nonooktk` は wwwroot にソース一式が残るため動いていた
- 対応: tech0 ターゲットの CA パスを、配備で消えない `/home/site/certs/azure-mysql-ca.pem` にした（`config.sh`）。`01b-configure-existing.sh` が、手元の CA（`GUAPP_CA_FILE`）を Kudu の VFS API で、このパスに置く。CA は公開証明書で秘密ではない。nonooktk ターゲットは従来どおり wwwroot のパスで、この処理は飛ばす
- 実行順: `01b` を `02-settings.sh` より前に実行する。すでに `02` を実行済みの環境では、`01b` → `02` の順でやり直す（CA パスの設定を入れ直すため）
- 教訓: 配備物の中のファイルを絶対パスで参照しない（配備先によって展開場所が変わる）

動作確認（Basic 認証がないため `-u` は不要）:

```bash
curl -i https://app-tech0-gen12-01-be.azurewebsites.net/api/v1/health
curl -i https://app-tech0-gen12-01-fe.azurewebsites.net/
```

### F1 無料プランの注意

- 1 日の CPU 時間に上限がある。超えると QuotaExceeded になりアプリが停止する
- QuotaExceeded の間は zip 配備が通らない見込み。UTC 0 時（日本時間 9 時）にリセットされるまで待つ
- Always On を設定できない。しばらくアクセスが無いと停止し、次のアクセスで起動し直すため、初回応答が遅い
- メモリは 1 GB のため api のワーカーは 1
- 現行環境の削除（`99-delete.sh`）は `guapp-appsvc-*` を全部消すため、並行運用中は実行しない

## 動作確認

```bash
# api のヘルスチェック（内部トークン不要）
curl -i https://app-guapp-api-nonooktk.azurewebsites.net/api/v1/health

# web（Basic 認証あり）。apps/web/.env.basic-auth の値を使う
curl -u '<BASIC_AUTH_USER>:<BASIC_AUTH_PASSWORD>' -i https://app-guapp-web-nonooktk.azurewebsites.net/

# 認証なしは 401 になることを確認
curl -i https://app-guapp-web-nonooktk.azurewebsites.net/

# 期間限定バナーの文言が入っていることを確認（ブラウザで開いて目視でも可）
curl -u '<BASIC_AUTH_USER>:<BASIC_AUTH_PASSWORD>' -s https://app-guapp-web-nonooktk.azurewebsites.net/ | grep -o "講義レビュー用のデモ.\{0,60\}"
```

ブラウザで実際に商品閲覧・検索・カート・注文確定まで一通り動かし、問題なければレビュワーに URL と `apps/web/.env.basic-auth` の ID・パスワードを Slack で個別に伝える。

## 終了日の延長

コード変更・再デプロイ不要。App Service の環境変数を書き換えるだけでよい。

```bash
az webapp config appsettings set \
  --name app-guapp-web-nonooktk \
  --resource-group rg-001-gen12 \
  --settings DEMO_PUBLIC_UNTIL=2026-10-31
```

## 停止・削除

```bash
# レビュー期間終了後（自動停止はしない。手動で実行すること）
scripts/azure-deploy/90-stop.sh

# 完全に不要になった場合（破壊的操作。確認プロンプトあり）
scripts/azure-deploy/99-delete.sh
```

`99-delete.sh` は講義 MySQL 本体・スキーマ・共用のリソースグループは削除しない。DB ファイアウォールの `guapp-appsvc-*` 規則だけを削除する。

## 費用の目安

App Service Plan B1（Linux・japaneast）1 つに web・api を同居させる。2026-09-25 に Azure Retail Prices API（`https://prices.azure.com/api/retail/prices`）で確認した単価は USD 0.019/時間、730 時間/月換算で概算 USD 13.87/月（為替換算はしていない参考値。実際の請求通貨・金額は Azure ポータルの請求情報で確認すること）。DB は既存の講義サーバーに相乗りするため追加課金は無い想定。停止中（`90-stop.sh` 実行後）は稼働時間分の課金は止まるが、プラン自体の基本料金は発生し続けるため、不要になった時点で `99-delete.sh` を実行すること。

## トラブルシューティング

| 症状 | 原因 | 対処 |
| --- | --- | --- |
| `az webapp create` が名前の衝突でエラーになる | App Service 名はグローバルに一意 | `GUAPP_NAME_SUFFIX="-1"` を設定して `config.sh` 経由の名前を変え、再実行する |
| api が起動しない | 起動コマンド・`requirements.txt` の不整合 | `az webapp log tail --name app-guapp-api-nonooktk --resource-group rg-001-gen12` でログを確認。DS-DEC-54 の暫定コマンド（`uvicorn --workers 2`）を使っているか確認する |
| DB に繋がらない | ファイアウォール未登録・CA 証明書パス不一致 | `03-db-firewall.sh` を再実行。`apps/api/certs/azure-mysql-ca.pem` が zip に含まれているか（`04-deploy-api.sh` のログ）を確認する |
| Basic 認証が効かない | `BASIC_AUTH_USER`・`BASIC_AUTH_PASSWORD` の設定漏れ | `02-settings.sh` を再実行する（値はローテーションされる） |
