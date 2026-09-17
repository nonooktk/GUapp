# scripts/mysql-local — ローカル MySQL 8.4.11（zip 版）

Docker も管理者権限も無い Windows PC で、MySQL 8.4.11 の zip（noinstall）版をユーザー領域に展開して動かす一式。P1 実装プラン 3 章（案 A）の実装。設定値は設計仕様書 DS-DEC-25（utf8mb4・UTC）と同じで、`docker-compose.yml`・CI の `services: mysql:8.4` と揃えてある。

## 前提

| 項目 | 内容 |
| --- | --- |
| OS | Windows 10/11 x64。管理者権限は不要 |
| シェル | Windows PowerShell 5.1（`pwsh` でも可） |
| VC++ ランタイム | **Microsoft Visual C++ 2015-2022 再頒布可能パッケージ (x64)** が必要（`C:\Windows\System32\vcruntime140_1.dll` があれば OK）。無いと mysqld が起動時に 0xc000007b 等で落ちる。多くの PC には他アプリの同梱で入っている。無ければ https://aka.ms/vs/17/release/vc_redist.x64.exe（管理者権限が必要なので IT へ依頼） |
| ディスク | 約 1GB（zip 268MB ＋ 展開 600MB ＋ data） |
| ネットワーク | 初回のみ dev.mysql.com から zip をダウンロード |

すべてのファイルは **リポジトリ外** `%LOCALAPPDATA%\guapp-mysql\` に置く（`C:\Users\<you>\AppData\Local\guapp-mysql\`）。

```
%LOCALAPPDATA%\guapp-mysql\
  mysql-8.4.11-winx64.zip      取得した zip（MD5 検証済み）
  mysql-8.4.11-winx64\         展開先（bin\mysqld.exe など）
  my.ini                       設定（setup.ps1 が生成）
  data\                        データディレクトリ
  credentials.txt              接続情報（パスワード含む。リポジトリに入れない）
  mysqld.log / mysqld-init.log エラーログ
```

## 手順

リポジトリルート（`GUapp/`）で実行する。実行ポリシーで止まる場合は `-ExecutionPolicy Bypass` を付ける。

```powershell
# 1. 初回セットアップ（ダウンロード → 展開 → my.ini → 初期化 → 起動 → DB/ユーザー作成 → 接続情報保存）
powershell -ExecutionPolicy Bypass -File scripts\mysql-local\setup.ps1

# 2. 状態確認（プロセス・ポート・SELECT VERSION()）
powershell -ExecutionPolicy Bypass -File scripts\mysql-local\status.ps1

# 3. 停止
powershell -ExecutionPolicy Bypass -File scripts\mysql-local\stop.ps1

# 4. 起動（2 回目以降。PC 再起動後もこれ）
powershell -ExecutionPolicy Bypass -File scripts\mysql-local\start.ps1
```

`setup.ps1` は冪等で、済んでいる手順（zip あり・展開済み・data あり）はスキップする。再実行しても data と `guapp` ユーザーのパスワードは変わらない。

作成されるもの:

| 種類 | 名前 | 備考 |
| --- | --- | --- |
| DB | `guapp` | 開発用 |
| DB | `guapp_test` | IT 用（conftest は DB 名が `_test` で終わることを確認する） |
| ユーザー | `guapp`@`localhost` | ランダム 32 文字パスワード。両 DB に全権限 |
| ユーザー | `root`@`localhost` | **空パスワードのまま**（`--initialize-insecure`）。下記リスク参照 |

## 接続情報と DATABASE_URL

パスワードは画面に出さず `%LOCALAPPDATA%\guapp-mysql\credentials.txt` に保存する。`apps/api/.env` の `DATABASE_URL` には次の形で書く（`<MYSQL_PASSWORD>` を credentials.txt の値に置き換える。`.env` はコミット禁止）:

```
DATABASE_URL=mysql+asyncmy://guapp:<MYSQL_PASSWORD>@127.0.0.1:3306/guapp
DATABASE_URL_TEST=mysql+asyncmy://guapp:<MYSQL_PASSWORD>@127.0.0.1:3306/guapp_test
```

credentials.txt にはこの 2 行が実値入りで書かれているので、そのままコピーしてもよい。

## ポート衝突時（3306 が使われている）

別の MySQL などが 3306 を使っている場合は `-Port` を付けて setup を実行する（プラン 5 章の取り決めは 3307）:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\mysql-local\setup.ps1 -Port 3307
```

my.ini の `port` と credentials.txt の URL が新しいポートで書き直される。`start.ps1`／`stop.ps1`／`status.ps1` は my.ini の `port` を読むので引数は不要。**既に guapp-mysql の mysqld が起動している状態でポートを変えるときは、先に `stop.ps1` で止めてから** setup を実行する。

3306 を誰が使っているか調べる: `Get-NetTCPConnection -LocalPort 3306 | Select-Object OwningProcess` → `Get-Process -Id <PID>`。

## 停止忘れの注意

`status.ps1` の「プロセス」に PID が 2 つ出るのは正常（Windows 版 mysqld は監視プロセス＋サーバー本体の 2 プロセスで動く）。

`start.ps1` はバックグラウンドで mysqld を起動するため、PowerShell を閉じても **mysqld は動き続ける**。サインアウト・シャットダウン時は Windows が強制終了するので通常は壊れないが、行儀よく止めるには作業の終わりに `stop.ps1` を実行する。`status.ps1` で「プロセス: 起動中」なら動いている。

## セキュリティ上の注意（ローカル専用）

- `root` は空パスワード。`bind-address=127.0.0.1` で **同じ PC からしか接続できない**ため、開発 PC のローカル用途に限って許容している。この構成を共有サーバーや本番で使ってはいけない。
- `credentials.txt` にはパスワードが平文で入る。リポジトリ外（`%LOCALAPPDATA%`）にあり、`.gitignore` でも `.env`・`mysql-data/` は除外しているが、**ファイルをリポジトリ内にコピーしない**こと。
- X Plugin（ポート 33060）は `mysqlx=OFF` で無効化している。

## my.ini の主な設定値

| 項目 | 値 | 根拠 |
| --- | --- | --- |
| `port` | 3306（`-Port` で変更可） | 設計仕様書 8.2 |
| `bind-address` | 127.0.0.1 | ローカル専用 |
| `character-set-server` / `collation-server` | utf8mb4 / utf8mb4_0900_ai_ci | DS-DEC-25 |
| `default-time-zone` | '+00:00' | DS-DEC-16・25（UTC 保存・JST 表示） |
| `max_connections` | 200 | 同時実行テスト（テスト設計書 1.4 #1: プール 20 以上） |
| `lower_case_table_names` | 既定（Windows は 1） | 変更しない |

## トラブルシュート

| 症状 | 見る場所・対処 |
| --- | --- |
| setup が「MD5 が一致しません」 | ダウンロード途中で切れた。zip は自動削除されるので再実行 |
| start が「30 秒以内にポートが開きませんでした」 | `%LOCALAPPDATA%\guapp-mysql\mysqld.log` の末尾。VC++ ランタイム不足・ポート衝突・data 破損が典型 |
| `--initialize-insecure` が失敗 | `mysqld-init.log`。data フォルダを空にして再実行 |
| 完全に作り直したい | `stop.ps1` → `%LOCALAPPDATA%\guapp-mysql\data` と `credentials.txt` を削除 → `setup.ps1` |
