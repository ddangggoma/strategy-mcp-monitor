# server/tests/test_install_scripts.py
"""install.ps1 / uninstall.ps1 / audit-policy.ps1 (Plan 5 Task 14).

Only ``-DryRun`` plans and the "not an administrator: change nothing, exit 1" path run here (Global
Constraints): this PC is not elevated and its services, firewall, audit policy, registry and ACLs
must not change. Every real (non-DryRun) run goes through ``real_run``, which fails the test first
if the suite is elevated (preflight F13).

PowerShell runs in a new hidden console, so its console code page is this PC's (949 on ko-KR), as
in an operator's console (preflight F13): the scripts must still write UTF-8.
"""

import ctypes
import json
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from app.winsvc import DESCRIPTION

REPO = Path(__file__).resolve().parents[2]
INSTALL = REPO / "install"
PS = [str(Path(os.environ["SystemRoot"]) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"),
      "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass"]
GUID = re.compile(r"\{0CCE92[0-9A-F]{2}-69AE-11D9-BED3-505054503030\}")
AUDIT_KEY = r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System\Audit\ProcessCreationIncludeCmdLine_Enabled"
PS_KEY = r"HKLM\SOFTWARE\Policies\Microsoft\Windows\PowerShell\ScriptBlockLogging\EnableScriptBlockLogging"
ICACLS = str(Path(os.environ["SystemRoot"]) / "System32" / "icacls.exe")
SCRATCH = Path(os.environ["LOCALAPPDATA"]) / "mcp-monitor-install-tests"


@pytest.fixture(name="tmp_path")
def scratch_path():
    """A scratch folder whose parents only SYSTEM, Administrators and this account can change.

    install.ps1 refuses a data root below a folder another account may delete or rename (re-review 2), and
    this PC's %TEMP% gives a sandbox's user group Modify, so pytest's own tmp_path would be refused. A folder
    under %LOCALAPPDATA% inherits only the profile's ACL. Removed after the test.
    """
    path = SCRATCH / uuid.uuid4().hex[:12]
    path.mkdir(parents=True)
    yield path
    shutil.rmtree(path, ignore_errors=True)
    if path.exists():  # a test failed before it unlocked its folder
        subprocess.run([ICACLS, str(path), "/reset", "/T", "/C", "/Q"], capture_output=True)
        shutil.rmtree(path, ignore_errors=True)
    try:
        SCRATCH.rmdir()
    except OSError:
        pass


def ps(*args, timeout=120):
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0  # SW_HIDE
    return subprocess.run([*PS, *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, stdin=subprocess.DEVNULL,
                          creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=si)


def dry(script, *args):
    p = ps("-File", str(INSTALL / script), "-DryRun", *args)
    assert p.returncode == 0, p.stdout + p.stderr
    return json.loads(p.stdout)


def real_run(script, *args):
    # A real run on an elevated PowerShell would install/uninstall for real: never (Global Constraints).
    if ctypes.windll.shell32.IsUserAnAdmin():
        pytest.fail("the install-script tests must not run elevated: they would change this PC")
    return ps("-File", str(INSTALL / script), *args)


@pytest.fixture
def bundle(tmp_path):
    # Its own folder: an install folder inside the bundle is refused (robocopy /MIR would copy it into itself).
    b = tmp_path / "bundle"
    b.mkdir()
    (b / "bundle.json").write_text(json.dumps({"layout": "runtime", "version": "1.0.0", "python": "3.15.2",
                                               "built_at": "x", "commit": "y"}), "utf-8")
    (b / "runtime").mkdir(); (b / "runtime" / "python.exe").write_bytes(b"")
    return b


def step(plan, sid):
    return next(s for s in plan["steps"] if s["id"] == sid)


@pytest.mark.parametrize("name", ["install.ps1", "uninstall.ps1", "audit-policy.ps1", "build.ps1"])
def test_scripts_parse(name):
    p = ps("-Command", f"$e = $null; [void][System.Management.Automation.Language.Parser]::ParseFile('{INSTALL / name}', [ref]$null, [ref]$e); $e.Count")
    assert p.returncode == 0 and p.stdout.strip() == "0", p.stdout + p.stderr


@pytest.mark.parametrize("name", ["install.ps1", "uninstall.ps1", "audit-policy.ps1"])
def test_operations_guide_documents_every_parameter(name):
    # docs/ops/OPERATIONS.md ships in the bundle (Task 16): a new or renamed script parameter must
    # show up in it, as `-Name` in a table row or a command
    text = (INSTALL / name).read_text("utf-8-sig")
    block = re.search(r"^param\((.*?)^\)", text, re.S | re.M)
    assert block, name
    params = re.findall(r"\$([A-Za-z]+)\s*(?:=|,|$)", block.group(1), re.M)
    assert params, name
    guide = (REPO / "docs" / "ops" / "OPERATIONS.md").read_text("utf-8")
    assert [p for p in params if f"-{p}" not in guide] == [], name


@pytest.mark.parametrize("name", ["install.ps1", "uninstall.ps1", "audit-policy.ps1"])
def test_scripts_are_utf8_with_bom(name):
    # Windows PowerShell 5.1 reads a BOM-less script in the ANSI code page (949): Korean text would break.
    raw = (INSTALL / name).read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    raw.decode("utf-8")


# Each script stays one self-contained file (audit-policy.ps1 is also used alone, before an install): the
# shared code is copied, and this test keeps the copies one implementation.
SHARED = ["Stop-WithArgumentError", "Get-FullPath", "Test-Inside", "Get-Prop", "Read-JsonFile", "Test-Admin", "Add-Step",
          "ConvertTo-CommandLineArg", "Invoke-Native", "Get-LocalDriveLetters", "Get-PathLinkProblem",
          "Get-UnsafeRootReason", "Test-DataRootMarker"]
# The data root helpers install.ps1 and audit-policy.ps1 both use (C1): identical in the two.
DATA_ROOT = ["Get-RegistryValue", "Get-TreeItems", "Get-InnerException", "Get-UntrustedRule", "Get-DataRootProblem",
             "Test-DataRootReadable", "Get-FolderAcl", "Get-AncestorProblem", "Reset-ItemAcl", "New-RootSecurity", "Set-RootAcl", "New-ProtectedDirectory",
             "Get-DataRootAclProblems", "Initialize-DataRoot"]


def functions(name):
    p = ps("-Command", f"[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false); "
                       f"$ast = [System.Management.Automation.Language.Parser]::ParseFile('{INSTALL / name}', [ref]$null, [ref]$null); "
                       "$d = @{}; foreach ($f in $ast.FindAll({ $args[0] -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)) "
                       "{ $d[$f.Name] = $f.Extent.Text }; $d | ConvertTo-Json -Compress")
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def test_shared_helpers_are_identical_in_the_three_scripts():
    install, uninstall, audit = (functions(n) for n in ("install.ps1", "uninstall.ps1", "audit-policy.ps1"))
    for name in SHARED:
        assert install[name] == uninstall[name] == audit[name], name
    for name in DATA_ROOT:
        assert install[name] == audit[name], name
    assert uninstall["Restore-RegistryValues"] == audit["Restore-RegistryValues"]


def test_native_arguments_survive_the_command_line(tmp_path):
    # sc.exe binPath= takes one argument with quotes inside; a data root may end in "\" or hold spaces.
    cases = ['"C:\\Program Files\\MCP Monitor\\bin\\monitor\\mcp-monitor.exe" service --root "C:\\Data\\x y" --local-port 8700',
             "name=MCP Monitor (8701)", "", "plain", "a\\\\b\\", 'tail\\"q', "C:\\dir with space\\", "/file:C:\\관리 폴더\\a.csv"]
    (tmp_path / "cases.json").write_text(json.dumps(cases), "utf-8")
    src = functions("install.ps1")
    script = tmp_path / "probe.ps1"
    script.write_text("\ufeff" + src["ConvertTo-CommandLineArg"] + "\n" + src["Invoke-Native"] + "\n"
                      "[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false\n"
                      f"$cases = [IO.File]::ReadAllText('{tmp_path / 'cases.json'}') | ConvertFrom-Json\n"
                      "Write-Output (@($cases | ForEach-Object { ConvertTo-CommandLineArg $_ }) -join ' ')\n"
                      "Write-Output (Invoke-Native 'cmd' @('/c', 'exit', '7'))\n", "utf-8")
    p = ps("-File", str(script))
    assert p.returncode == 0, p.stderr
    line, code = p.stdout.splitlines()
    argc = ctypes.c_int()
    shell32 = ctypes.windll.shell32
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
    argv = shell32.CommandLineToArgvW("x.exe " + line, ctypes.byref(argc))
    try:
        assert [argv[i] for i in range(1, argc.value)] == cases
    finally:
        ctypes.windll.kernel32.LocalFree(argv)
    assert code == "7"  # exit codes come back from System32 tools


def run_actions(name, tmp_path, setup, body):
    """Run the script's own functions and $Internal / $Conditions blocks (not the plan) in a harness.

    Only actions that touch nothing outside ``tmp_path`` are called here (never (admin) or a System32 tool).
    """
    p = ps("-Command", f"$ast = [System.Management.Automation.Language.Parser]::ParseFile('{INSTALL / name}', [ref]$null, [ref]$null); "
                       "$parts = @($ast.FindAll({ $args[0] -is [System.Management.Automation.Language.FunctionDefinitionAst] -or "
                       "($args[0] -is [System.Management.Automation.Language.AssignmentStatementAst] -and "
                       "$args[0].Left -is [System.Management.Automation.Language.VariableExpressionAst] -and "
                       "@('Internal', 'Conditions') -contains $args[0].Left.VariablePath.UserPath) }, $true) | ForEach-Object { $_.Extent.Text }); "
                       f"[IO.File]::WriteAllText('{tmp_path / 'parts.ps1'}', ($parts -join [Environment]::NewLine), [Text.UTF8Encoding]::new($true))")
    assert p.returncode == 0, p.stderr
    harness = tmp_path / "harness.ps1"
    harness.write_text("\ufeff[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false\n"
                       "Set-StrictMode -Version Latest\n$ErrorActionPreference = 'Stop'\n" + setup + "\n"
                       + (tmp_path / "parts.ps1").read_text("utf-8-sig") + "\n" + body + "\n", "utf-8")
    p = ps("-File", str(harness))
    assert p.returncode == 0, p.stdout + p.stderr
    return p.stdout.splitlines()


def test_install_runtime_actions(tmp_path):
    import http.server
    import threading

    class Ok(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200 if self.path == "/api/channel" else 404); self.end_headers()

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Ok)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    d = tmp_path / "d"
    state = {"installed_at": None, "version": "1.0.0", "local_port": 8700, "firewall": False,
             "registry_before": {AUDIT_KEY: None, PS_KEY: 0}, "audit_backup": None}
    (tmp_path / "state.json").write_text(json.dumps(state), "utf-8")
    try:
        out = run_actions("install.ps1", tmp_path,
                          f"$InstallDir = '{tmp_path / 'i'}'; $ServiceName = 'mcp-monitor-test-absent'; $FirewallRule = 'MCP Monitor test-absent (1)'; $BackupPath = '{d / 'data' / 'b.csv'}'",
                          f"Write-Output ([IO.Directory]::CreateDirectory('{d / 'logs'}').Exists -and [IO.Directory]::CreateDirectory('{d / 'data'}').Exists)\n"
                          f"$st = [IO.File]::ReadAllText('{tmp_path / 'state.json'}')\n"
                          f"Write-Output (& $Internal['(write-state)'] @{{ args = @('{d / 'data' / 'install-state.json'}', $st) }})\n"
                          "Write-Output (& $Internal['(check-os)'] @{ args = @() })\n"
                          f"Write-Output (& $Internal['(wait)'] @{{ args = @('http://127.0.0.1:{server.server_port}/api/channel', '5') }})\n"
                          f"try {{ & $Internal['(wait)'] @{{ args = @('http://127.0.0.1:{server.server_port}/missing', '1') }} }} catch {{ Write-Output \"wait-failed: $($_.Exception.Message)\" }}\n"
                          "Write-Output (& $Conditions['no_backup_yet'])\n"
                          "Write-Output (& $Conditions['service_exists'])\n"
                          "Write-Output (& $Conditions['firewall_rule_missing'])\n")
    finally:
        server.shutdown()
    assert out[0] == "True" and (d / "logs").is_dir() and (d / "data").is_dir()
    assert out[1] == "0"
    written = json.loads((d / "data" / "install-state.json").read_bytes())
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d", written.pop("installed_at"))
    assert written == {k: v for k, v in state.items() if k != "installed_at"}
    assert not (d / "data" / "install-state.json").read_bytes().startswith(b"\xef\xbb\xbf")
    # this PC is Windows 11 Home and the test install dir is outside Program Files: both warnings, then 0
    assert any("RDP" in line for line in out) and any("Program Files" in line for line in out)
    assert out[-6:] == ["0", "0", next(line for line in out if line.startswith("wait-failed: ")), "True", "False", "True"]


def test_uninstall_runtime_actions(tmp_path):
    inst, data = tmp_path / "i", tmp_path / "d"
    (inst / "bin").mkdir(parents=True); (inst / "bundle.json").write_text("{}", "utf-8")
    (data / "data").mkdir(parents=True); (data / "data" / "tamper-baseline.json").write_text("{}", "utf-8")
    (data / "data" / "mcp-monitor-data-root.json").write_text('{"product": "mcp-monitor"}', "utf-8")
    for user in ("alice", "bob"):
        (tmp_path / "Users" / user / "AppData" / "Local" / "mcp-monitor" / "notice-edge").mkdir(parents=True)
    (tmp_path / "Users" / "bob" / "AppData" / "Local" / "other").mkdir()
    out = run_actions("uninstall.ps1", tmp_path,
                      f"$InstallDir = '{inst}'; $DataRoot = '{data}'; $AuditBackup = '{data / 'data' / 'missing.csv'}'",
                      "Write-Output (& $Conditions['install_dir_is_bundle'])\n"
                      "Write-Output (& $Conditions['data_root_is_ours'])\n"
                      "Write-Output (& $Conditions['audit_backup_exists'])\n"
                      f"Write-Output (& $Internal['(remove)'] @{{ args = @('{inst}', '{data}', '{tmp_path / 'Users' / '*' / 'AppData' / 'Local' / 'mcp-monitor'}') }})\n"
                      "Write-Output (& $Conditions['install_dir_is_bundle'])\n"
                      "Write-Output (& $Internal['(reg-restore)'] @{ args = @() })\n")
    assert out == ["True", "True", "False", "0", "False", next(line for line in out if "레지스트리" in line), "0"]
    assert not inst.exists() and not data.exists()
    assert not list((tmp_path / "Users").glob("*/AppData/Local/mcp-monitor"))
    assert (tmp_path / "Users" / "bob" / "AppData" / "Local" / "other").is_dir()


def test_install_plan_default(bundle, tmp_path):
    inst, data = str(tmp_path / "inst"), str(tmp_path / "data")
    plan = dry("install.ps1", "-Source", str(bundle), "-InstallDir", inst, "-DataRoot", data)
    assert [s["id"] for s in plan["steps"]] == [
        "require_admin", "check_os", "stop_existing", "copy_bundle", "secure_data_root", "audit_backup", "audit_policy_success", "audit_policy_failure", "registry_cmdline", "registry_scriptblock",
        "security_log_size", "powershell_log_size", "service_install", "service_description", "service_failure",
        "service_failureflag", "install_state", "service_start", "wait_ready"]
    # C1: the ACL is built from scratch and verified inside the step (icacls /grant:r kept other ACEs)
    assert (step(plan, "secure_data_root")["cmd"], step(plan, "secure_data_root")["args"]) == ("(secure-data-root)", [data])
    assert not [s for s in plan["steps"] if s["cmd"] == "icacls"]
    subs = [a for a in step(plan, "audit_policy_success")["args"] if a.startswith("/subcategory:")][0]
    assert len(GUID.findall(subs)) == 5
    svc = step(plan, "service_install")["args"]
    assert svc[:2] == ["create", "mcp-monitor"] and plan["service_mode"] == "create"
    assert svc[svc.index("start=") + 1] == "delayed-auto" and svc[svc.index("obj=") + 1] == "LocalSystem"
    assert svc[svc.index("binPath=") + 1] == f'"{inst}\\runtime\\python.exe" -m app service --root "{data}" --local-port 8700 --external-port 8701'
    assert step(plan, "service_failure")["args"] == ["failure", "mcp-monitor", "reset=", "86400", "actions=", "restart/5000/restart/10000/restart/60000"]


def test_install_plan_details(bundle, tmp_path):
    inst, data = str(tmp_path / "inst"), str(tmp_path / "data")
    plan = dry("install.ps1", "-Source", str(bundle), "-InstallDir", inst, "-DataRoot", data)
    assert {k: plan[k] for k in ("script", "version", "layout", "install_dir", "data_root")} == {
        "script": "install", "version": "1.0.0", "layout": "runtime", "install_dir": inst, "data_root": data}
    assert step(plan, "require_admin")["cmd"] == "(admin)" and plan["steps"][0]["id"] == "require_admin"
    stop = step(plan, "stop_existing")
    assert (stop["cmd"], stop["args"], stop["ok"], stop["when"]) == ("sc.exe", ["stop", "mcp-monitor"], [0, 1062], "service_exists")
    copy = step(plan, "copy_bundle")
    assert copy["cmd"] == "robocopy" and copy["args"][:3] == [str(bundle), inst, "/MIR"] and copy["ok"] == list(range(8))
    # Full destination paths: a bare "/XD data" would also skip any nested "data" folder in the bundle.
    xd = copy["args"].index("/XD")
    assert copy["args"][xd + 1:xd + 4] == [f"{inst}\\logs", f"{inst}\\data", f"{inst}\\scripts"]
    backup = step(plan, "audit_backup")
    assert backup["args"] == ["/backup", f"/file:{data}\\data\\auditpol-backup.csv"] and backup["when"] == "no_backup_yet"
    fail = [a for a in step(plan, "audit_policy_failure")["args"] if a.startswith("/subcategory:")][0]
    assert GUID.findall(fail) == ["{0CCE9215-69AE-11D9-BED3-505054503030}", "{0CCE921C-69AE-11D9-BED3-505054503030}"]
    assert step(plan, "audit_policy_failure")["args"][-1] == "/failure:enable"
    assert step(plan, "registry_cmdline")["args"] == [
        "add", r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System\Audit", "/v",
        "ProcessCreationIncludeCmdLine_Enabled", "/t", "REG_DWORD", "/d", "1", "/f"]
    assert step(plan, "security_log_size")["args"] == ["sl", "Security", "/ms:268435456"]
    assert step(plan, "powershell_log_size")["args"] == ["sl", "Microsoft-Windows-PowerShell/Operational", "/ms:67108864"]
    svc = step(plan, "service_install")["args"]
    assert svc[svc.index("DisplayName=") + 1] == "MCP Monitor"
    # Korean survives the CP949 console (F13): the description is the service host's own text.
    assert step(plan, "service_description")["args"] == ["description", "mcp-monitor", DESCRIPTION]
    assert step(plan, "service_failureflag")["args"] == ["failureflag", "mcp-monitor", "1"]
    assert "firewall" not in [s["id"] for s in plan["steps"]]  # spec §2 #6: closed unless -OpenFirewall
    assert step(plan, "service_start")["ok"] == [0, 1056]
    assert step(plan, "wait_ready")["args"] == ["http://127.0.0.1:8700/api/channel", "30"]
    path, state = step(plan, "install_state")["args"]
    assert path == f"{data}\\data\\install-state.json"
    state = json.loads(state)
    assert state["installed_at"] is None and state["firewall"] is False
    assert {k: state[k] for k in ("version", "layout", "install_dir", "data_root", "local_port", "external_port", "audit_backup")} == {
        "version": "1.0.0", "layout": "runtime", "install_dir": inst, "data_root": data, "local_port": 8700,
        "external_port": 8701, "audit_backup": f"{data}\\data\\auditpol-backup.csv"}
    assert set(state["registry_before"]) == {AUDIT_KEY, PS_KEY}


def test_install_plan_open_firewall_and_skip_audit(bundle, tmp_path):
    plan = dry("install.ps1", "-Source", str(bundle), "-InstallDir", str(tmp_path / "i"), "-DataRoot", str(tmp_path / "d"),
               "-OpenFirewall", "-SkipAuditPolicy", "-ExternalPort", "9701")
    ids = [s["id"] for s in plan["steps"]]
    assert "audit_policy_success" not in ids and "registry_cmdline" not in ids
    assert not {"audit_backup", "audit_policy_failure", "registry_scriptblock", "security_log_size", "powershell_log_size"} & set(ids)
    assert step(plan, "firewall")["args"] == ["advfirewall", "firewall", "add", "rule", "name=MCP Monitor (9701)", "dir=in",
                                              "action=allow", "protocol=TCP", "localport=9701", "profile=domain,private"]
    assert ids.index("firewall") == ids.index("service_failureflag") + 1
    assert step(plan, "firewall")["when"] == "firewall_rule_missing"  # no duplicate rule on a reinstall
    state =json.loads(step(plan, "install_state")["args"][1])
    assert state["firewall"] is True and state["external_port"] == 9701
    assert state["registry_before"] == {} and state["audit_backup"] is None


def test_install_plan_pyinstaller_layout_and_ports(bundle, tmp_path):
    (bundle / "bundle.json").write_text(json.dumps({"layout": "pyinstaller", "version": "1.0.0", "python": "3.15.2",
                                                    "built_at": "x", "commit": "y"}), "utf-8")
    inst, data = str(tmp_path / "설치 폴더"), str(tmp_path / "데이터")
    plan = dry("install.ps1", "-Source", str(bundle), "-InstallDir", inst, "-DataRoot", data,
               "-LocalPort", "9700", "-ExternalPort", "9701")
    assert plan["layout"] == "pyinstaller" and plan["install_dir"] == inst and plan["data_root"] == data
    svc = step(plan, "service_install")["args"]
    assert svc[svc.index("binPath=") + 1] == f'"{inst}\\bin\\monitor\\mcp-monitor.exe" service --root "{data}" --local-port 9700 --external-port 9701'
    assert step(plan, "service_description")["args"][2] == DESCRIPTION.replace("8700", "9700").replace("8701", "9701")
    assert step(plan, "wait_ready")["args"][0] == "http://127.0.0.1:9700/api/channel"


def test_reinstall_keeps_the_first_registry_values_and_backup(bundle, tmp_path):
    # A second install must not record our own values (1) as "before", nor back up our own audit policy.
    data = tmp_path / "d"
    (data / "data").mkdir(parents=True)
    (data / "data" / "auditpol-backup.csv").write_text("x", "utf-8")
    (data / "data" / "install-state.json").write_text(json.dumps({
        "registry_before": {AUDIT_KEY: None, PS_KEY: 0}, "audit_backup": str(data / "data" / "auditpol-backup.csv"),
        "version": "1.0.0", "external_port": 8701}), "utf-8")
    plan = dry("install.ps1", "-Source", str(bundle), "-InstallDir", str(tmp_path / "i"), "-DataRoot", str(data))
    state = json.loads(step(plan, "install_state")["args"][1])
    assert state["registry_before"] == {AUDIT_KEY: None, PS_KEY: 0}
    assert step(plan, "audit_backup")["when"] == "no_backup_yet"


@pytest.mark.parametrize("case", ["no_bundle_json", "same_dir", "install_inside_source", "foreign_install_dir", "bad_layout", "same_ports"])
def test_install_argument_errors_exit_2(bundle, tmp_path, case):
    inst = tmp_path / "i"
    args = ["-Source", str(bundle), "-InstallDir", str(inst), "-DataRoot", str(tmp_path / "d")]
    if case == "no_bundle_json":
        (bundle / "bundle.json").unlink()
    elif case == "same_dir":
        args[3] = str(bundle)
    elif case == "install_inside_source":
        args[3] = str(bundle / "sub")
    elif case == "foreign_install_dir":
        # /MIR would delete whatever else is there: only an empty folder or an earlier install is accepted.
        inst.mkdir(); (inst / "keep.txt").write_text("x", "utf-8")
    elif case == "bad_layout":
        (bundle / "bundle.json").write_text(json.dumps({"layout": "zip", "version": "1.0.0"}), "utf-8")
    elif case == "same_ports":
        args += ["-LocalPort", "8800", "-ExternalPort", "8800"]
    p = ps("-File", str(INSTALL / "install.ps1"), "-DryRun", *args)
    assert p.returncode == 2 and p.stdout.strip() == "", p.stdout + p.stderr
    assert p.stderr.strip()


def test_install_accepts_an_earlier_install_dir(bundle, tmp_path):
    inst = tmp_path / "i"
    inst.mkdir(); (inst / "bundle.json").write_text("{}", "utf-8"); (inst / "old.txt").write_text("x", "utf-8")
    assert dry("install.ps1", "-Source", str(bundle), "-InstallDir", str(inst), "-DataRoot", str(tmp_path / "d"))["steps"]


def test_install_refuses_without_admin(bundle, tmp_path):
    p = real_run("install.ps1", "-Source", str(bundle), "-InstallDir", str(tmp_path / "i"), "-DataRoot", str(tmp_path / "d"))
    assert p.returncode == 1 and "관리자 권한" in (p.stdout + p.stderr)
    assert "관리자 권한(Administrator)으로 PowerShell을 열고 다시 실행하세요." in p.stdout
    assert not (tmp_path / "i").exists() and not (tmp_path / "d").exists()


def test_uninstall_plan_keeps_data_by_default(tmp_path):
    base = ["-InstallDir", str(tmp_path / "i"), "-DataRoot", str(tmp_path / "d")]
    assert [s["id"] for s in dry("uninstall.ps1", *base)["steps"]] == [
        "require_admin", "stop_service", "delete_service", "firewall_delete", "remove_install_dir"]
    full = [s["id"] for s in dry("uninstall.ps1", *base, "-RemoveData", "-RestoreAuditPolicy")["steps"]]
    assert full == ["require_admin", "stop_service", "delete_service", "firewall_delete", "restore_audit_policy",
                    "restore_registry", "remove_install_dir", "remove_data", "remove_edge_profiles"]


def test_uninstall_plan_details_without_state(tmp_path):
    inst, data = str(tmp_path / "i"), str(tmp_path / "d")
    plan = dry("uninstall.ps1", "-InstallDir", inst, "-DataRoot", data, "-RemoveData", "-RestoreAuditPolicy")
    assert (plan["script"], plan["install_dir"], plan["data_root"], plan["version"]) == ("uninstall", inst, data, None)
    assert step(plan, "stop_service")["ok"] == [0, 1060, 1062]
    assert (step(plan, "delete_service")["args"], step(plan, "delete_service")["ok"]) == (["delete", "mcp-monitor"], [0, 1060])
    fw = step(plan, "firewall_delete")
    assert fw["args"] == ["advfirewall", "firewall", "delete", "rule", "name=MCP Monitor (8701)"] and fw["ok"] == [0, 1]
    assert step(plan, "restore_audit_policy")["args"] == ["/restore", f"/file:{data}\\data\\auditpol-backup.csv"]
    assert step(plan, "restore_registry")["args"] == []
    assert step(plan, "remove_install_dir")["args"] == [inst]
    assert step(plan, "remove_data")["args"] == [data]
    edge = step(plan, "remove_edge_profiles")["args"]
    assert len(edge) == 1 and edge[0].endswith(r"\*\AppData\Local\mcp-monitor")


def test_uninstall_plan_reads_the_install_state(tmp_path):
    data = tmp_path / "d"
    (data / "data").mkdir(parents=True)
    backup = str(data / "data" / "auditpol-backup.csv")
    (data / "data" / "install-state.json").write_text(json.dumps({
        "version": "1.0.0", "layout": "pyinstaller", "external_port": 9701, "firewall": True,
        "registry_before": {AUDIT_KEY: None, PS_KEY: 0}, "audit_backup": backup}), "utf-8")
    # The Task 7 tamper baseline lives in the data root: -RemoveData removes the whole root with it.
    (data / "data" / "tamper-baseline.json").write_text("{}", "utf-8")
    plan = dry("uninstall.ps1", "-InstallDir", str(tmp_path / "i"), "-DataRoot", str(data), "-RemoveData", "-RestoreAuditPolicy")
    assert (plan["version"], plan["layout"]) == ("1.0.0", "pyinstaller")
    assert step(plan, "firewall_delete")["args"][-1] == "name=MCP Monitor (9701)"
    assert step(plan, "restore_audit_policy")["args"] == ["/restore", f"/file:{backup}"]
    assert step(plan, "restore_registry")["args"] == [f"{AUDIT_KEY}=null", f"{PS_KEY}=0"]
    removed = Path(step(plan, "remove_data")["args"][0])
    assert removed == data and (data / "data" / "tamper-baseline.json").is_relative_to(removed)


def test_uninstall_refuses_without_admin(tmp_path):
    inst, data = tmp_path / "i", tmp_path / "d"
    inst.mkdir(); (inst / "bundle.json").write_text("{}", "utf-8")
    (data / "data").mkdir(parents=True); (data / "data" / "tamper-baseline.json").write_text("{}", "utf-8")
    p = real_run("uninstall.ps1", "-InstallDir", str(inst), "-DataRoot", str(data), "-RemoveData", "-RestoreAuditPolicy")
    assert p.returncode == 1 and "관리자 권한(Administrator)으로 PowerShell을 열고 다시 실행하세요." in p.stdout
    assert (inst / "bundle.json").is_file() and (data / "data" / "tamper-baseline.json").is_file()


AUDIT_STEPS = ["audit_backup", "audit_policy_success", "audit_policy_failure", "registry_cmdline", "registry_scriptblock",
               "security_log_size", "powershell_log_size"]


def test_audit_policy_script_plan(tmp_path):
    plan = dry("audit-policy.ps1", "-Enable", "-DataRoot", str(tmp_path / "d"))
    assert [s["id"] for s in plan["steps"]] == ["require_admin", "secure_data_root", "record_registry", *AUDIT_STEPS]


def test_audit_policy_enable_matches_install(bundle, tmp_path):
    data = str(tmp_path / "d")
    enable = dry("audit-policy.ps1", "-Enable", "-DataRoot", data)
    install = dry("install.ps1", "-Source", str(bundle), "-InstallDir", str(tmp_path / "i"), "-DataRoot", data)
    assert enable["script"] == "audit-policy" and enable["steps"][0]["id"] == "require_admin"
    assert enable["steps"][3:] == [step(install, sid) for sid in AUDIT_STEPS]
    # finding 11: before an install the data root is made here, with the install's ACL step
    assert step(enable, "secure_data_root") == step(install, "secure_data_root")


def test_audit_policy_enable_records_the_registry_before_it_changes(tmp_path):
    data = tmp_path / "d"
    plan = dry("audit-policy.ps1", "-Enable", "-DataRoot", str(data))
    rec = step(plan, "record_registry")
    assert rec["cmd"] == "(write-json)" and rec["when"] == "no_registry_record_yet"
    path, record = rec["args"]
    assert path == f"{data}\\data\\audit-policy-state.json"
    record = json.loads(record)
    assert set(record["registry_before"]) == {AUDIT_KEY, PS_KEY} and record["audit_backup"] == f"{data}\\data\\auditpol-backup.csv"
    # install.ps1 (and uninstall / -Restore) take those values over when there is no install state yet
    (data / "data").mkdir(parents=True)
    (data / "data" / "mcp-monitor-data-root.json").write_text('{"product": "mcp-monitor"}', "utf-8")
    (data / "data" / "audit-policy-state.json").write_text(json.dumps({"registry_before": {AUDIT_KEY: None, PS_KEY: 0}}), "utf-8")
    assert step(dry("uninstall.ps1", "-InstallDir", str(tmp_path / "i"), "-DataRoot", str(data), "-RestoreAuditPolicy"),
                "restore_registry")["args"] == [f"{AUDIT_KEY}=null", f"{PS_KEY}=0"]
    assert step(dry("audit-policy.ps1", "-Restore", str(data / "data" / "audit-policy-state.json"), "-DataRoot", str(data)),
                "restore_registry")["args"] == [f"{AUDIT_KEY}=null", f"{PS_KEY}=0"]


def test_restore_registry_refuses_values_install_never_set(tmp_path):
    # A state file must not choose which registry values an elevated uninstall writes (C1 follow-up).
    out = run_actions("uninstall.ps1", tmp_path, "",
                      "try { & $Internal['(reg-restore)'] @{ args = @('HKLM\\SOFTWARE\\Evil\\Run=1') } } catch { Write-Output \"refused: $($_.Exception.Message)\" }\n"
                      f"try {{ & $Internal['(reg-restore)'] @{{ args = @('{AUDIT_KEY}=1 /f') }} }} catch {{ Write-Output \"refused: $($_.Exception.Message)\" }}\n")
    assert len(out) == 2 and all(line.startswith("refused: 알 수 없는 레지스트리 값") for line in out), out


def test_audit_policy_restore_plan(tmp_path):
    backup = tmp_path / "백업.csv"
    backup.write_text("x", "utf-8")
    plan = dry("audit-policy.ps1", "-Restore", str(backup), "-DataRoot", str(tmp_path / "d"))
    assert [s["id"] for s in plan["steps"]] == ["require_admin", "restore_audit_policy", "restore_registry"]
    assert step(plan, "restore_audit_policy")["args"] == ["/restore", f"/file:{backup}"]


@pytest.mark.parametrize("args", [[], ["-Enable", "-Restore", "x.csv"], ["-Restore", "missing.csv"]])
def test_audit_policy_argument_errors_exit_2(tmp_path, args):
    p = ps("-File", str(INSTALL / "audit-policy.ps1"), "-DryRun", *[str(tmp_path / a) if a.endswith(".csv") else a for a in args])
    assert p.returncode == 2 and p.stdout.strip() == "", p.stdout + p.stderr


def test_audit_policy_refuses_without_admin(tmp_path):
    p = real_run("audit-policy.ps1", "-Enable", "-DataRoot", str(tmp_path / "d"))
    assert p.returncode == 1 and "관리자 권한(Administrator)으로 PowerShell을 열고 다시 실행하세요." in p.stdout
    assert not (tmp_path / "d").exists()


# -- the data root (plan review C1, I3) -----------------------------------------------------------

EVERYONE = "S-1-1-0"
AUTHENTICATED_USERS = "S-1-5-11"


def me_sid():
    p = ps("-Command", "[Security.Principal.WindowsIdentity]::GetCurrent().User.Value")
    assert p.returncode == 0, p.stderr
    return p.stdout.strip()


def junction(link, target):
    import _winapi
    target.mkdir(parents=True, exist_ok=True)
    _winapi.CreateJunction(str(target), str(link))  # no admin needed (unlike a symbolic link)


def sddl(path):
    p = ps("-Command", f"(Get-Acl -LiteralPath '{path}').Sddl")
    assert p.returncode == 0, p.stderr
    return p.stdout.strip()


def test_install_refuses_a_data_root_someone_else_filled(bundle, tmp_path):
    # C1: a folder made before the install (C:\ProgramData lets any user do that) is taken over only when
    # it is empty or an earlier data root, owned by SYSTEM/Administrators/the installer, without links.
    cases = {}
    foreign = tmp_path / "foreign"
    (foreign / "scripts").mkdir(parents=True); (foreign / "scripts" / "a.ps1").write_text("x", "utf-8")
    cases["not empty, no marker"] = foreign
    linked = tmp_path / "linked"
    (linked / "data").mkdir(parents=True); (linked / "data" / "install-state.json").write_text("{}", "utf-8")
    junction(linked / "scripts", tmp_path / "elsewhere")
    cases["junction inside"] = linked
    deep = tmp_path / "deep"
    (deep / "data").mkdir(parents=True); (deep / "data" / "mcp-monitor-data-root.json").write_text("{}", "utf-8")
    (deep / "logs" / "x").mkdir(parents=True)
    junction(deep / "logs" / "x" / "y", tmp_path / "elsewhere2")
    cases["junction deep inside"] = deep
    root_link = tmp_path / "rootlink"
    junction(root_link, tmp_path / "target")
    cases["root is a junction"] = root_link
    a_file = tmp_path / "file"; a_file.write_text("x", "utf-8")
    cases["a file"] = a_file
    for name, root in cases.items():
        p = ps("-File", str(INSTALL / "install.ps1"), "-DryRun", "-Source", str(bundle), "-InstallDir", str(tmp_path / "i"),
               "-DataRoot", str(root))
        assert p.returncode == 2 and p.stdout.strip() == "", (name, p.stdout + p.stderr)
        assert "-DataRoot" in p.stderr, (name, p.stderr)


def test_install_accepts_an_empty_or_earlier_data_root(bundle, tmp_path):
    empty = tmp_path / "empty"; empty.mkdir()
    earlier = tmp_path / "earlier"
    (earlier / "logs").mkdir(parents=True); (earlier / "logs" / "2026-11-01.jsonl").write_text("{}\n", "utf-8")
    (earlier / "data").mkdir(); (earlier / "data" / "mcp-monitor-data-root.json").write_text("{}", "utf-8")
    for root in (empty, earlier, tmp_path / "missing"):
        plan = dry("install.ps1", "-Source", str(bundle), "-InstallDir", str(tmp_path / "i"), "-DataRoot", str(root))
        assert step(plan, "secure_data_root")["args"] == [str(root)]


@pytest.mark.parametrize("case", ["inside_install", "contains_install", "same_as_install", "inside_source",
                                  "drive_root", "other_drive_root", "program_data", "users", "inside_windows"])
def test_install_refuses_unsafe_data_root_paths(bundle, tmp_path, case):
    # I3: robocopy /MIR would delete a data root inside the install folder; uninstall -RemoveData deletes
    # the data root whole, so it is never a drive root or a system folder.
    inst = tmp_path / "i"
    root = {
        "inside_install": str(inst / "var"), "contains_install": str(tmp_path), "same_as_install": str(inst),
        "inside_source": str(bundle / "data"), "drive_root": os.environ["SystemDrive"] + "\\", "other_drive_root": "Q:\\",
        "program_data": os.environ["ProgramData"], "users": str(Path(os.environ["PUBLIC"]).parent),
        "inside_windows": str(Path(os.environ["SystemRoot"]) / "Temp" / "mcp"),
    }[case]
    p = ps("-File", str(INSTALL / "install.ps1"), "-DryRun", "-Source", str(bundle), "-InstallDir", str(inst), "-DataRoot", root)
    assert p.returncode == 2 and p.stdout.strip() == "", p.stdout + p.stderr
    assert "-DataRoot" in p.stderr


def test_data_root_problem_names_a_foreign_owner(tmp_path):
    root = tmp_path / "r"
    (root / "data").mkdir(parents=True); (root / "data" / "mcp-monitor-data-root.json").write_text("{}", "utf-8")
    me = me_sid()
    out = run_actions("install.ps1", tmp_path, "",
                      f"Write-Output \"[$(Get-DataRootProblem '{root}' @('S-1-5-18', 'S-1-5-32-544', '{me}'))]\"\n"
                      f"Write-Output (Get-DataRootProblem '{root}' @('S-1-5-18', 'S-1-5-32-544'))\n"
                      f"Write-Output \"[$(Get-DataRootProblem '{tmp_path / 'missing'}' @())]\"\n")
    assert out[0] == "[]" and out[2] == "[]"
    assert me in out[1] and "소유자" in out[1]


def test_initialize_data_root_rebuilds_the_acl_from_scratch(tmp_path):
    """C1 on a scratch folder (no admin: this account owns the folder and stands in for Administrators):
    an earlier data root whose root and a file carry an extra Everyone read ACE (a right that does not get
    the folder refused) comes out with exactly the given SIDs, inheritance off at the root and nothing
    explicit below, and the read-back check passes; an ACE added afterwards is caught by that check."""
    root = tmp_path / "MCP Monitor"
    (root / "data").mkdir(parents=True)
    (root / "data" / "install-state.json").write_text("{}", "utf-8")
    log = root / "logs" / "2026-11-01.jsonl"
    log.parent.mkdir(); log.write_text("{}\n", "utf-8")
    subprocess.run([ICACLS, str(root), "/grant", f"*{EVERYONE}:(OI)(CI)RX"], check=True, capture_output=True)
    subprocess.run([ICACLS, str(log), "/grant", f"*{EVERYONE}:R"], check=True, capture_output=True)
    assert ";;;WD)" in sddl(root) and ";;;WD)" in sddl(log)  # WD = Everyone
    me = me_sid()
    sids = f"@('S-1-5-18', 'S-1-5-32-544', '{me}')"
    out = run_actions("install.ps1", tmp_path, "",
                      f"Initialize-DataRoot '{root}' '{me}' {sids} {sids} 'install'\n"
                      f"Write-Output \"problems=$(@(Get-DataRootAclProblems '{root}' '{me}' {sids}).Count)\"\n"
                      f"& '{ICACLS}' '{log}' /grant '*{EVERYONE}:R' | Out-Null\n"
                      f"Write-Output (@(Get-DataRootAclProblems '{root}' '{me}' {sids}) -join '|')\n")
    assert out[0] == "problems=0", out
    assert EVERYONE in out[1] and "2026-11-01.jsonl" in out[1], out  # the check reads the ACL back
    subprocess.run([ICACLS, str(log), "/remove", f"*{EVERYONE}"], check=True, capture_output=True)
    for item in [root, *root.rglob("*")]:
        s = sddl(item)
        assert "WD)" not in s and s.startswith(f"O:{me}"), (item, s)
    assert "D:P" in sddl(root)  # protected: nothing inherited from the parent folder
    assert all((root / d).is_dir() for d in ("logs", "data", "scripts"))
    marker = json.loads((root / "data" / "mcp-monitor-data-root.json").read_text("utf-8"))
    assert marker["product"] == "mcp-monitor" and marker["created_by"] == "install"


def test_initialize_data_root_creates_a_new_root(tmp_path):
    root = tmp_path / "new" / "MCP Monitor"
    me = me_sid()
    sids = f"@('S-1-5-18', 'S-1-5-32-544', '{me}')"
    out = run_actions("install.ps1", tmp_path, "",
                      f"Initialize-DataRoot '{root}' '{me}' {sids} {sids} 'audit-policy'\n"
                      f"Write-Output (@(Get-DataRootAclProblems '{root}' '{me}' {sids}).Count)\n")
    assert out == ["0"]
    assert sorted(p.name for p in root.iterdir()) == ["data", "logs", "scripts"]
    assert json.loads((root / "data" / "mcp-monitor-data-root.json").read_text("utf-8"))["created_by"] == "audit-policy"
    # re-review 2: the missing parent is made with the root's ACL too (protected, the given SIDs only)
    for folder in (tmp_path / "new", root):
        s = sddl(folder)
        assert s.startswith(f"O:{me}") and "D:P" in s and "WD)" not in s and "AU)" not in s, (folder, s)


def test_initialize_data_root_refuses_a_foreign_folder(tmp_path):
    root = tmp_path / "r"
    (root / "scripts").mkdir(parents=True)
    me = me_sid()
    sids = f"@('S-1-5-18', 'S-1-5-32-544', '{me}')"
    before = sddl(root)
    out = run_actions("install.ps1", tmp_path, "",
                      f"try {{ Initialize-DataRoot '{root}' '{me}' {sids} {sids} 'install' }} catch {{ Write-Output \"refused: $($_.Exception.Message)\" }}\n")
    assert len(out) == 1 and out[0].startswith("refused: ") and "MCP Monitor" in out[0]
    assert sddl(root) == before and not (root / "data").exists()  # nothing changed


@pytest.mark.parametrize("case", ["drive_root", "program_data", "users", "inside_install"])
def test_uninstall_refuses_to_remove_unsafe_roots(tmp_path, case):
    inst = tmp_path / "i"
    args = {"drive_root": ["-DataRoot", os.environ["SystemDrive"] + "\\", "-RemoveData"],
            "program_data": ["-DataRoot", os.environ["ProgramData"], "-RemoveData"],
            "users": ["-DataRoot", str(Path(os.environ["PUBLIC"]).parent), "-RemoveData"],
            # without -RemoveData, removing the install folder must not take a data root inside it along
            "inside_install": ["-DataRoot", str(inst / "var")]}[case]
    p = ps("-File", str(INSTALL / "uninstall.ps1"), "-DryRun", "-InstallDir", str(inst), *args)
    assert p.returncode == 2 and p.stdout.strip() == "", p.stdout + p.stderr


def test_uninstall_removes_only_a_marked_data_root(tmp_path):
    # I3: a bare data\ folder is not enough (D:\ with a D:\data folder would have been deleted whole)
    bare, marked, legacy = tmp_path / "bare", tmp_path / "marked", tmp_path / "legacy"
    for r in (bare, marked, legacy):
        (r / "data").mkdir(parents=True)
    (marked / "data" / "mcp-monitor-data-root.json").write_text("{}", "utf-8")
    (legacy / "data" / "install-state.json").write_text("{}", "utf-8")  # an install from before the marker
    drive = os.environ["SystemDrive"] + "\\"
    body = "".join(f"$DataRoot = '{r}'; Write-Output (& $Conditions['data_root_is_ours'])\n" for r in (bare, marked, legacy, drive))
    assert run_actions("uninstall.ps1", tmp_path, "", body) == ["False", "True", "True", "False"]


def test_audit_policy_enable_refuses_unsafe_data_roots(tmp_path):
    foreign = tmp_path / "foreign"
    (foreign / "x").mkdir(parents=True)
    for root in (os.environ["SystemDrive"] + "\\", str(foreign)):
        p = ps("-File", str(INSTALL / "audit-policy.ps1"), "-DryRun", "-Enable", "-DataRoot", root)
        assert p.returncode == 2 and p.stdout.strip() == "", p.stdout + p.stderr


# -- re-review (d510b97..1a11c2c) items 1-4 --------------------------------------------------------

def test_initialize_data_root_refuses_a_root_made_just_before_it(tmp_path):
    """Re-review 1: a folder another account creates between the first check and the creation keeps that
    account's owner and ACL, and CreateDirectory leaves an existing folder as it is: the folder is checked as
    found, before Set-RootAcl would make it look like ours, and refused. Here the folder is made (inherited
    ACL) by a wrapper around the creation, the moment the attacker of the review aims for."""
    root = tmp_path / "MCP Monitor"
    me = me_sid()
    sids = f"@('S-1-5-18', 'S-1-5-32-544', '{me}')"
    out = run_actions("install.ps1", tmp_path, "",
                      "$create = ${function:New-ProtectedDirectory}\n"
                      "function New-ProtectedDirectory([string]$Path, [string]$Owner, [string[]]$Sids) {\n"
                      "    [void][IO.Directory]::CreateDirectory($Path); & $create $Path $Owner $Sids }\n"
                      f"try {{ Initialize-DataRoot '{root}' '{me}' {sids} {sids} 'install'; Write-Output 'accepted' }}"
                      " catch { Write-Output \"refused: $($_.Exception.Message)\" }\n")
    assert len(out) == 1 and out[0].startswith("refused: ") and "먼저 만들었습니다" in out[0], out
    assert "D:P" not in sddl(root) and not (root / "data").exists()  # left as found: not taken over


def test_install_refuses_a_data_root_below_a_folder_others_may_rename(bundle, tmp_path):
    """Re-review 2: D:\\apps inherits Authenticated Users:(M) from a data volume's root; a user renames it while
    the service is stopped and puts his own tree at the data root's path. Inherit-only ACEs (they apply below,
    where the root is protected) do not count."""
    apps = tmp_path / "apps"
    apps.mkdir()
    root = str(apps / "MCP Monitor")
    install = ["-File", str(INSTALL / "install.ps1"), "-DryRun", "-Source", str(bundle), "-InstallDir", str(tmp_path / "i"), "-DataRoot", root]
    enable = ["-File", str(INSTALL / "audit-policy.ps1"), "-DryRun", "-Enable", "-DataRoot", root]
    subprocess.run([ICACLS, str(apps), "/grant", f"*{AUTHENTICATED_USERS}:(OI)(CI)M"], check=True, capture_output=True)
    for args in (install, enable):
        p = ps(*args)
        assert p.returncode == 2 and p.stdout.strip() == "", p.stdout + p.stderr
        assert "-DataRoot" in p.stderr and str(apps) in p.stderr and AUTHENTICATED_USERS in p.stderr, p.stderr
    subprocess.run([ICACLS, str(apps), "/remove:g", f"*{AUTHENTICATED_USERS}"], check=True, capture_output=True)
    subprocess.run([ICACLS, str(apps), "/grant", f"*{AUTHENTICATED_USERS}:(OI)(CI)(IO)M"], check=True, capture_output=True)
    for args in (install, enable):
        p = ps(*args)
        assert p.returncode == 0, p.stdout + p.stderr


def test_ancestor_check_passes_the_default_and_drive_level_roots(tmp_path):
    # The default C:\ProgramData\MCP Monitor (Users may add folders to ProgramData, not delete or rename them)
    # and a folder directly under each local drive root with this PC's real drive root ACLs: C:\ (Authenticated
    # Users may add folders) and a data volume's root (Authenticated Users Modify on the root itself, which can
    # be neither deleted nor renamed; no delete-child, permission or owner rights). Read-only on this PC.
    letters = run_actions("install.ps1", tmp_path, "", "Write-Output ((Get-LocalDriveLetters) -join ',')")[0].split(",")
    assert os.environ["SystemDrive"][0].upper() in letters
    body = f"Write-Output \"[$(Get-AncestorProblem '{os.environ['ProgramData']}\\MCP Monitor' @('S-1-5-18', 'S-1-5-32-544'))]\"\n"
    body += "".join(f"Write-Output \"[$(Get-AncestorProblem '{x}:\\MCP Monitor' @('S-1-5-18', 'S-1-5-32-544'))]\"\n" for x in letters)
    assert run_actions("install.ps1", tmp_path, "", body) == ["[]"] * (1 + len(letters))


@pytest.mark.parametrize("grant, refused", [("(DC)", True), ("(WDAC)", True), ("(WO)", True), ("F", True),
                                            ("M", False), ("(AD)", False), ("(OI)(CI)(IO)M", False)])
def test_ancestor_check_includes_the_drive_root(tmp_path, grant, refused):
    """Fix wave: a drive root that lets a non-admin delete its children (FILE_DELETE_CHILD) or change its
    permissions or owner lets him rename the data root away at any time, without a handle. The drive root's
    ACL is stood in for by a scratch folder (a real drive root's ACL must not change); DELETE on the drive
    root itself (a data volume's default Authenticated Users:(M)) does not count."""
    fake = tmp_path / "fake-drive-root"
    fake.mkdir()
    subprocess.run([ICACLS, str(fake), "/grant", f"*{AUTHENTICATED_USERS}:{grant}"], check=True, capture_output=True)
    drive = str(tmp_path)[:3]
    sids = f"@('S-1-5-18', 'S-1-5-32-544', '{me_sid()}')"
    out = run_actions("install.ps1", tmp_path, "",
                      "$real = ${function:Get-FolderAcl}\n"
                      f"function Get-FolderAcl([string]$Path) {{ if ($Path -eq '{drive}') {{ $Path = '{fake}' }}; & $real $Path }}\n"
                      f"Write-Output \"[$(Get-AncestorProblem '{tmp_path / 'MCP Monitor'}' {sids})]\"\n")
    assert len(out) == 1, out
    if refused:
        assert drive in out[0] and AUTHENTICATED_USERS in out[0] and "드라이브" in out[0], out
    else:
        assert out == ["[]"]


def granted(path, grant):
    subprocess.run([ICACLS, str(path), "/grant", f"*{AUTHENTICATED_USERS}:{grant}"], check=True, capture_output=True)


@pytest.mark.parametrize("case", ["inherited_modify", "write_dac", "write_owner", "delete_on_a_file", "write_on_a_script"])
def test_existing_data_root_others_may_delete_or_rechmod_is_refused(bundle, tmp_path, case):
    """Fix wave: an existing data root was accepted after checking only owners and contents. A standard user
    opens it (or an item in it) with DELETE, WRITE_DAC, WRITE_OWNER or write access before the install and
    keeps the handle: after Set-RootAcl he renames the root through that handle and puts his own tree (config.db,
    scripts) where the SYSTEM service looks. Such a root is refused before its ACL changes, with advice to delete
    it and let the install create it; nothing is changed."""
    if case == "inherited_modify":
        # an admin pre-creates an empty D:\MCP Monitor that inherits Authenticated Users:(M) from D:\
        vol = tmp_path / "vol"
        vol.mkdir()
        granted(vol, "(OI)(CI)(IO)M")  # inherit-only: the folder above itself passes the ancestor check
        root = vol / "MCP Monitor"
        root.mkdir()
    else:
        root = tmp_path / "MCP Monitor"
        (root / "data").mkdir(parents=True); (root / "data" / "mcp-monitor-data-root.json").write_text("{}", "utf-8")
        (root / "data" / "config.db").write_bytes(b"")
        (root / "scripts").mkdir(); (root / "scripts" / "a.ps1").write_text("x", "utf-8")
        target, grant = {"write_dac": (root, "(WDAC)"), "write_owner": (root, "(WO)"),
                         "delete_on_a_file": (root / "data" / "config.db", "(D)"),
                         "write_on_a_script": (root / "scripts" / "a.ps1", "(WD)")}[case]
        granted(target, grant)
    before = sddl(root)
    for args in (["-File", str(INSTALL / "install.ps1"), "-DryRun", "-Source", str(bundle), "-InstallDir", str(tmp_path / "i"), "-DataRoot", str(root)],
                 ["-File", str(INSTALL / "audit-policy.ps1"), "-DryRun", "-Enable", "-DataRoot", str(root)]):
        p = ps(*args)
        assert p.returncode == 2 and p.stdout.strip() == "", p.stdout + p.stderr
        assert "-DataRoot" in p.stderr and AUTHENTICATED_USERS in p.stderr and "지우고" in p.stderr, p.stderr
    me = me_sid()
    sids = f"@('S-1-5-18', 'S-1-5-32-544', '{me}')"
    out = run_actions("install.ps1", tmp_path, "",
                      f"try {{ Initialize-DataRoot '{root}' '{me}' {sids} {sids} 'install'; Write-Output 'accepted' }}"
                      " catch { Write-Output \"refused: $($_.Exception.Message)\" }\n")
    assert len(out) == 1 and out[0].startswith("refused: ") and AUTHENTICATED_USERS in out[0], out
    assert sddl(root) == before and "D:P" not in before  # left as found


def test_existing_data_root_with_harmless_extra_rights_is_accepted(bundle, tmp_path):
    # Read and execute for others, and inherit-only rights that never reach the root, take nothing over.
    root = tmp_path / "MCP Monitor"
    root.mkdir()
    granted(root, "(OI)(CI)RX")
    subprocess.run([ICACLS, str(root), "/grant", f"*{EVERYONE}:(OI)(CI)(IO)RX"], check=True, capture_output=True)
    assert step(dry("install.ps1", "-Source", str(bundle), "-InstallDir", str(tmp_path / "i"), "-DataRoot", str(root)),
                "secure_data_root")["args"] == [str(root)]


def unc(path):
    path = str(path)
    return f"\\\\localhost\\{path[0]}$\\{path[3:]}"


@pytest.mark.parametrize("form", ["device", "dot_device", "admin_share", "link_in_path"])
def test_install_refuses_device_unc_and_linked_paths(bundle, tmp_path, form):
    # Re-review 3: \\?\C:\...\i\var and \\localhost\C$\...\i\var passed the overlap check (the next reinstall's
    # /MIR deletes them); a junction in the path makes another folder pass under a different name.
    inst = tmp_path / "i"
    junction(tmp_path / "link", tmp_path / "real")
    bad = {"device": lambda p: "\\\\?\\" + str(p), "dot_device": lambda p: "\\\\.\\" + str(p), "admin_share": unc,
           "link_in_path": lambda p: str(tmp_path / "link" / p.name)}[form]
    for name, args in (("-DataRoot", ["-InstallDir", str(inst), "-DataRoot", bad(inst / "var")]),
                       ("-InstallDir", ["-InstallDir", bad(tmp_path / "i2"), "-DataRoot", str(tmp_path / "d")])):
        p = ps("-File", str(INSTALL / "install.ps1"), "-DryRun", "-Source", str(bundle), *args)
        assert p.returncode == 2 and p.stdout.strip() == "", (name, p.stdout + p.stderr)
        assert name in p.stderr, (name, p.stderr)
    p = ps("-File", str(INSTALL / "audit-policy.ps1"), "-DryRun", "-Enable", "-DataRoot", bad(tmp_path / "d"))
    assert p.returncode == 2 and p.stdout.strip() == "", p.stdout + p.stderr


@pytest.mark.parametrize("form", ["device", "admin_share", "link_in_path"])
def test_uninstall_refuses_device_unc_and_linked_paths(tmp_path, form):
    # \\?\C:\ProgramData passed Get-UnsafeRootReason: -RemoveData would have deleted ProgramData once any user
    # had planted data\mcp-monitor-data-root.json there.
    marked = tmp_path / "real" / "marked"
    (marked / "data").mkdir(parents=True); (marked / "data" / "mcp-monitor-data-root.json").write_text("{}", "utf-8")
    junction(tmp_path / "link", tmp_path / "real")
    bad = {"device": lambda p: "\\\\?\\" + str(p), "admin_share": unc,
           "link_in_path": lambda p: str(tmp_path / "link" / p.name)}[form]
    for args in (["-InstallDir", str(tmp_path / "i"), "-DataRoot", bad(marked), "-RemoveData"],
                 ["-InstallDir", bad(marked), "-DataRoot", str(tmp_path / "d")]):
        p = ps("-File", str(INSTALL / "uninstall.ps1"), "-DryRun", *args)
        assert p.returncode == 2 and p.stdout.strip() == "", (args, p.stdout + p.stderr)
    assert (marked / "data" / "mcp-monitor-data-root.json").is_file()


def test_unsafe_root_reason_needs_a_local_fixed_volume(tmp_path):
    # A subst or network drive has no local fixed volume of its own: shown here by a PC whose volume list
    # lacks the drive (creating a real subst drive would change this logon session).
    out = run_actions("uninstall.ps1", tmp_path, "",
                      "Write-Output ((Get-LocalDriveLetters) -join ',')\n"
                      f"Write-Output \"[$(Get-UnsafeRootReason '{tmp_path / 'd'}')]\"\n"
                      "function Get-LocalDriveLetters { @('Q') }\n"
                      f"Write-Output (Get-UnsafeRootReason '{tmp_path / 'd'}')\n")
    letters = out[0].split(",")
    assert os.environ["SystemDrive"][0].upper() in letters and str(tmp_path)[0].upper() in letters, out
    assert out[1] == "[]", out
    assert "로컬 고정 디스크가 아닙니다" in out[2], out


def test_data_root_problem_looks_again_when_a_file_goes_away(tmp_path):
    # Re-review 4: retention may gzip or delete a log while the walk runs: one more look, then "could not check".
    root = tmp_path / "r"
    root.mkdir()
    sids = f"@('S-1-5-18', 'S-1-5-32-544', '{me_sid()}')"
    out = run_actions("install.ps1", tmp_path, "",
                      "$script:walks = 0\n"
                      "function Get-TreeItems([string]$Root) { $script:walks++; if ($script:walks -eq 1) { throw (New-Object System.IO.FileNotFoundException 'gone') }; @() }\n"
                      f"Write-Output \"[$(Get-DataRootProblem '{root}' {sids})] $script:walks\"\n"
                      "function Get-TreeItems([string]$Root) { $script:walks++; throw (New-Object System.IO.FileNotFoundException 'gone') }\n"
                      f"Write-Output (Get-DataRootProblem '{root}' {sids})\n"
                      "Write-Output $script:walks\n")
    assert out[0] == "[] 2" and "확인하지 못했습니다" in out[1] and out[2] == "4", out


def test_dry_run_without_admin_plans_over_an_installed_data_root(bundle, tmp_path):
    """Re-review 4: an installed data root (SYSTEM + Administrators only) cannot be listed without admin rights;
    -DryRun prints the plan with a note instead of exit 2. secure_data_root checks it again when run."""
    root = tmp_path / "MCP Monitor"
    (root / "data").mkdir(parents=True)
    (root / "data" / "mcp-monitor-data-root.json").write_text("{}", "utf-8")
    lock = ("$s = New-Object System.Security.AccessControl.DirectorySecurity; $s.SetAccessRuleProtection($true, $false); "
            "foreach ($sid in 'S-1-5-18', 'S-1-5-32-544') { $s.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule("
            "(New-Object System.Security.Principal.SecurityIdentifier $sid), 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow'))) }; "
            f"(New-Object System.IO.DirectoryInfo '{root}').SetAccessControl($s)")
    p = ps("-Command", lock)
    assert p.returncode == 0, p.stderr
    try:
        with pytest.raises(PermissionError):
            os.listdir(root)
        for script, args in (("install.ps1", ["-Source", str(bundle), "-InstallDir", str(tmp_path / "i")]), ("audit-policy.ps1", ["-Enable"])):
            p = ps("-File", str(INSTALL / script), "-DryRun", *args, "-DataRoot", str(root))
            assert p.returncode == 0, (script, p.stdout + p.stderr)
            plan = json.loads(p.stdout)
            assert step(plan, "secure_data_root")["args"] == [str(root)]
            assert len(plan["notes"]) == 1 and "관리자 권한으로 다시 실행하면 확인합니다" in plan["notes"][0], plan["notes"]
            assert "참고:" in p.stderr
        # a real run without admin still stops at require_admin (exit 1), not at the argument check
        p = real_run("install.ps1", "-Source", str(bundle), "-InstallDir", str(tmp_path / "i"), "-DataRoot", str(root))
        assert p.returncode == 1 and "관리자 권한(Administrator)" in p.stdout, p.stdout + p.stderr
    finally:
        subprocess.run([ICACLS, str(root), "/reset", "/T", "/C", "/Q"], capture_output=True)
    assert dry("install.ps1", "-Source", str(bundle), "-InstallDir", str(tmp_path / "i"), "-DataRoot", str(root))["notes"] == []
