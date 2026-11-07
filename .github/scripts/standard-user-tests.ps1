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

  With -ReleaseExe <path> (the release job, Plan 6 re-review nit 3) step 1 is replaced: instead of the test
  binaries the account runs the release exe's `install --install-dir <scratch>\i --data-root <scratch>\d`
  (the server test test_desktop_exe.py::test_install_without_admin_changes_nothing, which skips on the
  elevated runner). It must exit 1 with the "run as administrator" line on stdout and create neither
  folder nor <scratch>\i.staging; <scratch> is a folder in the account's own %LOCALAPPDATA%.
#>
[CmdletBinding()]
param(
    # Test functions that need a standard token without calling skip_when_elevated.
    [string[]]$Extra = @(
        "elevation_agrees_with_the_mandatory_label",
        "autostart_without_an_install_exits_1_and_writes_nothing",
        "a_locked_data_root_is_unreadable_without_admin"
    ),
    # The release exe to check instead of the test binaries (see -ReleaseExe above).
    [string]$ReleaseExe
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$Desktop = (Get-Location).Path
if (-not (Test-Path -LiteralPath (Join-Path $Desktop "Cargo.toml"))) { throw "run from desktop\" }

# One run per entry: Exe, Args (the inner script expands %VARIABLES% as the account), Gone (paths that
# must not exist afterwards, '|'-separated, expanded the same way), Names (tests that must be reported
# ok), ExitCode (the wanted exit code), Expect (a regex the output must match, or "").
$plan = @()
if ($ReleaseExe) {
    $ReleaseExe = (Resolve-Path -LiteralPath $ReleaseExe).Path
    $s = "%MCPMON_STD_SCRATCH%"
    $plan += [pscustomobject]@{
        Exe = $ReleaseExe
        Args = "install --install-dir `"$s\i`" --data-root `"$s\d`""
        Gone = "$s\i|$s\d|$s\i.staging"
        Names = @()
        ExitCode = "1"
        # The ADMIN_MESSAGE line (desktop\src\install\plan.rs), escaped: Windows PowerShell 5.1 reads this
        # file in the ANSI code page.
        Expect = '(?m)^\uAD00\uB9AC\uC790 \uAD8C\uD55C\uC73C\uB85C \uB2E4\uC2DC \uC2E4\uD589\uD558\uC138\uC694'
    }
    $wanted = @("release exe: install without admin")
    Write-Host "release exe as a standard user: $ReleaseExe $($plan[0].Args)"
} else {

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
$found = New-Object System.Collections.Generic.HashSet[string]
foreach ($exe in $binaries) {
    $ErrorActionPreference = "Continue"
    $listed = & $exe --list 2>$null
    $ErrorActionPreference = "Stop"
    $mine = @($listed | Where-Object { $_ -match '^(\S+): test$' } | ForEach-Object { $_ -replace ': test$', '' } |
        Where-Object { $wanted.Contains(($_ -split '::')[-1]) })
    if ($mine.Count -gt 0) {
        $plan += [pscustomobject]@{
            Exe = $exe; Args = "--exact --test-threads=1 $($mine -join ' ')"; Gone = ""; Names = $mine
            ExitCode = "0"; Expect = ""
        }
        foreach ($m in $mine) { [void]$found.Add(($m -split '::')[-1]) }
    }
}
$missing = @($wanted | Where-Object { -not $found.Contains($_) })
if ($missing.Count -gt 0) { throw "not found in any test binary (renamed? update `$Extra): $($missing -join ', ')" }
}

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
    foreach ($p in $plan) { $grant[$p.Exe] = "(RX)" }
    if (-not $ReleaseExe) { $grant[(Join-Path $Desktop "target\debug\mcp-monitor.exe")] = "(RX)" }
    $grant[$work] = "(OI)(CI)(M)"
    foreach ($path in $grant.Keys) {
        & icacls.exe $path /grant "${user}:$($grant[$path])" /Q | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "icacls $path exited $LASTEXITCODE" }
    }
    $listFile = Join-Path $work "binaries.txt"
    $lines = foreach ($p in $plan) { "$($p.Exe)`t$($p.Args)`t$($p.Gone)" }
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
        $entry = $plan[$i]
        $leaf = Split-Path -Leaf $entry.Exe
        $log = Join-Path $work "test-$i.log"
        $text = if (Test-Path -LiteralPath $log) { [System.IO.File]::ReadAllText($log) } else { "" }
        Write-Host "----- $leaf -----"
        Write-Host $text
        $codeFile = Join-Path $work "test-$i.code"
        $exit = if (Test-Path -LiteralPath $codeFile) { (Get-Content -LiteralPath $codeFile).Trim() } else { "none" }
        if ($exit -ne $entry.ExitCode) { $problems += "$leaf exited $exit (wanted $($entry.ExitCode))" }
        foreach ($n in $entry.Names) {
            if ($text -notmatch "(?m)^test $([regex]::Escape($n)) \.\.\. ok\r?$") { $problems += "$n was not reported ok" }
        }
        if ($entry.Expect -and $text -notmatch $entry.Expect) { $problems += "$leaf did not print the expected line" }
        $leftFile = Join-Path $work "test-$i.left"
        if ($entry.Gone) {
            if (-not (Test-Path -LiteralPath $leftFile)) { $problems += "$leaf`: no record of the folders it left" }
            else {
                foreach ($l in [System.IO.File]::ReadAllLines($leftFile)) { if ($l) { $problems += "$leaf left $l behind" } }
            }
        }
        foreach ($l in ($text -split "`r?`n" | Where-Object { $_ -match 'SKIPPED' })) { $problems += "skipped: $l" }
    }
    if ($problems.Count -gt 0) {
        $problems | ForEach-Object { Write-Host "::error::standard-user tests: $_" }
        throw "standard-user tests failed ($($problems.Count) problem(s))"
    }
    Write-Host "standard-user tests: $(@($wanted).Count) checks in $($plan.Count) runs passed as $user (Medium Mandatory Level, not an administrator)"
} finally {
    try { $computer.Delete("User", $user); Write-Host "deleted local account $user" } catch { Write-Host "::warning::could not delete $user`: $_" }
}
