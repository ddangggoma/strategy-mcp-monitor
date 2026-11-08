<#
.SYNOPSIS
  Runs as the throw-away standard user (started by standard-user-tests.ps1, review I1): records the token's
  groups, then runs each line of -ListFile (`<exe> TAB <arguments> TAB <paths that must not exist, |-separated>`;
  the test binaries get --exact --test-threads=1 <names>), writing test-<i>.log (stdout and stderr, UTF-8),
  test-<i>.code and test-<i>.left (the paths that exist afterwards) into -OutDir. %VARIABLES% in the
  arguments and paths are expanded as this account; %MCPMON_STD_SCRATCH% is an empty folder in its own
  %LOCALAPPDATA%. Windows PowerShell 5.1.
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

# A scratch folder only this account (and SYSTEM, Administrators) may change: the installer refuses a data
# root below a folder others may rename (the server tests use %LOCALAPPDATA% for the same reason).
$scratch = Join-Path $local "mcpmon-std-scratch"
if (Test-Path -LiteralPath $scratch) { Remove-Item -LiteralPath $scratch -Recurse -Force }
New-Item -ItemType Directory -Path $scratch | Out-Null
$env:MCPMON_STD_SCRATCH = $scratch

$utf8 = New-Object System.Text.UTF8Encoding $false
$i = 0
foreach ($line in [System.IO.File]::ReadAllLines($ListFile)) {
    $exe, $arguments, $gone = $line -split "`t", 3
    $psi = New-Object System.Diagnostics.ProcessStartInfo $exe
    $psi.Arguments = [Environment]::ExpandEnvironmentVariables($arguments)
    $psi.UseShellExecute = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.StandardOutputEncoding = $utf8
    $psi.StandardErrorEncoding = $utf8
    $psi.WorkingDirectory = $OutDir
    $proc = [System.Diagnostics.Process]::Start($psi)
    $stderr = $proc.StandardError.ReadToEndAsync()
    $stdout = $proc.StandardOutput.ReadToEnd()
    $proc.WaitForExit()
    [System.IO.File]::WriteAllText((Join-Path $OutDir "test-$i.log"), $stdout + "`n--- stderr ---`n" + $stderr.Result, $utf8)
    [System.IO.File]::WriteAllText((Join-Path $OutDir "test-$i.code"), "$($proc.ExitCode)")
    $left = @()
    if ($gone) {
        foreach ($path in ($gone -split '\|')) {
            $path = [Environment]::ExpandEnvironmentVariables($path)
            if (Test-Path -LiteralPath $path) { $left += $path }
        }
    }
    [System.IO.File]::WriteAllLines((Join-Path $OutDir "test-$i.left"), [string[]]$left)
    Write-Output "$(Split-Path -Leaf $exe): exit $($proc.ExitCode)"
    $i++
}
Remove-Item -LiteralPath $scratch -Recurse -Force -ErrorAction SilentlyContinue
