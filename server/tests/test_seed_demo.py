"""``python -m app seed-demo`` (app.demo): demo users, dummy MCPs and their wrapper scripts."""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.__main__ import EXIT_ROOT_IN_USE, main
from app.clock import SystemClock
from app.db import Database
from app.demo import DEMO_MCPS, DEMO_USERS, wrapper_script
from app.monitor.probes import listening_ports
from app.monitor.runner import build_argv
from app.monitor.scripts import ScriptStore
from app.monitor.store import McpStore
from app.paths import AppPaths
from app.rootlock import RootLock
from app.users.store import UserStore
from tests.live import free_port

REPO_DUMMY = Path(__file__).resolve().parents[2] / "dummy-mcps"


@pytest.fixture
def dummy_dir(tmp_path):
    """A minimal dummy-mcps layout (the real checkout's .venv is not needed to seed)."""
    d = tmp_path / "dummy mcps"
    (d / "examples").mkdir(parents=True)
    for kind in ("start", "stop", "restart"):
        (d / "examples" / f"{kind}.ps1").write_text("exit 0\n", encoding="utf-8")
    for m in DEMO_MCPS:
        (d / m.module).mkdir()
        (d / m.module / "__main__.py").write_text("", encoding="utf-8")
    return d


@pytest.fixture
def root(tmp_path):
    return tmp_path / "root"


def _seed(root: Path, dummy_dir: Path, *extra: str) -> int:
    return main(["seed-demo", "--root", str(root), "--dummy-mcps-dir", str(dummy_dir), *extra])


def _open(root: Path):
    paths = AppPaths(root)
    db = Database(paths.db_path)
    db.migrate()
    clock = SystemClock()
    users = UserStore(db, clock)
    mcps = McpStore(db, clock, users)
    return db, paths, users, mcps, ScriptStore(db, paths, clock, mcps)


def _audit_lines(root: Path) -> list[dict]:
    lines = []
    for f in sorted((root / "logs").glob("*.jsonl")):
        lines += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x]
    return [x for x in lines if x["cat"] == "admin.audit"]


def test_the_real_dummy_mcps_match_the_demo_table():
    start = (REPO_DUMMY / "examples" / "start.ps1").read_text(encoding="utf-8-sig")
    for m in DEMO_MCPS:
        assert f"'{m.name}' = '{m.module}'" in start  # MCP_NAME -> module map of the examples
        main_py = (REPO_DUMMY / m.module / "__main__.py").read_text(encoding="utf-8")
        assert f'run("{m.name}", ' in main_py and f"None, {m.port}" in main_py


def test_seed_creates_users_mcps_and_scripts(root, dummy_dir, capsys):
    assert _seed(root, dummy_dir) == 0
    out = capsys.readouterr().out
    assert "데모 데이터" in out and "만듦" in out
    db, paths, users, mcps, scripts = _open(root)
    try:
        by_email = {u.email: u for u in users.list()}
        assert {(u.email, u.name, u.role) for u in by_email.values()} == {
            (u.email, u.name, u.role) for u in DEMO_USERS
        }
        listed = {m.config.name: m for m in mcps.list()}
        assert set(listed) == {m.name for m in DEMO_MCPS}
        for demo in DEMO_MCPS:
            mcp = listed[demo.name]
            assert mcp.config_error is None
            assert (mcp.config.host, mcp.config.port, mcp.config.path) == ("127.0.0.1", demo.port, "/mcp")
            assert mcp.config.probe == "mcp_ping" and mcp.config.autostart_on_boot
            assert mcp.config.icon == demo.icon and demo.icon is not None  # every demo MCP gets an emoji
            assert mcp.owner_id == by_email[demo.owner_email].id
            infos = scripts.list(mcp.id)
            assert [i.kind for i in infos] == ["start", "stop", "restart"]
            for info in infos:
                data = info.path.read_bytes()
                assert hashlib.sha256(data).hexdigest() == info.sha256  # what the runner checks
                text = data.decode("utf-8-sig")
                assert info.path.suffix == ".ps1"
                assert f"$env:DUMMY_MCPS_DIR = '{dummy_dir.resolve()}'" in text
                assert f"$env:DUMMY_MCP_RUN_DIR = '{paths.data_dir / 'demo-run'}'" in text
                assert f"& '{dummy_dir.resolve() / 'examples' / (info.kind + '.ps1')}'" in text
    finally:
        db.close()
    audit = _audit_lines(root)
    assert [a["action"] for a in audit] == ["user_create"] * 3 + ["mcp_create"] * 3
    assert all(a["actor"] == "seed-demo" and a["result"] == "ok" for a in audit)


def test_seed_is_idempotent(root, dummy_dir, capsys):
    assert _seed(root, dummy_dir) == 0
    db, _paths, users, mcps, scripts = _open(root)
    try:
        before = (users.list(), mcps.list(), [scripts.list(m.id) for m in mcps.list()])
    finally:
        db.close()
    capsys.readouterr()
    assert _seed(root, dummy_dir) == 0
    assert "만듦" not in capsys.readouterr().out
    db, _paths, users, mcps, scripts = _open(root)
    try:
        assert (users.list(), mcps.list(), [scripts.list(m.id) for m in mcps.list()]) == before
    finally:
        db.close()
    assert len(_audit_lines(root)) == 6  # the second run wrote no audit line


def test_existing_users_are_kept_and_the_first_admin_is_the_creator(root, dummy_dir):
    paths = AppPaths(root)
    paths.ensure()
    db, _paths, users, _mcps, _scripts = _open(root)
    try:
        admin = users.create_first_admin("me@corp.example", "Me")
        dev1 = users.create("DEV1@example.com", "Someone", "developer", created_by=admin.id)
    finally:
        db.close()
    assert _seed(root, dummy_dir) == 0
    db, _paths, users, mcps, _scripts = _open(root)
    try:
        assert users.get(dev1.id).name == "Someone"  # untouched
        assert users.get_by_email("dev2@example.com").created_by == admin.id
        owners = {m.config.name: m.owner_id for m in mcps.list()}
        assert owners["seoul-weather"] == dev1.id
    finally:
        db.close()


def test_owner_email_must_be_an_active_admin(root, dummy_dir, capsys):
    assert _seed(root, dummy_dir, "--owner-email", "nobody@example.com") == 2
    assert "not an active admin" in capsys.readouterr().err
    assert not (AppPaths(root).scripts_dir).exists() or not any(AppPaths(root).scripts_dir.iterdir())


def test_a_folder_without_the_examples_is_refused(root, tmp_path, capsys):
    assert _seed(root, tmp_path / "nothing") == 2
    assert "is not a dummy-mcps folder" in capsys.readouterr().err


def test_refused_while_the_root_lock_is_held(root, dummy_dir, capsys):
    with RootLock(root):
        assert _seed(root, dummy_dir) == EXIT_ROOT_IN_USE
    assert "already in use" in capsys.readouterr().err
    db, _paths, users, _mcps, _scripts = _open(root)
    try:
        assert users.count() == 0
    finally:
        db.close()


def test_an_endpoint_taken_by_another_mcp_is_reported_and_the_rest_seeded(root, dummy_dir, capsys):
    assert _seed(root, dummy_dir) == 0
    db, _paths, _users, mcps, _scripts = _open(root)
    try:
        weather = next(m for m in mcps.list() if m.config.name == "seoul-weather")
        mcps.update(weather.id, {"name": "my-weather"})  # keeps 127.0.0.1:9101
    finally:
        db.close()
    assert _seed(root, dummy_dir) == 1
    assert "endpoint_taken" in capsys.readouterr().out
    assert _audit_lines(root)[-1]["result"] == "error"


def test_wrapper_quotes_single_quotes_in_paths():
    text = wrapper_script("start", Path(r"C:\it's\dummy-mcps"), Path(r"C:\D\data\demo-run"))
    assert r"$env:DUMMY_MCPS_DIR = 'C:\it''s\dummy-mcps'" in text
    assert text.rstrip().endswith("exit $LASTEXITCODE")


@pytest.mark.skipif(
    sys.platform != "win32" or not (REPO_DUMMY / ".venv" / "Scripts" / "python.exe").exists(),
    reason="Windows + dummy-mcps venv only",
)
def test_the_seeded_wrappers_start_and_stop_a_real_dummy_mcp(root, tmp_path):
    """The stored start/stop scripts, run like the ScriptRunner runs them, drive a real dummy MCP."""
    assert _seed(root, REPO_DUMMY) == 0
    db, paths, _users, mcps, scripts = _open(root)
    try:
        calc = next(m for m in mcps.list() if m.config.name == "calculator")
        start, stop = (scripts.get(calc.id, k).path for k in ("start", "stop"))
    finally:
        db.close()
    port = free_port()  # not the demo port: an installed instance may be running it
    env = {**os.environ, "MCP_ID": str(calc.id), "MCP_NAME": "calculator", "MCP_HOST": "127.0.0.1",
           "MCP_PORT": str(port)}
    env.pop("DUMMY_MCPS_DIR", None)
    env.pop("DUMMY_MCP_RUN_DIR", None)

    def run(path: Path) -> tuple[int, str]:
        # A file, not a pipe: the MCP the start script leaves running inherits the handle, so a
        # pipe would never reach EOF (the ScriptRunner waits for the exit for the same reason).
        out = tmp_path / f"{path.stem}.out"
        with open(out, "wb") as f:
            code = subprocess.run(build_argv(path), env=env, stdin=subprocess.DEVNULL, stdout=f,
                                  stderr=subprocess.STDOUT, timeout=60, check=False).returncode
        return code, out.read_text("utf-8", errors="replace")

    try:
        code, output = run(start)
        assert code == 0, output
        assert listening_ports().get(port) is not None
        assert (paths.data_dir / "demo-run" / f"{calc.id}.pid").is_file()
    finally:
        code, output = run(stop)
    assert code == 0, output
    assert listening_ports().get(port) is None
