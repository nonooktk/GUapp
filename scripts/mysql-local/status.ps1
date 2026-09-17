# GUapp ローカル MySQL の状態を表示する（プロセス・ポート・VERSION()）。
# 使い方:  powershell -ExecutionPolicy Bypass -File scripts\mysql-local\status.ps1
$ErrorActionPreference = "Continue"
. (Join-Path $PSScriptRoot "common.ps1")

$port = Get-GuappMysqlPort
Write-Host "=== GUapp ローカル MySQL 状態（$GuappMysqlRoot） ==="
Write-Host "設定ファイル : $MyIniPath  $(if (Test-Path $MyIniPath) { '(あり)' } else { '(なし: setup.ps1 未実行)' })"
Write-Host "ポート       : $BindAddress`:$port"

$procs = @(Get-GuappMysqldProcess)
if ($procs.Count -gt 0) {
    Write-Host "プロセス     : 起動中 (PID $(($procs | ForEach-Object { $_.Id }) -join ', '))"
} else {
    Write-Host "プロセス     : なし"
}

$portOpen = Test-GuappMysqlPort -Port $port
Write-Host "ポート開放   : $(if ($portOpen) { '開いている' } else { '閉じている' })"

if ($portOpen -and (Test-Path $MysqlExe)) {
    try {
        $ver = Invoke-GuappMysqlRoot -Port $port -Silent -Sql "SELECT VERSION();"
        Write-Host "SELECT VERSION(): $ver"
        $dbs = Invoke-GuappMysqlRoot -Port $port -Silent -Sql "SHOW DATABASES LIKE 'guapp%';"
        Write-Host "DB (guapp%)  : $($dbs -join ', ')"
        exit 0
    } catch {
        Write-Host "SELECT VERSION(): 失敗 - $($_.Exception.Message)"
        exit 1
    }
} else {
    Write-Host "SELECT VERSION(): (未接続)"
    exit 1
}
