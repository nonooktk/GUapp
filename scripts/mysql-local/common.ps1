# GUapp ローカル MySQL（zip 版）共通定義。各スクリプトから dot-source する。
# 実行環境: Windows PowerShell 5.1、管理者権限なし。
# すべてのファイルはリポジトリ外 %LOCALAPPDATA%\guapp-mysql\ に置く（P1 実装プラン 3 章）。

Set-StrictMode -Version 2.0

$script:MysqlVersion = "8.4.11"
$script:MysqlZipName = "mysql-$script:MysqlVersion-winx64.zip"
$script:MysqlZipUrl = "https://dev.mysql.com/get/Downloads/MySQL-8.4/$script:MysqlZipName"
$script:MysqlZipMd5 = "2e833921898a9a030ea6bfe81bd811bc"  # pragma: allowlist secret（zip の MD5 チェックサム。秘密ではない）

$script:GuappMysqlRoot = Join-Path $env:LOCALAPPDATA "guapp-mysql"
$script:MysqlZipPath = Join-Path $GuappMysqlRoot $MysqlZipName
$script:MysqlHome = Join-Path $GuappMysqlRoot "mysql-$script:MysqlVersion-winx64"
$script:MysqlBin = Join-Path $MysqlHome "bin"
$script:MysqldExe = Join-Path $MysqlBin "mysqld.exe"
$script:MysqlExe = Join-Path $MysqlBin "mysql.exe"
$script:MysqladminExe = Join-Path $MysqlBin "mysqladmin.exe"
$script:MyIniPath = Join-Path $GuappMysqlRoot "my.ini"
$script:DataDir = Join-Path $GuappMysqlRoot "data"
$script:CredentialsPath = Join-Path $GuappMysqlRoot "credentials.txt"
$script:MysqldLogPath = Join-Path $GuappMysqlRoot "mysqld.log"
$script:DefaultPort = 3306
$script:BindAddress = "127.0.0.1"

function Get-GuappMysqlPort {
    # my.ini があればその port を、無ければ既定 3306 を返す
    if (Test-Path $MyIniPath) {
        $line = Select-String -Path $MyIniPath -Pattern '^\s*port\s*=\s*(\d+)' | Select-Object -First 1
        if ($line) { return [int]$line.Matches[0].Groups[1].Value }
    }
    return $DefaultPort
}

function Test-GuappMysqlPort {
    param([int]$Port)
    # TCP 接続を試みてポートが開いているかを返す（Test-NetConnection より速い）
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect($BindAddress, $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne(500)) { return $false }
        $client.EndConnect($async)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Wait-GuappMysqlPort {
    param([int]$Port, [bool]$Open = $true, [int]$TimeoutSec = 30)
    # ポートが Open（開く）/ Close（閉じる）まで最大 TimeoutSec 秒待つ。到達したら $true
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if ((Test-GuappMysqlPort -Port $Port) -eq $Open) { return $true }
        Start-Sleep -Milliseconds 500
    }
    return ((Test-GuappMysqlPort -Port $Port) -eq $Open)
}

function Get-GuappMysqldProcess {
    # このフォルダの mysqld.exe だけを返す（他の MySQL とは区別する）
    Get-Process -Name mysqld -ErrorAction SilentlyContinue | Where-Object {
        try { $_.Path -and ($_.Path -ieq $MysqldExe) } catch { $false }
    }
}

function Start-GuappMysqld {
    param([int]$Port)
    # mysqld をバックグラウンド起動し、ポートが開くまで最大 30 秒待つ。成功なら $true
    if (-not (Test-Path $MysqldExe)) { throw "mysqld.exe が見つかりません: $MysqldExe（先に setup.ps1 を実行してください）" }
    if (-not (Test-Path $MyIniPath)) { throw "my.ini が見つかりません: $MyIniPath（先に setup.ps1 を実行してください）" }
    if (Test-GuappMysqlPort -Port $Port) {
        Write-Host "[start] ポート $Port は既に開いています。起動済みとみなして何もしません。"
        return $true
    }
    # --console でエラーログを stderr に出し、mysqld.log に書き出す
    $proc = Start-Process -FilePath $MysqldExe `
        -ArgumentList @("--defaults-file=`"$MyIniPath`"", "--console") `
        -WindowStyle Hidden -PassThru -RedirectStandardError $MysqldLogPath
    Write-Host "[start] mysqld を起動しました (PID $($proc.Id))。ポート $Port が開くのを待ちます（最大 30 秒）..."
    if (Wait-GuappMysqlPort -Port $Port -Open $true -TimeoutSec 30) {
        Write-Host "[start] OK: 127.0.0.1:$Port で待ち受け中。ログ: $MysqldLogPath"
        return $true
    }
    Write-Host "[start] NG: 30 秒以内にポートが開きませんでした。ログを確認してください: $MysqldLogPath"
    if (Test-Path $MysqldLogPath) { Get-Content $MysqldLogPath -Tail 20 | ForEach-Object { Write-Host "  | $_" } }
    return $false
}

function Invoke-GuappMysqlRoot {
    param([int]$Port, [string]$Sql, [switch]$Silent)
    # root（空パスワード・localhost 限定）で SQL を実行する。SQL は stdin で渡す（引数に残さない）
    $mysqlArgs = @("--no-defaults", "-u", "root", "--protocol=TCP", "-h", $BindAddress, "--port=$Port", "--batch")
    if ($Silent) { $mysqlArgs += "--skip-column-names" }
    $Sql | & $MysqlExe @mysqlArgs
    if ($LASTEXITCODE -ne 0) { throw "mysql の実行に失敗しました (exit $LASTEXITCODE)" }
}
