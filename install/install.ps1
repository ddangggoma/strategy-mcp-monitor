<#
.SYNOPSIS
  MCP Monitor 설치 (Plan 5 Task 14): 묶음 복사, 데이터 폴더 ACL, 감사 정책, 서비스 등록·시작.

.DESCRIPTION
  계획(단계 목록)을 먼저 만들고, -DryRun이면 그 계획을 JSON 한 줄로 출력하고 끝납니다(관리자 불필요,
  아무것도 바꾸지 않음). 아니면 같은 계획을 차례로 실행합니다. 첫 단계는 관리자 확인이며, 관리자가
  아니면 어떤 변경도 하기 전에 종료 코드 1로 끝납니다(W29).

  ACL은 이름이 아니라 SID로, 감사 정책은 하위 범주 GUID로 지정합니다(한국어 Windows에서도 같음, W30).
  방화벽 규칙은 -OpenFirewall일 때만 만듭니다(spec 2 #6).

  데이터 루트(플랜 리뷰 C1, I3): 없는 폴더, 빈 폴더, 이전 데이터 루트만 받습니다(SYSTEM·Administrators·
  설치하는 계정이 모든 항목의 소유자이고 정션·심볼릭 링크가 없을 때). 있는 데이터 루트와 그 안의 항목을
  관리자가 아닌 계정이 지우거나 쓰거나 권한·소유자를 바꿀 수 있으면 거부합니다(미리 열어 둔 핸들은 ACL을
  바꾼 뒤에도 남음: 그 폴더는 지우고 설치가 만들게 함). 드라이브 루트·시스템 폴더와 설치
  폴더·묶음과 겹치는 폴더도 거부합니다. ACL은 고치지 않고 처음부터 새로 만든 뒤 다시 읽어 확인합니다.
  없는 데이터 루트(와 없는 상위 폴더)는 처음부터 그 ACL로 만듭니다. 있는 상위 폴더를 관리자가 아닌 계정이
  지우거나 이름·권한을 바꿀 수 있거나, 드라이브 루트에서 그 안의 폴더를 지우거나 이름을 바꾸거나 드라이브
  루트의 권한을 바꿀 수 있으면 거부합니다(재검토 1, 2).
  -InstallDir와 -DataRoot는 로컬 고정 디스크의 경로(C:\...)여야 합니다: \\?\·\\.\ 장치 경로, UNC·관리 공유,
  subst·네트워크 드라이브, 경로 안의 정션·심볼릭 링크는 거부합니다(재검토 3).

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

# The first ACE of $Acl that gives an account other than $Owners and TrustedInstaller one of $Rights on the
# item itself ($null: none). Deny ACEs, inherit-only ACEs (they apply below, not to the item), CREATOR OWNER /
# OWNER RIGHTS placeholders and app-container SIDs (S-1-15-*, never alone enough for access) do not count.
function Get-UntrustedRule($Acl, [string[]]$Owners, [int64]$Rights) {
    $trusted = @($Owners) + "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"
    foreach ($rule in @($Acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier]))) {
        $sid = $rule.IdentityReference.Value
        if ($rule.AccessControlType -ne "Allow" -or ($rule.PropagationFlags -band [System.Security.AccessControl.PropagationFlags]::InheritOnly) -or
            $trusted -contains $sid -or $sid -like "S-1-3-*" -or $sid -like "S-1-15-*") { continue }
        if (([int64]$rule.FileSystemRights -band $Rights) -ne 0) { return $rule }
    }
    return $null
}

# Why an existing folder must not become the data root ($null: safe). Only an empty folder or an earlier
# data root (marker) is taken over, and only when SYSTEM, Administrators or the account running this script
# ($Owners) own every item and nothing is a junction or symbolic link: a user who created the folder before
# the install would otherwise keep write access to what the service runs as SYSTEM (finding C1). Nor may any
# other account have DELETE, WRITE_DAC, WRITE_OWNER, FILE_DELETE_CHILD, write access or a generic all/write
# right on the root or an item below it, explicit or inherited: a handle he opens with it before the install
# keeps that access after Set-RootAcl, so he could rename the root away through it and put his own config.db
# and scripts in its place, or write into them (fix wave). Such a folder is deleted and the install makes it.
function Get-DataRootProblem([string]$Root, [string[]]$Owners) {
    if (-not (Test-Path -LiteralPath $Root)) { return $null }
    $info = New-Object System.IO.DirectoryInfo $Root
    if (-not $info.Exists) { return "$Root 은(는) 폴더가 아닙니다" }
    if ($info.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { return "$Root 은(는) 정션 또는 심볼릭 링크입니다" }
    # DELETE, WRITE_DAC, WRITE_OWNER, FILE_DELETE_CHILD, GENERIC_ALL, GENERIC_WRITE, FILE_WRITE_DATA, FILE_APPEND_DATA
    $open = 0x10000 -bor 0x40000 -bor 0x80000 -bor 0x40 -bor 0x10000000 -bor 0x40000000 -bor 0x2 -bor 0x4
    $sections = [System.Security.AccessControl.AccessControlSections]"Owner, Access"
    for ($attempt = 1; ; $attempt++) {
        try {
            $items = @(Get-TreeItems $Root)
            foreach ($item in @($info) + $items) {
                if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { return "$($item.FullName) 은(는) 정션 또는 심볼릭 링크입니다" }
                $acl = $item.GetAccessControl($sections)
                $owner = $acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value
                if ($Owners -notcontains $owner) { return "$($item.FullName) 의 소유자($owner)가 SYSTEM·Administrators가 아닙니다" }
                $rule = Get-UntrustedRule $acl $Owners $open
                if ($rule) {
                    return "$($item.FullName) 을(를) 관리자가 아닌 계정($($rule.IdentityReference.Value))이 지우거나 쓰거나 권한·소유자를 바꿀 수 있습니다" +
                        "($($rule.FileSystemRights)). 그 권한으로 설치 전에 열어 둔 핸들은 설치가 권한을 바꾼 뒤에도 남습니다. " +
                        "$Root 을(를) 지우고 설치가 새로 만들게 하세요(이전 데이터를 지킬 때는 그 권한을 없애고 PC를 다시 시작한 뒤 설치하세요)"
                }
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

# The ACL of a folder above the data root (a test stands a scratch folder in for a drive root here).
function Get-FolderAcl([string]$Path) {
    return (New-Object System.IO.DirectoryInfo $Path).GetAccessControl()
}

# Why the folders above the data root would let a user who is not an administrator swap it ($null: none,
# re-review 2). Every existing folder from the drive root down to the data root's parent must be owned by
# SYSTEM, Administrators, TrustedInstaller or $Owners and give no other account (Get-UntrustedRule) DELETE,
# WRITE_DAC, WRITE_OWNER, FILE_DELETE_CHILD or GENERIC_ALL: with any of them a user renames the folder (or,
# with FILE_DELETE_CHILD, the folder below it) while the service is stopped and puts a tree of his own in its
# place, which the service then runs as SYSTEM. The drive root itself can be neither deleted nor renamed, so
# DELETE on it does not count (a data volume's root gives Authenticated Users Modify on itself). C:\, a data
# volume's default root, C:\ProgramData and a folder directly under a drive root pass.
function Get-AncestorProblem([string]$Root, [string[]]$Owners) {
    $trusted = @($Owners) + "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"
    # DELETE, WRITE_DAC, WRITE_OWNER, FILE_DELETE_CHILD, GENERIC_ALL
    $danger = 0x10000 -bor 0x40000 -bor 0x80000 -bor 0x40 -bor 0x10000000
    $full = Get-FullPath $Root
    $drive = [System.IO.Path]::GetPathRoot($full)
    $chain = @()
    $dir = Split-Path -Parent $full
    while ($dir) { $chain = @($dir) + $chain; $dir = Split-Path -Parent $dir }
    foreach ($folder in $chain) {
        # A missing folder (and everything below it) is made with the data root's own ACL (New-ProtectedDirectory).
        if (-not (Test-Path -LiteralPath $folder -PathType Container)) { return $null }
        try { $acl = Get-FolderAcl $folder }
        catch { return "$folder 의 권한을 확인하지 못했습니다: $((Get-InnerException $_.Exception).Message)" }
        $isDrive = $folder.TrimEnd('\') -eq $drive.TrimEnd('\')
        if ($isDrive) {
            $what = "드라이브 루트 $folder 에서 관리자가 아닌 계정이 그 안의 폴더를 지우거나 이름을 바꾸거나 드라이브 루트의 권한을 바꿀 수 있습니다"
            $advice = "드라이브 루트의 그 권한을 없애거나 데이터 루트를 다른 드라이브에 두세요"
            $rights = $danger -band -bnot 0x10000
        } else {
            $what = "$folder 을(를) 관리자가 아닌 계정이 지우거나 이름·권한을 바꿀 수 있습니다"
            $advice = "데이터 루트는 관리자만 바꿀 수 있는 폴더 아래나 드라이브 바로 아래(예: D:\MCP Monitor)에 두세요"
            $rights = $danger
        }
        $owner = $acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value
        if ($trusted -notcontains $owner) { return "$folder 의 소유자($owner)가 관리자가 아닙니다. $advice" }
        $rule = Get-UntrustedRule $acl $Owners $rights
        if ($rule) { return "$what($($rule.IdentityReference.Value): $($rule.FileSystemRights)). $advice" }
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
    "(secure-data-root)" = { param($s) Initialize-DataRoot $s.args[0] "S-1-5-32-544" @("S-1-5-18", "S-1-5-32-544") $DataRootOwners "install"; 0 }
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

# robocopy /MIR fills and prunes the install folder and the service runs it as SYSTEM (re-review 3).
$unsafe = Get-UnsafeRootReason $InstallDir
if ($unsafe) { Stop-WithArgumentError "-InstallDir: $unsafe" }
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
# The data root: never where robocopy /MIR copies or deletes (I3), nor a folder uninstall must not delete
# whole, nor a folder someone else made (C1). Checked before anything is read from it.
foreach ($other in @($InstallDir, $Source)) {
    if ($DataRoot -eq $other -or (Test-Inside $DataRoot $other) -or (Test-Inside $other $DataRoot)) {
        Stop-WithArgumentError "-DataRoot($DataRoot)는 $other 와(과) 겹치지 않는 폴더여야 합니다."
    }
}
$unsafe = Get-UnsafeRootReason $DataRoot
if ($unsafe) { Stop-WithArgumentError "-DataRoot: $unsafe" }
$DataRootOwners = @("S-1-5-18", "S-1-5-32-544", [Security.Principal.WindowsIdentity]::GetCurrent().User.Value)
$Notes = New-Object System.Collections.Generic.List[string]
if (-not (Test-Admin) -and -not (Test-DataRootReadable $DataRoot)) {
    # An installed data root without admin rights (-DryRun): what it holds is checked again in secure_data_root.
    $Notes.Add("$DataRoot 은(는) 관리자만 읽을 수 있어 안을 확인하지 못했습니다(소유자·내용 검사, 이전 install-state.json). 관리자 권한으로 다시 실행하면 확인합니다.")
} else {
    $problem = Get-DataRootProblem $DataRoot $DataRootOwners
    if ($problem) { Stop-WithArgumentError "-DataRoot: $problem" }
}
$problem = Get-AncestorProblem $DataRoot $DataRootOwners
if ($problem) { Stop-WithArgumentError "-DataRoot: $problem" }

$ServiceExists = $null -ne (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue)
$BackupPath = "$DataRoot\data\auditpol-backup.csv"
$StatePath = "$DataRoot\data\install-state.json"
$OldState = Read-JsonFile $StatePath

# The values before our first install (or before audit-policy.ps1 -Enable): a reinstall keeps them (it
# would otherwise record our own 1s).
$RegistryValues = [ordered]@{ "$AuditKey\ProcessCreationIncludeCmdLine_Enabled" = $null; "$PsLogKey\EnableScriptBlockLogging" = $null }
$RegistryBefore = [ordered]@{}
$oldRegistry = Get-Prop $OldState "registry_before"
if ($null -eq $oldRegistry) { $oldRegistry = Get-Prop (Read-JsonFile "$DataRoot\data\audit-policy-state.json") "registry_before" }
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
# Data root ACL from scratch: owner Administrators, no inheritance, SYSTEM + Administrators full control
# only; everything below inherits only that; read back and verified (Initialize-DataRoot, finding C1).
Add-Step "secure_data_root" "(secure-data-root)" @($DataRoot)
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
        notes        = $Notes.ToArray()
    }
    foreach ($note in $Notes) { [Console]::Error.WriteLine("참고: $note") }
    Write-Output ($plan | ConvertTo-Json -Depth 6 -Compress)
    exit 0
}

Invoke-Plan
Write-Host "설치 완료: http://127.0.0.1:$LocalPort/admin/setup 에서 첫 Admin 계정을 만드세요."
exit 0
