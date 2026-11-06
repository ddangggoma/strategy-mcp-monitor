<#
.SYNOPSIS
  MCP Monitor 제거 (Plan 5 Task 14): 서비스 정지·삭제, 방화벽 규칙 삭제, 설치 폴더 삭제.

.DESCRIPTION
  기본으로 데이터(로그·설정·스크립트)를 남깁니다(W31). -RemoveData일 때만 데이터 루트 전체(로그,
  config.db, scripts, data\collector-state.json, data\tamper-baseline.json, 감사 정책 백업 포함)와 사용자별
  고지 창 Edge 프로필(%LOCALAPPDATA%\mcp-monitor)을 지웁니다. -RestoreAuditPolicy일 때만 설치 전 감사 정책
  (auditpol 백업)과 레지스트리 값(install-state.json의 registry_before)을 되돌립니다.

  install.ps1과 같은 구조입니다: 계획을 만들고, -DryRun이면 JSON으로 출력하고 끝(관리자 불필요, 아무것도
  바꾸지 않음), 아니면 실행합니다. 첫 단계는 관리자 확인입니다(W29).

  종료 코드: 0 성공, 1 실패(관리자 아님 포함), 2 인자 오류.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File uninstall.ps1 -DryRun
#>
[CmdletBinding()]
param(
    [string]$InstallDir = "$env:ProgramFiles\MCP Monitor",
    [string]$DataRoot = "$env:ProgramData\MCP Monitor",
    [switch]$RemoveData,
    [switch]$RestoreAuditPolicy,
    [switch]$DryRun
)

# The console code page (949 on Korean Windows) would mangle Korean text in redirected output (F13).
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false } catch { }
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$ServiceName = "mcp-monitor"
$AdminMessage = "관리자 권한(Administrator)으로 PowerShell을 열고 다시 실행하세요."

# --- common helpers (the same in install.ps1, uninstall.ps1 and audit-policy.ps1) ---------------
function Stop-WithArgumentError([string]$Message) {
    [Console]::Error.WriteLine("오류: $Message")
    exit 2
}

function Get-FullPath([string]$Path) {
    # A drive that does not exist (Q:) has no PowerShell provider path: .NET still makes it absolute.
    try { $Path = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Path) } catch { }
    $full = [System.IO.Path]::GetFullPath($Path)
    if ($full.Length -gt 3) { $full = $full.TrimEnd('\') }
    return $full
}

function Test-Inside([string]$Child, [string]$Parent) {
    return $Child.StartsWith($Parent.TrimEnd('\') + '\', [System.StringComparison]::OrdinalIgnoreCase)
}

function Get-Prop($Object, [string]$Name) {
    if ($null -eq $Object) { return $null }
    $p = $Object.PSObject.Properties[$Name]
    if ($null -eq $p) { return $null }
    return $p.Value
}

function Read-JsonFile([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    try { return ([System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8) | ConvertFrom-Json) } catch { return $null }
}

function Test-Admin {
    $principal = New-Object Security.Principal.WindowsPrincipal ([Security.Principal.WindowsIdentity]::GetCurrent())
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# --- data root helpers (the same in install.ps1 and audit-policy.ps1; the first two also in uninstall.ps1) ---
# uninstall -RemoveData deletes the data root whole: never a drive root, a system folder or a folder above one.
function Get-UnsafeRootReason([string]$Root) {
    $full = Get-FullPath $Root
    if ($full.TrimEnd('\') -eq ([System.IO.Path]::GetPathRoot($full)).TrimEnd('\')) { return "$full 은(는) 드라이브 루트입니다" }
    $system = @($env:SystemRoot, $env:ProgramData, $env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:ProgramW6432,
        (Split-Path -Parent $env:PUBLIC), $env:PUBLIC, $env:USERPROFILE, $env:LOCALAPPDATA, $env:APPDATA) | Where-Object { $_ }
    foreach ($s in $system) {
        $s = Get-FullPath $s
        if ($full -eq $s -or (Test-Inside $s $full)) { return "$full 은(는) 시스템 폴더($s)이거나 그 위 폴더입니다" }
    }
    if (Test-Inside $full (Get-FullPath $env:SystemRoot)) { return "$full 은(는) Windows 폴더 안입니다" }
    return $null
}

# A data root this product made: install.ps1 / audit-policy.ps1 write the marker (an install before the
# marker existed has install-state.json).
function Test-DataRootMarker([string]$Root) {
    return (Test-Path -LiteralPath (Join-Path $Root "data\mcp-monitor-data-root.json") -PathType Leaf) -or
        (Test-Path -LiteralPath (Join-Path $Root "data\install-state.json") -PathType Leaf)
}

$Steps = New-Object System.Collections.Generic.List[object]
function Add-Step([string]$Id, [string]$Cmd, [object[]]$Arguments = @(), [int[]]$Ok = @(0), $When = $null) {
    $Steps.Add([ordered]@{ id = $Id; cmd = $Cmd; args = @($Arguments | ForEach-Object { [string]$_ }); ok = $Ok; when = $When })
}

# One argument for CreateProcess, quoted by the MSVCRT rules (embedded quotes and the backslashes before them).
function ConvertTo-CommandLineArg([string]$Arg) {
    if ($Arg.Length -gt 0 -and $Arg -notmatch '[\s"]') { return $Arg }
    $sb = New-Object System.Text.StringBuilder
    [void]$sb.Append('"')
    $slashes = 0
    foreach ($ch in $Arg.ToCharArray()) {
        if ($ch -eq [char]'\') { $slashes++; continue }
        if ($ch -eq [char]'"') { [void]$sb.Append([char]'\', 2 * $slashes + 1) }
        elseif ($slashes -gt 0) { [void]$sb.Append([char]'\', $slashes) }
        [void]$sb.Append($ch)
        $slashes = 0
    }
    [void]$sb.Append([char]'\', 2 * $slashes)
    [void]$sb.Append('"')
    return $sb.ToString()
}

# Runs a Windows tool from System32 (never from the current folder or PATH) and returns its exit code.
function Invoke-Native([string]$Cmd, [string[]]$Arguments) {
    $exe = Join-Path ([Environment]::SystemDirectory) $Cmd
    if (-not $exe.EndsWith(".exe", [System.StringComparison]::OrdinalIgnoreCase)) { $exe += ".exe" }
    $psi = New-Object System.Diagnostics.ProcessStartInfo $exe
    $psi.Arguments = (@($Arguments | ForEach-Object { ConvertTo-CommandLineArg $_ }) -join " ")
    $psi.UseShellExecute = $false
    $proc = [System.Diagnostics.Process]::Start($psi)
    $proc.WaitForExit()
    return $proc.ExitCode
}

function Wait-ServiceStopped([int]$Seconds) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ($true) {
        $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
        if ($null -eq $svc -or $svc.Status -eq "Stopped") { return }
        if ((Get-Date) -ge $deadline) { throw "서비스 $ServiceName 이(가) $Seconds 초 안에 멈추지 않았습니다" }
        Start-Sleep -Seconds 1
    }
}

# "<key>\<value name>=<previous DWORD or null>" (install-state.json registry_before): put back or delete.
# Only the two values install.ps1 sets, and only DWORDs: the state file must not choose what is written.
function Restore-RegistryValues([string[]]$Entries) {
    if ($Entries.Count -eq 0) { Write-Host "  되돌릴 레지스트리 값이 없습니다(install-state.json 없음)." }
    $known = @("HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System\Audit\ProcessCreationIncludeCmdLine_Enabled",
        "HKLM\SOFTWARE\Policies\Microsoft\Windows\PowerShell\ScriptBlockLogging\EnableScriptBlockLogging")
    foreach ($entry in $Entries) {
        $at = $entry.LastIndexOf("=")
        $full = $entry.Substring(0, $at)
        $value = $entry.Substring($at + 1)
        if ($known -notcontains $full -or ($value -ne "null" -and $value -notmatch '^\d{1,10}$')) { throw "알 수 없는 레지스트리 값 $entry" }
        $key = Split-Path -Parent $full
        $name = Split-Path -Leaf $full
        if ($value -eq "null") { $code = Invoke-Native "reg" @("delete", $key, "/v", $name, "/f"); $ok = @(0, 1) }
        else { $code = Invoke-Native "reg" @("add", $key, "/v", $name, "/t", "REG_DWORD", "/d", $value, "/f"); $ok = @(0) }
        if ($ok -notcontains $code) { throw "reg ($full) 종료 코드 $code" }
    }
}

$Internal = @{
    "(admin)"       = { param($s) if (-not (Test-Admin)) { Write-Host $AdminMessage; exit 1 }; 0 }
    "(reg-restore)" = { param($s) Restore-RegistryValues @($s.args); 0 }
    "(remove)"      = {
        param($s)
        foreach ($path in $s.args) {
            if ($path.Contains("*")) {
                Get-Item -Path $path -Force -ErrorAction SilentlyContinue | ForEach-Object { Remove-Item -LiteralPath $_.FullName -Recurse -Force }
            } elseif (Test-Path -LiteralPath $path) {
                Remove-Item -LiteralPath $path -Recurse -Force
            }
        }
        0
    }
}

$Conditions = @{
    audit_backup_exists   = { Test-Path -LiteralPath $AuditBackup -PathType Leaf }
    # Guards against deleting the wrong folder: an install has bundle.json, a data root our marker
    # (or install-state.json); neither is ever a drive root or a system folder (finding I3).
    install_dir_is_bundle = { (Test-Path -LiteralPath (Join-Path $InstallDir "bundle.json") -PathType Leaf) -and -not (Get-UnsafeRootReason $InstallDir) }
    data_root_is_ours     = { (Test-DataRootMarker $DataRoot) -and -not (Get-UnsafeRootReason $DataRoot) }
}

$AfterStep = @{
    stop_service = { Wait-ServiceStopped 60 }
}

function Invoke-Plan {
    # A folder that is the current directory cannot be deleted.
    Set-Location -LiteralPath ([Environment]::SystemDirectory)
    [Environment]::CurrentDirectory = [Environment]::SystemDirectory
    $n = $Steps.Count
    $i = 0
    foreach ($s in $Steps) {
        $i++
        if ($s.when -and -not (& $Conditions[$s.when])) {
            Write-Host "[$i/$n] $($s.id): 건너뜀 ($($s.when) 아님)"
            continue
        }
        Write-Host "[$i/$n] $($s.id)"
        try {
            if ($s.cmd.StartsWith("(")) { $code = & $Internal[$s.cmd] $s } else { $code = Invoke-Native $s.cmd $s.args }
            if ($s.ok -notcontains $code) { throw "종료 코드 $code" }
            if ($AfterStep.ContainsKey($s.id)) { & $AfterStep[$s.id] }
        } catch {
            Write-Host "[실패] $($s.id): $($_.Exception.Message)"
            exit 1
        }
    }
}

# --- arguments ----------------------------------------------------------------------------------
$DataRoot = Get-FullPath $DataRoot
if ($RemoveData) {
    $unsafe = Get-UnsafeRootReason $DataRoot
    if ($unsafe) { Stop-WithArgumentError "-DataRoot: $unsafe -RemoveData는 이 폴더를 지우지 않습니다." }
}
$State = Read-JsonFile "$DataRoot\data\install-state.json"
if (-not $PSBoundParameters.ContainsKey("InstallDir") -and (Get-Prop $State "install_dir")) { $InstallDir = Get-Prop $State "install_dir" }
$InstallDir = Get-FullPath $InstallDir
# Removing the install folder would take a data root inside it along (I3): only with -RemoveData.
if (-not $RemoveData -and ($DataRoot -eq $InstallDir -or (Test-Inside $DataRoot $InstallDir))) {
    Stop-WithArgumentError "-DataRoot($DataRoot)가 설치 폴더($InstallDir) 안에 있어 데이터를 남길 수 없습니다(-RemoveData로 함께 지우기)."
}
$ExternalPort = Get-Prop $State "external_port"
if (-not $ExternalPort) { $ExternalPort = 8701 }
$AuditBackup = Get-Prop $State "audit_backup"
if (-not $AuditBackup) { $AuditBackup = "$DataRoot\data\auditpol-backup.csv" }
$RegistryEntries = @()
$before = Get-Prop $State "registry_before"
if ($null -eq $before) { $before = Get-Prop (Read-JsonFile "$DataRoot\data\audit-policy-state.json") "registry_before" }
if ($null -ne $before) {
    $RegistryEntries = @($before.PSObject.Properties | ForEach-Object { "$($_.Name)=$(if ($null -eq $_.Value) { 'null' } else { $_.Value })" })
}
# Every user's notice-window Edge profile (Plan 4 agent: %LOCALAPPDATA%\mcp-monitor).
$EdgeProfiles = Join-Path (Split-Path -Parent $env:PUBLIC) "*\AppData\Local\mcp-monitor"

# --- plan ---------------------------------------------------------------------------------------
Add-Step "require_admin" "(admin)"
Add-Step "stop_service" "sc.exe" @("stop", $ServiceName) -Ok @(0, 1060, 1062)
Add-Step "delete_service" "sc.exe" @("delete", $ServiceName) -Ok @(0, 1060)
Add-Step "firewall_delete" "netsh" @("advfirewall", "firewall", "delete", "rule", "name=MCP Monitor ($ExternalPort)") -Ok @(0, 1)
if ($RestoreAuditPolicy) {
    Add-Step "restore_audit_policy" "auditpol" @("/restore", "/file:$AuditBackup") -When "audit_backup_exists"
    Add-Step "restore_registry" "(reg-restore)" $RegistryEntries
}
Add-Step "remove_install_dir" "(remove)" @($InstallDir) -When "install_dir_is_bundle"
if ($RemoveData) {
    Add-Step "remove_data" "(remove)" @($DataRoot) -When "data_root_is_ours"
    Add-Step "remove_edge_profiles" "(remove)" @($EdgeProfiles)
}

if ($DryRun) {
    $plan = [ordered]@{
        script       = "uninstall"
        version      = Get-Prop $State "version"
        layout       = Get-Prop $State "layout"
        install_dir  = $InstallDir
        data_root    = $DataRoot
        service_mode = $null
        steps        = $Steps.ToArray()
    }
    Write-Output ($plan | ConvertTo-Json -Depth 6 -Compress)
    exit 0
}

Invoke-Plan
if ($RemoveData) { Write-Host "제거 완료(데이터 포함)." }
else { Write-Host "제거 완료. 데이터는 $DataRoot 에 남아 있습니다(지우려면 -RemoveData)." }
exit 0
