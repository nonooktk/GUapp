# GUapp ローカル MySQL を起動する（既に起動中なら何もしない）。
# 使い方:  powershell -ExecutionPolicy Bypass -File scripts\mysql-local\start.ps1
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

$port = Get-GuappMysqlPort
if (-not (Start-GuappMysqld -Port $port)) { exit 1 }
