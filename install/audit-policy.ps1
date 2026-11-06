<#
.SYNOPSIS
  MCP Monitor 감사 정책만 켜거나 되돌립니다(Plan 5 Task 14; Plan 4 실기기 점검표 준비 단계).

.DESCRIPTION
  -Enable: install.ps1의 감사 단계(9-15)와 같습니다. 처음 한 번 현재 감사 정책을 백업하고(auditpol
  /backup), 프로세스 만들기·로그온·로그오프·기타 로그온/로그오프·감사 정책 변경을 하위 범주 GUID로 켜고
  (한국어 Windows에서도 같음, W30), 명령줄 기록·스크립트 블록 기록 레지스트리 값과 로그 크기를 정합니다.
  -Restore <백업 파일>: auditpol /restore로 백업을 되돌리고, install-state.json이 있으면 레지스트리 값도
  설치 전 값으로 되돌립니다.

  install.ps1과 같은 구조입니다: 계획을 만들고, -DryRun이면 JSON으로 출력하고 끝(관리자 불필요, 아무것도
  바꾸지 않음), 아니면 실행합니다. 첫 단계는 관리자 확인입니다(W29).

  종료 코드: 0 성공, 1 실패(관리자 아님 포함), 2 인자 오류.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File audit-policy.ps1 -Enable -DryRun
#>
[CmdletBinding()]
param(
    [switch]$Enable,
    [string]$Restore,
    [string]$DataRoot = "$env:ProgramData\MCP Monitor",
    [switch]$DryRun
)

# The console code page (949 on Korean Windows) would mangle Korean text in redirected output (F13).
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false } catch { }
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$AdminMessage = "관리자 권한(Administrator)으로 PowerShell을 열고 다시 실행하세요."
$AuditKey = "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System\Audit"
$PsLogKey = "HKLM\SOFTWARE\Policies\Microsoft\Windows\PowerShell\ScriptBlockLogging"
# Process Creation, Logon, Logoff, Other Logon/Logoff Events, Audit Policy Change.
$SuccessGuids = "{0CCE922B-69AE-11D9-BED3-505054503030},{0CCE9215-69AE-11D9-BED3-505054503030},{0CCE9216-69AE-11D9-BED3-505054503030},{0CCE921C-69AE-11D9-BED3-505054503030},{0CCE922F-69AE-11D9-BED3-505054503030}"
# Logon, Other Logon/Logoff Events.
$FailureGuids = "{0CCE9215-69AE-11D9-BED3-505054503030},{0CCE921C-69AE-11D9-BED3-505054503030}"

# --- common helpers (the same in install.ps1, uninstall.ps1 and audit-policy.ps1) ---------------
function Stop-WithArgumentError([string]$Message) {
    [Console]::Error.WriteLine("오류: $Message")
    exit 2
}

function Get-FullPath([string]$Path) {
    $full = [System.IO.Path]::GetFullPath($ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Path))
    if ($full.Length -gt 3) { $full = $full.TrimEnd('\') }
    return $full
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

# "<key>\<value name>=<previous DWORD or null>" (install-state.json registry_before): put back or delete.
function Restore-RegistryValues([string[]]$Entries) {
    if ($Entries.Count -eq 0) { Write-Host "  되돌릴 레지스트리 값이 없습니다(install-state.json 없음)." }
    foreach ($entry in $Entries) {
        $at = $entry.LastIndexOf("=")
        $full = $entry.Substring(0, $at)
        $value = $entry.Substring($at + 1)
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
}

$Conditions = @{
    no_backup_yet = { -not (Test-Path -LiteralPath $BackupPath) }
}

function Invoke-Plan {
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
        } catch {
            Write-Host "[실패] $($s.id): $($_.Exception.Message)"
            exit 1
        }
    }
}

# --- arguments ----------------------------------------------------------------------------------
if ($Enable -eq [bool]$Restore) { Stop-WithArgumentError "-Enable 또는 -Restore <백업 파일> 중 하나만 주세요." }
$DataRoot = Get-FullPath $DataRoot
$BackupPath = "$DataRoot\data\auditpol-backup.csv"
if ($Restore) {
    $Restore = Get-FullPath $Restore
    if (-not (Test-Path -LiteralPath $Restore -PathType Leaf)) { Stop-WithArgumentError "백업 파일 $Restore 이(가) 없습니다." }
}
$Bundle = Read-JsonFile (Join-Path (Split-Path -Parent $PSScriptRoot) "bundle.json")

# --- plan ---------------------------------------------------------------------------------------
Add-Step "require_admin" "(admin)"
if ($Enable) {
    # The same steps (and arguments) as install.ps1 steps 9-15.
    Add-Step "audit_backup" "auditpol" @("/backup", "/file:$BackupPath") -When "no_backup_yet"
    Add-Step "audit_policy_success" "auditpol" @("/set", "/subcategory:$SuccessGuids", "/success:enable")
    Add-Step "audit_policy_failure" "auditpol" @("/set", "/subcategory:$FailureGuids", "/failure:enable")
    Add-Step "registry_cmdline" "reg" @("add", $AuditKey, "/v", "ProcessCreationIncludeCmdLine_Enabled", "/t", "REG_DWORD", "/d", "1", "/f")
    Add-Step "registry_scriptblock" "reg" @("add", $PsLogKey, "/v", "EnableScriptBlockLogging", "/t", "REG_DWORD", "/d", "1", "/f")
    Add-Step "security_log_size" "wevtutil" @("sl", "Security", "/ms:268435456")
    Add-Step "powershell_log_size" "wevtutil" @("sl", "Microsoft-Windows-PowerShell/Operational", "/ms:67108864")
} else {
    $RegistryEntries = @()
    $before = Get-Prop (Read-JsonFile "$DataRoot\data\install-state.json") "registry_before"
    if ($null -ne $before) {
        $RegistryEntries = @($before.PSObject.Properties | ForEach-Object { "$($_.Name)=$(if ($null -eq $_.Value) { 'null' } else { $_.Value })" })
    }
    Add-Step "restore_audit_policy" "auditpol" @("/restore", "/file:$Restore")
    Add-Step "restore_registry" "(reg-restore)" $RegistryEntries
}

if ($DryRun) {
    $plan = [ordered]@{
        script       = "audit-policy"
        version      = Get-Prop $Bundle "version"
        layout       = Get-Prop $Bundle "layout"
        install_dir  = $null
        data_root    = $DataRoot
        service_mode = $null
        steps        = $Steps.ToArray()
    }
    Write-Output ($plan | ConvertTo-Json -Depth 6 -Compress)
    exit 0
}

Invoke-Plan
Write-Host $(if ($Enable) { "감사 정책을 켰습니다." } else { "감사 정책을 되돌렸습니다." })
exit 0
