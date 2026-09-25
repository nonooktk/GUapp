# scripts/azure-deploy — レビュー用 Azure App Service 公開

Tech0 講義レビュー期間中、レビュワーに GUapp を実際に触ってもらうための Azure App Service へのデプロイ手順（ADR-0004・設計仕様書公開追補）。**手動デプロイ**（Azure CLI）を前提にしたスクリプト群で、GitHub Actions による自動デプロイは講義 Week7 以降に別途整備する。

> [!warning] 実行前に必ず統括の承認を得ること
> このディレクトリのスクリプトは実際に Azure リソースを作成・変更する。`01-create.sh`・`02-settings.sh`・`03-db-firewall.sh`・`04-deploy-api.sh`・`05-deploy-web.sh`・`06-migrate-seed.sh`・`90-stop.sh`・`99-delete.sh` はいずれも実行前に `az account show` の内容を表示し、確認を求める（`GUAPP_ASSUME_YES=1` で確認をスキップできるが、`99-delete.sh` の最終確認だけは省略できない）。

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

# 4. マイグレーションを適用する（seed は付けない。統括の指示があるときだけ --seed）
scripts/azure-deploy/06-migrate-seed.sh

# 5. api・web をデプロイする
scripts/azure-deploy/04-deploy-api.sh
scripts/azure-deploy/05-deploy-web.sh
```

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
