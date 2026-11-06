<#
.SYNOPSIS
  MCP Monitor 설치 (Plan 5 Task 14): 묶음 복사, 데이터 폴더 ACL, 감사 정책, 서비스 등록·시작.

.DESCRIPTION
  계획(단계 목록)을 먼저 만들고, -DryRun이면 그 계획을 JSON 한 줄로 출력하고 끝납니다(관리자 불필요,
  아무것도 바꾸지 않음). 아니면 같은 계획을 차례로 실행합니다. 첫 단계는 관리자 확인이며, 관리자가
  아니면 어떤 변경도 하기 전에 종료 코드 1로 끝납니다(W29).

  ACL은 이름이 아니라 SID로, 감사 정책은 하위 범주 GUID로 지정합니다(한국어 Windows에서도 같음, W30).
  방화벽 규칙은 -OpenFirewall일 때만 만듭니다(spec 2 #6).

  종료 코드: 0 성공, 1 실패(관리자 아님 포함), 2 인자 오류.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File install\install.ps1 -DryRun
#>
[CmdletBinding()]
param(
    [string]$Source,
    [string]$InstallDir = "$env:ProgramFiles\MCP Monitor",
    [string]$DataRoot = "$env:ProgramData\MCP Monitor",
    [switch]$OpenFirewall,
    [switch]$SkipAuditPolicy,
    [ValidateRange(1, 65535)][int]$LocalPort = 8700,
    [ValidateRange(1, 65535)][int]$ExternalPort = 8701,
    [switch]$DryRun
)

# The console code page (949 on Korean Windows) would mangle Korean text in redirected output (F13).
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false } catch { }
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$ServiceName = "mcp-monitor"
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

function Get-RegistryValue([string]$Key, [string]$Name) {
    $item = Get-ItemProperty -LiteralPath "Registry::$Key" -Name $Name -ErrorAction SilentlyContinue
    if ($null -eq $item) { return $null }
    return $item.$Name
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

$Internal = @{
    "(admin)"       = { param($s) if (-not (Test-Admin)) { Write-Host $AdminMessage; exit 1 }; 0 }
    "(check-os)"    = {
        param($s)
        $os = Get-CimInstance -ClassName Win32_OperatingSystem
        if ($os.Caption -match "Home" -or @(98, 99, 100, 101) -contains [int]$os.OperatingSystemSKU) {
            Write-Host "경고: $($os.Caption)은(는) RDP 호스트가 아니어서 세션 수집이 동작하지 않습니다. 설치는 계속합니다."
        }
        if (-not (Test-Inside $InstallDir $env:ProgramFiles)) {
            Write-Host "경고: $InstallDir 은(는) Program Files 밖입니다. 서비스(SYSTEM)가 이 폴더의 프로그램을 실행하므로 일반 사용자가 쓸 수 없는 폴더여야 합니다."
        }
        0
    }
    "(mkdir)"       = { param($s) foreach ($d in $s.args) { [void][System.IO.Directory]::CreateDirectory($d) }; 0 }
    "(write-state)" = {
        param($s)
        $state = $s.args[1] | ConvertFrom-Json
        $state.installed_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
        [System.IO.File]::WriteAllText($s.args[0], ($state | ConvertTo-Json -Depth 4), (New-Object System.Text.UTF8Encoding $false))
        0
    }
    "(wait)"        = {
        param($s)
        $deadline = (Get-Date).AddSeconds([int]$s.args[1])
        while ($true) {
            try {
                $req = [System.Net.WebRequest]::Create($s.args[0])
                $req.Proxy = $null
                $req.Timeout = 2000
                $resp = $req.GetResponse()
                $status = [int]$resp.StatusCode
                $resp.Close()
                if ($status -eq 200) { return 0 }
            } catch { }
            if ((Get-Date) -ge $deadline) { throw "$($s.args[0]) 이(가) $($s.args[1])초 안에 응답하지 않았습니다" }
            Start-Sleep -Seconds 1
        }
    }
}

$Conditions = @{
    service_exists = { $null -ne (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue) }
    no_backup_yet  = { -not (Test-Path -LiteralPath $BackupPath) }
    # netsh "add rule" adds a duplicate on every reinstall.
    firewall_rule_missing = { $null -eq (Get-NetFirewallRule -DisplayName $FirewallRule -ErrorAction SilentlyContinue) }
}

$AfterStep = @{
    stop_existing = { Wait-ServiceStopped 60 }
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
            if ($AfterStep.ContainsKey($s.id)) { & $AfterStep[$s.id] }
        } catch {
            Write-Host "[실패] $($s.id): $($_.Exception.Message)"
            exit 1
        }
    }
}

# --- arguments ----------------------------------------------------------------------------------
if (-not $Source) { $Source = Split-Path -Parent $PSScriptRoot }
$Source = Get-FullPath $Source
$InstallDir = Get-FullPath $InstallDir
$DataRoot = Get-FullPath $DataRoot

$meta = Read-JsonFile (Join-Path $Source "bundle.json")
if ($null -eq $meta) { Stop-WithArgumentError "$Source 에 bundle.json이 없습니다(-Source는 배포 묶음 폴더)." }
$Layout = Get-Prop $meta "layout"
$Version = Get-Prop $meta "version"
if ($Layout -eq "pyinstaller") { $Program = "`"$InstallDir\bin\monitor\mcp-monitor.exe`" service" }
elseif ($Layout -eq "runtime") { $Program = "`"$InstallDir\runtime\python.exe`" -m app service" }
else { Stop-WithArgumentError "bundle.json의 layout '$Layout'을(를) 알 수 없습니다(pyinstaller 또는 runtime)." }

if ($Source -eq $InstallDir -or (Test-Inside $InstallDir $Source) -or (Test-Inside $Source $InstallDir)) {
    Stop-WithArgumentError "-Source($Source)와 -InstallDir($InstallDir)는 서로 다른, 겹치지 않는 폴더여야 합니다."
}
if (Test-Path -LiteralPath $InstallDir -PathType Leaf) { Stop-WithArgumentError "-InstallDir($InstallDir)이(가) 파일입니다." }
# robocopy /MIR deletes everything else in the folder: only an empty folder or an earlier install.
if ((Test-Path -LiteralPath $InstallDir -PathType Container) -and
    -not (Test-Path -LiteralPath (Join-Path $InstallDir "bundle.json")) -and
    @(Get-ChildItem -LiteralPath $InstallDir -Force).Count -gt 0) {
    Stop-WithArgumentError "-InstallDir($InstallDir)이(가) 비어 있지 않고 MCP Monitor 설치 폴더(bundle.json)도 아닙니다."
}
if ($LocalPort -eq $ExternalPort) { Stop-WithArgumentError "-LocalPort와 -ExternalPort가 같습니다($LocalPort)." }

$ServiceExists = $null -ne (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue)
$BackupPath = "$DataRoot\data\auditpol-backup.csv"
$StatePath = "$DataRoot\data\install-state.json"
$OldState = Read-JsonFile $StatePath

# The values before our first install: a reinstall keeps them (it would otherwise record our own 1s).
$RegistryValues = [ordered]@{ "$AuditKey\ProcessCreationIncludeCmdLine_Enabled" = $null; "$PsLogKey\EnableScriptBlockLogging" = $null }
$RegistryBefore = [ordered]@{}
$oldRegistry = Get-Prop $OldState "registry_before"
if ($null -ne $oldRegistry) { foreach ($p in $oldRegistry.PSObject.Properties) { $RegistryBefore[$p.Name] = $p.Value } }
if (-not $SkipAuditPolicy) {
    foreach ($key in $RegistryValues.Keys) {
        if (-not $RegistryBefore.Contains($key)) {
            $RegistryBefore[$key] = Get-RegistryValue (Split-Path -Parent $key) (Split-Path -Leaf $key)
        }
    }
}
$AuditBackup = Get-Prop $OldState "audit_backup"
if (-not $SkipAuditPolicy -or (Test-Path -LiteralPath $BackupPath)) { $AuditBackup = $BackupPath }

$Description = "MCP 상태 감시와 RDP 접속·행동 감사 (127.0.0.1:$LocalPort / 0.0.0.0:$ExternalPort)"
$BinPath = "$Program --root `"$DataRoot`" --local-port $LocalPort --external-port $ExternalPort"
$FirewallRule = "MCP Monitor ($ExternalPort)"

# --- plan ---------------------------------------------------------------------------------------
Add-Step "require_admin" "(admin)"
Add-Step "check_os" "(check-os)"
Add-Step "stop_existing" "sc.exe" @("stop", $ServiceName) -Ok @(0, 1062) -When "service_exists"
Add-Step "copy_bundle" "robocopy" @($Source, $InstallDir, "/MIR", "/XD", "$InstallDir\logs", "$InstallDir\data", "$InstallDir\scripts",
    "/NFL", "/NDL", "/NJH", "/NJS", "/NP") -Ok @(0..7)
Add-Step "create_dirs" "(mkdir)" @("$DataRoot\logs", "$DataRoot\data", "$DataRoot\scripts")
Add-Step "acl_data" "icacls" @($DataRoot, "/inheritance:r", "/grant:r", "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F")
Add-Step "acl_children" "icacls" @("$DataRoot\*", "/reset", "/T", "/C", "/Q")
Add-Step "acl_owner" "icacls" @($DataRoot, "/setowner", "*S-1-5-32-544", "/T", "/C", "/Q")
if (-not $SkipAuditPolicy) {
    Add-Step "audit_backup" "auditpol" @("/backup", "/file:$BackupPath") -When "no_backup_yet"
    Add-Step "audit_policy_success" "auditpol" @("/set", "/subcategory:$SuccessGuids", "/success:enable")
    Add-Step "audit_policy_failure" "auditpol" @("/set", "/subcategory:$FailureGuids", "/failure:enable")
    Add-Step "registry_cmdline" "reg" @("add", $AuditKey, "/v", "ProcessCreationIncludeCmdLine_Enabled", "/t", "REG_DWORD", "/d", "1", "/f")
    Add-Step "registry_scriptblock" "reg" @("add", $PsLogKey, "/v", "EnableScriptBlockLogging", "/t", "REG_DWORD", "/d", "1", "/f")
    Add-Step "security_log_size" "wevtutil" @("sl", "Security", "/ms:268435456")
    Add-Step "powershell_log_size" "wevtutil" @("sl", "Microsoft-Windows-PowerShell/Operational", "/ms:67108864")
}
# The start type is always delayed-auto here; the service then follows the web setting (W25).
Add-Step "service_install" "sc.exe" @($(if ($ServiceExists) { "config" } else { "create" }), $ServiceName, "binPath=", $BinPath,
    "start=", "delayed-auto", "DisplayName=", "MCP Monitor", "obj=", "LocalSystem")
Add-Step "service_description" "sc.exe" @("description", $ServiceName, $Description)
Add-Step "service_failure" "sc.exe" @("failure", $ServiceName, "reset=", "86400", "actions=", "restart/5000/restart/10000/restart/60000")
Add-Step "service_failureflag" "sc.exe" @("failureflag", $ServiceName, "1")
if ($OpenFirewall) {
    Add-Step "firewall" "netsh" @("advfirewall", "firewall", "add", "rule", "name=$FirewallRule", "dir=in", "action=allow",
        "protocol=TCP", "localport=$ExternalPort", "profile=domain,private") -When "firewall_rule_missing"
}
$State = [ordered]@{
    installed_at    = $null
    version         = $Version
    layout          = $Layout
    install_dir     = $InstallDir
    data_root       = $DataRoot
    local_port      = $LocalPort
    external_port   = $ExternalPort
    firewall        = [bool]$OpenFirewall
    registry_before = $RegistryBefore
    audit_backup    = $AuditBackup
}
Add-Step "install_state" "(write-state)" @($StatePath, ($State | ConvertTo-Json -Depth 4 -Compress))
Add-Step "service_start" "sc.exe" @("start", $ServiceName) -Ok @(0, 1056)
Add-Step "wait_ready" "(wait)" @("http://127.0.0.1:$LocalPort/api/channel", "30")

if ($DryRun) {
    $plan = [ordered]@{
        script       = "install"
        version      = $Version
        layout       = $Layout
        install_dir  = $InstallDir
        data_root    = $DataRoot
        service_mode = $(if ($ServiceExists) { "update" } else { "create" })
        steps        = $Steps.ToArray()
    }
    Write-Output ($plan | ConvertTo-Json -Depth 6 -Compress)
    exit 0
}

Invoke-Plan
Write-Host "설치 완료: http://127.0.0.1:$LocalPort/admin/setup 에서 첫 Admin 계정을 만드세요."
exit 0
