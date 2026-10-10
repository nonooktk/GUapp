# ADR-0005 配備先の変更（app-tech0-gen12-01-fe / -be、F1 無料プラン）

| 項目 | 内容 |
| --- | --- |
| 状態 | 承認 |
| 日付 | 2026-10-10 |
| 決定者 | 統括 |

## 背景

統括から、フロントを `app-tech0-gen12-01-fe`、バックを `app-tech0-gen12-01-be` へ配備し直す指示があった。事実は次のとおり。

- 両アプリは `rg-001-gen12` に作成済み。プランは `asp-tech0-gen12-01`（Linux、F1 無料プラン）
- fe は NODE:24-lts、be は PYTHON:3.12。起動コマンド・アプリ設定は空
- api は `requires-python>=3.13` のため、be のランタイムを PYTHON:3.13 に変える必要がある
- F1 では Always On を設定できない
- 現行の `app-guapp-web-nonooktk` / `app-guapp-api-nonooktk`（B1）は ADR-0004 で作成したもの

## 決定

1. 配備先を `app-tech0-gen12-01-fe`（web）と `app-tech0-gen12-01-be`（api）にする。プランとアプリは作成しない。`scripts/azure-deploy/01b-configure-existing.sh` で既存アプリに設定だけを適用する
2. `scripts/azure-deploy/config.sh` に `GUAPP_TARGET`（既定 `nonooktk`、もう一つ `tech0`）を設ける。既定の値は従来と同じ
3. Basic 認証は付けない（`BASIC_AUTH_USER`・`BASIC_AUTH_PASSWORD` を設定しない）。`apps/web/proxy.ts` は両方が未設定なら認証なしで通す
4. `DEMO_PUBLIC_UNTIL` は設定しない。`apps/web/lib/demo-banner.ts` は未設定なら帯を出さない
5. DB は従来と同じ `guapp_nonooktk`（`gen12-mysql-pos`）を使う。マイグレーションは実行しない
6. 現行環境（B1）は確認が済むまで並行して残す。MySQL のファイアウォール規則は既存の `guapp-appsvc-1〜25` に触れず、新しい api の送信 IP は 26 番以降に追加する（`GUAPP_FIREWALL_START_INDEX=26`）
7. api の起動コマンドのワーカー数は 1（`--workers 1`）にする

## 判断基準と理由

- 統括の指示による配備先の変更
- F1 のメモリは 1 GB、CPU 時間には 1 日の上限がある。そのためワーカーは 1 にする
- DB を変えないため、06-migrate-seed.sh は実行しない
- 並行運用中に既存規則を消すと現行環境の DB 接続が止まる。そのため規則名の番号を分ける

## F1 の制約

- Always On を設定できない。一定時間アクセスが無いとアプリが停止し、次のアクセスで起動し直す（初回応答が遅い）
- 1 日の CPU 時間に上限があり、超えると QuotaExceeded になってアプリが停止する。この間は zip 配備が通らない見込み
- 上限は UTC 0 時（日本時間 9 時）にリセットされる

## 検討した代替案

| 案 | 内容 | 採否 |
| --- | --- | --- |
| 案 A（採用） | 既存アプリに設定だけ適用し、config.sh のターゲット切り替えで配備する | 採用 |
| 案 B | 現行環境を削除して置き換える | 確認が済むまで現行環境を残す方針のため不採用 |

## 影響とリスク

- Basic 認証が無いため、ADR-0004 が前提にしていた「認証を通過できるのはレビュワーだけ」が成り立たない。ADR-0003（検索 API のレート制限の見送り）はこの前提に依存しているため、再訪の対象になる
- F1 の CPU 時間上限により、利用が多い日は QuotaExceeded で停止する可能性がある

## 関連

- ADR-0002（講義 MySQL の資格情報とファイアウォール方針）
- ADR-0003（検索 API のレート制限の見送り）
- ADR-0004（レビュー用の App Service 公開）。配備先に関する記述は本 ADR の並行運用が終わるまで有効
- 設計仕様書 `GU_ECsite_設計仕様書_公開追補_draft-v1.md` 11 章（2026-10-10 追補）
- `scripts/azure-deploy/README.md`「既存の App Service へ配備する場合（tech0 ターゲット）」
