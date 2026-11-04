# Plan 1 — Core Service & Auth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 이후 모든 기능이 올라갈 백엔드 코어를 만듭니다. 범위는 프로젝트 골격, 설정 저장소, 일일 JSONL 로그, 채널 2개 서버(Local 127.0.0.1:8700 / External 0.0.0.0:8701), 이메일 + Dummy OTP 로그인, 역할 기반 권한 정책, 사용자 관리 API, 전역 설정 API입니다.

**Architecture:** 하나의 Python 프로세스 안에서 같은 `Services` 묶음을 공유하는 FastAPI 앱 두 개를 띄웁니다. Local 전용 라우터는 Local 앱에만 등록해서, External 포트에는 해당 경로가 아예 존재하지 않게 합니다. 모든 권한 판단은 `can(user, action, channel, owner_id)` 함수 하나로 모읍니다. 저장소는 SQLite(WAL) 파일 하나이고, 로그는 KST 날짜별 JSONL 파일에 배치로 기록합니다.

**Tech Stack:** Python 3.15.x(조건부로 3.14.x), uv, FastAPI, Uvicorn, Pydantic v2, pytest, pytest-asyncio, httpx, pip-audit

**Spec:** `docs/PLAN.md` (v0.4). 이 계획은 §4(인증·권한), §5.1, §5.2, §5.6(로그 기록 부분), §6.4-7의 설정 항목, §9.1을 구현합니다.

### 전체 로드맵 (spec을 서브시스템 단위로 나눈 계획들)
| Plan | 범위 | 실행 환경 |
|---|---|---|
| **1 (이 문서)** | 코어 서비스, 로그 기록, 채널 2개, OTP 로그인, 권한, 사용자·설정 API | 개발 PC |
| 2 | Dummy MCP 3종 + chaos, 프로브, 상태 머신, 스크립트 실행기(예외 격리, 120초 타임아웃), MCP·스크립트·소유권 API | 개발 PC |
| 3 | 웹 UI: 디자인 시스템, 상태 보드, 로그인, MCP 관리, 사용자·설정·고지 편집 화면 | 개발 PC |
| 4 | Windows 수집: RDP 세션, 프로세스·PowerShell, 세션 에이전트, 연결마다 고지 다이얼로그, 우회 탐지, localhost Windows 계정 식별 | **Win 11 Pro** |
| 5 | 로그 조회(인덱스·필터·히스토그램), 보존 정리와 미리보기, 패키징·서비스 등록·설치 스크립트 | 개발 PC + Win 11 Pro |

## Global Constraints

- 코드는 `server/` 아래에 둡니다. 패키지명은 `app`, 테스트는 `server/tests/`입니다. 모든 명령은 `server/`에서 `uv run ...`으로 실행합니다.
- Python: 3.15 최신 패치에서 `pywin32`, `psutil`, `pyinstaller`, `pydantic-core`의 Windows 휠이 **모두** 설치되면 3.15를 쓰고, 하나라도 안 되면 3.14 최신 패치(3.14.10 이상)를 씁니다. 결정한 버전은 `server/.python-version`에 기록합니다.
- 의존성은 `uv.lock`으로 고정합니다. `uv run pip-audit`에서 취약점이 0건이어야 합니다.
- 시간은 내부적으로 UTC aware `datetime`으로 다룹니다. 로그 `ts`와 일일 파일 날짜는 **KST(UTC+09:00, 고정 오프셋)** 기준이며, `datetime.timezone(timedelta(hours=9))`를 씁니다. 한국은 일광절약시간이 없어서 `tzdata`가 필요 없습니다.
- 로그 파일: `logs/YYYY-MM-DD.jsonl`, UTF-8, 한 줄에 JSON 하나(`json.dumps(event, ensure_ascii=False)`, 기본 구분자), `ts`는 ISO 8601 밀리초 + `+09:00`.
- 포트: Local `127.0.0.1:8700`, External `0.0.0.0:8701` (CLI로 변경 가능).
- 역할 코드: `developer`(화면 표기 "MCP 개발자"), `admin`(화면 표기 "Admin"). 익명은 `None`입니다.
- OTP: 6자리 숫자, 유효 300초, 1회용, 5회 틀리면 무효, 재발송 쿨다운 60초, IP당 600초에 10회까지.
- 세션: 쿠키 `mcpmon_sid`, `HttpOnly`, `SameSite=Strict`, `Path=/`. 최대 8시간, 유휴 30분. 변경 요청(POST/PUT/PATCH/DELETE)에는 `X-CSRF-Token` 헤더가 필요합니다.
- 전역 설정 범위: `ping_interval_sec` 1–300(기본 5), `issue_check_interval_sec` 5–60(기본 10), `confirm_interval_sec` 1–10(기본 1), `log_retention_days` 7–3650(기본 180), `log_compress_after_days` 1–`log_retention_days`(기본 30), `service_start_type` ∈ {`auto`, `delayed-auto`, `manual`}(기본 `delayed-auto`), `otp_provider` ∈ {`dummy`}(기본 `dummy`).
- API 오류 본문은 `{"error": "<code>"}` 형식입니다. 코드: `login_required`(401), `forbidden`(403), `csrf`(403), `not_found`(404), `user_exists`(409), `last_admin`(409), `bootstrap_done`(409), `invalid_email`(422), `validation`(422), `rate_limited`(429, `Retry-After` 헤더 포함).

## Review Focus

1. **대소문자·공백이 섞인 이메일**(`"  Hong@Corp.COM "`): 등록과 로그인 모두 같은 사용자로 처리해야 합니다. → Task 5 `test_email_normalized`, Task 10 `test_login_with_mixed_case_email`
2. **유효한 Admin 쿠키를 가지고 External 포트로 Local 전용 API를 호출**: 403이 아니라 404여야 하고, 라우트의 존재 자체가 드러나지 않아야 합니다. → Task 11 `test_users_api_absent_on_external`
3. **등록되지 않은 이메일로 OTP 요청**: 등록된 이메일과 똑같이 202로 응답하고, 발송 기록은 남지 않아야 합니다. → Task 7 `test_unknown_email_silent`, Task 10 `test_request_unknown_email_same_response`
4. **배치 버퍼에 이벤트가 있는 동안 KST 자정이 지나는 경우**: 각 이벤트가 자기 `ts` 날짜의 파일에 들어가야 합니다. → Task 4 `test_batch_split_across_midnight`
5. **로그인 중인 사용자를 비활성화하거나 강등하는 경우**: 기존 세션이 즉시 무효가 되어야 합니다. 그리고 두 Admin이 동시에 서로를 강등해도 Admin이 최소 1명 남아야 합니다. → Task 11 `test_deactivate_revokes_session`, Task 5 `test_concurrent_demotion_keeps_one_admin`

---

### Task 1: 저장소와 런타임 준비

**Files:**
- Create: `.gitignore`, `server/pyproject.toml`, `server/.python-version`, `server/app/__init__.py`, `server/tests/test_smoke.py`

**Interfaces:**
- Produces: `app.__version__ = "0.1.0"`

- [ ] **Step 1: git 저장소 초기화**

Run: `git init` (프로젝트 루트). `.gitignore`에는 `.venv/`, `__pycache__/`, `*.pyc`, `server/.pytest_cache/`, `/logs/`, `/data/`, `/scripts/`, `node_modules/`, `dist/`를 넣습니다.

- [ ] **Step 2: uv 설치 확인**

Run: `uv --version`. 없으면 `winget install --id astral-sh.uv -e`로 설치한 뒤 새 셸에서 다시 확인합니다.
Expected: `uv 0.x.y` 출력

- [ ] **Step 3: Python 버전 결정**

Run:
```bash
uv python install 3.15
uv venv %TEMP%\py315check --python 3.15
uv pip install --python %TEMP%\py315check --only-binary :all: pywin32 psutil pyinstaller pydantic-core
```
Expected: 4개 모두 설치되면 `3.15`를 씁니다. 하나라도 실패하면 `uv python install 3.14`를 실행하고 `3.14`를 씁니다. 결정한 버전을 `server/.python-version`에 적고, 확인용 venv는 삭제합니다.

- [ ] **Step 4: 프로젝트 생성**

`server/pyproject.toml`을 만듭니다. `name = "mcp-monitor"`, `requires-python`은 결정한 버전에 맞춥니다.
- 런타임 의존성: `fastapi`, `uvicorn[standard]`, `pydantic`
- dev 의존성: `pytest`, `pytest-asyncio`, `httpx`, `pip-audit`
- `[tool.pytest.ini_options]`: `asyncio_mode = "auto"`, `testpaths = ["tests"]`

Run: `uv sync`

- [ ] **Step 5: 스모크 테스트 작성**

```python
# server/tests/test_smoke.py
import app

def test_version():
    assert app.__version__ == "0.1.0"
```

- [ ] **Step 6: 테스트와 보안 점검 실행**

Run: `uv run pytest -q` → `1 passed`
Run: `uv run pip-audit` → `No known vulnerabilities found`

- [ ] **Step 7: Commit**

```bash
git add .gitignore server/ docs/
git commit -m "chore: bootstrap server project and pin runtime"
```

---

### Task 2: 시계, 경로, 데이터베이스

**Files:**
- Create: `server/app/clock.py`, `server/app/paths.py`, `server/app/db.py`, `server/tests/conftest.py`, `server/tests/fakes.py`, `server/tests/test_db.py`

**Interfaces:**
- Produces:
  - `app.clock.KST: timezone` (UTC+9)
  - `app.clock.Clock` (Protocol): `now() -> datetime` (UTC aware)
  - `app.clock.SystemClock`
  - `app.clock.to_kst_iso(dt: datetime) -> str`: `"2026-11-04T14:03:22.418+09:00"` 형식
  - `tests.fakes.FakeClock(start: datetime)`: `.now()`, `.advance(seconds: float) -> None`
  - `app.paths.AppPaths(root: Path)` (frozen dataclass): `.logs_dir`, `.data_dir`, `.dev_dir`(= `data/dev`), `.scripts_dir`, `.db_path`(= `data/config.db`), `.ensure() -> None`
  - `app.db.Database(path: Path)`:
    - `.query(sql: str, params: Sequence = ()) -> list[sqlite3.Row]`
    - `.execute(sql: str, params: Sequence = ()) -> int` (lastrowid)
    - `.transaction() -> ContextManager[sqlite3.Connection]` (`BEGIN IMMEDIATE`)
    - `.migrate() -> None`
    - `.close()`
  - conftest fixtures: `clock` (FakeClock, 2026-11-04T05:00:00Z), `paths` (tmp_path 기반, `ensure()` 호출됨), `db` (migrate 완료)

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_db.py
from datetime import datetime, timezone
from app.clock import to_kst_iso

def test_kst_iso():
    dt = datetime(2026, 11, 4, 15, 0, 0, 5000, tzinfo=timezone.utc)
    assert to_kst_iso(dt) == "2026-11-05T00:00:00.005+09:00"

def test_migrate_creates_tables(db):
    names = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"settings", "users", "otp_codes", "otp_ip_requests", "auth_sessions", "secrets"} <= names
    assert db.query("PRAGMA journal_mode")[0][0] == "wal"

def test_migrate_idempotent(db):
    db.migrate()
    assert db.query("PRAGMA user_version")[0][0] == 1

def test_transaction_rollback(db):
    try:
        with db.transaction() as conn:
            conn.execute("INSERT INTO secrets(name, value) VALUES ('x', 'y')")
            raise RuntimeError
    except RuntimeError:
        pass
    assert db.query("SELECT * FROM secrets WHERE name='x'") == []
```

- [ ] **Step 2: 실패 확인**

Run: `uv run pytest tests/test_db.py -v` → FAIL (`ModuleNotFoundError: app.clock`)

- [ ] **Step 3: 구현**

- `Database`는 `sqlite3.connect(path, check_same_thread=False, isolation_level=None)`로 연결하고 `row_factory = sqlite3.Row`를 씁니다. 모든 호출은 `threading.RLock`으로 직렬화합니다. 연결 시 `PRAGMA journal_mode=WAL`, `PRAGMA foreign_keys=ON`을 설정합니다.
- `migrate()`는 `MIGRATIONS: list[str]`의 각 항목을 `PRAGMA user_version` 이후부터 차례로 적용합니다.
- 마이그레이션 1의 테이블:
  - `settings(key TEXT PRIMARY KEY, value TEXT NOT NULL)`
  - `users(id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE, name TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('developer','admin')), active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, created_by INTEGER, last_login_at TEXT)`
  - `otp_codes(email TEXT PRIMARY KEY, code_hash TEXT, expires_at TEXT, attempts INTEGER NOT NULL DEFAULT 0, last_sent_at TEXT NOT NULL)`
  - `otp_ip_requests(ip TEXT NOT NULL, at TEXT NOT NULL)`
  - `auth_sessions(id_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), channel TEXT NOT NULL, csrf_token TEXT NOT NULL, created_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, ip TEXT, user_agent TEXT)`
  - `secrets(name TEXT PRIMARY KEY, value TEXT NOT NULL)`

- [ ] **Step 4: 통과 확인**

Run: `uv run pytest tests/test_db.py -v` → 4 passed

- [ ] **Step 5: Commit**

```bash
git add server/app server/tests
git commit -m "feat: add clock, app paths and sqlite database with migrations"
```

---

### Task 3: 설정 저장소

**Files:**
- Create: `server/app/settings/__init__.py`, `server/app/settings/store.py`, `server/tests/test_settings_store.py`

**Interfaces:**
- Consumes: `Database`
- Produces:
  - `app.settings.store.Settings` (pydantic `BaseModel`): Global Constraints의 필드·범위·기본값 그대로. `log_compress_after_days <= log_retention_days`는 model validator로 검사합니다.
  - `SettingsStore(db: Database)`:
    - `.get() -> Settings`: 저장된 값이 없으면 기본값
    - `.update(patch: Mapping[str, Any]) -> Settings`: 잘못된 값이면 `pydantic.ValidationError`. 알 수 없는 키도 거부합니다 (`extra="forbid"`).

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_settings_store.py
import pytest
from pydantic import ValidationError
from app.settings.store import SettingsStore

def test_defaults(db):
    s = SettingsStore(db).get()
    assert (s.ping_interval_sec, s.issue_check_interval_sec, s.confirm_interval_sec) == (5, 10, 1)
    assert (s.log_retention_days, s.log_compress_after_days) == (180, 30)
    assert s.service_start_type == "delayed-auto" and s.otp_provider == "dummy"

def test_update_persists(db):
    SettingsStore(db).update({"ping_interval_sec": 30, "log_retention_days": 365})
    s = SettingsStore(db).get()
    assert s.ping_interval_sec == 30 and s.log_retention_days == 365

@pytest.mark.parametrize("patch", [
    {"ping_interval_sec": 0}, {"ping_interval_sec": 301},
    {"log_retention_days": 6}, {"log_retention_days": 3651},
    {"log_retention_days": 20, "log_compress_after_days": 21},
    {"service_start_type": "boot"}, {"unknown_key": 1},
])
def test_update_rejects(db, patch):
    with pytest.raises(ValidationError):
        SettingsStore(db).update(patch)
    assert SettingsStore(db).get().ping_interval_sec == 5
```

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_settings_store.py -v` → FAIL

- [ ] **Step 3: 구현**

`settings` 테이블에 키 하나 `"global"`로 JSON 전체를 저장합니다. `update`는 현재 값에 patch를 합쳐 `Settings.model_validate`로 검증한 다음 저장합니다.

- [ ] **Step 4: 통과 확인** — Run: `uv run pytest tests/test_settings_store.py -v` → 9 passed

- [ ] **Step 5: Commit** — `git commit -m "feat: add validated global settings store"`

---

### Task 4: 일일 JSONL 로그 기록기

**Files:**
- Create: `server/app/logstore/__init__.py`, `server/app/logstore/writer.py`, `server/tests/test_log_writer.py`

**Interfaces:**
- Consumes: `Clock`, `to_kst_iso`, `AppPaths.logs_dir`
- Produces:
  - `DailyJsonlWriter(logs_dir: Path)`:
    - `.write_batch(events: Sequence[Mapping[str, Any]]) -> None`
    - 각 event에는 `ts`(ISO, 오프셋 포함)와 `cat`이 반드시 있어야 합니다.
    - 파일은 `ts`를 KST로 바꾼 날짜로 고릅니다.
  - `LogWriter(daily: DailyJsonlWriter, clock: Clock, flush_interval: float = 0.2, max_batch: int = 500)`:
    - `.emit(cat: str, **fields: Any) -> None`: 막히지 않는 호출입니다. 현재 시각을 `ts`로 붙여 큐에 넣습니다.
    - `async .start() -> None`
    - `async .stop() -> None`: 남은 이벤트를 모두 기록한 뒤 종료합니다.
    - `async .flush() -> None`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_log_writer.py
import json
from app.logstore.writer import DailyJsonlWriter, LogWriter

def read(paths, day):
    return [json.loads(l) for l in (paths.logs_dir / f"{day}.jsonl").read_text("utf-8").splitlines()]

def test_batch_split_across_midnight(paths):
    w = DailyJsonlWriter(paths.logs_dir)
    w.write_batch([
        {"ts": "2026-11-04T23:59:59.999+09:00", "cat": "system", "msg": "a"},
        {"ts": "2026-11-04T15:00:00.000+00:00", "cat": "system", "msg": "b"},  # = 11-05 00:00 KST
    ])
    assert [e["msg"] for e in read(paths, "2026-11-04")] == ["a"]
    assert [e["msg"] for e in read(paths, "2026-11-05")] == ["b"]

def test_korean_not_escaped(paths):
    DailyJsonlWriter(paths.logs_dir).write_batch([{"ts": "2026-11-04T10:00:00.000+09:00", "cat": "system", "msg": "접속"}])
    assert "접속" in (paths.logs_dir / "2026-11-04.jsonl").read_text("utf-8")

async def test_emit_and_stop_flushes(paths, clock):
    lw = LogWriter(DailyJsonlWriter(paths.logs_dir), clock, flush_interval=60)
    await lw.start()
    for i in range(3):
        lw.emit("auth", n=i)
    await lw.stop()
    rows = read(paths, "2026-11-04")
    assert [r["n"] for r in rows] == [0, 1, 2]
    assert rows[0]["ts"] == "2026-11-04T14:00:00.000+09:00" and rows[0]["cat"] == "auth"

async def test_max_batch_triggers_write(paths, clock):
    lw = LogWriter(DailyJsonlWriter(paths.logs_dir), clock, flush_interval=60, max_batch=2)
    await lw.start()
    lw.emit("system", n=1); lw.emit("system", n=2)
    await lw.flush()
    assert len(read(paths, "2026-11-04")) == 2
    await lw.stop()
```

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_log_writer.py -v` → FAIL

- [ ] **Step 3: 구현**

- `LogWriter`는 `asyncio.Queue`와 백그라운드 task를 씁니다. `flush_interval` 경과, `max_batch` 도달, `flush()` 호출, `stop()` 호출 중 하나가 일어나면 쌓인 묶음을 기록합니다.
- 파일 쓰기는 `asyncio.to_thread(daily.write_batch, batch)`로 이벤트 루프 밖에서 합니다. 파일은 append 모드로 열고, 날짜별로 묶어 한 번씩만 엽니다.
- 쓰기에 실패해도(디스크 가득 참 등) 예외로 task가 죽지 않게 합니다. stderr에 경고를 남기고 묶음을 재시도 큐에 한 번 다시 넣습니다.

- [ ] **Step 4: 통과 확인** — Run: `uv run pytest tests/test_log_writer.py -v` → 4 passed

- [ ] **Step 5: Commit** — `git commit -m "feat: add batched daily jsonl log writer (KST)"`

---

### Task 5: 사용자 저장소

**Files:**
- Create: `server/app/users/__init__.py`, `server/app/users/store.py`, `server/tests/test_user_store.py`

**Interfaces:**
- Consumes: `Database`, `Clock`
- Produces:
  - `Role = Literal["developer", "admin"]`
  - `User` (frozen dataclass): `id: int`, `email: str`, `name: str`, `role: Role`, `active: bool`, `created_at: datetime`, `created_by: int | None`, `last_login_at: datetime | None`
  - `normalize_email(raw: str) -> str`: strip + lower. `^[^@\s]+@[^@\s]+\.[^@\s]+$`에 맞지 않으면 `InvalidEmailError`
  - 예외: `UserExistsError`, `LastAdminError`, `UserNotFoundError`
  - `UserStore(db: Database, clock: Clock)`:
    - `.create(email, name, role, created_by: int | None) -> User`
    - `.get(user_id) -> User | None`
    - `.get_by_email(email) -> User | None` (정규화 후 조회)
    - `.list() -> list[User]`
    - `.set_role(user_id, role) -> User`
    - `.set_active(user_id, active) -> User`
    - `.set_name(user_id, name) -> User`
    - `.touch_login(user_id) -> None`
    - `.count() -> int`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_user_store.py
import threading, pytest
from app.users.store import UserStore, InvalidEmailError, UserExistsError, LastAdminError

def test_email_normalized(db, clock):
    s = UserStore(db, clock)
    u = s.create("  Hong@Corp.COM ", "홍길동", "developer", None)
    assert u.email == "hong@corp.com"
    assert s.get_by_email("HONG@corp.com ").id == u.id

@pytest.mark.parametrize("bad", ["", "hong", "a@b", "a b@c.com", "a@@c.com"])
def test_invalid_email(db, clock, bad):
    with pytest.raises(InvalidEmailError):
        UserStore(db, clock).create(bad, "x", "developer", None)

def test_duplicate(db, clock):
    s = UserStore(db, clock); s.create("a@x.com", "a", "admin", None)
    with pytest.raises(UserExistsError):
        s.create("A@X.com", "a2", "developer", None)

def test_last_admin_protected(db, clock):
    s = UserStore(db, clock); a = s.create("a@x.com", "a", "admin", None)
    with pytest.raises(LastAdminError): s.set_role(a.id, "developer")
    with pytest.raises(LastAdminError): s.set_active(a.id, False)
    b = s.create("b@x.com", "b", "admin", a.id)
    assert s.set_role(a.id, "developer").role == "developer"
    with pytest.raises(LastAdminError): s.set_active(b.id, False)

def test_inactive_admin_not_counted(db, clock):
    s = UserStore(db, clock); a = s.create("a@x.com", "a", "admin", None)
    b = s.create("b@x.com", "b", "admin", a.id); s.set_active(b.id, False)
    with pytest.raises(LastAdminError): s.set_role(a.id, "developer")

def test_concurrent_demotion_keeps_one_admin(db, clock):
    s = UserStore(db, clock); a = s.create("a@x.com", "a", "admin", None); b = s.create("b@x.com", "b", "admin", a.id)
    barrier = threading.Barrier(2); errors = []
    def demote(uid):
        barrier.wait()
        try: s.set_role(uid, "developer")
        except LastAdminError as e: errors.append(e)
    ts = [threading.Thread(target=demote, args=(u,)) for u in (a.id, b.id)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert len(errors) == 1
    assert sum(u.role == "admin" and u.active for u in s.list()) == 1
```

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_user_store.py -v` → FAIL

- [ ] **Step 3: 구현**

마지막 Admin 검사는 `db.transaction()`(BEGIN IMMEDIATE) 안에서 "활성 Admin 수 조회 → 변경"을 함께 수행해서 경쟁 상태를 막습니다. 이름이 비어 있으면 `ValueError`를 냅니다.

- [ ] **Step 4: 통과 확인** — Run: `uv run pytest tests/test_user_store.py -v` → 10 passed

- [ ] **Step 5: Commit** — `git commit -m "feat: add user store with email normalization and last-admin guard"`

---

### Task 6: 권한 정책 `can()`

**Files:**
- Create: `server/app/auth/__init__.py`, `server/app/auth/policy.py`, `server/app/web/__init__.py`, `server/app/web/channels.py`, `server/tests/test_policy.py`

**Interfaces:**
- Consumes: `User`
- Produces:
  - `app.web.channels.Channel = Literal["local", "external"]`
  - `app.auth.policy.Action` (StrEnum): `VIEW_BOARD`, `VIEW_MCP_HISTORY`, `VIEW_SESSION_HISTORY`, `VIEW_LOGS`, `EXPORT_LOGS`, `VIEW_AUDIT`, `EDIT_MCP_SETTINGS`, `MCP_MANUAL_ACTION`, `CREATE_MCP`, `DELETE_MCP`, `EDIT_SCRIPTS`, `TRANSFER_OWNERSHIP`, `MANAGE_USERS`, `EDIT_GLOBAL_SETTINGS`, `EDIT_RETENTION`, `EDIT_NOTICE`
  - `can(user: User | None, action: Action, channel: Channel, owner_id: int | None = None) -> bool`: `user.active == False`이면 익명으로 취급합니다.

- [ ] **Step 1: 실패하는 테스트 작성 (spec §4.3 매트릭스 전체)**

```python
# server/tests/test_policy.py
import pytest
from datetime import datetime, timezone
from app.auth.policy import Action as A, can
from app.users.store import User

def mk(role, uid=1, active=True):
    return User(uid, f"{uid}@x.com", "n", role, active, datetime.now(timezone.utc), None, None)

DEV, ADM = mk("developer", 1), mk("admin", 2)
# (action, 익명, 개발자, Admin, local_only, owner_only)
MATRIX = [
    (A.VIEW_BOARD,           1, 1, 1, False, False),
    (A.VIEW_MCP_HISTORY,     0, 1, 1, False, False),
    (A.VIEW_SESSION_HISTORY, 0, 1, 1, False, False),
    (A.VIEW_LOGS,            0, 1, 1, False, False),
    (A.EXPORT_LOGS,          0, 1, 1, False, False),
    (A.VIEW_AUDIT,           0, 1, 1, False, False),
    (A.EDIT_MCP_SETTINGS,    0, 1, 1, False, False),
    (A.MCP_MANUAL_ACTION,    0, 1, 1, False, False),
    (A.CREATE_MCP,           0, 1, 1, True,  False),
    (A.EDIT_SCRIPTS,         0, 1, 1, True,  True),
    (A.TRANSFER_OWNERSHIP,   0, 0, 1, True,  False),
    (A.MANAGE_USERS,         0, 0, 1, True,  False),
    (A.EDIT_GLOBAL_SETTINGS, 0, 0, 1, True,  False),
    (A.EDIT_RETENTION,       0, 0, 1, True,  False),
    (A.EDIT_NOTICE,          0, 0, 1, True,  False),
]

@pytest.mark.parametrize("action,anon,dev,adm,local_only,owner_only", MATRIX)
@pytest.mark.parametrize("channel", ["local", "external"])
@pytest.mark.parametrize("is_owner", [True, False])
def test_matrix(action, anon, dev, adm, local_only, owner_only, channel, is_owner):
    for user, allowed in ((None, anon), (DEV, dev), (ADM, adm)):
        owner = (user.id if user else 99) if is_owner else 99
        expected = bool(allowed) and (channel == "local" or not local_only) and (not owner_only or (user is not None and owner == user.id))
        assert can(user, action, channel, owner_id=owner) is expected, (action, user and user.role, channel, is_owner)

@pytest.mark.parametrize("channel", ["local", "external"])
def test_delete_mcp(channel):
    local = channel == "local"
    assert can(DEV, A.DELETE_MCP, channel, owner_id=DEV.id) is local
    assert can(DEV, A.DELETE_MCP, channel, owner_id=99) is False
    assert can(ADM, A.DELETE_MCP, channel, owner_id=99) is local
    assert can(None, A.DELETE_MCP, channel, owner_id=99) is False

def test_inactive_user_is_anonymous():
    assert can(mk("admin", 3, active=False), A.VIEW_LOGS, "local") is False
    assert can(mk("admin", 3, active=False), A.VIEW_BOARD, "local") is True

def test_admin_scripts_not_exempt():
    assert can(ADM, A.EDIT_SCRIPTS, "local", owner_id=99) is False
```

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_policy.py -v` → FAIL

- [ ] **Step 3: 구현**

규칙을 `Action → (최소 역할, local_only, owner_rule)` 표 하나로 선언하고, `can`은 그 표를 해석하기만 합니다. `DELETE_MCP`의 owner_rule은 "developer는 소유자만, admin은 모두"입니다.

- [ ] **Step 4: 통과 확인** — Run: `uv run pytest tests/test_policy.py -v` → 64 passed

- [ ] **Step 5: Commit** — `git commit -m "feat: add single permission policy matching spec matrix"`

---

### Task 7: OTP 서비스와 Dummy 공급자

**Files:**
- Create: `server/app/auth/otp.py`, `server/tests/test_otp.py`
- Modify: `server/tests/fakes.py` (`CapturingOtpProvider` 추가)

**Interfaces:**
- Consumes: `Database`, `UserStore`, `Clock`, `User`
- Produces:
  - `OtpProvider` (Protocol): `send(email: str, code: str) -> None`
  - `DummyOtpProvider(outbox: Path, echo: Callable[[str], None] = print)`: `"<KST ts> <email> <code>"` 한 줄을 outbox에 덧붙이고 echo로도 출력합니다.
  - `tests.fakes.CapturingOtpProvider`: `.sent: list[tuple[str, str]]`
  - 상수: `OTP_TTL_SEC = 300`, `OTP_MAX_ATTEMPTS = 5`, `OTP_RESEND_COOLDOWN_SEC = 60`, `OTP_IP_LIMIT = 10`, `OTP_IP_WINDOW_SEC = 600`
  - 예외: `OtpRateLimitError(retry_after: int)`
  - `OtpService(db, users, provider, clock, secret: bytes, dev_fixed_code: str | None = None)`:
    - `.request(email: str, ip: str) -> None`: 쿨다운이나 IP 한도를 넘으면 `OtpRateLimitError`
    - `.verify(email: str, code: str) -> User | None`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_otp.py
import pytest
from app.auth.otp import OtpService, OtpRateLimitError, DummyOtpProvider
from app.users.store import UserStore
from tests.fakes import CapturingOtpProvider

@pytest.fixture
def env(db, clock):
    users = UserStore(db, clock); u = users.create("a@x.com", "a", "admin", None)
    p = CapturingOtpProvider()
    return OtpService(db, users, p, clock, secret=b"k" * 32), p, u, clock

def test_success_once(env):
    svc, p, u, _ = env
    svc.request("A@x.com", "1.1.1.1"); code = p.sent[-1][1]
    assert len(code) == 6 and code.isdigit()
    assert svc.verify("a@x.com", code).id == u.id
    assert svc.verify("a@x.com", code) is None  # 1회용

def test_expiry(env):
    svc, p, _, clock = env
    svc.request("a@x.com", "ip"); code = p.sent[-1][1]
    clock.advance(301)
    assert svc.verify("a@x.com", code) is None

def test_valid_just_before_expiry(env):
    svc, p, _, clock = env
    svc.request("a@x.com", "ip"); code = p.sent[-1][1]; clock.advance(299)
    assert svc.verify("a@x.com", code) is not None

def test_attempt_limit(env):
    svc, p, _, _ = env
    svc.request("a@x.com", "ip"); code = p.sent[-1][1]
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5): assert svc.verify("a@x.com", wrong) is None
    assert svc.verify("a@x.com", code) is None

def test_cooldown(env):
    svc, _, _, clock = env
    svc.request("a@x.com", "ip")
    with pytest.raises(OtpRateLimitError) as e: svc.request("a@x.com", "ip")
    assert 1 <= e.value.retry_after <= 60
    clock.advance(60); svc.request("a@x.com", "ip")

def test_unknown_email_silent(env):
    svc, p, _, _ = env
    svc.request("ghost@x.com", "ip")
    assert p.sent == []
    with pytest.raises(OtpRateLimitError): svc.request("ghost@x.com", "ip")  # 등록 여부와 무관하게 같은 동작

def test_ip_limit(env):
    svc, _, _, clock = env
    for i in range(10): svc.request(f"u{i}@x.com", "9.9.9.9")
    with pytest.raises(OtpRateLimitError): svc.request("u10@x.com", "9.9.9.9")
    clock.advance(601); svc.request("u10@x.com", "9.9.9.9")

def test_inactive_user_cannot_verify(env, db, clock):
    svc, p, u, _ = env
    UserStore(db, clock).create("b@x.com", "b", "admin", None)
    svc.request("a@x.com", "ip"); code = p.sent[-1][1]
    UserStore(db, clock).set_active(u.id, False)
    assert svc.verify("a@x.com", code) is None

def test_dev_fixed_code(db, clock):
    users = UserStore(db, clock); users.create("a@x.com", "a", "admin", None)
    svc = OtpService(db, users, CapturingOtpProvider(), clock, b"k" * 32, dev_fixed_code="000000")
    assert svc.verify("a@x.com", "000000") is not None

def test_dummy_provider_outbox(paths):
    lines = []
    DummyOtpProvider(paths.dev_dir / "otp-outbox.log", echo=lines.append).send("a@x.com", "123456")
    assert "a@x.com 123456" in (paths.dev_dir / "otp-outbox.log").read_text("utf-8")
    assert "123456" in lines[0]
```

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_otp.py -v` → FAIL

- [ ] **Step 3: 구현**

- 코드는 `secrets.randbelow(10**6)`로 만들고 6자리로 0을 채웁니다.
- 저장값은 `hmac.new(secret, f"{email}:{code}".encode(), "sha256").hexdigest()`이고, 비교는 `hmac.compare_digest`로 합니다.
- 등록되지 않았거나 비활성인 이메일도 `otp_codes`에 `code_hash=NULL`인 행을 만들어 쿨다운을 동일하게 적용합니다. 발송은 하지 않습니다.
- `dev_fixed_code`는 등록된 활성 사용자일 때만 통과시킵니다.

- [ ] **Step 4: 통과 확인** — Run: `uv run pytest tests/test_otp.py -v` → 10 passed

- [ ] **Step 5: Commit** — `git commit -m "feat: add OTP service with dummy provider and rate limits"`

---

### Task 8: 로그인 세션 저장소

**Files:**
- Create: `server/app/auth/sessions.py`, `server/tests/test_sessions.py`

**Interfaces:**
- Consumes: `Database`, `Clock`, `Channel`
- Produces:
  - 상수: `SESSION_ABSOLUTE_SEC = 28800`, `SESSION_IDLE_SEC = 1800`
  - `AuthSession` (dataclass): `user_id: int`, `channel: Channel`, `csrf_token: str`, `created_at: datetime`, `last_seen_at: datetime`
  - `SessionStore(db, clock)`:
    - `.create(user_id, channel, ip, user_agent) -> tuple[str, str]`: `(session_id, csrf_token)`
    - `.get(session_id, channel) -> AuthSession | None`: 성공하면 `last_seen_at`을 갱신합니다.
    - `.revoke(session_id) -> None`
    - `.revoke_user(user_id) -> None`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_sessions.py
from app.auth.sessions import SessionStore
from app.users.store import UserStore

def setup(db, clock):
    uid = UserStore(db, clock).create("a@x.com", "a", "admin", None).id
    return SessionStore(db, clock), uid

def test_idle_timeout(db, clock):
    s, uid = setup(db, clock); sid, _ = s.create(uid, "local", "127.0.0.1", "ua")
    clock.advance(29 * 60); assert s.get(sid, "local") is not None
    clock.advance(29 * 60); assert s.get(sid, "local") is not None  # 활동으로 연장
    clock.advance(31 * 60); assert s.get(sid, "local") is None

def test_absolute_timeout(db, clock):
    s, uid = setup(db, clock); sid, _ = s.create(uid, "local", "ip", "ua")
    for _ in range(16): clock.advance(29 * 60); s.get(sid, "local")  # 7h44m
    clock.advance(20 * 60); assert s.get(sid, "local") is None          # 8h04m

def test_channel_bound(db, clock):
    s, uid = setup(db, clock); sid, _ = s.create(uid, "external", "ip", "ua")
    assert s.get(sid, "local") is None and s.get(sid, "external") is not None

def test_revoke_user(db, clock):
    s, uid = setup(db, clock); a, _ = s.create(uid, "local", "ip", "ua"); b, _ = s.create(uid, "external", "ip", "ua")
    s.revoke_user(uid)
    assert s.get(a, "local") is None and s.get(b, "external") is None

def test_id_stored_hashed(db, clock):
    s, uid = setup(db, clock); sid, _ = s.create(uid, "local", "ip", "ua")
    assert db.query("SELECT 1 FROM auth_sessions WHERE id_hash = ?", (sid,)) == []
```

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_sessions.py -v` → FAIL

- [ ] **Step 3: 구현**

- `session_id = secrets.token_urlsafe(32)`, `csrf_token = secrets.token_urlsafe(24)`로 만듭니다.
- 저장 키는 `sha256(session_id)`입니다.
- 만료된 행은 `get`에서 발견하는 즉시 삭제합니다.

- [ ] **Step 4: 통과 확인** — Run: `uv run pytest tests/test_sessions.py -v` → 5 passed

- [ ] **Step 5: Commit** — `git commit -m "feat: add channel-bound auth sessions with idle and absolute expiry"`

---

### Task 9: 채널 2개 앱, 서비스 묶음, 서버 실행

**Files:**
- Create: `server/app/services.py`, `server/app/audit.py`, `server/app/web/app_factory.py`, `server/app/web/deps.py`, `server/app/web/shared_api.py`, `server/app/web/local_api.py`, `server/app/main.py`, `server/app/__main__.py`, `server/tests/test_channels.py`
- Modify: `server/tests/conftest.py` (`services`, `local_client`, `external_client` fixture 추가)

**Interfaces:**
- Consumes: Task 2–8의 모든 클래스
- Produces:
  - `AuditLogger(log: LogWriter)`:
    - `.auth(event: str, email: str, channel, ip, user_agent, ok: bool) -> None` → cat `auth`
    - `.admin(actor: User | None, action: str, channel, ip, target: Mapping, result: Literal["ok","denied","error"]) -> None` → cat `admin.audit`
  - `Services` (dataclass): `paths`, `db`, `clock`, `settings: SettingsStore`, `users: UserStore`, `otp: OtpService`, `sessions: SessionStore`, `log: LogWriter`, `audit: AuditLogger`
  - `build_services(root: Path, clock: Clock | None = None, otp_provider: OtpProvider | None = None, dev_fixed_code: str | None = None) -> Services`
    - OTP 비밀키는 `secrets` 테이블의 `otp_secret`입니다. 없으면 생성합니다.
    - 기본 공급자는 `DummyOtpProvider(paths.dev_dir / "otp-outbox.log")`입니다.
  - `create_app(channel: Channel, services: Services) -> FastAPI`: `shared_api.router`는 항상 등록하고, `local_api.router`는 `channel == "local"`일 때만 등록합니다. `app.state.channel`과 `app.state.services`를 설정합니다.
  - `deps.py`:
    - `get_channel(request) -> Channel`
    - `get_services(request) -> Services`
    - `current_user(request) -> User | None`: 쿠키 `mcpmon_sid` → `SessionStore.get` → `UserStore.get`
    - `require(action: Action, owner_id: Callable[[Request], int | None] | None = None)` → FastAPI dependency. 반환값은 `User | None`입니다.
      - 익명이 거부되면 401 `login_required`, 로그인 사용자가 거부되면 403 `forbidden`이고, 거부할 때마다 `audit.admin(..., result="denied")`를 남깁니다.
      - 세션이 있는 상태의 변경 메서드인데 `X-CSRF-Token` 헤더가 다르면 403 `csrf`입니다.
  - `GET /api/channel` (shared) → `{"channel": "local" | "external"}`
  - `main.server_configs(local_app, external_app, local_port: int = 8700, external_port: int = 8701) -> list[uvicorn.Config]`: host는 각각 `"127.0.0.1"`, `"0.0.0.0"`입니다.
  - `main.serve(root: Path, local_port: int, external_port: int) -> None` (async): 서비스 생성 → `log.start()` → 두 서버를 `asyncio.gather`로 실행합니다. 종료 시 `log.stop()`을 호출합니다.
  - CLI: `python -m app --root <dir> [--local-port 8700] [--external-port 8701]`
  - conftest:
    - `services` (FakeClock + CapturingOtpProvider, `log.start()`/`stop()` 포함)
    - `local_client`, `external_client`: `httpx.AsyncClient(transport=ASGITransport(app), base_url="http://test")`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_channels.py
from app.main import server_configs
from app.web import local_api

async def test_channel_reported(local_client, external_client):
    assert (await local_client.get("/api/channel")).json() == {"channel": "local"}
    assert (await external_client.get("/api/channel")).json() == {"channel": "external"}

def test_local_routes_absent_on_external(services):
    from app.web.app_factory import create_app
    ext_paths = {r.path for r in create_app("external", services).routes}
    local_only = {r.path for r in local_api.router.routes}
    assert local_only and not (ext_paths & local_only)

def test_bind_hosts(services):
    from app.web.app_factory import create_app
    cfgs = server_configs(create_app("local", services), create_app("external", services))
    assert [(c.host, c.port) for c in cfgs] == [("127.0.0.1", 8700), ("0.0.0.0", 8701)]
```

`local_api.router`가 비어 있지 않아야 이 테스트가 의미 있으므로, 이 Task에서 `GET /api/bootstrap` 자리만 먼저 등록합니다(Task 10에서 구현).

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_channels.py -v` → FAIL

- [ ] **Step 3: 구현** — 위 Interfaces대로 작성합니다.

- [ ] **Step 4: 통과 확인** — Run: `uv run pytest -q` → 전체 통과

- [ ] **Step 5: Commit** — `git commit -m "feat: add dual-channel app factory, deps and server entry"`

---

### Task 10: 로그인·최초 설정 API

**Files:**
- Modify: `server/app/web/shared_api.py`, `server/app/web/local_api.py`
- Create: `server/tests/test_auth_api.py`

**Interfaces:**
- Consumes: `Services`, `deps.current_user`, `AuditLogger`
- Produces (HTTP):
  - shared `POST /api/auth/otp/request` `{email}` → 202 `{}`. 한도 초과는 429 `rate_limited` + `Retry-After`, 형식 오류는 422 `invalid_email`
  - shared `POST /api/auth/otp/verify` `{email, code}`
    - 성공: 200 `{"user": {id,email,name,role}, "csrf_token": str}` + 쿠키. `UserStore.touch_login` 호출
    - 실패: 401 `login_required`
  - shared `POST /api/auth/logout` → 204, 세션 폐기, 쿠키 삭제
  - shared `GET /api/auth/me` → `{"user": {...} | null, "channel": ...}`
  - local `GET /api/bootstrap` → `{"needed": bool}`
  - local `POST /api/bootstrap` `{email, name}` → 201 user (role `admin`). 사용자가 이미 있으면 409 `bootstrap_done`
  - 모든 로그인 시도는 `audit.auth`에 남깁니다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_auth_api.py
async def bootstrap(local_client):
    r = await local_client.post("/api/bootstrap", json={"email": "Admin@X.com", "name": "관리자"})
    assert r.status_code == 201 and r.json()["role"] == "admin"

async def login(client, services, email="admin@x.com"):
    await client.post("/api/auth/otp/request", json={"email": email})
    code = services.otp.provider.sent[-1][1]
    r = await client.post("/api/auth/otp/verify", json={"email": email, "code": code})
    assert r.status_code == 200
    client.csrf = r.json()["csrf_token"]
    return r

async def test_bootstrap_once(local_client):
    assert (await local_client.get("/api/bootstrap")).json() == {"needed": True}
    await bootstrap(local_client)
    r = await local_client.post("/api/bootstrap", json={"email": "b@x.com", "name": "b"})
    assert r.status_code == 409 and r.json() == {"error": "bootstrap_done"}

async def test_bootstrap_absent_on_external(external_client):
    assert (await external_client.post("/api/bootstrap", json={"email": "a@x.com", "name": "a"})).status_code == 404

async def test_login_with_mixed_case_email(local_client, services):
    await bootstrap(local_client)
    r = await login(local_client, services, " ADMIN@x.com ")
    cookie = r.headers["set-cookie"].lower()
    assert "mcpmon_sid=" in cookie and "httponly" in cookie and "samesite=strict" in cookie
    me = (await local_client.get("/api/auth/me")).json()
    assert me["user"]["email"] == "admin@x.com" and me["channel"] == "local"

async def test_request_unknown_email_same_response(local_client, services):
    await bootstrap(local_client)
    r = await local_client.post("/api/auth/otp/request", json={"email": "ghost@x.com"})
    assert r.status_code == 202 and services.otp.provider.sent == []

async def test_cooldown_429(local_client):
    await bootstrap(local_client)
    await local_client.post("/api/auth/otp/request", json={"email": "admin@x.com"})
    r = await local_client.post("/api/auth/otp/request", json={"email": "admin@x.com"})
    assert r.status_code == 429 and int(r.headers["retry-after"]) > 0

async def test_wrong_code_401_and_audited(local_client, services):
    await bootstrap(local_client)
    await local_client.post("/api/auth/otp/request", json={"email": "admin@x.com"})
    code = services.otp.provider.sent[-1][1]
    wrong = "000000" if code != "000000" else "111111"
    r = await local_client.post("/api/auth/otp/verify", json={"email": "admin@x.com", "code": wrong})
    assert r.status_code == 401 and r.json() == {"error": "login_required"}
    await services.log.flush()
    text = (services.paths.logs_dir / "2026-11-04.jsonl").read_text("utf-8")
    assert '"cat": "auth"' in text and '"ok": false' in text

async def test_logout(local_client, services):
    await bootstrap(local_client); await login(local_client, services)
    assert (await local_client.get("/api/auth/me")).json()["user"] is not None
    assert (await local_client.post("/api/auth/logout")).status_code == 403  # CSRF 없음
    r = await local_client.post("/api/auth/logout", headers={"X-CSRF-Token": local_client.csrf})
    assert r.status_code == 204
    assert (await local_client.get("/api/auth/me")).json()["user"] is None
```

`login()` 헬퍼는 verify 응답의 `csrf_token`을 `client.csrf`에 저장합니다. 이후 테스트는 이 값을 `X-CSRF-Token` 헤더로 보냅니다. logout도 세션이 있는 변경 요청이므로 CSRF 검사를 받습니다.

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_auth_api.py -v` → FAIL

- [ ] **Step 3: 구현**

- 요청 IP는 `request.client.host`로 얻습니다.
- 쿠키는 `response.set_cookie("mcpmon_sid", sid, httponly=True, samesite="strict", path="/", secure=request.url.scheme == "https")`로 설정합니다.
- 최초 설정은 `db.transaction()` 안에서 `users.count() == 0`을 확인하고 생성합니다(동시 요청 경쟁 방지).

- [ ] **Step 4: 통과 확인** — Run: `uv run pytest tests/test_auth_api.py -v` → 7 passed

- [ ] **Step 5: Commit** — `git commit -m "feat: add OTP login, logout, me and local-only bootstrap API"`

---

### Task 11: 사용자 관리 API (localhost Admin)

**Files:**
- Modify: `server/app/web/local_api.py`
- Create: `server/tests/test_users_api.py`

**Interfaces:**
- Consumes: `require(Action.MANAGE_USERS)`, `UserStore`, `SessionStore.revoke_user`, `AuditLogger.admin`
- Produces (local 전용 HTTP):
  - `GET /api/users` → `[{id,email,name,role,active,created_at,last_login_at}]`
  - `POST /api/users` `{email,name,role}` → 201. 오류: 409 `user_exists`, 422 `invalid_email`
  - `PATCH /api/users/{id}` `{name?, role?, active?}` → 200
    - 마지막 Admin이면 409 `last_admin`, 대상이 없으면 404 `not_found`
    - role·active가 바뀌면 그 사용자의 세션을 모두 폐기합니다.
  - 모든 변경은 `audit.admin`에 기록합니다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_users_api.py
from tests.test_auth_api import bootstrap, login

async def admin_client(local_client, services):
    await bootstrap(local_client); await login(local_client, services)
    return local_client

async def test_create_and_promote(local_client, services):
    c = await admin_client(local_client, services); h = {"X-CSRF-Token": c.csrf}
    r = await c.post("/api/users", json={"email": "Dev@x.com", "name": "개발자", "role": "developer"}, headers=h)
    assert r.status_code == 201 and r.json()["email"] == "dev@x.com"
    uid = r.json()["id"]
    assert (await c.patch(f"/api/users/{uid}", json={"role": "admin"}, headers=h)).json()["role"] == "admin"

async def test_duplicate_and_invalid(local_client, services):
    c = await admin_client(local_client, services); h = {"X-CSRF-Token": c.csrf}
    assert (await c.post("/api/users", json={"email": "ADMIN@x.com", "name": "a", "role": "developer"}, headers=h)).json() == {"error": "user_exists"}
    assert (await c.post("/api/users", json={"email": "nope", "name": "a", "role": "developer"}, headers=h)).status_code == 422

async def test_last_admin(local_client, services):
    c = await admin_client(local_client, services); h = {"X-CSRF-Token": c.csrf}
    me = (await c.get("/api/auth/me")).json()["user"]["id"]
    r = await c.patch(f"/api/users/{me}", json={"role": "developer"}, headers=h)
    assert r.status_code == 409 and r.json() == {"error": "last_admin"}

async def test_csrf_required(local_client, services):
    c = await admin_client(local_client, services)
    r = await c.post("/api/users", json={"email": "d@x.com", "name": "d", "role": "developer"})
    assert r.status_code == 403 and r.json() == {"error": "csrf"}

async def test_developer_forbidden(local_client, services):
    c = await admin_client(local_client, services); h = {"X-CSRF-Token": c.csrf}
    await c.post("/api/users", json={"email": "dev@x.com", "name": "d", "role": "developer"}, headers=h)
    await c.post("/api/auth/logout", headers=h)
    services.otp.provider.sent.clear(); services.clock.advance(61)
    await login(c, services, "dev@x.com")
    assert (await c.get("/api/users")).json() == {"error": "forbidden"}

async def test_anonymous_401(local_client):
    assert (await local_client.get("/api/users")).status_code == 401

async def test_users_api_absent_on_external(local_client, external_client, services):
    await bootstrap(local_client); await login(external_client, services)
    assert (await external_client.get("/api/users")).status_code == 404

async def test_deactivate_revokes_session(local_client, external_client, services):
    c = await admin_client(local_client, services); h = {"X-CSRF-Token": c.csrf}
    uid = (await c.post("/api/users", json={"email": "dev@x.com", "name": "d", "role": "developer"}, headers=h)).json()["id"]
    services.clock.advance(61); await login(external_client, services, "dev@x.com")
    assert (await external_client.get("/api/auth/me")).json()["user"] is not None
    await c.patch(f"/api/users/{uid}", json={"active": False}, headers=h)
    assert (await external_client.get("/api/auth/me")).json()["user"] is None
```

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_users_api.py -v` → FAIL

- [ ] **Step 3: 구현** — 위 Interfaces대로 작성합니다. 요청 본문은 pydantic 모델로 받고, `role`은 `Literal["developer","admin"]`입니다.

- [ ] **Step 4: 통과 확인** — Run: `uv run pytest tests/test_users_api.py -v` → 8 passed

- [ ] **Step 5: Commit** — `git commit -m "feat: add local admin user management API"`

---

### Task 12: 전역 설정 API (localhost Admin)

**Files:**
- Modify: `server/app/web/local_api.py`
- Create: `server/tests/test_settings_api.py`

**Interfaces:**
- Consumes: `SettingsStore`, `require(Action.EDIT_GLOBAL_SETTINGS)`, `require(Action.EDIT_RETENTION)`
- Produces (local 전용 HTTP):
  - `GET /api/settings` → `Settings` JSON (Admin)
  - `PUT /api/settings` (부분 patch) → 200 `Settings`. 잘못된 값은 422 `validation`
    - `log_retention_days` 또는 `log_compress_after_days`가 들어 있으면 `EDIT_RETENTION` 권한도 검사합니다.
    - 변경 전후 값을 `audit.admin`에 기록합니다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_settings_api.py
from tests.test_users_api import admin_client

async def test_get_and_update(local_client, services):
    c = await admin_client(local_client, services); h = {"X-CSRF-Token": c.csrf}
    assert (await c.get("/api/settings")).json()["log_retention_days"] == 180
    r = await c.put("/api/settings", json={"log_retention_days": 90, "ping_interval_sec": 10}, headers=h)
    assert r.status_code == 200 and r.json()["log_retention_days"] == 90
    assert services.settings.get().ping_interval_sec == 10

async def test_invalid_422(local_client, services):
    c = await admin_client(local_client, services); h = {"X-CSRF-Token": c.csrf}
    r = await c.put("/api/settings", json={"log_retention_days": 5}, headers=h)
    assert r.status_code == 422 and r.json() == {"error": "validation"}

async def test_absent_on_external(external_client):
    assert (await external_client.get("/api/settings")).status_code == 404
```

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_settings_api.py -v` → FAIL

- [ ] **Step 3: 구현** — `ValidationError`를 422 `validation`으로 바꾸는 예외 핸들러를 `create_app`에 등록합니다. 다른 API에도 같은 형식으로 적용됩니다.

- [ ] **Step 4: 통과 확인** — Run: `uv run pytest tests/test_settings_api.py -v` → 3 passed

- [ ] **Step 5: Commit** — `git commit -m "feat: add local admin global settings API"`

---

### Task 13: 실제 서버 실행 확인과 보안 점검

**Files:**
- Create: `server/tests/test_e2e_serve.py`

**Interfaces:**
- Consumes: `python -m app` CLI

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_e2e_serve.py
import socket, subprocess, sys, time, httpx, pytest

def free_port():
    with socket.socket() as s: s.bind(("127.0.0.1", 0)); return s.getsockname()[1]

@pytest.fixture
def server(tmp_path):
    lp, ep = free_port(), free_port()
    p = subprocess.Popen([sys.executable, "-m", "app", "--root", str(tmp_path), "--local-port", str(lp), "--external-port", str(ep)],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for _ in range(50):
        try: httpx.get(f"http://127.0.0.1:{lp}/api/channel", timeout=0.2); break
        except httpx.HTTPError: time.sleep(0.1)
    yield lp, ep, tmp_path
    p.terminate(); p.wait(10)

def test_two_channels_live(server):
    lp, ep, root = server
    assert httpx.get(f"http://127.0.0.1:{lp}/api/channel").json()["channel"] == "local"
    assert httpx.get(f"http://127.0.0.1:{ep}/api/channel").json()["channel"] == "external"
    assert httpx.get(f"http://127.0.0.1:{ep}/api/bootstrap").status_code == 404

def test_dummy_otp_outbox_written(server):
    lp, _, root = server
    httpx.post(f"http://127.0.0.1:{lp}/api/bootstrap", json={"email": "a@x.com", "name": "a"})
    httpx.post(f"http://127.0.0.1:{lp}/api/auth/otp/request", json={"email": "a@x.com"})
    time.sleep(0.5)
    assert "a@x.com" in (root / "data" / "dev" / "otp-outbox.log").read_text("utf-8")
    assert list((root / "logs").glob("*.jsonl"))
```

- [ ] **Step 2: 실행해서 통과 확인** — Run: `uv run pytest tests/test_e2e_serve.py -v` → 2 passed (실패하면 Task 9의 `serve` 연결부를 고칩니다)

- [ ] **Step 3: 전체 테스트와 보안 점검**

Run: `uv run pytest -q` → 전체 통과
Run: `uv run pip-audit` → `No known vulnerabilities found`

- [ ] **Step 4: 수동 확인**

Run: `uv run python -m app --root ..\.devroot`
- 브라우저에서 `http://localhost:8700/api/channel`을 열면 `local`이 나와야 합니다.
- 같은 네트워크의 다른 기기에서 `http://<PC IP>:8701/api/channel`을 열면 `external`이 나와야 합니다. 방화벽이 막으면 그 결과를 기록만 합니다. 방화벽은 사용자가 직접 설정합니다.

- [ ] **Step 5: Commit** — `git commit -m "test: add live two-channel e2e check"`
