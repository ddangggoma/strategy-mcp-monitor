<#
.SYNOPSIS
  Build the MCP Monitor payload: the folder mcp-monitor.exe embeds (Plan 6 Task 2).

.DESCRIPTION
  Security gates (pip-audit, pnpm audit), the web build, then the payload folder:
    bundle.json   {layout: "pyinstaller", version, python, built_at, commit, agent: "desktop"}
    bin\monitor\  mcp-monitor-server.exe (PyInstaller onedir; the server and the Windows service host)
    web\          the built web app
    docs\         OPERATIONS.md
  The session agent and the installer are mcp-monitor.exe itself (desktop\, install\build-desktop.ps1),
  which embeds this folder; there is no zip and no install script here.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File install\build.ps1
#>
[CmdletBinding()]
param(
    [string]$Out,
    [switch]$SkipAudit
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Repo = Split-Path -Parent $PSScriptRoot
$Server = Join-Path $Repo "server"
$Web = Join-Path $Repo "web"

function Write-Step([string]$Message) { Write-Host "==> $Message" }
function Write-Warn([string]$Message) { Write-Host "WARNING: $Message" }

# Runs a native command; a non-zero exit code throws. Native stderr (uv/pnpm progress) is not an
# error by itself, so the preference is relaxed for the call only.
function Invoke-Native([string]$What, [scriptblock]$Command) {
    $ErrorActionPreference = "Continue"
    & $Command
    $code = $LASTEXITCODE
    if ($code -ne 0) { throw "$What failed (exit code $code)" }
}

# Like Invoke-Native, but returns stdout (trimmed) for a short query.
function Get-NativeOutput([string]$What, [scriptblock]$Command) {
    $ErrorActionPreference = "Continue"
    $text = & $Command
    $code = $LASTEXITCODE
    if ($code -ne 0) { throw "$What failed (exit code $code)" }
    return (($text | Out-String).Trim())
}

function Find-Uv {
    if ($env:UV_EXE -and (Test-Path -LiteralPath $env:UV_EXE)) { return $env:UV_EXE }
    $cmd = Get-Command uv -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $winget = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
    $found = Get-ChildItem -Path $winget -Filter "uv.exe" -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.DirectoryName -like "*astral-sh.uv_*" } | Select-Object -First 1
    if ($found) { return $found.FullName }
    throw "uv was not found: put it on PATH or set UV_EXE"
}

function Write-Utf8NoBom([string]$Path, [string]$Text) {
    [System.IO.File]::WriteAllText($Path, $Text, (New-Object System.Text.UTF8Encoding $false))
}

# --- parameters ---------------------------------------------------------------------------------
$initPy = Get-Content -LiteralPath (Join-Path $Server "app\__init__.py") -Raw
if ($initPy -notmatch '__version__\s*=\s*"([^"]+)"') { throw "no __version__ in server\app\__init__.py" }
$Version = $Matches[1]

$ops = Join-Path $Repo "docs\ops\OPERATIONS.md"
if (-not (Test-Path -LiteralPath $ops -PathType Leaf)) { throw "docs\ops\OPERATIONS.md is missing; the payload needs it" }

if (-not $Out) { $Out = Join-Path $Repo "dist\payload" }
$Out = [System.IO.Path]::GetFullPath($(if ([System.IO.Path]::IsPathRooted($Out)) { $Out } else { Join-Path (Get-Location).Path $Out }))
# $Out is deleted and rebuilt: only an empty folder, an earlier payload (bundle.json) or an
# unfinished build (.partial, removed once bundle.json is written) may be replaced.
$Partial = Join-Path $Out ".partial"
if ((Test-Path -LiteralPath $Out) -and -not (Test-Path -LiteralPath (Join-Path $Out "bundle.json")) -and
    -not (Test-Path -LiteralPath $Partial) -and @(Get-ChildItem -LiteralPath $Out -Force).Count -gt 0) {
    throw "-Out $Out exists and is not an earlier payload (no bundle.json); refusing to delete it"
}

$Uv = Find-Uv
Write-Step "MCP Monitor $Version payload -> $Out"

# --- 1. security gates (spec 9.1) ---------------------------------------------------------------
if ($SkipAudit) {
    Write-Warn "-SkipAudit: pip-audit and pnpm audit were not run"
} else {
    Write-Step "pip-audit (server)"
    Push-Location $Server
    try { Invoke-Native "pip-audit" { & $Uv run python -m pip_audit } } finally { Pop-Location }
    Write-Step "pnpm audit (web)"
    Push-Location $Web
    try {
        $audit = Get-NativeOutput "pnpm audit" { & pnpm audit }
        Write-Host $audit
        if ($audit -notmatch "No known vulnerabilities found") { throw "pnpm audit did not report 'No known vulnerabilities found'" }
    } finally { Pop-Location }
}

# --- 2. pyyaml cp3XX wheel re-check (W27): a warning only --------------------------------------
Push-Location $Server
try {
    $Python = Get-NativeOutput "python version" { & $Uv run --group build python -c "import platform; print(platform.python_version())" }
} finally { Pop-Location }
if ($Python -notmatch '^(\d+)\.(\d+)\.\d+$') { throw "unexpected Python version '$Python'" }
$Tag = "cp$($Matches[1])$($Matches[2])"
try {
    $pyyaml = Invoke-RestMethod -Uri "https://pypi.org/pypi/pyyaml/json" -UseBasicParsing -TimeoutSec 30
    if (@($pyyaml.urls | Where-Object { $_.filename -like "*-$Tag-*win_amd64.whl" }).Count -gt 0) {
        Write-Warn "pyyaml now has a $Tag wheel: consider uvicorn[standard]"
    }
} catch {
    Write-Warn "could not check PyPI for a pyyaml $Tag wheel: $($_.Exception.Message)"
}

# --- 3. web ------------------------------------------------------------------------------------
Write-Step "pnpm build (web)"
Push-Location $Web
try { Invoke-Native "pnpm build" { & pnpm build } } finally { Pop-Location }

# --- 4. payload folder: web app and operations guide --------------------------------------------
Write-Step "payload folder"
if (Test-Path -LiteralPath $Out) { Remove-Item -LiteralPath $Out -Recurse -Force }
New-Item -ItemType Directory -Path $Out | Out-Null
New-Item -ItemType File -Path $Partial | Out-Null
Copy-Item -LiteralPath (Join-Path $Web "dist") -Destination (Join-Path $Out "web") -Recurse
$vite = Join-Path $Out "web\.vite"
if (Test-Path -LiteralPath $vite) { Remove-Item -LiteralPath $vite -Recurse -Force }
New-Item -ItemType Directory -Path (Join-Path $Out "docs") | Out-Null
Copy-Item -LiteralPath $ops -Destination (Join-Path $Out "docs")

# --- 5. the server: PyInstaller onedir (bin\monitor\mcp-monitor-server.exe) ---------------------
$bin = Join-Path $Out "bin"
$work = Join-Path $Repo "build\pyinstaller"
Write-Step "PyInstaller mcp-monitor.spec"
$specPath = Join-Path $PSScriptRoot "pyinstaller\mcp-monitor.spec"
Push-Location $Server
try {
    Invoke-Native "PyInstaller mcp-monitor.spec" {
        & $Uv run --group build python -m PyInstaller $specPath --distpath $bin --workpath $work --noconfirm
    }
} finally { Pop-Location }
$serverExe = Join-Path $bin "monitor\mcp-monitor-server.exe"
if (-not (Test-Path -LiteralPath $serverExe -PathType Leaf)) { throw "PyInstaller did not produce $serverExe" }

# --- 6. bundle.json (the server reads "agent": "desktop" and runs mcp-monitor.exe agent) ---------
$commit = Get-NativeOutput "git rev-parse" { & git -C $Repo rev-parse HEAD }
$meta = [ordered]@{
    layout   = "pyinstaller"
    version  = $Version
    python   = $Python
    built_at = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
    commit   = $commit
    agent    = "desktop"
}
Write-Utf8NoBom (Join-Path $Out "bundle.json") (($meta | ConvertTo-Json) + "`n")
Remove-Item -LiteralPath $Partial -Force
Write-Step "done: $Out"
