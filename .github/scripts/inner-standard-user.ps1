<#
.SYNOPSIS
  Runs as the throw-away standard user (started by standard-user-tests.ps1, review I1): records the token's
  groups, then runs each test binary with --exact <names> --test-threads=1, writing test-<i>.log (stdout and
  stderr) and test-<i>.code into -OutDir. Windows PowerShell 5.1.
#>
param(
    [Parameter(Mandatory)][string]$ListFile,
    [Parameter(Mandatory)][string]$OutDir
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# This account's own folders (the inherited variables may name the runner user's), and never the CI flags
# that let tests run elevated.
$local = [Environment]::GetFolderPath("LocalApplicationData")
if (-not $local) { throw "this account has no %LOCALAPPDATA% (profile not loaded)" }
$env:LOCALAPPDATA = $local
$env:APPDATA = [Environment]::GetFolderPath("ApplicationData")
$env:USERPROFILE = [Environment]::GetFolderPath("UserProfile")
$env:TEMP = Join-Path $local "Temp"
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
Remove-Item Env:GITHUB_ACTIONS, Env:MCPMON_TESTS_ALLOW_ELEVATED -ErrorAction SilentlyContinue
$env:RUST_BACKTRACE = "1"

$whoami = Join-Path $env:SystemRoot "System32\whoami.exe"
$groups = (& $whoami /user /groups /fo csv /nh | Out-String)
[System.IO.File]::WriteAllText((Join-Path $OutDir "whoami.txt"), $groups)
Write-Output "running as $(& $whoami) with LOCALAPPDATA=$local"

$i = 0
foreach ($line in [System.IO.File]::ReadAllLines($ListFile)) {
    $exe, $names = $line -split "`t", 2
    $psi = New-Object System.Diagnostics.ProcessStartInfo $exe
    $psi.Arguments = "--exact --test-threads=1 $names"
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.WorkingDirectory = $OutDir
    $proc = [System.Diagnostics.Process]::Start($psi)
    $stderr = $proc.StandardError.ReadToEndAsync()
    $stdout = $proc.StandardOutput.ReadToEnd()
    $proc.WaitForExit()
    [System.IO.File]::WriteAllText((Join-Path $OutDir "test-$i.log"), $stdout + "`n--- stderr ---`n" + $stderr.Result)
    [System.IO.File]::WriteAllText((Join-Path $OutDir "test-$i.code"), "$($proc.ExitCode)")
    Write-Output "$(Split-Path -Leaf $exe): exit $($proc.ExitCode)"
    $i++
}
