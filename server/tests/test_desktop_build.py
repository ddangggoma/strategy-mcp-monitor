"""install/build.ps1 and install/build-desktop.ps1 (Plan 6 Task 13–14): parse, no dev features in a release build,
and the checks build-desktop.ps1 makes before it builds anything (ruling F03: the cargo invocations are read from
the parsed script, not counted as substrings, so comments and progress lines do not matter)."""
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
INSTALL = REPO / "install"
FIXTURE_PAYLOAD = REPO / "desktop" / "tests" / "fixtures" / "payload"
PS = [str(Path(os.environ["SystemRoot"]) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"),
      "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass"]


def ps_command(script: str) -> subprocess.CompletedProcess:
    return subprocess.run([*PS, "-Command", script], capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)


def build_desktop(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([*PS, "-File", str(INSTALL / "build-desktop.ps1"), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120, stdin=subprocess.DEVNULL,
                          env=None if env is None else {**os.environ, **env})


def call_script_function(name: str, argument: str) -> str:
    """Runs one function of build-desktop.ps1 (taken from the parsed script, without running the script) on
    `argument`; the result is printed one value per line, or `<null>`."""
    script = (
        "$e = $null; $ast = [System.Management.Automation.Language.Parser]::ParseFile("
        f"'{INSTALL / 'build-desktop.ps1'}', [ref]$null, [ref]$e); "
        "$f = $ast.Find({ param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and "
        f"$n.Name -eq '{name}' }}, $true); "
        ". ([scriptblock]::Create($f.Extent.Text)); "
        f"$r = {name} ([System.IO.File]::ReadAllText($env:MCPMON_ARG)); "
        "if ($null -eq $r) { '<null>' } else { $r | ForEach-Object { \"$_\" } }")
    arg = Path(os.environ.get("TEMP", ".")) / f"mcpmon-build-arg-{os.getpid()}.txt"
    arg.write_text(argument, encoding="utf-8")
    try:
        p = subprocess.run([*PS, "-Command", script], capture_output=True, text=True, timeout=120,
                           stdin=subprocess.DEVNULL, env={**os.environ, "MCPMON_ARG": str(arg)})
    finally:
        arg.unlink()
    assert p.returncode == 0, p.stdout + p.stderr
    return p.stdout.strip()


@pytest.mark.parametrize("name", ["build.ps1", "build-desktop.ps1"])
def test_build_scripts_parse_and_have_a_bom(name):
    p = ps_command(f"$e = $null; [void][System.Management.Automation.Language.Parser]::ParseFile('{INSTALL / name}', [ref]$null, [ref]$e); $e.Count")
    assert p.returncode == 0 and p.stdout.strip() == "0", p.stdout + p.stderr
    if name == "build-desktop.ps1":
        assert (INSTALL / name).read_bytes().startswith(b"\xef\xbb\xbf")


def test_a_release_build_never_enables_features():
    # Every command the script runs whose name is `cargo`, as PowerShell parses it (elements joined by one space).
    p = ps_command(
        "$e = $null; $ast = [System.Management.Automation.Language.Parser]::ParseFile("
        f"'{INSTALL / 'build-desktop.ps1'}', [ref]$null, [ref]$e); "
        "$ast.FindAll({ param($n) $n -is [System.Management.Automation.Language.CommandAst] }, $true) | "
        "Where-Object { $_.GetCommandName() -match '^cargo(\\.exe)?$' } | "
        "ForEach-Object { ($_.CommandElements | ForEach-Object { $_.Extent.Text }) -join ' ' }")
    assert p.returncode == 0, p.stdout + p.stderr
    assert sorted(p.stdout.splitlines()) == ["cargo audit", "cargo build --release --locked"], p.stdout
    text = (INSTALL / "build-desktop.ps1").read_text("utf-8-sig")
    assert "--features" not in text and "$env:MCPMON_PAYLOAD_DIR = $Payload" in text


def test_signing_needs_a_timestamp_url():
    p = build_desktop("-SkipPayload", "-SignThumbprint", "0" * 40)
    assert p.returncode != 0 and "-SignThumbprint needs -TimestampUrl" in p.stdout + p.stderr, p.stdout + p.stderr
    assert "==> cargo" not in p.stdout


def test_a_folder_without_bundle_json_is_refused(tmp_path):
    p = build_desktop("-SkipPayload", "-SkipAudit", "-Payload", str(tmp_path))
    assert p.returncode != 0 and "has no bundle.json" in p.stdout + p.stderr, p.stdout + p.stderr
    assert "==> cargo" not in p.stdout


def test_a_release_build_refuses_the_fixture_payload(tmp_path):
    # The fixture has the release layout (check_release_layout passes it, Task 3): only its bundle.json tells.
    payload = tmp_path / "payload"
    shutil.copytree(FIXTURE_PAYLOAD, payload)
    p = build_desktop("-SkipPayload", "-SkipAudit", "-Payload", str(payload))
    assert p.returncode != 0 and "is a development (fixture) payload" in p.stdout + p.stderr, p.stdout + p.stderr
    assert "==> cargo" not in p.stdout


@pytest.mark.parametrize("name", ["RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS", "CARGO_BUILD_RUSTFLAGS",
                                  "CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_RUSTFLAGS"])
def test_a_rustflags_variable_is_refused_before_anything_is_built(name):
    # Review item 10: it would replace .cargo/config.toml's +crt-static and /DEPENDENTLOADFLAG:0x800.
    p = build_desktop("-SkipPayload", "-SkipAudit", env={name: "-C opt-level=1"})
    out = p.stdout + p.stderr
    assert p.returncode != 0 and f"{name} is set" in out, out
    assert "==> " not in p.stdout


LOAD_CONFIG = """
            0000 Reserved
             {flag} Dependent Load Flag
        0000000000000000 Edit list
"""


@pytest.mark.parametrize(("flag", "value"), [("800", "2048"), ("1800", "6144"), ("A800", "43008"), ("0", "0")])
def test_dependent_load_flag_is_read_as_a_number(flag, value):
    # Review item 10: "1800" or "A800" contain "800" but add the application folder or the default dirs.
    assert call_script_function("Get-DependentLoadFlag", LOAD_CONFIG.format(flag=flag)) == value
    assert call_script_function("Get-DependentLoadFlag", "no load config here") == "<null>"
    text = (INSTALL / "build-desktop.ps1").read_text("utf-8-sig")
    assert "if ($flag -ne 0x800)" in text


def test_c_runtime_imports_are_found():
    dependents = """
  Image has the following dependencies:

    KERNEL32.dll
    VCRUNTIME140.dll
    api-ms-win-crt-runtime-l1-1-0.dll
    ucrtbase.dll
    WS2_32.dll
"""
    assert call_script_function("Get-CrtImports", dependents).splitlines() == [
        "VCRUNTIME140.dll", "api-ms-win-crt-runtime-l1-1-0.dll", "ucrtbase.dll"]
    assert call_script_function("Get-CrtImports", "    KERNEL32.dll\n    USER32.dll\n") == "<null>"


def test_powershell_installer_is_retired():
    for name in ("install.ps1", "uninstall.ps1", "audit-policy.ps1", "LAYOUT", "pyinstaller/mcp-agent.spec", "pyinstaller/entry_agent.py"):
        assert not (INSTALL / name).exists(), name
    assert not (REPO / "server" / "tests" / "test_install_scripts.py").exists()
    for script in ("build.ps1", "build-desktop.ps1"):
        text = (INSTALL / script).read_text("utf-8-sig")
        assert not re.search(r"install\.ps1|uninstall\.ps1|audit-policy\.ps1|mcp-agent|LAYOUT", text), script
