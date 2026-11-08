<#
.SYNOPSIS
    TEST/DEMO ONLY: fill the MCP Monitor installed on this PC with demo data.

.DESCRIPTION
    1. Makes sure dummy-mcps\.venv exists (runs `uv sync` there as you, before elevating).
    2. Asks for administrator rights once (UAC) for the service steps.
    3. Stops the mcp-monitor service, runs
         mcp-monitor-server.exe seed-demo --root <DataRoot> --dummy-mcps-dir <repo>\dummy-mcps
       (demo users dev1/dev2/ops@example.com and the three dummy MCPs with start/stop/restart scripts;
       idempotent), and unless -NoDevOtp adds
         --external-host 127.0.0.1 --dev-otp-code <code>
       to the service's binPath so every user logs in with that fixed code.
    4. Starts the service and waits for http://127.0.0.1:<local port>/api/channel.
    -Revert removes the added binPath arguments again and restarts the service (the demo data stays;
    delete it in the web UI). Never use this on a production install.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\seed-demo.ps1
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\seed-demo.ps1 -Revert
#>
[CmdletBinding()]
param(
    [ValidatePattern('^[0-9]{6}$')]
    [string]$DevOtpCode = '123456',
    [switch]$NoDevOtp,
    [switch]$Revert,
    [string]$InstallDir = 'C:\Program Files\MCP Monitor',
    [string]$DataRoot = 'C:\ProgramData\MCP Monitor',
    [string]$LogFile = '',
    # Set by the script itself on the elevated run: it never asks for elevation twice.
    [switch]$Elevated
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0

$ServiceName = 'mcp-monitor'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$DummyDir = Join-Path $RepoRoot 'dummy-mcps'
$ServerExe = Join-Path $InstallDir 'bin\monitor\mcp-monitor-server.exe'
$LogDir = Join-Path $env:LOCALAPPDATA 'mcp-monitor-demo'
if (-not $LogFile) { $LogFile = Join-Path $LogDir ('seed-demo-{0:yyyyMMdd-HHmmss}.log' -f (Get-Date)) }
# What -DevOtpCode appends to the binPath (and -Revert removes): a loopback external channel is
# required by the server for --dev-otp-code (app/__main__.py refuses it on 0.0.0.0).
$DevTailPattern = '\s+--external-host\s+127\.0\.0\.1\s+--dev-otp-code\s+[0-9]{6}\s*$'

function Write-Log([string]$Message) {
    Write-Host $Message
    try {
        $dir = Split-Path -Parent $LogFile
        if (-not (Test-Path -LiteralPath $dir)) { [void](New-Item -ItemType Directory -Force -Path $dir) }
        Add-Content -LiteralPath $LogFile -Value ('{0:HH:mm:ss} {1}' -f (Get-Date), $Message) -Encoding UTF8
    } catch {
        Write-Host "(로그 파일에 쓰지 못했습니다: $($_.Exception.Message))"
    }
}

function Stop-WithError([string]$Message) {
    Write-Log "오류: $Message"
    Write-Log "로그: $LogFile"
    exit 1
}

function Test-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    return (New-Object Security.Principal.WindowsPrincipal $identity).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

# Every function that changes the service or its data starts with this guard.
function Assert-Elevated {
    if (-not (Test-Admin)) { throw 'this step needs administrator rights (run from an elevated PowerShell)' }
}

# Runs a native program; its stdout and stderr lines go to the log. Returns the exit code.
function Invoke-Logged([string]$FilePath, [string[]]$Arguments) {
    $saved = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'  # PS 5.1 turns native stderr lines into errors
    try {
        & $FilePath @Arguments 2>&1 | ForEach-Object { Write-Log "  $_" }
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $saved
    }
}

# ---- pure helpers (dot-source the script to test them) ------------------------------------------

function Get-SeedArguments {
    return @('seed-demo', '--root', $DataRoot, '--dummy-mcps-dir', $DummyDir)
}

# The binPath with the demo arguments: added (-DevOtpCode), removed (-Revert) or left as is (-NoDevOtp).
function Get-DemoBinPath([string]$Current, [string]$Code, [bool]$Remove) {
    $base = $Current -replace $DevTailPattern, ''
    if ($Remove) { return $base }
    return "$base --external-host 127.0.0.1 --dev-otp-code $Code"
}

function Get-LocalPort([string]$BinPath) {
    if ($BinPath -match '--local-port\s+([0-9]+)') { return [int]$Matches[1] }
    return 8700
}

function Get-ElevationArguments {
    $list = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"", '-Elevated',
        '-LogFile', "`"$LogFile`"", '-InstallDir', "`"$InstallDir`"", '-DataRoot', "`"$DataRoot`"",
        '-DevOtpCode', $DevOtpCode)
    if ($NoDevOtp) { $list += '-NoDevOtp' }
    if ($Revert) { $list += '-Revert' }
    return $list
}

# ---- as the invoking user ------------------------------------------------------------------------

function Initialize-DummyVenv {
    $python = Join-Path $DummyDir '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $python -PathType Leaf) { return }
    if (-not (Test-Path -LiteralPath (Join-Path $DummyDir 'pyproject.toml'))) {
        Stop-WithError "dummy-mcps 폴더가 없습니다: $DummyDir"
    }
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($null -eq $uv) {
        Stop-WithError ("dummy-mcps\.venv 가 없고 uv 도 찾지 못했습니다. uv 를 설치한 뒤(https://docs.astral.sh/uv/) " +
            "일반 PowerShell 에서 cd '$DummyDir'; uv sync 를 실행하고 다시 시도하세요.")
    }
    Write-Log "dummy-mcps\.venv 가 없어 uv sync 를 실행합니다(현재 사용자로): $DummyDir"
    Push-Location -LiteralPath $DummyDir
    try { $code = Invoke-Logged $uv.Source @('sync') } finally { Pop-Location }
    if ($code -ne 0 -or -not (Test-Path -LiteralPath $python -PathType Leaf)) {
        Stop-WithError "uv sync 가 실패했습니다(종료 코드 $code). cd '$DummyDir'; uv sync 를 직접 실행해 보세요."
    }
}

# True when $Path is inside the user's profile folder (case-insensitive). The service runs as LocalSystem
# and may not see such a path: a Python installed by uv from inside a packaged (MSIX) app lands in the
# app's private copy of AppData, visible to that app only (seen 2026-11-08: "did not find executable").
function Test-InUserProfile([string]$Path, [string]$UserProfile) {
    if (-not $Path -or -not $UserProfile) { return $false }
    $p = [IO.Path]::GetFullPath($Path).TrimEnd('\') + '\'
    $u = [IO.Path]::GetFullPath($UserProfile).TrimEnd('\') + '\'
    return $p.StartsWith($u, [StringComparison]::OrdinalIgnoreCase)
}

function Get-VenvHome([string]$VenvDir) {
    $cfg = Join-Path $VenvDir 'pyvenv.cfg'
    if (-not (Test-Path -LiteralPath $cfg)) { return $null }
    foreach ($line in Get-Content -LiteralPath $cfg -Encoding UTF8) {
        if ($line -match '^\s*home\s*=\s*(.+?)\s*$') { return $Matches[1] }
    }
    return $null
}

# Rebuilds dummy-mcps\.venv on a copy of its interpreter under dummy-mcps\.python when the interpreter
# lives in the user profile, so the LocalSystem service can run the dummy MCPs.
function Repair-DummyVenvForService {
    $venv = Join-Path $DummyDir '.venv'
    $venvHome = Get-VenvHome $venv
    if (-not $venvHome -or -not (Test-InUserProfile $venvHome $env:USERPROFILE)) { return }
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($null -eq $uv) {
        Stop-WithError ("dummy-mcps\.venv 의 Python($venvHome)이 사용자 프로필 안에 있어 서비스(LocalSystem)가 실행하지 못할 수 있습니다. " +
            "uv 를 PATH 에 두고 다시 실행하세요.")
    }
    $target = Join-Path (Join-Path $DummyDir '.python') (Split-Path -Leaf $venvHome)
    Write-Log "서비스가 볼 수 있도록 Python 을 복사합니다: $venvHome -> $target"
    $null = & robocopy.exe $venvHome $target /E /NFL /NDL /NJH /NJS /NP
    if ($LASTEXITCODE -ge 8) { Stop-WithError "Python 복사가 실패했습니다(robocopy $LASTEXITCODE)." }
    $python = Join-Path $target 'python.exe'
    Push-Location -LiteralPath $DummyDir
    try {
        $code = Invoke-Logged $uv.Source @('venv', '--clear', '--python', $python, '.venv')
        if ($code -eq 0) { $code = Invoke-Logged $uv.Source @('sync', '--python', $python) }
    } finally { Pop-Location }
    if ($code -ne 0) { Stop-WithError "dummy-mcps\.venv 를 다시 만들지 못했습니다(종료 코드 $code)." }
}

function Invoke-SelfElevated {
    Write-Log '서비스를 다루려면 관리자 권한이 필요합니다. UAC 창에서 허용하세요.'
    try {
        $proc = Start-Process -FilePath 'powershell.exe' -ArgumentList (Get-ElevationArguments) -Verb RunAs -Wait -PassThru
    } catch {
        Stop-WithError "관리자 권한을 얻지 못했습니다: $($_.Exception.Message)"
    }
    return $proc.ExitCode
}

# ---- elevated: the service steps -----------------------------------------------------------------

function Get-MonitorService {
    Assert-Elevated
    $svc = Get-CimInstance -ClassName Win32_Service -Filter "Name='$ServiceName'"
    if ($null -eq $svc) { throw "service $ServiceName is not installed" }
    return $svc
}

function Stop-MonitorService {
    Assert-Elevated
    $svc = Get-Service -Name $ServiceName
    if ($svc.Status -eq 'Stopped') { Write-Log '서비스가 이미 멈춰 있습니다.'; return }
    Write-Log '서비스를 멈춥니다(sc.exe stop, 최대 90초).'
    if ($svc.Status -ne 'StopPending') { [void](Invoke-Logged 'sc.exe' @('stop', $ServiceName)) }
    $svc.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(90))
    Write-Log '서비스: STOPPED'
}

function Invoke-SeedDemo {
    Assert-Elevated
    if (-not (Test-Path -LiteralPath $ServerExe -PathType Leaf)) { throw "server not found: $ServerExe" }
    Write-Log "데모 데이터를 넣습니다: `"$ServerExe`" $((Get-SeedArguments) -join ' ')"
    $savedEncoding = [Console]::OutputEncoding
    [Console]::OutputEncoding = [Text.Encoding]::UTF8  # the server prints UTF-8 (Korean summary)
    try { return (Invoke-Logged $ServerExe (Get-SeedArguments)) } finally { [Console]::OutputEncoding = $savedEncoding }
}

function Set-MonitorBinPath([string]$PathName) {
    Assert-Elevated
    $svc = Get-MonitorService
    $result = Invoke-CimMethod -InputObject $svc -MethodName Change -Arguments @{ PathName = $PathName }
    if ($result.ReturnValue -ne 0) { throw "Win32_Service.Change failed ($($result.ReturnValue))" }
    Write-Log "binPath: $PathName"
}

function Start-MonitorService([int]$LocalPort) {
    Assert-Elevated
    Write-Log '서비스를 시작합니다(sc.exe start).'
    [void](Invoke-Logged 'sc.exe' @('start', $ServiceName))
    (Get-Service -Name $ServiceName).WaitForStatus('Running', [TimeSpan]::FromSeconds(60))
    $url = "http://127.0.0.1:$LocalPort/api/channel"
    $deadline = (Get-Date).AddSeconds(90)
    while ((Get-Date) -lt $deadline) {
        try {
            $request = [Net.HttpWebRequest]::Create($url)
            $request.Proxy = $null
            $request.Timeout = 3000
            $response = $request.GetResponse()
            $response.Close()
            Write-Log "응답 확인: $url"
            return
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    throw "the service did not answer $url within 90 s"
}

function Invoke-Elevated {
    Assert-Elevated
    $svc = Get-MonitorService
    $original = [string]$svc.PathName
    $localPort = Get-LocalPort $original
    Write-Log "현재 binPath: $original"
    $stopped = $false
    $seedCode = 0
    try {
        Stop-MonitorService
        $stopped = $true
        if (-not $Revert) {
            $seedCode = Invoke-SeedDemo
            if ($seedCode -eq 4) { throw 'the data root is still in use (another MCP Monitor process holds it)' }
            if ($seedCode -ne 0) { Write-Log "주의: seed-demo 종료 코드 $seedCode (위 실패 줄 참고). 계속합니다." }
        }
        if ($Revert -or -not $NoDevOtp) {
            $wanted = Get-DemoBinPath $original $DevOtpCode ([bool]$Revert)
            if ($wanted -ne $original) {
                $saved = Join-Path $LogDir 'original-binpath.txt'
                if (-not $Revert -and -not (Test-Path -LiteralPath $saved)) {
                    Set-Content -LiteralPath $saved -Value $original -Encoding UTF8
                }
                Set-MonitorBinPath $wanted
            } else {
                Write-Log 'binPath 는 이미 원하는 값입니다.'
            }
        }
    } finally {
        if ($stopped) { Start-MonitorService $localPort }
    }
    Write-Log ''
    if ($Revert) {
        Write-Log '되돌렸습니다: binPath 에서 --external-host 127.0.0.1 --dev-otp-code 를 뺐습니다(데모 데이터는 그대로입니다).'
    } else {
        Write-Log '완료 (테스트 전용 데모 설정).'
        Write-Log '  사용자: dev1@example.com, dev2@example.com (개발자), ops@example.com (운영 관리자, admin)'
        if (-not $NoDevOtp) {
            Write-Log "  로그인 코드: 모든 사용자 $DevOtpCode (외부 채널은 이 PC의 127.0.0.1 에서만 열립니다)"
        }
        Write-Log '  MCP: seoul-weather :9101, calculator :9102, seoul-clock :9103 (서비스 시작 때 자동 시작)'
        Write-Log "  MCP 실행 기록: $DataRoot\data\demo-run"
        Write-Log '되돌리기:'
        Write-Log '  고정 로그인 코드 끄기(원래 binPath): powershell -ExecutionPolicy Bypass -File tools\seed-demo.ps1 -Revert'
        Write-Log '  데모 데이터 지우기: 관리 화면에서 MCP 삭제, 사용자 비활성화(seed-demo 는 지우지 않습니다)'
    }
    Write-Log "로그: $LogFile"
    if ($seedCode -ne 0) { return 1 }
    return 0
}

# ---- main ----------------------------------------------------------------------------------------

function Invoke-Main {
    Write-Log "MCP Monitor seed-demo (테스트 전용) $(if ($Revert) { '-Revert' } else { '' })"
    if (-not (Test-Admin)) {
        if ($Elevated) { Stop-WithError '관리자 권한으로 다시 실행했지만 권한이 없습니다.' }
        if (-not $Revert) { Initialize-DummyVenv; Repair-DummyVenvForService }  # as the invoking user, before elevating
        $printed = 0
        if (Test-Path -LiteralPath $LogFile) { $printed = @(Get-Content -LiteralPath $LogFile -Encoding UTF8).Count }
        $code = Invoke-SelfElevated
        if (Test-Path -LiteralPath $LogFile) {  # what the elevated window showed
            Get-Content -LiteralPath $LogFile -Encoding UTF8 | Select-Object -Skip $printed | ForEach-Object { Write-Host $_ }
        }
        exit $code
    }
    if (-not $Revert) { Initialize-DummyVenv }
    try {
        exit (Invoke-Elevated)
    } catch {
        Stop-WithError $_.Exception.Message
    }
}

if ($MyInvocation.InvocationName -ne '.') { Invoke-Main }
