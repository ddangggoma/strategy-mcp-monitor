"""install/build.ps1 and install/build-desktop.ps1 (Plan 6 Task 13–14): parse, no dev features in a release build,
and the checks build-desktop.ps1 makes before it builds anything (ruling F03: the cargo invocations are read from
the parsed script, not counted as substrings, so comments and progress lines do not matter)."""
import os
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


def build_desktop(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([*PS, "-File", str(INSTALL / "build-desktop.ps1"), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120, stdin=subprocess.DEVNULL)


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
