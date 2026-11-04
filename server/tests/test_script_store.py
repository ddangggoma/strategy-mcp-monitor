import hashlib
import sys

import pytest

import app.monitor.scripts as mod
from app.monitor.scripts import (
    MAX_SCRIPT_BYTES,
    ScriptNotFoundError,
    ScriptRequiredError,
    ScriptStore,
    ScriptValidationError,
    prepare_script,
)
from app.monitor.scripts import ScriptUpload as U
from app.monitor.store import EndpointTakenError, McpNotFoundError, McpStore, NameTakenError
from app.users.store import UserStore
from tests.mcp_helpers import cfg

# The "oem" codec exists only on Windows (the target platform).
windows_only = pytest.mark.skipif(sys.platform != "win32", reason="oem codec is Windows-only")

BASIC = {"start": U(".bat", "@echo off\nexit /b 0"), "stop": U(".bat", "exit /b 0")}


@pytest.fixture
def env(db, paths, clock):
    users = UserStore(db, clock)
    owner = users.create("o@x.com", "o", "developer", None)
    mcps = McpStore(db, clock, users)
    return ScriptStore(db, paths, clock, mcps), mcps, owner, paths


def _tree(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


# ---- prepare_script ----


def test_prepare_ps1_bom_crlf():
    p = prepare_script("start", U(".ps1", "Write-Output '시작'\nexit 0"))
    assert p.data == b"\xef\xbb\xbf" + "Write-Output '시작'\r\nexit 0\r\n".encode("utf-8")
    assert p.sha256 == hashlib.sha256(p.data).hexdigest()
    assert p.text == "Write-Output '시작'\r\nexit 0\r\n"


@windows_only
def test_prepare_bat_crlf():
    p = prepare_script("stop", U(".bat", "@echo off\r\nexit /b 0\n"))
    assert p.data == b"@echo off\r\nexit /b 0\r\n"


@windows_only
@pytest.mark.parametrize("ext", [".bat", ".cmd"])
def test_prepare_bat_cmd_use_oem_code_page_with_korean(ext):
    text = "echo 안녕하세요\n"
    try:
        expected = text.replace("\n", "\r\n").encode("oem")
    except UnicodeEncodeError:  # the OEM code page of this machine has no Hangul
        with pytest.raises(ScriptValidationError) as e:
            prepare_script("start", U(ext, text))
        assert e.value.code == "script_encoding"
        return
    p = prepare_script("start", U(ext, text))
    assert p.data == expected and not p.data.startswith(b"\xef\xbb\xbf")
    assert p.data.decode("oem") == p.text  # round-trips through the same code page


def test_prepare_normalizes_mixed_line_endings():
    p = prepare_script("start", U(".ps1", "a\r\nb\rc\nd\r\n\r\n"))
    assert p.text == "a\r\nb\r\nc\r\nd\r\n\r\n"
    assert b"\n" not in p.data.replace(b"\r\n", b"") and b"\r" not in p.data.replace(b"\r\n", b"")


def test_prepare_ps1_korean_round_trip():
    original = "Write-Host '서울 날씨 서버를 시작합니다'\n"
    p = prepare_script("start", U(".ps1", original))
    assert p.data[:3] == b"\xef\xbb\xbf"
    assert p.data.decode("utf-8-sig") == original.replace("\n", "\r\n")


def test_prepare_ext_is_case_insensitive():
    assert prepare_script("start", U(".PS1", "exit 0")).ext == ".ps1"


@pytest.mark.parametrize(
    "kind,upload,code",
    [
        ("start", U(".exe", "x"), "validation"),
        ("start", U("", "x"), "validation"),
        ("start", U("../x.bat", "x"), "validation"),
        ("deploy", U(".bat", "x"), "validation"),
        ("../start", U(".bat", "x"), "validation"),
        ("start", U(".bat", "  \n "), "script_empty"),
        ("start", U(".ps1", ""), "script_empty"),
        ("start", U(".ps1", "\ud800"), "script_encoding"),  # lone surrogate
        ("start", U(".bat", "\U0001F600"), "script_encoding"),
        ("start", U(".ps1", "가" * 30_000), "script_too_large"),
    ],
)
def test_prepare_rejects(kind, upload, code):
    if upload.ext in (".bat", ".cmd") and sys.platform != "win32":
        pytest.skip("oem codec is Windows-only")
    with pytest.raises(ScriptValidationError) as e:
        prepare_script(kind, upload)
    assert e.value.code == code


def test_size_cap_applies_after_encoding_including_bom_and_crlf():
    # BOM (3) + content + CRLF (2) must fit in 65,536 bytes
    ok = prepare_script("start", U(".ps1", "a" * (MAX_SCRIPT_BYTES - 5)))
    assert len(ok.data) == MAX_SCRIPT_BYTES
    with pytest.raises(ScriptValidationError) as e:
        prepare_script("start", U(".ps1", "a" * (MAX_SCRIPT_BYTES - 4)))
    assert e.value.code == "script_too_large"
    # 22,000 Hangul = 22,000 characters but 66,000 UTF-8 bytes
    with pytest.raises(ScriptValidationError) as e:
        prepare_script("start", U(".ps1", "가" * 22_000))
    assert e.value.code == "script_too_large"


@windows_only
def test_size_cap_bat_counts_encoded_bytes():
    ok = prepare_script("start", U(".bat", "a" * (MAX_SCRIPT_BYTES - 2)))
    assert len(ok.data) == MAX_SCRIPT_BYTES
    with pytest.raises(ScriptValidationError) as e:
        prepare_script("start", U(".bat", "a" * (MAX_SCRIPT_BYTES - 1)))
    assert e.value.code == "script_too_large"


# ---- create_mcp ----


@windows_only
def test_create_mcp_writes_files(env):
    s, _, owner, paths = env
    m = s.create_mcp(cfg(), owner.id, BASIC)
    info = s.get(m.id, "start")
    assert info.path == paths.scripts_dir / str(m.id) / "start.bat" and info.version == 1
    assert hashlib.sha256(info.path.read_bytes()).hexdigest() == info.sha256
    assert s.get(m.id, "restart") is None and s.content(m.id, "stop") == "exit /b 0\r\n"
    assert [i.kind for i in s.list(m.id)] == ["start", "stop"]
    assert s.versions(m.id, "start")[0].author_id == owner.id
    assert _tree(paths.scripts_dir / str(m.id)) == ["start.bat", "stop.bat"]  # no tmp left


def test_create_mcp_with_ps1_and_restart_records_hash_of_disk_bytes(env):
    s, _, owner, _ = env
    m = s.create_mcp(
        cfg(),
        owner.id,
        {
            "start": U(".ps1", "Write-Output '시작'"),
            "stop": U(".ps1", "Write-Output '중지'"),
            "restart": U(".ps1", "Write-Output '재시작'"),
        },
    )
    infos = s.list(m.id)
    assert [i.kind for i in infos] == ["start", "stop", "restart"]
    for info in infos:
        raw = info.path.read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf") and raw.endswith(b"\r\n")
        assert hashlib.sha256(raw).hexdigest() == info.sha256
        assert s.version(m.id, info.kind, 1).sha256 == info.sha256
    assert s.content(m.id, "restart") == "Write-Output '재시작'\r\n"


@pytest.mark.parametrize("missing", ["start", "stop"])
def test_create_requires_start_and_stop(env, missing):
    s, mcps, owner, paths = env
    uploads = {k: v for k, v in BASIC.items() if k != missing}
    with pytest.raises(ScriptValidationError) as e:
        s.create_mcp(cfg(), owner.id, uploads)
    assert e.value.code == "scripts_required" and mcps.list() == []
    assert list(paths.scripts_dir.iterdir()) == []


def test_create_rejects_unknown_kind_and_invalid_content(env):
    s, mcps, owner, paths = env
    with pytest.raises(ScriptValidationError) as e:
        s.create_mcp(cfg(), owner.id, {**BASIC, "deploy": U(".bat", "x")})
    assert e.value.code == "validation"
    with pytest.raises(ScriptValidationError) as e:
        s.create_mcp(cfg(), owner.id, {"start": U(".ps1", "x"), "stop": U(".ps1", " ")})
    assert e.value.code == "script_empty"
    assert mcps.list() == [] and list(paths.scripts_dir.iterdir()) == []


def test_create_duplicate_name_and_endpoint_leave_nothing_new(env):
    s, mcps, owner, paths = env
    ps = {"start": U(".ps1", "exit 0"), "stop": U(".ps1", "exit 0")}
    first = s.create_mcp(cfg(), owner.id, ps)
    with pytest.raises(NameTakenError):
        s.create_mcp(cfg(port=9999), owner.id, ps)
    with pytest.raises(EndpointTakenError):
        s.create_mcp(cfg(name="other"), owner.id, ps)
    assert [m.id for m in mcps.list()] == [first.id]
    assert [p.name for p in paths.scripts_dir.iterdir()] == [str(first.id)]


def test_create_failure_leaves_nothing(env, monkeypatch):
    s, mcps, owner, paths = env
    real, calls = mod.os.replace, []

    def flaky(a, b):
        calls.append(a)
        if len(calls) == 2:
            raise OSError("disk")
        real(a, b)

    monkeypatch.setattr(mod.os, "replace", flaky)
    with pytest.raises(OSError):
        s.create_mcp(cfg(), owner.id, {"start": U(".ps1", "exit 0"), "stop": U(".ps1", "exit 0")})
    assert len(calls) == 2
    assert mcps.list() == [] and list(paths.scripts_dir.iterdir()) == []
    assert s.get(1, "start") is None and s.versions(1, "start") == []


# ---- put / versions ----


@windows_only
def test_put_versions_and_ext_switch(env):
    s, _, owner, paths = env
    m = s.create_mcp(cfg(), owner.id, BASIC)
    info = s.put(m.id, "start", U(".ps1", "exit 0"), owner.id)
    d = paths.scripts_dir / str(m.id)
    assert info.version == 2 and (d / "start.ps1").exists() and not (d / "start.bat").exists()
    assert [v.version for v in s.versions(m.id, "start")] == [2, 1]
    assert s.versions(m.id, "start")[0].author_id == owner.id
    assert _tree(d) == ["start.ps1", "stop.bat"]


def test_put_records_disk_hash_and_content(env, clock):
    s, _, owner, _ = env
    m = s.create_mcp(cfg(), owner.id, {"start": U(".ps1", "a"), "stop": U(".ps1", "b")})
    clock.advance(60)
    info = s.put(m.id, "start", U(".ps1", "Write-Output '두번째'\nexit 0"), owner.id)
    assert hashlib.sha256(info.path.read_bytes()).hexdigest() == info.sha256
    assert s.content(m.id, "start") == "Write-Output '두번째'\r\nexit 0\r\n"
    assert info.updated_at == clock.now() and info.updated_by == owner.id
    assert s.version(m.id, "start", 1).content == "a\r\n"
    assert s.version(m.id, "start", 99) is None


def test_put_unknown_mcp(env):
    s, _, owner, paths = env
    with pytest.raises(McpNotFoundError):
        s.put(999, "start", U(".ps1", "exit 0"), owner.id)
    assert list(paths.scripts_dir.iterdir()) == []


def test_put_invalid_input_changes_nothing(env):
    s, _, owner, paths = env
    m = s.create_mcp(cfg(), owner.id, {"start": U(".ps1", "a"), "stop": U(".ps1", "b")})
    before = _tree(paths.scripts_dir)
    for kind, upload, code in [
        ("start", U(".ps1", " "), "script_empty"),
        ("start", U(".exe", "x"), "validation"),
        ("../../evil", U(".ps1", "x"), "validation"),
    ]:
        with pytest.raises(ScriptValidationError) as e:
            s.put(m.id, kind, upload, owner.id)
        assert e.value.code == code
    assert _tree(paths.scripts_dir) == before and s.get(m.id, "start").version == 1


def test_put_write_failure_rolls_back_row_and_keeps_old_file(env, monkeypatch):
    s, _, owner, paths = env
    m = s.create_mcp(cfg(), owner.id, {"start": U(".ps1", "old"), "stop": U(".ps1", "b")})
    before = s.get(m.id, "start")
    old_bytes = before.path.read_bytes()

    def boom(a, b):
        raise OSError("disk")

    monkeypatch.setattr(mod.os, "replace", boom)
    with pytest.raises(OSError):
        s.put(m.id, "start", U(".cmd", "echo new"), owner.id)
    monkeypatch.undo()
    assert s.get(m.id, "start") == before and [v.version for v in s.versions(m.id, "start")] == [1]
    assert before.path.read_bytes() == old_bytes
    assert _tree(paths.scripts_dir / str(m.id)) == ["start.ps1", "stop.ps1"]  # no partial/tmp file


def test_failed_put_does_not_burn_a_version_number(env, monkeypatch):
    s, _, owner, _ = env
    m = s.create_mcp(cfg(), owner.id, {"start": U(".ps1", "a"), "stop": U(".ps1", "b")})
    real = mod.os.replace
    monkeypatch.setattr(mod.os, "replace", lambda a, b: (_ for _ in ()).throw(OSError("x")))
    with pytest.raises(OSError):
        s.put(m.id, "start", U(".ps1", "c"), owner.id)
    monkeypatch.setattr(mod.os, "replace", real)
    assert s.put(m.id, "start", U(".ps1", "c"), owner.id).version == 2


# ---- delete ----


@windows_only
def test_delete_only_restart(env):
    s, _, owner, paths = env
    m = s.create_mcp(cfg(), owner.id, {**BASIC, "restart": U(".bat", "exit /b 0")})
    s.delete(m.id, "restart", owner.id)
    assert s.get(m.id, "restart") is None and not (paths.scripts_dir / str(m.id) / "restart.bat").exists()
    assert s.content(m.id, "restart") is None
    marker = s.versions(m.id, "restart")[0]
    assert marker.deleted is True and marker.version == 2 and marker.author_id == owner.id
    assert (marker.ext, marker.sha256, marker.content) == (None, None, None)
    with pytest.raises(ScriptRequiredError):
        s.delete(m.id, "start", owner.id)
    with pytest.raises(ScriptRequiredError):
        s.delete(m.id, "stop", owner.id)
    assert s.get(m.id, "start") is not None


def test_delete_missing_restart_and_bad_kind(env):
    s, _, owner, _ = env
    m = s.create_mcp(cfg(), owner.id, {"start": U(".ps1", "a"), "stop": U(".ps1", "b")})
    with pytest.raises(ScriptNotFoundError):
        s.delete(m.id, "restart", owner.id)
    with pytest.raises(ScriptValidationError):
        s.delete(m.id, "../start", owner.id)
    assert s.versions(m.id, "restart") == []


def test_put_after_delete_continues_numbering(env):
    s, _, owner, _ = env
    m = s.create_mcp(
        cfg(), owner.id, {"start": U(".ps1", "a"), "stop": U(".ps1", "b"), "restart": U(".ps1", "r")}
    )
    s.delete(m.id, "restart", owner.id)
    assert s.put(m.id, "restart", U(".ps1", "r2"), owner.id).version == 3
    assert [v.version for v in s.versions(m.id, "restart")] == [3, 2, 1]


# ---- revert ----


@windows_only
def test_revert(env):
    s, _, owner, _ = env
    m = s.create_mcp(cfg(), owner.id, BASIC)
    v1 = s.get(m.id, "start")
    s.put(m.id, "start", U(".ps1", "exit 0"), owner.id)
    info = s.revert(m.id, "start", 1, owner.id)
    assert (info.version, info.ext, info.sha256) == (3, ".bat", v1.sha256)
    assert info.path.read_bytes() == v1.path.read_bytes() if v1.path == info.path else True
    assert hashlib.sha256(info.path.read_bytes()).hexdigest() == v1.sha256
    assert [v.version for v in s.versions(m.id, "start")] == [3, 2, 1]  # history kept, new version added
    assert s.content(m.id, "start") == "@echo off\r\nexit /b 0\r\n"


def test_revert_ps1_korean_restores_exact_bytes(env):
    s, _, owner, _ = env
    m = s.create_mcp(
        cfg(), owner.id, {"start": U(".ps1", "Write-Output '시작'\n"), "stop": U(".ps1", "b")}
    )
    original = s.get(m.id, "start").path.read_bytes()
    s.put(m.id, "start", U(".ps1", "Write-Output '변경'"), owner.id)
    assert s.get(m.id, "start").path.read_bytes() != original
    info = s.revert(m.id, "start", 1, owner.id)
    assert info.version == 3 and info.path.read_bytes() == original


def test_revert_to_deleted_marker_and_missing_version(env):
    s, _, owner, _ = env
    m = s.create_mcp(
        cfg(), owner.id, {"start": U(".ps1", "a"), "stop": U(".ps1", "b"), "restart": U(".ps1", "r")}
    )
    s.delete(m.id, "restart", owner.id)
    with pytest.raises(ScriptValidationError) as e:
        s.revert(m.id, "restart", 2, owner.id)
    assert e.value.code == "validation"
    with pytest.raises(ScriptNotFoundError):
        s.revert(m.id, "restart", 42, owner.id)
    # reverting to the pre-deletion version brings the script back as a new version
    assert s.revert(m.id, "restart", 1, owner.id).version == 3
    assert s.get(m.id, "restart") is not None


def test_revert_write_failure_rolls_back(env, monkeypatch):
    s, _, owner, _ = env
    m = s.create_mcp(cfg(), owner.id, {"start": U(".ps1", "a"), "stop": U(".ps1", "b")})
    s.put(m.id, "start", U(".ps1", "c"), owner.id)
    before = s.get(m.id, "start")
    monkeypatch.setattr(mod.os, "replace", lambda a, b: (_ for _ in ()).throw(OSError("x")))
    with pytest.raises(OSError):
        s.revert(m.id, "start", 1, owner.id)
    monkeypatch.undo()
    assert s.get(m.id, "start") == before
    assert hashlib.sha256(before.path.read_bytes()).hexdigest() == before.sha256


# ---- remove_dir / paths ----


def test_remove_dir(env):
    s, _, owner, paths = env
    m = s.create_mcp(cfg(), owner.id, {"start": U(".ps1", "a"), "stop": U(".ps1", "b")})
    s.remove_dir(m.id)
    assert list(paths.scripts_dir.iterdir()) == []
    s.remove_dir(m.id)  # idempotent


def test_files_stay_inside_the_mcp_directory(env):
    s, _, owner, paths = env
    m = s.create_mcp(cfg(), owner.id, {"start": U(".ps1", "a"), "stop": U(".ps1", "b")})
    for kind in ("../../start", "..\\start", "start/../../x", "con", ""):
        assert s.get(m.id, kind) is None
        with pytest.raises(ScriptValidationError):
            s.put(m.id, kind, U(".ps1", "x"), owner.id)
    root = paths.scripts_dir.resolve()
    for p in root.rglob("*"):
        assert root in p.resolve().parents
    assert [p.name for p in root.iterdir()] == [str(m.id)]
