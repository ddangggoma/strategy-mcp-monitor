<#
.SYNOPSIS
  MCP Monitor 감사 정책만 켜거나 되돌립니다(Plan 5 Task 14; Plan 4 실기기 점검표 준비 단계).

.DESCRIPTION
  -Enable: install.ps1의 감사 단계와 같습니다. 데이터 루트가 없으면 install.ps1과 같은 검사·ACL로 먼저
  만들고(secure_data_root), 바꾸기 전 레지스트리 값을 data\audit-policy-state.json에 처음 한 번 기록한 뒤,
  처음 한 번 현재 감사 정책을 백업하고(auditpol /backup), 프로세스 만들기·로그온·로그오프·기타
  로그온/로그오프·감사 정책 변경을 하위 범주 GUID로 켜고(한국어 Windows에서도 같음, W30), 명령줄 기록·
  스크립트 블록 기록 레지스트리 값과 로그 크기를 정합니다.
  -Restore <백업 파일>: auditpol /restore로 백업을 되돌리고, install-state.json(없으면
  audit-policy-state.json)이 있으면 레지스트리 값도 바꾸기 전 값으로 되돌립니다.

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
    # A drive that does not exist (Q:) has no PowerShell provider path: .NET still makes it absolute.
    try { $Path = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Path) } catch { }
    # A device path or a name .NET cannot read is an argument error, not a script failure (exit 1).
    try { $full = [System.IO.Path]::GetFullPath($Path) } catch { Stop-WithArgumentError "경로 $Path 을(를) 해석할 수 없습니다: $($_.Exception.Message)" }
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

# --- data root helpers (the same in install.ps1 and audit-policy.ps1; the first four also in uninstall.ps1) ---
# Letters of this PC's local fixed volumes ("C", "D"). A subst drive has no volume of its own, a network or
# removable drive is not a local fixed one: none of them is listed (re-review 3).
function Get-LocalDriveLetters {
    if (-not (Test-Path variable:script:LocalDriveLetters)) {
        $script:LocalDriveLetters = @(Get-CimInstance -ClassName Win32_Volume -Filter "DriveType = 3" |
            Where-Object { $_.DriveLetter } | ForEach-Object { $_.DriveLetter.Substring(0, 1).ToUpperInvariant() })
    }
    return $script:LocalDriveLetters
}

# The first existing folder from the drive down to $Full itself that is a junction or symbolic link ($null:
# none). Through one, another folder (the install folder, a system folder) would pass under a different name.
function Get-PathLinkProblem([string]$Full) {
    $path = $Full.Substring(0, 3)
    foreach ($part in @($Full.Substring(3).Split([char]'\') | Where-Object { $_ })) {
        $path = $path.TrimEnd('\') + '\' + $part
        try { $attributes = [System.IO.File]::GetAttributes($path) } catch {
            $e = $_.Exception
            while ($e.InnerException -and $e -is [System.Management.Automation.MethodInvocationException]) { $e = $e.InnerException }
            # Nothing exists below a missing folder.
            if ($e -is [System.IO.FileNotFoundException] -or $e -is [System.IO.DirectoryNotFoundException]) { return $null }
            return "$path 을(를) 확인하지 못했습니다: $($e.Message)"
        }
        if ($attributes -band [System.IO.FileAttributes]::ReparsePoint) { return "$path 은(는) 정션 또는 심볼릭 링크입니다(경로에 둘 수 없음)" }
    }
    return $null
}

# A folder these scripts create, fill or delete whole (the data root, the install folder): a path on a local
# fixed drive (C:\...) without a junction or symbolic link in it (\\?\ and \\.\ device paths, UNC and admin
# shares, subst and network drives would let one folder pass the comparisons below under another name, re-review
# 3), never a drive root, a system folder or a folder above one, nothing inside Windows (I3).
function Get-UnsafeRootReason([string]$Root) {
    if ($Root -match '^[\\/]{2}') { return "$Root 은(는) 로컬 드라이브의 경로(예: D:\MCP Monitor)가 아닙니다(UNC·장치 경로)" }
    $full = Get-FullPath $Root
    if ($full -notmatch '^[A-Za-z]:\\') { return "$Root 은(는) 로컬 드라이브의 경로(예: D:\MCP Monitor)가 아닙니다" }
    if ((Get-LocalDriveLetters) -notcontains $full.Substring(0, 1).ToUpperInvariant()) {
        return "$($full.Substring(0, 2)) 은(는) 이 PC의 로컬 고정 디스크가 아닙니다(subst·네트워크·이동식 드라이브)"
    }
    if ($full.TrimEnd('\') -eq ([System.IO.Path]::GetPathRoot($full)).TrimEnd('\')) { return "$full 은(는) 드라이브 루트입니다" }
    $link = Get-PathLinkProblem $full
    if ($link) { return $link }
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

# Every file and folder below $Root, never entering a junction or symbolic link.
function Get-TreeItems([string]$Root) {
    $out = New-Object System.Collections.Generic.List[System.IO.FileSystemInfo]
    $stack = New-Object System.Collections.Generic.Stack[System.IO.DirectoryInfo]
    $stack.Push((New-Object System.IO.DirectoryInfo $Root))
    while ($stack.Count -gt 0) {
        foreach ($item in $stack.Pop().EnumerateFileSystemInfos()) {
            $out.Add($item)
            if ($item -is [System.IO.DirectoryInfo] -and -not ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) { $stack.Push($item) }
        }
    }
    return $out.ToArray()
}

# The .NET exception under PowerShell's MethodInvocationException wrapper.
function Get-InnerException([System.Exception]$Exception) {
    while ($Exception.InnerException -and $Exception -is [System.Management.Automation.MethodInvocationException]) { $Exception = $Exception.InnerException }
    return $Exception
}

# Why an existing folder must not become the data root ($null: safe). Only an empty folder or an earlier
# data root (marker) is taken over, and only when SYSTEM, Administrators or the account running this script
# ($Owners) own every item and nothing is a junction or symbolic link: a user who created the folder before
# the install would otherwise keep write access to what the service runs as SYSTEM (finding C1).
function Get-DataRootProblem([string]$Root, [string[]]$Owners) {
    if (-not (Test-Path -LiteralPath $Root)) { return $null }
    $info = New-Object System.IO.DirectoryInfo $Root
    if (-not $info.Exists) { return "$Root 은(는) 폴더가 아닙니다" }
    if ($info.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { return "$Root 은(는) 정션 또는 심볼릭 링크입니다" }
    for ($attempt = 1; ; $attempt++) {
        try {
            $items = @(Get-TreeItems $Root)
            foreach ($item in @($info) + $items) {
                if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { return "$($item.FullName) 은(는) 정션 또는 심볼릭 링크입니다" }
                $owner = $item.GetAccessControl([System.Security.AccessControl.AccessControlSections]::Owner).GetOwner([System.Security.Principal.SecurityIdentifier]).Value
                if ($Owners -notcontains $owner) { return "$($item.FullName) 의 소유자($owner)가 SYSTEM·Administrators가 아닙니다" }
            }
            break
        } catch {
            $e = Get-InnerException $_.Exception
            # The running service's retention may gzip or delete a log between the listing and the read: look once more.
            if ($attempt -lt 2 -and ($e -is [System.IO.FileNotFoundException] -or $e -is [System.IO.DirectoryNotFoundException])) { continue }
            return "$Root 을(를) 확인하지 못했습니다: $($e.Message)"
        }
    }
    if ($items.Count -gt 0 -and -not (Test-DataRootMarker $Root)) { return "$Root 이(가) 비어 있지 않고 MCP Monitor 데이터 폴더도 아닙니다" }
    return $null
}

# $false when the data root exists but this account may not list it: an installed data root (SYSTEM and
# Administrators only) seen from a PowerShell without admin rights (-DryRun, re-review 4).
function Test-DataRootReadable([string]$Root) {
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) { return $true }
    try {
        [void](New-Object System.IO.DirectoryInfo $Root).EnumerateFileSystemInfos().GetEnumerator().MoveNext()
        return $true
    } catch {
        return -not ((Get-InnerException $_.Exception) -is [System.UnauthorizedAccessException])
    }
}

# Why the folders above the data root would let a user who is not an administrator swap it ($null: none,
# re-review 2). Every existing folder between the drive root and the data root must be owned by SYSTEM,
# Administrators, TrustedInstaller or $Owners and give no other account DELETE, WRITE_DAC, WRITE_OWNER or
# FILE_DELETE_CHILD: with any of them a user renames the folder while the service is stopped and puts a tree
# of his own in its place, which the service then runs as SYSTEM. Inherit-only ACEs (they apply below, not
# to the folder), CREATOR OWNER / OWNER RIGHTS placeholders and app-container SIDs (S-1-15-*, never alone
# enough for access) do not count. C:\ProgramData and a folder directly under a drive root pass.
function Get-AncestorProblem([string]$Root, [string[]]$Owners) {
    $trusted = @($Owners) + "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"
    # DELETE, WRITE_DAC, WRITE_OWNER, FILE_DELETE_CHILD, GENERIC_ALL
    $danger = 0x10000 -bor 0x40000 -bor 0x80000 -bor 0x40 -bor 0x10000000
    $sidType = [System.Security.Principal.SecurityIdentifier]
    $full = Get-FullPath $Root
    $drive = ([System.IO.Path]::GetPathRoot($full)).TrimEnd('\')
    $chain = @()
    $dir = Split-Path -Parent $full
    while ($dir -and $dir.TrimEnd('\') -ne $drive) { $chain = @($dir) + $chain; $dir = Split-Path -Parent $dir }
    foreach ($folder in $chain) {
        # A missing folder (and everything below it) is made with the data root's own ACL (New-ProtectedDirectory).
        if (-not (Test-Path -LiteralPath $folder -PathType Container)) { return $null }
        try { $acl = (New-Object System.IO.DirectoryInfo $folder).GetAccessControl() }
        catch { return "$folder 의 권한을 확인하지 못했습니다: $((Get-InnerException $_.Exception).Message)" }
        $advice = "데이터 루트는 관리자만 바꿀 수 있는 폴더 아래나 드라이브 바로 아래(예: D:\MCP Monitor)에 두세요"
        $owner = $acl.GetOwner($sidType).Value
        if ($trusted -notcontains $owner) { return "$folder 의 소유자($owner)가 관리자가 아닙니다. $advice" }
        foreach ($rule in @($acl.GetAccessRules($true, $true, $sidType))) {
            $sid = $rule.IdentityReference.Value
            if ($rule.AccessControlType -ne "Allow" -or ($rule.PropagationFlags -band [System.Security.AccessControl.PropagationFlags]::InheritOnly) -or
                $trusted -contains $sid -or $sid -like "S-1-3-*" -or $sid -like "S-1-15-*") { continue }
            if (([int64]$rule.FileSystemRights -band $danger) -ne 0) {
                return "$folder 을(를) 관리자가 아닌 계정($sid)이 지우거나 이름·권한을 바꿀 수 있습니다($($rule.FileSystemRights)). $advice"
            }
        }
    }
    return $null
}

# One item below the data root: no ACEs of its own (only those inherited from the root), owner $Owner.
function Reset-ItemAcl([System.IO.FileSystemInfo]$Item, [string]$Owner) {
    if ($Item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { throw "$($Item.FullName) 은(는) 정션 또는 심볼릭 링크입니다" }
    $acl = $Item.GetAccessControl()
    foreach ($rule in @($acl.GetAccessRules($true, $false, [System.Security.Principal.SecurityIdentifier]))) { [void]$acl.RemoveAccessRuleSpecific($rule) }
    $acl.SetAccessRuleProtection($false, $false)
    $acl.SetOwner((New-Object System.Security.Principal.SecurityIdentifier $Owner))
    $Item.SetAccessControl($acl)
}

# The data root's ACL built from scratch (not edited: icacls /grant:r keeps every other explicit ACE):
# owner $Owner, inheritance off, full control for $Sids only, inherited by everything below.
function New-RootSecurity([string]$Owner, [string[]]$Sids) {
    $sec = New-Object System.Security.AccessControl.DirectorySecurity
    $sec.SetOwner((New-Object System.Security.Principal.SecurityIdentifier $Owner))
    $sec.SetAccessRuleProtection($true, $false)
    foreach ($sid in $Sids) {
        $sec.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
            (New-Object System.Security.Principal.SecurityIdentifier $sid), "FullControl", "ContainerInherit,ObjectInherit", "None", "Allow")))
    }
    return $sec
}

function Set-RootAcl([string]$Root, [string]$Owner, [string[]]$Sids) {
    (New-Object System.IO.DirectoryInfo $Root).SetAccessControl((New-RootSecurity $Owner $Sids))
}

# Creates $Path and every missing folder above it, each in one call with the data root's final ACL: there is
# no moment in which it inherits the parent's ACL (C:\ProgramData lets Users add files and folders), and a
# missing parent of a custom data root is as closed as the root itself (re-review 1, 2). A folder that already
# exists is left as it is (CreateDirectory does nothing), so the caller checks what it finds afterwards.
function New-ProtectedDirectory([string]$Path, [string]$Owner, [string[]]$Sids) {
    $sec = New-RootSecurity $Owner $Sids
    $missing = @()
    $dir = $Path
    while ($dir -and -not (Test-Path -LiteralPath $dir)) { $missing = @($dir) + $missing; $dir = Split-Path -Parent $dir }
    foreach ($d in $missing) { [void][System.IO.Directory]::CreateDirectory($d, $sec) }
}

# What differs from the ACL Initialize-DataRoot sets (empty: exactly that), read back from the disk.
function Get-DataRootAclProblems([string]$Root, [string]$Owner, [string[]]$Sids) {
    $problems = New-Object System.Collections.Generic.List[string]
    $sidType = [System.Security.Principal.SecurityIdentifier]
    $full = [System.Security.AccessControl.FileSystemRights]::FullControl
    $rootInfo = New-Object System.IO.DirectoryInfo $Root
    foreach ($item in @($rootInfo) + @(Get-TreeItems $Root)) {
        $name = $item.FullName
        if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { $problems.Add("$($name): 정션 또는 심볼릭 링크"); continue }
        $acl = $item.GetAccessControl()
        $isRoot = $name.TrimEnd('\') -eq $rootInfo.FullName.TrimEnd('\')
        $o = $acl.GetOwner($sidType).Value
        if ($o -ne $Owner) { $problems.Add("$($name): 소유자 $o") }
        $explicit = @($acl.GetAccessRules($true, $false, $sidType))
        if ($isRoot) {
            if (-not $acl.AreAccessRulesProtected) { $problems.Add("$($name): 상위 폴더의 권한을 상속함") }
            foreach ($sid in $Sids) {
                $ok = @($explicit | Where-Object { $_.IdentityReference.Value -eq $sid -and $_.AccessControlType -eq "Allow" -and
                    ($_.FileSystemRights -band $full) -eq $full -and $_.InheritanceFlags -eq "ContainerInherit, ObjectInherit" })
                if ($ok.Count -eq 0) { $problems.Add("$($name): $sid 의 모든 권한 없음") }
            }
        } elseif ($explicit.Count -gt 0) {
            $problems.Add("$($name): 자체 ACE $($explicit.Count)개")
        }
        foreach ($rule in @($acl.GetAccessRules($true, $true, $sidType))) {
            if ($rule.AccessControlType -ne "Allow" -or $Sids -notcontains $rule.IdentityReference.Value) {
                $problems.Add("$($name): $($rule.IdentityReference.Value) $($rule.AccessControlType) $($rule.FileSystemRights)")
            }
        }
    }
    return $problems.ToArray()
}

# Creates or takes over the data root (finding C1): the checks of Get-DataRootProblem and Get-AncestorProblem;
# a missing root created with its final ACL and then checked as found (a folder another account made in the
# moment before keeps that account's owner and ACL: refused, re-review 1); an existing root checked as found
# before its ACL changes; the root's ACL from scratch; the same checks again once nobody else can write; every
# item below reset; logs\ data\ scripts\ and the marker; then the ACL read back: any difference fails the step.
function Initialize-DataRoot([string]$Root, [string]$Owner, [string[]]$Sids, [string[]]$Owners, [string]$CreatedBy) {
    $problem = Get-DataRootProblem $Root $Owners
    if (-not $problem) { $problem = Get-AncestorProblem $Root $Owners }
    if ($problem) { throw $problem }
    if (-not (Test-Path -LiteralPath $Root)) {
        New-ProtectedDirectory $Root $Owner $Sids
        $problems = @(Get-DataRootAclProblems $Root $Owner $Sids)
        if ($problems.Count -gt 0) { throw "$Root 을(를) 다른 계정이 먼저 만들었습니다: $($problems -join '; ')" }
        $problem = Get-AncestorProblem $Root $Owners
        if ($problem) { throw $problem }
    }
    $problem = Get-DataRootProblem $Root $Owners
    if ($problem) { throw $problem }
    Set-RootAcl $Root $Owner $Sids
    $problem = Get-DataRootProblem $Root $Owners
    if ($problem) { throw $problem }
    foreach ($item in @(Get-TreeItems $Root)) { Reset-ItemAcl $item $Owner }
    foreach ($d in "logs", "data", "scripts") {
        $dir = New-Object System.IO.DirectoryInfo (Join-Path $Root $d)
        if (-not $dir.Exists) { $dir.Create(); $dir.Refresh(); Reset-ItemAcl $dir $Owner }
    }
    $marker = Join-Path $Root "data\mcp-monitor-data-root.json"
    if (-not (Test-Path -LiteralPath $marker)) {
        $text = [ordered]@{ product = "mcp-monitor"; created_by = $CreatedBy; created_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz") } | ConvertTo-Json
        [System.IO.File]::WriteAllText($marker, $text, (New-Object System.Text.UTF8Encoding $false))
        Reset-ItemAcl (New-Object System.IO.FileInfo $marker) $Owner
    }
    $problems = @(Get-DataRootAclProblems $Root $Owner $Sids)
    if ($problems.Count -gt 0) { throw "데이터 폴더 권한 확인 실패: $($problems -join '; ')" }
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
    # Before an install the data root may not exist yet: made here with the same ACL as install.ps1.
    "(secure-data-root)" = { param($s) Initialize-DataRoot $s.args[0] "S-1-5-32-544" @("S-1-5-18", "S-1-5-32-544") $DataRootOwners "audit-policy"; 0 }
    "(write-json)"  = { param($s) [System.IO.File]::WriteAllText($s.args[0], $s.args[1], (New-Object System.Text.UTF8Encoding $false)); 0 }
}

$Conditions = @{
    no_backup_yet = { -not (Test-Path -LiteralPath $BackupPath) }
    # install-state.json (or an earlier -Enable) already holds the values from before our first change.
    no_registry_record_yet = { -not (Test-Path -LiteralPath $AuditStatePath) -and -not (Test-Path -LiteralPath $InstallStatePath) }
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
$Notes = New-Object System.Collections.Generic.List[string]
$DataRoot = Get-FullPath $DataRoot
$BackupPath = "$DataRoot\data\auditpol-backup.csv"
$InstallStatePath = "$DataRoot\data\install-state.json"
$AuditStatePath = "$DataRoot\data\audit-policy-state.json"
if ($Restore) {
    $Restore = Get-FullPath $Restore
    if (-not (Test-Path -LiteralPath $Restore -PathType Leaf)) { Stop-WithArgumentError "백업 파일 $Restore 이(가) 없습니다." }
}
if ($Enable) {
    # -Enable writes into the data root (the backup, the registry record): the same checks as install.ps1 (C1, I3).
    $unsafe = Get-UnsafeRootReason $DataRoot
    if ($unsafe) { Stop-WithArgumentError "-DataRoot: $unsafe" }
    $DataRootOwners = @("S-1-5-18", "S-1-5-32-544", [Security.Principal.WindowsIdentity]::GetCurrent().User.Value)
    if (-not (Test-Admin) -and -not (Test-DataRootReadable $DataRoot)) {
        # An installed data root without admin rights (-DryRun): what it holds is checked again in secure_data_root.
        $Notes.Add("$DataRoot 은(는) 관리자만 읽을 수 있어 안을 확인하지 못했습니다(소유자·내용 검사, 이전 레지스트리 기록). 관리자 권한으로 다시 실행하면 확인합니다.")
    } else {
        $problem = Get-DataRootProblem $DataRoot $DataRootOwners
        if ($problem) { Stop-WithArgumentError "-DataRoot: $problem" }
    }
    $problem = Get-AncestorProblem $DataRoot $DataRootOwners
    if ($problem) { Stop-WithArgumentError "-DataRoot: $problem" }
}
$Bundle = Read-JsonFile (Join-Path (Split-Path -Parent $PSScriptRoot) "bundle.json")
$RegistryBefore = Get-Prop (Read-JsonFile $InstallStatePath) "registry_before"
if ($null -eq $RegistryBefore) { $RegistryBefore = Get-Prop (Read-JsonFile $AuditStatePath) "registry_before" }

# --- plan ---------------------------------------------------------------------------------------
Add-Step "require_admin" "(admin)"
if ($Enable) {
    Add-Step "secure_data_root" "(secure-data-root)" @($DataRoot)
    # The registry values before our first change (uninstall / -Restore put them back), recorded before
    # anything changes; install.ps1 takes them over.
    $current = [ordered]@{}
    foreach ($key in @("$AuditKey\ProcessCreationIncludeCmdLine_Enabled", "$PsLogKey\EnableScriptBlockLogging")) {
        $current[$key] = Get-RegistryValue (Split-Path -Parent $key) (Split-Path -Leaf $key)
    }
    $record = [ordered]@{ registry_before = $current; audit_backup = $BackupPath; recorded_at = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz") }
    Add-Step "record_registry" "(write-json)" @($AuditStatePath, ($record | ConvertTo-Json -Depth 4 -Compress)) -When "no_registry_record_yet"
    # The same steps (and arguments) as install.ps1's audit steps.
    Add-Step "audit_backup" "auditpol" @("/backup", "/file:$BackupPath") -When "no_backup_yet"
    Add-Step "audit_policy_success" "auditpol" @("/set", "/subcategory:$SuccessGuids", "/success:enable")
    Add-Step "audit_policy_failure" "auditpol" @("/set", "/subcategory:$FailureGuids", "/failure:enable")
    Add-Step "registry_cmdline" "reg" @("add", $AuditKey, "/v", "ProcessCreationIncludeCmdLine_Enabled", "/t", "REG_DWORD", "/d", "1", "/f")
    Add-Step "registry_scriptblock" "reg" @("add", $PsLogKey, "/v", "EnableScriptBlockLogging", "/t", "REG_DWORD", "/d", "1", "/f")
    Add-Step "security_log_size" "wevtutil" @("sl", "Security", "/ms:268435456")
    Add-Step "powershell_log_size" "wevtutil" @("sl", "Microsoft-Windows-PowerShell/Operational", "/ms:67108864")
} else {
    $RegistryEntries = @()
    if ($null -ne $RegistryBefore) {
        $RegistryEntries = @($RegistryBefore.PSObject.Properties | ForEach-Object { "$($_.Name)=$(if ($null -eq $_.Value) { 'null' } else { $_.Value })" })
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
        notes        = $Notes.ToArray()
    }
    foreach ($note in $Notes) { [Console]::Error.WriteLine("참고: $note") }
    Write-Output ($plan | ConvertTo-Json -Depth 6 -Compress)
    exit 0
}

Invoke-Plan
Write-Host $(if ($Enable) { "감사 정책을 켰습니다." } else { "감사 정책을 되돌렸습니다." })
exit 0
