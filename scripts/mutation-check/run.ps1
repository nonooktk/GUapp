# 防御外し確認（簡易ミューテーションテスト。テスト設計書 1.4 #8）。
# 「防御を 1 つ外すと該当 IT が赤になる」ことを機械的に確かめ、テストが防御を本当に見ていることを証明する。
#
#   powershell -ExecutionPolicy Bypass -File scripts\mutation-check\run.ps1 -Case all
#   powershell -ExecutionPolicy Bypass -File scripts\mutation-check\run.ps1 -Case 1
#
# 判定: 該当テストが赤 → 「防御が有効（PASS）」／緑 → 「テストが防御を見ていない（FAIL）」
# 復元: どのケースも finally でバックアップから必ず戻し、ハッシュ一致を確認する。ケース 1 は guapp_test の
#       schema も downgrade base → upgrade head で元に戻す。最後に `git diff --stat -- apps/` が空であることを表示する。
# 実行環境: Windows PowerShell 5.1（&& / || は使わない）。git 操作は読み取りの diff --stat のみ。

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("1", "2", "3", "all")]
    [string]$Case,

    # uv.exe のパス。空なら PATH → 既定の per-user 導入先の順で探す
    [string]$UvPath = "",

    # 復元後の再確認（ruff check・該当テストの緑）で該当テストが赤だったとき 1 回だけ再実行する
    [int]$GreenRetry = 1
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Continue"   # ネイティブコマンドの stderr で止めない。失敗は $LASTEXITCODE で見る

# ── パス ─────────────────────────────────────────────────────────────────────
$ScriptDir = $PSScriptRoot
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
$ApiDir = Join-Path $RepoRoot "apps\api"
$CasesPath = Join-Path $ScriptDir "cases.json"
$MutatePy = Join-Path $ScriptDir "mutate.py"
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$WorkDir = Join-Path $env:TEMP ("guapp-mutation-check\" + $Stamp)
$BackupRoot = Join-Path $WorkDir "backup"
$LogDir = Join-Path $WorkDir "logs"
New-Item -ItemType Directory -Force -Path $BackupRoot, $LogDir | Out-Null

$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Write-Step { param([string]$Message) Write-Host ("[mutation-check] " + $Message) }

# ── 外部コマンド実行（stdout+stderr をログに落とし、終了コードを返す） ─────────
function ConvertTo-WinArg {
    # 空白・引用符を含む引数を CommandLineToArgvW の規則で引用する（内側の " は \"、直前の \ は倍にする）
    param([string]$Arg)
    if ($Arg -eq "") { return '""' }
    if ($Arg -notmatch '[\s"]') { return $Arg }
    $sb = New-Object System.Text.StringBuilder
    [void]$sb.Append('"')
    $backslashes = 0
    foreach ($ch in $Arg.ToCharArray()) {
        if ($ch -eq '\') { $backslashes++; continue }
        if ($ch -eq '"') { [void]$sb.Append('\' * ($backslashes * 2 + 1)); [void]$sb.Append('"'); $backslashes = 0; continue }
        if ($backslashes -gt 0) { [void]$sb.Append('\' * $backslashes); $backslashes = 0 }
        [void]$sb.Append($ch)
    }
    if ($backslashes -gt 0) { [void]$sb.Append('\' * ($backslashes * 2)) }
    [void]$sb.Append('"')
    return $sb.ToString()
}

function Invoke-Logged {
    param(
        [string]$WorkingDirectory,
        [string]$Exe,
        [string[]]$Arguments,
        [string]$LogPath,
        [hashtable]$ExtraEnv = @{}
    )
    $saved = @{}
    foreach ($k in $ExtraEnv.Keys) {
        $saved[$k] = [Environment]::GetEnvironmentVariable($k, "Process")
        [Environment]::SetEnvironmentVariable($k, [string]$ExtraEnv[$k], "Process")
    }
    try {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $Exe
        $psi.WorkingDirectory = $WorkingDirectory
        $psi.UseShellExecute = $false
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
        $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8
        # .NET Framework（PS 5.1）には ArgumentList が無いので、Windows の規則で引用して 1 本の文字列にする
        $psi.Arguments = (($Arguments | ForEach-Object { ConvertTo-WinArg $_ }) -join " ")
        $proc = [System.Diagnostics.Process]::Start($psi)
        # デッドロック回避: stderr は非同期で読む
        $stderrTask = $proc.StandardError.ReadToEndAsync()
        $stdout = $proc.StandardOutput.ReadToEnd()
        $proc.WaitForExit()
        $stderr = $stderrTask.Result
        [IO.File]::WriteAllText($LogPath, ($stdout + "`n----- stderr -----`n" + $stderr), $Utf8NoBom)
        return $proc.ExitCode
    } finally {
        foreach ($k in $saved.Keys) { [Environment]::SetEnvironmentVariable($k, $saved[$k], "Process") }
    }
}

function Get-LogTail {
    param([string]$LogPath, [int]$Lines = 12)
    if (-not (Test-Path $LogPath)) { return "(ログ無し)" }
    # 1 行だけのときも配列にする（StrictMode で .Count が無いと落ちる）
    $all = @([IO.File]::ReadAllLines($LogPath, [System.Text.Encoding]::UTF8) | Where-Object { $_ -notmatch '^----- stderr -----$' -and $_.Trim() -ne "" })
    if ($all.Count -le $Lines) { return ($all -join "`n") }
    return (($all | Select-Object -Last $Lines) -join "`n")
}

function Get-PytestSummary {
    # 例: "1 failed, 38 passed in 18.09s" → @{failed=1; passed=38; errors=0; line=...}
    param([string]$LogPath)
    $result = @{ failed = 0; passed = 0; errors = 0; line = "(summary 行なし)" }
    if (-not (Test-Path $LogPath)) { return $result }
    $lines = [IO.File]::ReadAllLines($LogPath, [System.Text.Encoding]::UTF8)
    $summary = $lines | Where-Object { $_ -match '^(=+ )?\d+ (failed|passed|error)' -or $_ -match '^=+ .*(passed|failed|error).* in [\d.]+s' } | Select-Object -Last 1
    if ($summary) {
        $result.line = ($summary -replace '^=+\s*', '' -replace '\s*=+$', '')
        if ($summary -match '(\d+) failed') { $result.failed = [int]$Matches[1] }
        if ($summary -match '(\d+) passed') { $result.passed = [int]$Matches[1] }
        if ($summary -match '(\d+) errors?') { $result.errors = [int]$Matches[1] }
    }
    return $result
}

# ── 前提の解決 ───────────────────────────────────────────────────────────────
if ($UvPath -eq "") {
    $cmd = Get-Command uv -ErrorAction SilentlyContinue
    if ($cmd) { $UvPath = $cmd.Source }
    else { $UvPath = Join-Path $env:APPDATA "Python\Python312\Scripts\uv.exe" }
}
if (-not (Test-Path $UvPath)) { throw "uv が見つかりません: $UvPath（-UvPath で指定してください）" }

# DATABASE_URL_TEST: 環境変数 → %LOCALAPPDATA%\guapp-mysql\credentials.txt。値は表示しない
$TestUrl = $env:DATABASE_URL_TEST
if (-not $TestUrl) {
    $credPath = Join-Path $env:LOCALAPPDATA "guapp-mysql\credentials.txt"
    if (-not (Test-Path $credPath)) { throw "DATABASE_URL_TEST が未設定で、$credPath も無いため中止します（scripts\mysql-local\setup.ps1 を先に実行）" }
    $line = Get-Content $credPath | Where-Object { $_ -match '^\s*DATABASE_URL_TEST\s*=' } | Select-Object -First 1
    if (-not $line) { throw "credentials.txt に DATABASE_URL_TEST がありません" }
    $TestUrl = ($line -replace '^\s*DATABASE_URL_TEST\s*=\s*', '').Trim().Trim('"')
}
if ($TestUrl -notmatch '^mysql\+[a-z]+://[^@]+@([^:/]+):(\d+)/([^?]+)') { throw "DATABASE_URL_TEST の書式を解釈できません（mysql+driver://user:pass@host:port/db を期待）" }  # pragma: allowlist secret（書式説明のみ）
$DbHost = $Matches[1]; $DbPort = [int]$Matches[2]; $DbName = $Matches[3]
if (-not $DbName.EndsWith("_test")) { throw "DATABASE_URL_TEST の DB 名 '$DbName' が '_test' で終わっていません。開発 DB を壊す危険があるため中止します" }

# MySQL 到達確認（TCP）
$tcp = New-Object System.Net.Sockets.TcpClient
try {
    $async = $tcp.BeginConnect($DbHost, $DbPort, $null, $null)
    if (-not $async.AsyncWaitHandle.WaitOne(1000)) { throw "MySQL ${DbHost}:${DbPort} に接続できません（scripts\mysql-local\start.ps1 で起動）" }
    $tcp.EndConnect($async)
} finally { $tcp.Close() }

# apps/ に未コミット変更があると「復元後に diff が空」を確認できないので中止
$preDiff = (& git -C $RepoRoot diff --stat -- apps/) -join "`n"
if ($LASTEXITCODE -ne 0) { throw "git diff --stat が失敗しました（git が無い、または repo ではない）" }
if ($preDiff.Trim() -ne "") { throw "apps/ に未コミットの変更があります。復元確認ができないため中止します:`n$preDiff" }

Write-Step "repo=$RepoRoot"
Write-Step "uv=$UvPath"
Write-Step "MySQL=${DbHost}:${DbPort} db=$DbName（値は表示しない）"
Write-Step "作業フォルダ=$WorkDir"

$AllCases = (Get-Content $CasesPath -Encoding UTF8 -Raw | ConvertFrom-Json).cases
if ($Case -eq "all") { $Selected = @($AllCases) } else { $Selected = @($AllCases | Where-Object { [string]$_.id -eq $Case }) }
if ($Selected.Count -eq 0) { throw "ケース $Case が cases.json にありません" }

# 置換元がすべて 1 回ずつ見つかることを、何も変える前に確認する
Write-Step "置換元の事前確認（mutate.py --mode check）"
$rc = Invoke-Logged -WorkingDirectory $ApiDir -Exe $UvPath -Arguments @("run", "python", $MutatePy, "--cases", $CasesPath, "--root", $RepoRoot, "--case", $Case, "--mode", "check") -LogPath (Join-Path $LogDir "precheck.log") -ExtraEnv @{ PYTHONUTF8 = "1" }
Write-Host (Get-LogTail (Join-Path $LogDir "precheck.log") 20)
if ($rc -ne 0) { throw "置換元が見つからない（またはコード変更で位置が変わった）ため中止します。cases.json の old を worktree の実ファイルに合わせてください" }

# ── schema 作り直し（ケース 1） ────────────────────────────────────────────
function Rebuild-TestSchema {
    param([string]$Label)
    $envMap = @{ DATABASE_URL = $TestUrl; APP_ENV = "test"; PYTHONUTF8 = "1" }
    $rc1 = Invoke-Logged -WorkingDirectory $ApiDir -Exe $UvPath -Arguments @("run", "alembic", "downgrade", "base") -LogPath (Join-Path $LogDir "alembic-downgrade-$Label.log") -ExtraEnv $envMap
    if ($rc1 -ne 0) { throw "alembic downgrade base に失敗（$Label）。ログ: $LogDir\alembic-downgrade-$Label.log" }
    $rc2 = Invoke-Logged -WorkingDirectory $ApiDir -Exe $UvPath -Arguments @("run", "alembic", "upgrade", "head") -LogPath (Join-Path $LogDir "alembic-upgrade-$Label.log") -ExtraEnv $envMap
    if ($rc2 -ne 0) { throw "alembic upgrade head に失敗（$Label）。ログ: $LogDir\alembic-upgrade-$Label.log" }
    Write-Step "guapp_test の schema を作り直しました（$Label）"
}

# ── ケース実行 ───────────────────────────────────────────────────────────────
$Rows = @()
$AllTests = @()
foreach ($c in $Selected) {
    $cid = [int]$c.id
    $label = "case$cid"
    $t0 = Get-Date
    $status = ""; $judge = ""; $summaryLine = ""; $restoreNote = ""
    $files = @($c.files | ForEach-Object { $_.path })
    $AllTests += @($c.tests)
    Write-Step "===== ケース $cid : $($c.name) ====="
    Write-Step "外す箇所: $($c.removed)"

    # ① バックアップ（相対パスを保って temp へ）とハッシュ
    $hashes = @{}
    foreach ($f in $files) {
        $src = Join-Path $RepoRoot $f
        $dst = Join-Path (Join-Path $BackupRoot $label) $f
        New-Item -ItemType Directory -Force -Path (Split-Path $dst) | Out-Null
        Copy-Item -LiteralPath $src -Destination $dst -Force
        $hashes[$f] = (Get-FileHash -LiteralPath $src -Algorithm SHA256).Hash
    }
    Write-Step "バックアップ: $BackupRoot\$label（$($files.Count) ファイル）"

    try {
        # ② 防御を外す
        $rc = Invoke-Logged -WorkingDirectory $ApiDir -Exe $UvPath -Arguments @("run", "python", $MutatePy, "--cases", $CasesPath, "--root", $RepoRoot, "--case", "$cid", "--mode", "apply") -LogPath (Join-Path $LogDir "$label-apply.log") -ExtraEnv @{ PYTHONUTF8 = "1" }
        Write-Host (Get-LogTail (Join-Path $LogDir "$label-apply.log") 10)
        if ($rc -ne 0) { throw "置換元が見つからず中止（mutate.py exit $rc）" }

        # 外した後もモジュールが import できる（構文を壊していない）ことを確認。壊れていたら赤の理由が別物になる
        $mods = @($c.import_check)
        if ($mods.Count -gt 0) {
            $rc = Invoke-Logged -WorkingDirectory $ApiDir -Exe $UvPath -Arguments @("run", "python", "-c", ("import " + ($mods -join ", ") + "; print('import ok')")) -LogPath (Join-Path $LogDir "$label-import.log") -ExtraEnv @{ PYTHONUTF8 = "1" }
            if ($rc -ne 0) { throw "防御を外した後の import に失敗（置換がコードを壊した）: " + (Get-LogTail (Join-Path $LogDir "$label-import.log") 5) }
        }

        # ③ ケース 1 は schema を作り直す（UNIQUE の無い orders 表にする）
        if ([bool]$c.rebuild_schema) { Rebuild-TestSchema -Label "$label-mutated" }

        # ④ 該当テストだけ実行
        $pytestArgs = @("run", "pytest", "-q", "-p", "no:cacheprovider", "--tb=short") + @($c.tests)
        Write-Step ("実行: uv " + ($pytestArgs -join " "))
        $rc = Invoke-Logged -WorkingDirectory $ApiDir -Exe $UvPath -Arguments $pytestArgs -LogPath (Join-Path $LogDir "$label-pytest.log") -ExtraEnv @{ DATABASE_URL_TEST = $TestUrl; PYTHONUTF8 = "1" }
        $sum = Get-PytestSummary (Join-Path $LogDir "$label-pytest.log")
        $summaryLine = $sum.line
        Write-Host (Get-LogTail (Join-Path $LogDir "$label-pytest.log") 15)

        # ⑤ 判定
        if ($rc -eq 0) {
            $status = "緑（exit 0: $summaryLine）"
            $judge = "FAIL: テストが防御を見ていない"
        } elseif ($rc -eq 1 -and $sum.failed -ge [int]$c.min_failed) {
            $status = "赤（exit 1: $summaryLine）"
            $judge = "PASS: 防御が有効"
        } elseif ($rc -eq 1) {
            $status = "赤だが failed=$($sum.failed) < min_failed=$($c.min_failed)（$summaryLine）"
            $judge = "判定不能: 失敗数が少ない（フレークの疑い。ログを確認）"
        } else {
            $status = "pytest exit $rc（$summaryLine）"
            $judge = "判定不能: テスト自体が動かなかった（環境・収集エラー）"
        }
    } catch {
        $status = "中止: " + $_.Exception.Message
        $judge = "判定不能"
    } finally {
        # ⑥ 復元（例外時も必ず）。ハッシュで元と同一か確認
        $restored = @()
        foreach ($f in $files) {
            $src = Join-Path (Join-Path $BackupRoot $label) $f
            $dst = Join-Path $RepoRoot $f
            Copy-Item -LiteralPath $src -Destination $dst -Force
            $after = (Get-FileHash -LiteralPath $dst -Algorithm SHA256).Hash
            if ($after -eq $hashes[$f]) { $restored += "${f}: 復元OK（SHA256 一致）" } else { $restored += "${f}: 復元NG（SHA256 不一致）" }
        }
        $restoreNote = ($restored -join "; ")
        Write-Step "復元: $restoreNote"
        if ([bool]$c.rebuild_schema) {
            try { Rebuild-TestSchema -Label "$label-restored" }
            catch { $restoreNote += "; schema 復元NG: " + $_.Exception.Message; Write-Step $restoreNote }
        }
    }
    $sec = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1)
    Write-Step "判定: $judge（$sec 秒）"
    $Rows += New-Object PSObject -Property @{
        id = $cid; name = [string]$c.name; removed = [string]$c.removed; tests = (@($c.tests) -join "<br>")
        expected = [string]$c.expected_red; actual = $status; judge = $judge; seconds = $sec; restore = $restoreNote
    }
}

# ── 復元後の再確認 ───────────────────────────────────────────────────────────
Write-Step "===== 復元後の再確認 ====="
$rcRuff = Invoke-Logged -WorkingDirectory $ApiDir -Exe $UvPath -Arguments @("run", "ruff", "check", ".") -LogPath (Join-Path $LogDir "post-ruff.log") -ExtraEnv @{ PYTHONUTF8 = "1" }
$ruffLine = Get-LogTail (Join-Path $LogDir "post-ruff.log") 3
Write-Step "ruff check: exit $rcRuff / $ruffLine"

$AllTests = @($AllTests | Select-Object -Unique)
$greenLines = @()
$attempt = 0
$rcGreen = -1
while ($attempt -le $GreenRetry) {
    $attempt++
    $pytestArgs = @("run", "pytest", "-q", "-p", "no:cacheprovider", "--tb=short") + $AllTests
    $rcGreen = Invoke-Logged -WorkingDirectory $ApiDir -Exe $UvPath -Arguments $pytestArgs -LogPath (Join-Path $LogDir "post-pytest-$attempt.log") -ExtraEnv @{ DATABASE_URL_TEST = $TestUrl; PYTHONUTF8 = "1" }
    $sumG = Get-PytestSummary (Join-Path $LogDir "post-pytest-$attempt.log")
    $greenLines += "試行 ${attempt}: exit $rcGreen / $($sumG.line)"
    Write-Step ("該当テスト（復元後）" + $greenLines[-1])
    if ($rcGreen -eq 0) { break }
    Write-Host (Get-LogTail (Join-Path $LogDir "post-pytest-$attempt.log") 15)
}

$postDiff = (& git -C $RepoRoot diff --stat -- apps/) -join "`n"
if ($postDiff.Trim() -eq "") { $diffNote = "（空）apps/ に差分なし" } else { $diffNote = "差分あり（復元漏れ！）:`n$postDiff" }
Write-Step "git diff --stat -- apps/ : $diffNote"

# ── 結果表（Markdown） ─────────────────────────────────────────────────────
$Today = Get-Date -Format "yyyyMMdd"
$ResultPath = Join-Path $ScriptDir "result-$Today.md"
if (Test-Path $ResultPath) { $ResultPath = Join-Path $ScriptDir ("result-$Today-" + (Get-Date -Format "HHmmss") + ".md") }

$overall = "PASS"
foreach ($r in $Rows) { if ($r.judge -notlike "PASS*") { $overall = "要確認" } }
if ($rcRuff -ne 0 -or $rcGreen -ne 0 -or $postDiff.Trim() -ne "") { $overall = "要確認" }

$md = @()
$md += "# 防御外し確認（テスト設計書 1.4 #8）結果 $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
$md += ""
$md += "- 対象: ``-Case $Case``／総合: **$overall**"
$md += "- worktree: ``$RepoRoot``"
$md += "- DB: ${DbHost}:${DbPort}/$DbName（URL は表示しない）"
$md += "- ログ: ``$LogDir``"
$md += ""
$md += "| ケース | 外した箇所 | 実行テスト | 期待 | 実際 | 判定 | 所要秒 |"
$md += "| --- | --- | --- | --- | --- | --- | --- |"
foreach ($r in ($Rows | Sort-Object id)) {
    $md += "| $($r.id) $($r.name) | $($r.removed) | $($r.tests) | 赤: $($r.expected) | $($r.actual) | **$($r.judge)** | $($r.seconds) |"
}
$md += ""
$md += "## 復元確認"
$md += ""
foreach ($r in ($Rows | Sort-Object id)) { $md += "- ケース $($r.id): $($r.restore)" }
$md += "- ``uv run ruff check .``: exit $rcRuff（$ruffLine）"
foreach ($g in $greenLines) { $md += "- 該当テスト再実行（復元後）$g" }
$md += "- ``git diff --stat -- apps/``: $diffNote"
[IO.File]::WriteAllText($ResultPath, (($md -join "`n") + "`n"), $Utf8NoBom)

Write-Host ""
Write-Host (($md -join "`n"))
Write-Host ""
Write-Step "結果表: $ResultPath"
if ($overall -ne "PASS") { exit 1 }
exit 0
