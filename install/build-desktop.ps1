<#
.SYNOPSIS
  Build the release mcp-monitor.exe (Plan 6 Task 13): payload (build.ps1) -> optional signing -> cargo audit ->
  cargo build --release with the payload embedded -> checks -> dist\mcp-monitor-<version>.exe + .sha256.

.DESCRIPTION
  1. install\build.ps1 -Out <Payload> (unless -SkipPayload). A development payload (the fixture under
     desktop\tests\fixtures, bundle.json built_at/commit "fixture") is refused: it has the release layout,
     so only its bundle.json tells it apart.
  2. -SignThumbprint (needs -TimestampUrl): signs bin\monitor\mcp-monitor-server.exe before it is embedded.
     Without it nothing is signed (D5: no certificate).
  3. cargo audit (-SkipAudit: a warning only).
  4. MCPMON_PAYLOAD_DIR=<Payload> cargo build --release --locked, with no features (dev stays off, Y24).
  0. A RUSTFLAGS, CARGO_ENCODED_RUSTFLAGS, CARGO_BUILD_RUSTFLAGS or CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_RUSTFLAGS
     variable is refused: it would replace desktop\.cargo\config.toml's rustflags.
  5. Checks: --version is "mcp-monitor <version> (payload <12 hex>, release)", DependentLoadFlags is exactly 0x800
     (dumpbin /loadconfig, read as a number), no VC++ Redistributable DLL import (dumpbin /dependents:
     +crt-static; the Universal CRT api-ms-win-crt-*.dll / ucrtbase.dll is part of Windows 10/11 and only listed),
     verify-payload extracts into a scratch folder under %LOCALAPPDATA% and the
     embedded server answers --version (the scratch folder is removed).
  6. -SignThumbprint: signs mcp-monitor.exe; otherwise "NOTE: not signed".
  7. <Out>\mcp-monitor-<version>.exe and .sha256 ("<hash>  <name>`n", no BOM).

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File install\build-desktop.ps1
#>
[CmdletBinding()]
param(
    [switch]$SkipAudit,
    [switch]$SkipPayload,
    [string]$SignThumbprint,
    [string]$TimestampUrl,
    [string]$Out,
    # The payload folder (default <repo>\dist\payload): built there by build.ps1, or used as is with -SkipPayload.
    [string]$Payload
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
$Desktop = Join-Path $Repo "desktop"
if (-not $Payload) { $Payload = Join-Path $Repo "dist\payload" }
$Payload = [System.IO.Path]::GetFullPath($(if ([System.IO.Path]::IsPathRooted($Payload)) { $Payload } else { Join-Path (Get-Location).Path $Payload }))
if (-not $Out) { $Out = Join-Path $Repo "dist" }
if ($SignThumbprint -and -not $TimestampUrl) { throw "-SignThumbprint needs -TimestampUrl" }
# Review item 10: any of these replaces the rustflags of desktop\.cargo\config.toml (+crt-static and
# /DEPENDENTLOADFLAG:0x800, Y2/Y5) without a word, so a release build refuses them.
foreach ($name in @("RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "CARGO_BUILD_RUSTFLAGS", "CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_RUSTFLAGS")) {
    if ([Environment]::GetEnvironmentVariable($name)) {
        throw "$name is set: it would replace the rustflags of desktop\.cargo\config.toml (+crt-static, /DEPENDENTLOADFLAG:0x800). Unset it and run again."
    }
}

function Write-Step([string]$Message) { Write-Host "==> $Message" }

# The DependentLoadFlags value of `dumpbin /loadconfig` output (a hex number before "Dependent Load Flag"), or
# $null when there is none. Read as a number: 0x1800 or 0xA800 are not 0x800 (review item 10).
function Get-DependentLoadFlag([string]$LoadConfig) {
    $m = [regex]::Match($LoadConfig, '(?m)^\s*([0-9A-Fa-f]+)\s+Dependent Load Flag\s*$')
    if (-not $m.Success) { return $null }
    return [Convert]::ToInt32($m.Groups[1].Value, 16)
}

# The VC++ Redistributable DLLs in `dumpbin /dependents` output (vcruntime*, msvcp*, concrt*, vccorlib*, and the
# debug UCRT ucrtbased.dll, which no user PC has): none in a +crt-static build, so no redistributable is needed.
function Get-VcRedistImports([string]$Dependents) {
    return @([regex]::Matches($Dependents, '(?im)^\s*((?:vcruntime|msvcp|concrt|vccorlib)[0-9_a-z]*\.dll|ucrtbased\.dll)\s*$') |
        ForEach-Object { $_.Groups[1].Value })
}

# The Universal CRT imports (api-ms-win-crt-*.dll, ucrtbase.dll): part of Windows 10/11, so allowed and only listed
# (controller ruling after CI run 42395693338: a /MD prebuilt lib may pull them in even with +crt-static).
function Get-UcrtImports([string]$Dependents) {
    return @([regex]::Matches($Dependents, '(?im)^\s*(ucrtbase\.dll|api-ms-win-crt-[0-9a-z-]+\.dll)\s*$') |
        ForEach-Object { $_.Groups[1].Value })
}

# Runs a native command; a non-zero exit code throws. Native stderr (cargo progress) is not an error by
# itself, so the preference is relaxed for the call only.
function Invoke-Native([string]$What, [scriptblock]$Command) {
    $ErrorActionPreference = "Continue"
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit code $LASTEXITCODE)" }
}

# Runs an exe and returns its stdout (trimmed); a non-zero exit code throws. The exe is called right here, in
# the middle of a pipeline: mcp-monitor.exe is a GUI-subsystem exe, and PowerShell waits for one and reads its
# output only when it is not the last command of its own pipeline (inside a scriptblock it would be).
function Get-NativeOutput([string]$What, [string]$File, [string[]]$Arguments) {
    $ErrorActionPreference = "Continue"
    $global:LASTEXITCODE = 0
    $text = (& $File @Arguments | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit code $LASTEXITCODE): $text" }
    return $text
}

function Find-VsTool([string]$Name) {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
    $vs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    $tool = Get-ChildItem -Path (Join-Path $vs "VC\Tools\MSVC\*\bin\Hostx64\x64\$Name") -ErrorAction SilentlyContinue |
        Sort-Object FullName | Select-Object -Last 1
    if (-not $tool) { throw "$Name was not found under $vs" }
    return $tool.FullName
}

function Invoke-Sign([string]$File) {
    $signtool = Get-ChildItem -Path "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName | Select-Object -Last 1
    if (-not $signtool) { throw "signtool.exe was not found (Windows SDK)" }
    Invoke-Native "signtool sign" { & $signtool.FullName sign /sha1 $SignThumbprint /fd SHA256 /tr $TimestampUrl /td SHA256 $File }
    Invoke-Native "signtool verify" { & $signtool.FullName verify /pa $File }
}

# A string property of bundle.json, or "" when it is missing (StrictMode refuses a missing property).
function Get-BundleValue($Meta, [string]$Name) {
    $p = $Meta.PSObject.Properties[$Name]
    if ($p -and $p.Value -is [string]) { return $p.Value }
    return ""
}

# Ruling F05: rustup's folder is not on PATH in every shell.
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    $env:PATH = (Join-Path $env:USERPROFILE ".cargo\bin") + ";" + $env:PATH
}

$cargoToml = Get-Content -LiteralPath (Join-Path $Desktop "Cargo.toml") -Raw
if ($cargoToml -notmatch '(?m)^version\s*=\s*"([^"]+)"') { throw "no version in desktop\Cargo.toml" }
$Version = $Matches[1]

if (-not $SkipPayload) {
    Write-Step "payload (install\build.ps1)"
    $buildArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $PSScriptRoot "build.ps1"), "-Out", $Payload)
    if ($SkipAudit) { $buildArgs += "-SkipAudit" }
    Invoke-Native "build.ps1" { & powershell.exe @buildArgs }
}
$bundleJson = Join-Path $Payload "bundle.json"
if (-not (Test-Path -LiteralPath $bundleJson -PathType Leaf)) { throw "$Payload has no bundle.json: run without -SkipPayload" }
$meta = Get-Content -LiteralPath $bundleJson -Raw -Encoding UTF8 | ConvertFrom-Json
if ((Get-BundleValue $meta "built_at") -eq "fixture" -or (Get-BundleValue $meta "commit") -notmatch '^[0-9a-f]{40}$') {
    throw "$Payload is a development (fixture) payload (bundle.json built_at '$(Get-BundleValue $meta "built_at")', commit '$(Get-BundleValue $meta "commit")'): build it with install\build.ps1"
}
if ($SignThumbprint) { Write-Step "sign the embedded server"; Invoke-Sign (Join-Path $Payload "bin\monitor\mcp-monitor-server.exe") }

Push-Location $Desktop
try {
    if ($SkipAudit) { Write-Host "WARNING: -SkipAudit: cargo audit was not run" }
    else { Write-Step "cargo audit"; Invoke-Native "cargo audit" { & cargo audit } }
    Write-Step "cargo build --release --locked (payload embedded, no features)"
    $env:MCPMON_PAYLOAD_DIR = $Payload
    try { Invoke-Native "cargo build" { & cargo build --release --locked } }
    finally { Remove-Item Env:MCPMON_PAYLOAD_DIR -ErrorAction SilentlyContinue }
} finally { Pop-Location }
$Exe = Join-Path $Desktop "target\release\mcp-monitor.exe"

Write-Step "checks"
$line = Get-NativeOutput "mcp-monitor --version" $Exe @("--version")
if ($line -notmatch "^mcp-monitor $([regex]::Escape($Version)) \(payload [0-9a-f]{12}, release\)$") { throw "unexpected --version: $line" }
$dumpbin = Find-VsTool "dumpbin.exe"
$loadConfig = Get-NativeOutput "dumpbin /loadconfig" $dumpbin @("/loadconfig", $Exe)
$flag = Get-DependentLoadFlag $loadConfig
if ($flag -ne 0x800) { throw "DependentLoadFlags is $(if ($null -eq $flag) { 'missing' } else { '0x{0:X}' -f $flag }), not 0x800 (System32 only)" }
$dependents = Get-NativeOutput "dumpbin /dependents" $dumpbin @("/dependents", $Exe)
$redist = @(Get-VcRedistImports $dependents)
if ($redist.Count -gt 0) { throw "the exe imports the VC++ Redistributable ($($redist -join ', ')): it must be built with +crt-static" }
$ucrt = @(Get-UcrtImports $dependents)
if ($ucrt.Count -gt 0) { Write-Host "  Universal CRT imports (part of Windows 10/11, allowed): $($ucrt -join ', ')" }
$checkRoot = Join-Path $env:LOCALAPPDATA "mcp-monitor-build"
$check = Join-Path $checkRoot ([guid]::NewGuid().ToString("N").Substring(0, 12))
try {
    $verify = Get-NativeOutput "mcp-monitor verify-payload" $Exe @("verify-payload", $check)
    if ($verify -notmatch "^payload OK: ") { throw "verify-payload: $verify" }
    $server = Get-NativeOutput "mcp-monitor-server --version" (Join-Path $check "payload\bin\monitor\mcp-monitor-server.exe") @("--version")
    if ($server -ne "mcp-monitor $Version") { throw "embedded server --version: $server" }
} finally {
    Remove-Item -LiteralPath $check -Recurse -Force -ErrorAction SilentlyContinue
    if ((Test-Path -LiteralPath $checkRoot) -and @(Get-ChildItem -LiteralPath $checkRoot -Force).Count -eq 0) {
        Remove-Item -LiteralPath $checkRoot -Force -ErrorAction SilentlyContinue
    }
}

if ($SignThumbprint) { Write-Step "sign mcp-monitor.exe"; Invoke-Sign $Exe }
else { Write-Host "NOTE: not signed (no -SignThumbprint; D5)" }

New-Item -ItemType Directory -Force -Path $Out | Out-Null
$target = Join-Path $Out "mcp-monitor-$Version.exe"
Copy-Item -LiteralPath $Exe -Destination $target -Force
$hash = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
[System.IO.File]::WriteAllText("$target.sha256", "$hash  mcp-monitor-$Version.exe`n", (New-Object System.Text.UTF8Encoding $false))
Write-Step "done: $target (sha256 $hash)"
