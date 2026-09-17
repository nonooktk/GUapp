# GUapp ローカル MySQL を停止する（mysqladmin shutdown）。
# 使い方:  powershell -ExecutionPolicy Bypass -File scripts\mysql-local\stop.ps1
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

$port = Get-GuappMysqlPort
if (-not (Test-GuappMysqlPort -Port $port)) {
    Write-Host "[stop] ポート $port は閉じています。起動していないので何もしません。"
    exit 0
}
if (-not (Test-Path $MysqladminExe)) { throw "mysqladmin.exe が見つかりません: $MysqladminExe" }

Write-Host "[stop] mysqladmin shutdown を送信（port=$port）..."
& $MysqladminExe --no-defaults -u root --protocol=TCP -h $BindAddress --port=$port shutdown
if ($LASTEXITCODE -ne 0) { throw "mysqladmin shutdown が失敗しました (exit $LASTEXITCODE)" }

if (-not (Wait-GuappMysqlPort -Port $port -Open $false -TimeoutSec 30)) {
    Write-Host "[stop] NG: 30 秒以内にポートが閉じませんでした。プロセスを確認してください（status.ps1）。"
    exit 1
}
# Windows 版 mysqld は監視プロセス＋サーバー本体の 2 プロセス。両方が終わるまで待つ（最大 30 秒）
$deadline = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $deadline -and @(Get-GuappMysqldProcess).Count -gt 0) { Start-Sleep -Milliseconds 500 }
$remain = @(Get-GuappMysqldProcess)
if ($remain.Count -gt 0) {
    Write-Host "[stop] 注意: ポートは閉じましたが mysqld プロセスが残っています (PID $(($remain | ForEach-Object { $_.Id }) -join ', '))。"
    exit 1
}
Write-Host "[stop] OK: 停止しました。"
