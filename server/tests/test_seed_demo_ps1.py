"""tools/seed-demo.ps1 (TEST/DEMO ONLY): parsed and its pure helpers called; no service step runs."""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "seed-demo.ps1"
POWERSHELL = shutil.which("powershell.exe")
needs_ps = pytest.mark.skipif(sys.platform != "win32" or POWERSHELL is None, reason="Windows PowerShell only")

# Functions that change the service or its data: each must start with the elevation guard.
SERVICE_STEPS = re.compile(r"sc\.exe|Invoke-CimMethod|Get-CimInstance|Get-SeedArguments\)|\$ServerExe")


def _ps(command: str) -> str:
    assert POWERSHELL is not None
    done = subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", command],
        stdin=subprocess.DEVNULL, capture_output=True, timeout=60, check=False,
    )
    assert done.returncode == 0, done.stderr.decode("utf-8", errors="replace")
    return done.stdout.decode("utf-8", errors="replace")


def _functions() -> dict[str, list[str]]:
    """Function name -> its top-level statements (as text), from the PowerShell parser."""
    out = _ps(
        "[Console]::OutputEncoding = [Text.Encoding]::UTF8; $t = $null; $e = $null; "
        f"$ast = [Management.Automation.Language.Parser]::ParseFile('{SCRIPT}', [ref]$t, [ref]$e); "
        "if ($e.Count) { throw ($e | Out-String) }; "
        "$fs = $ast.FindAll({ param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] }, $true); "
        "$map = @{}; foreach ($f in $fs) { $map[$f.Name] = @($f.Body.EndBlock.Statements | ForEach-Object { $_.Extent.Text }) }; "
        "$map | ConvertTo-Json -Depth 3 -Compress"
    )
    return {name: body if isinstance(body, list) else [body] for name, body in json.loads(out).items()}


def test_utf8_bom_and_defaults():
    data = SCRIPT.read_bytes()
    assert data.startswith(b"\xef\xbb\xbf")  # Korean text: PowerShell 5.1 needs the BOM
    text = data.decode("utf-8-sig")
    assert "[string]$InstallDir = 'C:\\Program Files\\MCP Monitor'" in text
    assert "[string]$DataRoot = 'C:\\ProgramData\\MCP Monitor'" in text
    assert "Join-Path $InstallDir 'bin\\monitor\\mcp-monitor-server.exe'" in text
    assert "[ValidatePattern('^[0-9]{6}$')]\n    [string]$DevOtpCode = '123456'" in text
    assert "Join-Path $env:LOCALAPPDATA 'mcp-monitor-demo'" in text
    assert "$ServiceName = 'mcp-monitor'" in text


@needs_ps
def test_every_service_step_is_guarded_by_elevation():
    functions = _functions()
    # A service step uses a primitive or calls another service step (to a fixed point).
    guarded = {name for name, body in functions.items() if SERVICE_STEPS.search("\n".join(body))}
    while True:
        callers = {
            name for name, body in functions.items()
            if name not in guarded and name != "Invoke-Main"  # main branches on Test-Admin itself
            and any(re.search(rf"(?<![\w-]){re.escape(g)}(?![\w-])", "\n".join(body)) for g in guarded)
        }
        if not callers:
            break
        guarded |= callers
    assert {"Stop-MonitorService", "Invoke-SeedDemo", "Set-MonitorBinPath", "Start-MonitorService",
            "Get-MonitorService", "Invoke-Elevated"} <= set(guarded)
    for name in guarded:
        assert functions[name][0] == "Assert-Elevated", name
    assert "Test-Admin" in "\n".join(functions["Assert-Elevated"])
    assert "throw" in "\n".join(functions["Assert-Elevated"])


@needs_ps
def test_main_elevates_once_and_only_then_runs_the_service_steps():
    main = "\n".join(_functions()["Invoke-Main"])
    not_admin = main.index("if (-not (Test-Admin))")
    assert main.index("Invoke-SelfElevated") > not_admin
    assert main.index("if ($Elevated) { Stop-WithError") < main.index("Invoke-SelfElevated")  # no second UAC
    assert main.index("Initialize-DummyVenv") < main.index("Invoke-SelfElevated")  # uv sync as the user
    assert main.index("exit $code") < main.index("Invoke-Elevated")  # the unelevated run stops there
    elevation = "\n".join(_functions()["Get-ElevationArguments"])
    assert "'-Elevated'" in elevation and "-Verb RunAs" in "\n".join(_functions()["Invoke-SelfElevated"])


@needs_ps
def test_seed_arguments_and_bin_path_helpers():
    out = _ps(
        f". '{SCRIPT}' -DevOtpCode 654321 -DataRoot 'D:\\Data Root'; "
        "$cur = '\"C:\\Program Files\\MCP Monitor\\bin\\monitor\\mcp-monitor-server.exe\" service "
        "--root \"C:\\ProgramData\\MCP Monitor\" --local-port 8800 --external-port 8801'; "
        "$added = Get-DemoBinPath $cur $DevOtpCode $false; "
        "@{ seed = @(Get-SeedArguments); dummy = $DummyDir; cur = $cur; added = $added; "
        "again = (Get-DemoBinPath $added '111111' $false); reverted = (Get-DemoBinPath $added '' $true); "
        "port = (Get-LocalPort $cur); default_port = (Get-LocalPort 'x.exe service'); "
        "elevation = @(Get-ElevationArguments) } | ConvertTo-Json -Compress"
    )
    r = json.loads(out)
    assert r["seed"] == ["seed-demo", "--root", "D:\\Data Root", "--dummy-mcps-dir", r["dummy"]]
    assert Path(r["dummy"]) == SCRIPT.parents[1] / "dummy-mcps"
    assert r["added"] == r["cur"] + " --external-host 127.0.0.1 --dev-otp-code 654321"
    assert r["again"] == r["cur"] + " --external-host 127.0.0.1 --dev-otp-code 111111"  # replaced, not stacked
    assert r["reverted"] == r["cur"]
    assert (r["port"], r["default_port"]) == (8800, 8700)
    assert "-Elevated" in r["elevation"] and "654321" in r["elevation"]
    assert "\"D:\\Data Root\"" in r["elevation"]


def test_the_dev_code_arguments_are_accepted_by_the_server_parser():
    """What the script appends to the service's binPath parses (a loopback external host)."""
    from app.__main__ import parse_args

    ns = parse_args(["--root", "C:\\x", "--local-port", "8700", "--external-port", "8701",
                     "--external-host", "127.0.0.1", "--dev-otp-code", "123456"])
    assert (ns.external_host, ns.dev_otp_code) == ("127.0.0.1", "123456")


def test_python_in_the_user_profile_is_moved_for_the_service(tmp_path):
    # A uv Python installed from inside a packaged (MSIX) app lives in that app's private AppData copy,
    # which the LocalSystem service cannot see: the venv must be rebuilt on a copy outside the profile.
    venv = tmp_path / ".venv"
    venv.mkdir()
    (venv / "pyvenv.cfg").write_text(
        r"home = C:\Users\someone\AppData\Roaming\uv\python\cpython-3.15.2-windows-x86_64-none" "\n"
        "implementation = CPython\n",
        encoding="utf-8",
    )
    out = _ps(
        f". '{SCRIPT}'; "
        f"$h = Get-VenvHome '{venv}'; "
        "@{ home = $h; "
        r"in_profile = (Test-InUserProfile $h 'c:\users\SOMEONE'); "
        r"other_user = (Test-InUserProfile $h 'C:\Users\someone-else'); "
        r"repo = (Test-InUserProfile 'E:\workspace\dummy-mcps\.python\cpython' 'C:\Users\someone'); "
        f"missing = ($null -eq (Get-VenvHome '{tmp_path / 'none'}')) "
        "} | ConvertTo-Json -Compress"
    )
    r = json.loads(out)
    assert r["home"].endswith("cpython-3.15.2-windows-x86_64-none")
    assert r["in_profile"] is True  # case-insensitive
    assert r["other_user"] is False  # a sibling folder with the same prefix is not inside
    assert r["repo"] is False
    assert r["missing"] is True


def test_main_repairs_the_venv_before_elevating():
    main = "\n".join(_functions()["Invoke-Main"])
    assert "Repair-DummyVenvForService" in main
    assert main.index("Repair-DummyVenvForService") < main.index("Invoke-SelfElevated")
