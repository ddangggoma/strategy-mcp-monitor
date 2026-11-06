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
import subprocess
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
def test_scripts_are_utf8_with_bom(name):
    # Windows PowerShell 5.1 reads a BOM-less script in the ANSI code page (949): Korean text would break.
    raw = (INSTALL / name).read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    raw.decode("utf-8")


SHARED = ["Get-FullPath", "Get-Prop", "Read-JsonFile", "Test-Admin", "Add-Step", "ConvertTo-CommandLineArg", "Invoke-Native"]


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
                          f"Write-Output (& $Internal['(mkdir)'] @{{ args = @('{d / 'logs'}', '{d / 'data'}') }})\n"
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
    assert out[0] == "0" and (d / "logs").is_dir() and (d / "data").is_dir()
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
        "require_admin", "check_os", "stop_existing", "copy_bundle", "create_dirs", "acl_data", "acl_children", "acl_owner",
        "audit_backup", "audit_policy_success", "audit_policy_failure", "registry_cmdline", "registry_scriptblock",
        "security_log_size", "powershell_log_size", "service_install", "service_description", "service_failure",
        "service_failureflag", "install_state", "service_start", "wait_ready"]
    assert step(plan, "acl_data")["args"] == [data, "/inheritance:r", "/grant:r", "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F"]
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
    assert step(plan, "create_dirs")["args"] == [f"{data}\\logs", f"{data}\\data", f"{data}\\scripts"]
    assert step(plan, "acl_children")["args"] == [f"{data}\\*", "/reset", "/T", "/C", "/Q"]
    assert step(plan, "acl_owner")["args"] == [data, "/setowner", "*S-1-5-32-544", "/T", "/C", "/Q"]
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


def test_audit_policy_script_plan():
    plan = dry("audit-policy.ps1", "-Enable")
    assert [s["id"] for s in plan["steps"]][1:] == ["audit_backup", "audit_policy_success", "audit_policy_failure",
                                                    "registry_cmdline", "registry_scriptblock", "security_log_size", "powershell_log_size"]


def test_audit_policy_enable_matches_install(bundle, tmp_path):
    data = str(tmp_path / "d")
    enable = dry("audit-policy.ps1", "-Enable", "-DataRoot", data)
    install = dry("install.ps1", "-Source", str(bundle), "-InstallDir", str(tmp_path / "i"), "-DataRoot", data)
    assert enable["script"] == "audit-policy" and enable["steps"][0]["id"] == "require_admin"
    assert enable["steps"][1:] == install["steps"][8:15]


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
