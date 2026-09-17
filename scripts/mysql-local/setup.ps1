# GUapp ローカル MySQL 8.4.11（zip 版）の初期セットアップ。
# 使い方:  powershell -ExecutionPolicy Bypass -File scripts\mysql-local\setup.ps1 [-Port 3307]
# 何をするか: ①zip 取得＋MD5 検証 ②展開 ③my.ini 生成 ④データ初期化 ⑤起動して DB・ユーザー作成 ⑥接続情報を保存
# 冪等: 済んでいる手順はスキップする。再実行しても data とパスワードは保持される。
param(
    [int]$Port = 0
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "common.ps1")

if ($Port -le 0) { $Port = Get-GuappMysqlPort }
if ($Port -lt 1024 -or $Port -gt 65535) { throw "ポートは 1024〜65535 で指定してください: $Port" }

Write-Host "=== GUapp ローカル MySQL $MysqlVersion セットアップ（port=$Port） ==="
Write-Host "配置先: $GuappMysqlRoot"
New-Item -ItemType Directory -Force -Path $GuappMysqlRoot | Out-Null

# ---------- ① ダウンロード（既にあればスキップ）＋ MD5 検証 ----------
if (Test-Path $MysqlZipPath) {
    Write-Host "[1/6] zip は既にあります。ダウンロードをスキップ: $MysqlZipPath"
} else {
    Write-Host "[1/6] ダウンロード中（約 268MB。数分かかります）: $MysqlZipUrl"
    $curl = Join-Path $env:SystemRoot "System32\curl.exe"
    if (Test-Path $curl) {
        & $curl -L -sS -o $MysqlZipPath $MysqlZipUrl
        if ($LASTEXITCODE -ne 0) { throw "curl によるダウンロードに失敗しました (exit $LASTEXITCODE)" }
    } else {
        $ProgressPreference = "SilentlyContinue"
        Invoke-WebRequest -Uri $MysqlZipUrl -OutFile $MysqlZipPath -UseBasicParsing
    }
}
$actualMd5 = (Get-FileHash -Algorithm MD5 -Path $MysqlZipPath).Hash.ToLower()
if ($actualMd5 -ne $MysqlZipMd5) {
    Remove-Item -Force $MysqlZipPath
    throw "MD5 が一致しません（期待 $MysqlZipMd5 / 実際 $actualMd5）。破損の可能性があるため zip を削除しました。再実行してください。"
}
Write-Host "[1/6] MD5 検証 OK: $actualMd5"

# ---------- ② 展開（bin\mysqld.exe があればスキップ） ----------
if (Test-Path $MysqldExe) {
    Write-Host "[2/6] 展開済み。スキップ: $MysqlHome"
} else {
    Write-Host "[2/6] 展開中: $MysqlHome"
    $tar = Join-Path $env:SystemRoot "System32\tar.exe"
    if (Test-Path $tar) {
        # Windows 10 以降同梱の bsdtar。Expand-Archive より速い
        & $tar -xf $MysqlZipPath -C $GuappMysqlRoot
        if ($LASTEXITCODE -ne 0) { throw "tar による展開に失敗しました (exit $LASTEXITCODE)" }
    } else {
        Expand-Archive -Path $MysqlZipPath -DestinationPath $GuappMysqlRoot -Force
    }
    if (-not (Test-Path $MysqldExe)) { throw "展開後に mysqld.exe が見つかりません: $MysqldExe" }
}
# VC++ ランタイム（mysqld.exe の依存）の存在確認。無ければ起動時に 0xc000007b 等で失敗する
$vcRuntime = Join-Path $env:SystemRoot "System32\vcruntime140_1.dll"
if (-not (Test-Path $vcRuntime)) {
    Write-Warning "Microsoft Visual C++ 2015-2022 再頒布可能パッケージ (x64) が見当たりません。mysqld が起動しない場合はインストールしてください（README 参照）。"
}

# ---------- ③ my.ini 生成 ----------
# パスは MySQL が読める forward slash にする
$basedirIni = $MysqlHome.Replace("\", "/")
$datadirIni = $DataDir.Replace("\", "/")
$myIni = @"
# GUapp ローカル MySQL 設定（scripts/mysql-local/setup.ps1 が生成。手で直したら stop → start）
# 設計仕様書 DS-DEC-25（utf8mb4・UTC）と同じ値。
[mysqld]
basedir=$basedirIni
datadir=$datadirIni
port=$Port
bind-address=$BindAddress
character-set-server=utf8mb4
collation-server=utf8mb4_0900_ai_ci
default-time-zone='+00:00'
max_connections=200
# X Plugin（33060 番）は使わないので無効化してポート衝突を避ける
mysqlx=OFF

[client]
port=$Port
host=$BindAddress
"@
[System.IO.File]::WriteAllText($MyIniPath, $myIni, (New-Object System.Text.UTF8Encoding($false)))
Write-Host "[3/6] my.ini を生成: $MyIniPath"

# ---------- ④ データディレクトリ初期化（data があればスキップ） ----------
if ((Test-Path $DataDir) -and ((Get-ChildItem $DataDir -Force | Measure-Object).Count -gt 0)) {
    Write-Host "[4/6] data は既に初期化済み。スキップ: $DataDir"
} else {
    Write-Host "[4/6] データディレクトリを初期化中（--initialize-insecure: root は空パスワード）..."
    $initLog = Join-Path $GuappMysqlRoot "mysqld-init.log"
    $p = Start-Process -FilePath $MysqldExe `
        -ArgumentList @("--defaults-file=`"$MyIniPath`"", "--initialize-insecure", "--console") `
        -WindowStyle Hidden -PassThru -Wait -RedirectStandardError $initLog
    if ($p.ExitCode -ne 0) {
        Write-Host "---- $initLog ----"
        Get-Content $initLog | ForEach-Object { Write-Host "  | $_" }
        throw "mysqld --initialize-insecure が失敗しました (exit $($p.ExitCode))"
    }
    Write-Host "[4/6] 初期化 OK（ログ: $initLog）"
}

# ---------- ⑤ 起動して DB・ユーザー作成 ----------
Write-Host "[5/6] mysqld を起動して DB とユーザーを作成..."
if (-not (Start-GuappMysqld -Port $Port)) { throw "mysqld の起動に失敗しました。" }

# パスワード: credentials.txt があれば再利用（再実行で変わらない）、無ければ 32 文字のランダム生成
$password = $null
if (Test-Path $CredentialsPath) {
    $m = Select-String -Path $CredentialsPath -Pattern '^MYSQL_PASSWORD=(.+)$' | Select-Object -First 1
    if ($m) { $password = $m.Matches[0].Groups[1].Value.Trim() }
}
if (-not $password) {
    $chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    $rng = New-Object System.Security.Cryptography.RNGCryptoServiceProvider
    $bytes = New-Object byte[] 32
    $rng.GetBytes($bytes)
    $password = -join ($bytes | ForEach-Object { $chars[$_ % $chars.Length] })
}

# SQL は stdin で渡す（コマンドライン引数にパスワードを残さない）。英数字のみなのでクォート不要
$sql = @"
CREATE DATABASE IF NOT EXISTS guapp CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE DATABASE IF NOT EXISTS guapp_test CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER IF NOT EXISTS 'guapp'@'localhost' IDENTIFIED BY '$password';
ALTER USER 'guapp'@'localhost' IDENTIFIED BY '$password';
GRANT ALL PRIVILEGES ON guapp.* TO 'guapp'@'localhost';
GRANT ALL PRIVILEGES ON guapp_test.* TO 'guapp'@'localhost';
FLUSH PRIVILEGES;
"@
Invoke-GuappMysqlRoot -Port $Port -Sql $sql
$dbs = Invoke-GuappMysqlRoot -Port $Port -Silent -Sql "SHOW DATABASES LIKE 'guapp%';"
Write-Host "[5/6] 作成済み DB: $($dbs -join ', ')  / ユーザー: guapp@localhost"

# ---------- ⑥ 接続情報を保存（リポジトリ外） ----------
$now = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$cred = @"
# GUapp ローカル MySQL 接続情報（setup.ps1 が $now に生成）
# このファイルはリポジトリ外にあります。コピーして .env に貼るときも .env はコミット禁止。
MYSQL_HOST=$BindAddress
MYSQL_PORT=$Port
MYSQL_USER=guapp
MYSQL_PASSWORD=$password
MYSQL_DATABASE=guapp
MYSQL_TEST_DATABASE=guapp_test
DATABASE_URL=mysql+asyncmy://guapp:$password@$BindAddress`:$Port/guapp
DATABASE_URL_TEST=mysql+asyncmy://guapp:$password@$BindAddress`:$Port/guapp_test
"@
# BOM 付き UTF-8（PowerShell 5.1 の Get-Content でも日本語コメントが化けない）
[System.IO.File]::WriteAllText($CredentialsPath, $cred, (New-Object System.Text.UTF8Encoding($true)))
Write-Host "[6/6] 接続情報を保存: $CredentialsPath"

Write-Host ""
Write-Host "=== セットアップ完了。MySQL は起動したままです（停止は stop.ps1） ==="
Write-Host "DATABASE_URL の形（パスワードの実値は $CredentialsPath を参照）:"
Write-Host "  mysql+asyncmy://guapp:<MYSQL_PASSWORD>@$BindAddress`:$Port/guapp"
Write-Host "  mysql+asyncmy://guapp:<MYSQL_PASSWORD>@$BindAddress`:$Port/guapp_test   (IT 用)"
Write-Host "注意: root は空パスワードのまま（localhost 限定・bind-address=$BindAddress）。ローカル開発専用です。"
