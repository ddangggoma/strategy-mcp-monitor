# stop.ps1 - stop a dummy MCP: kill this MCP's own python process(es): the pid-file pid and the listener on MCP_PORT, each only if its command line has -m <module> or this MCP's --pid-file.
# Exit 0 once the port is free (also when it was already stopped); 1 if it is still listening after 10 s (e.g. a foreign process owns the port, which is left alone).

# Input environment variables:
#   MCP_ID             numeric id; names the files <run>\<MCP_ID>.pid / .out.log / .err.log  (required)
#   MCP_NAME           seoul-weather | calculator | seoul-clock                               (required)
#   MCP_HOST           bind / dial host                                                       (required)
#   MCP_PORT           TCP port 1-65535                                                       (required)
#   DUMMY_MCPS_DIR     dummy-mcps checkout; must contain .venv\Scripts\python.exe             (required; a relative path is resolved against the cwd)
#   DUMMY_MCP_RUN_DIR  directory for the pid and log files (relative: against the cwd)  (default: <DUMMY_MCPS_DIR>\run)
#   DUMMY_MCP_CHAOS    "1" adds --chaos (registers the /chaos/* endpoints)
# The other MCP_* variables the monitor sets (MCP_PID, MCP_REASON, ...) are ignored.
# Exit codes: 0 success, 1 failure, 2 environment error (bad or missing variable, unknown MCP_NAME, no venv python).
#
# Keep in sync: start.ps1, stop.ps1 and restart.ps1 are deliberately self-contained (each executed file is hash-checked
# on its own), so the "SHARED" blocks are copies. tests/test_examples.py fails when they drift apart.
# >>> SHARED prelude
$ErrorActionPreference = 'Stop'
$Modules = @{ 'seoul-weather' = 'seoul_weather'; 'calculator' = 'calculator'; 'seoul-clock' = 'seoul_clock' }

function Exit-Env([string]$Message) {
    [Console]::Error.WriteLine("environment error: $Message")
    exit 2
}

if ($env:MCP_ID -notmatch '^[0-9]{1,9}\z') { Exit-Env 'MCP_ID must be a number' }
if (-not $env:MCP_NAME -or -not $Modules.ContainsKey($env:MCP_NAME)) { Exit-Env "unknown MCP_NAME '$($env:MCP_NAME)'" }
if (-not $env:MCP_HOST -or $env:MCP_HOST -match '[\s"]' -or $env:MCP_HOST.StartsWith('-')) { Exit-Env 'MCP_HOST is missing or invalid' }
$Port = 0
if (-not [int]::TryParse("$($env:MCP_PORT)", [ref]$Port) -or $Port -lt 1 -or $Port -gt 65535) { Exit-Env 'MCP_PORT must be 1-65535' }
if (-not $env:DUMMY_MCPS_DIR) { Exit-Env 'DUMMY_MCPS_DIR is not set' }

# Every path is made absolute against the caller's cwd: the server runs with WorkingDirectory=DUMMY_MCPS_DIR, so a
# relative --pid-file or log path would point somewhere other than where this script looks.
function Resolve-Abs([string]$Path) {
    [IO.Path]::GetFullPath([IO.Path]::Combine((Get-Location).ProviderPath, $Path))
}
$DummyDir = Resolve-Abs $env:DUMMY_MCPS_DIR
$Python = Join-Path $DummyDir '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { Exit-Env "python not found: $Python" }

$Module = $Modules[$env:MCP_NAME]
$RunDir = if ($env:DUMMY_MCP_RUN_DIR) { Resolve-Abs $env:DUMMY_MCP_RUN_DIR } else { Join-Path $DummyDir 'run' }
$PidFile = Join-Path $RunDir "$($env:MCP_ID).pid"
$OutLog = Join-Path $RunDir "$($env:MCP_ID).out.log"
$ErrLog = Join-Path $RunDir "$($env:MCP_ID).err.log"
[void](New-Item -ItemType Directory -Force -Path $RunDir)

# Address to dial for the readiness check (a wildcard bind is reached through loopback).
$ConnectHost = switch ($env:MCP_HOST) { '0.0.0.0' { '127.0.0.1' } '::' { '::1' } default { $env:MCP_HOST } }

function Test-Connect {
    $client = New-Object System.Net.Sockets.TcpClient
    try { return ($client.ConnectAsync($ConnectHost, $Port).Wait(1000) -and $client.Connected) }
    catch { return $false }
    finally { $client.Dispose() }
}

function Get-ListenerPids {
    @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique)
}

function Test-IsPython([int]$ProcessId) {
    $p = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    return ($null -ne $p -and $p.ProcessName -eq 'python')
}
# <<< SHARED prelude

# >>> SHARED stop-logic
# Only this MCP's own processes are killed. A pid file can outlive its process (crash, hard kill) and the pid can be
# recycled, and another python may hold the port, so a process (the pid-file pid or a listener) must be a python whose
# command line carries `-m <this module>` or this MCP's own --pid-file path.
function Test-OwnedProcess([int]$ProcessId) {
    $cim = Get-CimInstance -ClassName Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if ($null -eq $cim -or $null -eq $cim.CommandLine) { return $false }
    return ($cim.CommandLine.IndexOf($PidFile, [StringComparison]::OrdinalIgnoreCase) -ge 0 -or
        $cim.CommandLine -match "(?i)(^|\s)-m\s+$([regex]::Escape($Module))(\s|$)")
}

function Stop-Mcp {
    $targets = New-Object System.Collections.Generic.HashSet[int]
    foreach ($id in (Get-ListenerPids)) {
        if ((Test-IsPython $id) -and (Test-OwnedProcess $id)) { [void]$targets.Add([int]$id) }
    }
    if (Test-Path -LiteralPath $PidFile) {
        $text = "$(Get-Content -LiteralPath $PidFile -Raw -ErrorAction SilentlyContinue)".Trim()
        $hinted = 0
        if ([int]::TryParse($text, [ref]$hinted) -and $hinted -gt 0 -and (Test-IsPython $hinted) -and (Test-OwnedProcess $hinted)) {
            [void]$targets.Add($hinted)
        }
    }
    foreach ($id in $targets) {
        Write-Host "stopping pid $id"
        Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
    }
    $deadline = (Get-Date).AddSeconds(10)
    while (@(Get-ListenerPids).Count -gt 0) {
        if ((Get-Date) -ge $deadline) {
            Write-Host "port $Port is owned by unexpected process pid $((Get-ListenerPids) -join ', '); not stopping it"
            return 1
        }
        Start-Sleep -Milliseconds 200
    }
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
    Write-Host "$($env:MCP_NAME) on port $Port is stopped"
    return 0
}
# <<< SHARED stop-logic

exit (Stop-Mcp)
