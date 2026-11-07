<#
.SYNOPSIS
  Runs the desktop tests that need a standard (non-admin) token as a throw-away local standard user
  (Plan 6 review I1). Windows PowerShell 5.1; run from desktop\ after the default-feature test build.

.DESCRIPTION
  The GitHub runner's user is an elevated administrator, so every test that proves "without admin rights:
  exit 1 and change nothing" skips there with a "SKIPPED ..." line (winutil::skip_when_elevated). This
  script runs exactly those tests again under a standard token, so they are a real gate:

  1. The tests: every test function that calls skip_when_elevated (found in src\ and tests\, so a new one
     is picked up without editing this script) plus the ones named in $Extra (they need a standard token
     too, or print SKIPPED for another reason). Each must exist in a test binary of the default-feature
     build (cargo test --no-run --message-format=json); a name that is not found fails the step.
  2. A local account in Users only (never Administrators) with a random password. The password is masked
     in the log (::add-mask::) and never printed or written to a file.
  3. The account gets read/execute on the test binaries and target\debug\mcp-monitor.exe (the exe the
     integration tests start) and modify on one scratch folder under RUNNER_TEMP. Its own profile gives it
     %LOCALAPPDATA%, where the tests make their scratch folders.
  4. powershell.exe runs inner-standard-user.ps1 as that account (Start-Process -Credential, profile
     loaded). It records whoami /groups (no High Mandatory Level, no Administrators) and runs each binary
     with --exact <names> --test-threads=1.
  5. Fails when: the account's token is elevated or in Administrators, a binary exits non-zero, a wanted
     test is not reported "ok", or any output line contains "SKIPPED". The account is deleted at the end.
#>
[CmdletBinding()]
param(
    # Test functions that need a standard token without calling skip_when_elevated.
    [string[]]$Extra = @(
        "elevation_agrees_with_the_mandatory_label",
        "autostart_without_an_install_exits_1_and_writes_nothing"
    )
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$Desktop = (Get-Location).Path
if (-not (Test-Path -LiteralPath (Join-Path $Desktop "Cargo.toml"))) { throw "run from desktop\" }

# 1. The wanted test names.
$wanted = New-Object System.Collections.Generic.SortedSet[string]
foreach ($file in Get-ChildItem -Recurse -File -Filter *.rs -Path (Join-Path $Desktop "src"), (Join-Path $Desktop "tests")) {
    $fn = $null
    foreach ($line in [System.IO.File]::ReadAllLines($file.FullName)) {
        if ($line -match '^\s*(?:pub(?:\([^)]*\))?\s+)?(?:unsafe\s+)?fn\s+([A-Za-z0-9_]+)') { $fn = $Matches[1] }
        if ($line -match 'skip_when_elevated\(' -and $line -notmatch 'fn\s+skip_when_elevated' -and $fn) {
            [void]$wanted.Add($fn)
        }
    }
}
foreach ($n in $Extra) { [void]$wanted.Add($n) }
Write-Host "tests that need a standard token ($($wanted.Count)): $($wanted -join ', ')"

# The default-feature test binaries (already built: this lists them without building anything new).
$ErrorActionPreference = "Continue"
$messages = & cargo test --locked --no-run --message-format=json 2>$null
$code = $LASTEXITCODE
$ErrorActionPreference = "Stop"
if ($code -ne 0) { throw "cargo test --no-run exited $code" }
$binaries = @($messages | Where-Object { $_ -like '{*' } | ForEach-Object { $_ | ConvertFrom-Json } |
    Where-Object { $_.reason -eq "compiler-artifact" -and $_.profile.test -and $_.executable } |
    ForEach-Object { $_.executable } | Sort-Object -Unique)
if ($binaries.Count -eq 0) { throw "no test binaries" }

# Which binary holds which wanted test (full paths, for --exact).
$plan = @()
$found = New-Object System.Collections.Generic.HashSet[string]
foreach ($exe in $binaries) {
    $ErrorActionPreference = "Continue"
    $listed = & $exe --list 2>$null
    $ErrorActionPreference = "Stop"
    $mine = @($listed | Where-Object { $_ -match '^(\S+): test$' } | ForEach-Object { $_ -replace ': test$', '' } |
        Where-Object { $wanted.Contains(($_ -split '::')[-1]) })
    if ($mine.Count -gt 0) {
        $plan += , @($exe, $mine)
        foreach ($m in $mine) { [void]$found.Add(($m -split '::')[-1]) }
    }
}
$missing = @($wanted | Where-Object { -not $found.Contains($_) })
if ($missing.Count -gt 0) { throw "not found in any test binary (renamed? update `$Extra): $($missing -join ', ')" }

# 2. The account.
$user = "mcpmon-std-" + (Get-Random -Minimum 1000 -Maximum 9999)
$bytes = New-Object byte[] 24
(New-Object System.Security.Cryptography.RNGCryptoServiceProvider).GetBytes($bytes)
$password = [Convert]::ToBase64String($bytes) + "aA1!"
Write-Host "::add-mask::$password"
$computer = [ADSI]"WinNT://$env:COMPUTERNAME,computer"
$account = $computer.Create("User", $user)
$account.SetPassword($password)
$account.Put("Description", "MCP Monitor CI standard user (deleted at the end of the step)")
$account.SetInfo()
$usersGroup = (New-Object System.Security.Principal.SecurityIdentifier "S-1-5-32-545").Translate([System.Security.Principal.NTAccount]).Value.Split("\")[-1]
([ADSI]"WinNT://$env:COMPUTERNAME/$usersGroup,group").Add("WinNT://$env:COMPUTERNAME/$user,user")
Write-Host "created local account $user (member of $usersGroup only)"

$work = Join-Path $env:RUNNER_TEMP "standard-user"
try {
    # 3. Rights: the binaries, the exe they start, and one scratch folder for the logs.
    New-Item -ItemType Directory -Force -Path $work | Out-Null
    $grant = @{}
    foreach ($p in $plan) { $grant[$p[0]] = "(RX)" }
    $grant[(Join-Path $Desktop "target\debug\mcp-monitor.exe")] = "(RX)"
    $grant[$work] = "(OI)(CI)(M)"
    foreach ($path in $grant.Keys) {
        & icacls.exe $path /grant "${user}:$($grant[$path])" /Q | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "icacls $path exited $LASTEXITCODE" }
    }
    $listFile = Join-Path $work "binaries.txt"
    $lines = foreach ($p in $plan) { "$($p[0])`t$($p[1] -join ' ')" }
    [System.IO.File]::WriteAllLines($listFile, [string[]]$lines)
    $inner = Join-Path $work "inner-standard-user.ps1"
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "inner-standard-user.ps1") -Destination $inner

    # 4. Run as the account. The Secondary Logon service starts the process (CreateProcessWithLogonW).
    $svc = Get-Service seclogon
    if ($svc.StartType -eq "Disabled") { Set-Service seclogon -StartupType Manual }
    if ($svc.Status -ne "Running") { Start-Service seclogon }
    $credential = New-Object System.Management.Automation.PSCredential(".\$user", (ConvertTo-SecureString $password -AsPlainText -Force))
    $ps = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
    $p = Start-Process -FilePath $ps -Credential $credential -LoadUserProfile -WorkingDirectory $work `
        -ArgumentList @("-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", "`"$inner`"", "-ListFile", "`"$listFile`"", "-OutDir", "`"$work`"") `
        -RedirectStandardOutput (Join-Path $work "inner.out") -RedirectStandardError (Join-Path $work "inner.err") -Wait -PassThru
    Write-Host "----- inner script (exit $($p.ExitCode)) -----"
    Get-Content -LiteralPath (Join-Path $work "inner.out"), (Join-Path $work "inner.err") -ErrorAction SilentlyContinue | Write-Host

    # 5. Verdict.
    $problems = @()
    if ($p.ExitCode -ne 0) { $problems += "the inner script exited $($p.ExitCode)" }
    $groups = Get-Content -Raw -LiteralPath (Join-Path $work "whoami.txt") -ErrorAction SilentlyContinue
    if (-not $groups) { $problems += "no whoami /groups record" }
    elseif ($groups -match 'S-1-16-12288|S-1-16-16384' -or $groups -match '"S-1-5-32-544"') { $problems += "the account's token is elevated or in Administrators" }
    elseif ($groups -notmatch 'S-1-16-8192') { $problems += "the account's token is not Medium Mandatory Level" }
    for ($i = 0; $i -lt $plan.Count; $i++) {
        $exe, $names = $plan[$i]
        $log = Join-Path $work "test-$i.log"
        $text = if (Test-Path -LiteralPath $log) { [System.IO.File]::ReadAllText($log) } else { "" }
        Write-Host "----- $(Split-Path -Leaf $exe) -----"
        Write-Host $text
        $codeFile = Join-Path $work "test-$i.code"
        $exit = if (Test-Path -LiteralPath $codeFile) { (Get-Content -LiteralPath $codeFile).Trim() } else { "none" }
        if ($exit -ne "0") { $problems += "$(Split-Path -Leaf $exe) exited $exit" }
        foreach ($n in $names) {
            if ($text -notmatch "(?m)^test $([regex]::Escape($n)) \.\.\. ok\r?$") { $problems += "$n was not reported ok" }
        }
        foreach ($l in ($text -split "`r?`n" | Where-Object { $_ -match 'SKIPPED' })) { $problems += "skipped: $l" }
    }
    if ($problems.Count -gt 0) {
        $problems | ForEach-Object { Write-Host "::error::standard-user tests: $_" }
        throw "standard-user tests failed ($($problems.Count) problem(s))"
    }
    Write-Host "standard-user tests: $($wanted.Count) tests in $($plan.Count) binaries passed as $user (Medium Mandatory Level, not an administrator)"
} finally {
    try { $computer.Delete("User", $user); Write-Host "deleted local account $user" } catch { Write-Host "::warning::could not delete $user`: $_" }
}
