# scripts/mutation-check — 防御外し確認（テスト設計書 1.4 #8）

同時実行テスト IT-014-02〜04 が「防御を本当に見ている」ことを、防御を 1 つずつ外して赤くなることで確かめる簡易ミューテーションテスト。防御が壊れていても緑になる偽陽性（テスト設計書 1.4 冒頭）を仕組みで検出する。実施は Wave 3（検収）。

## 何を外し、何が赤になるか

| ケース | 外す防御 | 対象ファイル | 赤になるべきテスト |
| --- | --- | --- | --- |
| 1 | 冪等キー UNIQUE | `apps/api/app/models/order.py`（`unique=True`）と `apps/api/alembic/versions/0001_p1_initial.py`（`UniqueConstraint("idempotency_key")`）。外した後に guapp_test を `alembic downgrade base` → `upgrade head` で作り直す | IT-014-02（同一キー 20 同時。全応答 200/201・201 は 1 回が崩れる） |
| 2 | カートの条件付き UPDATE | `apps/api/app/repositories/orders.py` `mark_cart_ordered` の `Cart.status == CartStatus.active` | IT-014-03（両方 201 になる） |
| 3 | 在庫の `stock >= :q` | 同ファイル `reserve_stock` の `Variant.stock >= quantity` | IT-014-04（両方 201 か CHECK 違反で 500）と UT-014-04 |

外す箇所の正本は `cases.json`（`old` → `new` の文字列置換）。`old` が対象ファイルに**ちょうど 1 回**見つからなければ何も変えずに中止する（コードの位置が変わったら `cases.json` を直す）。

## 前提

- MySQL 8.4 が起動していて `guapp_test` がある（`scripts/mysql-local/start.ps1`。`status.ps1` で確認）
- `apps/api` で `uv sync` 済み
- `DATABASE_URL_TEST` が環境変数にあるか、`%LOCALAPPDATA%\guapp-mysql\credentials.txt` に書かれている（スクリプトが読む。値は表示・記録しない）。DB 名が `_test` で終わらなければ中止する
- `apps/` に未コミットの変更が無い（あると「復元後に差分が空」を確認できないので中止する）
- ポート 8000 は使わない（IT の `live_server` が空きポートで uvicorn を起動する）

## 使い方

リポジトリ（worktree）ルートで:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\mutation-check\run.ps1 -Case all   # 3 件すべて（約 2 分）
powershell -ExecutionPolicy Bypass -File scripts\mutation-check\run.ps1 -Case 3     # 1 件だけ
# uv が PATH に無いとき
powershell -ExecutionPolicy Bypass -File scripts\mutation-check\run.ps1 -Case all -UvPath "$env:APPDATA\Python\Python312\Scripts\uv.exe"
```

各ケースの流れ: ①対象ファイルを `%TEMP%\guapp-mutation-check\<日時>\backup\` へバックアップ（SHA256 を記録）→ ②`mutate.py` で防御を外す → 外した後も `import` が通ることを確認（置換がコードを壊していないか）→ ③ケース 1 は schema を作り直す → ④該当テストだけ `uv run pytest -q <file>::<test>` → ⑤判定 → ⑥`finally` でバックアップから復元し SHA256 一致を確認、ケース 1 は schema も元に戻す。

全ケース後に `uv run ruff check .`、該当テストの緑（赤なら 1 回だけ再実行して両方記録）、`git diff --stat -- apps/` が空であることを確認して表示する。

## 判定

| pytest の結果 | 判定 |
| --- | --- |
| 赤（exit 1、failed が `cases.json` の `min_failed` 以上） | **PASS: 防御が有効**（テストは防御を見ている） |
| 緑（exit 0） | **FAIL: テストが防御を見ていない** → 重大。原因を調べてコーディネーターに報告（テストの修正はコーディネーター判断） |
| 赤だが failed が `min_failed` 未満／exit 2 以上（収集エラー等）／置換元なし | **判定不能** → ログを見る |

`min_failed` はケース 3 だけ 2（IT-014-04 は 30 反復なので、防御が無ければほぼ全回赤になる。1 回だけの赤は同時性フレークと区別できないため）。

## 出力

- `scripts/mutation-check/result-<YYYYMMDD>.md`: 結果表（ケース・外した箇所・実行テスト・期待＝赤・実際・判定・所要秒）と復元確認。同日に 2 回目以降は `-HHmmss` が付く。テスト設計書 10 章の実施記録に転記する
- `%TEMP%\guapp-mutation-check\<日時>\logs\`: 各ステップの stdout/stderr（`caseN-pytest.log`・`alembic-*.log`・`post-*.log`）

終了コード: 全ケース PASS かつ復元確認がすべて OK なら 0、それ以外は 1。

## 注意

- **実行中は guapp_test の schema と内容が一時的に変わる**（ケース 1 は表を全部落として作り直す）。開発 DB `guapp` には触らない（URL の DB 名 `_test` を強制）
- **復元は例外時も含めて必ず行う**が、途中で強制終了（Ctrl+C・電源断）した場合は `git diff --stat -- apps/` と `git status` で `apps/` に差分が残っていないか確認し、残っていればバックアップ（上記 `%TEMP%` 配下）または `git checkout -- apps/`（コーディネーター判断）で戻す。復元漏れは本番コードの防御に穴を残す
- git 操作は読み取りの `git diff --stat` だけ。commit・checkout・stash はしない
- ベースライン（防御を外さない状態）で IT-014-04 がまれに `inflight_max=1` で赤になることがある（2026-09-18 に 90 反復中 1 回）。復元後の再確認で赤が出たら再実行の結果も併記されるので、両方を結果表で確認する
