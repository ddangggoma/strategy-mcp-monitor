# Plan 2 — MCP Monitoring Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** MCP 감시 백엔드를 만듭니다. 범위는 Dummy MCP 3종(+chaos, 예시 스크립트), 프로브(MCP ping/TCP/ICMP, 포트→PID), 상태 머신, 예외 격리된 스크립트 실행기(R20), 스크립트 버전 관리, MCP·스크립트·소유권 API, 상태 보드 API와 SSE `/api/stream`입니다. UI는 만들지 않습니다.

**Architecture:** 상태 머신(`McpEngine`)은 시계와 측정 결과만 입력받는 순수 로직입니다. `Monitor`가 asyncio 루프 3개(ping, 10초 점검, 1초 재측정)로 프로브를 돌려 엔진에 넣고, 엔진이 돌려준 효과(전이·스크립트 실행·알림)를 적용합니다. 스크립트는 항상 자식 프로세스로 돌고, `Monitor`는 실행을 task로 띄울 뿐 기다리지 않습니다. 측정 이력은 메모리(스파크라인 60점)와 DB 분 단위 집계(24시간 가동률, 7일 보관)로 나눕니다. 보드 변경분은 `BoardBus`를 거쳐 SSE로 1초 단위로 묶어 보냅니다.

**Tech Stack:** Python 3.15, uv, FastAPI, httpx(프로브), psutil(포트→PID, 프로세스 트리 종료), asyncio subprocess, `ping.exe`, PowerShell 5.1 / cmd, 공식 `mcp` Python SDK(FastMCP, Dummy 전용), pytest, pytest-asyncio, ruff, mypy

**Spec:** `docs/PLAN.md` (v0.4). 이 계획은 §5.7, §5.8(R20 포함), §5.9의 MCP `autostart_on_boot`, §5.10, §4.3·§8의 MCP·스크립트·소유권 행, §6.2 상태 보드의 데이터(백엔드 API만)를 구현합니다. 이전 계획에서 넘어온 항목은 `docs/superpowers/plans/carry-forward.md`의 "Plan 2" 절이고, 이미 내려진 결정은 `docs/superpowers/plans/2026-11-04-plan1-rulings.md`에 있습니다.

## Global Constraints

- 브랜치: `feat/plan2-mcp-monitor` (Plan 1 위에 쌓음). 서버 명령은 `server/`에서, Dummy 명령은 `dummy-mcps/`에서 `uv run ...`으로 실행합니다. uv 실행 파일: `C:\Users\ddang\AppData\Local\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\uv.exe` (PATH에 없으면 이 경로로 부릅니다. 계획 본문에서는 `uv`라고 씁니다).
- Python 3.15 (`.python-version` = `3.15`, 두 프로젝트 모두). 의존성은 각 프로젝트의 `uv.lock`으로 고정하고, 두 프로젝트 모두 `uv run pip-audit` 결과가 0건이어야 합니다.
- 새 서버 런타임 의존성: `httpx`(dev에서 런타임으로 이동), `psutil`. dev: `ruff`, `mypy`, `types-psutil`. 그 밖의 런타임 의존성은 추가하지 않습니다.
- 운영 OS는 Windows입니다. asyncio 기본 이벤트 루프(Proactor)를 씁니다. `WindowsSelectorEventLoopPolicy`를 설정하지 않습니다(Selector 루프는 subprocess를 지원하지 않습니다).
- 시간: 내부는 UTC aware `datetime`. DB 시각은 `dt.astimezone(timezone.utc).isoformat()`(UTC, 마이크로초, `users`·`auth_sessions`와 같은 형식). 분 집계 키는 `"YYYY-MM-DDTHH:MMZ"`(UTC). API 응답과 로그의 시각은 `to_kst_iso`(KST, 밀리초)입니다.
- `LogWriter.emit`은 이벤트 루프 스레드에서만 부릅니다. `asyncio.to_thread`로 보낸 작업은 값을 돌려주기만 하고, 로그는 루프에서 남깁니다.
- `db.transaction()` 안에서는 `await`하지 않고, 중첩하지 않습니다(Task 2부터 중첩은 `RuntimeError`).
- 로그 카테고리: 상태 전이·알림 `mcp.health`, 스크립트 실행 `mcp.action`, 해시 불일치 `tamper`, 모든 API 변경 `admin.audit`(`result` ∈ `ok`/`error`/`denied`), 내부 오류 `system`.
- 전역 설정(기존 `Settings`): `ping_interval_sec` 1–300(5), `issue_check_interval_sec` 5–60(10), `confirm_interval_sec` 1–10(1). 루프는 매 회차마다 설정을 다시 읽습니다(재시작 없이 반영).
- MCP별 설정(`McpConfig`, 범위는 이 계획의 결정, 기본값은 spec §5.7):

  | 필드 | 타입 | 기본 | 범위 |
  |---|---|---|---|
  | `name` | str | — | 앞뒤 공백 제거 후 1–64자, 대소문자 무시 유일 |
  | `host` | str | — | 호스트명 / IPv4 / IPv6, 소문자로 정규화, `-`로 시작 불가 |
  | `port` | int | — | 1–65535, `(host, port)` 유일 |
  | `path` | str | `"/mcp"` | `/`로 시작, 공백 없음, ≤ 200자 |
  | `probe` | `"mcp_ping"`·`"tcp"`·`"icmp"` | `"mcp_ping"` | |
  | `expected_process_name` | str \| None | None | 1–260자 |
  | `action_delay_sec` | int | 30 | 1–3600 |
  | `startup_grace_sec` | int | 30 | 0–600 |
  | `max_auto_actions` | int | 3 | 1–20 |
  | `window_sec` | int | 600 | 60–86400 |
  | `auto_recovery` | bool | True | |
  | `autostart_on_boot` | bool | False | |
  | `maintenance` | bool | False | |
  | `script_timeout_sec` | int | 120 | 10–120 |

- 스크립트: 종류 `start`(필수)·`stop`(필수)·`restart`(선택), 확장자 `.ps1`·`.bat`·`.cmd`, 내용 ≤ 65,536바이트(인코딩 후). 파일 위치 `paths.scripts_dir / str(mcp_id) / f"{kind}{ext}"`.
- 실행기: 타임아웃 `min(script_timeout_sec, 120)`초, stdout/stderr 각 1,048,576바이트 저장, 전체 동시 실행 4개, MCP별 잠금, 강제 종료는 `timeout`일 때만(프로세스 트리), 결과 `ok`/`failed`/`timeout`/`error`, 예외를 호출자에게 던지지 않음.
- 스크립트 환경변수: `MCP_ID`, `MCP_NAME`, `MCP_HOST`, `MCP_PORT`, `MCP_PID`(모르면 빈 문자열), `MCP_REASON`(이슈 코드 또는 `manual`), `MCP_TRIGGER`(`auto`/`manual`/`boot`), `MCP_ACTOR`(수동이면 이메일, 아니면 `system`). 서비스 환경변수를 상속하고 그 위에 덮어씁니다.
- 프로브: 타임아웃 3초, 응답 본문 최대 65,536바이트, MCP 프로토콜 버전 `"2025-06-18"`.
- Dummy MCP: `seoul-weather` 9101, `calculator` 9102, `seoul-clock` 9103, streamable HTTP 경로 `/mcp`. chaos(`POST /chaos/crash`, `POST /chaos/hang?sec=N`, `POST /chaos/slow?ms=N`)는 `--chaos`일 때만 등록합니다.
- SSE: 변경분을 1초 단위로 묶음, heartbeat 15초, 동시 스트림 최대 100개.
- 새 API 오류 코드: `body_too_large`(413), `name_taken`(409), `endpoint_taken`(409), `action_in_progress`(409), `script_required`(409), `scripts_required`(422), `script_too_large`(422), `script_encoding`(422), `script_empty`(422), `invalid_owner`(422), `too_many_streams`(503). 기존 형식 `{"error": "<code>"}`을 그대로 따릅니다.
- 테스트: 기본 실행 `uv run pytest -q`는 `integration` 마커를 제외합니다. 통합 시나리오는 `uv run pytest -m integration -q`로 따로 돌립니다. Windows 전용 테스트는 `sys.platform != "win32"`이면 skip합니다.

## Review Focus

1. **start 스크립트가 MCP를 백그라운드로 띄우고, 그 MCP가 스크립트의 stdout/stderr 파이프 핸들을 상속하는 경우**(PowerShell `Start-Process -RedirectStandardOutput`가 그렇게 합니다): 실행기는 파이프 EOF가 아니라 스크립트 프로세스 종료로 완료를 판단해야 하고, 띄운 MCP는 죽이면 안 됩니다. → Task 7 `test_background_child_holding_pipe_does_not_block`
2. **포트→PID 조회가 실패하는 경우**(psutil `AccessDenied` 등): 모든 로컬 MCP를 `PROCESS_DOWN`으로 판정해 start를 일제히 실행하면 안 됩니다. 포트 정보 없이 판정해야 합니다. → Task 9 `test_classify_port_unknown`, `test_check_survives_port_lookup_failure`
3. **TCP는 받지만 응답하지 않는(hang) MCP, 또는 끝나지 않는 SSE / 거대한 응답을 보내는 MCP**: 프로브는 3초·64KB에서 끊겨야 하고, 같은 MCP의 점검이 겹쳐 쌓이면 안 됩니다. → Task 9 `test_mcp_ping_timeout`, `test_mcp_ping_bad_replies[too_large]`, Task 11 `test_no_overlapping_checks_for_same_mcp`
4. **External 채널에서 Local에만 있는 메서드를 호출하는 경우**(`POST /api/mcps`, `DELETE /api/mcps/{id}`는 경로가 shared `GET`과 겹칩니다): 405가 아니라 404여야 라우트 존재가 드러나지 않습니다. → Task 13 `test_local_methods_404_on_external`
5. **한국어가 들어간 스크립트와 스크립트 출력**: `.ps1`은 PowerShell 5.1이 읽을 수 있게 UTF-8 BOM으로 저장하고, OEM 코드 페이지(cp949)로 나온 출력도 깨지지 않게 디코딩해야 합니다. `.bat`에 OEM으로 표현할 수 없는 문자가 있으면 저장 시 거부합니다. → Task 6 `test_prepare_ps1_bom_crlf`, `test_prepare_rejects`, Task 7 `test_ps1_korean_output`

---

### Task 1: 외부 입력 크기 제한과 감사 스로틀 키 (carry-forward)

**Files:**
- Modify: `server/app/audit.py`, `server/app/auth/sessions.py`, `server/app/auth/otp.py`, `server/app/web/shared_api.py`, `server/app/web/app_factory.py`
- Create: `server/tests/test_input_limits.py`
- Modify (tests): `server/tests/test_audit.py`, `server/tests/test_otp.py`

**Interfaces:**
- Produces:
  - `app.audit.MAX_USER_AGENT = 512`, `app.audit.cap_user_agent(ua: str | None) -> str | None` (앞 512자). `AuditLogger.auth`와 `SessionStore.create`가 저장 전에 적용합니다.
  - `OtpRequestBody`, `OtpVerifyBody`: `model_config = ConfigDict(extra="forbid")`
  - `app.web.app_factory.MAX_BODY_BYTES = 262_144`, `BodySizeLimit` (순수 ASGI 미들웨어, 두 채널 모두): `Content-Length`가 한도를 넘으면 즉시, 본문을 읽다가 누적 바이트가 넘으면 그때 413 `{"error": "body_too_large"}`를 한 번 보내고, 앱이 이후 보내는 메시지는 버립니다. http 외 scope는 그대로 통과시킵니다.
  - `OtpRateLimitError(retry_after: int, scope: Literal["ip", "email"] = "ip")`: IP 한도·verify IP 예산은 `"ip"`, 재발송 쿨다운·이메일 잠금은 `"email"`.
  - `AuditLogger.auth_rate_limited(..., scope: Literal["ip", "email"] = "ip")`: 스로틀 키가 `"ip"`면 `(event, ip)`, `"email"`이면 `(event, ip, sha256(email)[:16])`. 라우트는 `scope=exc.scope`를 넘깁니다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_input_limits.py
import pytest
from tests.test_auth_api import audit_events, bootstrap

async def test_user_agent_capped_in_audit_and_session(local_client, services):
    await bootstrap(local_client)
    ua = {"User-Agent": "A" * 5000}
    await local_client.post("/api/auth/otp/request", json={"email": "admin@x.com"}, headers=ua)
    code = services.otp.provider.sent[-1][1]
    r = await local_client.post("/api/auth/otp/verify", json={"email": "admin@x.com", "code": code}, headers=ua)
    assert r.status_code == 200
    events = await audit_events(services, "auth")
    assert events and all(len(e["user_agent"]) == 512 for e in events)
    assert len(services.db.query("SELECT user_agent FROM auth_sessions")[0]["user_agent"]) == 512

@pytest.mark.parametrize("path,body", [
    ("/api/auth/otp/request", {"email": "a@x.com", "x": 1}),
    ("/api/auth/otp/verify", {"email": "a@x.com", "code": "123456", "x": 1}),
])
async def test_otp_bodies_forbid_extra(external_client, path, body):
    r = await external_client.post(path, json=body)
    assert r.status_code == 422 and r.json() == {"error": "validation"}

async def test_body_too_large_413(external_client):
    r = await external_client.post("/api/auth/otp/request", content=b"{" + b" " * 262_144 + b"}",
                                   headers={"Content-Type": "application/json"})
    assert r.status_code == 413 and r.json() == {"error": "body_too_large"}

async def test_chunked_body_too_large_413(local_client):
    async def chunks():
        for _ in range(5):
            yield b" " * 65_536
    r = await local_client.post("/api/bootstrap", content=chunks(), headers={"Content-Type": "application/json"})
    assert r.status_code == 413 and r.json() == {"error": "body_too_large"}
```

```python
# server/tests/test_audit.py (추가)
def test_email_scope_throttles_per_email():
    log = _Log(); audit = AuditLogger(log); t0 = datetime(2026, 11, 4, 5, 0, tzinfo=timezone.utc)
    for email in ("a@x.com", "b@x.com", "a@x.com"):
        audit.auth_rate_limited(event="otp_request", email=email, channel="external", ip="1.1.1.1",
                                user_agent=None, now=t0, scope="email")
    assert len(log.events) == 2

def test_user_agent_capped():
    log = _Log(); AuditLogger(log).auth(event="login", email="a@x.com", channel="local", ip=None, user_agent="u" * 600, ok=True)
    assert len(log.events[0][1]["user_agent"]) == 512
```

```python
# server/tests/test_otp.py (추가)
def test_rate_limit_scope(env):
    svc, _, _, _ = env
    svc.request("a@x.com", "ip")
    with pytest.raises(OtpRateLimitError) as e: svc.request("a@x.com", "ip")
    assert e.value.scope == "email"
    for i in range(9): svc.request(f"u{i}@x.com", "ip")
    with pytest.raises(OtpRateLimitError) as e: svc.request("new@x.com", "ip")
    assert e.value.scope == "ip"
```

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_input_limits.py tests/test_audit.py tests/test_otp.py -v` → FAIL

- [ ] **Step 3: 구현** — 위 Interfaces대로 작성합니다. `BodySizeLimit`은 `create_app`에서 채널과 관계없이 `app.add_middleware(BodySizeLimit)`로 등록합니다.

- [ ] **Step 4: 통과 확인** — Run: `uv run pytest -q` → 전체 통과

- [ ] **Step 5: Commit** — `git commit -m "fix: cap user agent and request body, scope rate-limit audit throttle"`

---

### Task 2: 코어 하드닝 (carry-forward)과 `VIEW_SCRIPTS`

**Files:**
- Modify: `server/app/db.py`, `server/app/settings/store.py`, `server/app/web/app_factory.py`, `server/app/web/local_api.py`, `server/app/auth/policy.py`
- Modify (tests): `server/tests/test_db.py`, `server/tests/test_settings_store.py`, `server/tests/test_errors_and_serve.py`, `server/tests/test_policy.py`

**Interfaces:**
- Produces:
  - `Database.transaction()`: 잠금을 얻은 뒤 `self._conn.in_transaction`이면 `RuntimeError("transaction already open")`
  - `Database.execute_rowcount(sql: str, params: Sequence = ()) -> int`. `execute()` docstring에 "반환값 lastrowid는 INSERT에서만 의미가 있다"를 적습니다.
  - 전역 `pydantic.ValidationError` → 422 핸들러(`_pydantic_validation_handler`)를 삭제합니다. `PUT /api/settings`는 `ValidationError`를 잡아 audit 후 `ApiError(422, "validation")`을 던집니다. 라우트 안의 모델 버그는 500 `internal`이 됩니다.
  - `SettingsStore.get()`: 저장된 행이 깨져 있으면(`ValidationError`/`ValueError`) stderr 경고 후 `Settings()`. `update()`: 깨진 행이면 기본값 위에 patch를 합쳐 덮어씁니다.
  - `can()`: 맨 앞에서 비활성 사용자를 `None`으로 바꿉니다. `Rule.min_role: Role | None`, 채널 검사는 `channel not in get_args(Channel)`, `RULES: Mapping[Action, Rule] = MappingProxyType({...})`.
  - `Action.VIEW_SCRIPTS = "view_scripts"`: `Rule("developer", local_only=True)` (스크립트 읽기 전용 조회, 소유자 무관)

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_db.py (추가)
def test_transaction_reentry_raises(db):
    with db.transaction():
        with pytest.raises(RuntimeError, match="already open"):
            with db.transaction():
                pass
    db.execute("INSERT INTO secrets(name, value) VALUES ('ok', '1')")
    assert len(db.query("SELECT * FROM secrets WHERE name='ok'")) == 1

def test_execute_rowcount(db):
    db.execute("INSERT INTO secrets(name, value) VALUES ('a','1')"); db.execute("INSERT INTO secrets(name, value) VALUES ('b','1')")
    assert db.execute_rowcount("UPDATE secrets SET value='2'") == 2
    assert db.execute_rowcount("DELETE FROM secrets WHERE name='zz'") == 0
```

기존 `test_db.py`의 `user_version` 고정값(18, 100, 131행)은 `len(MIGRATIONS)` 기준 값으로 바꿉니다(Task 5에서 마이그레이션이 늘어도 깨지지 않게).

```python
# server/tests/test_settings_store.py (추가)
def test_corrupt_row_falls_back(db):
    db.execute("INSERT INTO settings(key, value) VALUES ('global', '{not json')")
    s = SettingsStore(db)
    assert s.get() == Settings()
    assert s.update({"ping_interval_sec": 7}).ping_interval_sec == 7
    assert s.get().ping_interval_sec == 7
```

```python
# server/tests/test_errors_and_serve.py (추가)
async def test_model_bug_in_route_is_500(services):
    app = create_app("local", services); router = APIRouter()
    @router.get("/t/model")
    async def model():
        Settings.model_validate({"ping_interval_sec": 0})
    app.include_router(router)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8700") as c:
        r = await c.get("/t/model")
    assert r.status_code == 500 and r.json() == {"error": "internal"}
```

```python
# server/tests/test_policy.py (MATRIX에 행 추가 + 새 테스트)
    (A.VIEW_SCRIPTS,         0, 1, 1, True,  False),

def test_rules_frozen():
    from app.auth.policy import RULES
    with pytest.raises(TypeError):
        RULES[A.VIEW_BOARD] = RULES[A.VIEW_LOGS]

def test_unknown_channel_denied():
    assert can(ADM, A.VIEW_BOARD, "LOCAL") is False

def test_inactive_owner_is_not_owner():
    assert can(mk("developer", 5, active=False), A.EDIT_SCRIPTS, "local", owner_id=5) is False
```

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_db.py tests/test_settings_store.py tests/test_errors_and_serve.py tests/test_policy.py -v` → FAIL

- [ ] **Step 3: 구현** — 위 Interfaces대로 작성합니다. 기존 `test_settings_api.py`의 422 기대값은 그대로 통과해야 합니다.

- [ ] **Step 4: 통과 확인** — Run: `uv run pytest -q` → 전체 통과

- [ ] **Step 5: Commit** — `git commit -m "fix: guard transaction reentry, route-level settings 422, harden can(), add VIEW_SCRIPTS"`

---

### Task 3: Dummy MCP 3종과 chaos

**Files:**
- Create: `dummy-mcps/pyproject.toml`, `dummy-mcps/.python-version`, `dummy-mcps/uv.lock`
- Create: `dummy-mcps/common/__init__.py`, `dummy-mcps/common/server.py`, `dummy-mcps/common/chaos.py`
- Create: `dummy-mcps/seoul_weather/{__init__,__main__,tools}.py`, `dummy-mcps/calculator/{__init__,__main__,tools,safe_eval}.py`, `dummy-mcps/seoul_clock/{__init__,__main__,tools}.py`
- Create: `dummy-mcps/tests/__init__.py`, `dummy-mcps/tests/helpers.py`, `dummy-mcps/tests/test_tools.py`, `dummy-mcps/tests/test_servers.py`
- Modify: `.gitignore` (`dummy-mcps/run/` 추가)

**Interfaces:**
- Produces:
  - CLI: `python -m <seoul_weather|calculator|seoul_clock> [--host 127.0.0.1] [--port <9101|9102|9103>] [--chaos] [--pid-file PATH] [--open-meteo]` (`--open-meteo`는 seoul_weather만). 시작 시 `--pid-file`에 `os.getpid()`를 쓰고, 정상 종료 시 지웁니다.
  - `common.server.run(name: str, tools: Sequence[Callable], argv: Sequence[str] | None, default_port: int) -> None`
  - `common.chaos.ChaosState(slow_ms: int = 0)`, `chaos_routes(state) -> list[Route]`, `SlowMiddleware(app, state)` (http scope에만 `slow_ms` 지연, lifespan 등 나머지는 그대로 통과)
  - 도구 (순수 함수, 잘못된 입력은 `ValueError`):
    - `seoul_weather.tools.DISTRICTS: tuple[str, ...]` (서울 25개 구), `get_current_weather(district: str, fetch: Callable[[], dict] | None = None) -> dict` (`district`, `temperature_c: float`, `humidity_pct: int`, `condition: str`, `source: "dummy" | "open-meteo"`), `get_forecast(days: int) -> list[dict]` (1–7일)
    - `calculator.tools.add/subtract/multiply/divide(a: float, b: float) -> float`, `evaluate(expression: str) -> float | int`; `calculator.safe_eval.UnsafeExpression(ValueError)`
    - `seoul_clock.tools.now_kst() -> str` (ISO, `+09:00`), `convert_timezone(time: str, tz: str) -> str` (IANA 이름 또는 `±HH:MM`; 오프셋 없는 입력은 KST로 간주)

- [ ] **Step 1: 프로젝트 생성과 `mcp` 설치 확인**

`dummy-mcps/pyproject.toml`: `name = "dummy-mcps"`, `requires-python = ">=3.15,<3.16"`, `[tool.uv] package = false`, 의존성 `mcp`, `uvicorn`, `starlette`, `httpx`, `tzdata`(Windows에는 IANA tz DB가 없음), dev `pytest`, `psutil`, `pip-audit`. `[tool.pytest.ini_options]`에 `testpaths = ["tests"]`, `pythonpath = ["."]`.

Run: `uv sync` → 성공
Run: `uv run python -c "import sys, mcp.server.fastmcp; print(sys.version)"` → `3.15.x` 출력

**대체 규칙:** `uv sync`가 cp315 휠이 없어 실패하면(후보: `jsonschema`가 끌어오는 `rpds-py`), Python 버전을 바꾸지 말고 `mcp`를 의존성에서 빼고 `common/jsonrpc.py`에 starlette로 최소 streamable-HTTP JSON-RPC 서버를 만듭니다. `POST /mcp`는 단일 JSON 메시지를 받아 `application/json`으로 답합니다. `initialize`는 `{"protocolVersion", "capabilities": {"tools": {}}, "serverInfo": {"name", "version"}}`과 `Mcp-Session-Id` 헤더를 돌려줍니다. `notifications/*`는 202 빈 본문, `ping`은 `{}`, `tools/list`는 손으로 쓴 `inputSchema`, `tools/call`은 `{"content": [{"type": "text", "text": json}], "isError": bool}`입니다. 모르는 메서드는 `-32601`, 모르는 세션은 404, `DELETE /mcp`는 세션을 지웁니다. 어떤 경로를 택했는지 커밋 메시지에 적습니다.

- [ ] **Step 2: 실패하는 테스트 작성**

```python
# dummy-mcps/tests/test_tools.py
import pytest
from calculator.tools import add, subtract, multiply, divide, evaluate
from seoul_weather.tools import DISTRICTS, get_current_weather, get_forecast
from seoul_clock.tools import now_kst, convert_timezone

def test_arith():
    assert (add(2, 3), subtract(2, 3), multiply(4, 2.5), divide(7, 2)) == (5, -1, 10, 3.5)
    with pytest.raises(ValueError): divide(1, 0)

@pytest.mark.parametrize("expr,val", [("1+2*3", 7), ("(1+2)*3", 9), ("-2**2", -4), ("7//2", 3), ("7%4", 3), ("2**10", 1024)])
def test_evaluate(expr, val):
    assert evaluate(expr) == val

@pytest.mark.parametrize("expr", ["__import__('os')", "a+1", "1 if 1 else 2", "[1]", "2**10**10", "9" * 201, "1/0", "lambda: 1", "().__class__"])
def test_evaluate_rejects(expr):
    with pytest.raises(ValueError): evaluate(expr)

def test_weather():
    assert len(DISTRICTS) == 25 and "강남구" in DISTRICTS
    w = get_current_weather("강남구")
    assert w["district"] == "강남구" and isinstance(w["temperature_c"], float) and w["source"] == "dummy"
    with pytest.raises(ValueError): get_current_weather("부산")
    assert len(get_forecast(3)) == 3
    for bad in (0, 8):
        with pytest.raises(ValueError): get_forecast(bad)

def test_weather_open_meteo_and_fallback():
    live = get_current_weather("중구", fetch=lambda: {"current": {"temperature_2m": 3.5, "relative_humidity_2m": 40, "weather_code": 0}})
    assert live["source"] == "open-meteo" and live["temperature_c"] == 3.5
    def boom(): raise OSError("offline")
    assert get_current_weather("중구", fetch=boom)["source"] == "dummy"

def test_clock():
    assert now_kst().endswith("+09:00")
    assert convert_timezone("2026-11-05T09:00:00+09:00", "UTC") == "2026-11-05T00:00:00+00:00"
    assert convert_timezone("2026-11-05T09:00:00", "Asia/Tokyo") == "2026-11-05T09:00:00+09:00"
    assert convert_timezone("2026-11-05T09:00:00+09:00", "+05:30") == "2026-11-05T05:30:00+05:30"
    with pytest.raises(ValueError): convert_timezone("2026-11-05T09:00:00", "Mars/Base")
```

```python
# dummy-mcps/tests/helpers.py — 공용 헬퍼 (Task 4도 사용)
# ROOT: Path = dummy-mcps/ 디렉터리
# free_port() -> int
# listener_pid(port: int) -> int | None   : psutil.net_connections("tcp")에서 LISTEN인 pid
# wait_listening(port: int, timeout: float = 15.0) -> None  (TCP 연결 성공까지 0.1초 간격)
# rpc(port, method, params=None, *, session=None, id=1, timeout=3.0) -> tuple[dict | None, httpx.Headers]
#   POST /mcp, Accept: application/json, text/event-stream. 응답이 text/event-stream이면 data: 줄의 JSON을,
#   아니면 본문 JSON을 돌려줍니다. 알림(id 없음)은 (None, headers).
# open_session(port) -> str | None : initialize → notifications/initialized, Mcp-Session-Id 반환
```

```python
# dummy-mcps/tests/test_servers.py
import subprocess, sys, time, httpx, pytest
from tests.helpers import free_port, listener_pid, wait_listening, rpc, open_session, ROOT

EXPECTED = {
    "seoul_weather": ("seoul-weather", {"get_current_weather", "get_forecast"}),
    "calculator": ("calculator", {"add", "subtract", "multiply", "divide", "evaluate"}),
    "seoul_clock": ("seoul-clock", {"now_kst", "convert_timezone"}),
}

@pytest.fixture(params=sorted(EXPECTED))
def server(request, tmp_path):
    port = free_port()
    p = subprocess.Popen([sys.executable, "-m", request.param, "--port", str(port), "--chaos",
                          "--pid-file", str(tmp_path / "p.pid")], cwd=ROOT, stdin=subprocess.DEVNULL)
    wait_listening(port)
    yield request.param, port, p, tmp_path
    p.kill(); p.wait(10)

def test_initialize_ping_tools(server):
    mod, port, _, _ = server
    init, _ = rpc(port, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}})
    assert init["result"]["serverInfo"]["name"] == EXPECTED[mod][0]
    sid = open_session(port)
    assert rpc(port, "ping", session=sid)[0]["result"] == {}
    tools = {t["name"] for t in rpc(port, "tools/list", session=sid)[0]["result"]["tools"]}
    assert tools == EXPECTED[mod][1]

def test_pid_file_is_listener(server):
    _, port, _, tmp = server
    assert int((tmp / "p.pid").read_text()) == listener_pid(port)

def test_calculator_tool_call(server):
    mod, port, _, _ = server
    if mod != "calculator": pytest.skip("calculator only")
    sid = open_session(port)
    res = rpc(port, "tools/call", {"name": "evaluate", "arguments": {"expression": "1+2*3"}}, session=sid)[0]["result"]
    assert res.get("isError") in (None, False) and "7" in res["content"][0]["text"]

def test_chaos_slow_then_crash(server):
    _, port, p, _ = server
    assert httpx.post(f"http://127.0.0.1:{port}/chaos/slow?ms=300").json() == {"slow_ms": 300}
    t = time.perf_counter(); rpc(port, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}})
    assert time.perf_counter() - t >= 0.3
    httpx.post(f"http://127.0.0.1:{port}/chaos/crash")
    assert p.wait(5) == 1

def test_chaos_hang(server):
    _, port, _, _ = server
    httpx.post(f"http://127.0.0.1:{port}/chaos/hang?sec=3")
    time.sleep(0.3)
    with pytest.raises(httpx.TimeoutException):
        rpc(port, "ping", timeout=1.0)
    time.sleep(3)
    assert rpc(port, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}})[0]["result"]

def test_no_chaos_without_flag():
    port = free_port()
    p = subprocess.Popen([sys.executable, "-m", "calculator", "--port", str(port)], cwd=ROOT, stdin=subprocess.DEVNULL)
    try:
        wait_listening(port)
        assert httpx.post(f"http://127.0.0.1:{port}/chaos/crash").status_code == 404
        time.sleep(0.3); assert p.poll() is None
    finally:
        p.kill(); p.wait(10)
```

`ROOT`는 `dummy-mcps/` 경로입니다. Windows의 venv `python.exe`는 실제 인터프리터를 자식으로 띄우는 런처라서, `Popen`의 pid와 포트를 점유한 pid가 다릅니다. 그래서 pid 파일은 서버 자신이 `os.getpid()`로 쓰고, 테스트는 리스너 pid와 비교합니다.

- [ ] **Step 3: 실패 확인** — Run: `uv run pytest -q` (dummy-mcps) → FAIL

- [ ] **Step 4: 구현**

- `common.server.run`: FastMCP 서버를 만들고 도구를 `server.tool()(fn)`로 등록합니다. 등록하는 함수는 spec의 인자만 드러내는 얇은 래퍼입니다(예: `get_current_weather(district)`). `fetch`는 `--open-meteo`일 때 래퍼 안에서 묶습니다. `app = server.streamable_http_app()`(경로 `/mcp`, POST 응답은 SSE). `--chaos`면 `app.router.routes.extend(chaos_routes(state))`. `uvicorn.Server(uvicorn.Config(SlowMiddleware(app, state), host, port, log_level="warning")).run()`. initialize가 Host 검사 때문에 421/403을 내면 `transport_security`의 허용 호스트에 바인드 주소를 넣습니다.
- chaos: crash는 202 `{"crashing": true}` 응답 후 `loop.call_later(0.1, os._exit, 1)`. hang은 `sec` 1–3600(기본 30), 202 응답 후 `loop.call_later(0.1, time.sleep, sec)`로 루프 전체를 막습니다(프로세스는 살아 있고 포트도 열려 있음 = UNRESPONSIVE 재현). slow는 `ms` 0–60000, 200 `{"slow_ms": ms}`. 범위를 벗어나면 422.
- `evaluate`: `ast.parse(mode="eval")` 후 허용 노드만 계산합니다. 숫자 상수, `+ - * / // % **`, 단항 `+ -`. 식 길이 ≤ 200자, 노드 수 ≤ 100, `**` 지수의 절댓값 ≤ 100, 정수 결과는 1000자리 이하. 0으로 나누기는 `UnsafeExpression("division by zero")`.
- 날씨 더미 데이터는 `hash((district, KST 시각의 시))`로 만들어, 같은 시간대에는 같은 값을 돌려줍니다. `--open-meteo`면 `fetch`가 `https://api.open-meteo.com/v1/forecast?latitude=37.5665&longitude=126.978&current=temperature_2m,relative_humidity_2m,weather_code`(timeout 3초)를 부르고, 어떤 오류든 더미로 돌아갑니다.

- [ ] **Step 5: 통과 확인** — Run: `uv run pytest -q` (dummy-mcps) → 전체 통과. Run: `uv run pip-audit` → `No known vulnerabilities found`

- [ ] **Step 6: Commit** — `git commit -m "feat: add dummy MCP servers (weather, calculator, clock) with chaos endpoints"`

---

### Task 4: 예시 스크립트 (start / stop / restart)

**Files:**
- Create: `dummy-mcps/examples/start.ps1`, `dummy-mcps/examples/stop.ps1`, `dummy-mcps/examples/restart.ps1`
- Create: `dummy-mcps/tests/test_examples.py`

**Interfaces:**
- Consumes: Task 3 CLI(`--pid-file`, `--chaos`), spec §5.8 환경변수
- Produces: Dummy 3종 모두에 쓰는 범용 스크립트 3개(UTF-8 BOM). 동작 계약:
  - 입력 환경변수: `MCP_ID`, `MCP_NAME`, `MCP_HOST`, `MCP_PORT`, `DUMMY_MCPS_DIR`(필수), `DUMMY_MCP_RUN_DIR`(기본 `$env:DUMMY_MCPS_DIR\run`), `DUMMY_MCP_CHAOS`(`1`이면 `--chaos`)
  - 모듈 매핑 `@{ 'seoul-weather'='seoul_weather'; 'calculator'='calculator'; 'seoul-clock'='seoul_clock' }`. 모르는 `MCP_NAME`이거나 `$env:DUMMY_MCPS_DIR\.venv\Scripts\python.exe`가 없으면 exit 2.
  - 파일: `<run>\<MCP_ID>.pid`, `<run>\<MCP_ID>.out.log`, `<run>\<MCP_ID>.err.log`
  - start: 포트가 이미 LISTEN이면 exit 0. 아니면 `Start-Process -FilePath <python> -ArgumentList '-m',<module>,'--host',$env:MCP_HOST,'--port',$env:MCP_PORT,'--pid-file',<pid>[, '--chaos'] -WorkingDirectory $env:DUMMY_MCPS_DIR -WindowStyle Hidden -RedirectStandardOutput <out> -RedirectStandardError <err>`. 20초 안에 TCP 연결이 되면 exit 0, 아니면 exit 1.
  - stop: pid 파일의 프로세스와, `Get-NetTCPConnection -LocalPort $env:MCP_PORT -State Listen`의 `OwningProcess` 중 **이름이 `python`인 프로세스만** `Stop-Process -Force`합니다. 10초 안에 포트가 비면 pid 파일을 지우고 exit 0, 아니면 exit 1. 원래 꺼져 있었어도 exit 0.
  - restart: stop 절차 후 start 절차. **다른 스크립트 파일을 호출하지 않고** 같은 로직을 자체 포함합니다(실행되는 파일마다 해시 검사를 받게 하기 위해서입니다).

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# dummy-mcps/tests/test_examples.py
import os, subprocess, sys, httpx, pytest
from tests.helpers import free_port, listener_pid, rpc, ROOT

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
PS = [os.path.expandvars(r"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"),
      "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File"]

@pytest.fixture
def env(tmp_path):
    port = free_port()
    e = {"MCP_ID": "901", "MCP_NAME": "calculator", "MCP_HOST": "127.0.0.1", "MCP_PORT": str(port),
         "DUMMY_MCPS_DIR": str(ROOT), "DUMMY_MCP_RUN_DIR": str(tmp_path), "DUMMY_MCP_CHAOS": "1"}
    yield e
    run_script("stop", e, tmp_path)

def run_script(kind, env, tmp_path):
    # 출력은 파일로 받습니다. capture_output을 쓰면 백그라운드 MCP가 파이프를 상속해 EOF가 오지 않습니다.
    with open(tmp_path / f"{kind}.txt", "wb") as out:
        return subprocess.run(PS + [str(ROOT / "examples" / f"{kind}.ps1")], env={**os.environ, **env},
                              stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, timeout=60)

def test_start_stop_cycle(env, tmp_path):
    port = int(env["MCP_PORT"])
    assert run_script("start", env, tmp_path).returncode == 0
    pid = int((tmp_path / "901.pid").read_text())
    assert listener_pid(port) == pid
    assert run_script("start", env, tmp_path).returncode == 0 and listener_pid(port) == pid
    assert run_script("stop", env, tmp_path).returncode == 0
    assert listener_pid(port) is None and not (tmp_path / "901.pid").exists()
    assert run_script("stop", env, tmp_path).returncode == 0

def test_restart_recovers_hung(env, tmp_path):
    port = int(env["MCP_PORT"])
    assert run_script("start", env, tmp_path).returncode == 0
    old = listener_pid(port)
    httpx.post(f"http://127.0.0.1:{port}/chaos/hang?sec=120")
    assert run_script("restart", env, tmp_path).returncode == 0
    assert listener_pid(port) not in (None, old)
    assert rpc(port, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}})[0]["result"]

@pytest.mark.parametrize("override", [{"MCP_NAME": "nope"}, {"DUMMY_MCPS_DIR": r"C:\does-not-exist"}])
def test_bad_environment_exit_2(env, tmp_path, override):
    assert run_script("start", {**env, **override}, tmp_path).returncode == 2
```

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_examples.py -v` (dummy-mcps) → FAIL

- [ ] **Step 3: 구현** — 위 동작 계약대로 작성합니다. 각 스크립트 첫머리 주석에 입력 환경변수와 종료 코드(0 성공, 1 실패, 2 환경 오류)를 적습니다.

- [ ] **Step 4: 통과 확인** — Run: `uv run pytest -q` (dummy-mcps) → 전체 통과

- [ ] **Step 5: Commit** — `git commit -m "feat: add example start/stop/restart scripts for dummy MCPs"`

---

### Task 5: MCP 모델과 등록 저장소 (마이그레이션 4)

**Files:**
- Create: `server/app/monitor/__init__.py`, `server/app/monitor/models.py`, `server/app/monitor/store.py`, `server/tests/test_mcp_store.py`
- Modify: `server/app/db.py` (MIGRATIONS 4), `server/tests/test_db.py`

**Interfaces:**
- Consumes: `Database`, `Clock`, `UserStore.get`
- Produces:
  - `app.monitor.models`:
    - `McpState(StrEnum)`: `HEALTHY`, `SUSPECT`, `ACTION`, `RECOVERING`, `FAILED`, `MAINTENANCE` (값 = 이름)
    - `Issue(StrEnum)`: `PROCESS_DOWN`, `UNRESPONSIVE`, `NETWORK_DOWN`, `WRONG_PROCESS`; `ALERT_ONLY_ISSUES = frozenset({Issue.NETWORK_DOWN, Issue.WRONG_PROCESS})`
    - `ProbeKind = Literal["mcp_ping", "tcp", "icmp"]`, `ScriptKind = Literal["start", "stop", "restart"]`, `ActionKind = ScriptKind`, `Trigger = Literal["auto", "manual", "boot"]`, `ScriptStatus = Literal["ok", "failed", "timeout", "error"]`
    - `McpConfig` (pydantic, `extra="forbid"`, `strict=True`): Global Constraints 표의 필드·기본값·범위. `host`는 `field_validator(mode="before")`로 strip+lower 후 `ipaddress.ip_address` 또는 호스트명 정규식 `^(?=.{1,253}$)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$`, `name`은 strip.
    - `Mcp` (frozen dataclass): `id: int`, `config: McpConfig`, `owner_id: int | None`, `created_by: int | None`, `created_at: datetime`; property `url -> str` (`http://{host}:{port}{path}`, IPv6는 `[host]`)
    - `CheckResult` (frozen dataclass): `at: datetime`, `issue: Issue | None`, `latency_ms: float | None`, `pid: int | None`, `process_name: str | None`, `error: str | None`
  - `app.monitor.store`: 예외 `McpNotFoundError`, `NameTakenError`, `EndpointTakenError`
  - `McpStore(db: Database, clock: Clock, users: UserStore)`:
    - `.insert(conn: sqlite3.Connection, config: McpConfig, owner_id: int, created_by: int) -> int` (호출자 트랜잭션 안에서 사용)
    - `.create(config, owner_id) -> Mcp` (`created_by = owner_id`)
    - `.get(mcp_id) -> Mcp | None`, `.list() -> list[Mcp]` (이름순)
    - `.update(mcp_id, patch: Mapping[str, Any]) -> tuple[Mcp, Mcp]` (before, after). 잘못된 값은 `pydantic.ValidationError`
    - `.set_owner(mcp_id, owner_id: int) -> Mcp`, `.set_maintenance(mcp_id, on: bool) -> Mcp`, `.delete(mcp_id) -> None`
    - `.effective_owner_id(mcp: Mcp) -> int | None`: 소유자가 활성이면 그 id, 아니면 None("소유자 없음")

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_mcp_store.py
import pytest
from pydantic import ValidationError
from app.monitor.models import McpConfig
from app.monitor.store import McpStore, NameTakenError, EndpointTakenError, McpNotFoundError
from app.users.store import UserStore

def cfg(**kw):
    return McpConfig.model_validate({"name": "calc", "host": "127.0.0.1", "port": 9102, **kw})

@pytest.fixture
def env(db, clock):
    users = UserStore(db, clock); owner = users.create("o@x.com", "o", "developer", None)
    users.create("a@x.com", "a", "admin", None)
    return McpStore(db, clock, users), users, owner

def test_defaults():
    c = cfg()
    assert (c.path, c.probe, c.action_delay_sec, c.startup_grace_sec, c.max_auto_actions, c.window_sec) == ("/mcp", "mcp_ping", 30, 30, 3, 600)
    assert (c.auto_recovery, c.autostart_on_boot, c.maintenance, c.script_timeout_sec, c.expected_process_name) == (True, False, False, 120, None)

@pytest.mark.parametrize("bad", [
    {"port": 0}, {"port": 65536}, {"host": "-x"}, {"host": "a b"}, {"host": ""}, {"name": " "}, {"name": "x" * 65},
    {"path": "mcp"}, {"script_timeout_sec": 9}, {"script_timeout_sec": 121}, {"action_delay_sec": 0},
    {"probe": "http"}, {"bogus": 1}, {"auto_recovery": "yes"},
])
def test_config_rejects(bad):
    with pytest.raises(ValidationError): cfg(**bad)

def test_host_normalized_and_url():
    assert cfg(host=" LocalHost ").host == "localhost"
    assert cfg(host="::1").host == "::1"

def test_create_get_list(env):
    s, _, owner = env
    m = s.create(cfg(), owner.id)
    assert s.get(m.id).config == cfg() and s.get(m.id).owner_id == owner.id
    assert m.url == "http://127.0.0.1:9102/mcp" and [x.id for x in s.list()] == [m.id]

def test_unique_name_and_endpoint(env):
    s, _, owner = env; s.create(cfg(), owner.id)
    with pytest.raises(NameTakenError): s.create(cfg(name="CALC", port=9200), owner.id)
    with pytest.raises(EndpointTakenError): s.create(cfg(name="other"), owner.id)

def test_update(env):
    s, _, owner = env; m = s.create(cfg(), owner.id)
    before, after = s.update(m.id, {"action_delay_sec": 5})
    assert before.config.action_delay_sec == 30 and after.config.action_delay_sec == 5
    for bad in ({"port": 0}, {"bogus": 1}):
        with pytest.raises(ValidationError): s.update(m.id, bad)
    assert s.get(m.id).config.port == 9102
    with pytest.raises(McpNotFoundError): s.update(999, {"port": 1})

def test_effective_owner(env, db, clock):
    s, users, owner = env; m = s.create(cfg(), owner.id)
    assert s.effective_owner_id(m) == owner.id
    users.set_active(owner.id, False)
    assert s.effective_owner_id(s.get(m.id)) is None

def test_maintenance_owner_delete_cascade(env, db):
    s, users, owner = env; m = s.create(cfg(), owner.id)
    assert s.set_maintenance(m.id, True).config.maintenance is True
    other = users.create("b@x.com", "b", "developer", None)
    assert s.set_owner(m.id, other.id).owner_id == other.id
    db.execute("INSERT INTO mcp_minutes(mcp_id, minute, ok, total) VALUES (?, '2026-11-04T05:00Z', 1, 1)", (m.id,))
    s.delete(m.id)
    assert s.get(m.id) is None and db.query("SELECT * FROM mcp_minutes") == []
    with pytest.raises(McpNotFoundError): s.delete(m.id)

def test_ids_not_reused(env):
    s, _, owner = env; a = s.create(cfg(), owner.id); s.delete(a.id)
    assert s.create(cfg(), owner.id).id > a.id
```

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_mcp_store.py -v` → FAIL

- [ ] **Step 3: 구현**

마이그레이션 4 (그대로 사용):

```sql
CREATE TABLE mcps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    host TEXT NOT NULL,
    port INTEGER NOT NULL,
    config TEXT NOT NULL,                       -- McpConfig JSON (name/host/port 포함, 위 열과 항상 일치)
    owner_id INTEGER REFERENCES users(id),
    created_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL,
    UNIQUE (host, port)
);
CREATE TABLE mcp_scripts (
    mcp_id INTEGER NOT NULL REFERENCES mcps(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('start','stop','restart')),
    ext TEXT NOT NULL CHECK (ext IN ('.ps1','.bat','.cmd')),
    sha256 TEXT NOT NULL,
    version INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by INTEGER,
    PRIMARY KEY (mcp_id, kind)
);
CREATE TABLE mcp_script_versions (
    mcp_id INTEGER NOT NULL REFERENCES mcps(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    version INTEGER NOT NULL,
    ext TEXT,                                   -- ext/content/sha256 모두 NULL = 삭제 표시
    content TEXT,
    sha256 TEXT,
    author_id INTEGER,
    created_at TEXT NOT NULL,
    PRIMARY KEY (mcp_id, kind, version)
);
CREATE TABLE mcp_minutes (
    mcp_id INTEGER NOT NULL REFERENCES mcps(id) ON DELETE CASCADE,
    minute TEXT NOT NULL,
    ok INTEGER NOT NULL,
    total INTEGER NOT NULL,
    latency_sum REAL NOT NULL DEFAULT 0,
    latency_n INTEGER NOT NULL DEFAULT 0,
    latency_max REAL,
    PRIMARY KEY (mcp_id, minute)
) WITHOUT ROWID;
CREATE TABLE mcp_transitions (
    id INTEGER PRIMARY KEY,
    mcp_id INTEGER NOT NULL REFERENCES mcps(id) ON DELETE CASCADE,
    at TEXT NOT NULL,
    from_state TEXT NOT NULL,
    to_state TEXT NOT NULL,
    issue TEXT
);
CREATE INDEX idx_mcp_transitions ON mcp_transitions(mcp_id, at);
CREATE TABLE mcp_actions (
    id INTEGER PRIMARY KEY,
    run_id TEXT NOT NULL,
    mcp_id INTEGER NOT NULL REFERENCES mcps(id) ON DELETE CASCADE,
    at TEXT NOT NULL,
    requested TEXT NOT NULL,
    kind TEXT NOT NULL,
    trigger TEXT NOT NULL CHECK (trigger IN ('auto','manual','boot')),
    reason TEXT NOT NULL,
    actor_id INTEGER,
    status TEXT NOT NULL CHECK (status IN ('ok','failed','timeout','error')),
    exit_code INTEGER,
    duration_ms INTEGER NOT NULL,
    killed INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    stdout TEXT NOT NULL DEFAULT '',
    stderr TEXT NOT NULL DEFAULT '',
    stdout_truncated INTEGER NOT NULL DEFAULT 0,
    stderr_truncated INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_mcp_actions ON mcp_actions(mcp_id, at);
```

`update`는 트랜잭션 안에서 현재 config에 patch를 합쳐 `McpConfig.model_validate`로 검증하고 `config`·`name`·`host`·`port`를 함께 씁니다. `sqlite3.IntegrityError` 메시지에 `mcps.name`이 있으면 `NameTakenError`, `mcps.host`이면 `EndpointTakenError`로 바꿉니다. `test_db.py`의 테이블 목록 테스트에 위 6개 테이블을 추가합니다.

- [ ] **Step 4: 통과 확인** — Run: `uv run pytest tests/test_mcp_store.py tests/test_db.py -v` → 전체 통과

- [ ] **Step 5: Commit** — `git commit -m "feat: add MCP model, registry store and migration 4"`

---

### Task 6: 스크립트 저장소 (버전, 해시, 인코딩)

**Files:**
- Create: `server/app/monitor/scripts.py`, `server/tests/test_script_store.py`

**Interfaces:**
- Consumes: `Database`, `AppPaths.scripts_dir`, `Clock`, `McpStore.insert`, `McpStore.get`
- Produces:
  - 상수: `SCRIPT_EXTS = (".ps1", ".bat", ".cmd")`, `MAX_SCRIPT_BYTES = 65_536`
  - 예외: `ScriptValidationError(code: str)` (`code` ∈ `scripts_required`, `script_too_large`, `script_encoding`, `script_empty`, `validation`), `ScriptRequiredError` (start/stop 삭제 시도), `ScriptNotFoundError`
  - `ScriptUpload(NamedTuple)`: `ext: str`, `content: str`
  - `PreparedScript` (frozen dataclass): `kind`, `ext`, `text: str`(정규화된 내용), `data: bytes`(파일에 쓸 바이트), `sha256: str`(= `sha256(data)`)
  - `prepare_script(kind: str, upload: ScriptUpload) -> PreparedScript`:
    - 줄바꿈을 CRLF로 통일하고 끝에 CRLF가 없으면 붙입니다.
    - `.ps1`은 UTF-8 + BOM(`b"\xef\xbb\xbf"`), `.bat`/`.cmd`는 `"oem"` 코덱(strict). 인코딩할 수 없으면 `script_encoding`입니다.
    - 공백뿐이면 `script_empty`, 인코딩 후 65,536바이트를 넘으면 `script_too_large`, 종류·확장자가 틀리면 `validation`입니다.
  - `ScriptInfo` (frozen dataclass): `kind`, `ext`, `sha256`, `version: int`, `updated_at: datetime`, `updated_by: int | None`, `path: Path`
  - `ScriptVersion` (frozen dataclass): `version`, `ext: str | None`, `sha256: str | None`, `content: str | None`, `author_id: int | None`, `created_at: datetime`; property `deleted -> bool`
  - `ScriptStore(db, paths: AppPaths, clock, mcps: McpStore)`:
    - `.create_mcp(config: McpConfig, owner_id: int, uploads: Mapping[str, ScriptUpload]) -> Mcp`: start·stop이 없으면 `ScriptValidationError("scripts_required")`
    - `.get(mcp_id, kind) -> ScriptInfo | None`, `.list(mcp_id) -> list[ScriptInfo]`, `.content(mcp_id, kind) -> str | None`
    - `.put(mcp_id, kind, upload, author_id) -> ScriptInfo` (`McpNotFoundError`)
    - `.delete(mcp_id, kind, author_id) -> None`: start/stop이면 `ScriptRequiredError`, 없으면 `ScriptNotFoundError`
    - `.versions(mcp_id, kind) -> list[ScriptVersion]` (최신순), `.version(mcp_id, kind, version) -> ScriptVersion | None`
    - `.revert(mcp_id, kind, version, author_id) -> ScriptInfo`: 대상이 삭제 표시면 `ScriptValidationError("validation")`, 없으면 `ScriptNotFoundError`
    - `.remove_dir(mcp_id) -> None`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_script_store.py
import hashlib, pytest
from app.monitor.scripts import ScriptStore, ScriptUpload as U, prepare_script, ScriptValidationError, ScriptRequiredError
from app.monitor.store import McpStore
from app.users.store import UserStore
from tests.test_mcp_store import cfg

BASIC = {"start": U(".bat", "@echo off\nexit /b 0"), "stop": U(".bat", "exit /b 0")}

@pytest.fixture
def env(db, paths, clock):
    users = UserStore(db, clock); owner = users.create("o@x.com", "o", "developer", None)
    mcps = McpStore(db, clock, users)
    return ScriptStore(db, paths, clock, mcps), mcps, owner, paths

def test_prepare_ps1_bom_crlf():
    p = prepare_script("start", U(".ps1", "Write-Output '시작'\nexit 0"))
    assert p.data == b"\xef\xbb\xbf" + "Write-Output '시작'\r\nexit 0\r\n".encode("utf-8")
    assert p.sha256 == hashlib.sha256(p.data).hexdigest()

def test_prepare_bat_crlf():
    assert prepare_script("stop", U(".bat", "@echo off\r\nexit /b 0\n")).data == b"@echo off\r\nexit /b 0\r\n"

@pytest.mark.parametrize("kind,upload,code", [
    ("start", U(".exe", "x"), "validation"), ("deploy", U(".bat", "x"), "validation"),
    ("start", U(".bat", "  \n "), "script_empty"), ("start", U(".bat", "\U0001F600"), "script_encoding"),
    ("start", U(".ps1", "가" * 30_000), "script_too_large"),
])
def test_prepare_rejects(kind, upload, code):
    with pytest.raises(ScriptValidationError) as e: prepare_script(kind, upload)
    assert e.value.code == code

def test_create_mcp_writes_files(env):
    s, _, owner, paths = env
    m = s.create_mcp(cfg(), owner.id, BASIC)
    info = s.get(m.id, "start")
    assert info.path == paths.scripts_dir / str(m.id) / "start.bat" and info.version == 1
    assert hashlib.sha256(info.path.read_bytes()).hexdigest() == info.sha256
    assert s.get(m.id, "restart") is None and s.content(m.id, "stop") == "exit /b 0\r\n"

def test_create_requires_start_and_stop(env):
    s, mcps, owner, _ = env
    with pytest.raises(ScriptValidationError) as e: s.create_mcp(cfg(), owner.id, {"start": BASIC["start"]})
    assert e.value.code == "scripts_required" and mcps.list() == []

def test_put_versions_and_ext_switch(env):
    s, _, owner, paths = env; m = s.create_mcp(cfg(), owner.id, BASIC)
    info = s.put(m.id, "start", U(".ps1", "exit 0"), owner.id)
    d = paths.scripts_dir / str(m.id)
    assert info.version == 2 and (d / "start.ps1").exists() and not (d / "start.bat").exists()
    assert [v.version for v in s.versions(m.id, "start")] == [2, 1]
    assert s.versions(m.id, "start")[0].author_id == owner.id

def test_delete_only_restart(env):
    s, _, owner, paths = env; m = s.create_mcp(cfg(), owner.id, {**BASIC, "restart": U(".bat", "exit /b 0")})
    s.delete(m.id, "restart", owner.id)
    assert s.get(m.id, "restart") is None and not (paths.scripts_dir / str(m.id) / "restart.bat").exists()
    assert s.versions(m.id, "restart")[0].deleted is True
    with pytest.raises(ScriptRequiredError): s.delete(m.id, "start", owner.id)

def test_revert(env):
    s, _, owner, _ = env; m = s.create_mcp(cfg(), owner.id, BASIC)
    v1 = s.get(m.id, "start"); s.put(m.id, "start", U(".ps1", "exit 0"), owner.id)
    info = s.revert(m.id, "start", 1, owner.id)
    assert (info.version, info.ext, info.sha256) == (3, ".bat", v1.sha256)
    assert info.path.read_bytes() == v1.path.read_bytes()

def test_create_failure_leaves_nothing(env, monkeypatch):
    s, mcps, owner, paths = env
    import app.monitor.scripts as mod
    real, calls = mod.os.replace, []
    def flaky(a, b):
        calls.append(a)
        if len(calls) == 2: raise OSError("disk")
        real(a, b)
    monkeypatch.setattr(mod.os, "replace", flaky)
    with pytest.raises(OSError): s.create_mcp(cfg(), owner.id, BASIC)
    assert mcps.list() == [] and list(paths.scripts_dir.iterdir()) == []
```

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_script_store.py -v` → FAIL

- [ ] **Step 3: 구현**

- 쓰기 순서(`put`, `revert`, `create_mcp` 공통):
  1. `prepare_script`
  2. `<kind><ext>.tmp`에 바이트 쓰기
  3. `db.transaction()` 안에서 버전 행 삽입, `mcp_scripts` upsert, **마지막 문장으로** `os.replace(tmp, final)`
  4. 커밋 후 같은 종류의 다른 확장자 파일 삭제
- `os.replace`가 실패하면 트랜잭션이 롤백되고 기존 파일은 그대로 남습니다. `create_mcp`는 하나의 트랜잭션에서 `mcps.insert`와 모든 스크립트를 처리합니다. 실패하면 `shutil.rmtree(dir, ignore_errors=True)`로 디렉터리를 지우고 예외를 다시 던집니다.
- 작성자는 `create_mcp`에서는 `owner_id`, 나머지에서는 `author_id`입니다.
- 디렉터리 ACL(SYSTEM + Administrators)은 설치 스크립트(Plan 5)에서 겁니다.

- [ ] **Step 4: 통과 확인** — Run: `uv run pytest tests/test_script_store.py -v` → 전체 통과

- [ ] **Step 5: Commit** — `git commit -m "feat: add versioned script store with hashing and Windows encodings"`

---

### Task 7: 스크립트 실행기 (R20 예외 격리)

**Files:**
- Modify: `server/pyproject.toml` (`psutil` 런타임 추가, `httpx`를 런타임으로 이동), `server/uv.lock`
- Create: `server/app/monitor/runner.py`, `server/tests/test_script_runner.py`

**Interfaces:**
- Consumes: `ScriptStatus`
- Produces:
  - 상수: `MAX_TIMEOUT_SEC = 120`, `OUTPUT_CAP_BYTES = 1_048_576`, `DEFAULT_CONCURRENCY = 4`, `PIPE_DRAIN_SEC = 1.0`, `KILL_WAIT_SEC = 5.0`
  - `ScriptResult` (frozen dataclass): `status: ScriptStatus`, `exit_code: int | None`, `duration_ms: int`, `stdout: str`, `stderr: str`, `stdout_truncated: bool`, `stderr_truncated: bool`, `killed: int`, `error: str | None`, `actual_sha256: str | None`. `error` ∈ `missing`, `hash_mismatch`, `unsupported`, `spawn_failed`, `internal`.
  - `effective_timeout(requested: float) -> float`: `max(1.0, min(requested, 120.0))`
  - `build_argv(path: Path) -> list[str]`:
    - `.ps1` → `[%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(path)]`
    - `.bat`/`.cmd` → `[%SystemRoot%\System32\cmd.exe, "/d", "/c", str(path)]`
    - 그 밖은 `ValueError`. 인터프리터는 PATH가 아니라 절대 경로로 지정합니다.
  - `decode_output(data: bytes) -> str`: UTF-8(BOM 제거)로 읽고, 실패하면 `data.decode("oem", errors="replace")`
  - `kill_tree(pid: int) -> int` (블로킹): `children(recursive=True)`와 부모를 모두 `kill`하고, `psutil.wait_procs(timeout=KILL_WAIT_SEC)`로 끝난 프로세스 수를 돌려줍니다. 이미 없으면 0입니다.
  - `ScriptRunner(concurrency: int = DEFAULT_CONCURRENCY)`:
    - `async .run(path: Path, *, expected_sha256: str, timeout_sec: float, env: Mapping[str, str], lock_key: Hashable) -> ScriptResult`: **절대 예외를 던지지 않습니다**(`CancelledError` 제외).
    - `.active: int`, `.peak_active: int` (관측용, 테스트가 0으로 되돌릴 수 있음)

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_script_runner.py
import asyncio, hashlib, sys, time, uuid, psutil, pytest
from pathlib import Path
from app.monitor.runner import ScriptRunner, effective_timeout, build_argv, decode_output

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
ENV = {"PYTHON": sys.executable, "MCP_ID": "7", "MCP_NAME": "calc", "MCP_TRIGGER": "auto"}

def write(tmp_path, name, text, bom=False):
    data = (b"\xef\xbb\xbf" if bom else b"") + text.replace("\n", "\r\n").encode("utf-8")
    p = tmp_path / name; p.write_bytes(data); return p, hashlib.sha256(data).hexdigest()

async def run(runner, p, sha, timeout=10, key=1):
    return await runner.run(p, expected_sha256=sha, timeout_sec=timeout, env=ENV, lock_key=key)

def marker_alive(marker):
    return any(marker in " ".join(pr.info["cmdline"] or []) for pr in psutil.process_iter(["cmdline"]))

def kill_marker(marker):
    for pr in psutil.process_iter(["cmdline"]):
        if marker in " ".join(pr.info["cmdline"] or []): pr.kill()

async def test_bat_ok_with_env(tmp_path):
    p, sha = write(tmp_path, "start.bat", "@echo off\necho %MCP_ID% %MCP_TRIGGER%\nexit /b 0")
    r = await run(ScriptRunner(), p, sha)
    assert (r.status, r.exit_code, r.killed, r.error) == ("ok", 0, 0, None) and "7 auto" in r.stdout

async def test_ps1_korean_output(tmp_path):
    try: "시작".encode("oem")
    except UnicodeEncodeError: pytest.skip("OEM code page cannot encode Korean")
    p, sha = write(tmp_path, "start.ps1", "Write-Output \"$env:MCP_NAME 시작\"\nexit 0", bom=True)
    r = await run(ScriptRunner(), p, sha)
    assert r.status == "ok" and "calc 시작" in r.stdout

async def test_failed_exit_code(tmp_path):
    p, sha = write(tmp_path, "stop.bat", "@echo off\necho bad 1>&2\nexit /b 3")
    r = await run(ScriptRunner(), p, sha)
    assert (r.status, r.exit_code) == ("failed", 3) and "bad" in r.stderr

async def test_missing_and_unsupported(tmp_path):
    r = await run(ScriptRunner(), tmp_path / "nope.bat", "0" * 64)
    assert (r.status, r.error, r.exit_code) == ("error", "missing", None)
    p, sha = write(tmp_path, "x.py", "print(1)")
    assert (await run(ScriptRunner(), p, sha)).error == "unsupported"

async def test_hash_mismatch_does_not_execute(tmp_path):
    flag = tmp_path / "ran.txt"
    p, sha = write(tmp_path, "start.bat", f"@echo off\necho x > \"{flag}\"")
    r = await run(ScriptRunner(), p, "0" * 64)
    assert (r.status, r.error, r.actual_sha256) == ("error", "hash_mismatch", sha) and not flag.exists()

async def test_timeout_kills_tree(tmp_path):
    marker = uuid.uuid4().hex
    p, sha = write(tmp_path, "start.bat", f'@echo off\nstart "" /b "%PYTHON%" -c "import time; time.sleep(60)" {marker}\nping -n 60 127.0.0.1 >nul')
    t = time.perf_counter(); r = await run(ScriptRunner(), p, sha, timeout=2)
    assert r.status == "timeout" and r.exit_code is None and r.killed >= 2
    assert time.perf_counter() - t < 8 and not marker_alive(marker)

async def test_output_capped(tmp_path):
    p, sha = write(tmp_path, "start.bat", '@echo off\n"%PYTHON%" -c "import sys; sys.stdout.write(\'x\' * 5_000_000)"')
    r = await run(ScriptRunner(), p, sha, timeout=30)
    assert r.status == "ok" and len(r.stdout.encode()) == 1_048_576 and r.stdout_truncated is True

async def test_background_child_holding_pipe_does_not_block(tmp_path):
    marker = uuid.uuid4().hex
    p, sha = write(tmp_path, "start.bat", f'@echo off\nstart "" /b "%PYTHON%" -c "import time; time.sleep(30)" {marker}\nexit /b 0')
    try:
        r = await run(ScriptRunner(), p, sha)
        assert r.status == "ok" and r.killed == 0 and r.duration_ms < 5000
        assert marker_alive(marker)
    finally:
        kill_marker(marker)

async def test_per_key_lock_and_global_cap(tmp_path):
    p, sha = write(tmp_path, "s.bat", "@echo off\nping -n 2 127.0.0.1 >nul")
    runner = ScriptRunner(concurrency=4)
    await asyncio.gather(run(runner, p, sha, key=1), run(runner, p, sha, key=1))
    assert runner.peak_active == 1
    runner.peak_active = 0
    rs = await asyncio.gather(*(run(runner, p, sha, key=k) for k in range(6)))
    assert runner.peak_active == 4 and all(r.status == "ok" for r in rs)

async def test_spawn_failure_is_result(tmp_path, monkeypatch):
    p, sha = write(tmp_path, "start.bat", "exit /b 0")
    async def boom(*a, **k): raise PermissionError("denied")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", boom)
    r = await run(ScriptRunner(), p, sha)
    assert (r.status, r.error) == ("error", "spawn_failed")

def test_effective_timeout_and_argv():
    assert (effective_timeout(300), effective_timeout(30)) == (120.0, 30.0)
    ps = build_argv(Path(r"C:\s\start.ps1"))
    assert ps[0].lower().endswith(r"windowspowershell\v1.0\powershell.exe")
    assert ps[1:] == ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", r"C:\s\start.ps1"]
    assert build_argv(Path(r"C:\s\stop.cmd"))[1:] == ["/d", "/c", r"C:\s\stop.cmd"]

def test_decode_output():
    assert decode_output(b"\xef\xbb\xbfok") == "ok"
```

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_script_runner.py -v` → FAIL

- [ ] **Step 3: 구현** — `run`의 순서는 다음과 같습니다.
  1. MCP별 `asyncio.Lock`(키마다 하나)을 먼저 얻고, 그다음 전역 `asyncio.Semaphore`를 얻습니다. 같은 MCP 잠금을 기다리는 동안 전역 슬롯을 차지하지 않게 하기 위해서입니다. 세마포어를 얻은 동안만 `active`가 늘어납니다.
  2. 확장자 검사(`unsupported`) → `asyncio.to_thread`로 바이트 읽기(`missing`) → sha256 비교(`hash_mismatch`, 실행하지 않음)
  3. `asyncio.create_subprocess_exec(*build_argv(path), stdin=DEVNULL, stdout=PIPE, stderr=PIPE, env={**os.environ, **env}, cwd=path.parent, creationflags=subprocess.CREATE_NO_WINDOW)`. `OSError`/`PermissionError`이면 `spawn_failed`입니다.
  4. stdout/stderr를 64KB 단위로 읽는 task 2개를 둡니다. 각 1MB까지만 모으고, 그 뒤는 버리면서 계속 읽습니다(자식이 막히지 않게).
  5. **완료 판단은 `proc.wait()`입니다**(`asyncio.wait_for(..., effective_timeout(timeout_sec))`). 시간을 넘기면 `killed = await asyncio.to_thread(kill_tree, proc.pid)`, 상태는 `timeout`입니다.
  6. 종료 후 읽기 task를 최대 `PIPE_DRAIN_SEC` 기다리고 취소한 다음 `proc._transport.close()`를 부릅니다. private이지만, 상속된 파이프 핸들을 놓아줄 방법이 이것뿐입니다. 정상 종료한 스크립트의 자식은 건드리지 않습니다.
  7. 예상하지 못한 예외는 모두 `error="internal"`로 바꿉니다. `CancelledError`(서비스 종료)에서는 기다리기만 멈추고 프로세스는 죽이지 않습니다(강제 종료는 timeout일 때만).

- [ ] **Step 4: 통과 확인** — Run: `uv run pytest tests/test_script_runner.py -v` → 전체 통과. Run: `uv run pip-audit` → 0건

- [ ] **Step 5: Commit** — `git commit -m "feat: add isolated script runner with timeout tree kill and output caps"`

---

### Task 8: 모니터 엔진 상태 머신

**Files:**
- Create: `server/app/monitor/engine.py`, `server/tests/test_engine.py`

**Interfaces:**
- Consumes: `McpConfig`, `McpState`, `Issue`, `ALERT_ONLY_ISSUES`, `CheckResult`, `ActionKind`, `Trigger`, `ScriptStatus`, `Clock`
- Produces:
  - 효과 (frozen dataclass): `Transition(from_state: McpState, to_state: McpState, issue: Issue | None)`, `RunScript(kind: ActionKind, trigger: Trigger, reason: str)`(reason = 이슈 값 또는 `"manual"`), `Alert(issue: Issue)`; `Effect = Transition | RunScript | Alert`
  - `ActionInProgressError(Exception)`
  - `EngineSnapshot` (frozen dataclass): `state`, `issue: Issue | None`, `state_since: datetime`, `action_due_at: datetime | None`, `auto_actions_in_window: int`, `alerted: bool`, `running: RunScript | None`
  - `McpEngine(config: McpConfig, clock: Clock)`: `config.maintenance`이면 `MAINTENANCE`, 아니면 `HEALTHY`로 시작합니다.
    - `.state`, `.config` (property)
    - `.on_check(result) -> list[Effect]`, `.boot(result) -> list[Effect]`, `.tick() -> list[Effect]`
    - `.on_action_done(run: RunScript, status: ScriptStatus) -> list[Effect]`
    - `.manual(kind: ActionKind) -> list[Effect]` (실행 중이면 `ActionInProgressError`)
    - `.set_maintenance(on: bool) -> list[Effect]`, `.reconfigure(config) -> None`
    - `.needs_issue_check() -> bool` (HEALTHY), `.needs_confirm() -> bool` (SUSPECT·RECOVERING), `.snapshot() -> EngineSnapshot`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_engine.py
import pytest
from datetime import timedelta
from app.monitor.engine import McpEngine, Transition as T, RunScript as R, Alert, ActionInProgressError
from app.monitor.models import CheckResult, Issue, McpState as S
from tests.test_mcp_store import cfg

PD, UN, ND = Issue.PROCESS_DOWN, Issue.UNRESPONSIVE, Issue.NETWORK_DOWN

def ok(clock): return CheckResult(clock.now(), None, 5.0, 1, "python.exe", None)
def bad(clock, issue=PD): return CheckResult(clock.now(), issue, None, None, None, "connect")
def eng(clock, **kw): return McpEngine(cfg(**{"action_delay_sec": 30, "startup_grace_sec": 30, **kw}), clock)

def to_action(e, clock, issue=PD):
    e.on_check(bad(clock, issue)); clock.advance(30); return e.on_check(bad(clock, issue))

def test_suspect_then_back_to_healthy(clock):
    e = eng(clock)
    assert e.on_check(bad(clock)) == [T(S.HEALTHY, S.SUSPECT, PD)]
    assert e.on_check(ok(clock)) == [T(S.SUSPECT, S.HEALTHY, None)]

def test_accumulates_to_start(clock):
    e = eng(clock); t0 = clock.now(); e.on_check(bad(clock))
    clock.advance(29); assert e.on_check(bad(clock)) == []
    assert e.snapshot().action_due_at == t0 + timedelta(seconds=30)
    clock.advance(1)
    assert e.on_check(bad(clock)) == [T(S.SUSPECT, S.ACTION, PD), R("start", "auto", "PROCESS_DOWN")]

def test_unresponsive_restarts(clock):
    assert to_action(eng(clock), clock, UN)[-1] == R("restart", "auto", "UNRESPONSIVE")

def test_grace_recovering_healthy(clock):
    e = eng(clock); run = to_action(e, clock)[-1]
    assert e.on_check(bad(clock)) == []                       # ACTION 중 점검 무시
    assert e.on_action_done(run, "ok") == []
    clock.advance(29); assert e.tick() == []
    clock.advance(1); assert e.tick() == [T(S.ACTION, S.RECOVERING, PD)]
    assert e.on_check(ok(clock)) == [T(S.RECOVERING, S.HEALTHY, None)]

def test_recovering_failure_back_to_suspect(clock):
    e = eng(clock, startup_grace_sec=0); run = to_action(e, clock)[-1]
    assert e.on_action_done(run, "ok") == [T(S.ACTION, S.RECOVERING, PD)]
    assert e.on_check(bad(clock)) == [T(S.RECOVERING, S.SUSPECT, PD)]

def test_budget_exhausted_stops_and_fails(clock):
    e = eng(clock, startup_grace_sec=0, max_auto_actions=2)
    for _ in range(2):
        run = to_action(e, clock)[-1]; e.on_action_done(run, "ok")
    e.on_check(bad(clock)); clock.advance(30)
    assert e.on_check(bad(clock)) == [T(S.SUSPECT, S.FAILED, PD), R("stop", "auto", "PROCESS_DOWN"), Alert(PD)]
    assert e.on_check(ok(clock)) == [] and e.state == S.FAILED

def test_budget_window_expires(clock):
    e = eng(clock, startup_grace_sec=0, max_auto_actions=1, window_sec=600)
    run = to_action(e, clock)[-1]; e.on_action_done(run, "ok"); e.on_check(ok(clock))
    clock.advance(601)
    assert to_action(e, clock)[-1] == R("start", "auto", "PROCESS_DOWN")

def test_non_ok_result_backs_off(clock):
    e = eng(clock); run = to_action(e, clock)[-1]
    assert e.on_action_done(run, "timeout") == [T(S.ACTION, S.SUSPECT, PD)]
    assert e.snapshot().action_due_at == clock.now() + timedelta(seconds=30)
    assert e.snapshot().auto_actions_in_window == 1

@pytest.mark.parametrize("kw,issue", [({}, ND), ({"auto_recovery": False}, PD)])
def test_alert_only(clock, kw, issue):
    e = eng(clock, **kw); e.on_check(bad(clock, issue))
    assert e.snapshot().action_due_at is None
    clock.advance(30); assert e.on_check(bad(clock, issue)) == [Alert(issue)]
    clock.advance(30); assert e.on_check(bad(clock, issue)) == [] and e.state == S.SUSPECT

def test_manual_stop_is_maintenance(clock):
    e = eng(clock)
    assert e.manual("stop") == [T(S.HEALTHY, S.MAINTENANCE, None), R("stop", "manual", "manual")]
    with pytest.raises(ActionInProgressError): e.manual("start")
    e.on_action_done(R("stop", "manual", "manual"), "ok")
    assert e.on_check(bad(clock)) == [] and e.state == S.MAINTENANCE

def test_manual_start_from_failed_and_non_ok(clock):
    e = eng(clock, startup_grace_sec=0, max_auto_actions=1)
    run = to_action(e, clock)[-1]; e.on_action_done(run, "ok"); to_action(e, clock)
    assert e.state == S.FAILED
    e.on_action_done(R("stop", "auto", "PROCESS_DOWN"), "ok")
    assert e.manual("start") == [T(S.FAILED, S.ACTION, None), R("start", "manual", "manual")]
    assert e.on_action_done(R("start", "manual", "manual"), "failed") == [T(S.ACTION, S.RECOVERING, None)]

def test_maintenance_toggle_and_initial(clock):
    e = eng(clock)
    assert e.set_maintenance(True) == [T(S.HEALTHY, S.MAINTENANCE, None)]
    assert e.set_maintenance(False) == [T(S.MAINTENANCE, S.HEALTHY, None)]
    assert eng(clock, maintenance=True).state == S.MAINTENANCE

def test_result_ignored_after_maintenance(clock):
    e = eng(clock); run = to_action(e, clock)[-1]
    e.set_maintenance(True)
    assert e.on_action_done(run, "ok") == [] and e.state == S.MAINTENANCE and e.snapshot().running is None

def test_boot(clock):
    e = eng(clock, autostart_on_boot=True)
    assert e.boot(bad(clock)) == [T(S.HEALTHY, S.ACTION, PD), R("start", "boot", "PROCESS_DOWN")]
    assert e.snapshot().auto_actions_in_window == 0
    assert eng(clock).boot(bad(clock)) == [T(S.HEALTHY, S.SUSPECT, PD)]
    assert eng(clock, autostart_on_boot=True, maintenance=True).boot(bad(clock)) == []
```

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_engine.py -v` → FAIL

- [ ] **Step 3: 구현** — 아래 전이표를 그대로 따릅니다. 효과 순서는 항상 `Transition` → `RunScript` → `Alert`입니다. 상태가 바뀌지 않으면 `Transition`을 내지 않습니다.

| 상태 | 사건 | 조건 | 결과 |
|---|---|---|---|
| HEALTHY | 점검 이슈 | | → SUSPECT, `suspect_since = result.at` |
| SUSPECT | 점검 정상 | | → HEALTHY, `alerted = False` |
| SUSPECT | 점검 이슈 | `at - suspect_since < action_delay_sec` | 이슈만 갱신 |
| SUSPECT | 점검 이슈 | 지연 도달, 알림 전용 이슈 또는 `auto_recovery=False` | `alerted`가 아니면 `Alert`, `alerted = True`, SUSPECT 유지 |
| SUSPECT | 점검 이슈 | 지연 도달, 조치 대상, 창(`window_sec`) 안 자동 조치 수 < `max_auto_actions` | 자동 조치 시각 기록, → ACTION, `RunScript(PROCESS_DOWN이면 start, 아니면 restart, "auto")` |
| SUSPECT | 점검 이슈 | 지연 도달, 한도 소진 | → FAILED, `RunScript(stop, "auto")`, `Alert` |
| ACTION | 점검 | | 무시 |
| ACTION | 실행 완료 `ok` | | `grace_until = now + startup_grace_sec` (0이면 즉시 → RECOVERING) |
| ACTION | 실행 완료 `ok` 아님 | trigger `manual` | → RECOVERING |
| ACTION | 실행 완료 `ok` 아님 | trigger `auto`/`boot` | → SUSPECT, `suspect_since = now` (지연만큼 다시 기다림 = 백오프) |
| ACTION | tick | 실행 중 아님, `now >= grace_until` | → RECOVERING |
| RECOVERING | 점검 정상 / 이슈 | | → HEALTHY / → SUSPECT(`suspect_since = at`) |
| FAILED, MAINTENANCE | 점검 | | 무시 (FAILED는 수동 조치나 점검 모드로만 벗어남) |
| 모든 상태 | `manual(start/restart)` | 실행 중 아님 | → ACTION, `RunScript(kind, "manual", "manual")` |
| 모든 상태 | `manual(stop)` | 실행 중 아님 | → MAINTENANCE, `RunScript("stop", "manual", "manual")` |
| 모든 상태 | `set_maintenance(True)` / MAINTENANCE에서 `False` | | → MAINTENANCE / → HEALTHY |
| HEALTHY | `boot(result)` | `autostart_on_boot`, 이슈 = PROCESS_DOWN | → ACTION, `RunScript("start", "boot", "PROCESS_DOWN")` (예산에 넣지 않음) |

`Transition.issue`는 전이 후 엔진의 현재 이슈입니다. 수동 조치와 MAINTENANCE·HEALTHY 진입은 이슈를 None으로 비웁니다. 자동 조치 경로(SUSPECT → ACTION → RECOVERING)는 이슈를 유지합니다. `on_action_done`은 항상 `running`을 비웁니다. 상태가 ACTION이 아니면 다른 일은 하지 않습니다. 수동·boot 조치는 자동 조치 예산에 넣지 않습니다. `action_due_at`은 SUSPECT이고, 조치 대상이고, `auto_recovery`이고, `alerted`가 아닐 때만 `suspect_since + action_delay_sec`이며, 나머지 경우는 None입니다.

- [ ] **Step 4: 통과 확인** — Run: `uv run pytest tests/test_engine.py -v` → 전체 통과

- [ ] **Step 5: Commit** — `git commit -m "feat: add pure MCP monitor state machine"`

---

### Task 9: 프로브와 이슈 분류

**Files:**
- Create: `server/app/monitor/probes.py`, `server/tests/live.py`, `server/tests/test_probes.py`
- Modify: `server/tests/test_e2e_serve.py` (`free_port`를 `tests.live`에서 가져오게), `server/tests/fakes.py` (`make_mcp`)

**Interfaces:**
- Consumes: `Mcp`, `CheckResult`, `Issue`, `Clock`
- Produces:
  - 상수: `PROBE_TIMEOUT_SEC = 3.0`, `MAX_RESPONSE_BYTES = 65_536`, `MCP_PROTOCOL_VERSION = "2025-06-18"`, `PORT_CACHE_TTL_SEC = 0.5`
  - `ProbeResult` (frozen dataclass): `ok: bool`, `latency_ms: float | None`, `error: str | None`. `error` ∈ `timeout`, `connect`, `http_<status>`, `rpc_error`, `bad_response`, `too_large`, `no_reply`
  - `McpPingClient(http: httpx.AsyncClient)`: `async .ping(url: str, timeout: float) -> ProbeResult`, `.forget(url) -> None`
  - `async probe_tcp(host: str, port: int, timeout: float) -> ProbeResult`
  - `async probe_icmp(host: str, timeout: float) -> ProbeResult`: `%SystemRoot%\System32\PING.EXE -n 1 -w <ms> <host>`를 asyncio subprocess로 실행합니다. 종료 코드 0이면서 출력에 `TTL=`가 있어야 ok입니다.
  - `parse_ping_output(text: str) -> float | None`: 정규식 `[=<](\d+)ms\s+TTL=`
  - `listening_ports() -> dict[int, int]` (블로킹, port → pid, LISTEN만), `process_name(pid: int) -> str | None` (블로킹, `AccessDenied`/`NoSuchProcess`이면 None)
  - `local_addresses() -> frozenset[str]` (`"localhost"`, 소문자 hostname, `psutil.net_if_addrs()`의 모든 IP), `is_local_host(host: str, local: frozenset[str]) -> bool` (루프백 IP 포함)
  - `classify(*, local: bool, port_known: bool, listening_pid: int | None, process_name: str | None, expected_process_name: str | None, probe_ok: bool, icmp_ok: bool | None) -> Issue | None`
  - `Prober(clock: Clock, http: httpx.AsyncClient | None = None, timeout: float = PROBE_TIMEOUT_SEC)`: `async .probe(mcp) -> ProbeResult`, `async .check(mcp) -> CheckResult`, `.forget(mcp_id: int) -> None`, `async .aclose()`
  - `tests.live`: `free_port() -> int`, `live_app(app) -> AsyncContextManager[str]` (같은 루프에서 `uvicorn.Server`를 띄우고 `"http://127.0.0.1:<port>"`를 줍니다. `started`를 기다리고, 끝나면 `should_exit`)

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_probes.py
import asyncio, json, os, socket, sys, time, httpx, pytest, psutil
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route
from app.monitor import probes
from app.monitor.models import Issue
from app.monitor.probes import McpPingClient, Prober, classify, parse_ping_output, probe_icmp, probe_tcp, is_local_host, local_addresses
from tests.live import free_port, live_app
from tests.fakes import make_mcp

def fake_mcp(mode="json", delay=0.0, big=False, ping_error=False):
    seen = []; sessions = {"s1"}
    async def handler(request):
        body = await request.json(); seen.append((body["method"], request.headers.get("mcp-session-id")))
        await asyncio.sleep(delay)
        if body["method"] == "initialize":
            sessions.add("s1"); msg = {"jsonrpc": "2.0", "id": body["id"], "result": {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "f", "version": "1"}}}
            headers = {"Mcp-Session-Id": "s1"}
        elif "id" not in body:
            return Response(status_code=202)
        else:
            if request.headers.get("mcp-session-id") not in sessions: return Response(status_code=404)
            msg = {"jsonrpc": "2.0", "id": body["id"], **({"error": {"code": -1, "message": "x"}} if ping_error else {"result": {"pad": "x" * 100_000} if big else {}})}
            headers = {}
        if mode == "sse":
            async def gen(): yield f"event: message\ndata: {json.dumps(msg)}\n\n"
            return StreamingResponse(gen(), media_type="text/event-stream", headers=headers)
        return JSONResponse(msg, headers=headers)
    app = Starlette(routes=[Route("/mcp", handler, methods=["POST"])])
    return app, seen, sessions

@pytest.mark.parametrize("mode", ["json", "sse"])
async def test_mcp_ping_reuses_session(mode):
    app, seen, _ = fake_mcp(mode)
    async with live_app(app) as base, httpx.AsyncClient() as http:
        c = McpPingClient(http)
        r = await c.ping(base + "/mcp", 3.0)
        assert r.ok and r.latency_ms >= 0 and r.error is None
        assert seen == [("initialize", None), ("notifications/initialized", "s1"), ("ping", "s1")]
        assert (await c.ping(base + "/mcp", 3.0)).ok and seen[-1] == ("ping", "s1") and len(seen) == 4

async def test_session_expired_reinitializes():
    app, seen, sessions = fake_mcp()
    async with live_app(app) as base, httpx.AsyncClient() as http:
        c = McpPingClient(http); await c.ping(base + "/mcp", 3.0)
        sessions.clear()
        assert (await c.ping(base + "/mcp", 3.0)).ok
        assert [m for m, _ in seen].count("initialize") == 2

@pytest.mark.parametrize("kw,error", [({"ping_error": True}, "rpc_error"), ({"big": True}, "too_large")])
async def test_mcp_ping_bad_replies(kw, error):
    app, _, _ = fake_mcp(**kw)
    async with live_app(app) as base, httpx.AsyncClient() as http:
        r = await McpPingClient(http).ping(base + "/mcp", 3.0)
    assert (r.ok, r.error) == (False, error)

async def test_mcp_ping_timeout():
    app, _, _ = fake_mcp(delay=2.0)
    async with live_app(app) as base, httpx.AsyncClient() as http:
        t = time.perf_counter(); r = await McpPingClient(http).ping(base + "/mcp", 0.5)
    assert (r.ok, r.error) == (False, "timeout") and time.perf_counter() - t < 1.5

async def test_connect_refused_and_tcp():
    port = free_port()
    async with httpx.AsyncClient() as http:
        assert (await McpPingClient(http).ping(f"http://127.0.0.1:{port}/mcp", 1.0)).error == "connect"
    assert (await probe_tcp("127.0.0.1", port, 1.0)).ok is False
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); s.listen()
        assert (await probe_tcp("127.0.0.1", s.getsockname()[1], 1.0)).ok is True

@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
async def test_icmp_localhost():
    assert (await probe_icmp("127.0.0.1", 1.0)).ok is True

def test_parse_ping_output():
    assert parse_ping_output("Reply from 1.1.1.1: bytes=32 time=12ms TTL=57") == 12.0
    assert parse_ping_output("127.0.0.1의 응답: 바이트=32 시간<1ms TTL=128") == 1.0
    assert parse_ping_output("Destination host unreachable.") is None
    assert parse_ping_output("요청 시간이 만료되었습니다.") is None

D = dict(local=True, port_known=True, listening_pid=10, process_name=None, expected_process_name=None, probe_ok=True, icmp_ok=None)
@pytest.mark.parametrize("kw,expected", [
    ({"listening_pid": None, "probe_ok": False}, Issue.PROCESS_DOWN),
    ({"process_name": "node.exe", "expected_process_name": "python.exe"}, Issue.WRONG_PROCESS),
    ({"process_name": "Python.EXE", "expected_process_name": "python.exe"}, None),
    ({"process_name": None, "expected_process_name": "python.exe"}, None),
    ({"probe_ok": False}, Issue.UNRESPONSIVE),
    ({"local": False, "listening_pid": None}, None),
    ({"local": False, "listening_pid": None, "probe_ok": False, "icmp_ok": False}, Issue.NETWORK_DOWN),
    ({"local": False, "listening_pid": None, "probe_ok": False, "icmp_ok": True}, Issue.UNRESPONSIVE),
])
def test_classify(kw, expected):
    assert classify(**{**D, **kw}) is expected

def test_classify_port_unknown():
    assert classify(**{**D, "port_known": False, "listening_pid": None, "probe_ok": False}) is Issue.UNRESPONSIVE
    assert classify(**{**D, "port_known": False, "listening_pid": None}) is None

def test_listening_ports_and_local():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); s.listen()
        assert probes.listening_ports()[s.getsockname()[1]] == os.getpid()
    local = local_addresses()
    assert all(is_local_host(h, local) for h in ("127.0.0.1", "localhost", "::1", socket.gethostname().lower()))
    assert is_local_host("203.0.113.5", local) is False

async def test_check_process_down(clock):
    p = Prober(clock)
    try:
        r = await p.check(make_mcp(port=free_port()))
        assert r.issue is Issue.PROCESS_DOWN and r.at == clock.now() and r.pid is None
    finally:
        await p.aclose()

async def test_check_survives_port_lookup_failure(clock, monkeypatch):
    def denied(): raise psutil.AccessDenied()
    monkeypatch.setattr(probes, "listening_ports", denied)
    p = Prober(clock)
    try:
        assert (await p.check(make_mcp(port=free_port()))).issue is Issue.UNRESPONSIVE
    finally:
        await p.aclose()
```

`tests/fakes.py`에 `make_mcp(id: int = 1, **config) -> Mcp`를 추가합니다. 기본 config는 `name="m{id}"`, `host="127.0.0.1"`, `port=9100 + id`이고, `owner_id=None`, `created_by=None`, `created_at=2026-11-04T05:00Z`입니다.

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_probes.py -v` → FAIL

- [ ] **Step 3: 구현**

- `McpPingClient.ping`:
  - URL별로 `(session_id | None, protocol_version)`을 캐시합니다. 캐시가 없으면 `initialize`(clientInfo `{"name": "mcp-monitor", "version": app.__version__}`) → `notifications/initialized` 순서로 보냅니다.
  - 그다음 `ping`을 보냅니다. 헤더는 `Accept: application/json, text/event-stream`, `Content-Type: application/json`이고, 세션이 있으면 `Mcp-Session-Id`, 협상한 `MCP-Protocol-Version`을 붙입니다.
  - 캐시한 세션으로 보낸 ping이 404면 캐시를 버리고 같은 호출 안에서 한 번만 다시 초기화합니다.
  - 지연은 ping 요청에 대해서만 `time.perf_counter()`로 잽니다. 호출 전체는 `asyncio.timeout(timeout)`으로 묶습니다.
  - 응답은 `http.stream`으로 받아 64KB를 넘으면 `too_large`입니다. `text/event-stream`이면 `data:` 줄에서 해당 `id`의 JSON을 찾고, 없으면 `no_reply`입니다. 세션 DELETE는 보내지 않습니다(세션 재사용).
- `Prober.check`:
  - `local = is_local_host(host, self._local)`. 이어서 `probe`를 실행합니다.
  - `local`이면 포트 스냅샷(`asyncio.to_thread(listening_ports)`, `PORT_CACHE_TTL_SEC` 동안 모든 MCP가 공유)을 봅니다. 어떤 예외든 나면 `port_known=False`로 둡니다.
  - pid가 있고 `expected_process_name`이 설정되어 있으면 `to_thread(process_name, pid)`.
  - 원격 MCP의 프로브가 실패하면 `icmp_ok`를 구합니다. probe가 icmp였으면 그 결과를 쓰고, 아니면 `probe_icmp`를 실행합니다.
- `classify` 순서:
  - `local and port_known`이면: pid 없음 → PROCESS_DOWN, 이름 불일치(대소문자 무시, 이름을 모르면 검사 생략) → WRONG_PROCESS, 프로브 실패 → UNRESPONSIVE, 그 밖은 None
  - `local and not port_known`이면: 프로브 실패 → UNRESPONSIVE
  - 원격이면: 프로브 성공 → None, `icmp_ok is False` → NETWORK_DOWN, 그 밖은 UNRESPONSIVE

- [ ] **Step 4: 통과 확인** — Run: `uv run pytest tests/test_probes.py tests/test_e2e_serve.py -v` → 전체 통과

- [ ] **Step 5: Commit** — `git commit -m "feat: add MCP ping, tcp, icmp probes and issue classification"`

---

### Task 10: 이력 저장과 보드 버스

**Files:**
- Create: `server/app/monitor/history.py`, `server/app/monitor/bus.py`, `server/tests/test_history.py`, `server/tests/test_bus.py`

**Interfaces:**
- Consumes: `Database`, `Clock`, `ScriptResult`, `McpState`, `Issue`
- Produces:
  - `history.py` 상수: `SPARKLINE_POINTS = 60`, `HISTORY_KEEP_DAYS = 7`
  - `MinuteBucket` (frozen dataclass): `minute: datetime`, `ok: int`, `total: int`, `avg_latency_ms: float | None`, `max_latency_ms: float | None`
  - `ActionRecord` (frozen dataclass): `run_id: str`, `mcp_id: int`, `at: datetime`, `requested: ActionKind`, `kind: ActionKind`, `trigger: Trigger`, `reason: str`, `actor_id: int | None`, `result: ScriptResult`, `id: int | None = None`
  - `TransitionRecord` (frozen dataclass): `at`, `from_state: McpState`, `to_state: McpState`, `issue: Issue | None`
  - `McpHistory(db, clock)`:
    - `.record(mcp_id, at, ok: bool, latency_ms: float | None, counted: bool = True) -> None`: 메모리만 갱신합니다. 분이 바뀌면 지난 분 버킷을 DB에 씁니다. `counted=False`면 스파크라인과 마지막 점검 시각만 갱신합니다.
    - `.sparkline(mcp_id) -> list[float | None]` (실패는 None), `.last_check_at(mcp_id) -> datetime | None`
    - `.uptime(mcp_id, hours: int = 24) -> float | None` (DB와 미기록 버킷 합산, ok/total, 데이터 없으면 None), `.buckets(mcp_id, since: datetime) -> list[MinuteBucket]`
    - `.flush() -> None`: 미기록 버킷을 가산 UPSERT(`ok = ok + excluded.ok` …)한 뒤 비웁니다.
    - `.purge() -> int`: 7일보다 오래된 `mcp_minutes` 삭제
    - `.forget(mcp_id) -> None`
    - `.record_transition(mcp_id, TransitionRecord) -> None`, `.transitions(mcp_id, limit: int = 100) -> list[TransitionRecord]` (최신순)
    - `.record_action(ActionRecord) -> int`: stdout/stderr 전체(각 ≤ 1MB) 저장
    - `.actions(mcp_id, limit: int = 50) -> list[ActionRecord]` (최신순), `.action(mcp_id, action_id) -> ActionRecord | None`
  - `bus.py` 상수: `MAX_STREAMS = 100`, `MAX_PENDING_EVENTS = 100`
  - `StreamLimitError(Exception)`, `Subscription`: `.dirty: set[int]`, `.events: deque[tuple[str, dict]]` (maxlen 100), `.wake: asyncio.Event`
  - `BoardBus(max_streams: int = MAX_STREAMS)`: `.subscribe() -> Subscription` (한도면 `StreamLimitError`), `.unsubscribe(sub)`, `.mark_dirty(mcp_id)`, `.publish(event: str, data: Mapping) -> None`, `.subscriber_count: int`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_history.py
import pytest
from datetime import timedelta
from app.monitor.history import McpHistory, ActionRecord, TransitionRecord
from app.monitor.models import McpState as S, Issue
from app.monitor.runner import ScriptResult
from app.monitor.store import McpStore
from app.users.store import UserStore
from tests.test_mcp_store import cfg

@pytest.fixture
def env(db, clock):
    users = UserStore(db, clock); o = users.create("o@x.com", "o", "developer", None)
    m = McpStore(db, clock, users).create(cfg(), o.id)
    return McpHistory(db, clock), m.id, clock

def test_sparkline_bounded(env):
    h, mid, clock = env
    for i in range(70): h.record(mid, clock.now(), True, float(i))
    h.record(mid, clock.now(), False, None)
    s = h.sparkline(mid)
    assert len(s) == 60 and s[-2] == 69.0 and s[-1] is None and h.last_check_at(mid) == clock.now()

def test_uptime_pending_and_flushed(env, db):
    h, mid, clock = env
    assert h.uptime(mid) is None
    for ok in (True, True, True, False): h.record(mid, clock.now(), ok, 1.0 if ok else None)
    assert h.uptime(mid) == 0.75
    h.flush(); assert h.uptime(mid) == 0.75
    assert McpHistory(db, clock).uptime(mid) == 0.75            # 재시작 후에도 유지

def test_uptime_window_and_not_counted(env):
    h, mid, clock = env
    h.record(mid, clock.now(), False, None); clock.advance(25 * 3600)
    h.record(mid, clock.now(), True, 2.0); h.record(mid, clock.now(), False, None, counted=False)
    assert h.uptime(mid) == 1.0 and h.sparkline(mid)[-1] is None

def test_rollover_buckets_and_additive_flush(env):
    h, mid, clock = env
    h.record(mid, clock.now(), True, 2.0); h.record(mid, clock.now(), True, 4.0)
    h.flush(); h.record(mid, clock.now(), False, None); h.flush()
    clock.advance(60); h.record(mid, clock.now(), True, 1.0)
    b = h.buckets(mid, clock.now() - timedelta(hours=1))
    assert [(x.ok, x.total, x.avg_latency_ms, x.max_latency_ms) for x in b] == [(2, 3, 3.0, 4.0), (1, 1, 1.0, 1.0)]

def test_purge(env, db):
    h, mid, clock = env
    h.record(mid, clock.now(), True, 1.0); h.flush(); clock.advance(8 * 86400)
    h.record(mid, clock.now(), True, 1.0); h.flush()
    assert h.purge() == 1 and len(db.query("SELECT * FROM mcp_minutes")) == 1

def test_transitions_and_actions(env):
    h, mid, clock = env
    h.record_transition(mid, TransitionRecord(clock.now(), S.HEALTHY, S.SUSPECT, Issue.PROCESS_DOWN))
    assert h.transitions(mid)[0].to_state == S.SUSPECT
    res = ScriptResult("ok", 0, 120, "out", "", False, False, 0, None, None)
    aid = h.record_action(ActionRecord("r1", mid, clock.now(), "restart", "stop", "auto", "UNRESPONSIVE", None, res))
    got = h.action(mid, aid)
    assert (got.kind, got.requested, got.result.stdout) == ("stop", "restart", "out") and h.actions(mid)[0].id == aid
```

```python
# server/tests/test_bus.py
import pytest
from app.monitor.bus import BoardBus, StreamLimitError

def test_dirty_and_events():
    bus = BoardBus(); sub = bus.subscribe()
    bus.mark_dirty(3); bus.mark_dirty(3); bus.publish("action", {"run_id": "r"})
    assert sub.dirty == {3} and list(sub.events) == [("action", {"run_id": "r"})] and sub.wake.is_set()

def test_events_bounded_and_limit():
    bus = BoardBus(max_streams=1); sub = bus.subscribe()
    for i in range(150): bus.publish("action", {"i": i})
    assert len(sub.events) == 100 and sub.events[0][1] == {"i": 50}
    with pytest.raises(StreamLimitError): bus.subscribe()
    bus.unsubscribe(sub); assert bus.subscriber_count == 0
```

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_history.py tests/test_bus.py -v` → FAIL

- [ ] **Step 3: 구현** — 위 Interfaces대로 작성합니다.
  - 분 키는 `at`을 UTC 분 단위로 잘라 `"%Y-%m-%dT%H:%MZ"`로 만듭니다.
  - 평균 지연은 `latency_sum / latency_n`이며, 성공 점검만 셉니다.
  - `uptime`은 `SELECT SUM(ok), SUM(total) FROM mcp_minutes WHERE mcp_id = ? AND minute >= ?`에 미기록 버킷을 더해서 구합니다. 캐시는 두지 않습니다(PK 인덱스 범위 조회).

- [ ] **Step 4: 통과 확인** — Run: `uv run pytest tests/test_history.py tests/test_bus.py -v` → 전체 통과

- [ ] **Step 5: Commit** — `git commit -m "feat: add MCP check history, uptime buckets and board bus"`

---

### Task 11: Monitor 실행기와 서비스 연결

**Files:**
- Create: `server/app/monitor/supervisor.py`, `server/tests/test_monitor.py`, `server/tests/mcp_helpers.py`
- Modify: `server/app/services.py`, `server/app/main.py`, `server/tests/fakes.py`, `server/tests/conftest.py`

**Interfaces:**
- Consumes: Task 5–10의 모든 클래스, `SettingsStore`, `LogWriter`, `User`
- Produces:
  - `ScriptRunnerLike` (Protocol): `async run(path, *, expected_sha256, timeout_sec, env, lock_key) -> ScriptResult`. `ProberLike` (Protocol): `async probe(mcp) -> ProbeResult`, `async check(mcp) -> CheckResult`, `forget(mcp_id) -> None`, `async aclose() -> None`
  - `Monitor(*, mcps: McpStore, scripts: ScriptStore, history: McpHistory, settings: SettingsStore, runner: ScriptRunnerLike, prober: ProberLike, log: LogWriter, bus: BoardBus, clock: Clock)`:
    - `async .start(run_loops: bool = True) -> None`: 모든 MCP의 엔진을 만들고, `autostart_on_boot`이면서 점검 모드가 아닌 MCP는 boot 점검을 task로 띄웁니다(`run_loops`와 무관). `run_loops`면 ping / 10초 점검 / 1초 재측정 / 60초 정리(flush, 60회마다 purge) 루프를 시작합니다.
    - `async .stop(grace_sec: float = 10.0) -> None`: 루프와 프로브 task를 취소합니다. 실행 중인 스크립트 task는 `grace_sec`까지 기다린 뒤 취소합니다(프로세스는 죽이지 않음). 이어서 `history.flush()`, `prober.aclose()`.
    - `.add(mcp)`, `.reconfigure(mcp)` (maintenance가 바뀌었으면 `engine.set_maintenance`, URL이 바뀌었으면 `prober.forget`), `.remove(mcp_id)` (실행 중이면 `ActionInProgressError`. `history.forget` 후 `bus.mark_dirty`)
    - `.manual_action(mcp_id: int, kind: ActionKind, actor: User) -> str` (run_id = `uuid4().hex`): MCP가 없으면 `McpNotFoundError`, 실행 중이면 `ActionInProgressError`. stop이면 `mcps.set_maintenance(id, True)`, start/restart이면 `False`로 저장합니다.
    - `async .ping_round()`, `async .issue_round()`, `async .confirm_round()`: task만 띄우고 바로 돌아옵니다. 같은 MCP의 ping·점검이 이미 진행 중이면 건너뜁니다.
    - `async .wait_idle() -> None` (테스트용: 진행 중인 프로브·스크립트 task를 모두 기다림)
    - `.board_item(mcp_id) -> dict | None`, `.board() -> list[dict]` (이름순). 항목 키는 정확히 `id`, `name`, `state`, `issue`, `latency_ms`, `sparkline`, `uptime_24h`, `last_check_at`, `action_due_at`, `action_in_sec`, `maintenance`, `running`입니다. 시각은 KST ISO, `action_in_sec`은 `max(0, due - now)`를 소수 1자리로 반올림, `running`은 실행 중인 kind 또는 None입니다.
    - `.engine(mcp_id) -> McpEngine | None`
  - `Services`에 필드 추가: `mcps: McpStore`, `scripts: ScriptStore`, `history: McpHistory`, `bus: BoardBus`, `monitor: Monitor`. `build_services(..., runner: ScriptRunnerLike | None = None, prober: ProberLike | None = None)`. 기본값은 `ScriptRunner()`, `Prober(clock)`이고, 모니터는 시작하지 않습니다.
  - `serve()`: `log.start()` → `monitor.start()` → 서버 실행. 종료 시 `monitor.stop()` → `log.stop()`.
  - `tests.fakes.FakeRunner`:
    - `.calls: list[RunCall]`, `RunCall(path, expected_sha256, timeout_sec, env, lock_key)`
    - `.results: deque[ScriptResult]` (비면 ok), `.gate: asyncio.Event | None` (설정되면 set될 때까지 대기), `.raise_next: Exception | None`
    - 헬퍼 `ok_result(**kw) -> ScriptResult`
  - `tests.fakes.FakeProber(clock)`:
    - `.set_probe(mcp_id, ProbeResult)`, `.set_check(mcp_id, issue: Issue | None, pid: int | None = None)`, `.delay: float = 0.0`
    - `.probe_calls: list[int]`, `.check_calls: list[int]`
    - 기본은 probe ok(5.0ms), check issue None·pid None입니다.
  - `tests.mcp_helpers`:
    - `BAT = {"start": ScriptUpload(".bat", "exit /b 0"), "stop": ScriptUpload(".bat", "exit /b 0")}`
    - `make_user(services, email, role="developer") -> User`
    - `seed_mcp(services, owner: User, scripts=BAT, **config) -> Mcp` (`scripts.create_mcp` + `monitor.add`. 기본 name `"calc"`, host `127.0.0.1`, port 9102)
    - `login_as(client, services, user, channel) -> str` (세션 직접 생성, 쿠키 설정, csrf 반환)
  - conftest `services` fixture: `build_services(tmp_path, clock=clock, otp_provider=CapturingOtpProvider(), runner=FakeRunner(), prober=FakeProber(clock))`. 정리 시 `await svc.monitor.stop()`.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_monitor.py
import asyncio, json, pytest
from app.monitor.engine import ActionInProgressError
from app.monitor.models import Issue, McpState as S
from app.monitor.probes import ProbeResult
from app.monitor.scripts import ScriptUpload
from tests.fakes import ok_result
from tests.mcp_helpers import make_user, seed_mcp

async def logs(services, cat):
    await services.log.flush()
    return [e for f in services.paths.logs_dir.glob("*.jsonl") for e in map(json.loads, f.read_text("utf-8").splitlines()) if e["cat"] == cat]

async def crash_to_action(services, m, issue=Issue.PROCESS_DOWN):
    mon = services.monitor; services.monitor._prober.set_check(m.id, issue)
    await mon.issue_round(); await mon.wait_idle()
    services.clock.advance(30); await mon.confirm_round(); await mon.wait_idle()

async def test_ping_round_records_history(services):
    m = seed_mcp(services, make_user(services, "o@x.com")); sub = services.bus.subscribe()
    services.monitor._prober.set_probe(m.id, ProbeResult(True, 4.2, None))
    await services.monitor.ping_round(); await services.monitor.wait_idle()
    assert services.history.sparkline(m.id)[-1] == 4.2 and m.id in sub.dirty

async def test_crash_runs_start_and_records(services):
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner)
    await crash_to_action(services, m)
    call = services.monitor._runner.calls[-1]
    assert call.path.name == "start.bat" and call.lock_key == m.id and call.timeout_sec == 120
    assert {k: call.env[k] for k in ("MCP_ID", "MCP_NAME", "MCP_HOST", "MCP_PORT", "MCP_PID", "MCP_REASON", "MCP_TRIGGER", "MCP_ACTOR")} == \
        {"MCP_ID": str(m.id), "MCP_NAME": "calc", "MCP_HOST": "127.0.0.1", "MCP_PORT": "9102", "MCP_PID": "", "MCP_REASON": "PROCESS_DOWN", "MCP_TRIGGER": "auto", "MCP_ACTOR": "system"}
    a = services.history.actions(m.id)[0]
    assert (a.kind, a.trigger, a.result.status) == ("start", "auto", "ok")
    assert services.monitor.engine(m.id).state == S.ACTION
    assert [e["to"] for e in await logs(services, "mcp.health")] == ["SUSPECT", "ACTION"]
    assert (await logs(services, "mcp.action"))[0]["status"] == "ok"

async def test_restart_fallback_stop_then_start(services):
    m = seed_mcp(services, make_user(services, "o@x.com"))
    await crash_to_action(services, m, Issue.UNRESPONSIVE)
    assert [c.path.name for c in services.monitor._runner.calls] == ["stop.bat", "start.bat"]
    assert [a.kind for a in services.history.actions(m.id)] == ["start", "stop"]

async def test_tamper_logged(services):
    m = seed_mcp(services, make_user(services, "o@x.com"))
    services.monitor._runner.results.append(ok_result(status="error", exit_code=None, error="hash_mismatch", actual_sha256="ab" * 32))
    await crash_to_action(services, m)
    t = (await logs(services, "tamper"))[0]
    assert (t["mcp_id"], t["kind"], t["actual_sha256"]) == (m.id, "start", "ab" * 32)
    assert services.monitor.engine(m.id).state == S.SUSPECT

async def test_slow_script_does_not_block_and_conflicts(services):
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner)
    services.monitor._runner.gate = asyncio.Event()
    services.monitor.manual_action(m.id, "start", owner); await asyncio.sleep(0)
    await asyncio.wait_for(services.monitor.ping_round(), 1.0)
    with pytest.raises(ActionInProgressError): services.monitor.manual_action(m.id, "restart", owner)
    with pytest.raises(ActionInProgressError): services.monitor.remove(m.id)
    services.monitor._runner.gate.set(); await services.monitor.wait_idle()
    assert services.monitor._runner.calls[-1].env["MCP_ACTOR"] == "o@x.com"

async def test_manual_stop_persists_maintenance(services):
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner)
    services.monitor.manual_action(m.id, "stop", owner); await services.monitor.wait_idle()
    assert services.mcps.get(m.id).config.maintenance is True
    services.monitor.remove(m.id); services.monitor.add(services.mcps.get(m.id))
    assert services.monitor.engine(m.id).state == S.MAINTENANCE

async def test_boot_autostart(services):
    m = seed_mcp(services, make_user(services, "o@x.com"), autostart_on_boot=True)
    services.monitor._prober.set_check(m.id, Issue.PROCESS_DOWN)
    services.monitor.remove(m.id)
    await services.monitor.start(run_loops=False); await services.monitor.wait_idle()
    assert services.monitor._runner.calls[-1].env["MCP_TRIGGER"] == "boot"

async def test_runner_exception_isolated(services):
    m = seed_mcp(services, make_user(services, "o@x.com"))
    services.monitor._runner.raise_next = RuntimeError("boom")
    await crash_to_action(services, m)
    assert services.monitor.engine(m.id).state == S.SUSPECT
    assert services.history.actions(m.id)[0].result.error == "internal"
    assert any("boom" in e.get("error", "") for e in await logs(services, "system"))

async def test_no_overlapping_checks_for_same_mcp(services):
    m = seed_mcp(services, make_user(services, "o@x.com"))
    services.monitor._prober.delay = 0.3; services.monitor._prober.set_check(m.id, Issue.UNRESPONSIVE)
    await services.monitor.issue_round(); await services.monitor.wait_idle()
    services.monitor._prober.check_calls.clear()
    for _ in range(3): await services.monitor.confirm_round()
    await services.monitor.wait_idle()
    assert services.monitor._prober.check_calls == [m.id]

async def test_probes_run_concurrently(services):
    owner = make_user(services, "o@x.com")
    for i in range(50): seed_mcp(services, owner, name=f"m{i}", port=10000 + i)
    services.monitor._prober.delay = 0.3
    t = asyncio.get_running_loop().time()
    await services.monitor.ping_round(); await services.monitor.wait_idle()
    assert asyncio.get_running_loop().time() - t < 1.0

async def test_timeout_setting_passed(services):
    m = seed_mcp(services, make_user(services, "o@x.com"), script_timeout_sec=30)
    await crash_to_action(services, m)
    assert services.monitor._runner.calls[-1].timeout_sec == 30

async def test_loops_follow_settings(services):
    seed_mcp(services, make_user(services, "o@x.com"))
    services.settings.update({"ping_interval_sec": 1})
    await services.monitor.start(run_loops=True)
    await asyncio.sleep(2.5)
    assert len(services.monitor._prober.probe_calls) >= 2
```

`_runner`, `_prober`는 `Monitor`가 생성자 인자를 그대로 담아 두는 속성 이름입니다(테스트가 접근).

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_monitor.py -v` → FAIL

- [ ] **Step 3: 구현**

- **점검 흐름** `_check(mcp_id)`:
  - `result = await prober.check(mcp)`
  - `history.record(id, result.at, result.issue is None, result.latency_ms, counted=engine.state != MAINTENANCE)`
  - 마지막 pid를 저장합니다(`MCP_PID`용). `_apply(id, engine.on_check(result))` 후 `bus.mark_dirty(id)`
- **ping 흐름**: `probe` → `history.record`(`counted` 규칙은 점검과 같음) → `mark_dirty`
- **회차별 대상**: `issue_round`는 `needs_issue_check()`인 MCP만, `confirm_round`는 먼저 모든 엔진에 `tick()`을 적용하고 `needs_confirm()`인 MCP만 점검합니다. ping은 모든 MCP에 보냅니다.
- **`_apply` 효과 처리**:
  - `Transition`: `history.record_transition` + `mcp.health` 로그(`mcp_id`, `name`, `from`, `to`, `issue`) + `mark_dirty`
  - `Alert`: `mcp.health` 로그(`alert: true`, `issue`)
  - `RunScript`: `_execute` task 생성
- **`_execute(mcp_id, run, actor, run_id)`**:
  - `restart` 스크립트가 없으면 stop → start를 차례로 실행합니다. stop 결과와 관계없이 start를 실행하고, 엔진에는 start의 결과를 넘깁니다.
  - 실행할 때마다 `history.record_action` + `mcp.action` 로그를 남깁니다. 필드는 `mcp_id`, `name`, `run_id`, `kind`, `requested`, `trigger`, `reason`, `actor`, `status`, `exit_code`, `duration_ms`, `killed`, `error`와, 앞 4096자로 자른 `stdout`·`stderr`입니다.
  - `error == "hash_mismatch"`면 `tamper` 로그(`mcp_id`, `kind`, `path`, `expected_sha256`, `actual_sha256`)도 남깁니다.
  - 결과마다 `bus.publish("action", {"run_id", "mcp_id", "kind", "trigger", "status", "exit_code", "duration_ms"})`(출력은 넣지 않음).
  - 전체를 `try/except Exception`으로 감쌉니다. 예외가 나면 `system` 로그(`error=repr(exc)`)와 `ScriptResult(status="error", error="internal")` 행을 남기고, 엔진에 `"error"`를 전달합니다. 마지막에 `_apply(engine.on_action_done(run, status))`.
- **루프**: `while True: await round(); await asyncio.sleep(getattr(settings.get(), key))`. 회차 예외는 `system` 로그만 남기고 계속 돕니다.

- [ ] **Step 4: 통과 확인** — Run: `uv run pytest -q` → 전체 통과 (`test_e2e_serve.py` 포함. 실제 서버도 모니터와 함께 뜨고 꺼져야 합니다)

- [ ] **Step 5: Commit** — `git commit -m "feat: add monitor supervisor loops and wire into services"`

---

### Task 12: 공통 MCP API와 SSE (두 채널)

**Files:**
- Create: `server/app/web/mcp_shared.py`, `server/tests/test_mcp_shared_api.py`
- Modify: `server/app/web/app_factory.py` (두 채널에 `mcp_shared.router` 등록)

**Interfaces:**
- Consumes: `require`, `ApiError`, `client_ip`, `Monitor`, `McpStore`, `McpHistory`, `BoardBus`, `AuditLogger.admin`
- Produces (HTTP, 두 채널):
  - `GET /api/board` (VIEW_BOARD, 익명 가능) → `{"now": kst, "mcps": [board item]}`. host·port·소유자는 넣지 않습니다.
  - `GET /api/stream` (VIEW_BOARD) → SSE. 응답 헤더 `Content-Type: text/event-stream; charset=utf-8`, `Cache-Control: no-store`, `X-Accel-Buffering: no`. 스트림이 한도면 503 `too_many_streams`.
  - `GET /api/mcps` (VIEW_MCP_HISTORY) → `[detail]`. `GET /api/mcps/{mcp_id}` → detail. detail은 McpConfig 전체 필드와 `id`, `owner: {id,email,name} | null`(effective owner), `created_at`, `live: board item`입니다.
  - `GET /api/mcps/{mcp_id}/history?hours=24` (VIEW_MCP_HISTORY, hours 1–168) → `{"buckets": [{minute, ok, total, avg_latency_ms, max_latency_ms}], "transitions": [{at, from, to, issue}], "actions": [{id, run_id, at, requested, kind, trigger, reason, actor_id, status, exit_code, duration_ms, killed, error}]}`
  - `GET /api/mcps/{mcp_id}/actions/{action_id}` (VIEW_MCP_HISTORY) → 위 action 필드 + `stdout`, `stderr`, `stdout_truncated`, `stderr_truncated`
  - `PUT /api/mcps/{mcp_id}` (EDIT_MCP_SETTINGS) 부분 patch → 200 detail. 422 `validation`, 409 `name_taken`/`endpoint_taken`, 404 `not_found`. `monitor.reconfigure`. 실제로 바뀐 값만 `audit.admin(action="mcp_update", target={"mcp_id", "changes": {k: [before, after]}})`. 실패는 `result="error"`.
  - `POST /api/mcps/{mcp_id}/actions/{kind}` (MCP_MANUAL_ACTION, kind ∈ start/restart/stop) → 202 `{"run_id": str}`. 409 `action_in_progress`, 404. audit `mcp_action` `{mcp_id, kind, run_id}`.
  - 경로 파라미터는 `Annotated[int, Path(ge=1, le=2**63 - 1)]`입니다.
  - `mcp_detail(services: Services, mcp: Mcp) -> dict` (위 detail 직렬화, Task 13도 사용)
  - `board_stream(monitor: Monitor, bus: BoardBus, sub: Subscription, *, coalesce_sec: float = 1.0, heartbeat_sec: float = 15.0) -> AsyncIterator[str]`:
    - 첫 이벤트는 `event: board`(GET /api/board와 같은 본문)입니다.
    - 그 뒤 깨어날 때마다, 직전 전송 후 `coalesce_sec`이 지날 때까지 기다렸다가 dirty id마다 `event: mcp`(board item) 또는 `event: mcp_removed`(`{"id"}`)를 보내고, 쌓인 이벤트(`event: action` 등)를 보냅니다.
    - `heartbeat_sec` 동안 아무 일이 없으면 `": ping\n\n"`을 보냅니다.
    - 형식은 `f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"`입니다. `finally`에서 `bus.unsubscribe(sub)`.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_mcp_shared_api.py
import asyncio, json, httpx, pytest
from datetime import timedelta
from app.clock import to_kst_iso
from app.monitor.models import Issue
from app.web.app_factory import create_app
from app.web.mcp_shared import board_stream
from tests.live import live_app
from tests.mcp_helpers import login_as, make_user, seed_mcp
from tests.test_auth_api import audit_events

KEYS = {"id", "name", "state", "issue", "latency_ms", "sparkline", "uptime_24h", "last_check_at", "action_due_at", "action_in_sec", "maintenance", "running"}

async def test_board_anonymous(external_client, services):
    seed_mcp(services, make_user(services, "o@x.com"))
    item = (await external_client.get("/api/board")).json()["mcps"][0]
    assert set(item) == KEYS and item["state"] == "HEALTHY" and item["running"] is None

async def test_board_suspect_countdown(external_client, services):
    m = seed_mcp(services, make_user(services, "o@x.com")); t0 = services.clock.now()
    services.monitor._prober.set_check(m.id, Issue.PROCESS_DOWN)
    await services.monitor.issue_round(); await services.monitor.wait_idle(); services.clock.advance(10)
    item = (await external_client.get("/api/board")).json()["mcps"][0]
    assert (item["state"], item["issue"], item["action_in_sec"]) == ("SUSPECT", "PROCESS_DOWN", 20.0)
    assert item["action_due_at"] == to_kst_iso(t0 + timedelta(seconds=30))

async def test_detail_requires_login(external_client, services):
    m = seed_mcp(services, make_user(services, "o@x.com"))
    for path in ("/api/mcps", f"/api/mcps/{m.id}", f"/api/mcps/{m.id}/history"):
        assert (await external_client.get(path)).status_code == 401

async def test_detail_and_history(external_client, services):
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner); login_as(external_client, services, owner, "external")
    d = (await external_client.get(f"/api/mcps/{m.id}")).json()
    assert d["host"] == "127.0.0.1" and d["owner"]["id"] == owner.id and set(d["live"]) == KEYS
    h = (await external_client.get(f"/api/mcps/{m.id}/history?hours=24")).json()
    assert set(h) == {"buckets", "transitions", "actions"}
    for bad in (0, 169):
        assert (await external_client.get(f"/api/mcps/{m.id}/history?hours={bad}")).status_code == 422
    assert (await external_client.get("/api/mcps/999")).json() == {"error": "not_found"}

async def test_put_settings_external(external_client, services):
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner)
    other = make_user(services, "d@x.com"); csrf = login_as(external_client, services, other, "external"); h = {"X-CSRF-Token": csrf}
    r = await external_client.put(f"/api/mcps/{m.id}", json={"action_delay_sec": 5}, headers=h)
    assert r.status_code == 200 and services.mcps.get(m.id).config.action_delay_sec == 5
    assert services.monitor.engine(m.id).config.action_delay_sec == 5
    ev = [e for e in await audit_events(services, "admin.audit") if e["action"] == "mcp_update"]
    assert ev[-1]["result"] == "ok" and ev[-1]["target"]["changes"] == {"action_delay_sec": [30, 5]}
    for bad in ({"port": 0}, {"bogus": 1}):
        r = await external_client.put(f"/api/mcps/{m.id}", json=bad, headers=h)
        assert r.status_code == 422 and r.json() == {"error": "validation"}
    seed_mcp(services, owner, name="clock", port=9103)
    assert (await external_client.put(f"/api/mcps/{m.id}", json={"name": "Clock"}, headers=h)).json() == {"error": "name_taken"}

async def test_manual_action_flow(external_client, services):
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner)
    assert (await external_client.post(f"/api/mcps/{m.id}/actions/start")).status_code == 401
    csrf = login_as(external_client, services, owner, "external")
    assert (await external_client.post(f"/api/mcps/{m.id}/actions/start")).json() == {"error": "csrf"}
    h = {"X-CSRF-Token": csrf}; services.monitor._runner.gate = asyncio.Event()
    r = await external_client.post(f"/api/mcps/{m.id}/actions/start", headers=h)
    assert r.status_code == 202 and isinstance(r.json()["run_id"], str)
    assert (await external_client.post(f"/api/mcps/{m.id}/actions/stop", headers=h)).json() == {"error": "action_in_progress"}
    assert (await external_client.post(f"/api/mcps/{m.id}/actions/deploy", headers=h)).status_code == 422
    services.monitor._runner.gate.set(); await services.monitor.wait_idle()
    assert (await external_client.post(f"/api/mcps/{m.id}/actions/stop", headers=h)).status_code == 202
    await services.monitor.wait_idle()
    assert services.mcps.get(m.id).config.maintenance is True

async def test_stream_generator(services):
    m = seed_mcp(services, make_user(services, "o@x.com"))
    sub = services.bus.subscribe()
    gen = board_stream(services.monitor, services.bus, sub, coalesce_sec=0.05, heartbeat_sec=0.3)
    first = await anext(gen)
    assert first.startswith("event: board\n") and json.loads(first.split("data: ", 1)[1])["mcps"][0]["id"] == m.id
    for _ in range(3): services.bus.mark_dirty(m.id)
    nxt = await asyncio.wait_for(anext(gen), 1)
    assert nxt.startswith("event: mcp\n") and json.loads(nxt.split("data: ", 1)[1])["id"] == m.id
    assert await asyncio.wait_for(anext(gen), 1) == ": ping\n\n"
    services.monitor.remove(m.id)
    assert (await asyncio.wait_for(anext(gen), 1)).startswith("event: mcp_removed\n")
    await gen.aclose(); assert services.bus.subscriber_count == 0

async def test_stream_over_http(services):
    async with live_app(create_app("external", services)) as base, httpx.AsyncClient() as c:
        async with c.stream("GET", base + "/api/stream") as r:
            assert r.headers["content-type"].startswith("text/event-stream") and r.headers["cache-control"] == "no-store"
            assert (await anext(r.aiter_lines())) == "event: board"

async def test_stream_limit_503(external_client, services, monkeypatch):
    monkeypatch.setattr(services.bus, "_max_streams", 0)
    r = await external_client.get("/api/stream")
    assert r.status_code == 503 and r.json() == {"error": "too_many_streams"}
```

`BoardBus`는 한도를 `self._max_streams`에 담아 둡니다(테스트가 바꿈).

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_mcp_shared_api.py -v` → FAIL

- [ ] **Step 3: 구현** — 위 Interfaces대로 작성합니다.
  - `PUT`은 `McpStore.update`의 `ValidationError`를 잡아 audit(`result="error"`) 후 `ApiError(422, "validation")`을 던집니다(전역 핸들러는 Task 2에서 삭제했습니다).
  - `/api/stream`은 라우트에서 `bus.subscribe()`를 호출하고(`StreamLimitError` → 503), `StreamingResponse(board_stream(...))`를 돌려줍니다. 클라이언트가 끊기면 Starlette가 생성기를 취소하므로 `finally`에서 구독이 풀립니다.

- [ ] **Step 4: 통과 확인** — Run: `uv run pytest -q` → 전체 통과

- [ ] **Step 5: Commit** — `git commit -m "feat: add shared MCP board, settings, manual action and SSE stream API"`

---

### Task 13: Local 전용 MCP·스크립트·소유권 API

**Files:**
- Create: `server/app/web/mcp_local.py`, `server/tests/test_mcp_local_api.py`
- Modify: `server/app/web/app_factory.py` (`mcp_local.router`는 local에만 등록. External에서는 405를 404 `not_found`로 바꿉니다)

**Interfaces:**
- Consumes: `require(action, owner_id=...)`, `ScriptStore`, `McpStore`, `Monitor`, `UserStore`, `AuditLogger.admin`, Task 12의 detail 직렬화(`mcp_shared.mcp_detail(services, mcp) -> dict`)
- Produces (local 전용 HTTP):
  - `mcp_owner(request) -> int | None`: `require`의 owner_id 콜백입니다. `int(path_params["mcp_id"])`가 실패하거나 1–2**63-1 범위를 벗어나면 `ValueError`(→ 422), MCP가 없으면 `ApiError(404, "not_found")`, 있으면 `mcps.effective_owner_id(mcp)`를 돌려줍니다.
  - `POST /api/mcps` (CREATE_MCP) 본문 = McpConfig 필드 + `scripts: {start?, stop?, restart?: {ext: ".ps1"|".bat"|".cmd", content: str(max_length=65_536)}}`(모델 `extra="forbid"`)
    - 성공: 201 detail, 소유자 = 요청자. `monitor.add`, audit `mcp_create` `{mcp_id, name, host, port}`
    - start·stop이 빠지면 422 `scripts_required`, 스크립트 검증 실패는 `{"error": exc.code}`(422), 중복은 409 `name_taken`/`endpoint_taken`
  - `DELETE /api/mcps/{mcp_id}` (DELETE_MCP, owner=`mcp_owner`) → 204. 실행 중이면 409 `action_in_progress`. 순서는 `monitor.remove` → `mcps.delete` → `scripts.remove_dir`. stop 스크립트는 실행하지 않습니다. audit `mcp_delete`.
  - `POST /api/mcps/{mcp_id}/owner` (TRANSFER_OWNERSHIP) `{user_id: int}` → 200 detail. 대상이 없거나 비활성이면 422 `invalid_owner`. audit `mcp_owner_transfer` `{mcp_id, from, to}`.
  - `GET /api/mcps/{mcp_id}/scripts` (VIEW_SCRIPTS) → `[{kind, ext, version, sha256, updated_at, updated_by}]`
  - `GET /api/mcps/{mcp_id}/scripts/{kind}` (VIEW_SCRIPTS) → `{kind, ext, version, sha256, content, editable}`. `editable = can(user, EDIT_SCRIPTS, channel, effective owner)`. 스크립트가 없으면 404.
  - `PUT /api/mcps/{mcp_id}/scripts/{kind}` (EDIT_SCRIPTS, owner=`mcp_owner`) `{ext, content}` → 200 `{kind, ext, version, sha256}`. audit `script_update` `{mcp_id, kind, version, sha256}`.
  - `DELETE /api/mcps/{mcp_id}/scripts/{kind}` (EDIT_SCRIPTS) → 204. start/stop이면 409 `script_required`, 없으면 404. audit `script_delete`.
  - `GET /api/mcps/{mcp_id}/scripts/{kind}/versions` (VIEW_SCRIPTS) → `[{version, ext, sha256, author_id, created_at, deleted}]`. `GET .../versions/{version}`은 여기에 `content`를 더합니다.
  - `POST /api/mcps/{mcp_id}/scripts/{kind}/versions/{version}/revert` (EDIT_SCRIPTS) → 200 `{kind, ext, version, sha256}`. audit `script_revert` `{mcp_id, kind, from_version, version}`.
  - `kind` 경로 파라미터는 `Literal["start", "stop", "restart"]`(그 밖은 422)입니다. 실패한 변경은 모두 `result="error"`로 audit합니다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_mcp_local_api.py
import pytest
from tests.mcp_helpers import login_as, make_user, seed_mcp
from tests.test_auth_api import audit_events

SCRIPTS = {"start": {"ext": ".bat", "content": "exit /b 0"}, "stop": {"ext": ".bat", "content": "exit /b 0"}}
BODY = {"name": "calc", "host": "127.0.0.1", "port": 9102, "scripts": SCRIPTS}

async def as_user(client, services, email, role="developer", channel="local"):
    u = make_user(services, email, role); return u, {"X-CSRF-Token": login_as(client, services, u, channel)}

async def test_create_owner_is_creator(local_client, services):
    dev, h = await as_user(local_client, services, "dev@x.com")
    r = await local_client.post("/api/mcps", json=BODY, headers=h)
    assert r.status_code == 201 and r.json()["owner"]["id"] == dev.id
    mid = r.json()["id"]
    assert (services.paths.scripts_dir / str(mid) / "start.bat").exists() and services.monitor.engine(mid) is not None
    assert (await audit_events(services, "admin.audit"))[-1]["action"] == "mcp_create"

async def test_create_requires_both_scripts(local_client, services):
    _, h = await as_user(local_client, services, "dev@x.com")
    r = await local_client.post("/api/mcps", json={**BODY, "scripts": {"start": SCRIPTS["start"]}}, headers=h)
    assert r.status_code == 422 and r.json() == {"error": "scripts_required"} and services.mcps.list() == []
    big = {**SCRIPTS, "start": {"ext": ".ps1", "content": "가" * 30_000}}
    assert (await local_client.post("/api/mcps", json={**BODY, "scripts": big}, headers=h)).json() == {"error": "script_too_large"}

async def test_local_methods_404_on_external(external_client, services):
    dev, h = await as_user(external_client, services, "dev@x.com", channel="external"); m = seed_mcp(services, dev)
    for method, path in (("POST", "/api/mcps"), ("DELETE", f"/api/mcps/{m.id}"), ("PUT", f"/api/mcps/{m.id}/scripts/start"),
                         ("GET", f"/api/mcps/{m.id}/scripts/start"), ("POST", f"/api/mcps/{m.id}/owner")):
        r = await external_client.request(method, path, json={}, headers=h)
        assert r.status_code == 404 and r.json() == {"error": "not_found"}, (method, path)

async def test_script_edit_owner_only(local_client, services):
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner)
    for email, role in (("b@x.com", "developer"), ("adm@x.com", "admin")):
        _, h = await as_user(local_client, services, email, role)
        assert (await local_client.put(f"/api/mcps/{m.id}/scripts/start", json={"ext": ".bat", "content": "exit /b 1"}, headers=h)).json() == {"error": "forbidden"}
        g = (await local_client.get(f"/api/mcps/{m.id}/scripts/start")).json()
        assert g["editable"] is False and g["content"] == "exit /b 0\r\n"

async def test_script_versions_revert_delete(local_client, services):
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner); h = {"X-CSRF-Token": login_as(local_client, services, owner, "local")}
    r = await local_client.put(f"/api/mcps/{m.id}/scripts/start", json={"ext": ".ps1", "content": "exit 0"}, headers=h)
    assert r.json()["version"] == 2
    vs = (await local_client.get(f"/api/mcps/{m.id}/scripts/start/versions")).json()
    assert [v["version"] for v in vs] == [2, 1]
    assert (await local_client.get(f"/api/mcps/{m.id}/scripts/start/versions/1")).json()["content"] == "exit /b 0\r\n"
    r = await local_client.post(f"/api/mcps/{m.id}/scripts/start/versions/1/revert", headers=h)
    assert (r.json()["version"], r.json()["ext"]) == (3, ".bat")
    assert (await local_client.delete(f"/api/mcps/{m.id}/scripts/start", headers=h)).json() == {"error": "script_required"}
    assert (await local_client.delete(f"/api/mcps/{m.id}/scripts/restart", headers=h)).status_code == 404
    acts = [e["action"] for e in await audit_events(services, "admin.audit")]
    assert "script_update" in acts and "script_revert" in acts

async def test_owner_transfer(local_client, services):
    a = make_user(services, "a@x.com"); b = make_user(services, "b@x.com"); m = seed_mcp(services, a)
    _, hd = await as_user(local_client, services, "d@x.com")
    assert (await local_client.post(f"/api/mcps/{m.id}/owner", json={"user_id": b.id}, headers=hd)).json() == {"error": "forbidden"}
    _, h = await as_user(local_client, services, "adm@x.com", "admin")
    assert (await local_client.post(f"/api/mcps/{m.id}/owner", json={"user_id": 9999}, headers=h)).json() == {"error": "invalid_owner"}
    r = await local_client.post(f"/api/mcps/{m.id}/owner", json={"user_id": b.id}, headers=h)
    assert r.status_code == 200 and r.json()["owner"]["id"] == b.id
    hb = {"X-CSRF-Token": login_as(local_client, services, b, "local")}
    assert (await local_client.put(f"/api/mcps/{m.id}/scripts/stop", json={"ext": ".bat", "content": "exit /b 0"}, headers=hb)).status_code == 200

async def test_inactive_owner_shows_no_owner(local_client, services):
    a = make_user(services, "a@x.com"); m = seed_mcp(services, a); _, h = await as_user(local_client, services, "adm@x.com", "admin")
    services.users.set_active(a.id, False)
    assert (await local_client.get(f"/api/mcps/{m.id}")).json()["owner"] is None
    assert (await local_client.put(f"/api/mcps/{m.id}/scripts/start", json={"ext": ".bat", "content": "x"}, headers=h)).json() == {"error": "forbidden"}

async def test_delete_mcp(local_client, services):
    a = make_user(services, "a@x.com"); m = seed_mcp(services, a)
    _, hb = await as_user(local_client, services, "b@x.com")
    assert (await local_client.delete(f"/api/mcps/{m.id}", headers=hb)).json() == {"error": "forbidden"}
    assert (await local_client.delete("/api/mcps/999", headers=hb)).json() == {"error": "not_found"}
    assert (await local_client.put("/api/mcps/abc/scripts/start", json={}, headers=hb)).json() == {"error": "validation"}
    assert (await local_client.delete(f"/api/mcps/{2**70}", headers=hb)).status_code == 422
    ha = {"X-CSRF-Token": login_as(local_client, services, a, "local")}
    assert (await local_client.delete(f"/api/mcps/{m.id}", headers=ha)).status_code == 204
    assert services.mcps.get(m.id) is None and not (services.paths.scripts_dir / str(m.id)).exists()
    assert services.monitor.board() == []
```

- [ ] **Step 2: 실패 확인** — Run: `uv run pytest tests/test_mcp_local_api.py -v` → FAIL

- [ ] **Step 3: 구현**
  - 위 Interfaces대로 작성합니다. `test_local_routes_absent_on_external`(Plan 1)이 `mcp_local.router`도 검사하도록, 비교 대상에 `mcp_local.router.routes`를 추가합니다.
  - 405 → 404 변환은 `_http_exception_handler`에서 `request.app.state.channel == "external" and exc.status_code == 405`일 때 합니다.

- [ ] **Step 4: 통과 확인** — Run: `uv run pytest -q` → 전체 통과

- [ ] **Step 5: Commit** — `git commit -m "feat: add local-only MCP registration, script and ownership API"`

---

### Task 14: 통합 시나리오, 정적 점검, 문서 정리

**Files:**
- Create: `server/tests/test_integration_monitor.py`
- Modify: `server/pyproject.toml` (marker, addopts, ruff·mypy 설정), `server/uv.lock`, `docs/PLAN.md`, `docs/superpowers/plans/carry-forward.md`

**Interfaces:**
- Consumes: 전체. `build_services`(기본 `ScriptRunner`·`Prober`, `SystemClock`), `dummy-mcps/examples/*.ps1`, `tests.test_auth_api.bootstrap/login`, `tests.live.free_port`

- [ ] **Step 1: pytest 설정**

`[tool.pytest.ini_options]`에 `markers = ["integration: real subprocess scenario (Windows, needs dummy-mcps/.venv)"]`, `addopts = "-m 'not integration'"`을 추가합니다. 명령줄의 `-m integration`이 addopts를 덮어씁니다.

- [ ] **Step 2: 통합 테스트 작성**

```python
# server/tests/test_integration_monitor.py
import asyncio, sys, time, httpx, psutil, pytest, pytest_asyncio
from datetime import datetime
from pathlib import Path
from app.services import build_services
from app.web.app_factory import create_app
from tests.fakes import CapturingOtpProvider
from tests.live import free_port
from tests.test_auth_api import bootstrap, login

pytestmark = [pytest.mark.integration, pytest.mark.skipif(sys.platform != "win32", reason="Windows only")]
DUMMY = Path(__file__).resolve().parents[2] / "dummy-mcps"
SCRIPTS = {k: {"ext": ".ps1", "content": (DUMMY / "examples" / f"{k}.ps1").read_text("utf-8-sig")} for k in ("start", "stop", "restart")}
TIMING = {"expected_process_name": "python.exe", "action_delay_sec": 1, "startup_grace_sec": 1,
          "max_auto_actions": 2, "window_sec": 600, "script_timeout_sec": 30}

@pytest_asyncio.fixture
async def live(tmp_path, monkeypatch):
    assert (DUMMY / ".venv" / "Scripts" / "python.exe").exists(), "run `uv sync` in dummy-mcps first"
    run_dir = tmp_path / "run"
    monkeypatch.setenv("DUMMY_MCPS_DIR", str(DUMMY)); monkeypatch.setenv("DUMMY_MCP_RUN_DIR", str(run_dir)); monkeypatch.setenv("DUMMY_MCP_CHAOS", "1")
    svc = build_services(tmp_path / "root", otp_provider=CapturingOtpProvider())
    svc.settings.update({"ping_interval_sec": 1, "issue_check_interval_sec": 5, "confirm_interval_sec": 1})
    await svc.log.start(); await svc.monitor.start()
    transport = httpx.ASGITransport(app=create_app("local", svc))
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8700") as c:
            yield svc, c
    finally:
        await svc.monitor.stop(); await svc.log.stop(); svc.db.close()
        for pid_file in run_dir.glob("*.pid"):
            try: psutil.Process(int(pid_file.read_text())).kill()
            except (psutil.Error, ValueError): pass

async def board_item(c, mcp_id):
    return next(i for i in (await c.get("/api/board")).json()["mcps"] if i["id"] == mcp_id)

async def wait_state(c, mcp_id, states, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        item = await board_item(c, mcp_id)
        if item["state"] in states: return item
        await asyncio.sleep(0.2)
    pytest.fail(f"mcp {mcp_id} not in {states}: {item}")

async def chaos(port, path):
    async with httpx.AsyncClient() as h:
        try: await h.post(f"http://127.0.0.1:{port}{path}", timeout=2)
        except httpx.HTTPError: pass

async def test_crash_hang_and_failed(live):
    svc, c = live
    await bootstrap(c); await login(c, svc); h = {"X-CSRF-Token": c.csrf}
    ports, ids = {"calculator": free_port(), "seoul-clock": free_port()}, {}
    for name, port in ports.items():
        r = await c.post("/api/mcps", json={"name": name, "host": "127.0.0.1", "port": port, **TIMING, "scripts": SCRIPTS}, headers=h)
        assert r.status_code == 201; ids[name] = r.json()["id"]
        assert (await c.post(f"/api/mcps/{ids[name]}/actions/start", headers=h)).status_code == 202
    for i in ids.values(): await wait_state(c, i, {"HEALTHY"}, 30)
    calc, other = ids["calculator"], ids["seoul-clock"]

    samples = []
    async def sample():
        while True:
            t = time.perf_counter(); item = await board_item(c, other); dt = time.perf_counter() - t
            age = time.time() - datetime.fromisoformat(item["last_check_at"]).timestamp()
            samples.append((dt, age, item["state"])); await asyncio.sleep(0.2)
    sampler = asyncio.create_task(sample())
    try:
        await chaos(ports["calculator"], "/chaos/crash")                       # 1) crash → 자동 start
        await wait_state(c, calc, {"SUSPECT", "ACTION"}, 10); await wait_state(c, calc, {"HEALTHY"}, 30)
        a = svc.history.actions(calc)[0]
        assert (a.kind, a.trigger, a.reason, a.result.status) == ("start", "auto", "PROCESS_DOWN", "ok")

        await chaos(ports["calculator"], "/chaos/hang?sec=120")                # 2) hang → 자동 restart
        await wait_state(c, calc, {"SUSPECT", "ACTION"}, 15); await wait_state(c, calc, {"HEALTHY"}, 40)
        a = svc.history.actions(calc)[0]
        assert (a.kind, a.trigger, a.reason, a.result.status) == ("restart", "auto", "UNRESPONSIVE", "ok")

        await chaos(ports["calculator"], "/chaos/crash")                       # 3) 한도 소진 → stop + FAILED
        await wait_state(c, calc, {"FAILED"}, 20)
        await svc.monitor.wait_idle()
        a = svc.history.actions(calc)[0]
        assert (a.kind, a.trigger) == ("stop", "auto")
    finally:
        sampler.cancel()
    assert samples and max(s[0] for s in samples) < 0.5                         # API 응답 유지
    assert max(s[1] for s in samples) < 3.5                                     # 다른 MCP ping 계속 흐름
    assert {s[2] for s in samples} == {"HEALTHY"}
```

- [ ] **Step 3: 통합 테스트 실행**

Run (dummy-mcps): `uv sync`
Run (server): `uv run pytest -m integration -v` → 1 passed, 60초 이내. 실패하면 상태 전이 로그(`logs/*.jsonl`의 `mcp.health`·`mcp.action`)로 원인을 찾아 해당 Task 코드를 고칩니다. 타이밍 값을 늘려서 통과시키지 않습니다.

- [ ] **Step 4: ruff·mypy 한 번 실행 (carry-forward)**

dev 의존성 `ruff`, `mypy`, `types-psutil`을 추가합니다. `[tool.ruff] line-length = 100`, `[tool.mypy] python_version = "3.15"`, `packages = ["app"]`, `ignore_missing_imports = true`.
Run: `uv run ruff check app tests` → 0건이 될 때까지 고칩니다.
Run: `uv run mypy` → 오류를 고칩니다. 설계 변경이 필요한 오류만 오류 원문과 함께 carry-forward(Plan 3 절)에 적습니다.

- [ ] **Step 5: 문서 정리**

- `docs/PLAN.md`: 변경 이력에 `v0.4.1 | 구현 정합: §4.4 can 시그니처, §8 사용자 PATCH, §8 스크립트 GET 읽기 규칙` 행을 추가합니다.
  - §4.4 `can(user, action, resource, channel)` → `can(user, action, channel, owner_id)`
  - §8 `GET/POST/PUT /api/users` → `GET/POST /api/users`, `PATCH /api/users/{id}`
  - §8 스크립트 행을 두 줄로 나눕니다. `GET /api/mcps/{id}/scripts…`는 Local, MCP 개발자 이상 읽기 전용(§6.4)이고, `PUT/DELETE`는 Local, 소유자만입니다.
- `carry-forward.md`: Plan 2 항목 8개에 체크하고 각 줄 끝에 `(Plan 2 Task N)`을 적습니다. 다음 항목을 추가합니다.
  - Plan 3:
    - 보드는 `GET /api/board`와 SSE 이벤트 `board`/`mcp`/`mcp_removed`/`action`을 씁니다.
    - 수동 조치는 202 + `run_id`이고, 토스트는 `action` 이벤트로 띄웁니다.
    - 스크립트 diff는 versions API 내용으로 클라이언트에서 계산합니다.
    - 익명 보드에는 host:port가 없습니다.
  - Plan 4: `/api/board`와 SSE에 `sessions`를 추가합니다.
  - Plan 5:
    - `scripts/` ACL(SYSTEM + Administrators)
    - `mcp_actions`·`mcp_transitions` 보존 정리
    - 서비스 시작 유형 적용
  - 추후: `Alert`는 현재 `mcp.health` 로그만 남깁니다. 알림 채널(§14)이 필요합니다.

- [ ] **Step 6: 전체 검증**

Run (server): `uv run pytest -q` → 전체 통과. `uv run pytest -m integration -q` → 통과. `uv run pip-audit` → 0건
Run (dummy-mcps): `uv run pytest -q` → 전체 통과. `uv run pip-audit` → 0건

- [ ] **Step 7: Commit** — `git commit -m "test: add live crash/hang/failed monitor scenario; lint, types and spec alignment"`
