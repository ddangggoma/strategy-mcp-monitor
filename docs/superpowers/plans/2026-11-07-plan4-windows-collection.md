# Plan 4 — Windows 세션·행동 수집 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 사용자 지시에 따라 과제마다 리뷰하지 않고, 마지막에 계획 전체 리뷰 한 번 + 수정 한 번만 합니다.

**Goal:** spec P4(세션 수집)와 P5(행동 로그 + 고지)를 구현합니다. RDP 세션 수집기(WTS + 이벤트 로그, §5.3), 세션 이력과 상태 보드 실시간 표시(§6.2), 프로세스·명령 수집(WMI·4688·4104, §5.4), 세션 에이전트(창 이벤트·유휴, 고지 창, §3·§5.5), 연결마다 고지 **표시**와 확인 기록(편집기·저장소는 Plan 3), 에이전트 재기동 감시와 우회 탐지(§2 #4)입니다. 로그 조회 화면·보존 정리·패키징·서비스 호스트·설치 스크립트는 Plan 5입니다.

**Architecture:** Windows API는 `server/app/win/`의 어댑터 뒤에만 있습니다. WTS·세션 ID·TCP 피어는 ctypes, 이벤트 로그(`EvtSubscribe`)·WMI(COM)·`CreateProcessAsUser`는 pywin32입니다. 수집은 전용 스레드에서 돌고, 결과는 `CollectorBridge`(묶음 전달, 상한 있음)로 asyncio 루프에 넘어가며, 루프 쪽 핸들러만 DB·`LogWriter`·`BoardBus`를 만집니다. `SessionTracker`가 WTS 스냅숏의 차이로 연결(로그온/재연결/기존)을 열고 닫아 `rdp_connections`에 남기고, 보드 `sessions`와 SSE `sessions` 이벤트를 만듭니다. 연결이 열리면 `NoticeDisplays`가 고지 표시 건을 만들고, `AgentSupervisor`가 그 세션에 에이전트를 띄웁니다(서비스면 `CreateProcessAsUser`, 개발 PC면 자기 세션에서 `Popen`). 에이전트(`agent/`, 표준 라이브러리 + ctypes만)는 Local 채널(127.0.0.1:8700)에 **HTTP**로 붙고(`X-Agent-Token` + TCP 피어 → PID → 세션 ID 검증), 명령을 long-poll로 받아 Edge `--app` 창으로 `/notice#d=<id>&t=<토큰>`을 엽니다. 고지 페이지가 토큰으로 내용을 받고(`notice_shown`) 확인을 보냅니다(`notice_acknowledged`). 에이전트가 죽으면 감독자가 기록(`tamper`)하고 백오프로 다시 띄우며, 확인 전이던 고지를 다시 보여 줍니다. 창 이벤트·유휴는 에이전트가 묶어 보냅니다. 웹은 notice 번들의 표시 모드, 세션 카드 보강, 세션 화면, 대시보드 우회 탐지 카드를 더합니다.

**Tech Stack:** 서버: Python 3.15, FastAPI, uv, pytest, psutil(기존), **pywin32 312**(신규, V2), ctypes(wtsapi32·kernel32·user32). 에이전트: Python 3.15 표준 라이브러리 + ctypes(의존성 없음, V5), Microsoft Edge(Windows 11 기본 설치) `--app` 창(V3). 웹: Plan 3 스택 그대로(신규 의존성 없음).

**Spec:** `docs/PLAN.md` (v0.5; Plan 3 끝에 v0.6). 이 계획은 §5.3(세션 수집기), §5.4(행동 로그), §5.5(고지 **표시**·기록), §3(에이전트·세션 ID 검증), §5.9(세션 에이전트 기동), §6.2(보드 접속자 카드), §6.4 #1(대시보드 현재 세션·우회 탐지)·#3(세션 화면), §7(이벤트 수집·창 이벤트 성능), §8(`GET /api/sessions/history`), §13(에이전트 사칭 차단·Win 11 Pro 실기기), §15, §11 P4·P5 완료 기준을 구현합니다. carry-forward의 "Plan 4" 절 5개 항목과 Plan 3이 넘긴 계약(`RdpSession`, `loadNoticeContent()`·`notifyHost()` 교체, `notice_shown` 문구 버전, 대시보드 현재 세션)을 모두 아래 과제에 배정했습니다(Task 20에서 체크). 이미 내려진 결정은 `2026-11-04-plan1-rulings.md`, `2026-11-05-plan2-rulings.md`, Plan 3 부록 A(U1–U32)와 Plan 3 ledger의 F18(`/notice`는 Local 채널에서만 제공)입니다. 이 계획의 결정(V1–V33)은 **부록 A**, 서버 API·SSE와 클라이언트 대응은 **부록 B**에 있습니다. 본문의 `V<n>`은 부록 A의 행입니다.

**carry-forward 배정:**
| 항목 | 과제 |
|---|---|
| `LogWriter.emit()`은 루프 스레드 전용 → 수집 스레드는 `call_soon_threadsafe` | Task 1 (`emit_threadsafe`, `CollectorBridge`), 이후 모든 수집기 |
| 이벤트 시각 `ts` 덮어쓰기 | Task 1 (`emit(at=)`), Task 7–10·12·14가 사용 |
| 두 번째 프로세스의 `config.db` 경합 | V5: 에이전트는 HTTP만 쓰고 DB를 열지 않음(Task 15 테스트), 북마크는 JSON 파일(Task 7) |
| localhost 로그인의 Windows 계정 기록(§4.1.5) | Task 2 |
| `GET /api/board`·SSE에 `sessions` | Task 5 |
| (Plan 3) `RdpSession` 키를 그대로 채움 | Task 4·5 (서버), Task 17 (웹 타입 확장) |
| (Plan 3) notice 번들 `loadNoticeContent()`·`notifyHost()` 교체 | Task 17 |
| (Plan 3) `notice_shown`의 문구 버전 = `NoticeStore.current().version` | Task 11 |
| (Plan 3) 대시보드 "현재 세션" 카드가 같은 데이터 사용 | Task 18 |

## Global Constraints

- 브랜치 `feat/plan4-windows-collection`을 **Plan 3이 끝난 커밋**(전체 리뷰 수정까지)에서 만듭니다. Plan 3이 이 문서가 인용한 이름과 다르게 구현됐으면 실제 코드를 따르고 보고서에 적습니다(V1).
- 서버 명령은 `server/`에서 `uv run python -m pytest ...`, `uv run python -m app ...`처럼 **`python -m` 형태로만** 부릅니다(앱 제어 정책이 `.venv\Scripts\*.exe` 콘솔 런처를 막습니다). 에이전트는 `agent/`에서 `uv run python -m pytest ...`. uv가 PATH에 없으면 `C:\Users\ddang\AppData\Local\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\uv.exe`(E2E는 환경변수 `UV_EXE`). 웹은 `web/`에서 `pnpm <script>`(Git Bash면 먼저 `export PATH="/c/nvm4w/nodejs:$PATH"`).
- 개발 PC는 **Windows 11 Home, 관리자 아님**입니다(2026-11-05 확인): Security 로그 `EvtQuery` → 액세스 거부(5), `PowerShellCore/Operational` 채널 없음(15007), `Win32_ProcessStartTrace` → 액세스 거부(0x80041003), `__InstanceCreationEvent WITHIN 1`은 동작(CommandLine·SessionId 포함), LSM·RCM·PowerShell/Operational·System 읽기 가능, WTS 세션은 `Services`(0)·`Console`(1)뿐. 테스트를 관리자 권한으로 돌리지 않고, 이 PC의 감사 정책·레지스트리·보안 설정을 바꾸지 않습니다. RDP·Security·`CreateProcessAsUser`는 가짜·녹화 픽스처로 자동 테스트하고, 실기기 확인은 Task 20 점검표에 "대기"로 남깁니다.
- pytest 마커: `integration`(실제 하위 프로세스), `winlive`(관리자 없이 이 PC의 실제 Windows API를 부르는 어댑터 확인, 신규). 둘 다 기본 실행에서 빠지고(`addopts = "-m 'not integration and not winlive'"`), 각 과제의 Run 단계가 명시적으로 실행합니다. winlive 테스트가 권한 부족으로 실패하면 고치지 말고 `pytest.skip("<이유>")`로 바꾸지도 말고 멈춰서 보고합니다.
- 의존성: 서버에 `pywin32==312`(`sys_platform == 'win32'`)만 더합니다(V2: PyPI에 cp315 `win_amd64` 휠 있음, 3.15.2에서 `win32evtlog`·`win32com.client`·`win32ts`·`win32process`·`win32profile`·`win32security` import 확인). 에이전트는 런타임 의존성 0개, dev는 `pytest`·`pytest-timeout`. 웹은 신규 의존성 없음. 그 밖은 Ruling 없이 추가하지 않습니다.
- 스레드 규칙: Windows API의 블로킹 호출은 수집 스레드나 `asyncio.to_thread`에서만 부릅니다. 수집 스레드는 `LogWriter.emit`·`Database`·`BoardBus`·`SessionTracker`를 직접 부르지 않고 `CollectorBridge`의 `post`(또는 `LogWriter.emit_threadsafe`)만 씁니다. `db.transaction()` 안에서 `await`·중첩 금지(Plan 2 그대로).
- Windows 이벤트에서 온 로그 줄의 `ts`는 **이벤트 시각**입니다(`emit(..., at=<이벤트 시각>)`). 수신 시각을 쓰는 것은 WTS 스냅숏(스냅숏 시각)과 에이전트 시계가 ±300초를 넘게 틀린 경우(V28)뿐입니다.
- 오류 본문 `{"error": "<code>"}`. **새 오류 코드 없음**: 에이전트·고지 표시 라우트는 `login_required`(401)·`forbidden`(403)·`not_found`(404)·`validation`(422)만 씁니다.
- 에이전트 API(`/api/agent/*`)와 고지 표시 API(`/api/notice/display/*`)는 **Local 앱에만** 등록합니다. `tests/test_channels.py::_local_only_routes`에 두 라우터를 더합니다(외부 채널 404).
- 로그 카테고리와 `event` 이름은 아래로 고정합니다(테스트가 씁니다). 세션 맥락 필드는 `session_id`, `user`(`DOMAIN\name`, 도메인이 없으면 이름만), `client_ip`, `client_name`입니다.
  - `session`: `connect`(`kind` = `logon`/`reconnect`/`existing`), `disconnect`, `logoff`, `lock`, `unlock`(WTS, `source: "wts"`), 이벤트 로그 유래는 `lsm_logon`·`lsm_shell_start`·`lsm_logoff`·`lsm_disconnect`·`lsm_reconnect`·`rdp_auth_ok`·`logon`·`logon_failed`·`logoff`·`user_logoff`·`session_reconnect`·`session_disconnect`·`lock`·`unlock`(`source: "eventlog:<id>"`), `agent_stopped`(로그오프로 에이전트가 끝남).
  - `notice`: `notice_shown`, `notice_acknowledged`, `notice_unacknowledged`(`reason` = `agent_exited`/`window_closed`/`superseded`/`logoff`/`service_restart`).
  - `activity.process`: `start`, `stop`. `activity.command`: `process_cmdline`(4688), `script_block`(4104). `activity.window`: `foreground`, `minimize`, `restore`, `title`. `activity.idle`: `idle`, `active`.
  - `tamper`: `agent_exited`, `agent_unresponsive`, `agent_restart_storm`, `agent_impersonation`, `notice_token_misuse`, `script_hash_mismatch`, `script_file_changed`, `script_file_missing`, `log_file_removed`, `log_file_truncated`, `audit_policy_changed`, `log_cleared`, `audit_config_changed`.
  - `system`: `collector.status`, `collector.mode`, `collector.dropped`, `collector.handler_failed`, `sessions.wts_failed`, `agent.launched`, `agent.launch_failed`, `audit.config`.
- 수집하지 않는 것(spec §2 #7, §14): cmd 내부 명령, 키 입력, 클립보드, 화면. 창 제목·명령줄은 원문 그대로 기록합니다(§15 위험은 보존 기간과 조회 권한으로 다룹니다, Plan 5).
- DB 시각 형식은 Plan 2 그대로(UTC aware `isoformat()`), API 응답 시각은 `to_kst_iso`.
- 웹 규칙은 Plan 3 Global Constraints 그대로입니다: 문구는 `web/src/copy/ko.ts`에만, `aria-disabled` + 이유, reduced-motion, 표에는 애니메이션 없음, 보드 < 200KB·notice < 100KB(gzip), 외부 채널에서 Local 전용 API를 부르지 않음, MSW 픽스처는 `api-types.ts` 타입을 따름.
- 테스트 본문은 모두 실제 단언입니다(주석만 있는 테스트 금지, Plan 3 ruling F10).

## Review Focus

1. **재연결마다 고지가 다시 뜨고 확인이 기록되는가**(연결 해제 후 재연결, 확인 전 연결 해제, 해제를 놓친 빠른 재연결, 서비스 재시작 중 접속): 새 연결마다 표시 건이 하나 생기고 이전 미확인 건은 `superseded`로 닫혀야 하며, 확인까지 걸린 시간이 남아야 합니다. → Task 4 `test_fast_reconnect_detected_by_connect_time`, Task 11 `test_reconnect_supersedes_pending_display`, `test_open_and_ack_flow_logs_and_marks_board`, Task 19 `test_reconnect_reshows_notice`(integration), E2E `reconnect shows the notice again`
2. **에이전트가 죽으면 재기동되고 그 사실이 기록되는가**(사용자가 작업 관리자로 종료, 응답 없음, 계속 죽음, 로그오프로 인한 정상 종료): 로그오프는 우회로 기록하지 않고, 우리가 죽인 경우는 `agent_exited`가 아니며, 확인 전이던 고지는 재기동 뒤 다시 떠야 합니다. → Task 13 `test_agent_exit_logs_tamper_and_relaunches_with_backoff`, `test_exit_after_logoff_is_not_tamper`, `test_hello_timeout_kills_once_and_reports_unresponsive`, `test_restart_storm_reported_once_per_window`, `test_pending_notice_reshown_after_restart`, Task 19 `test_killing_the_agent_relaunches_it_and_reshows_pending_notice`
3. **에이전트·고지 사칭 차단**(다른 세션에서 훔친 토큰, 브라우저 페이지의 교차 출처 요청, 외부 채널, 토큰 없는 요청): 세션 검증은 요청의 TCP 피어에서 서버가 직접 구해야 하고 본문의 주장은 믿지 않아야 합니다. → Task 12 `test_token_used_from_another_session_is_rejected_and_reported`, `test_hello_with_wrong_session_id_is_403`, `test_agent_routes_absent_on_external`, Task 11 `test_display_api_other_session_404`, `test_cross_site_fetch_is_refused`
4. **스레드 경계와 이벤트 시각**(수집 스레드에서 오는 대량 이벤트, 자정 직전 이벤트, 루프가 바쁠 때): 루프 밖에서 `LogWriter`·DB를 건드리지 않고, 넘칠 때는 오래된 것부터 버리며 그 수를 기록하고, 줄은 이벤트 날짜 파일에 들어가야 합니다. → Task 1 `test_emit_at_overrides_timestamp_and_day`, `test_emit_threadsafe_from_worker_thread`, `test_overflow_drops_oldest_and_logs_once`, Task 7 `test_watcher_posts_records_and_saves_bookmark`, Task 8 `test_session_events_use_event_time`
5. **세션 차이 계산의 정확성과 2초 기준**(세션 ID 재사용, WTS 일시 실패, 콘솔 세션 제외, 유휴 시간 때문에 SSE가 매초 흐르는 일): → Task 4 `test_session_id_reuse_is_a_new_logon`, `test_wts_failure_logged_once_per_minute_and_state_kept`, `test_publishes_sessions_only_on_visible_change`, E2E `board shows 접속 중 within 2 s of an RDP connection and clears on logoff`
6. **익명 보드의 공개 범위**: 접속자 정보(IP 포함, §4.3)는 익명에게 보이지만 `tamper`·`action`·에이전트 내부 정보는 로그인한 MCP 개발자 이상에게만 가야 합니다. → Task 5 `test_anonymous_board_and_stream_carry_sessions`, Task 6 `test_report_logs_rings_and_publishes_to_authed_only`

---

### Task 1: 기반 — pywin32, 로그 이벤트 시각·스레드 경계, CollectorBridge, 테스트 마커

**Files:**
- Modify: `server/pyproject.toml`, `server/uv.lock`, `server/app/logstore/writer.py`
- Create: `server/app/collect/__init__.py`, `server/app/collect/bridge.py`, `server/app/win/__init__.py`
- Create: `server/tests/test_collect_bridge.py`, `server/tests/test_win_imports.py`, `server/tests/winfakes.py`
- Modify (tests): `server/tests/test_log_writer.py`

**Interfaces:**
- Produces:
  - `pyproject.toml`: `dependencies`에 `"pywin32==312; sys_platform == 'win32'"`(`uv add "pywin32==312 ; sys_platform == 'win32'"`). `[tool.pytest.ini_options]` `markers`에 `"winlive: real Windows API on this PC, no admin rights"`, `addopts = "-m 'not integration and not winlive'"`.
  - `app.logstore.writer.LogSink(Protocol)`: `def emit(self, cat: str, *, at: datetime | None = None, **fields: Any) -> None`.
  - `LogWriter.emit(cat: str, *, at: datetime | None = None, **fields: Any) -> None`: `ts = to_kst_iso(at if at is not None else self._clock.now())`. `fields`의 `ts` 키는 지금처럼 무시합니다.
  - `LogWriter.emit_threadsafe(cat: str, *, at: datetime | None = None, **fields: Any) -> None`: `start()`가 `asyncio.get_running_loop()`를 저장합니다. 호출 스레드가 그 루프의 스레드면 `emit`을 바로 부르고, 아니면 `loop.call_soon_threadsafe(functools.partial(self.emit, cat, at=at, **fields))`. `start()` 전 → `_warn("emit_threadsafe before start")`, 루프가 닫혔으면(`RuntimeError`) → `_warn("emit_threadsafe after loop closed")` 후 버립니다. 절대 예외를 던지지 않습니다.
  - `app.collect.bridge.CollectorBridge(loop: asyncio.AbstractEventLoop, log: LogSink, *, max_pending: int = 10_000)`:
    - `register(name: str, handler: Callable[[list[Any]], None]) -> Callable[[Any], None]`: 같은 이름 두 번 → `ValueError`. 돌려주는 `post(item)`은 어느 스레드에서나 부를 수 있습니다(내부 `threading.Lock`).
    - `post`: 그 이름의 `deque`에 넣고, 길이가 `max_pending`을 넘으면 가장 오래된 것을 버리고 `dropped[name] += 1`. 드레인이 예약돼 있지 않으면 `loop.call_soon_threadsafe(self._drain)`(루프가 닫혀 `RuntimeError`면 조용히 무시).
    - `_drain`(루프 스레드): 잠금 안에서 큐와 `dropped`를 통째로 바꿔 꺼낸 뒤 잠금 밖에서 등록 순서대로 `handler(items)`. 버린 수가 있으면 `log.emit("system", event="collector.dropped", source=name, count=n)`, 핸들러 예외는 `log.emit("system", event="collector.handler_failed", source=name, error=repr(exc))` 후 다음 핸들러로 계속.
  - `app.win.IS_WINDOWS: bool = sys.platform == "win32"`.
  - `tests/winfakes.py`: `ListLog`(`events: list[tuple[str, datetime | None, dict]]`, `emit(cat, *, at=None, **f)`), `async def eventually(pred: Callable[[], bool], timeout: float = 5.0, step: float = 0.01) -> None`(시간 안에 참이 안 되면 `AssertionError`). 이후 과제가 가짜를 이 파일에 더합니다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_log_writer.py (추가; 파일의 read(paths, day) 헬퍼 사용)
import asyncio
import threading
from datetime import UTC, datetime

async def test_emit_at_overrides_timestamp_and_day(paths, clock):
    lw = LogWriter(DailyJsonlWriter(paths.logs_dir), clock, flush_interval=60)
    await lw.start()
    lw.emit("session", at=datetime(2026, 11, 3, 14, 59, 59, 500000, tzinfo=UTC), event="connect")  # 11-03 23:59:59.500 KST
    lw.emit("session", ts="2000-01-01T00:00:00+09:00", event="x")  # a ts field is still ignored
    await lw.stop()
    assert read(paths, "2026-11-03")[0]["ts"] == "2026-11-03T23:59:59.500+09:00"
    assert read(paths, "2026-11-04")[0]["ts"] == "2026-11-04T14:00:00.000+09:00"

async def test_emit_threadsafe_from_worker_thread(paths, clock):
    lw = LogWriter(DailyJsonlWriter(paths.logs_dir), clock, flush_interval=60)
    await lw.start()
    t = threading.Thread(target=lambda: [lw.emit_threadsafe("activity.process", n=i) for i in range(50)])
    t.start(); t.join()
    await asyncio.sleep(0.01)  # let the scheduled callbacks run
    await lw.stop()
    assert [r["n"] for r in read(paths, "2026-11-04")] == list(range(50))

async def test_emit_threadsafe_on_loop_thread_keeps_order(paths, clock):
    lw = LogWriter(DailyJsonlWriter(paths.logs_dir), clock, flush_interval=60)
    await lw.start()
    lw.emit_threadsafe("system", n=1); lw.emit("system", n=2)
    await lw.stop()
    assert [r["n"] for r in read(paths, "2026-11-04")] == [1, 2]

def test_emit_threadsafe_before_start_is_dropped_with_warning(paths, clock, capsys):
    lw = LogWriter(DailyJsonlWriter(paths.logs_dir), clock)
    lw.emit_threadsafe("system", n=1)
    assert "emit_threadsafe before start" in capsys.readouterr().err
```

```python
# server/tests/test_collect_bridge.py
import asyncio
import threading

import pytest

from app.collect.bridge import CollectorBridge
from tests.winfakes import ListLog, eventually

async def test_items_from_threads_reach_the_handler_on_the_loop_in_order():
    loop = asyncio.get_running_loop(); seen: list[tuple[int, list[int]]] = []
    bridge = CollectorBridge(loop, ListLog())
    post = bridge.register("wts", lambda items: seen.append((threading.get_ident(), list(items))))
    t = threading.Thread(target=lambda: [post(i) for i in range(100)]); t.start(); t.join()
    await eventually(lambda: sum(len(b) for _, b in seen) == 100)
    assert [x for _, batch in seen for x in batch] == list(range(100))
    assert {tid for tid, _ in seen} == {threading.get_ident()}

async def test_overflow_drops_oldest_and_logs_once():
    loop = asyncio.get_running_loop(); got: list[int] = []; log = ListLog()
    bridge = CollectorBridge(loop, log, max_pending=3)
    post = bridge.register("wmi", got.extend)
    t = threading.Thread(target=lambda: [post(i) for i in range(10)])
    t.start(); t.join()  # blocks the loop: nothing drains until the thread is done
    await eventually(lambda: got == [7, 8, 9])
    assert [(c, f) for c, _, f in log.events] == [("system", {"event": "collector.dropped", "source": "wmi", "count": 7})]

async def test_handler_exception_is_logged_and_other_handlers_still_run():
    loop = asyncio.get_running_loop(); ok: list[int] = []; log = ListLog()
    bridge = CollectorBridge(loop, log)
    bad = bridge.register("bad", lambda items: 1 / 0)
    good = bridge.register("good", ok.extend)
    bad(1); good(2)
    await eventually(lambda: ok == [2])
    assert log.events[0][2]["event"] == "collector.handler_failed" and log.events[0][2]["source"] == "bad"
    bad(3); good(4)
    await eventually(lambda: ok == [2, 4])

def test_register_twice_is_an_error():
    loop = asyncio.new_event_loop()
    try:
        bridge = CollectorBridge(loop, ListLog()); bridge.register("x", print)
        with pytest.raises(ValueError):
            bridge.register("x", print)
    finally:
        loop.close()

def test_post_after_loop_closed_is_ignored():
    loop = asyncio.new_event_loop(); bridge = CollectorBridge(loop, ListLog())
    post = bridge.register("x", print); loop.close()
    post(1)  # must not raise
```

```python
# server/tests/test_win_imports.py
import pytest

pytestmark = pytest.mark.winlive

def test_pywin32_modules_import():
    import pythoncom  # noqa: F401
    import win32com.client  # noqa: F401
    import win32event  # noqa: F401
    import win32evtlog  # noqa: F401
    import win32process  # noqa: F401
    import win32profile  # noqa: F401
    import win32security  # noqa: F401
    import win32ts

    assert win32ts.WTS_CURRENT_SERVER_HANDLE == 0
```

- [ ] **Step 2: 실패 확인** — Run: `uv run python -m pytest tests/test_log_writer.py tests/test_collect_bridge.py -v` → FAIL(`emit_threadsafe`·`app.collect` 없음)

- [ ] **Step 3: 의존성 추가와 구현** — Run: `uv add "pywin32==312 ; sys_platform == 'win32'"` → `uv.lock` 갱신. Run: `uv run python -m pytest -m winlive tests/test_win_imports.py -v` → 1 passed(앱 제어가 pywin32 DLL을 막으면 멈추고 막힌 경로를 보고합니다; V2의 대안은 컨트롤러가 결정). 그다음 위 Interfaces대로 `writer.py`, `bridge.py`, `app/win/__init__.py`, `winfakes.py`, `pyproject.toml` 마커를 구현합니다.

- [ ] **Step 4: 통과 확인** — Run: `uv run python -m pytest -q` → 전체 통과. `uv run python -m pytest -m winlive -q` → 통과. `uv run python -m ruff check app tests`, `uv run python -m mypy` → 0건. `uv run python -m pip_audit` → 0건.

- [ ] **Step 5: Commit** — `git commit -m "feat: event-time log timestamps, thread-safe emit and collector bridge; add pywin32"`

---

### Task 2: Windows 피어 식별과 localhost 로그인의 Windows 계정 기록

**Files:**
- Create: `server/app/win/ffi.py`, `server/app/win/peer.py`, `server/tests/test_peer.py`
- Modify: `server/app/services.py` (`peers`), `server/app/web/deps.py` (`peer_of`, `windows_user_of`), `server/app/audit.py`, `server/app/web/shared_api.py`, `server/tests/winfakes.py` (`FakePeerResolver`)
- Modify (tests): `server/tests/test_auth_api.py`

**Interfaces:**
- Produces:
  - `app.win.ffi.process_session_id(pid: int) -> int | None`: `kernel32.ProcessIdToSessionId(DWORD pid, POINTER(DWORD))`, 실패(0 반환) → `None`. `current_session_id() -> int`(= `process_session_id(os.getpid())`, 실패면 `RuntimeError`). ctypes 선언은 `argtypes`/`restype`를 명시합니다(`use_last_error=True`).
  - `app.win.peer`:
    - `@dataclass(frozen=True) PeerInfo(pid: int, session_id: int | None, user: str | None, exe: str | None)` — `user`는 `DOMAIN\name`(psutil `Process.username()` 그대로).
    - `class PeerResolver(Protocol): def resolve(self, client_ip: str, client_port: int, server_port: int) -> PeerInfo | None`
    - `class PsutilPeerResolver`: `client_ip`가 loopback(`ipaddress.ip_address(...).is_loopback`)이 아니면 `None`. `psutil.net_connections("tcp")`에서 `laddr.port == client_port`이고 `raddr`가 있고 `raddr.port == server_port`이며 `laddr.ip`가 loopback인 연결의 `pid`를 찾습니다(없거나 `pid`가 None/0이면 `None`). `session_id = process_session_id(pid)`, `user`·`exe`는 `psutil.Process(pid)`에서 읽고 `AccessDenied`/`NoSuchProcess`면 `None`.
  - `Services.peers: PeerResolver`(`build_services(..., peer_resolver: PeerResolver | None = None)`, 기본 `PsutilPeerResolver()`).
  - `app.web.deps.peer_of(request: Request) -> Awaitable[PeerInfo | None]`(async): Local 채널이고 `request.client`가 있고 `request.scope["server"]`가 있을 때만 `await asyncio.to_thread(services.peers.resolve, client.host, client.port, server[1])`, 예외 → `None`. 외부 채널 → 항상 `None`.
  - `app.web.deps.windows_user_of(request) -> Awaitable[str | None]` = `(await peer_of(request)).user` 또는 `None`.
  - `AuditLogger.auth(..., ok: bool, windows_user: str | None = None)`와 `auth_rate_limited(..., windows_user: str | None = None)`: `channel == "local"`일 때만 줄에 `windows_user` 키를 넣습니다(값이 `None`이어도 키는 있음). 외부 채널 줄에는 키가 없습니다.
  - `shared_api`: `otp_request`, `otp_verify`(성공·실패·429), `logout`이 `windows_user=await windows_user_of(request)`를 넘깁니다.
  - `tests/winfakes.FakePeerResolver(info: PeerInfo | None)`: `resolve`가 인자와 관계없이 `info`를 돌려주고 `calls`에 인자를 남깁니다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_peer.py
import getpass
import os
import socket
import sys

import pytest

from app.win.ffi import current_session_id, process_session_id
from app.win.peer import PeerInfo, PsutilPeerResolver
from tests.test_auth_api import audit_events, bootstrap, login
from tests.winfakes import FakePeerResolver

windows = pytest.mark.skipif(sys.platform != "win32", reason="Windows API")

@windows
def test_process_session_id_of_self_and_unknown_pid():
    sid = process_session_id(os.getpid())
    assert isinstance(sid, int) and sid >= 0 and current_session_id() == sid
    assert process_session_id(0xFFFFFFF0) is None

@windows
def test_real_resolver_finds_this_process_for_a_loopback_connection():
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen()
    cli = socket.create_connection(srv.getsockname()); conn, _ = srv.accept()
    try:
        info = PsutilPeerResolver().resolve("127.0.0.1", cli.getsockname()[1], srv.getsockname()[1])
        assert info is not None and info.pid == os.getpid() and info.session_id == current_session_id()
        assert info.user is not None and info.user.lower().endswith("\\" + getpass.getuser().lower())
        assert info.exe is not None and info.exe.lower().endswith("python.exe")
    finally:
        conn.close(); cli.close(); srv.close()

def test_resolver_ignores_non_loopback_and_unknown_connections():
    r = PsutilPeerResolver()
    assert r.resolve("10.0.0.1", 50000, 8700) is None
    assert r.resolve("127.0.0.1", 1, 2) is None

HONG = PeerInfo(pid=4242, session_id=2, user="CORP\\hong", exe=r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")

async def test_local_auth_events_record_the_windows_account(local_client, services):
    services.peers = FakePeerResolver(HONG)
    await bootstrap(local_client); await login(local_client, services)
    events = await audit_events(services, "auth")
    assert {e["event"] for e in events} >= {"otp_request", "login"}
    assert all(e["windows_user"] == "CORP\\hong" for e in events)
    assert services.peers.calls[0][0] == "127.0.0.1" and services.peers.calls[0][2] == 8700

async def test_external_auth_events_have_no_windows_account(local_client, external_client, services):
    services.peers = FakePeerResolver(HONG)
    await bootstrap(local_client); await login(external_client, services)
    ext = [e for e in await audit_events(services, "auth") if e["channel"] == "external"]
    assert ext and all("windows_user" not in e for e in ext)

async def test_unresolvable_peer_is_recorded_as_null(local_client, services):
    services.peers = FakePeerResolver(None)
    await bootstrap(local_client); await login(local_client, services)
    assert all(e["windows_user"] is None for e in await audit_events(services, "auth"))
```

- [ ] **Step 2: 실패 확인** — Run: `uv run python -m pytest tests/test_peer.py -v` → FAIL

- [ ] **Step 3: 구현** — 위 Interfaces대로. `ffi.py`는 모듈 import 시 `ctypes.WinDLL("kernel32", use_last_error=True)`를 `IS_WINDOWS`일 때만 만듭니다(다른 OS에서는 함수가 `None`을 돌려줌).

- [ ] **Step 4: 통과 확인** — Run: `uv run python -m pytest -q` → 전체 통과. ruff·mypy 0건.

- [ ] **Step 5: Commit** — `git commit -m "feat: resolve loopback peers to Windows sessions and record the localhost login's Windows account"`

---

### Task 3: WTS 세션 소스 (ctypes 어댑터, 개발용 JSON 소스, 파서)

**Files:**
- Create: `server/app/win/wts.py`, `server/app/sessions/__init__.py`, `server/app/sessions/jsonsource.py`, `server/tests/test_wts.py`
- Modify: `server/tests/winfakes.py` (`FakeWtsSource`)

**Interfaces:**
- Produces (`app.win.wts`):
  - `STATE_NAMES = ("active", "connected", "connect_query", "shadow", "disconnected", "idle", "listen", "reset", "down", "init")`; `state_name(code: int) -> str`(범위 밖 → `"unknown"`); `protocol_name(code: int) -> Literal["console", "rdp", "other"]`(0 → console, 2 → rdp, 그 밖 → other).
  - `filetime_to_dt(value: int) -> datetime | None`: 0 이하 → `None`; 아니면 `datetime(1601, 1, 1, tzinfo=UTC) + timedelta(microseconds=value // 10)`.
  - `parse_client_address(family: int, raw: bytes) -> str | None`: `AF_INET`(2) → `raw[2:6]`, `AF_INET6`(23) → `raw[2:18]`(V9의 실기기 확인 항목), 그 밖·전부 0 → `None`.
  - `format_resolution(h: int, v: int, depth_code: int) -> str | None`: `h`나 `v`가 0 → `None`. 색 깊이 코드 `{1: 4, 2: 8, 4: 16, 8: 24, 16: 15, 24: 24, 32: 32}` → `"1920x1080@32"`, 모르는 코드 → `"800x600"`(깊이 생략).
  - `@dataclass(frozen=True) WtsSession(session_id: int, station: str, state: str, user: str, domain: str | None, client_name: str | None, client_ip: str | None, client_build: int | None, protocol: Literal["console", "rdp", "other"], resolution: str | None, logon_at: datetime | None, connected_at: datetime | None, disconnected_at: datetime | None, last_input_at: datetime | None, locked: bool | None)` — `user`는 로그온한 사용자가 없으면 `""`.
  - `@dataclass(frozen=True) WtsSnapshot(at: datetime, sessions: tuple[WtsSession, ...])`
  - `class WtsError(Exception)`; `class WtsSource(Protocol): def snapshot(self) -> WtsSnapshot` (블로킹, 수집 스레드에서만 호출; 실패 → `WtsError`)
  - `class CtypesWtsSource(clock: Clock)`: `WTSEnumerateSessionsW(0, 0, 1, …)`(실패 → `WtsError`), 상태가 `listen`인 세션은 건너뜁니다. 세션마다 `WTSQuerySessionInformationW`로 `WTSSessionInfoEx`(25: `WTSINFOEX_LEVEL1_W` — `SessionState`, `SessionFlags`(0 = 잠김, 1 = 풀림, −1 = 모름), `WinStationName[33]`, `UserName[21]`, `DomainName[18]`, `LogonTime`·`ConnectTime`·`DisconnectTime`·`LastInputTime`(LARGE_INTEGER FILETIME)), `WTSClientName`(10), `WTSClientAddress`(14: `DWORD AddressFamily; BYTE Address[20]`), `WTSClientBuildNumber`(9: ULONG), `WTSClientDisplay`(15: 3×DWORD), `WTSClientProtocolType`(16: USHORT)를 읽고, 버퍼마다 `WTSFreeMemory`. 한 세션의 조회가 실패하면(세션이 그사이 사라짐) 그 세션만 건너뜁니다. `snapshot.at = clock.now()`. 빈 문자열은 `None`(단 `user`는 `""`).
- Produces (`app.sessions.jsonsource`):
  - `class JsonFileWtsSource(path: Path, clock: Clock, *, self_session_id: Callable[[], int] = current_session_id)`: **개발·E2E 전용**(V24). 파일 `{"sessions": [ {...} ]}`을 매번 읽습니다. 항목 키: `session_id`(정수 또는 `"self"`), `user`(필수 문자열), `domain`, `client_name`, `client_ip`, `client_build`, `resolution`, `logon_at`·`connected_at`·`disconnected_at`(ISO 8601, 오프셋 필수), `idle_sec`(→ `last_input_at = at − idle_sec`), `locked`, `state`(기본 `"active"`), `protocol`(기본 `"rdp"`). `station = f"json-{session_id}"`. 파일 없음·JSON 오류·타입 오류 → `WtsError`.
  - `tests/winfakes.FakeWtsSource(items: list[WtsSnapshot | Exception])`: `snapshot()`이 차례로 돌려주고(예외면 raise), 다 쓰면 마지막 항목을 반복합니다. `calls: int`.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_wts.py
import getpass
import ipaddress
import json
from datetime import UTC, datetime, timedelta

import pytest

from app.clock import SystemClock
from app.sessions.jsonsource import JsonFileWtsSource
from app.win.ffi import current_session_id
from app.win.wts import (CtypesWtsSource, WtsError, filetime_to_dt, format_resolution,
                         parse_client_address, protocol_name, state_name)

def test_filetime_to_dt():
    assert filetime_to_dt(0) is None
    assert filetime_to_dt(134382420000000000) == datetime(2026, 11, 4, 5, 0, tzinfo=UTC)
    assert filetime_to_dt(134382419705000000) == datetime(2026, 11, 4, 4, 59, 30, 500000, tzinfo=UTC)

def test_parse_client_address():
    assert parse_client_address(2, bytes([0, 0, 10, 0, 3, 21]) + bytes(14)) == "10.0.3.21"
    v6 = ipaddress.IPv6Address("fe80::1").packed
    assert parse_client_address(23, bytes(2) + v6 + bytes(2)) == "fe80::1"
    assert parse_client_address(0, bytes(20)) is None
    assert parse_client_address(2, bytes(20)) is None

def test_format_resolution():
    assert format_resolution(1920, 1080, 32) == "1920x1080@32"
    assert format_resolution(1280, 720, 8) == "1280x720@24"
    assert format_resolution(800, 600, 99) == "800x600"
    assert format_resolution(0, 0, 0) is None

def test_state_and_protocol_names():
    assert [state_name(i) for i in (0, 4, 6)] == ["active", "disconnected", "listen"] and state_name(42) == "unknown"
    assert (protocol_name(0), protocol_name(2), protocol_name(1)) == ("console", "rdp", "other")

def test_json_source_resolves_self_and_idle(tmp_path, clock):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"sessions": [{
        "session_id": "self", "user": "hong", "domain": "CORP", "client_ip": "10.0.3.21", "client_name": "HONG-LAPTOP",
        "client_build": 26100, "resolution": "1920x1080@32", "logon_at": "2026-11-04T13:00:00+09:00",
        "connected_at": "2026-11-04T13:59:00+09:00", "idle_sec": 90, "locked": False}]}), "utf-8")
    snap = JsonFileWtsSource(p, clock, self_session_id=lambda: 7).snapshot()
    [s] = snap.sessions
    assert (snap.at, s.session_id, s.state, s.protocol, s.client_ip, s.client_build, s.locked, s.station) == \
        (clock.now(), 7, "active", "rdp", "10.0.3.21", 26100, False, "json-7")
    assert s.connected_at == datetime(2026, 11, 4, 4, 59, tzinfo=UTC)
    assert s.last_input_at == clock.now() - timedelta(seconds=90) and s.disconnected_at is None

@pytest.mark.parametrize("content", [None, "{", '{"sessions": [{"session_id": "x", "user": "a"}]}', '{"sessions": [{"session_id": 1}]}'])
def test_json_source_errors(tmp_path, clock, content):
    p = tmp_path / "s.json"
    if content is not None:
        p.write_text(content, "utf-8")
    with pytest.raises(WtsError):
        JsonFileWtsSource(p, clock).snapshot()

@pytest.mark.winlive
def test_ctypes_source_sees_this_session():
    snap = CtypesWtsSource(SystemClock()).snapshot()
    mine = [s for s in snap.sessions if s.session_id == current_session_id()]
    assert len(mine) == 1 and mine[0].state == "active"
    assert mine[0].user.lower() == getpass.getuser().lower() and mine[0].logon_at is not None
    assert mine[0].protocol in ("console", "rdp") and mine[0].locked is False
    assert all(s.state != "listen" for s in snap.sessions)
```

- [ ] **Step 2: 실패 확인** — Run: `uv run python -m pytest tests/test_wts.py -v` → FAIL

- [ ] **Step 3: 구현** — 위 Interfaces대로. 구조체는 `ctypes.Structure`로 문서의 필드 순서 그대로 선언합니다(`WTSINFOEX_LEVEL1_W`는 `ULONG SessionId; WTS_CONNECTSTATE_CLASS SessionState; LONG SessionFlags; WCHAR WinStationName[33]; WCHAR UserName[21]; WCHAR DomainName[18]; LARGE_INTEGER LogonTime, ConnectTime, DisconnectTime, LastInputTime, CurrentTime; DWORD IncomingBytes, OutgoingBytes, IncomingFrames, OutgoingFrames, IncomingCompressedBytes, OutgoingCompressedBytes`, `WTSINFOEXW`는 `DWORD Level; union { WTSINFOEX_LEVEL1_W WTSInfoExLevel1; } Data`). 이름 바꾼 함수가 아니라 `W` 버전만 씁니다.

- [ ] **Step 4: 통과 확인** — Run: `uv run python -m pytest -q` → 전체 통과. Run: `uv run python -m pytest -m winlive tests/test_wts.py -v` → 통과. ruff·mypy 0건.

- [ ] **Step 5: Commit** — `git commit -m "feat: WTS session source over ctypes with parsers and a dev JSON source"`

---

### Task 4: 세션 이력 저장소와 SessionTracker (마이그레이션 6)

**Files:**
- Create: `server/app/sessions/history.py`, `server/app/sessions/tracker.py`, `server/app/collect/config.py`, `server/tests/session_helpers.py`, `server/tests/test_session_tracker.py`
- Modify: `server/app/db.py` (마이그레이션 6), `server/app/services.py` (`session_history`, `sessions`, `build_services(..., collectors: CollectorConfig | None = None)`), `server/tests/test_db.py` (테이블 목록)

**Interfaces:**
- Produces:
  - 마이그레이션 6:
    ```sql
    CREATE TABLE rdp_connections (
        id INTEGER PRIMARY KEY,
        session_id INTEGER NOT NULL,
        logon_at TEXT,
        kind TEXT NOT NULL CHECK (kind IN ('logon','reconnect','existing')),
        user TEXT NOT NULL,
        domain TEXT,
        client_name TEXT,
        client_ip TEXT,
        client_build INTEGER,
        protocol TEXT NOT NULL,
        resolution TEXT,
        reverse_dns TEXT,
        first_seen_ip INTEGER NOT NULL DEFAULT 0,
        first_seen_device INTEGER NOT NULL DEFAULT 0,
        connected_at TEXT NOT NULL,
        ended_at TEXT,
        end_reason TEXT CHECK (end_reason IN ('disconnect','logoff','reconnected','service_stop'))
    );
    CREATE INDEX idx_rdp_connections_connected ON rdp_connections(connected_at);
    CREATE INDEX idx_rdp_connections_ip ON rdp_connections(client_ip);
    CREATE INDEX idx_rdp_connections_device ON rdp_connections(client_name COLLATE NOCASE);
    CREATE TABLE rdp_logon_failures (
        id INTEGER PRIMARY KEY,
        at TEXT NOT NULL,
        user TEXT, domain TEXT, client_ip TEXT, workstation TEXT,
        logon_type INTEGER, status TEXT, sub_status TEXT,
        source TEXT NOT NULL,
        record_id INTEGER,
        UNIQUE (source, record_id)
    );
    CREATE INDEX idx_rdp_logon_failures_at ON rdp_logon_failures(at);
    ```
  - `app.collect.config.CollectorConfig` (frozen dataclass; 이후 과제가 필드를 더합니다): `wts: WtsSource | None = None`, `collect_console: bool = False`, `poll_interval_sec: float = 0.5`. `build_services`는 `collectors or CollectorConfig()`를 `Services.config_collectors`에 둡니다.
  - `app.sessions.history`:
    - `@dataclass(frozen=True) Connection(id, session_id, logon_at: datetime | None, kind, user, domain, client_name, client_ip, client_build, protocol, resolution, reverse_dns, first_seen_ip: bool, first_seen_device: bool, connected_at: datetime, ended_at: datetime | None, end_reason: str | None)`
    - `@dataclass(frozen=True) LogonFailureIn(at: datetime, user: str | None, domain: str | None, client_ip: str | None, workstation: str | None, logon_type: int | None, status: str | None, sub_status: str | None, source: str, record_id: int | None)`; `LogonFailure(LogonFailureIn)` + `id: int`(필드 순서: `id`가 맨 앞인 별도 dataclass).
    - `class SessionHistory(db: Database, clock: Clock)`: `open(s: WtsSession, kind: str, at: datetime) -> Connection`(한 트랜잭션: `first_seen_ip` = `client_ip`가 있고 같은 IP의 이전 행이 없음, `first_seen_device` = `client_name`이 있고 같은 이름(NOCASE)의 이전 행이 없음), `close(conn_id: int, at: datetime, reason: str) -> None`(`ended_at IS NULL`인 행만), `set_reverse_dns(conn_id, name: str | None)`, `close_dangling(at: datetime) -> int`(`ended_at IS NULL` → `service_stop`), `get(conn_id) -> Connection | None`, `connections(since: datetime, limit: int = 200, before_id: int | None = None) -> list[Connection]`(`connected_at >= since`, id 내림차순), `add_failure(f: LogonFailureIn) -> int | None`(`(source, record_id)` 중복이면 `None`), `failures(since: datetime, limit: int = 200) -> list[LogonFailure]`(최신순).
  - `app.sessions.tracker`:
    - `@dataclass(frozen=True) Opened(connection: Connection, session: WtsSession)`, `Closed(connection_id: int, session_id: int, reason: Literal["disconnect", "logoff", "reconnected"], at: datetime)`, `LockChanged(session_id: int, locked: bool, at: datetime)`; `Change = Opened | Closed | LockChanged`.
    - `@dataclass(frozen=True) SessionContext(session_id: int, user: str, domain: str | None, client_ip: str | None, client_name: str | None, connection_id: int | None)`; `account` 프로퍼티 = `f"{domain}\\{user}"`(도메인 없으면 `user`).
    - `RDP_KEYS = frozenset({"session_id", "user", "domain", "client_name", "client_ip", "reverse_dns", "logon_at", "connected_at", "state", "idle_sec", "resolution", "notice_acknowledged", "connection_id", "client_build", "protocol", "first_seen_ip", "first_seen_device"})`
    - `class SessionTracker(history: SessionHistory, clock: Clock, log: LogWriter, bus: BoardBus, *, collect_console: bool = False)` (루프 스레드 전용):
      - `ready: bool`(첫 `apply` 뒤 True), `start() -> int`(= `history.close_dangling(clock.now())`).
      - `apply(snap: WtsSnapshot) -> list[Change]`: 감시 대상 = `user != ""` 이고 (`protocol == "rdp"` 또는 (`collect_console` 이고 `protocol == "console"`)). 세션 정체성 = `(session_id, logon_at)`(V9). 규칙(세션별, 변화 순서대로 `Change`를 만듭니다):
        1. 이전에 없던 정체성이 `active`로 나타남 → `Opened(kind="existing")`(첫 스냅숏) 또는 `"logon"`(그 뒤). 같은 `session_id`의 이전 정체성이 있었다면 먼저 그 연결을 `Closed("logoff")`.
        2. 같은 정체성: `disconnected`/`connected` → `active` → `Opened("reconnect")`. `active` → `active`인데 `connected_at`이 바뀜 → `Closed("reconnected")` + `Opened("reconnect")`. `active` → `disconnected` → `Closed("disconnect")`.
        3. 정체성이 사라짐 → 열린 연결이 있으면 `Closed("logoff")`(없어도 `session` `logoff` 로그는 남김).
        4. `locked`가 `True`/`False` 사이에서 바뀜 → `LockChanged`.
        각 `Change`마다 `session` 로그(`connect`/`disconnect`/`logoff`/`lock`/`unlock`, `at=snap.at`, `source="wts"`, 연결 필드)와 이력 행을 쓰고, 그 뒤 리스너를 등록 순서대로 부릅니다(리스너 예외는 `system` `sessions.listener_failed`로 남기고 계속).
      - `failed(error: str) -> None`: 상태는 그대로 두고 `system` `sessions.wts_failed`를 시계 기준 60초에 한 번만 남깁니다.
      - `add_listener(fn: Callable[[Change], None])`.
      - `board_sessions() -> list[dict] | None`: `ready` 전 → `None`. 감시 대상 중 `active`인 세션만, `session_id` 순. 항목 = `RDP_KEYS`: `user`(이름만), `domain`, `client_*`, `reverse_dns`(연결 행), `logon_at`·`connected_at`(`to_kst_iso` | None), `state`(`"locked"` if `locked` else `"active"`), `idle_sec`(`int((snap.at − last_input_at).total_seconds())`, 음수면 0, 없으면 None), `resolution`, `notice_acknowledged`(`set_notice_state` 값, 기본 None), `connection_id`, `client_build`, `protocol`, `first_seen_ip`, `first_seen_device`.
      - 게시: `apply`·`set_notice_state`·`set_reverse_dns` 뒤 `board_sessions()`를 `idle_sec`를 `idle_sec // 60`으로 바꾼 비교 키로 이전 게시와 비교해, 다르면 `bus.publish("sessions", {"sessions": board_sessions()})`(공개). 처음 `ready`가 될 때도 한 번 게시합니다(V10).
      - `current() -> list[dict]`: 감시 대상 전부(끊긴 세션 포함) `{"session_id", "user", "domain", "state", "client_name", "client_ip", "protocol", "logon_at", "connected_at", "disconnected_at", "idle_sec", "connection_id"}`, `state` ∈ `active`/`locked`/`disconnected`/`connected`.
      - `context(session_id) -> SessionContext | None`(감시 대상 세션이 지금 있으면), `by_user(user: str, domain: str | None) -> SessionContext | None`(대소문자 무시, `domain`이 None이면 도메인 무시, 정확히 하나일 때만), `set_notice_state(connection_id: int, acknowledged: bool | None)`, `set_reverse_dns(connection_id: int, name: str | None)`(이력 행도 갱신), `connection_of(session_id) -> int | None`.
  - `Services.session_history: SessionHistory`, `Services.sessions: SessionTracker`(`collect_console`은 config에서).
  - `tests/session_helpers.py`: `T0 = datetime(2026, 11, 4, 4, 0, tzinfo=UTC)`(13:00 KST), `ws(session_id=2, *, state="active", user="hong", domain="CORP", protocol="rdp", logon=T0, connected=T0, ip="10.0.3.21", name="HONG-LAPTOP", build=26100, res="1920x1080@32", locked=False, last_input=None) -> WtsSession`(`station=f"RDP-Tcp#{session_id}"`, `disconnected_at=None`), `snap(at, *sessions) -> WtsSnapshot`.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_session_tracker.py
from datetime import timedelta

from app.clock import to_kst_iso
from app.sessions.tracker import RDP_KEYS, Closed, LockChanged, Opened, SessionTracker
from tests.session_helpers import T0, snap, ws
from tests.test_auth_api import audit_events

def kinds(changes):
    return [(type(c).__name__, getattr(c, "reason", None)) for c in changes]

async def test_first_snapshot_opens_existing_for_active_rdp_only(services, clock):
    ch = services.sessions.apply(snap(clock.now(), ws(2), ws(3, state="disconnected"),
                                      ws(1, protocol="console", user="dev"), ws(4, user="")))
    assert [(type(c).__name__, c.connection.kind, c.session.session_id) for c in ch] == [("Opened", "existing", 2)]
    rows = services.session_history.connections(T0 - timedelta(days=1))
    assert [(r.session_id, r.kind, r.ended_at) for r in rows] == [(2, "existing", None)]

async def test_logon_disconnect_reconnect_logoff(services, clock):
    t = services.sessions; t.apply(snap(clock.now()))
    clock.advance(5); [o] = t.apply(snap(clock.now(), ws(2, logon=clock.now(), connected=clock.now())))
    assert isinstance(o, Opened) and o.connection.kind == "logon"
    logon, conn = o.connection.logon_at, o.connection.connected_at
    clock.advance(5); [c] = t.apply(snap(clock.now(), ws(2, state="disconnected", logon=logon, connected=conn)))
    assert (c.reason, c.connection_id) == ("disconnect", o.connection.id)
    clock.advance(5); [o2] = t.apply(snap(clock.now(), ws(2, logon=logon, connected=clock.now())))
    assert o2.connection.kind == "reconnect" and o2.connection.id != o.connection.id
    clock.advance(5); [c2] = t.apply(snap(clock.now()))
    assert (c2.reason, c2.connection_id) == ("logoff", o2.connection.id)
    assert [e["event"] for e in await audit_events(services, "session")] == ["connect", "disconnect", "connect", "logoff"]

async def test_fast_reconnect_detected_by_connect_time(services, clock):
    t = services.sessions; t.apply(snap(clock.now()))
    t.apply(snap(clock.now(), ws(2, logon=T0, connected=T0)))
    clock.advance(3)
    ch = t.apply(snap(clock.now(), ws(2, logon=T0, connected=T0 + timedelta(minutes=5))))
    assert kinds(ch) == [("Closed", "reconnected"), ("Opened", None)] and ch[1].connection.kind == "reconnect"

async def test_session_id_reuse_is_a_new_logon(services, clock):
    t = services.sessions; t.apply(snap(clock.now())); t.apply(snap(clock.now(), ws(2, logon=T0)))
    later = T0 + timedelta(hours=1)
    ch = t.apply(snap(clock.now(), ws(2, logon=later, connected=later)))
    assert kinds(ch) == [("Closed", "logoff"), ("Opened", None)] and ch[1].connection.kind == "logon"

async def test_console_needs_collect_console(services, clock):
    assert services.sessions.apply(snap(clock.now(), ws(1, protocol="console"))) == []
    t = SessionTracker(services.session_history, clock, services.log, services.bus, collect_console=True)
    [o] = t.apply(snap(clock.now(), ws(1, protocol="console")))
    assert o.connection.kind == "existing" and t.board_sessions()[0]["protocol"] == "console"

async def test_lock_events(services, clock):
    t = services.sessions; t.apply(snap(clock.now(), ws(2)))
    assert t.apply(snap(clock.now(), ws(2, locked=True))) == [LockChanged(2, True, clock.now())]
    assert t.board_sessions()[0]["state"] == "locked"
    assert [e["event"] for e in await audit_events(services, "session")] == ["connect", "lock"]

async def test_board_sessions_shape(services, clock):
    t = services.sessions
    assert t.board_sessions() is None and not t.ready
    t.apply(snap(clock.now(), ws(2, last_input=clock.now() - timedelta(seconds=125))))
    [s] = t.board_sessions()
    assert set(s) == RDP_KEYS and isinstance(s["connection_id"], int)
    assert {k: v for k, v in s.items() if k != "connection_id"} == {
        "session_id": 2, "user": "hong", "domain": "CORP", "client_name": "HONG-LAPTOP", "client_ip": "10.0.3.21",
        "reverse_dns": None, "logon_at": to_kst_iso(T0), "connected_at": to_kst_iso(T0), "state": "active",
        "idle_sec": 125, "resolution": "1920x1080@32", "notice_acknowledged": None, "client_build": 26100,
        "protocol": "rdp", "first_seen_ip": True, "first_seen_device": True}

async def test_publishes_sessions_only_on_visible_change(services, clock):
    sub = services.bus.subscribe(); t = services.sessions; li = clock.now()
    t.apply(snap(clock.now(), ws(2, last_input=li)))
    assert [n for n, _ in sub.events] == ["sessions"]; sub.events.clear()
    clock.advance(30); t.apply(snap(clock.now(), ws(2, last_input=li)))
    assert list(sub.events) == []
    clock.advance(31); t.apply(snap(clock.now(), ws(2, last_input=li)))
    assert [d["sessions"][0]["idle_sec"] for _, d in sub.events] == [61]

async def test_first_seen_flags(services, clock):
    t = services.sessions; t.apply(snap(clock.now()))
    [o1] = t.apply(snap(clock.now(), ws(2)))
    clock.advance(1); t.apply(snap(clock.now()))
    clock.advance(1); [o2] = t.apply(snap(clock.now(), ws(3, logon=clock.now(), name="hong-laptop")))
    clock.advance(1); t.apply(snap(clock.now()))
    clock.advance(1); [o3] = t.apply(snap(clock.now(), ws(4, logon=clock.now(), ip="10.0.9.9", name="OTHER")))
    assert [(o.connection.first_seen_ip, o.connection.first_seen_device) for o in (o1, o2, o3)] == \
        [(True, True), (False, False), (True, True)]

async def test_start_closes_dangling_rows(services, clock):
    services.sessions.apply(snap(clock.now(), ws(2)))
    t2 = SessionTracker(services.session_history, clock, services.log, services.bus)
    clock.advance(60)
    assert t2.start() == 1
    [row] = services.session_history.connections(T0 - timedelta(days=1))
    assert (row.end_reason, row.ended_at) == ("service_stop", clock.now())

async def test_wts_failure_logged_once_per_minute_and_state_kept(services, clock):
    t = services.sessions; t.apply(snap(clock.now(), ws(2)))
    t.failed("boom"); clock.advance(30); t.failed("boom"); clock.advance(31); t.failed("boom")
    failures = [e for e in await audit_events(services, "system") if e.get("event") == "sessions.wts_failed"]
    assert len(failures) == 2 and failures[0]["error"] == "boom"
    assert len(t.board_sessions()) == 1

async def test_context_by_user_and_listener_order(services, clock):
    seen = []; t = services.sessions; t.add_listener(seen.append)
    t.apply(snap(clock.now(), ws(2), ws(3, user="kim", ip="10.0.0.9", name="KIM-PC")))
    ctx = t.context(3)
    assert (ctx.user, ctx.domain, ctx.client_ip, ctx.client_name, ctx.account) == ("kim", "CORP", "10.0.0.9", "KIM-PC", "CORP\\kim")
    assert t.by_user("KIM", "corp").session_id == 3 and t.by_user("kim", None).session_id == 3 and t.by_user("nobody", None) is None
    assert [c.session.session_id for c in seen] == [2, 3] and t.context(99) is None
```

- [ ] **Step 2: 실패 확인** — Run: `uv run python -m pytest tests/test_session_tracker.py tests/test_db.py -v` → FAIL

- [ ] **Step 3: 구현** — 위 Interfaces대로. 이력 쓰기는 `apply` 안에서 바로(루프 스레드) 합니다. `test_db.py`의 테이블 목록에 `rdp_connections`, `rdp_logon_failures`를 더합니다.

- [ ] **Step 4: 통과 확인** — Run: `uv run python -m pytest -q` → 전체 통과. ruff·mypy 0건.

- [ ] **Step 5: Commit** — `git commit -m "feat: RDP connection history and a session tracker that diffs WTS snapshots into connects, reconnects and logoffs"`

---
### Task 5: 세션 수집 배선 — 수집 스레드, 보드·SSE `sessions`, 세션 API, CLI

**Files:**
- Create: `server/app/sessions/collector.py`, `server/app/sessions/rdns.py`, `server/app/collect/manager.py`, `server/app/collect/cli.py`, `server/app/web/sessions_api.py`
- Create: `server/tests/test_session_collector.py`, `server/tests/test_sessions_api.py`
- Modify: `server/app/collect/config.py`, `server/app/services.py` (`collectors`), `server/app/web/mcp_shared.py` (`board_snapshot`, `board_stream(snapshot=)`), `server/app/web/app_factory.py` (두 채널에 `sessions_api.router`), `server/app/main.py`, `server/app/__main__.py`, `server/tests/winfakes.py`
- Modify (tests): `server/tests/test_main_cli.py`

**Interfaces:**
- Consumes: Task 1 `CollectorBridge`, Task 3 `WtsSource`/`WtsError`/`JsonFileWtsSource`/`CtypesWtsSource`, Task 4 `SessionTracker`/`SessionHistory`/`Opened`.
- Produces:
  - `app.sessions.collector`:
    - `@dataclass(frozen=True) WtsFailure(error: str, at: datetime)`
    - `class SessionCollector(source: WtsSource, post: Callable[[WtsSnapshot | WtsFailure], None], clock: Clock, *, interval_sec: float = 0.5)`: `start()`(데몬 스레드 `wts-collector`), `nudge()`(대기 중이면 즉시 깨움; Plan 5 서비스 호스트가 `SERVICE_CONTROL_SESSIONCHANGE`에서 부릅니다), `stop(timeout: float = 2.0)`, `alive: bool`. 루프: `snapshot()` → `post(snap)`; `WtsError`·그 밖 예외 → `post(WtsFailure(repr(exc), clock.now()))`; 그다음 `threading.Event.wait(interval_sec)`(nudge·stop이 깨움).
  - `app.sessions.rdns.ReverseDns(lookup: Callable[[str], tuple[str, list[str], list[str]]] = socket.gethostbyaddr, *, timeout_sec: float = 2.0, ttl_sec: float = 600, clock: Clock)`: `async resolve(ip: str) -> str | None` — IP가 아니면 `None`, 캐시(성공·실패 모두 `ttl_sec`), 조회는 `asyncio.to_thread` + `asyncio.wait_for(timeout_sec)`(시간 초과·`OSError` → `None`, 시간 초과 결과는 캐시하지 않음).
  - `app.collect.manager`:
    - `class Component(Protocol)`: `name: str`, `def start(self, bridge: CollectorBridge) -> None`(루프 스레드에서 호출, 스레드 생성), `def stop(self) -> None`(블로킹 허용; `asyncio.to_thread`로 불림).
    - `@dataclass CollectorStatus(name: str, ok: bool, error: str | None, since: datetime)`
    - `class Collectors(log: LogWriter, clock: Clock)`: `add(component)`, `add_task(name: str, fn: Callable[[], Awaitable[None]])`(시작 때 `create_task`, 정지 때 취소), `async start()`(실행 중인 루프로 `CollectorBridge` 생성 → 각 `component.start(bridge)` → 태스크 시작; 컴포넌트 시작 예외는 `report(name, False, repr(exc))` 후 계속), `async stop()`(태스크 취소 → 각 `await asyncio.to_thread(c.stop)`), `report(name, ok, error=None)`(상태가 바뀔 때만 `since` 갱신 + `system` `collector.status {source, ok, error}`), `status() -> list[CollectorStatus]`(이름순), `bridge: CollectorBridge | None`.
    - `class SessionsComponent(source, tracker, collectors, rdns: ReverseDns, clock, *, interval_sec)`: `name = "wts"`. `start`에서 `tracker.start()`, 브리지 핸들러 `"wts"` 등록(항목마다: `WtsSnapshot` → `tracker.apply` + `report("wts", True)`, `WtsFailure` → `tracker.failed(error)` + `report("wts", False, error)`), 트래커 리스너(`Opened`이고 `client_ip`가 있으면 `create_task(_resolve)` → `tracker.set_reverse_dns`), `SessionCollector` 시작.
  - `CollectorConfig`에 `wts`가 있으면 `build_services`가 `SessionsComponent`를 `Services.collectors`에 더합니다. `Services.collectors: Collectors`.
  - `app.web.mcp_shared.board_snapshot(services: Services) -> dict[str, Any]` = `monitor.board_snapshot()` + (`tracker.board_sessions()`가 None이 아니면 `"sessions"`). `GET /api/board`와 `open_stream`이 이것을 씁니다. `board_stream(monitor, bus, sub, *, snapshot: Callable[[], dict[str, Any]] | None = None, coalesce_sec=..., heartbeat_sec=...)` — `None`이면 지금처럼 `monitor.board_snapshot()`.
  - `app.web.sessions_api.router`(두 채널, 모두 `require(Action.VIEW_SESSION_HISTORY)`):
    - `GET /api/sessions/current` → `{"ready": bool, "sessions": tracker.current()}`
    - `GET /api/sessions/history?days=7&limit=200&before_id=`(`days` 1–90, `limit` 1–500, `before_id` 1–2^63−1) → `{"connections": [connection_json], "failures": [failure_json], "next_before_id": int | None}`. `since = clock.now() − days`. `next_before_id` = 마지막 행 id(행 수 == limit일 때), 아니면 None. `connection_json` 키 = `CONNECTION_KEYS = {"id", "session_id", "user", "domain", "client_name", "client_ip", "reverse_dns", "client_build", "protocol", "resolution", "kind", "logon_at", "connected_at", "ended_at", "end_reason", "first_seen_ip", "first_seen_device", "notice"}`(`notice`는 Task 11까지 `None`). `failure_json` 키 = `{"id", "at", "user", "domain", "client_ip", "workstation", "logon_type", "status", "sub_status", "source"}`.
    - `GET /api/sessions/collectors` → `[{"name", "ok", "error", "since"}]`
  - `app.collect.cli.collector_config(ns: argparse.Namespace, *, clock: Clock, root: Path) -> CollectorConfig`; `--session-source`: `wts`(기본, `CtypesWtsSource(clock)`), `none`(→ `wts=None`), `json:<경로>`(→ `JsonFileWtsSource`; stderr에 `WARNING: dev session source`). 그 밖 → `argparse` 오류(종료 2). `--collect-console`(store_true).
  - `serve(..., collectors: CollectorConfig | None = None)`: `build_services(root, dev_fixed_code=..., collectors=collectors)`; 모니터 시작 뒤 `await services.collectors.start()`, `finally`에서 모니터 정지 전에 `await services.collectors.stop()`. `main()`이 `collector_config(ns, clock=SystemClock(), root=ns.root)`를 넘깁니다.
  - `tests/winfakes.py`: `ListLog`, `eventually` 외에 Task 3의 `FakeWtsSource`.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_session_collector.py
import asyncio
import socket
import time

from app.collect.bridge import CollectorBridge
from app.sessions.collector import SessionCollector, WtsFailure
from app.sessions.rdns import ReverseDns
from app.win.wts import WtsError, WtsSnapshot
from tests.session_helpers import snap, ws
from tests.winfakes import FakeWtsSource, ListLog, eventually

async def test_collector_posts_snapshots_and_failures(clock):
    got = []; bridge = CollectorBridge(asyncio.get_running_loop(), ListLog())
    src = FakeWtsSource([snap(clock.now()), WtsError("rpc"), snap(clock.now(), ws(2))])
    c = SessionCollector(src, bridge.register("wts", got.extend), clock, interval_sec=0.01); c.start()
    try:
        await eventually(lambda: len(got) >= 3)
    finally:
        c.stop()
    assert [type(x) for x in got[:3]] == [WtsSnapshot, WtsFailure, WtsSnapshot] and got[1].error == "WtsError('rpc')"

async def test_nudge_wakes_the_collector_early(clock):
    got = []; bridge = CollectorBridge(asyncio.get_running_loop(), ListLog())
    c = SessionCollector(FakeWtsSource([snap(clock.now())]), bridge.register("wts", got.extend), clock, interval_sec=30); c.start()
    try:
        await eventually(lambda: len(got) == 1)
        c.nudge()
        await eventually(lambda: len(got) == 2, timeout=1.0)
    finally:
        c.stop()

async def test_stop_joins_quickly(clock):
    c = SessionCollector(FakeWtsSource([snap(clock.now())]), lambda item: None, clock, interval_sec=30); c.start()
    t0 = time.monotonic(); c.stop()
    assert not c.alive and time.monotonic() - t0 < 2.0

async def test_reverse_dns_timeout_cache_and_errors(clock):
    def slow(ip):
        time.sleep(0.5); return ("late.corp", [], [ip])
    assert await ReverseDns(slow, timeout_sec=0.05, clock=clock).resolve("10.0.3.21") is None
    calls = []
    def fast(ip):
        calls.append(ip)
        if ip == "10.0.0.2":
            raise socket.herror(1, "unknown host")
        return ("pc.corp", [], [ip])
    r = ReverseDns(fast, timeout_sec=1, clock=clock)
    assert await r.resolve("10.0.0.1") == "pc.corp" and await r.resolve("10.0.0.1") == "pc.corp"
    assert await r.resolve("10.0.0.2") is None and await r.resolve("10.0.0.2") is None
    assert calls == ["10.0.0.1", "10.0.0.2"] and await r.resolve("not-an-ip") is None
    clock.advance(601); await r.resolve("10.0.0.1"); assert calls.count("10.0.0.1") == 2
```

```python
# server/tests/test_sessions_api.py
import asyncio

from app.clock import to_kst_iso
from app.web.mcp_shared import board_snapshot, board_stream
from tests.mcp_helpers import login_as, make_user
from tests.session_helpers import snap, ws

CONNECTION_KEYS = {"id", "session_id", "user", "domain", "client_name", "client_ip", "reverse_dns", "client_build",
                   "protocol", "resolution", "kind", "logon_at", "connected_at", "ended_at", "end_reason",
                   "first_seen_ip", "first_seen_device", "notice"}

async def test_board_has_no_sessions_until_first_snapshot(external_client):
    assert "sessions" not in (await external_client.get("/api/board")).json()

async def test_anonymous_board_and_stream_carry_sessions(external_client, services, clock):
    services.sessions.apply(snap(clock.now(), ws(2)))
    b = (await external_client.get("/api/board")).json()
    assert (b["sessions"][0]["client_ip"], b["sessions"][0]["user"]) == ("10.0.3.21", "hong")
    sub = services.bus.subscribe(authed=False)
    gen = board_stream(services.monitor, services.bus, sub, snapshot=lambda: board_snapshot(services),
                       coalesce_sec=0.01, heartbeat_sec=5)
    try:
        first = await anext(gen)
        assert first.startswith("event: board\n") and '"sessions":[{' in first
        services.sessions.apply(snap(clock.now()))  # logoff
        assert await asyncio.wait_for(anext(gen), 2) == 'event: sessions\ndata: {"sessions":[]}\n\n'
    finally:
        await gen.aclose()

async def test_history_requires_login_and_paginates(external_client, services, clock):
    assert (await external_client.get("/api/sessions/history")).status_code == 401
    login_as(external_client, services, make_user(services, "d@x.com"), "external")
    t = services.sessions; t.apply(snap(clock.now()))
    for _ in range(3):
        clock.advance(10); t.apply(snap(clock.now(), ws(2, logon=clock.now(), connected=clock.now())))
        clock.advance(10); t.apply(snap(clock.now()))
    r1 = (await external_client.get("/api/sessions/history", params={"limit": 2})).json()
    assert len(r1["connections"]) == 2 and r1["next_before_id"] == r1["connections"][-1]["id"]
    c = r1["connections"][0]
    assert set(c) == CONNECTION_KEYS and (c["kind"], c["end_reason"], c["notice"]) == ("logon", "logoff", None)
    assert c["connected_at"] == to_kst_iso(services.session_history.get(c["id"]).connected_at)
    r2 = (await external_client.get("/api/sessions/history", params={"limit": 2, "before_id": r1["next_before_id"]})).json()
    assert len(r2["connections"]) == 1 and r2["next_before_id"] is None and r2["failures"] == []
    assert (await external_client.get("/api/sessions/history", params={"days": 91})).status_code == 422

async def test_current_lists_disconnected_sessions(external_client, services, clock):
    login_as(external_client, services, make_user(services, "d@x.com"), "external")
    services.sessions.apply(snap(clock.now(), ws(2), ws(3, state="disconnected", user="kim")))
    body = (await external_client.get("/api/sessions/current")).json()
    assert body["ready"] is True
    assert sorted((s["session_id"], s["state"]) for s in body["sessions"]) == [(2, "active"), (3, "disconnected")]

async def test_collectors_status(external_client, services, clock):
    login_as(external_client, services, make_user(services, "d@x.com"), "external")
    services.collectors.report("wts", False, "access denied")
    assert (await external_client.get("/api/sessions/collectors")).json() == \
        [{"name": "wts", "ok": False, "error": "access denied", "since": to_kst_iso(clock.now())}]
```

```python
# server/tests/test_main_cli.py (추가)
from app.collect.cli import collector_config
from app.sessions.jsonsource import JsonFileWtsSource
from app.win.wts import CtypesWtsSource

def test_session_source_flags(tmp_path, clock):
    assert isinstance(collector_config(parse_args([]), clock=clock, root=tmp_path).wts, CtypesWtsSource)
    assert collector_config(parse_args(["--session-source", "none"]), clock=clock, root=tmp_path).wts is None
    cfg = collector_config(parse_args(["--session-source", f"json:{tmp_path / 's.json'}", "--collect-console"]), clock=clock, root=tmp_path)
    assert isinstance(cfg.wts, JsonFileWtsSource) and cfg.collect_console is True

def test_session_source_rejects_unknown():
    with pytest.raises(SystemExit) as e:
        parse_args(["--session-source", "bogus"])
    assert e.value.code == 2
```

- [ ] **Step 2: 실패 확인** — Run: `uv run python -m pytest tests/test_session_collector.py tests/test_sessions_api.py tests/test_main_cli.py -v` → FAIL

- [ ] **Step 3: 구현** — 위 Interfaces대로.

- [ ] **Step 4: 통과 확인** — Run: `uv run python -m pytest -q` → 전체 통과. ruff·mypy 0건. 수동: `uv run python -m app --root <scratch>/p4 --session-source wts --collect-console --dev-otp-code 246810 --external-host 127.0.0.1`로 띄우고 `curl http://127.0.0.1:8701/api/board`에 자기 콘솔 세션이 `sessions`로 보이는지 확인합니다(보고서에 붙임).

- [ ] **Step 5: Commit** — `git commit -m "feat: session collector thread, board and SSE sessions, session history/current/collector APIs and CLI flags"`

---

### Task 6: 우회 탐지 기반 — TamperMonitor, `tamper` SSE, 최근 목록 API

**Files:**
- Create: `server/app/activity/__init__.py`, `server/app/activity/tamper.py`, `server/app/web/tamper_api.py`, `server/tests/test_tamper.py`
- Modify: `server/app/services.py` (`tamper`), `server/app/monitor/supervisor.py` (`Monitor(..., tamper=None)`), `server/app/web/app_factory.py` (두 채널에 `tamper_api.router`)
- Modify (tests): `server/tests/test_monitor.py` (`test_tamper_logged`)

**Interfaces:**
- Produces:
  - `app.activity.tamper.TamperMonitor(log: LogWriter, bus: BoardBus, clock: Clock, *, keep: int = 200)` (루프 스레드 전용):
    - `report(event: str, *, at: datetime | None = None, **fields: Any) -> dict[str, Any]`: 레코드 = `{"at": to_kst_iso(at or clock.now()), "event": event, **fields}`. `log.emit("tamper", at=at, event=event, **fields)`, 링 버퍼(최대 `keep`)에 넣고, `bus.publish("tamper", record, public=False)`. 레코드를 돌려줍니다.
    - `recent(limit: int = 50) -> list[dict[str, Any]]`(최신순).
  - `Monitor.__init__(..., tamper: TamperMonitor | None = None)`: 해시 불일치 때 `tamper`가 있으면 `tamper.report("script_hash_mismatch", mcp_id=..., kind=..., path=..., expected_sha256=..., actual_sha256=...)`, 없으면 지금처럼 `log.emit("tamper", event="script_hash_mismatch", ...)`. `build_services`가 `Services.tamper`를 만들어 넘깁니다.
  - `app.web.tamper_api.router`: `GET /api/tamper/recent?limit=50`(1–200, `require(Action.VIEW_LOGS)`, 두 채널) → `tamper.recent(limit)`.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_tamper.py
from datetime import timedelta

from app.activity.tamper import TamperMonitor
from app.clock import to_kst_iso
from tests.mcp_helpers import login_as, make_user
from tests.test_auth_api import audit_events

async def test_report_logs_rings_and_publishes_to_authed_only(services, clock):
    anon = services.bus.subscribe(authed=False); authed = services.bus.subscribe(authed=True)
    rec = services.tamper.report("agent_exited", session_id=2, user="CORP\\hong", exit_code=1)
    assert rec == {"at": to_kst_iso(clock.now()), "event": "agent_exited", "session_id": 2, "user": "CORP\\hong", "exit_code": 1}
    assert list(anon.events) == [] and list(authed.events) == [("tamper", rec)]
    [line] = await audit_events(services, "tamper")
    assert (line["event"], line["exit_code"], line["ts"]) == ("agent_exited", 1, rec["at"])

async def test_recent_is_newest_first_and_bounded(services, clock):
    t = TamperMonitor(services.log, services.bus, clock, keep=3)
    for i in range(5):
        t.report("log_file_truncated", n=i)
    assert [r["n"] for r in t.recent(10)] == [4, 3, 2] and [r["n"] for r in t.recent(1)] == [4]

async def test_event_time_override(services, clock):
    at = clock.now() - timedelta(hours=1)
    assert services.tamper.report("log_cleared", at=at, channel="Security")["at"] == to_kst_iso(at)

async def test_tamper_api_requires_login_and_validates(external_client, services):
    assert (await external_client.get("/api/tamper/recent")).status_code == 401
    login_as(external_client, services, make_user(services, "d@x.com"), "external")
    services.tamper.report("log_cleared", channel="System")
    assert [r["event"] for r in (await external_client.get("/api/tamper/recent")).json()] == ["log_cleared"]
    assert (await external_client.get("/api/tamper/recent", params={"limit": 0})).status_code == 422
```

```python
# server/tests/test_monitor.py — test_tamper_logged 끝에 추가
    assert t["event"] == "script_hash_mismatch"
    assert services.tamper.recent(1)[0]["mcp_id"] == m.id
```

- [ ] **Step 2: 실패 확인** — Run: `uv run python -m pytest tests/test_tamper.py tests/test_monitor.py -v` → FAIL

- [ ] **Step 3: 구현** — 위 Interfaces대로.

- [ ] **Step 4: 통과 확인** — Run: `uv run python -m pytest -q` → 전체 통과. ruff·mypy 0건.

- [ ] **Step 5: Commit** — `git commit -m "feat: tamper monitor with ring buffer, authenticated SSE tamper events and recent-tamper API"`

---

### Task 7: 이벤트 로그 리더 (pywin32 어댑터, XML 파서, 북마크, 채널 상태)

**Files:**
- Create: `server/app/win/eventlog.py`, `server/app/win/accounts.py`, `server/app/collect/eventlog.py`
- Create: `server/tests/eventlog_helpers.py`, `server/tests/fixtures/events/security-4688.xml`, `server/tests/fixtures/events/lsm-25.xml`, `server/tests/test_eventlog.py`
- Modify: `server/app/collect/config.py` (`event_log`, `bookmarks_path`), `server/app/collect/cli.py`, `server/app/services.py`, `server/tests/winfakes.py` (`FakeEventLogSource`)

**Interfaces:**
- Produces (`app.win.eventlog`):
  - `@dataclass(frozen=True) EventRecord(channel: str, provider: str, event_id: int, record_id: int, time_created: datetime, pid: int | None, tid: int | None, user_sid: str | None, computer: str | None, data: Mapping[str, str | None])`
  - `parse_event_xml(xml: str) -> EventRecord`: 네임스페이스 `http://schemas.microsoft.com/win/2004/08/events/event`. `System/Provider@Name`, `EventID`, `EventRecordID`, `TimeCreated@SystemTime`(소수부 7자리까지 → 6자리로 자름, `Z` → UTC), `Execution@ProcessID/@ThreadID`, `Security@UserID`, `Computer`, `Channel`. `EventData/Data[@Name]` → `data[name]`(이름 없는 `Data`는 `Data0`, `Data1`…; 빈 요소 → `None`). `UserData`는 첫 자식 요소의 자식들을 로컬 이름으로 펼칩니다. XML이 깨졌거나 필수 항목이 없으면 `ValueError`.
  - `class EventLogError(Exception)`: `access_denied: bool`, `channel_missing: bool`(winerror 5 / 15007).
  - `class EventSubscription(Protocol)`: `def next(self, timeout_ms: int) -> list[str]`(XML, 시간 초과면 `[]`), `def close(self) -> None`.
  - `class EventLogSource(Protocol)`: `def open(self, channel: str, xpath: str, after_record_id: int | None) -> EventSubscription`, `def latest_record_id(self, channel: str) -> int | None`.
  - `class PywinEventLogSource`: `open` = `win32event.CreateEvent(None, 0, 0, None)` + `win32evtlog.EvtSubscribe(channel, flags, SignalEvent=..., Query=xpath, Bookmark=...)`; `after_record_id`가 있으면 `EvtCreateBookmark(f"<BookmarkList><Bookmark Channel='{channel}' RecordId='{after_record_id}' IsCurrent='true'/></BookmarkList>")` + `EvtSubscribeStartAfterBookmark`, 없으면 `EvtSubscribeToFutureEvents`. `next` = `WaitForSingleObject(signal, timeout_ms)` 뒤 `EvtNext(handle, 64, 0)`을 빌 때까지 → `EvtRender(e, EvtRenderEventXml)`. `latest_record_id` = `EvtQuery(channel, EvtQueryReverseDirection, "*")` → `EvtNext(h, 1)` → 파싱한 `record_id`(없으면 None). `pywintypes.error` → `EventLogError`.
- Produces (`app.win.accounts`): `sid_to_account(sid: str) -> str | None` — `win32security.LookupAccountSid(None, ConvertStringSidToSid(sid))` → `DOMAIN\name`, 실패 → `None`, `functools.lru_cache(maxsize=4096)`.
- Produces (`app.collect.eventlog`):
  - `@dataclass(frozen=True) ChannelSpec(name: str, channel: str, event_ids: tuple[int, ...])`
  - `CHANNELS: tuple[ChannelSpec, ...]` = `eventlog:security`(`Security`; 1102, 4624, 4625, 4634, 4647, 4688, 4719, 4778, 4779, 4800, 4801), `eventlog:lsm`(`Microsoft-Windows-TerminalServices-LocalSessionManager/Operational`; 21–25), `eventlog:rcm`(`Microsoft-Windows-TerminalServices-RemoteConnectionManager/Operational`; 1149), `eventlog:powershell`(`Microsoft-Windows-PowerShell/Operational`; 4104), `eventlog:pwsh`(`PowerShellCore/Operational`; 4104), `eventlog:system`(`System`; 104).
  - `xpath_for(ids: Iterable[int]) -> str` → `"*[System[(EventID=21 or EventID=25)]]"`.
  - `class BookmarkStore(path: Path)`: `get(channel) -> int | None`, `set(channel, record_id)`(JSON `{channel: record_id}`, `path.with_suffix(".tmp")`에 쓰고 `os.replace`, `threading.Lock`), 손상된 파일 → 빈 상태 + stderr에 `collector-state: corrupt bookmark file, starting fresh` 한 번. **`config.db`가 아니라** `data/collector-state.json`입니다(V12).
  - `class ChannelWatcher(spec, source, post_record: Callable[[EventRecord], None], post_status: Callable[[tuple[str, bool, str | None]], None], bookmarks: BookmarkStore, *, now: Callable[[], datetime], retry_sec: float = 60, save_every_sec: float = 5, max_age: timedelta = timedelta(hours=24))`: 스레드 `start()`/`stop(timeout=2.0)`. 동작: `after = bookmarks.get(channel)`, 없으면 `source.latest_record_id(channel)`(처음에는 지금 이후만) → `open` 성공 → `post_status((name, True, None))` → `next(500)` 반복: 파싱(`ValueError`는 건너뛰고 세기), `time_created < now() − max_age`인 것은 버림, 나머지 `post_record`, 마지막 `record_id`를 `save_every_sec`마다 저장(정지할 때도 저장). `EventLogError`/예외 → `post_status((name, False, str(exc)))` → `retry_sec` 동안 정지 가능하게 대기 → 다시 `open`.
  - `class EventLogComponent(source: EventLogSource, bookmarks: BookmarkStore, collectors: Collectors, clock: Clock, specs=CHANNELS)`: `name = "eventlog"`. `on(spec_name: str, handler: Callable[[list[EventRecord]], None])`(여러 핸들러 가능). `start(bridge)`: 핸들러가 하나라도 있는 채널만 브리지 이름 `spec.name`으로 등록해 `ChannelWatcher` 시작, 상태는 브리지 `"eventlog:status"` → `collectors.report`. 핸들러가 없는 채널은 열지 않습니다.
  - `CollectorConfig.event_log: EventLogSource | None = None`, `bookmarks_path: Path | None = None`(None이면 `paths.data_dir / "collector-state.json"`). `--session-source wts`일 때 `collector_config`가 `PywinEventLogSource()`를 넣고, `none`·`json:`이면 `None`. `build_services`는 `event_log`가 있을 때 `Services.eventlog: EventLogComponent | None`을 만들어 `collectors.add` 합니다(핸들러는 Task 8–10·14가 `services.eventlog.on(...)`으로 등록; 등록은 `build_services` 안에서).
  - `tests/eventlog_helpers.evt_xml(channel: str, event_id: int, record_id: int, time: str = "2026-11-04T05:00:00.1234567Z", *, provider: str = "Microsoft-Windows-Security-Auditing", data: Mapping[str, str] | None = None, user_data: tuple[str, Mapping[str, str]] | None = None, pid: int = 4, user_sid: str | None = None) -> str` — 실제 Windows XML과 같은 모양(네임스페이스, `System` 하위 순서)으로 만듭니다.
  - `tests/winfakes.FakeEventLogSource`: `queue(channel, *batches: list[str] | Exception)`, `fail_open(channel, *errors)`, `latest: dict[str, int]`, `opened: list[tuple[str, str, int | None]]`. `next`는 배치가 있으면 꺼내고(예외면 raise), 없으면 `min(timeout_ms, 10)`ms 자고 `[]`.

- [ ] **Step 1: 실패하는 테스트 작성**

`server/tests/fixtures/events/security-4688.xml` (실제 형식, 한 줄로 저장해도 됨):
```xml
<Event xmlns='http://schemas.microsoft.com/win/2004/08/events/event'><System><Provider Name='Microsoft-Windows-Security-Auditing' Guid='{54849625-5478-4994-a5ba-3e3b0328c30d}'/><EventID>4688</EventID><Version>2</Version><Level>0</Level><Task>13312</Task><Opcode>0</Opcode><Keywords>0x8020000000000000</Keywords><TimeCreated SystemTime='2026-11-04T05:03:22.4181234Z'/><EventRecordID>91234</EventRecordID><Correlation/><Execution ProcessID='4' ThreadID='8120'/><Channel>Security</Channel><Computer>MCP-HOST</Computer><Security/></System><EventData><Data Name='SubjectUserSid'>S-1-5-21-111-222-333-1001</Data><Data Name='SubjectUserName'>hong</Data><Data Name='SubjectDomainName'>CORP</Data><Data Name='SubjectLogonId'>0x3e7a1</Data><Data Name='NewProcessId'>0x2274</Data><Data Name='NewProcessName'>C:\Windows\System32\cmd.exe</Data><Data Name='TokenElevationType'>%%1938</Data><Data Name='ProcessId'>0x1a2c</Data><Data Name='CommandLine'>cmd.exe /c deploy.bat</Data><Data Name='TargetUserSid'>S-1-0-0</Data><Data Name='TargetUserName'>-</Data><Data Name='TargetDomainName'>-</Data><Data Name='TargetLogonId'>0x0</Data><Data Name='ParentProcessName'>C:\Windows\explorer.exe</Data><Data Name='MandatoryLabel'>S-1-16-8192</Data></EventData></Event>
```

`server/tests/fixtures/events/lsm-25.xml`:
```xml
<Event xmlns='http://schemas.microsoft.com/win/2004/08/events/event'><System><Provider Name='Microsoft-Windows-TerminalServices-LocalSessionManager' Guid='{5d896912-022d-40aa-a3a8-4fa5515c76d7}'/><EventID>25</EventID><Version>0</Version><Level>4</Level><Task>0</Task><Opcode>0</Opcode><Keywords>0x1000000000000000</Keywords><TimeCreated SystemTime='2026-11-04T04:59:58.0000000Z'/><EventRecordID>512</EventRecordID><Correlation ActivityID='{f420bd6e-0000-0000-0000-000000000000}'/><Execution ProcessID='1080' ThreadID='2212'/><Channel>Microsoft-Windows-TerminalServices-LocalSessionManager/Operational</Channel><Computer>MCP-HOST</Computer><Security UserID='S-1-5-18'/></System><UserData><EventXML xmlns='Event_NS'><User>CORP\hong</User><SessionID>2</SessionID><Address>10.0.3.21</Address><SessionReason>0</SessionReason></EventXML></UserData></Event>
```

```python
# server/tests/test_eventlog.py
import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.collect.eventlog import CHANNELS, BookmarkStore, ChannelSpec, ChannelWatcher, EventLogComponent, xpath_for
from app.win.eventlog import EventLogError, PywinEventLogSource, parse_event_xml
from tests.eventlog_helpers import evt_xml
from tests.winfakes import FakeEventLogSource, eventually

FIX = Path(__file__).parent / "fixtures" / "events"

def test_parse_security_4688_fixture():
    r = parse_event_xml((FIX / "security-4688.xml").read_text("utf-8"))
    assert (r.channel, r.provider, r.event_id, r.record_id, r.pid, r.computer) == \
        ("Security", "Microsoft-Windows-Security-Auditing", 4688, 91234, 4, "MCP-HOST")
    assert r.time_created == datetime(2026, 11, 4, 5, 3, 22, 418123, tzinfo=UTC)
    assert (r.data["NewProcessId"], r.data["CommandLine"], r.data["SubjectUserName"]) == ("0x2274", "cmd.exe /c deploy.bat", "hong")

def test_parse_lsm_userdata_fixture():
    r = parse_event_xml((FIX / "lsm-25.xml").read_text("utf-8"))
    assert (r.event_id, r.user_sid, dict(r.data)) == (25, "S-1-5-18", {"User": "CORP\\hong", "SessionID": "2", "Address": "10.0.3.21", "SessionReason": "0"})

def test_parse_builder_round_trip_and_unnamed_data():
    r = parse_event_xml(evt_xml("System", 104, 7, provider="Microsoft-Windows-Eventlog", user_data=("LogFileCleared", {"SubjectUserName": "admin", "Channel": "Application"})))
    assert (r.channel, r.event_id, r.data["Channel"]) == ("System", 104, "Application")

@pytest.mark.parametrize("bad", ["", "<Event>", "<Event xmlns='http://schemas.microsoft.com/win/2004/08/events/event'><System/></Event>"])
def test_parse_rejects_malformed(bad):
    with pytest.raises(ValueError):
        parse_event_xml(bad)

def test_xpath_and_channel_table():
    assert xpath_for([21, 25]) == "*[System[(EventID=21 or EventID=25)]]"
    assert {c.name for c in CHANNELS} == {"eventlog:security", "eventlog:lsm", "eventlog:rcm", "eventlog:powershell", "eventlog:pwsh", "eventlog:system"}

def test_bookmark_store_roundtrip_and_corrupt(tmp_path, capsys):
    p = tmp_path / "state.json"; b = BookmarkStore(p); b.set("Security", 10); b.set("System", 3)
    assert BookmarkStore(p).get("Security") == 10 and json.loads(p.read_text("utf-8")) == {"Security": 10, "System": 3}
    p.write_text("{", "utf-8")
    assert BookmarkStore(p).get("Security") is None
    assert "corrupt bookmark file" in capsys.readouterr().err

LSM = ChannelSpec("eventlog:lsm", "LSM", (21, 25))
NOW = datetime(2026, 11, 4, 5, 0, tzinfo=UTC)

def watcher(src, records, statuses, tmp_path, **kw):
    return ChannelWatcher(LSM, src, records.append, statuses.append, BookmarkStore(tmp_path / "b.json"), now=lambda: NOW, **kw)

async def test_watcher_posts_records_and_saves_bookmark(tmp_path):
    src = FakeEventLogSource(); src.latest["LSM"] = 500
    src.queue("LSM", [evt_xml("LSM", 25, 501, "2026-11-04T04:59:59Z"), "<broken", evt_xml("LSM", 21, 502, "2026-11-04T04:59:59.5Z")])
    records, statuses = [], []
    w = watcher(src, records, statuses, tmp_path, save_every_sec=0); w.start()
    try:
        await eventually(lambda: len(records) == 2)
    finally:
        w.stop()
    assert src.opened == [("LSM", "*[System[(EventID=21 or EventID=25)]]", 500)]
    assert [r.record_id for r in records] == [501, 502] and statuses[0] == ("eventlog:lsm", True, None)
    assert BookmarkStore(tmp_path / "b.json").get("LSM") == 502

async def test_watcher_reports_access_denied_and_retries(tmp_path):
    src = FakeEventLogSource(); err = EventLogError("access denied"); err.access_denied = True
    src.fail_open("LSM", err)
    records, statuses = [], []
    w = watcher(src, records, statuses, tmp_path, retry_sec=0.05); w.start()
    try:
        await eventually(lambda: len(statuses) >= 2)
    finally:
        w.stop()
    assert statuses[0] == ("eventlog:lsm", False, "access denied") and statuses[1] == ("eventlog:lsm", True, None)

async def test_watcher_resumes_after_bookmark_and_drops_old_events(tmp_path):
    BookmarkStore(tmp_path / "b.json").set("LSM", 40)
    src = FakeEventLogSource()
    src.queue("LSM", [evt_xml("LSM", 25, 41, "2026-11-02T00:00:00Z"), evt_xml("LSM", 25, 42, "2026-11-04T04:00:00Z")])
    records, statuses = [], []
    w = watcher(src, records, statuses, tmp_path); w.start()
    try:
        await eventually(lambda: len(records) == 1)
    finally:
        w.stop()
    assert src.opened[0][2] == 40 and records[0].record_id == 42

async def test_component_dispatches_on_the_loop_and_skips_unhandled(services, clock, tmp_path):
    src = FakeEventLogSource(); src.latest["LSM"] = 1
    src.queue("LSM", [evt_xml("LSM", 25, 2, "2026-11-04T04:59:59Z")])
    comp = EventLogComponent(src, BookmarkStore(tmp_path / "b.json"), services.collectors, clock,
                             specs=(LSM, ChannelSpec("eventlog:rcm", "RCM", (1149,))))
    got = []; comp.on("eventlog:lsm", got.extend)
    services.collectors.add(comp); await services.collectors.start()
    try:
        await eventually(lambda: len(got) == 1)
    finally:
        await services.collectors.stop()
    assert [o[0] for o in src.opened] == ["LSM"]
    assert [(s.name, s.ok) for s in services.collectors.status()] == [("eventlog:lsm", True)]

@pytest.mark.winlive
def test_pywin_source_reads_recent_system_events():
    src = PywinEventLogSource(); last = src.latest_record_id("System")
    assert isinstance(last, int) and last > 3
    sub = src.open("System", "*", last - 3)
    try:
        xs = sub.next(2000)
    finally:
        sub.close()
    recs = [parse_event_xml(x) for x in xs]
    assert 1 <= len(recs) <= 3 and all(r.channel == "System" and r.record_id > last - 3 for r in recs)
    with pytest.raises(EventLogError) as e:
        src.open("Security", "*", None)
    assert e.value.access_denied
```

- [ ] **Step 2: 실패 확인** — Run: `uv run python -m pytest tests/test_eventlog.py -v` → FAIL

- [ ] **Step 3: 구현** — 위 Interfaces대로. `winlive`의 Security 단언은 이 PC가 관리자가 아니기 때문에 성립합니다(Global Constraints).

- [ ] **Step 4: 통과 확인** — Run: `uv run python -m pytest -q` → 전체 통과. Run: `uv run python -m pytest -m winlive tests/test_eventlog.py -v` → 통과. ruff·mypy 0건.

- [ ] **Step 5: Commit** — `git commit -m "feat: event log subscriptions with XML parsing, JSON bookmarks and per-channel status"`

---

### Task 8: 세션 이벤트 로그 매핑 (LSM·RCM·Security, 로그인 실패, 잠금)

**Files:**
- Create: `server/app/sessions/eventmap.py`, `server/tests/test_session_eventmap.py`
- Modify: `server/app/services.py` (핸들러 등록: `eventlog:security`, `eventlog:lsm`, `eventlog:rcm`)

**Interfaces:**
- Consumes: Task 7 `EventRecord`, `EventLogComponent.on`; Task 4 `SessionHistory.add_failure`, `LogonFailureIn`.
- Produces:
  - `SESSION_EVENT_NAMES = {21: "lsm_logon", 22: "lsm_shell_start", 23: "lsm_logoff", 24: "lsm_disconnect", 25: "lsm_reconnect", 1149: "rdp_auth_ok", 4624: "logon", 4625: "logon_failed", 4634: "logoff", 4647: "user_logoff", 4778: "session_reconnect", 4779: "session_disconnect", 4800: "lock", 4801: "unlock"}`
  - `@dataclass(frozen=True) SessionLogEvent(name: str, at: datetime, fields: dict[str, Any], failure: LogonFailureIn | None)`
  - `map_session_record(r: EventRecord) -> SessionLogEvent | None` — 필드(`None`·`"-"`·빈 값은 `None`):
    - LSM 21/22/25: `user`(`User` 그대로, 예 `CORP\hong`), `session_id`(int), `client_ip`(`Address`; `LOCAL` → None). 23: `user`, `session_id`. 24: `user`, `session_id`, `client_ip`.
    - RCM 1149: `user` = `Param2\Param1`(Param2가 비면 Param1), `client_ip` = `Param3`.
    - 4624: `LogonType`이 10·7일 때만, `TargetUserName`이 `$`로 끝나거나 `TargetUserSid`가 `S-1-5-18`/`19`/`20`이면 None. `user` = `TargetDomainName\TargetUserName`, `client_ip` = `IpAddress`, `workstation` = `WorkstationName`, `logon_type`(int), `logon_id` = `TargetLogonId`.
    - 4625: 모든 로그온 유형. `user`, `client_ip`, `workstation`, `logon_type`, `status` = `Status`, `sub_status` = `SubStatus` → `failure = LogonFailureIn(at, TargetUserName, TargetDomainName, client_ip, workstation, logon_type, status, sub_status, "eventlog:4625", record_id)`.
    - 4634: `LogonType` 10·7만, `user`, `logon_type`, `logon_id`. 4647: `user`, `logon_id`.
    - 4778/4779: `user` = `AccountDomain\AccountName`, `client_name` = `ClientName`, `client_ip` = `ClientAddress`, `session_name` = `SessionName`, `logon_id` = `LogonID`.
    - 4800/4801: `user` = `TargetDomainName\TargetUserName`, `session_id` = `SessionId`(int).
    - 그 밖 ID·채널 → None.
  - `class SessionEventHandler(history: SessionHistory, log: LogWriter)`: `__call__(records: list[EventRecord])` — 매핑된 것마다 `log.emit("session", at=ev.at, event=ev.name, event_id=r.event_id, record_id=r.record_id, source=f"eventlog:{r.event_id}", **ev.fields)`, `failure`가 있으면 `history.add_failure`. `build_services`가 `eventlog`가 있을 때 세 채널에 등록합니다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_session_eventmap.py
from datetime import UTC, datetime, timedelta

import pytest

from app.sessions.eventmap import SessionEventHandler, map_session_record
from app.win.eventlog import parse_event_xml
from tests.eventlog_helpers import evt_xml
from tests.test_auth_api import audit_events

SEC = "Security"; LSM = "Microsoft-Windows-TerminalServices-LocalSessionManager/Operational"
RCM = "Microsoft-Windows-TerminalServices-RemoteConnectionManager/Operational"

def rec(channel, eid, data=None, user_data=None, rid=1, time="2026-11-04T04:59:30Z"):
    return parse_event_xml(evt_xml(channel, eid, rid, time, data=data, user_data=user_data))

@pytest.mark.parametrize("record,name,fields", [
    (rec(LSM, 21, user_data=("EventXML", {"User": "CORP\\hong", "SessionID": "2", "Address": "10.0.3.21"})), "lsm_logon",
     {"user": "CORP\\hong", "session_id": 2, "client_ip": "10.0.3.21"}),
    (rec(LSM, 24, user_data=("EventXML", {"User": "CORP\\hong", "SessionID": "2", "Address": "LOCAL"})), "lsm_disconnect",
     {"user": "CORP\\hong", "session_id": 2, "client_ip": None}),
    (rec(RCM, 1149, user_data=("EventXML", {"Param1": "hong", "Param2": "CORP", "Param3": "10.0.3.21"})), "rdp_auth_ok",
     {"user": "CORP\\hong", "client_ip": "10.0.3.21"}),
    (rec(SEC, 4624, {"TargetUserName": "hong", "TargetDomainName": "CORP", "TargetUserSid": "S-1-5-21-1-2-3-1001", "LogonType": "10",
                     "IpAddress": "10.0.3.21", "WorkstationName": "HONG-LAPTOP", "TargetLogonId": "0x3e7a1"}), "logon",
     {"user": "CORP\\hong", "client_ip": "10.0.3.21", "workstation": "HONG-LAPTOP", "logon_type": 10, "logon_id": "0x3e7a1"}),
    (rec(SEC, 4778, {"AccountName": "hong", "AccountDomain": "CORP", "LogonID": "0x3e7a1", "SessionName": "RDP-Tcp#3",
                     "ClientName": "HONG-LAPTOP", "ClientAddress": "10.0.3.21"}), "session_reconnect",
     {"user": "CORP\\hong", "client_name": "HONG-LAPTOP", "client_ip": "10.0.3.21", "session_name": "RDP-Tcp#3", "logon_id": "0x3e7a1"}),
    (rec(SEC, 4800, {"TargetUserName": "hong", "TargetDomainName": "CORP", "SessionId": "2"}), "lock",
     {"user": "CORP\\hong", "session_id": 2}),
])
def test_maps_session_records(record, name, fields):
    ev = map_session_record(record)
    assert (ev.name, ev.fields, ev.failure, ev.at) == (name, fields, None, datetime(2026, 11, 4, 4, 59, 30, tzinfo=UTC))

@pytest.mark.parametrize("data", [
    {"TargetUserName": "svc", "TargetDomainName": "CORP", "TargetUserSid": "S-1-5-21-1", "LogonType": "3", "IpAddress": "-"},
    {"TargetUserName": "MCP-HOST$", "TargetDomainName": "CORP", "TargetUserSid": "S-1-5-21-2", "LogonType": "10"},
    {"TargetUserName": "SYSTEM", "TargetDomainName": "NT AUTHORITY", "TargetUserSid": "S-1-5-18", "LogonType": "7"},
])
def test_drops_noise_logons(data):
    assert map_session_record(rec(SEC, 4624, data)) is None

def test_unknown_ids_are_ignored():
    assert map_session_record(rec(SEC, 4720, {"TargetUserName": "x"})) is None

async def test_failures_are_stored_and_logged_with_event_time(services, clock):
    r = rec(SEC, 4625, {"TargetUserName": "hong", "TargetDomainName": "CORP", "LogonType": "3", "IpAddress": "203.0.113.9",
                        "WorkstationName": "EVIL", "Status": "0xc000006d", "SubStatus": "0xc000006a"}, rid=77)
    h = SessionEventHandler(services.session_history, services.log)
    h([r, r])  # a duplicate record id is stored once
    [f] = services.session_history.failures(clock.now() - timedelta(days=1))
    assert (f.user, f.domain, f.client_ip, f.workstation, f.logon_type, f.status, f.sub_status, f.source, f.record_id) == \
        ("hong", "CORP", "203.0.113.9", "EVIL", 3, "0xc000006d", "0xc000006a", "eventlog:4625", 77)
    lines = [e for e in await audit_events(services, "session") if e["event"] == "logon_failed"]
    assert lines[0]["ts"] == "2026-11-04T13:59:30.000+09:00" and lines[0]["source"] == "eventlog:4625"

async def test_session_events_use_event_time(services):
    h = SessionEventHandler(services.session_history, services.log)
    h([rec(LSM, 25, user_data=("EventXML", {"User": "CORP\\hong", "SessionID": "2", "Address": "10.0.3.21"}),
           time="2026-11-03T14:59:59.9Z")])
    await services.log.flush()
    day = (services.paths.logs_dir / "2026-11-03.jsonl").read_text("utf-8")
    assert '"event": "lsm_reconnect"' in day and '"ts": "2026-11-03T23:59:59.900+09:00"' in day
```

- [ ] **Step 2: 실패 확인** — Run: `uv run python -m pytest tests/test_session_eventmap.py -v` → FAIL

- [ ] **Step 3: 구현** — 위 Interfaces대로.

- [ ] **Step 4: 통과 확인** — Run: `uv run python -m pytest -q` → 전체 통과. ruff·mypy 0건.

- [ ] **Step 5: Commit** — `git commit -m "feat: map RDP session event-log records to session logs and logon-failure history"`

---

### Task 9: 프로세스 수집 (WMI)과 활동 맥락

**Files:**
- Create: `server/app/win/wmi.py`, `server/app/activity/context.py`, `server/app/activity/process.py`
- Create: `server/tests/test_wmi_mapping.py`, `server/tests/test_activity_process.py`
- Modify: `server/app/collect/config.py` (`process`, `activity`), `server/app/collect/cli.py` (`--activity on|off`), `server/app/services.py` (`activity_context`), `server/tests/winfakes.py` (`FakeProcessSource`, `FakeLookup`)

**Interfaces:**
- Produces (`app.win.wmi`):
  - `@dataclass(frozen=True) ProcessEvent(kind: Literal["start", "stop"], at: datetime, pid: int, ppid: int | None, name: str, exe: str | None, cmdline: str | None, session_id: int | None, user: str | None, exit_code: int | None, source: Literal["wmi:trace", "wmi:poll"])`
  - `class ProcessLookup(Protocol): def details(self, pid: int) -> tuple[str | None, str | None, str | None]` → (exe, cmdline, user). `PsutilProcessLookup`: `psutil.Process(pid)`의 `exe()`, `subprocess.list2cmdline(cmdline())`, `username()`; 각각 `AccessDenied`/`NoSuchProcess`/`ZombieProcess` → None.
  - `from_start_trace(props: Mapping[str, Any], lookup: ProcessLookup) -> ProcessEvent`(`ProcessID`, `ParentProcessID`, `ProcessName`, `SessionID`, `TIME_CREATED` → `filetime_to_dt(int(...))`, exe·cmdline·user는 `lookup`), `from_stop_trace(props) -> ProcessEvent`(`ExitStatus` → `exit_code`, lookup 없음), `from_instance_event(kind, event_props: Mapping, target: Mapping, lookup: ProcessLookup | None) -> ProcessEvent`(`target`의 `ProcessId`, `ParentProcessId`, `Name`, `ExecutablePath`, `CommandLine`, `SessionId`; `at`은 `event_props["TIME_CREATED"]`; start일 때만 `user`를 lookup).
  - `class ProcessWatch(Protocol)`: `mode: Literal["trace", "poll"]`, `def next(self, timeout_ms: int) -> ProcessEvent | None`, `def close(self) -> None`.
  - `class ProcessEventSource(Protocol): def watch(self, kind: Literal["start", "stop"]) -> ProcessWatch`
  - `class WmiProcessSource(lookup: ProcessLookup | None = None)`: 호출한 스레드에서 `pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)`, 모니커 `r"winmgmts:{impersonationLevel=impersonate}!\\.\root\cimv2"`(소스 파일에 그대로 — 셸 heredoc으로 쓰면 역슬래시가 줄어드니 편집 도구로 씁니다), 먼저 `SELECT * FROM Win32_ProcessStartTrace`(stop은 `StopTrace`), `com_error`의 `excepinfo[5] == -2147217405`(0x80041003 접근 거부)면 `SELECT * FROM __InstanceCreationEvent WITHIN 1 WHERE TargetInstance ISA 'Win32_Process'`(stop은 `__InstanceDeletionEvent`)로 바꿉니다(V13). `next`: `NextEvent(timeout_ms)`, `excepinfo[5] == -2147209215`(0x80043001 시간 초과) → None. 속성은 `{p.Name: p.Value for p in ev.Properties_}`, `TargetInstance`도 같은 방식.
- Produces (`app.activity.context`):
  - `class ActivityContext(tracker: SessionTracker, clock: Clock, *, pid_session: Callable[[int], int | None] = process_session_id, ttl_sec: float = 300, max_pids: int = 50_000)` (루프 스레드):
    - `remember(pid: int, session_id: int | None, name: str | None, at: datetime) -> None`(LRU, 가득 차면 가장 오래된 것 제거)
    - `session_of(pid: int | None, *, user: str | None = None, domain: str | None = None) -> int | None`: ① 캐시(`ttl_sec` 이내) ② `pid_session(pid)` ③ `tracker.by_user(user, domain)` ④ None.
    - `fields(session_id: int | None, *, user: str | None = None) -> dict[str, Any]` = `{"session_id", "user", "client_ip", "client_name"}` — 트래커에 그 세션이 있으면 `ctx.account`·`client_ip`·`client_name`, 없으면 `user`(인자)와 None들.
- Produces (`app.activity.process`):
  - `class ProcessActivityHandler(context: ActivityContext, log: LogWriter)`: `__call__(events: list[ProcessEvent])` — `session_id`가 None이면 `context.session_of(pid)`, start면 `context.remember`. 세션 0은 기록하지 않습니다(V13). 줄: `log.emit("activity.process", at=ev.at, event=ev.kind, pid, ppid, name, exe, cmdline, exit_code, source, **context.fields(session, user=ev.user))`(start에는 `exit_code` 없음, stop에는 `exe`/`cmdline` 없음 — 값이 None인 키는 넣지 않습니다).
  - `class ProcessComponent(source: ProcessEventSource, handler: ProcessActivityHandler, collectors: Collectors)`: `name = "wmi"`; start/stop 감시 스레드 2개(`wmi:start`, `wmi:stop`), 첫 `watch` 성공 때 `collectors.report(name, True)` + `system` `collector.mode {source, mode}`(루프 쪽에서), 실패 → `report(name, False, repr(exc))`, 60초 뒤 재시도.
  - `CollectorConfig.process: ProcessEventSource | None = None`, `activity: bool = True`. `--activity on|off`(기본 on): on이고 `--session-source wts`이면 `WmiProcessSource()`; off면 `process=None`이고 Task 10의 명령 핸들러도 등록하지 않습니다.
  - `Services.activity_context: ActivityContext`.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_wmi_mapping.py
import subprocess
from datetime import UTC, datetime

import pytest

from app.win.ffi import current_session_id
from app.win.wmi import WmiProcessSource, from_instance_event, from_start_trace, from_stop_trace
from tests.winfakes import FakeLookup

FT = 134382420000000000  # 2026-11-04T05:00:00Z

def test_start_trace_uses_lookup_for_details():
    lk = FakeLookup({8812: (r"C:\Windows\System32\notepad.exe", "notepad.exe a.txt", "CORP\\hong")})
    ev = from_start_trace({"ProcessID": 8812, "ParentProcessID": 4100, "ProcessName": "notepad.exe", "SessionID": 2, "TIME_CREATED": str(FT)}, lk)
    assert (ev.kind, ev.at, ev.pid, ev.ppid, ev.name, ev.exe, ev.cmdline, ev.session_id, ev.user, ev.source) == \
        ("start", datetime(2026, 11, 4, 5, 0, tzinfo=UTC), 8812, 4100, "notepad.exe", r"C:\Windows\System32\notepad.exe",
         "notepad.exe a.txt", 2, "CORP\\hong", "wmi:trace")

def test_stop_trace_has_exit_code_and_no_lookup():
    ev = from_stop_trace({"ProcessID": 8812, "ParentProcessID": 4100, "ProcessName": "notepad.exe", "SessionID": 2, "TIME_CREATED": FT, "ExitStatus": 1})
    assert (ev.kind, ev.exit_code, ev.exe, ev.cmdline, ev.source) == ("stop", 1, None, None, "wmi:trace")

def test_instance_event_reads_target_instance():
    ev = from_instance_event("start", {"TIME_CREATED": FT}, {"ProcessId": 77, "ParentProcessId": 1, "Name": "PING.EXE",
        "ExecutablePath": r"C:\Windows\System32\PING.EXE", "CommandLine": "ping -n 3 127.0.0.1", "SessionId": 1},
        FakeLookup({77: (None, None, "CORP\\hong")}))
    assert (ev.pid, ev.cmdline, ev.session_id, ev.user, ev.source) == (77, "ping -n 3 127.0.0.1", 1, "CORP\\hong", "wmi:poll")

@pytest.mark.winlive
def test_wmi_source_sees_a_new_process():
    w = WmiProcessSource().watch("start")
    try:
        p = subprocess.Popen(["ping", "-n", "3", "127.0.0.1"], stdout=subprocess.DEVNULL)
        found = None
        for _ in range(8):
            ev = w.next(1000)
            if ev is not None and ev.pid == p.pid:
                found = ev; break
        p.wait()
    finally:
        w.close()
    assert found is not None and "ping" in (found.cmdline or "").lower() and found.session_id == current_session_id()
    assert w.mode in ("trace", "poll")
```

```python
# server/tests/test_activity_process.py
from datetime import timedelta

from app.activity.context import ActivityContext
from app.activity.process import ProcessActivityHandler
from app.win.wmi import ProcessEvent
from tests.session_helpers import snap, ws
from tests.test_auth_api import audit_events

def pev(kind="start", pid=8812, session=2, **kw):
    base = dict(kind=kind, at=kw.pop("at", None), pid=pid, ppid=4100, name="notepad.exe", exe=r"C:\Windows\notepad.exe",
                cmdline="notepad.exe a.txt", session_id=session, user="CORP\\hong", exit_code=None, source="wmi:poll")
    base.update(kw); return ProcessEvent(**base)

async def test_context_resolution_order(services, clock):
    services.sessions.apply(snap(clock.now(), ws(2), ws(3, user="kim")))
    ctx = ActivityContext(services.sessions, clock, pid_session=lambda pid: {500: 3}.get(pid))
    ctx.remember(100, 2, "a.exe", clock.now())
    assert ctx.session_of(100) == 2 and ctx.session_of(500) == 3
    assert ctx.session_of(999, user="KIM", domain="CORP") == 3 and ctx.session_of(999) is None
    clock.advance(301); assert ctx.session_of(100) is None
    assert ctx.fields(2) == {"session_id": 2, "user": "CORP\\hong", "client_ip": "10.0.3.21", "client_name": "HONG-LAPTOP"}
    assert ctx.fields(None, user="X\\y") == {"session_id": None, "user": "X\\y", "client_ip": None, "client_name": None}

async def test_handler_logs_user_sessions_with_event_time(services, clock):
    services.sessions.apply(snap(clock.now(), ws(2)))
    h = ProcessActivityHandler(ActivityContext(services.sessions, clock), services.log)
    at = clock.now() - timedelta(seconds=2)
    h([pev(at=at), pev(pid=9, session=0, at=at), pev("stop", at=clock.now(), exit_code=0, exe=None, cmdline=None)])
    lines = await audit_events(services, "activity.process")
    assert [(e["event"], e["pid"]) for e in lines] == [("start", 8812), ("stop", 8812)]
    s = lines[0]
    assert (s["ts"], s["cmdline"], s["session_id"], s["user"], s["client_ip"], s["source"]) == \
        ("2026-11-04T13:59:58.000+09:00", "notepad.exe a.txt", 2, "CORP\\hong", "10.0.3.21", "wmi:poll")
    assert "exit_code" not in s and lines[1]["exit_code"] == 0 and "cmdline" not in lines[1]

async def test_handler_resolves_missing_session_and_remembers(services, clock):
    services.sessions.apply(snap(clock.now(), ws(2)))
    ctx = ActivityContext(services.sessions, clock, pid_session=lambda pid: 2)
    ProcessActivityHandler(ctx, services.log)([pev(session=None, at=clock.now())])
    assert ctx.session_of(8812) == 2 and (await audit_events(services, "activity.process"))[0]["session_id"] == 2

async def test_component_reports_mode_and_delivers(services, clock):
    services.sessions.apply(snap(clock.now(), ws(2)))
    src = FakeProcessSource(start=[pev(at=clock.now())], mode="poll")
    comp = ProcessComponent(src, ProcessActivityHandler(ActivityContext(services.sessions, clock), services.log), services.collectors)
    services.collectors.add(comp); await services.collectors.start()
    try:
        await eventually(lambda: services.collectors.status() and services.collectors.status()[0].ok)
        await services.log.flush()
        await eventually(lambda: (services.paths.logs_dir / "2026-11-04.jsonl").exists()
                         and '"cat": "activity.process"' in (services.paths.logs_dir / "2026-11-04.jsonl").read_text("utf-8"))
    finally:
        await services.collectors.stop()
    modes = [e for e in await audit_events(services, "system") if e.get("event") == "collector.mode"]
    assert {(e["source"], e["mode"]) for e in modes} == {("wmi:start", "poll"), ("wmi:stop", "poll")}
    assert len(await audit_events(services, "activity.process")) == 1
```

`test_activity_process.py` 맨 위 import에 `from app.activity.process import ProcessComponent`와 `from tests.winfakes import FakeProcessSource, eventually`를 더합니다. `FakeProcessSource(start: list[ProcessEvent] = (), stop: list[ProcessEvent] = (), mode: str = "poll")`: `watch(kind)`가 그 목록을 하나씩 `next`로 돌려주고 다 쓰면 `None`(10ms 대기)을 돌려주는 `ProcessWatch`를 만듭니다. `FakeLookup(table: dict[int, tuple[str | None, str | None, str | None]])`: 없는 pid → `(None, None, None)`.

- [ ] **Step 2: 실패 확인** — Run: `uv run python -m pytest tests/test_wmi_mapping.py tests/test_activity_process.py -v` → FAIL

- [ ] **Step 3: 구현** — 위 Interfaces대로.

- [ ] **Step 4: 통과 확인** — Run: `uv run python -m pytest -q` → 전체 통과. Run: `uv run python -m pytest -m winlive tests/test_wmi_mapping.py -v` → 통과(이 PC는 `poll` 모드). ruff·mypy 0건.

- [ ] **Step 5: Commit** — `git commit -m "feat: WMI process start/stop collection with trace-or-poll fallback and session-aware activity context"`

---
### Task 10: 명령 수집 (Security 4688, PowerShell 4104)

**Files:**
- Create: `server/app/activity/powershell.py`, `server/tests/test_activity_commands.py`
- Modify: `server/app/activity/process.py` (`map_4688`, `CommandHandler`), `server/app/services.py` (핸들러 등록 `eventlog:security`·`eventlog:powershell`·`eventlog:pwsh`, `collectors.add_task("powershell-expire", ...)`)

**Interfaces:**
- Consumes: Task 7 `EventRecord`, `sid_to_account`; Task 9 `ActivityContext`.
- Produces:
  - `SHELLS = {"cmd.exe": "cmd", "powershell.exe": "powershell", "powershell_ise.exe": "powershell", "pwsh.exe": "pwsh"}`, `IGNORED_CHILDREN = frozenset({"conhost.exe"})`, `SYSTEM_SIDS = frozenset({"S-1-5-18", "S-1-5-19", "S-1-5-20"})`
  - `@dataclass(frozen=True) CommandRecord(at: datetime, pid: int, ppid: int | None, exe: str, cmdline: str | None, parent_exe: str | None, shell: str | None, parent_shell: str | None, user: str | None, domain: str | None, record_id: int)`
  - `map_4688(r: EventRecord) -> CommandRecord | None`: Security 4688만. `SubjectUserSid` ∈ `SYSTEM_SIDS` → None. `NewProcessId`·`ProcessId`는 16진(`int(x, 16)`). 기본 이름은 `ntpath.basename(...).lower()`. 자식이 `IGNORED_CHILDREN` → None. 자식도 부모도 `SHELLS`가 아니면 None(cmd 내부 명령은 원래 4688이 안 생깁니다; §2 #7). `shell` = `SHELLS.get(자식)`, `parent_shell` = `SHELLS.get(부모)`, `cmdline` = `CommandLine`(정책이 꺼져 비어 있으면 None).
  - `class CommandHandler(context: ActivityContext, log: LogWriter)`: `__call__(records)` — 4688만 골라 `log.emit("activity.command", at=c.at, event="process_cmdline", shell, parent_shell, pid, ppid, exe, parent_exe, cmdline, source="eventlog:4688", record_id, **context.fields(context.session_of(c.pid, user=c.user, domain=c.domain), user=f"{c.domain}\\{c.user}"))`. `remember(pid, session, basename, at)`도 합니다.
  - `app.activity.powershell`:
    - `@dataclass(frozen=True) ScriptBlock(at: datetime, shell: Literal["powershell", "pwsh"], script_block_id: str, text: str, path: str | None, parts: int, total: int, truncated: bool, incomplete: bool, pid: int | None, user_sid: str | None, record_id: int)`
    - `class ScriptBlockAssembler(*, max_wait_sec: float = 5.0, max_chars: int = 65_536)`: `add(r: EventRecord, now: datetime) -> list[ScriptBlock]` — `MessageNumber`/`MessageTotal`(없으면 1/1)로 `(channel, ScriptBlockId)`별 조각을 모으고, 다 모이면 `MessageNumber` 순으로 이어 한 블록을 돌려줍니다. `user_sid` ∈ `SYSTEM_SIDS` → 버림(빈 목록). `expire(now) -> list[ScriptBlock]` — 첫 조각부터 `max_wait_sec`가 지난 미완성은 있는 조각만 이어 `incomplete=True`. 텍스트는 코드 포인트 `max_chars`에서 자르고 `truncated=True`. `at`·`pid`·`record_id`는 첫 조각 것. `shell`은 채널이 `PowerShellCore/Operational`이면 `pwsh`, 아니면 `powershell`.
    - `class PowerShellHandler(context: ActivityContext, log: LogWriter, clock: Clock, *, sid_to_account: Callable[[str], str | None] = accounts.sid_to_account, assembler: ScriptBlockAssembler | None = None)`: `__call__(records)`(`add`), `tick()`(`expire(clock.now())`) — 블록마다 `log.emit("activity.command", at=b.at, event="script_block", shell, text, script_block_id, path, parts, truncated, incomplete, pid, source="eventlog:4104", record_id, **context.fields(context.session_of(b.pid), user=sid_to_account(b.user_sid) if b.user_sid else None))`. `build_services`가 1초마다 `tick`을 부르는 태스크를 `collectors.add_task`로 등록합니다(`activity`가 켜져 있고 `eventlog`가 있을 때만).

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_activity_commands.py
from datetime import UTC, datetime, timedelta

import pytest

from app.activity.context import ActivityContext
from app.activity.powershell import PowerShellHandler, ScriptBlockAssembler
from app.activity.process import CommandHandler, map_4688
from app.win.eventlog import parse_event_xml
from tests.eventlog_helpers import evt_xml
from tests.session_helpers import snap, ws
from tests.test_auth_api import audit_events

USER = {"SubjectUserSid": "S-1-5-21-1-2-3-1001", "SubjectUserName": "hong", "SubjectDomainName": "CORP"}

def r4688(child, parent, cmd, rid=1, sid=None, pid="0x2274", ppid="0x1a2c"):
    data = {**USER, "NewProcessId": pid, "NewProcessName": child, "ProcessId": ppid, "CommandLine": cmd, "ParentProcessName": parent}
    if sid:
        data["SubjectUserSid"] = sid
    return parse_event_xml(evt_xml("Security", 4688, rid, "2026-11-04T04:59:00Z", data=data))

@pytest.mark.parametrize("child,parent,cmd,expect", [
    (r"C:\Windows\System32\cmd.exe", r"C:\Windows\explorer.exe", "cmd.exe /c deploy.bat", ("cmd", None)),
    (r"C:\Windows\System32\PING.EXE", r"C:\Windows\System32\cmd.exe", "ping -n 1 10.0.0.1", (None, "cmd")),
    (r"C:\Program Files\PowerShell\7\pwsh.exe", r"C:\Windows\explorer.exe", "pwsh -NoLogo", ("pwsh", None)),
    (r"C:\Windows\System32\conhost.exe", r"C:\Windows\System32\cmd.exe", r"\??\C:\Windows\system32\conhost.exe 0xffffffff", None),
    (r"C:\Windows\System32\notepad.exe", r"C:\Windows\explorer.exe", "notepad.exe", None),
])
def test_map_4688_keeps_only_shell_related_processes(child, parent, cmd, expect):
    c = map_4688(r4688(child, parent, cmd))
    if expect is None:
        assert c is None
    else:
        assert (c.shell, c.parent_shell, c.cmdline, c.pid, c.ppid, c.user, c.domain) == (*expect, cmd, 0x2274, 0x1A2C, "hong", "CORP")

def test_map_4688_skips_system_and_keeps_empty_cmdline_as_none():
    assert map_4688(r4688(r"C:\Windows\System32\cmd.exe", r"C:\x\svc.exe", "cmd /c x", sid="S-1-5-18")) is None
    assert map_4688(r4688(r"C:\Windows\System32\cmd.exe", r"C:\Windows\explorer.exe", "")).cmdline is None

async def test_command_handler_enriches_with_session_and_event_time(services, clock):
    services.sessions.apply(snap(clock.now(), ws(2)))
    ctx = ActivityContext(services.sessions, clock, pid_session=lambda pid: None)
    CommandHandler(ctx, services.log)([r4688(r"C:\Windows\System32\cmd.exe", r"C:\Windows\explorer.exe", "cmd.exe /c deploy.bat", rid=9)])
    [e] = await audit_events(services, "activity.command")
    assert (e["ts"], e["event"], e["shell"], e["cmdline"], e["session_id"], e["user"], e["client_ip"], e["source"], e["record_id"]) == \
        ("2026-11-04T13:59:00.000+09:00", "process_cmdline", "cmd", "cmd.exe /c deploy.bat", 2, "CORP\\hong", "10.0.3.21", "eventlog:4688", 9)

PS = "Microsoft-Windows-PowerShell/Operational"
NOW = datetime(2026, 11, 4, 5, 0, tzinfo=UTC)

def r4104(text, n=1, total=1, sbid="{aaaa}", rid=1, channel=PS, sid="S-1-5-21-1-2-3-1001"):
    return parse_event_xml(evt_xml(channel, 4104, rid, "2026-11-04T04:59:50Z", provider="Microsoft-Windows-PowerShell",
        data={"MessageNumber": str(n), "MessageTotal": str(total), "ScriptBlockText": text, "ScriptBlockId": sbid, "Path": ""},
        pid=6000, user_sid=sid))

def test_script_block_single_part_and_system_skip():
    a = ScriptBlockAssembler()
    [b] = a.add(r4104("Get-Process | Stop-Process -Name notepad"), NOW)
    assert (b.shell, b.text, b.parts, b.total, b.truncated, b.incomplete, b.pid, b.path) == \
        ("powershell", "Get-Process | Stop-Process -Name notepad", 1, 1, False, False, 6000, None)
    assert a.add(r4104("x", sid="S-1-5-18", sbid="{bbbb}"), NOW) == []

def test_script_block_multi_part_in_order():
    a = ScriptBlockAssembler()
    assert a.add(r4104("world", n=2, total=2, rid=2), NOW) == []
    [b] = a.add(r4104("hello ", n=1, total=2, rid=1), NOW)
    assert (b.text, b.parts, b.total) == ("hello world", 2, 2)

def test_script_block_incomplete_after_timeout_and_truncated():
    a = ScriptBlockAssembler(max_wait_sec=5, max_chars=4)
    assert a.add(r4104("abc", n=1, total=3), NOW) == [] and a.expire(NOW + timedelta(seconds=4)) == []
    [b] = a.expire(NOW + timedelta(seconds=5))
    assert (b.text, b.incomplete, b.parts, b.total) == ("abc", True, 1, 3)
    [t] = a.add(r4104("가나다라마바", sbid="{cccc}"), NOW)
    assert (t.text, t.truncated) == ("가나다라", True)

def test_pwsh_channel_shell_name():
    [b] = ScriptBlockAssembler().add(r4104("1+1", channel="PowerShellCore/Operational"), NOW)
    assert b.shell == "pwsh"

async def test_powershell_handler_logs_with_account_and_event_time(services, clock):
    services.sessions.apply(snap(clock.now(), ws(2)))
    h = PowerShellHandler(ActivityContext(services.sessions, clock, pid_session=lambda pid: 2), services.log, clock,
                          sid_to_account=lambda sid: "CORP\\hong")
    h([r4104("Get-ChildItem", rid=31)]); h.tick()
    [e] = await audit_events(services, "activity.command")
    assert (e["ts"], e["event"], e["shell"], e["text"], e["session_id"], e["user"], e["source"], e["record_id"]) == \
        ("2026-11-04T13:59:50.000+09:00", "script_block", "powershell", "Get-ChildItem", 2, "CORP\\hong", "eventlog:4104", 31)
```

- [ ] **Step 2: 실패 확인** — Run: `uv run python -m pytest tests/test_activity_commands.py -v` → FAIL

- [ ] **Step 3: 구현** — 위 Interfaces대로. `evt_xml`의 `user_sid`는 `System/Security@UserID`, `pid`는 `Execution@ProcessID`로 들어갑니다(Task 7 헬퍼).

- [ ] **Step 4: 통과 확인** — Run: `uv run python -m pytest -q` → 전체 통과. ruff·mypy 0건.

- [ ] **Step 5: Commit** — `git commit -m "feat: collect shell command lines from 4688 and PowerShell script blocks from 4104"`

---

### Task 11: 고지 표시 — 서버 측 (표시 건, 토큰, 열기·확인 API, 마이그레이션 7)

**Files:**
- Create: `server/app/notice/displays.py`, `server/app/web/notice_display_api.py`, `server/tests/test_notice_displays.py`, `server/tests/test_notice_display_api.py`
- Modify: `server/app/db.py` (마이그레이션 7), `server/app/services.py` (`displays`, 트래커 리스너), `server/app/web/app_factory.py` (Local만), `server/app/web/sessions_api.py` (`notice`), `server/tests/test_channels.py` (`_local_only_routes`), `server/tests/test_db.py`
- Modify (tests): `server/tests/test_session_tracker.py` — `test_board_sessions_shape`의 기대값 `"notice_acknowledged": None` → `False`(이제 연결이 열리면 표시 건이 생기므로). `server/tests/test_sessions_api.py::test_history_requires_login_and_paginates` — `c["notice"]`가 None이 아니라 `closed_reason == "logoff"`인 객체가 되도록 단언을 `assert (c["kind"], c["end_reason"], c["notice"]["closed_reason"]) == ("logon", "logoff", "logoff")`로 바꿉니다. 그 밖의 Task 4·5 테스트는 그대로 통과해야 합니다(`set_notice_state`의 게시는 마지막 게시와 같으면 생략되므로 `test_publishes_sessions_only_on_visible_change`도 그대로).

**Interfaces:**
- Consumes: Task 4 `Connection`, `Opened`, `Closed`, `SessionTracker.set_notice_state`; Plan 3 `NoticeStore.current()/version(v)`; Task 6 `TamperMonitor`; Task 2 `peer_of`.
- Produces:
  - 마이그레이션 7:
    ```sql
    CREATE TABLE notice_displays (
        id INTEGER PRIMARY KEY,
        connection_id INTEGER NOT NULL REFERENCES rdp_connections(id) ON DELETE CASCADE,
        session_id INTEGER NOT NULL,
        user TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('logon','reconnect','existing')),
        version INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        first_shown_at TEXT,
        last_shown_at TEXT,
        acknowledged_at TEXT,
        ack_ms INTEGER,
        closed_reason TEXT CHECK (closed_reason IN ('acknowledged','superseded','logoff','service_restart'))
    );
    CREATE INDEX idx_notice_displays_connection ON notice_displays(connection_id);
    CREATE INDEX idx_notice_displays_open ON notice_displays(session_id) WHERE closed_reason IS NULL;
    ```
  - `app.notice.displays`:
    - `@dataclass(frozen=True) Display(id, connection_id, session_id, user, kind, version, created_at: datetime, attempts: int, first_shown_at: datetime | None, last_shown_at: datetime | None, acknowledged_at: datetime | None, ack_ms: int | None, closed_reason: str | None)`
    - `@dataclass(frozen=True) Ticket(display_id: int, token: str, attempt: int)`; `class DisplayNotFoundError(Exception)`
    - `class NoticeDisplays(db, clock, log: LogWriter, notice: NoticeStore, tracker: SessionTracker, tamper: TamperMonitor)` (루프 스레드):
      - `start() -> int`: 열린 건 전부 `service_restart`로 닫고 각각 `notice_unacknowledged`(reason `service_restart`).
      - `on_session_change(change)`: `Opened` → `create(change.connection)`; `Closed(reason="logoff")` → `close_pending(session_id, "logoff")`. `disconnect`·`reconnected`는 아무것도 안 합니다(재연결의 `Opened`가 `create`에서 이전 건을 대체).
      - `create(conn: Connection) -> Display`: 같은 세션의 열린 건 → `superseded`로 닫고 `notice_unacknowledged`(reason `superseded`). 새 행(`version = notice.current().version`, Plan 3: 0 = 기본 문구) → `tracker.set_notice_state(conn.id, False)` → 리스너(`"created"`).
      - `pending_for_session(session_id) -> Display | None`, `get(display_id) -> Display | None`, `latest_for_connections(ids: Iterable[int]) -> dict[int, Display]`.
      - `issue(display_id) -> Ticket`: 열린 건만(아니면 `DisplayNotFoundError`). `secrets.token_urlsafe(32)`, 메모리에 `sha256(token) → (display_id, attempt)`; 같은 표시의 이전 토큰은 무효. `attempts += 1`.
      - `open(token: str, peer_session: int | None) -> tuple[Display, NoticeContent]`: 토큰을 모르거나 표시가 닫혔으면 `DisplayNotFoundError`. `peer_session != display.session_id`(None 포함)면 `tamper.report("notice_token_misuse", display_id, session_id, peer_session)` 후 `DisplayNotFoundError`. 그 시도(attempt)에서 처음 열릴 때만 `first_shown_at`(없으면)·`last_shown_at = now`와 `notice` `notice_shown {display_id, connection_id, session_id, user, kind, version, attempt}`. 내용은 `notice.version(display.version).content`(V15: 표시 건에 버전 고정).
      - `acknowledge(token, peer_session) -> Display`: 검증은 `open`과 같음(단 이미 `acknowledged`로 닫힌 표시의 같은 토큰이면 그대로 돌려줌 — 멱등). `ack_ms = round((now − last_shown_at) * 1000)`(열린 적이 없으면 `last_shown_at = now`로 보고 0), `closed_reason = "acknowledged"`, `notice_acknowledged {display_id, connection_id, session_id, user, kind, version, attempt, elapsed_ms}` → `tracker.set_notice_state(conn, True)` → 리스너(`"acknowledged"`).
      - `unacknowledged(display_id: int, reason: Literal["agent_exited", "window_closed"]) -> None`: 열린 건이면 `notice_unacknowledged`만 남기고 열린 채로 둡니다.
      - `close_pending(session_id: int, reason: Literal["logoff"]) -> None`.
      - `add_listener(fn: Callable[[Literal["created", "acknowledged"], Display], None])`.
    - `Services.displays: NoticeDisplays`; `build_services`가 `tracker.add_listener(displays.on_session_change)`를 **다른 세션 리스너보다 먼저** 등록합니다. `SessionsComponent.start`가 `tracker.start()` 다음에 `displays.start()`를 부릅니다.
  - `app.web.notice_display_api.router`(Local만):
    - 공통 의존성 `display_token(request)`: 헤더 `X-Notice-Token`(없으면 404 `not_found`), `Sec-Fetch-Site`가 있고 `same-origin`/`none`이 아니면 403 `forbidden`. `peer = await peer_of(request)`.
    - `POST /api/notice/display/open` → `{"display_id", "version", "title", "body", "button_text"}`; `DisplayNotFoundError` → 404.
    - `POST /api/notice/display/ack` → 204; `DisplayNotFoundError` → 404.
    - CSRF 쿠키 검사는 없습니다(세션 쿠키가 아니라 토큰 헤더 인증; 사용자 정의 헤더가 교차 출처 요청을 preflight로 막음, V16).
  - `sessions_api` 이력: `notice` = 그 연결의 최신 표시 `{"version", "attempts", "first_shown_at", "acknowledged_at", "ack_ms", "closed_reason"}`(시각은 KST) 또는 `None`.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_notice_displays.py
import pytest

from app.notice.content import NoticeContent
from app.notice.displays import DisplayNotFoundError, NoticeDisplays
from tests.session_helpers import T0, snap, ws
from tests.test_auth_api import audit_events

async def notice_events(services):
    return await audit_events(services, "notice")

async def test_create_pins_version_and_marks_board_unacknowledged(services, clock):
    services.notice.save(NoticeContent("안내", "본문", "확인"), None)  # version 1
    [o] = services.sessions.apply(snap(clock.now(), ws(2)))
    d = services.displays.pending_for_session(2)
    assert (d.version, d.kind, d.connection_id, d.attempts, d.closed_reason) == (1, "existing", o.connection.id, 0, None)
    assert services.sessions.board_sessions()[0]["notice_acknowledged"] is False
    services.notice.save(NoticeContent("안내", "바뀐 본문", "확인"), None)  # a later edit does not change this display
    tk = services.displays.issue(d.id)
    assert services.displays.open(tk.token, peer_session=2)[1].body == "본문"

async def test_open_and_ack_flow_logs_and_marks_board(services, clock):
    services.sessions.apply(snap(clock.now(), ws(2)))
    tk = services.displays.issue(services.displays.pending_for_session(2).id)
    services.displays.open(tk.token, peer_session=2)
    services.displays.open(tk.token, peer_session=2)  # a reload of the same attempt logs nothing new
    clock.advance(4.25)
    d = services.displays.acknowledge(tk.token, peer_session=2)
    assert (d.closed_reason, d.ack_ms) == ("acknowledged", 4250)
    ev = await notice_events(services)
    assert [e["event"] for e in ev] == ["notice_shown", "notice_acknowledged"]
    assert (ev[0]["kind"], ev[0]["version"], ev[0]["attempt"], ev[1]["elapsed_ms"]) == ("existing", 0, 1, 4250)
    assert services.sessions.board_sessions()[0]["notice_acknowledged"] is True
    assert services.displays.acknowledge(tk.token, peer_session=2).closed_reason == "acknowledged"
    assert len(await notice_events(services)) == 2

async def test_reconnect_supersedes_pending_display(services, clock):
    t = services.sessions; t.apply(snap(clock.now()))
    t.apply(snap(clock.now(), ws(2, logon=T0, connected=T0)))
    first = services.displays.pending_for_session(2)
    clock.advance(10); t.apply(snap(clock.now(), ws(2, state="disconnected", logon=T0, connected=T0)))
    assert services.displays.pending_for_session(2).id == first.id
    clock.advance(10); t.apply(snap(clock.now(), ws(2, logon=T0, connected=clock.now())))
    second = services.displays.pending_for_session(2)
    assert second.id != first.id and second.kind == "reconnect"
    assert services.displays.get(first.id).closed_reason == "superseded"
    un = [e for e in await notice_events(services) if e["event"] == "notice_unacknowledged"]
    assert [(e["display_id"], e["reason"]) for e in un] == [(first.id, "superseded")]

async def test_wrong_token_or_other_session_is_not_found_and_reported(services, clock):
    services.sessions.apply(snap(clock.now(), ws(2)))
    tk = services.displays.issue(services.displays.pending_for_session(2).id)
    with pytest.raises(DisplayNotFoundError):
        services.displays.open("nope", peer_session=2)
    with pytest.raises(DisplayNotFoundError):
        services.displays.open(tk.token, peer_session=3)
    with pytest.raises(DisplayNotFoundError):
        services.displays.acknowledge(tk.token, peer_session=None)
    misuse = [r for r in services.tamper.recent(10) if r["event"] == "notice_token_misuse"]
    assert [(r["session_id"], r["peer_session"]) for r in misuse] == [(2, None), (2, 3)]

async def test_reissue_invalidates_old_token_and_counts_attempts(services, clock):
    services.sessions.apply(snap(clock.now(), ws(2)))
    d = services.displays.pending_for_session(2)
    old = services.displays.issue(d.id); new = services.displays.issue(d.id)
    assert (old.attempt, new.attempt, services.displays.get(d.id).attempts) == (1, 2, 2)
    with pytest.raises(DisplayNotFoundError):
        services.displays.open(old.token, peer_session=2)
    services.displays.open(new.token, peer_session=2)
    assert (await notice_events(services))[0]["attempt"] == 2

async def test_logoff_and_unacknowledged_reasons(services, clock):
    services.sessions.apply(snap(clock.now(), ws(2)))
    d = services.displays.pending_for_session(2)
    services.displays.unacknowledged(d.id, "window_closed")
    assert services.displays.pending_for_session(2).id == d.id
    services.sessions.apply(snap(clock.now()))  # logoff
    assert services.displays.get(d.id).closed_reason == "logoff" and services.displays.pending_for_session(2) is None
    assert [e["reason"] for e in await notice_events(services) if e["event"] == "notice_unacknowledged"] == ["window_closed", "logoff"]

async def test_start_closes_pending_as_service_restart(services, clock):
    services.sessions.apply(snap(clock.now(), ws(2)))
    d = services.displays.pending_for_session(2)
    again = NoticeDisplays(services.db, clock, services.log, services.notice, services.sessions, services.tamper)
    assert again.start() == 1 and services.displays.get(d.id).closed_reason == "service_restart"
```

```python
# server/tests/test_notice_display_api.py
from app.notice.defaults import DEFAULT_NOTICE
from app.win.peer import PeerInfo
from tests.mcp_helpers import login_as, make_user
from tests.session_helpers import snap, ws
from tests.winfakes import FakePeerResolver

EDGE2 = PeerInfo(100, 2, "CORP\\hong", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")

def ticket(services, clock):
    services.sessions.apply(snap(clock.now(), ws(2)))
    return services.displays.issue(services.displays.pending_for_session(2).id)

async def test_display_api_flow(local_client, services, clock):
    services.peers = FakePeerResolver(EDGE2); tk = ticket(services, clock)
    r = await local_client.post("/api/notice/display/open", headers={"X-Notice-Token": tk.token, "Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 200 and r.json() == {"display_id": tk.display_id, "version": 0, "title": DEFAULT_NOTICE.title,
                                                 "body": DEFAULT_NOTICE.body, "button_text": DEFAULT_NOTICE.button_text}
    assert (await local_client.post("/api/notice/display/ack", headers={"X-Notice-Token": tk.token})).status_code == 204
    assert services.displays.get(tk.display_id).closed_reason == "acknowledged"

async def test_display_api_rejects_missing_or_bad_token(local_client, services, clock):
    services.peers = FakePeerResolver(EDGE2); ticket(services, clock)
    for headers in ({}, {"X-Notice-Token": "bad"}):
        r = await local_client.post("/api/notice/display/open", headers=headers)
        assert (r.status_code, r.json()) == (404, {"error": "not_found"})

async def test_display_api_other_session_404(local_client, services, clock):
    services.peers = FakePeerResolver(PeerInfo(100, 3, "CORP\\kim", "msedge.exe")); tk = ticket(services, clock)
    assert (await local_client.post("/api/notice/display/ack", headers={"X-Notice-Token": tk.token})).status_code == 404
    assert services.displays.get(tk.display_id).closed_reason is None

async def test_cross_site_fetch_is_refused(local_client, services, clock):
    services.peers = FakePeerResolver(EDGE2); tk = ticket(services, clock)
    r = await local_client.post("/api/notice/display/open", headers={"X-Notice-Token": tk.token, "Sec-Fetch-Site": "cross-site"})
    assert (r.status_code, r.json()) == (403, {"error": "forbidden"})

async def test_display_routes_absent_on_external(external_client):
    for path in ("/api/notice/display/open", "/api/notice/display/ack"):
        assert (await external_client.post(path, headers={"X-Notice-Token": "x"})).status_code == 404

async def test_history_includes_notice(external_client, local_client, services, clock):
    services.peers = FakePeerResolver(EDGE2); tk = ticket(services, clock)
    await local_client.post("/api/notice/display/open", headers={"X-Notice-Token": tk.token})
    clock.advance(2); await local_client.post("/api/notice/display/ack", headers={"X-Notice-Token": tk.token})
    login_as(external_client, services, make_user(services, "d@x.com"), "external")
    [c] = (await external_client.get("/api/sessions/history")).json()["connections"]
    assert c["notice"] == {"version": 0, "attempts": 1, "first_shown_at": "2026-11-04T14:00:00.000+09:00",
                           "acknowledged_at": "2026-11-04T14:00:02.000+09:00", "ack_ms": 2000, "closed_reason": "acknowledged"}
```

- [ ] **Step 2: 실패 확인** — Run: `uv run python -m pytest tests/test_notice_displays.py tests/test_notice_display_api.py tests/test_channels.py tests/test_db.py -v` → FAIL

- [ ] **Step 3: 구현** — 위 Interfaces대로. `test_channels.py`의 `_local_only_routes`에 `notice_display_api.router`를 더합니다. `test_db.py` 테이블 목록에 `notice_displays`.

- [ ] **Step 4: 통과 확인** — Run: `uv run python -m pytest -q` → 전체 통과. ruff·mypy 0건.

- [ ] **Step 5: Commit** — `git commit -m "feat: per-connection notice displays with pinned version, per-attempt tokens and local open/ack API"`

---

### Task 12: 에이전트 허브 API (hello·next·heartbeat·events·closed, 사칭 차단)

**Files:**
- Create: `server/app/activity/agent_hub.py`, `server/app/web/agent_api.py`, `server/tests/test_agent_api.py`, `server/tests/fixtures/agent-events.json`
- Modify: `server/app/services.py` (`agents`, 표시 리스너), `server/app/web/app_factory.py` (Local만), `server/tests/test_channels.py`

**Interfaces:**
- Consumes: Task 2 `peer_of`/`PeerInfo`, Task 4 `SessionTracker.context`, Task 6 `TamperMonitor`, Task 9 `ActivityContext.fields`, Task 11 `NoticeDisplays`.
- Produces:
  - `app.activity.agent_hub`:
    - `AGENT_TOKEN_HEADER = "X-Agent-Token"`; `HELLO = {"heartbeat_sec": 5, "events_max": 200, "idle_threshold_sec": 300}`
    - `class AgentAuthError(Exception)`: `status: int`(401/403), `code: str`(`login_required`/`forbidden`)
    - `@dataclass AgentSlot(session_id: int, user: str, token_sha256: str, minted_at: datetime, pid: int | None = None, hello_at: datetime | None = None, last_seen: datetime | None = None, version: str | None = None, commands: deque[dict[str, Any]] = field(default_factory=deque), wake: asyncio.Event = field(default_factory=asyncio.Event))`
    - `class AgentHub(clock, log: LogWriter, tamper: TamperMonitor, tracker: SessionTracker, displays: NoticeDisplays, context: ActivityContext, *, local_base_url: str = "http://127.0.0.1:8700", reshow_delay_sec: float = 1.0)` (루프 스레드):
      - `configure(local_base_url: str)`, `mint(session_id, user) -> str`(새 슬롯; 이전 슬롯·토큰 폐기), `revoke(session_id)`, `slot(session_id) -> AgentSlot | None`.
      - `authenticate(token: str | None, peer: PeerInfo | None) -> AgentSlot`: 토큰 없음·모름 → `AgentAuthError(401, "login_required")`(tamper 없음). 토큰은 맞는데 `peer is None` 또는 `peer.session_id != slot.session_id` → `tamper.report("agent_impersonation", claimed_session=slot.session_id, peer_session=…, peer_pid=…, peer_exe=…, peer_user=…)` + `AgentAuthError(403, "forbidden")`. 성공하면 `last_seen = now`.
      - `hello(slot, *, session_id: int, pid: int, version: str, peer: PeerInfo) -> dict`: `session_id != slot.session_id` 또는 `pid != peer.pid` → 같은 tamper + 403. 기록 후 `show_pending(slot.session_id)` → `HELLO` 반환.
      - `show_pending(session_id) -> bool`: 슬롯이 hello를 했고 열린 표시가 있으면 `displays.issue` → 큐에 같은 `display_id`의 이전 `show_notice`를 지우고 `{"type": "show_notice", "display_id": id, "attempt": n, "url": f"{base}/notice#d={id}&t={token}"}` 추가 → `wake.set()`.
      - `queue(session_id, command)`, `async next(slot, timeout: float) -> dict | None`(큐가 비면 `wake`를 `timeout`까지 기다림).
      - `heartbeat(slot, *, idle_sec: int | None, locked: bool | None)`, `events(slot, events: list[WindowEventIn | IdleEventIn])`(아래), `closed(slot, display_id: int)`: 그 세션의 열린 표시가 이 id면 `displays.unacknowledged(id, "window_closed")` + `loop.call_later(reshow_delay_sec, show_pending, session_id)`; 아니면 무시.
      - 표시 리스너: `"created"` → `show_pending(session_id)`, `"acknowledged"` → `queue(session_id, {"type": "close_notice", "display_id": id})`.
      - `agent_exited(session_id)`: 열린 표시가 있으면 `displays.unacknowledged(id, "agent_exited")`(Task 13이 부름).
  - `app.web.agent_api.router`(Local만; 모든 라우트가 의존성 `agent_slot` = `hub.authenticate(header, await peer_of(request))`, `AgentAuthError` → `ApiError(status, code)`):
    - 모델(모두 `extra="forbid"`): `HelloBody(session_id: int ≥ 0, pid: int ≥ 1, version: str ≤ 40)`, `HeartbeatBody(idle_sec: int ≥ 0 | None, locked: bool | None)`, `WindowEventIn(type: Literal["foreground", "minimize", "restore", "title"], at: AwareDatetime, pid: int ≥ 0, exe: str ≤ 260 | None, title: str ≤ 512)`, `IdleEventIn(type: Literal["idle", "active"], at: AwareDatetime, idle_sec: int ≥ 0)`, `EventsBody(events: list[Annotated[WindowEventIn | IdleEventIn, Field(discriminator="type")]]`, 최대 200개).
    - `POST /api/agent/hello` → 200 `HELLO`; `GET /api/agent/next?timeout=25`(0–30, float) → 200 명령 | 204; `POST /api/agent/heartbeat` → 204; `POST /api/agent/events` → 204; `POST /api/agent/notice/{display_id}/closed`(`Path(ge=1, le=2**63-1)`) → 204.
    - 이벤트 기록: `at`이 `now`와 300초 넘게 다르면 `at = now`, `clock_skew=True`(V28). 창 → `activity.window {event: type, pid, exe, title, source: "agent", **context.fields(slot.session_id)}`, 유휴 → `activity.idle {event: type, idle_sec, source: "agent", **fields}`.
  - `server/tests/fixtures/agent-events.json`: 에이전트가 실제로 보내는 본문의 기준 픽스처(Task 16의 에이전트 테스트가 같은 파일과 비교합니다):
    ```json
    {"events": [
      {"type": "foreground", "at": "2026-11-04T13:59:57.000+09:00", "pid": 4321, "exe": "C:\\Windows\\System32\\notepad.exe", "title": "메모 - 메모장"},
      {"type": "title", "at": "2026-11-04T13:59:58.500+09:00", "pid": 4321, "exe": "C:\\Windows\\System32\\notepad.exe", "title": "*메모 - 메모장"},
      {"type": "minimize", "at": "2026-11-04T13:59:59.000+09:00", "pid": 4321, "exe": "C:\\Windows\\System32\\notepad.exe", "title": "*메모 - 메모장"},
      {"type": "idle", "at": "2026-11-04T14:00:00.000+09:00", "idle_sec": 300}
    ]}
    ```

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_agent_api.py
import asyncio
import json
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from app.clock import to_kst_iso
from app.win.peer import PeerInfo
from tests.session_helpers import snap, ws
from tests.test_auth_api import audit_events
from tests.winfakes import FakePeerResolver

AGENT2 = PeerInfo(500, 2, "CORP\\hong", r"C:\Python315\python.exe")
FIX = Path(__file__).parent / "fixtures" / "agent-events.json"

def H(token):
    return {"X-Agent-Token": token}

@pytest.fixture
def agent(services, clock):
    services.peers = FakePeerResolver(AGENT2)
    services.agents.reshow_delay_sec = 0.01
    services.sessions.apply(snap(clock.now(), ws(2)))
    return services.agents.mint(2, "hong")

async def hello(client, token):
    r = await client.post("/api/agent/hello", json={"session_id": 2, "pid": 500, "version": "0.1.0"}, headers=H(token))
    assert r.status_code == 200
    return r.json()

def token_of(url):
    return parse_qs(urlsplit(url).fragment)["t"][0]

async def test_hello_then_next_delivers_pending_notice(local_client, services, agent):
    assert await hello(local_client, agent) == {"heartbeat_sec": 5, "events_max": 200, "idle_threshold_sec": 300}
    cmd = (await local_client.get("/api/agent/next", params={"timeout": 0}, headers=H(agent))).json()
    d = services.displays.pending_for_session(2)
    assert (cmd["type"], cmd["display_id"], cmd["attempt"]) == ("show_notice", d.id, 1)
    assert cmd["url"].startswith(f"http://127.0.0.1:8700/notice#d={d.id}&t=")
    assert (await local_client.get("/api/agent/next", params={"timeout": 0.05}, headers=H(agent))).status_code == 204

async def test_ack_queues_close_notice(local_client, services, agent):
    await hello(local_client, agent)
    cmd = (await local_client.get("/api/agent/next", params={"timeout": 0}, headers=H(agent))).json()
    assert (await local_client.post("/api/notice/display/ack", headers={"X-Notice-Token": token_of(cmd["url"])})).status_code == 204
    nxt = (await local_client.get("/api/agent/next", params={"timeout": 1}, headers=H(agent))).json()
    assert nxt == {"type": "close_notice", "display_id": cmd["display_id"]}

async def test_token_used_from_another_session_is_rejected_and_reported(local_client, services, agent):
    services.peers = FakePeerResolver(PeerInfo(900, 3, "CORP\\kim", r"C:\Python315\python.exe"))
    r = await local_client.post("/api/agent/heartbeat", json={"idle_sec": 0, "locked": False}, headers=H(agent))
    assert (r.status_code, r.json()) == (403, {"error": "forbidden"})
    rec = services.tamper.recent(1)[0]
    assert (rec["event"], rec["claimed_session"], rec["peer_session"], rec["peer_pid"]) == ("agent_impersonation", 2, 3, 900)

async def test_missing_or_unknown_token_is_401_without_tamper(local_client, services, agent):
    for headers in ({}, H("nope")):
        r = await local_client.post("/api/agent/heartbeat", json={"idle_sec": 0, "locked": None}, headers=headers)
        assert (r.status_code, r.json()) == (401, {"error": "login_required"})
    assert services.tamper.recent() == []

async def test_hello_with_wrong_session_id_is_403(local_client, services, agent):
    r = await local_client.post("/api/agent/hello", json={"session_id": 3, "pid": 500, "version": "0.1.0"}, headers=H(agent))
    assert r.status_code == 403 and services.tamper.recent(1)[0]["event"] == "agent_impersonation"

async def test_events_are_logged_with_session_context_and_event_time(local_client, services, agent):
    await hello(local_client, agent)
    body = json.loads(FIX.read_text("utf-8"))
    assert (await local_client.post("/api/agent/events", json=body, headers=H(agent))).status_code == 204
    w = await audit_events(services, "activity.window"); i = await audit_events(services, "activity.idle")
    assert [e["event"] for e in w] == ["foreground", "title", "minimize"]
    assert (w[0]["ts"], w[0]["title"], w[0]["session_id"], w[0]["client_ip"], w[0]["user"], w[0]["source"]) == \
        ("2026-11-04T13:59:57.000+09:00", "메모 - 메모장", 2, "10.0.3.21", "CORP\\hong", "agent")
    assert (i[0]["event"], i[0]["idle_sec"], "clock_skew" in i[0]) == ("idle", 300, False)

async def test_event_clock_skew_is_clamped(local_client, services, agent, clock):
    await hello(local_client, agent)
    far = (clock.now() - timedelta(hours=2)).isoformat()
    await local_client.post("/api/agent/events", json={"events": [{"type": "idle", "at": far, "idle_sec": 1}]}, headers=H(agent))
    [e] = await audit_events(services, "activity.idle")
    assert (e["ts"], e["clock_skew"]) == (to_kst_iso(clock.now()), True)

async def test_events_validation(local_client, services, agent):
    await hello(local_client, agent)
    one = {"type": "foreground", "at": "2026-11-04T13:59:57+09:00", "pid": 1, "exe": None, "title": "x"}
    for body in ({"events": [one] * 201}, {"events": [{**one, "title": "x" * 513}]}, {"events": [{**one, "at": "2026-11-04T13:59:57"}]}):
        assert (await local_client.post("/api/agent/events", json=body, headers=H(agent))).status_code == 422

async def test_closed_window_logs_unacknowledged_and_reshows(local_client, services, agent):
    await hello(local_client, agent)
    first = (await local_client.get("/api/agent/next", params={"timeout": 0}, headers=H(agent))).json()
    r = await local_client.post(f"/api/agent/notice/{first['display_id']}/closed", headers=H(agent))
    assert r.status_code == 204
    again = (await local_client.get("/api/agent/next", params={"timeout": 1}, headers=H(agent))).json()
    assert (again["type"], again["display_id"], again["attempt"]) == ("show_notice", first["display_id"], 2)
    assert token_of(again["url"]) != token_of(first["url"])
    un = [e for e in await audit_events(services, "notice") if e["event"] == "notice_unacknowledged"]
    assert [e["reason"] for e in un] == ["window_closed"]

async def test_agent_routes_absent_on_external(external_client):
    for method, path in [("POST", "/api/agent/hello"), ("GET", "/api/agent/next"), ("POST", "/api/agent/heartbeat"),
                         ("POST", "/api/agent/events"), ("POST", "/api/agent/notice/1/closed")]:
        assert (await external_client.request(method, path, headers=H("x"))).status_code == 404
```

- [ ] **Step 2: 실패 확인** — Run: `uv run python -m pytest tests/test_agent_api.py tests/test_channels.py -v` → FAIL

- [ ] **Step 3: 구현** — 위 Interfaces대로. `test_channels.py` `_local_only_routes`에 `agent_api.router`. `Services.agents: AgentHub`, `build_services`가 `displays.add_listener(agents.on_display)`를 등록합니다.

- [ ] **Step 4: 통과 확인** — Run: `uv run python -m pytest -q` → 전체 통과. ruff·mypy 0건.

- [ ] **Step 5: Commit** — `git commit -m "feat: local agent hub API with per-launch tokens, peer session verification, long-poll commands and window/idle events"`

---

### Task 13: 에이전트 감독과 런처 (재기동·백오프·종료 분류)

**Files:**
- Create: `server/app/win/launch.py`, `server/app/activity/agent_supervisor.py`, `server/tests/test_agent_supervisor.py`, `server/tests/test_launchers.py`
- Modify: `server/app/collect/config.py` (`launcher`, `agent`), `server/app/collect/cli.py` (`--agent-launcher`, `--agent-dialog`, `--agent-dir`), `server/app/services.py` (`agent_supervisor`), `server/app/main.py` (`configure`), `server/tests/winfakes.py` (`FakeLauncher`, `FakeProcess`)
- Modify (tests): `server/tests/test_main_cli.py`

**Interfaces:**
- Produces (`app.win.launch`):
  - `class AgentProcess(Protocol)`: `pid: int`, `def poll(self) -> int | None`, `def kill(self) -> None`.
  - `@dataclass(frozen=True) LaunchSpec(session_id: int, argv: list[str], env: dict[str, str], cwd: Path)`; `class LaunchError(Exception)`.
  - `class AgentLauncher(Protocol)`: `name: str`, `def launch(self, spec: LaunchSpec) -> AgentProcess`.
  - `class LocalLauncher`(`name="local"`): `spec.session_id != current_session_id()` → `LaunchError("session_mismatch")`. `subprocess.Popen(spec.argv, env={**os.environ, **spec.env}, cwd=spec.cwd, creationflags=CREATE_NO_WINDOW, stdin/stdout/stderr=DEVNULL)` → `PopenProcess`(`kill` = `taskkill /PID <pid> /T /F`, 실패 시 `Popen.kill`).
  - `class WtsLauncher(api: WtsApi | None = None)`(`name="wts"`): `WtsApi`는 pywin32 함수 묶음(`query_user_token`, `duplicate_token_ex`, `create_environment_block`, `create_process_as_user`, `get_exit_code`, `terminate`, `close_handle`)이고 기본값은 실제 pywin32 구현입니다. 순서: `win32ts.WTSQueryUserToken(session_id)` → `win32security.DuplicateTokenEx(tok, SecurityImpersonation, TOKEN_ALL_ACCESS, TokenPrimary)` → `win32profile.CreateEnvironmentBlock(primary, False)`에 `spec.env`를 덮어씀 → `STARTUPINFO.lpDesktop = "winsta0\\default"` → `win32process.CreateProcessAsUser(primary, None, subprocess.list2cmdline(spec.argv), None, None, False, CREATE_UNICODE_ENVIRONMENT | CREATE_NO_WINDOW, env, str(spec.cwd), si)` → `HandleProcess(hprocess, pid, api)`(`poll`: `GetExitCodeProcess == 259`(STILL_ACTIVE)이면 None). pywin32 예외 → `LaunchError(repr(exc))`.
  - `class NoLauncher`(`name="none"`): 항상 `LaunchError("disabled")`.
  - `running_as_system() -> bool`(현재 프로세스 토큰 사용자 SID가 `S-1-5-18`), `pick_launcher(mode: Literal["auto", "wts", "local", "none"]) -> AgentLauncher`(auto: SYSTEM이면 `WtsLauncher`, 아니면 `LocalLauncher`).
- Produces (`app.activity.agent_supervisor`):
  - `@dataclass(frozen=True) AgentOptions(dialog: Literal["edge", "print"] = "edge", agent_dir: Path = <repo>/agent, python: str = sys.executable, url_dir: Path | None = None, hello_timeout_sec: float = 30, heartbeat_timeout_sec: float = 20, exit_grace_sec: float = 3, backoff: tuple[float, ...] = (1, 2, 4, 8, 16, 30), healthy_reset_sec: float = 60, storm_count: int = 5, storm_window_sec: float = 600, tick_sec: float = 1.0, stop_grace_sec: float = 2.0)`
  - `class AgentSupervisor(hub: AgentHub, launcher: AgentLauncher, tracker: SessionTracker, tamper: TamperMonitor, log: LogWriter, clock: Clock, options: AgentOptions)` (루프 스레드):
    - `configure(server_url: str)`; `on_session_change(change)`: `Opened` → `ensure(session_id)`; `Closed(reason="logoff")` → `forget(session_id)`.
    - `ensure(session_id)`: 상태가 없거나(프로세스 없음·재시작 예약 없음) → 바로 `_launch`. 프로세스가 살아 있으면 `hub.show_pending(session_id)`.
    - `_launch(session_id)`: `token = hub.mint(session_id, ctx.user)`, `argv = [python, "-m", "mcp_agent", "--server", server_url, "--dialog", dialog]` + (print면 `["--url-file", str(url_dir / f"agent-{session_id}.url")]`), `env = {"MCPMON_AGENT_TOKEN": token, "PYTHONPATH": str(agent_dir)}`, `cwd = agent_dir`. 성공 → `system` `agent.launched {session_id, pid, launcher}`; `LaunchError` → `system` `agent.launch_failed {session_id, launcher, error}` + 백오프 예약.
    - `tick()`(테스트는 직접 부르고, `start()`는 `tick_sec`마다 부르는 태스크를 돌림): 세션마다
      1. 프로세스 없음 → 예약 시각이 지났고 `tracker.context(sid)`가 있으면 `_launch`.
      2. 살아 있음 → hello 전이고 `now − launched_at > hello_timeout_sec`, 또는 hello 후 `now − slot.last_seen > heartbeat_timeout_sec` → `tamper.report("agent_unresponsive", session_id, user, pid, stage="hello"|"heartbeat")` + `kill()`(우리가 죽임 표시).
      3. 종료됨 → 처음 본 tick이면 시각·코드만 기록. `exit_grace_sec`가 지나면: `tracker.context(sid)`가 없으면(로그오프) `session` `agent_stopped {session_id, reason: "logoff"}` 후 상태 삭제. 있으면: 우리가 죽인 게 아니면 `tamper.report("agent_exited", session_id, user, pid, exit_code, restarts)` + `hub.agent_exited(sid)`; 종료 시각을 창(`storm_window_sec`)에 넣고 `storm_count` 이상이면 그 창에서 처음 한 번만 `tamper.report("agent_restart_storm", session_id, user, exits)`; `relaunch_at = now + backoff[min(n, len − 1)]`(`n` = 연속 실패 수; hello 후 `healthy_reset_sec` 넘게 살아 있었으면 0으로 리셋).
    - `forget(session_id)`: 살아 있으면 죽이고(우리가 죽임), `hub.revoke`, 상태 삭제.
    - `async start()` / `async stop()`: stop은 살아 있는 에이전트마다 `hub.queue(sid, {"type": "exit"})` → `stop_grace_sec` 대기 → 남은 것 `kill`.
  - `CollectorConfig.launcher: AgentLauncher | None = None`, `agent: AgentOptions = AgentOptions()`. `build_services`는 `launcher`가 있을 때만 감독자를 만들고 트래커 리스너로 등록하며(`displays` 리스너 **다음**), `collectors.add_task("agent-supervisor", supervisor.run)`. `Services.agent_supervisor: AgentSupervisor | None`.
  - CLI: `--agent-launcher {auto,wts,local,none}`(기본 auto; `--session-source none`이면 무시하고 None), `--agent-dialog {edge,print}`(기본 edge), `--agent-dir PATH`(기본 `<repo>/agent`). print면 `url_dir = <root>/run`. `serve()`는 `services.agents.configure(f"http://127.0.0.1:{local_port}")`와 감독자 `configure`를 같은 URL로 부릅니다.
  - `tests/winfakes`: `FakeProcess(pid)`(`exit(code)`, `killed`, `poll`, `kill` → 다음 `poll`부터 1), `FakeLauncher`(`specs`, `procs`, `fail_next: LaunchError | None`, pid는 1000부터 1씩).

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_agent_supervisor.py
from pathlib import Path

import pytest

from app.activity.agent_supervisor import AgentOptions, AgentSupervisor
from app.win.launch import LaunchError
from app.win.peer import PeerInfo
from tests.session_helpers import snap, ws
from tests.test_auth_api import audit_events
from tests.winfakes import FakeLauncher

@pytest.fixture
def sup(services, clock, tmp_path):
    launcher = FakeLauncher()
    s = AgentSupervisor(services.agents, launcher, services.sessions, services.tamper, services.log, clock,
                        AgentOptions(dialog="print", url_dir=tmp_path, python="py.exe", agent_dir=Path("C:/agent"), stop_grace_sec=0.01))
    s.configure("http://127.0.0.1:8700"); services.sessions.add_listener(s.on_session_change)
    return s, launcher, tmp_path

def events(services, limit=50):
    return [r["event"] for r in services.tamper.recent(limit)]

async def test_opened_session_launches_agent_with_token_env_and_args(services, clock, sup):
    s, launcher, tmp = sup; services.sessions.apply(snap(clock.now(), ws(2)))
    [spec] = launcher.specs
    assert spec.session_id == 2 and spec.cwd == Path("C:/agent")
    assert spec.argv == ["py.exe", "-m", "mcp_agent", "--server", "http://127.0.0.1:8700", "--dialog", "print", "--url-file", str(tmp / "agent-2.url")]
    assert spec.env["PYTHONPATH"] == str(Path("C:/agent"))
    assert services.agents.authenticate(spec.env["MCPMON_AGENT_TOKEN"], PeerInfo(1, 2, None, None)).session_id == 2
    assert [e["event"] for e in await audit_events(services, "system") if e.get("event", "").startswith("agent.")] == ["agent.launched"]

async def test_agent_exit_logs_tamper_and_relaunches_with_backoff(services, clock, sup):
    s, launcher, _ = sup; services.sessions.apply(snap(clock.now(), ws(2)))
    launcher.procs[0].exit(1); s.tick()
    clock.advance(2); s.tick(); assert events(services) == []
    clock.advance(1.5); s.tick()
    rec = services.tamper.recent(1)[0]
    assert (rec["event"], rec["session_id"], rec["exit_code"]) == ("agent_exited", 2, 1) and len(launcher.specs) == 1
    clock.advance(1); s.tick(); assert len(launcher.specs) == 2
    launcher.procs[1].exit(1); s.tick(); clock.advance(3.5); s.tick()
    clock.advance(1); s.tick(); assert len(launcher.specs) == 2
    clock.advance(1); s.tick(); assert len(launcher.specs) == 3
    un = [e for e in await audit_events(services, "notice") if e["event"] == "notice_unacknowledged"]
    assert [e["reason"] for e in un] == ["agent_exited", "agent_exited"]

async def test_exit_after_logoff_is_not_tamper(services, clock, sup):
    s, launcher, _ = sup; services.sessions.apply(snap(clock.now(), ws(2)))
    launcher.procs[0].exit(0); s.tick()
    services.sessions.apply(snap(clock.now()))  # logoff
    clock.advance(5); s.tick(); clock.advance(60); s.tick()
    assert events(services) == [] and len(launcher.specs) == 1

async def test_hello_timeout_kills_once_and_reports_unresponsive(services, clock, sup):
    s, launcher, _ = sup; services.sessions.apply(snap(clock.now(), ws(2)))
    clock.advance(31); s.tick()
    assert launcher.procs[0].killed and events(services) == ["agent_unresponsive"]
    assert services.tamper.recent(1)[0]["stage"] == "hello"
    s.tick(); clock.advance(3.5); s.tick()
    assert events(services) == ["agent_unresponsive"]

async def test_restart_storm_reported_once_per_window(services, clock, sup):
    s, launcher, _ = sup; services.sessions.apply(snap(clock.now(), ws(2)))
    for i in range(7):
        launcher.procs[i].exit(1); s.tick(); clock.advance(3.5); s.tick(); clock.advance(31); s.tick()
    assert events(services).count("agent_restart_storm") == 1 and events(services).count("agent_exited") == 7

async def test_pending_notice_reshown_after_restart(services, clock, sup):
    s, launcher, _ = sup; services.sessions.apply(snap(clock.now(), ws(2)))
    d = services.displays.pending_for_session(2)
    launcher.procs[0].exit(1); s.tick(); clock.advance(3.5); s.tick(); clock.advance(1); s.tick()
    token = launcher.specs[1].env["MCPMON_AGENT_TOKEN"]
    slot = services.agents.authenticate(token, PeerInfo(1001, 2, None, None))
    services.agents.hello(slot, session_id=2, pid=1001, version="0.1.0", peer=PeerInfo(1001, 2, None, None))
    cmd = await services.agents.next(slot, 0)
    assert (cmd["type"], cmd["display_id"], cmd["attempt"]) == ("show_notice", d.id, 1)

async def test_launch_failure_is_logged_and_retried(services, clock, sup):
    s, launcher, _ = sup; launcher.fail_next = LaunchError("session_mismatch")
    services.sessions.apply(snap(clock.now(), ws(2)))
    fails = [e for e in await audit_events(services, "system") if e.get("event") == "agent.launch_failed"]
    assert fails[0]["error"] == "session_mismatch" and launcher.specs == []
    clock.advance(1); s.tick(); assert len(launcher.specs) == 1

async def test_stop_asks_agents_to_exit_then_kills(services, clock, sup):
    s, launcher, _ = sup; services.sessions.apply(snap(clock.now(), ws(2)))
    slot = services.agents.slot(2)
    await s.stop()
    assert list(slot.commands)[-1] == {"type": "exit"} and launcher.procs[0].killed
```

```python
# server/tests/test_launchers.py
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.win.ffi import current_session_id
from app.win.launch import LaunchError, LaunchSpec, LocalLauncher, NoLauncher, WtsLauncher, pick_launcher

windows = pytest.mark.skipif(sys.platform != "win32", reason="Windows API")

@windows
def test_local_launcher_refuses_another_session(tmp_path):
    with pytest.raises(LaunchError, match="session_mismatch"):
        LocalLauncher().launch(LaunchSpec(current_session_id() + 1, [sys.executable, "-c", "pass"], {}, tmp_path))

@windows
def test_local_launcher_runs_in_own_session_with_env(tmp_path):
    out = tmp_path / "o"
    code = "import os,time; open(os.environ['OUT'],'w').write(os.environ['MCPMON_AGENT_TOKEN']); time.sleep(30)"
    p = LocalLauncher().launch(LaunchSpec(current_session_id(), [sys.executable, "-c", code], {"OUT": str(out), "MCPMON_AGENT_TOKEN": "tok"}, tmp_path))
    try:
        deadline = time.monotonic() + 10
        while not out.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert out.read_text() == "tok" and p.poll() is None
    finally:
        p.kill()
    deadline = time.monotonic() + 5
    while p.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert p.poll() is not None

def test_wts_launcher_call_sequence():
    calls = []
    api = SimpleNamespace(
        query_user_token=lambda sid: calls.append(("token", sid)) or "tok",
        duplicate_token_ex=lambda tok: calls.append(("dup", tok)) or "primary",
        create_environment_block=lambda tok: calls.append(("env", tok)) or {"USERPROFILE": "C:\\Users\\hong", "PATH": "C:\\Windows"},
        create_process_as_user=lambda tok, cmdline, env, cwd, desktop: calls.append(("create", tok, cmdline, env, cwd, desktop)) or ("hproc", 777),
        get_exit_code=lambda h: 259, terminate=lambda h: calls.append(("kill", h)), close_handle=lambda h: None)
    spec = LaunchSpec(2, ["C:\\Py\\python.exe", "-m", "mcp_agent", "--server", "http://127.0.0.1:8700"], {"MCPMON_AGENT_TOKEN": "t"}, Path("C:/agent"))
    p = WtsLauncher(api).launch(spec)
    assert [c[0] for c in calls] == ["token", "dup", "env", "create"] and calls[0] == ("token", 2)
    _, tok, cmdline, env, cwd, desktop = calls[3]
    assert (tok, cmdline, cwd, desktop) == ("primary", "C:\\Py\\python.exe -m mcp_agent --server http://127.0.0.1:8700", str(Path("C:/agent")), "winsta0\\default")
    assert env == {"USERPROFILE": "C:\\Users\\hong", "PATH": "C:\\Windows", "MCPMON_AGENT_TOKEN": "t"}
    assert (p.pid, p.poll()) == (777, None)
    p.kill(); assert calls[-1] == ("kill", "hproc")

def test_wts_launcher_wraps_errors():
    api = SimpleNamespace(query_user_token=lambda sid: (_ for _ in ()).throw(OSError(1314, "privilege not held")))
    with pytest.raises(LaunchError, match="1314"):
        WtsLauncher(api).launch(LaunchSpec(2, ["x"], {}, Path(".")))

def test_pick_launcher():
    assert isinstance(pick_launcher("auto"), LocalLauncher)  # this dev PC never runs tests as SYSTEM
    assert isinstance(pick_launcher("none"), NoLauncher) and isinstance(pick_launcher("wts"), WtsLauncher)
    with pytest.raises(LaunchError, match="disabled"):
        NoLauncher().launch(LaunchSpec(1, ["x"], {}, Path(".")))
```

```python
# server/tests/test_main_cli.py (추가)
from app.win.launch import LocalLauncher

def test_agent_flags(tmp_path, clock):
    cfg = collector_config(parse_args(["--session-source", f"json:{tmp_path / 's.json'}", "--agent-launcher", "local",
                                       "--agent-dialog", "print"]), clock=clock, root=tmp_path)
    assert isinstance(cfg.launcher, LocalLauncher) and cfg.agent.dialog == "print" and cfg.agent.url_dir == tmp_path / "run"
    assert collector_config(parse_args(["--session-source", "none"]), clock=clock, root=tmp_path).launcher is None
    assert collector_config(parse_args(["--agent-launcher", "none"]), clock=clock, root=tmp_path).launcher is None
```

`WtsApi`의 `create_process_as_user(token, cmdline, env, cwd, desktop) -> (hprocess, pid)`는 실제 구현에서 `STARTUPINFO`·플래그를 만들고 `CreateProcessAsUser`를 부른 뒤 스레드 핸들을 닫습니다. 테스트는 이 경계 함수만 가짜로 바꿉니다. `--agent-launcher none` → `launcher=None`(감독자 없음).

- [ ] **Step 2: 실패 확인** — Run: `uv run python -m pytest tests/test_agent_supervisor.py tests/test_launchers.py tests/test_main_cli.py -v` → FAIL

- [ ] **Step 3: 구현** — 위 Interfaces대로.

- [ ] **Step 4: 통과 확인** — Run: `uv run python -m pytest -q` → 전체 통과. ruff·mypy 0건.

- [ ] **Step 5: Commit** — `git commit -m "feat: agent supervisor with local/WTS launchers, exit classification, backoff relaunch and storm detection"`

---

### Task 14: 우회 탐지 점검 (감사 정책·로그 삭제 이벤트, 레지스트리 기준선, 로그·스크립트 파일)

**Files:**
- Modify: `server/app/activity/tamper.py` (`map_tamper_record`, `TamperEventHandler`, `AUDIT_REGISTRY`, `read_hklm`, `TamperScanner`), `server/app/services.py` (핸들러 등록 `eventlog:security`·`eventlog:system`; `collectors.add_task("tamper-scan", ...)` 60초 — `CollectorConfig.wts`가 있을 때만, 즉 수집이 켜진 서버에서만. 단위 테스트의 `services`는 수집이 꺼져 있으므로 스캔 태스크가 없습니다)
- Create: `server/tests/test_tamper_scan.py`

**Interfaces:**
- Produces:
  - `map_tamper_record(r: EventRecord) -> tuple[str, dict[str, Any]] | None`:
    - Security 4719 → `("audit_policy_changed", {"user": SubjectDomainName\SubjectUserName, "category": CategoryId, "subcategory": SubcategoryGuid, "changes": AuditPolicyChanges})`
    - Security 1102 → `("log_cleared", {"channel": "Security", "user": SubjectDomainName\SubjectUserName})`(UserData `LogFileCleared`)
    - System 104(`Microsoft-Windows-Eventlog`) → `("log_cleared", {"channel": data["Channel"], "user": SubjectDomainName\SubjectUserName})`
    - 그 밖 → None.
  - `class TamperEventHandler(tamper: TamperMonitor)`: `__call__(records)` → `tamper.report(name, at=r.time_created, source=f"eventlog:{r.event_id}", record_id=r.record_id, **fields)`.
  - `@dataclass(frozen=True) RegistryValue(path: str, name: str)`; `AUDIT_REGISTRY = (RegistryValue(r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System\Audit", "ProcessCreationIncludeCmdLine_Enabled"), RegistryValue(r"SOFTWARE\Policies\Microsoft\Windows\PowerShell\ScriptBlockLogging", "EnableScriptBlockLogging"))`
  - `read_hklm(v: RegistryValue) -> int | str | None`: `winreg.OpenKey(HKEY_LOCAL_MACHINE, v.path)` + `QueryValueEx`; 키·값 없음 → None.
  - `class TamperScanner(tamper: TamperMonitor, scripts: ScriptStore, mcps: McpStore, logs_dir: Path, log: LogWriter, *, read_value: Callable[[RegistryValue], int | str | None] = read_hklm, registry: tuple[RegistryValue, ...] = AUDIT_REGISTRY)`: `scan() -> None`(루프 스레드; 파일 읽기는 작아서 그대로, 60초 주기):
    1. 레지스트리: 첫 스캔은 `system` `audit.config {values: {"<path>\\<name>": value}}`만. 이후 값이 바뀌면 `tamper.report("audit_config_changed", key=..., before=..., after=...)`(바뀐 값 하나당 한 번). `read_value`가 `OSError`를 던지면 None으로 봅니다.
    2. 스크립트: 모든 MCP·종류(`scripts.list(mcp.id)`)에 대해 파일 없음 → `script_file_missing {mcp_id, kind, path}`, sha256(파일 바이트) ≠ DB → `script_file_changed {mcp_id, kind, path, expected_sha256, actual_sha256}`. 같은 `(mcp_id, kind, actual)`은 다시 맞아질 때까지 한 번만 보고.
    3. 로그: `^\d{4}-\d{2}-\d{2}\.jsonl(\.gz)?$` 파일 크기를 기억합니다. 이전에 있던 파일이 없어짐 → `log_file_removed {file}`(단 `expect_log_removed(name)`으로 예고된 파일은 조용히 잊음 — Plan 5 보존 정리가 부릅니다), 크기가 줄어듦 → `log_file_truncated {file, before, after}`.
    - `expect_log_removed(file_name: str) -> None`.
  - `Services.tamper_scanner: TamperScanner`(항상 생성; 60초 태스크는 `collectors`에).

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_tamper_scan.py
from app.activity.tamper import RegistryValue, TamperEventHandler, TamperScanner, map_tamper_record
from app.win.eventlog import parse_event_xml
from tests.eventlog_helpers import evt_xml
from tests.mcp_helpers import make_user, seed_mcp
from tests.test_auth_api import audit_events

SUBJ = {"SubjectUserSid": "S-1-5-21-1", "SubjectUserName": "admin", "SubjectDomainName": "MCP-HOST", "SubjectLogonId": "0x1"}

def test_audit_policy_event_maps():
    r = parse_event_xml(evt_xml("Security", 4719, 5, data={**SUBJ, "CategoryId": "%%8274", "SubcategoryGuid": "{0CCE922B-69AE-11D9-BED3-505054503030}", "AuditPolicyChanges": "%%8448"}))
    assert map_tamper_record(r) == ("audit_policy_changed", {"user": "MCP-HOST\\admin", "category": "%%8274",
        "subcategory": "{0CCE922B-69AE-11D9-BED3-505054503030}", "changes": "%%8448"})

def test_log_cleared_events_map():
    sec = parse_event_xml(evt_xml("Security", 1102, 6, provider="Microsoft-Windows-Eventlog", user_data=("LogFileCleared", SUBJ)))
    sysr = parse_event_xml(evt_xml("System", 104, 7, provider="Microsoft-Windows-Eventlog", user_data=("LogFileCleared", {**SUBJ, "Channel": "Application"})))
    assert map_tamper_record(sec) == ("log_cleared", {"channel": "Security", "user": "MCP-HOST\\admin"})
    assert map_tamper_record(sysr) == ("log_cleared", {"channel": "Application", "user": "MCP-HOST\\admin"})
    assert map_tamper_record(parse_event_xml(evt_xml("Security", 4688, 8, data=SUBJ))) is None

async def test_handler_reports_with_event_time(services):
    TamperEventHandler(services.tamper)([parse_event_xml(evt_xml("Security", 1102, 6, "2026-11-04T04:00:00Z", provider="Microsoft-Windows-Eventlog", user_data=("LogFileCleared", SUBJ)))])
    rec = services.tamper.recent(1)[0]
    assert (rec["event"], rec["at"], rec["source"], rec["record_id"]) == ("log_cleared", "2026-11-04T13:00:00.000+09:00", "eventlog:1102", 6)

def scanner(services, values):
    return TamperScanner(services.tamper, services.scripts, services.mcps, services.paths.logs_dir, services.log,
                         read_value=lambda v: values[v.name], registry=(RegistryValue("A", "cmd"), RegistryValue("B", "ps")))

async def test_registry_baseline_then_change_reported_once(services):
    values = {"cmd": 1, "ps": None}; s = scanner(services, values)
    s.scan(); assert services.tamper.recent() == []
    assert [e["values"] for e in await audit_events(services, "system") if e.get("event") == "audit.config"] == [{"A\\cmd": 1, "B\\ps": None}]
    values["cmd"] = 0; s.scan(); s.scan()
    [rec] = services.tamper.recent()
    assert (rec["event"], rec["key"], rec["before"], rec["after"]) == ("audit_config_changed", "A\\cmd", 1, 0)

async def test_unreadable_registry_counts_as_missing(services):
    def boom(v):
        raise OSError(5, "denied")
    s = TamperScanner(services.tamper, services.scripts, services.mcps, services.paths.logs_dir, services.log, read_value=boom)
    s.scan(); s.scan()
    assert services.tamper.recent() == []

async def test_script_file_changed_and_missing_reported_once_until_fixed(services):
    m = seed_mcp(services, make_user(services, "o@x.com")); info = services.scripts.get(m.id, "start")
    s = scanner(services, {"cmd": None, "ps": None}); s.scan()
    original = info.path.read_bytes()
    info.path.write_bytes(b"exit /b 1"); s.scan(); s.scan()
    assert [r["event"] for r in services.tamper.recent()] == ["script_file_changed"]
    info.path.write_bytes(original); s.scan()
    info.path.write_bytes(b"exit /b 2"); s.scan()
    info.path.unlink(); s.scan()
    assert [r["event"] for r in services.tamper.recent()] == ["script_file_missing", "script_file_changed", "script_file_changed"]

async def test_log_files_truncated_or_removed(services):
    d = services.paths.logs_dir
    for name in ("2026-11-01.jsonl", "2026-11-02.jsonl", "2026-11-03.jsonl.gz"):
        (d / name).write_bytes(b"x" * 100)
    s = scanner(services, {"cmd": None, "ps": None}); s.scan()
    (d / "2026-11-01.jsonl").write_bytes(b"x" * 10)
    (d / "2026-11-02.jsonl").unlink()
    s.expect_log_removed("2026-11-03.jsonl.gz"); (d / "2026-11-03.jsonl.gz").unlink()
    s.scan()
    recs = sorted((r["event"], r["file"]) for r in services.tamper.recent())
    assert recs == [("log_file_removed", "2026-11-02.jsonl"), ("log_file_truncated", "2026-11-01.jsonl")]
```

- [ ] **Step 2: 실패 확인** — Run: `uv run python -m pytest tests/test_tamper_scan.py -v` → FAIL

- [ ] **Step 3: 구현** — 위 Interfaces대로. 오늘 날짜 파일은 `LogWriter`가 계속 키우므로 "줄어듦"만 봅니다.

- [ ] **Step 4: 통과 확인** — Run: `uv run python -m pytest -q` → 전체 통과. ruff·mypy 0건. 수동(이 PC, 관리자 아님): `uv run python -c "from app.activity.tamper import read_hklm, AUDIT_REGISTRY; print([read_hklm(v) for v in AUDIT_REGISTRY])"` → 예외 없이 값 또는 None(보고서에 붙임).

- [ ] **Step 5: Commit** — `git commit -m "feat: tamper detection for audit policy changes, cleared logs, audit registry drift and log/script file changes"`

---
### Task 15: 세션 에이전트 — 코어 (`agent/`: 설정, 클라이언트, 명령 루프, 고지 창)

**Files:**
- Create: `agent/pyproject.toml`, `agent/.python-version`(`3.15`), `agent/uv.lock`
- Create: `agent/mcp_agent/__init__.py`(`VERSION = "0.1.0"`), `agent/mcp_agent/__main__.py`, `agent/mcp_agent/config.py`, `agent/mcp_agent/client.py`, `agent/mcp_agent/runner.py`, `agent/mcp_agent/dialog.py`, `agent/mcp_agent/win32.py`
- Create: `agent/tests/__init__.py`, `agent/tests/conftest.py`, `agent/tests/fake_server.py`, `agent/tests/test_config_client.py`, `agent/tests/test_runner.py`, `agent/tests/test_dialog.py`
- Modify: `.gitignore`(`agent/.venv/`)

**Interfaces:**
- Produces:
  - `agent/pyproject.toml`:
    ```toml
    [project]
    name = "mcp-agent"
    version = "0.1.0"
    description = "MCP Monitor session agent: notice window, window and idle events"
    requires-python = ">=3.15,<3.16"
    dependencies = []

    [dependency-groups]
    dev = ["pytest", "pytest-timeout"]

    [tool.pytest.ini_options]
    testpaths = ["tests"]
    pythonpath = ["."]
    markers = ["winlive: real Windows API on this PC, no admin rights"]
    addopts = "-m 'not winlive'"
    timeout = 60
    ```
    런타임 의존성은 없습니다(V5). `sqlite3`를 import하지 않고 `config.db`를 열지 않습니다(carry-forward 경합 항목).
  - `config.py`: `@dataclass(frozen=True) AgentConfig(server: str, token: str, dialog: Literal["edge", "print"], url_file: Path | None, edge_path: str | None, profile_dir: Path, unreachable_exit_sec: float)`; `parse_args(argv: list[str], environ: MutableMapping[str, str]) -> AgentConfig` — `--server`(필수, 끝의 `/` 제거), `--dialog {edge,print}`(기본 edge), `--url-file`(print에서 필수), `--edge-path`, `--profile-dir`(기본 `%LOCALAPPDATA%\mcp-monitor\notice-edge`), `--unreachable-exit-sec`(기본 120). 토큰은 `environ.pop("MCPMON_AGENT_TOKEN")`(꺼낸 뒤 지워서 Edge 같은 자식 프로세스에 물려주지 않음, V17). 토큰이 없으면 `argparse` 오류(종료 2).
  - `client.py`: `class ServerUnavailable(Exception)`, `class AgentRejected(Exception)`; `class ServerClient(base_url: str, token: str, *, timeout: float = 10.0)`: `post(path: str, body: Mapping[str, Any] | None = None) -> dict | None`(204 → None), `next(timeout: float) -> dict | None`(`GET /api/agent/next?timeout=<t>`, 읽기 제한 `t + 10`초, 204 → None). 모든 요청에 `X-Agent-Token`, 본문은 `Content-Type: application/json`(UTF-8). `urllib.request`만 씁니다. 401·403 → `AgentRejected`, 연결 실패·시간 초과·5xx → `ServerUnavailable`, 그 밖 4xx → `RuntimeError`.
  - `dialog.py`:
    - `class NoticeWindow(Protocol)`: `open(url: str, display_id: int) -> None`, `close() -> None`, `closed_by_user() -> bool`(우리가 닫지 않았는데 창이 사라졌으면 True).
    - `class PrintWindow(url_file: Path)`: `open` → `OPEN <id> <url>` 줄 추가, `close` → `CLOSE <id>` 줄 추가(열린 것이 있을 때만), `closed_by_user` → 항상 False. E2E·통합 테스트용(V24).
    - `edge_command(edge: str, url: str, profile_dir: Path) -> list[str]` = `[edge, f"--app={url}", f"--user-data-dir={profile_dir}", "--no-first-run", "--no-default-browser-check", "--disable-sync", "--window-size=640,600"]`.
    - `find_edge() -> str | None`: `HKLM`→`HKCU` `SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe`의 기본값, 없으면 `%ProgramFiles(x86)%`·`%ProgramFiles%`의 `Microsoft\Edge\Application\msedge.exe`.
    - `class EdgeWindow(edge: str | None, profile_dir: Path, *, popen=subprocess.Popen, kill_tree: Callable[[int], None] = taskkill_tree, make_topmost: Callable[[int], bool] = win32.make_topmost_for_pid)`: `open` → 열린 창을 먼저 닫고 `popen(edge_command(...))`, 곧바로 `make_topmost(pid)`를 **동기로 한 번** 시도하고, False면 데몬 스레드가 5초 동안 0.2초마다 True가 될 때까지 다시 시도. `edge`가 None이면 `webbrowser.open(url)`로 대신 열고 창 추적은 하지 않습니다(V25). `close` → `kill_tree(pid)`(우리가 닫음 표시). `closed_by_user` → 프로세스가 끝났고 우리가 닫지 않았음.
    - `taskkill_tree(pid)` = `subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], creationflags=CREATE_NO_WINDOW, capture_output=True)`.
  - `win32.py`(ctypes): `current_session_id() -> int`(`ProcessIdToSessionId(GetCurrentProcessId())`), `idle_seconds() -> float`(`GetLastInputInfo` + `GetTickCount64`), `make_topmost_for_pid(pid) -> bool`(`EnumWindows`로 그 pid의 보이는 최상위 창을 찾아 화면 중앙으로 옮기고 `SetWindowPos(HWND_TOPMOST, …, SWP_SHOWWINDOW)` + `SetForegroundWindow`; 못 찾으면 False). Task 16이 함수를 더합니다.
  - `runner.py`: `class AgentRunner(cfg: AgentConfig, client: ServerClient, window: NoticeWindow, *, session_id: int, pid: int, monotonic: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep, idle: Callable[[], float] = win32.idle_seconds, on_hello: Callable[[dict[str, Any]], None] | None = None)`:
    - `run() -> int`: `hello`(`{"session_id", "pid", "version": VERSION}`)를 백오프(1, 2, 4, 8, 10초…)로 재시도. `ServerUnavailable`이 처음 난 뒤 `cfg.unreachable_exit_sec`가 지나면 **4**. `AgentRejected` → **3**. 성공하면 `on_hello(hello)` → 하트비트 스레드(`hello["heartbeat_sec"]`마다 `POST /api/agent/heartbeat {"idle_sec": int(idle()), "locked": None}`; `AgentRejected`면 루프에 정지 신호) → 명령 루프.
    - 명령 루프: 창이 열려 있고 `window.closed_by_user()`면 `POST /api/agent/notice/<id>/closed` 후 `pending = None`. `cmd = client.next(2.0 if pending else 25.0)`. `show_notice` → 다른 표시가 열려 있으면 `close`, `window.open(url, id)`, `pending = id`. `close_notice` → `pending == id`면 `close`, `pending = None`. `exit` → `close` 후 **0**. 모르는 `type`은 무시. 통신 중 `ServerUnavailable`은 같은 백오프·한도(→ 4), `AgentRejected` → 창 닫고 **3**.
  - `__main__.py`: `main(argv=None) -> int` = `parse_args(sys.argv[1:], os.environ)` → `ServerClient` → 창(`PrintWindow(cfg.url_file)` 또는 `EdgeWindow(cfg.edge_path or find_edge(), cfg.profile_dir)`) → `AgentRunner(..., session_id=win32.current_session_id(), pid=os.getpid()).run()`; `if __name__ == "__main__": sys.exit(main())`.
  - `tests/fake_server.py`: `FakeServer`(`http.server.ThreadingHTTPServer`, 포트 0): `url`, `requests: list[tuple[str, str, Any, dict[str, str]]]`(method, path(쿼리 제외), JSON 본문, 헤더), `commands: deque[dict]`(`GET /api/agent/next`가 하나씩; 비면 0.05초 뒤 204), `status_for: dict[str, int]`(경로별 강제 상태), `hello_body: dict`(기본 `{"heartbeat_sec": 5, "events_max": 200, "idle_threshold_sec": 300}`), 나머지 POST는 204. `conftest.py`의 `fake_server` 픽스처가 시작·정지합니다.

- [ ] **Step 1: 골격** — `agent/`에 위 `pyproject.toml`과 `.python-version`을 만들고 Run(agent): `uv sync` → 성공(`uv.lock` 생성), `uv run python -m pytest -q` → "no tests ran"(종료 5)까지 확인합니다.

- [ ] **Step 2: 실패하는 테스트 작성**

```python
# agent/tests/test_config_client.py
import socket
from pathlib import Path

import pytest

from mcp_agent.client import AgentRejected, ServerClient, ServerUnavailable
from mcp_agent.config import parse_args

def test_config_requires_token_and_server():
    with pytest.raises(SystemExit) as e:
        parse_args(["--server", "http://127.0.0.1:8700"], {})
    assert e.value.code == 2
    with pytest.raises(SystemExit):
        parse_args([], {"MCPMON_AGENT_TOKEN": "t"})

def test_config_reads_and_removes_the_token():
    env = {"MCPMON_AGENT_TOKEN": "tok", "OTHER": "1"}
    cfg = parse_args(["--server", "http://127.0.0.1:8700/", "--dialog", "print", "--url-file", "u.url"], env)
    assert (cfg.server, cfg.token, cfg.dialog, cfg.url_file, cfg.unreachable_exit_sec) == ("http://127.0.0.1:8700", "tok", "print", Path("u.url"), 120)
    assert "MCPMON_AGENT_TOKEN" not in env and env["OTHER"] == "1"
    assert parse_args(["--server", "http://x"], {"MCPMON_AGENT_TOKEN": "t"}).dialog == "edge"

def test_client_sends_token_and_json(fake_server):
    c = ServerClient(fake_server.url, "tok")
    assert c.post("/api/agent/hello", {"session_id": 1, "title": "메모"}) == fake_server.hello_body
    method, path, body, headers = fake_server.requests[-1]
    assert (method, path, body, headers["X-Agent-Token"], headers["Content-Type"]) == \
        ("POST", "/api/agent/hello", {"session_id": 1, "title": "메모"}, "tok", "application/json")

def test_client_maps_statuses(fake_server):
    c = ServerClient(fake_server.url, "tok")
    assert c.next(0.05) is None and c.post("/api/agent/heartbeat", {"idle_sec": 1}) is None
    fake_server.status_for["/api/agent/heartbeat"] = 403
    with pytest.raises(AgentRejected):
        c.post("/api/agent/heartbeat", {})
    fake_server.status_for["/api/agent/heartbeat"] = 503
    with pytest.raises(ServerUnavailable):
        c.post("/api/agent/heartbeat", {})

def test_client_unavailable_when_nothing_listens():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
    with pytest.raises(ServerUnavailable):
        ServerClient(f"http://127.0.0.1:{port}", "t", timeout=1).post("/api/agent/hello", {})

def test_agent_never_touches_the_database():
    src = "\n".join(p.read_text("utf-8") for p in (Path(__file__).parents[1] / "mcp_agent").glob("*.py"))
    assert "sqlite3" not in src and "config.db" not in src
```

```python
# agent/tests/test_runner.py
import os
import threading
import time
from pathlib import Path

from mcp_agent import VERSION
from mcp_agent.client import ServerClient
from mcp_agent.config import AgentConfig
from mcp_agent.dialog import PrintWindow
from mcp_agent.runner import AgentRunner

def cfg(server, tmp_path, **kw):
    base = dict(server=server, token="tok", dialog="print", url_file=tmp_path / "u.url", edge_path=None,
                profile_dir=tmp_path / "p", unreachable_exit_sec=120.0)
    base.update(kw); return AgentConfig(**base)

class FakeWindow:
    def __init__(self):
        self.opened, self.closed, self.user_closed = [], 0, False
    def open(self, url, display_id):
        self.opened.append((display_id, url)); self.user_closed = False
    def close(self):
        self.closed += 1
    def closed_by_user(self):
        return self.user_closed

def wait_until(pred, timeout=5.0):
    end = time.monotonic() + timeout
    while not pred():
        assert time.monotonic() < end, "condition not met"
        time.sleep(0.02)

def test_runner_shows_and_closes_notice(fake_server, tmp_path):
    url = "http://127.0.0.1:8700/notice#d=7&t=x"
    fake_server.commands.extend([{"type": "show_notice", "display_id": 7, "attempt": 1, "url": url},
                                 {"type": "close_notice", "display_id": 7}, {"type": "exit"}])
    c = cfg(fake_server.url, tmp_path)
    code = AgentRunner(c, ServerClient(fake_server.url, "tok"), PrintWindow(c.url_file), session_id=2, pid=os.getpid(), idle=lambda: 3.7).run()
    assert code == 0 and c.url_file.read_text("utf-8").splitlines() == [f"OPEN 7 {url}", "CLOSE 7"]
    hello = next(r for r in fake_server.requests if r[1] == "/api/agent/hello")
    assert hello[2] == {"session_id": 2, "pid": os.getpid(), "version": VERSION}

def test_runner_reports_a_window_the_user_closed(fake_server, tmp_path):
    w = FakeWindow(); fake_server.commands.append({"type": "show_notice", "display_id": 7, "attempt": 1, "url": "u"})
    r = AgentRunner(cfg(fake_server.url, tmp_path), ServerClient(fake_server.url, "tok"), w, session_id=2, pid=1, idle=lambda: 0)
    result = []; t = threading.Thread(target=lambda: result.append(r.run())); t.start()
    wait_until(lambda: w.opened == [(7, "u")])
    w.user_closed = True
    wait_until(lambda: any(x[:2] == ("POST", "/api/agent/notice/7/closed") for x in fake_server.requests))
    fake_server.commands.append({"type": "exit"}); t.join(10)
    assert result == [0]

def test_runner_sends_heartbeats_with_idle(fake_server, tmp_path):
    fake_server.hello_body = {"heartbeat_sec": 0.05, "events_max": 200, "idle_threshold_sec": 300}
    r = AgentRunner(cfg(fake_server.url, tmp_path), ServerClient(fake_server.url, "tok"), FakeWindow(), session_id=2, pid=1, idle=lambda: 12.9)
    t = threading.Thread(target=r.run); t.start()
    wait_until(lambda: sum(1 for x in fake_server.requests if x[1] == "/api/agent/heartbeat") >= 2)
    fake_server.commands.append({"type": "exit"}); t.join(10)
    hb = next(x for x in fake_server.requests if x[1] == "/api/agent/heartbeat")
    assert hb[2] == {"idle_sec": 12, "locked": None}

def test_runner_exits_3_when_rejected(fake_server, tmp_path):
    fake_server.status_for["/api/agent/hello"] = 401
    assert AgentRunner(cfg(fake_server.url, tmp_path), ServerClient(fake_server.url, "tok"), FakeWindow(), session_id=2, pid=1).run() == 3

def test_runner_exits_4_after_the_unreachable_limit(tmp_path):
    now = [0.0]
    r = AgentRunner(cfg("http://127.0.0.1:9", tmp_path, unreachable_exit_sec=30.0), ServerClient("http://127.0.0.1:9", "t", timeout=0.2),
                    FakeWindow(), session_id=2, pid=1, monotonic=lambda: now[0], sleep=lambda s: now.__setitem__(0, now[0] + s))
    assert r.run() == 4 and now[0] >= 30
```

```python
# agent/tests/test_dialog.py
import ctypes
from pathlib import Path

import pytest

from mcp_agent.dialog import EdgeWindow, PrintWindow, edge_command
from mcp_agent.win32 import current_session_id, idle_seconds

def test_edge_command_line():
    assert edge_command(r"C:\Edge\msedge.exe", "http://127.0.0.1:8700/notice#d=1&t=x", Path(r"C:\p")) == [
        r"C:\Edge\msedge.exe", "--app=http://127.0.0.1:8700/notice#d=1&t=x", r"--user-data-dir=C:\p",
        "--no-first-run", "--no-default-browser-check", "--disable-sync", "--window-size=640,600"]

class FakeProc:
    def __init__(self, pid):
        self.pid, self.code = pid, None
    def poll(self):
        return self.code

def test_edge_window_tracks_user_close_and_our_close(tmp_path):
    procs, killed, topmost = [], [], []
    def popen(argv, **kw):
        procs.append(FakeProc(100 + len(procs))); return procs[-1]
    w = EdgeWindow(r"C:\Edge\msedge.exe", tmp_path, popen=popen, kill_tree=killed.append, make_topmost=lambda pid: topmost.append(pid) or True)
    w.open("http://u/1", 1)
    assert not w.closed_by_user()
    procs[0].code = 0
    assert w.closed_by_user()
    w.open("http://u/2", 2); w.close(); procs[1].code = 1
    assert killed == [101] and not w.closed_by_user()
    assert topmost == [100, 101]  # first attempt is synchronous and succeeded, so no retry thread ran

def test_print_window_lines(tmp_path):
    w = PrintWindow(tmp_path / "u.url"); w.open("http://a", 3); w.close(); w.close()
    assert (tmp_path / "u.url").read_text("utf-8").splitlines() == ["OPEN 3 http://a", "CLOSE 3"] and not w.closed_by_user()

@pytest.mark.winlive
def test_session_id_and_idle_match_the_kernel():
    sid = ctypes.c_ulong()
    assert ctypes.windll.kernel32.ProcessIdToSessionId(ctypes.windll.kernel32.GetCurrentProcessId(), ctypes.byref(sid))
    assert current_session_id() == sid.value and idle_seconds() >= 0
```

- [ ] **Step 3: 실패 확인** — Run(agent): `uv run python -m pytest -v` → FAIL

- [ ] **Step 4: 구현** — 위 Interfaces대로. ctypes 선언에는 `argtypes`/`restype`를 모두 적습니다(64비트 HWND 잘림 방지).

- [ ] **Step 5: 통과 확인** — Run(agent): `uv run python -m pytest -q` → 통과. `uv run python -m pytest -m winlive -q` → 통과. 수동(이 PC): `uv run python -c "from mcp_agent.dialog import find_edge; print(find_edge())"` → msedge.exe 경로(보고서에 붙임).

- [ ] **Step 6: Commit** — `git commit -m "feat(agent): stdlib session agent with token client, long-poll command loop, heartbeat and Edge app-window notice"`

---

### Task 16: 세션 에이전트 — 창 이벤트와 유휴 (SetWinEventHook, 병합, 묶음 전송)

**Files:**
- Create: `agent/mcp_agent/coalesce.py`, `agent/mcp_agent/idle.py`, `agent/mcp_agent/sender.py`, `agent/mcp_agent/hooks.py`, `agent/mcp_agent/pump.py`
- Create: `agent/tests/test_events.py`, `agent/tests/test_hooks.py`
- Modify: `agent/mcp_agent/win32.py`, `agent/mcp_agent/__main__.py` (`on_hello`에서 시작)

**Interfaces:**
- Consumes: Task 12의 이벤트 모델과 `server/tests/fixtures/agent-events.json`(같은 저장소 경로로 읽음), Task 15 `ServerClient`, `AgentRunner(on_hello=...)`.
- Produces:
  - `coalesce.py`: `@dataclass(frozen=True) RawWinEvent(t: float, kind: Literal["foreground", "minimize", "restore", "title"], hwnd: int, pid: int, exe: str | None, title: str, at: datetime)`; `class WindowEventCoalescer(*, fg_merge_sec: float = 0.3, title_merge_sec: float = 1.0, dup_sec: float = 0.3)`:
    - `add(e)`: `foreground` — 보류 중인 foreground가 있고 `e.t − 그것.t < fg_merge_sec`이면 바꿔치기(마지막만 남김). 현재 전경 창 `hwnd`를 갱신합니다. `title` — `e.hwnd`가 현재 전경 창이 아니면 버림; 같은 hwnd의 보류 title이 있으면 바꿔치기(시각은 새 것). `minimize`/`restore` — 같은 hwnd·종류가 `dup_sec` 안에 있었으면 버림, 아니면 그대로.
    - `drain(now: float) -> list[RawWinEvent]`: 병합 창이 닫힌 것(foreground: `t + fg_merge_sec <= now`, title: `t + title_merge_sec <= now`, 나머지 즉시)을 `t` 순으로 내보냅니다. 내보낼 때 foreground는 마지막으로 내보낸 foreground와 `(hwnd, title)`이 같으면 버리고, title은 그 hwnd의 마지막으로 내보낸 제목과 같으면 버립니다.
  - `idle.py`: `class IdleTracker(threshold_sec: float = 300)`: `update(idle_sec: float, at: datetime) -> dict | None` — 활성→유휴(`idle_sec ≥ threshold`) → `{"type": "idle", "at": iso, "idle_sec": int}`; 유휴 중 값이 이전보다 작아짐(입력 발생) → `{"type": "active", "at": iso, "idle_sec": <직전 값 int>}`; 그 밖 None.
  - `sender.py`: `KST = timezone(timedelta(hours=9))`, `iso(at) = at.astimezone(KST).isoformat(timespec="milliseconds")`; `to_event(e: RawWinEvent) -> dict` = `{"type", "at", "pid", "exe", "title"}`; `to_payload(items: list[RawWinEvent | dict]) -> dict` = `{"events": [...]}`; `class EventSender(client: ServerClient, *, events_max: int = 200, buffer_max: int = 2000)`: `add(item)`(가득 차면 가장 오래된 것 버림, `dropped` 증가), `flush() -> None`(`events_max`씩 `POST /api/agent/events`; `ServerUnavailable`이면 남은 것을 그대로 두고 반환), `pending: int`.
  - `pump.py`: `class EventPump(coalescer, sender, idle_tracker, *, idle_seconds: Callable[[], float], idle_every_sec: float = 5.0)`: `on_raw(e)`(훅 스레드에서 호출, 내부 잠금), `step(mono: float, wall: datetime) -> None`(잠금 안에서 `drain(mono)` → `sender.add`; `idle_every_sec`마다 `idle_tracker.update(idle_seconds(), wall)` → 있으면 `sender.add`), `run(stop: threading.Event)`(0.25초마다 `step`, 1초마다 `sender.flush()`).
  - `hooks.py`: `class WinEventHookThread(on_event: Callable[[RawWinEvent], None])`(데몬 스레드): 스레드 안에서 `SetWinEventHook`을 세 번 — `(EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND)`, `(EVENT_SYSTEM_MINIMIZESTART, EVENT_SYSTEM_MINIMIZEEND)`, `(EVENT_OBJECT_NAMECHANGE, EVENT_OBJECT_NAMECHANGE)` — 모두 `WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS`, 콜백은 `WINFUNCTYPE(None, HANDLE, DWORD, HWND, LONG, LONG, DWORD, DWORD)`(참조 유지). NAMECHANGE는 `idObject == OBJID_WINDOW(0)`·`idChild == 0`·`hwnd == GetForegroundWindow()`일 때만. 이벤트마다 `GetWindowTextW`, `GetWindowThreadProcessId`, `QueryFullProcessImageNameW`(`PROCESS_QUERY_LIMITED_INFORMATION`)로 `RawWinEvent`(`t = time.monotonic()`, `at = datetime.now(UTC)`). `GetMessageW` 루프; `stop()`은 `PostThreadMessageW(tid, WM_QUIT)` 후 join(2초) + `UnhookWinEvent`. `wait_ready(timeout) -> bool`, `hook_count: int`(성공한 훅 수).
  - `win32.py` 추가: `window_text(hwnd) -> str`, `window_pid(hwnd) -> int`, `process_image(pid) -> str | None`, `foreground_window() -> int`.
  - `__main__.py`: `on_hello(h)` → `EventSender(client, events_max=h["events_max"])`, `IdleTracker(h["idle_threshold_sec"])`, `EventPump(...)`, `WinEventHookThread(pump.on_raw).start()`, 펌프 스레드 시작. `run()`이 끝나면 훅·펌프를 멈추고 마지막으로 `flush()` 한 번.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# agent/tests/test_events.py
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mcp_agent.client import ServerUnavailable
from mcp_agent.coalesce import RawWinEvent, WindowEventCoalescer
from mcp_agent.idle import IdleTracker
from mcp_agent.pump import EventPump
from mcp_agent.sender import EventSender, to_payload

AT = datetime(2026, 11, 4, 4, 59, 57, tzinfo=UTC)  # 13:59:57 KST

def raw(t, kind="foreground", hwnd=1, title="A", pid=10, exe="a.exe"):
    return RawWinEvent(t, kind, hwnd, pid, exe, title, AT + timedelta(seconds=t))

def test_foreground_burst_keeps_the_last():
    c = WindowEventCoalescer()
    c.add(raw(0.0, hwnd=1, title="A")); c.add(raw(0.1, hwnd=2, title="B")); c.add(raw(0.2, hwnd=3, title="C"))
    assert c.drain(0.4) == [] and [e.title for e in c.drain(0.5)] == ["C"]

def test_refocusing_the_same_window_and_title_is_dropped():
    c = WindowEventCoalescer(); c.add(raw(0, hwnd=1, title="A")); assert len(c.drain(1)) == 1
    c.add(raw(2, hwnd=1, title="A")); assert c.drain(3) == []
    c.add(raw(4, hwnd=1, title="A2")); assert [e.title for e in c.drain(5)] == ["A2"]

def test_title_changes_merge_for_the_foreground_window_only():
    c = WindowEventCoalescer(); c.add(raw(0, hwnd=1, title="doc")); c.drain(1)
    for i, t in enumerate(["doc*", "doc**", "doc***"]):
        c.add(raw(1 + i * 0.2, kind="title", hwnd=1, title=t))
    c.add(raw(1.1, kind="title", hwnd=9, title="background"))
    assert c.drain(2.3) == []
    assert [(e.kind, e.title) for e in c.drain(2.4)] == [("title", "doc***")]

def test_minimize_restore_pass_through_with_dedupe_and_order():
    c = WindowEventCoalescer(); c.add(raw(0, hwnd=1, title="A"))
    c.add(raw(0.5, kind="minimize", hwnd=1)); c.add(raw(0.6, kind="minimize", hwnd=1)); c.add(raw(0.9, kind="restore", hwnd=1))
    assert [e.kind for e in c.drain(1)] == ["foreground", "minimize", "restore"]

def test_idle_transitions():
    i = IdleTracker(threshold_sec=300)
    assert i.update(10, AT) is None and i.update(299, AT) is None
    assert i.update(300, AT) == {"type": "idle", "at": "2026-11-04T13:59:57.000+09:00", "idle_sec": 300}
    assert i.update(420, AT) is None
    assert i.update(2, AT) == {"type": "active", "at": "2026-11-04T13:59:57.000+09:00", "idle_sec": 420}
    assert i.update(5, AT) is None

def test_payload_matches_the_server_fixture():
    fixture = Path(__file__).resolve().parents[2] / "server" / "tests" / "fixtures" / "agent-events.json"
    exe = r"C:\Windows\System32\notepad.exe"
    items = [RawWinEvent(0.0, "foreground", 1, 4321, exe, "메모 - 메모장", AT),
             RawWinEvent(1.5, "title", 1, 4321, exe, "*메모 - 메모장", AT + timedelta(seconds=1.5)),
             RawWinEvent(2.0, "minimize", 1, 4321, exe, "*메모 - 메모장", AT + timedelta(seconds=2)),
             {"type": "idle", "at": "2026-11-04T14:00:00.000+09:00", "idle_sec": 300}]
    assert to_payload(items) == json.loads(fixture.read_text("utf-8"))

class FakeClient:
    def __init__(self, fail=0):
        self.fail, self.posts = fail, []
    def post(self, path, body=None):
        if self.fail:
            self.fail -= 1; raise ServerUnavailable("down")
        self.posts.append((path, [e["idle_sec"] for e in body["events"]]))

def test_sender_batches_and_buffers_while_unavailable():
    client = FakeClient(fail=1); s = EventSender(client, events_max=2, buffer_max=3)
    for n in range(4):
        s.add({"type": "idle", "at": "2026-11-04T14:00:00.000+09:00", "idle_sec": n})
    s.flush()
    assert client.posts == [] and (s.pending, s.dropped) == (3, 1)
    s.flush()
    assert client.posts == [("/api/agent/events", [1, 2]), ("/api/agent/events", [3])] and s.pending == 0

def test_pump_moves_coalesced_events_and_idle_into_the_sender():
    sent = []
    class S:
        def add(self, item): sent.append(item)
    pump = EventPump(WindowEventCoalescer(), S(), IdleTracker(300), idle_seconds=lambda: 301, idle_every_sec=5)
    pump.on_raw(raw(0.0, title="A"))
    pump.step(0.1, AT)
    assert [x["type"] for x in sent] == ["idle"]
    pump.step(0.5, AT)
    assert [getattr(x, "kind", None) or x["type"] for x in sent] == ["idle", "foreground"]
```

```python
# agent/tests/test_hooks.py
import pytest

from mcp_agent.hooks import WinEventHookThread

@pytest.mark.winlive
def test_hook_thread_installs_three_hooks_and_stops():
    got = []; t = WinEventHookThread(got.append); t.start()
    try:
        assert t.wait_ready(2.0) and t.hook_count == 3
    finally:
        t.stop()
    assert not t.is_alive()
```

- [ ] **Step 2: 실패 확인** — Run(agent): `uv run python -m pytest tests/test_events.py -v` → FAIL

- [ ] **Step 3: 구현** — 위 Interfaces대로. 훅 콜백 안에서는 무거운 일을 하지 않고(`process_image`는 pid별 캐시), 예외를 밖으로 던지지 않습니다.

- [ ] **Step 4: 통과 확인** — Run(agent): `uv run python -m pytest -q` → 통과, `uv run python -m pytest -m winlive -q` → 통과. 수동(이 PC, 선택): 서버를 `--session-source wts --collect-console --agent-launcher local --agent-dialog print`로 띄우고 창을 몇 번 바꾼 뒤 `logs/<오늘>.jsonl`에 `activity.window` 줄이 생기는지 확인(보고서에 3줄 붙임).

- [ ] **Step 5: Commit** — `git commit -m "feat(agent): foreground/minimize/title window events with debounce, idle transitions and batched delivery"`

---

### Task 17: 웹 — notice 번들 표시 모드와 보드 세션 카드 보강

**Files:**
- Create: `web/src/notice/NoticeApp.tsx`, `web/src/notice/NoticeApp.test.tsx`, `web/src/notice/source.test.ts`
- Modify: `web/src/notice/source.ts`, `web/src/notice/main.tsx`, `web/src/lib/api-types.ts`, `web/tests/msw/fixtures.ts`, `web/tests/msw/handlers.ts`, `web/src/components/status/SessionCard.tsx`, `web/src/components/status/status.test.tsx`, `web/src/copy/ko.ts`, `web/src/copy/ko.test.ts`

**Interfaces:**
- Consumes: Plan 3 Task 14 `NoticeDialog`, `source.ts`(U16, F18), Task 8 `SessionCard`/`ConnectionBanner`; Task 11 API.
- Produces:
  - `api-types.ts`:
    ```ts
    export interface RdpSession { session_id: number; user: string; domain: string | null; client_name: string | null;
      client_ip: string | null; reverse_dns: string | null; logon_at: string | null; connected_at: string | null;
      state: "active" | "locked"; idle_sec: number | null; resolution: string | null; notice_acknowledged: boolean | null;
      connection_id: number; client_build: number | null; protocol: "rdp" | "console" | "other";
      first_seen_ip: boolean; first_seen_device: boolean }
    export interface NoticeDisplayContent extends NoticeContent { display_id: number; version: number }
    ```
  - `fixtures.ts`: `rdpSession(p?: Partial<RdpSession>): RdpSession`(Plan 3 F17 이름; 기본값 `connection_id: 1, client_build: 26100, protocol: "rdp", first_seen_ip: false, first_seen_device: false, state: "active", notice_acknowledged: null`).
  - `source.ts`(U16 교체):
    ```ts
    export type NoticeSource = { mode: "display"; displayId: number; token: string } | { mode: "preview" };
    export function readNoticeSource(hash: string): NoticeSource          // "#d=<양의 정수>&t=<[A-Za-z0-9_-]{16,128}>" → display, 그 밖 → preview
    export function takeNoticeSource(loc?: Pick<Location, "hash" | "pathname" | "search">, hist?: Pick<History, "replaceState">): NoticeSource
                                                                         // 읽은 뒤 display면 hist.replaceState(null, "", pathname + search)로 토큰을 주소에서 지움
    export interface LoadedNotice extends NoticeContent { version: number | null }
    export class NoticeLoadError extends Error { readonly status: number }
    export function loadNoticeContent(src?: NoticeSource): Promise<LoadedNotice>
    export function notifyHost(message: { type: "notice_ack"; version: number | null }, src?: NoticeSource,
                               opts?: { retryDelaysMs?: readonly number[] }): Promise<boolean>
    ```
    display 모드: `fetch("/api/notice/display/open", {method: "POST", headers: {"X-Notice-Token": token}, credentials: "omit", cache: "no-store"})` → 200이면 `{title, body, button_text, version}`, 아니면 `NoticeLoadError(status)`(fetch 예외는 status 0). `notifyHost`는 `/api/notice/display/ack`에 같은 방식으로 POST, 204 → true, 404 → 바로 false, 그 밖(네트워크·5xx)은 `retryDelaysMs`(기본 `[1000, 2000]`) 간격으로 다시 시도해 모두 실패하면 false. preview 모드는 Plan 3(F18) 동작 그대로이고 `notifyHost`는 `window.chrome?.webview?.postMessage`가 있으면 보내고 true.
  - `NoticeApp({ source }: { source: NoticeSource })`: 불러오는 중(빈 화면, 깜빡임 없음) → `NoticeDialog mode="standalone"` → 확인 클릭 → 버튼 `aria-busy` → 성공: 다이얼로그 닫고 `copy.notice.acknowledged`; 실패: `copy.notice.ackFailed` + `copy.notice.retry` 버튼(누르면 다시 `notifyHost`). 불러오기 404(display) → `copy.notice.displayExpired`, 그 밖 오류 → `copy.notice.loadFailed`. `main.tsx` = `applyStoredTheme()` → `createRoot(...).render(<NoticeApp source={takeNoticeSource()} />)`.
  - `SessionCard` 보강: 상태 `copy.sessions.state[session.state]`, 유휴 `idle_sec >= 60`이면 `copy.sessions.idle(Math.floor(idle_sec / 60))`, 60 미만이거나 null이면 "—"(서버가 분이 바뀔 때만 다시 보내므로 클라이언트에서 초 단위로 세지 않음, V10), 배지 `copy.sessions.firstSeenIp`(`first_seen_ip`), `copy.sessions.firstSeenDevice`(`first_seen_device`)(아이콘 + 글자), 고지 `notice_acknowledged` true → `copy.sessions.noticeAcked`, false → `copy.sessions.noticePending`(주의 색 + 아이콘), null → `copy.sessions.noticeUnknown`. 해상도 `"1920x1080@32"` → `copy.sessions.resolution(w, h, bits)`.
  - `ko.ts`: `board.sessionsNotReady`를 "원격 접속 정보를 아직 받지 못했어요."로 바꿉니다(Plan 4부터 `sessions`가 없다는 것은 수집기가 꺼졌거나 아직 첫 스냅숏 전이라는 뜻). 새 키: `sessions.{title, current, history, failures, collectors, state.{active,locked,disconnected,connected}, firstSeenIp, firstSeenDevice, noticeAcked, noticePending, noticeUnknown, idle(min), resolution(w,h,bits), kinds.{logon,reconnect,existing}, endReasons.{disconnect,logoff,reconnected,service_stop}, ongoing, ackIn(ms), unacked, more, days(n), empty, failuresEmpty, collectorOk, collectorDown(error)}`, `notice.{displayExpired, ackFailed, retry}`, `tamper.{title, empty, events.<Global Constraints의 tamper 이름 13개>}`, `dashboard.tamperTitle`. 어조는 Plan 3 Task 6 ux-copy를 따르고, 새 문구는 `design:ux-copy` 스킬로 한 번 다듬습니다.

- [ ] **Step 1: 실패하는 테스트 작성**

```ts
// web/src/notice/source.test.ts
import { http, HttpResponse } from "msw";
import { server } from "../../tests/msw/server";
import { loadNoticeContent, NoticeLoadError, notifyHost, readNoticeSource, takeNoticeSource } from "./source";

const SRC = { mode: "display", displayId: 12, token: "tok_ABCDEFGHIJKLmnop" } as const;

it("reads the display id and token from the hash", () => {
  expect(readNoticeSource("#d=12&t=tok_ABCDEFGHIJKLmnop")).toEqual(SRC);
  expect(readNoticeSource("")).toEqual({ mode: "preview" });
  expect(readNoticeSource("#d=x&t=tok_ABCDEFGHIJKLmnop")).toEqual({ mode: "preview" });
  expect(readNoticeSource("#d=12&t=short")).toEqual({ mode: "preview" });
});

it("takes the token out of the address bar", () => {
  const replaceState = vi.fn();
  expect(takeNoticeSource({ hash: "#d=12&t=tok_ABCDEFGHIJKLmnop", pathname: "/notice", search: "" }, { replaceState })).toEqual(SRC);
  expect(replaceState).toHaveBeenCalledWith(null, "", "/notice");
});

it("opens the display with the token header", async () => {
  let token: string | null = null;
  server.use(http.post("/api/notice/display/open", ({ request }) => {
    token = request.headers.get("X-Notice-Token");
    return HttpResponse.json({ display_id: 12, version: 3, title: "안내", body: "본문", button_text: "확인" });
  }));
  await expect(loadNoticeContent(SRC)).resolves.toEqual({ title: "안내", body: "본문", button_text: "확인", version: 3 });
  expect(token).toBe("tok_ABCDEFGHIJKLmnop");
});

it("maps a missing display to NoticeLoadError 404", async () => {
  server.use(http.post("/api/notice/display/open", () => HttpResponse.json({ error: "not_found" }, { status: 404 })));
  await expect(loadNoticeContent(SRC)).rejects.toMatchObject({ status: 404 });
  await expect(loadNoticeContent(SRC)).rejects.toBeInstanceOf(NoticeLoadError);
});

it("acknowledges with retries and stops at 404", async () => {
  let calls = 0;
  server.use(http.post("/api/notice/display/ack", () => (++calls < 3 ? HttpResponse.json({ error: "internal" }, { status: 503 }) : new HttpResponse(null, { status: 204 }))));
  await expect(notifyHost({ type: "notice_ack", version: 3 }, SRC, { retryDelaysMs: [0, 0] })).resolves.toBe(true);
  expect(calls).toBe(3);
  calls = 0;
  server.use(http.post("/api/notice/display/ack", () => { calls++; return HttpResponse.json({ error: "not_found" }, { status: 404 }); }));
  await expect(notifyHost({ type: "notice_ack", version: 3 }, SRC, { retryDelaysMs: [0, 0] })).resolves.toBe(false);
  expect(calls).toBe(1);
});
```

```tsx
// web/src/notice/NoticeApp.test.tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { copy } from "@/copy/ko";
import { server } from "../../tests/msw/server";
import { NoticeApp } from "./NoticeApp";

const SRC = { mode: "display", displayId: 12, token: "tok_ABCDEFGHIJKLmnop" } as const;
const open = () => server.use(http.post("/api/notice/display/open", () =>
  HttpResponse.json({ display_id: 12, version: 3, title: "안내 제목", body: "**본문**", button_text: "확인했습니다" })));

it("shows the dialog and the acknowledged message after the button", async () => {
  open(); server.use(http.post("/api/notice/display/ack", () => new HttpResponse(null, { status: 204 })));
  render(<NoticeApp source={SRC} />);
  expect(await screen.findByRole("dialog")).toHaveTextContent("안내 제목");
  await userEvent.click(screen.getByRole("button", { name: "확인했습니다" }));
  expect(await screen.findByText(copy.notice.acknowledged)).toBeInTheDocument();
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("shows the expired message when the display is gone", async () => {
  server.use(http.post("/api/notice/display/open", () => HttpResponse.json({ error: "not_found" }, { status: 404 })));
  render(<NoticeApp source={SRC} />);
  expect(await screen.findByText(copy.notice.displayExpired)).toBeInTheDocument();
});

it("offers a retry when the acknowledgement fails", async () => {
  open(); let ok = false;
  server.use(http.post("/api/notice/display/ack", () => (ok ? new HttpResponse(null, { status: 204 }) : HttpResponse.json({ error: "not_found" }, { status: 404 }))));
  render(<NoticeApp source={SRC} />);
  await userEvent.click(await screen.findByRole("button", { name: "확인했습니다" }));
  expect(await screen.findByText(copy.notice.ackFailed)).toBeInTheDocument();
  ok = true; await userEvent.click(screen.getByRole("button", { name: copy.notice.retry }));
  expect(await screen.findByText(copy.notice.acknowledged)).toBeInTheDocument();
});
```

```tsx
// web/src/components/status/status.test.tsx (추가)
it("SessionCard shows first-seen badges, lock state, idle minutes and a pending notice", () => {
  render(<SessionCard session={rdpSession({ first_seen_ip: true, first_seen_device: false, state: "locked", notice_acknowledged: false, idle_sec: 125, resolution: "1920x1080@32" })} />);
  expect(screen.getByText(copy.sessions.firstSeenIp)).toBeInTheDocument();
  expect(screen.queryByText(copy.sessions.firstSeenDevice)).toBeNull();
  expect(screen.getByText(copy.sessions.state.locked)).toBeInTheDocument();
  expect(screen.getByText(copy.sessions.idle(2))).toBeInTheDocument();
  expect(screen.getByText(copy.sessions.noticePending)).toBeInTheDocument();
  expect(screen.getByText(copy.sessions.resolution(1920, 1080, 32))).toBeInTheDocument();
});
it.each([[true, "noticeAcked"], [null, "noticeUnknown"]] as const)("SessionCard notice state %s", (value, key) => {
  render(<SessionCard session={rdpSession({ notice_acknowledged: value })} />);
  expect(screen.getByText(copy.sessions[key])).toBeInTheDocument();
});
```

```ts
// web/src/copy/ko.test.ts (추가)
it("names every tamper event", () => {
  const names = ["agent_exited", "agent_unresponsive", "agent_restart_storm", "agent_impersonation", "notice_token_misuse",
    "script_hash_mismatch", "script_file_changed", "script_file_missing", "log_file_removed", "log_file_truncated",
    "audit_policy_changed", "log_cleared", "audit_config_changed"];
  for (const n of names) expect(copy.tamper.events[n as keyof typeof copy.tamper.events]).toMatch(/\S/);
});
```

- [ ] **Step 2: 실패 확인** — Run: `pnpm test` → FAIL

- [ ] **Step 3: 구현** — 위 Interfaces대로. notice 번들은 여전히 React·react-dom·자기 파일만 씁니다(`fetch` 직접 사용, Query·Motion·Radix 없음).

- [ ] **Step 4: 통과 확인** — Run: `pnpm typecheck && pnpm lint && pnpm test && pnpm build && pnpm test:budget` → 통과(notice < 100KB, 보드 < 200KB).

- [ ] **Step 5: Commit** — `git commit -m "feat(web): notice display mode with token open/ack and retry; richer session cards"`

---

### Task 18: 웹 — 세션 화면, 대시보드 우회 탐지 카드, 내비 개방

**Files:**
- Create: `docs/design/screens/sessions.md`
- Create: `web/src/admin/sessions/SessionsPage.tsx`, `web/src/admin/sessions/sessions.test.tsx`, `web/src/admin/dashboard/TamperCard.tsx`
- Modify: `web/tests/render.tsx`(`renderWithProviders`가 `{ router, store, qc }`를 돌려주지 않으면 이 Task에서 반환값을 더함), `web/src/admin/router.tsx` (`/admin/sessions`), `web/src/admin/shell/Nav.tsx`, `web/src/admin/shell/shell.test.tsx`, `web/src/admin/dashboard/DashboardPage.tsx`, `web/src/admin/dashboard/DashboardPage.test.tsx`, `web/src/admin/query-keys.ts`, `web/src/admin/queries.ts`, `web/src/admin/live.ts`, `web/src/lib/endpoints.ts`, `web/src/lib/api-types.ts`, `web/src/lib/board-store.ts`, `web/src/lib/board-store.test.ts`, `web/tests/msw/fixtures.ts`, `web/tests/msw/handlers.ts`, `web/src/copy/ko.ts`

**Interfaces:**
- Consumes: Task 5 `/api/sessions/{current,history,collectors}`, Task 6 `/api/tamper/recent` + SSE `tamper`, Task 17 `SessionCard`·문구.
- Produces:
  - `api-types.ts`:
    ```ts
    export interface CurrentSession { session_id: number; user: string; domain: string | null; state: "active" | "locked" | "disconnected" | "connected";
      client_name: string | null; client_ip: string | null; protocol: "rdp" | "console" | "other"; logon_at: string | null;
      connected_at: string | null; disconnected_at: string | null; idle_sec: number | null; connection_id: number | null }
    export interface ConnectionNotice { version: number; attempts: number; first_shown_at: string | null; acknowledged_at: string | null;
      ack_ms: number | null; closed_reason: "acknowledged" | "superseded" | "logoff" | "service_restart" | null }
    export interface SessionConnection { id: number; session_id: number; user: string; domain: string | null; client_name: string | null;
      client_ip: string | null; reverse_dns: string | null; client_build: number | null; protocol: "rdp" | "console" | "other";
      resolution: string | null; kind: "logon" | "reconnect" | "existing"; logon_at: string | null; connected_at: string;
      ended_at: string | null; end_reason: "disconnect" | "logoff" | "reconnected" | "service_stop" | null;
      first_seen_ip: boolean; first_seen_device: boolean; notice: ConnectionNotice | null }
    export interface LogonFailure { id: number; at: string; user: string | null; domain: string | null; client_ip: string | null;
      workstation: string | null; logon_type: number | null; status: string | null; sub_status: string | null; source: string }
    export interface SessionsHistory { connections: SessionConnection[]; failures: LogonFailure[]; next_before_id: number | null }
    export interface CollectorStatus { name: string; ok: boolean; error: string | null; since: string }
    export type TamperEventName = "agent_exited" | "agent_unresponsive" | "agent_restart_storm" | "agent_impersonation" | "notice_token_misuse"
      | "script_hash_mismatch" | "script_file_changed" | "script_file_missing" | "log_file_removed" | "log_file_truncated"
      | "audit_policy_changed" | "log_cleared" | "audit_config_changed";
    export interface TamperEvent { at: string; event: TamperEventName; [field: string]: unknown }
    ```
  - `endpoints.ts`: `sessionsCurrent(): Promise<{ ready: boolean; sessions: CurrentSession[] }>`, `sessionsHistory(days: number, beforeId?: number): Promise<SessionsHistory>`, `collectorsStatus(): Promise<CollectorStatus[]>`, `tamperRecent(limit?: number): Promise<TamperEvent[]>`.
  - `query-keys.ts`: `sessionsCurrent: ["sessions", "current"]`, `sessionsHistory: (days) => ["sessions", "history", days]`, `collectors: ["sessions", "collectors"]`, `tamper: ["tamper"]`. `queries.ts`: `useSessionsCurrent()`, `useSessionsHistory(days)`(TanStack `useInfiniteQuery`, `getNextPageParam = p => p.next_before_id ?? undefined`), `useCollectors()`, `useTamperRecent()` — 모두 `enabled: can(me, "view_session_history")`(tamper는 `view_logs`).
  - `board-store.ts`: `onTamper(fn: (e: TamperEvent) => void): () => void`; `apply`의 `tamper` 이벤트 → 리스너. `live.ts`: `sessions` 이벤트 → `qk.sessionsCurrent` invalidate, `tamper` → `qk.tamper` 앞에 넣기(최대 50).
  - 라우트 `/admin/sessions`(search `days?: 1 | 7 | 30 | 90`, 기본 7) → `SessionsPage`, 로그인 필요. 게이트 `view_session_history`(두 채널 — Local 전용이 아님). `Nav`의 세션 항목은 더 이상 `planned_sessions`가 아니라 `denyReason(me, "view_session_history")`를 씁니다(`DisabledReason`의 `planned_sessions`는 타입에 남기되 쓰지 않음, V31).
  - `SessionsPage`: ① 현재 세션(`useSessionsCurrent`, 끊긴 세션 포함, 카드 = `SessionCard`(보드 세션은 BoardStore에서, 끊긴 세션은 상태 줄만)) ② 접속 이력 표(TanStack Table, 애니메이션 없음): 접속 시각(KST), 사용자(`DOMAIN\user`), 클라이언트 PC, IP(+PTR 작은 글씨), 종류(`copy.sessions.kinds`), 종료(시각 + `endReasons`, 진행 중이면 `copy.sessions.ongoing`), 처음 보는 IP·기기 배지, 고지(`notice`가 acknowledged면 `copy.sessions.ackIn(ack_ms)`, 열려 있거나 다른 사유로 닫혔으면 `copy.sessions.unacked`, null이면 "—"); "더 보기" = 다음 페이지(`before_id`) ③ 로그인 실패 표(시각, 사용자, IP, 워크스테이션, 로그온 유형, 상태 코드) ④ 수집 상태(이름, 정상/중단 + 오류, 시각). 기간 선택(1·7·30·90일) → URL `?days=`.
  - `TamperCard`(대시보드 "우회 탐지 이벤트" 카드, `PlannedFeature planned_logs`를 대체): `useTamperRecent()` 최근 10개(아이콘 + `copy.tamper.events[event]` + KST 시각 + 세션/사용자 요약), 비면 `copy.tamper.empty`. "로그인 실패 추이"는 그대로 `PlannedFeature planned_logs`(Plan 5).
  - `fixtures.ts`: `currentSessionFixture(p?)`, `connectionFixture(p?)`, `failureFixture(p?)`, `sessionsHistoryFixture(p?)`, `collectorFixture(p?)`, `tamperFixture(p?)`; `handlers.ts` 기본 핸들러 4개.
  - `docs/design/screens/sessions.md`: `frontend-design` 스킬로 세션 화면(1366px·360px, dark/light, 표 밀도, 미확인 고지·처음 보는 IP 강조 방식, 빈 상태)을 정하고 Playwright 플러그인 확인 체크 목록을 채웁니다.

- [ ] **Step 1: `frontend-design` 스킬로 세션 화면 설계** — 입력: §6.4 #3, Plan 3 `docs/design/direction.md`·`screens/mcp.md`, 위 Interfaces. 출력: `docs/design/screens/sessions.md`.

- [ ] **Step 2: 실패하는 테스트 작성**

```tsx
// web/src/admin/sessions/sessions.test.tsx (renderWithProviders: Plan 3 F17의 web/tests/render.tsx)
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { copy } from "@/copy/ko";
import { connectionFixture, currentSessionFixture, failureFixture, meFixture, sessionsHistoryFixture, collectorFixture } from "../../../tests/msw/fixtures";
import { server } from "../../../tests/msw/server";
import { renderWithProviders } from "../../../tests/render";

it("lists current sessions including disconnected ones", async () => {
  server.use(http.get("/api/sessions/current", () => HttpResponse.json({ ready: true, sessions: [
    currentSessionFixture({ session_id: 2, state: "active" }), currentSessionFixture({ session_id: 3, user: "kim", state: "disconnected" })] })));
  renderWithProviders({ me: meFixture("developer", "external"), route: "/admin/sessions" });
  expect(await screen.findByText(copy.sessions.state.disconnected)).toBeInTheDocument();
});

it("shows history with kinds, first-seen badges and notice status", async () => {
  server.use(http.get("/api/sessions/history", () => HttpResponse.json(sessionsHistoryFixture({ connections: [
    connectionFixture({ id: 9, kind: "reconnect", first_seen_ip: true, notice: { version: 0, attempts: 1, first_shown_at: "2026-11-04T14:00:00.000+09:00",
      acknowledged_at: "2026-11-04T14:00:02.000+09:00", ack_ms: 2000, closed_reason: "acknowledged" } }),
    connectionFixture({ id: 8, kind: "logon", notice: { version: 0, attempts: 2, first_shown_at: null, acknowledged_at: null, ack_ms: null, closed_reason: "superseded" } })] }))));
  renderWithProviders({ me: meFixture("developer", "local"), route: "/admin/sessions" });
  const rows = await screen.findAllByTestId("connection-row");
  expect(within(rows[0]!).getByText(copy.sessions.kinds.reconnect)).toBeInTheDocument();
  expect(within(rows[0]!).getByText(copy.sessions.firstSeenIp)).toBeInTheDocument();
  expect(within(rows[0]!).getByText(copy.sessions.ackIn(2000))).toBeInTheDocument();
  expect(within(rows[1]!).getByText(copy.sessions.unacked)).toBeInTheDocument();
});

it("loads more with before_id", async () => {
  const seen: (string | null)[] = [];
  server.use(http.get("/api/sessions/history", ({ request }) => {
    const before = new URL(request.url).searchParams.get("before_id"); seen.push(before);
    return HttpResponse.json(before ? sessionsHistoryFixture({ connections: [connectionFixture({ id: 1 })], next_before_id: null })
                                    : sessionsHistoryFixture({ connections: [connectionFixture({ id: 5 })], next_before_id: 5 }));
  }));
  renderWithProviders({ me: meFixture("developer", "local"), route: "/admin/sessions" });
  await userEvent.click(await screen.findByRole("button", { name: copy.sessions.more }));
  expect(await screen.findAllByTestId("connection-row")).toHaveLength(2);
  expect(seen).toEqual([null, "5"]);
  expect(screen.queryByRole("button", { name: copy.sessions.more })).toBeNull();
});

it("shows logon failures and collector problems", async () => {
  server.use(
    http.get("/api/sessions/history", () => HttpResponse.json(sessionsHistoryFixture({ failures: [failureFixture({ client_ip: "203.0.113.9", status: "0xc000006d" })] }))),
    http.get("/api/sessions/collectors", () => HttpResponse.json([collectorFixture({ name: "eventlog:security", ok: false, error: "access denied" })])));
  renderWithProviders({ me: meFixture("developer", "local"), route: "/admin/sessions" });
  expect(await screen.findByText("203.0.113.9")).toBeInTheDocument();
  expect(await screen.findByText(copy.sessions.collectorDown("access denied"))).toBeInTheDocument();
});

it("changes the period through the URL", async () => {
  const days: (string | null)[] = [];
  server.use(http.get("/api/sessions/history", ({ request }) => {
    days.push(new URL(request.url).searchParams.get("days")); return HttpResponse.json(sessionsHistoryFixture());
  }));
  const { router } = renderWithProviders({ me: meFixture("developer", "local"), route: "/admin/sessions" });
  await userEvent.click(await screen.findByRole("button", { name: copy.sessions.days(30) }));
  expect(router.state.location.search).toEqual({ days: 30 });
  await vi.waitFor(() => expect(days).toContain("30"));
  expect(days[0]).toBe("7");
});
```

```tsx
// web/src/admin/shell/shell.test.tsx (갱신)
it("opens the sessions nav item for developers on both channels and gates it for anonymous", () => {
  renderShell(meFixture("developer", "external"));
  expect(screen.getByRole("link", { name: copy.nav.sessions })).not.toHaveAttribute("aria-disabled");
});
// 기존 "shows planned and forbidden nav items disabled with reasons"의 목록에서 [copy.nav.sessions, "planned_sessions"]를 뺍니다.
```

```tsx
// web/src/admin/dashboard/DashboardPage.test.tsx (갱신)
it("shows recent tamper events and prepends live ones", async () => {
  server.use(http.get("/api/tamper/recent", () => HttpResponse.json([tamperFixture({ event: "log_cleared", at: "2026-11-04T13:00:00.000+09:00" })])));
  const { store } = renderDashboard({ mcps: [item(1, "HEALTHY")], activity: activityFixture() });
  expect(await screen.findByText(copy.tamper.events.log_cleared)).toBeInTheDocument();
  act(() => store.apply({ event: "tamper", data: JSON.stringify(tamperFixture({ event: "agent_exited" })) }));
  expect(await screen.findByText(copy.tamper.events.agent_exited)).toBeInTheDocument();
  expect(screen.getAllByText(copy.deny.planned_logs)).toHaveLength(1);
});
it("current-session card follows the board sessions (Plan 3 contract)", async () => {
  const { store } = renderDashboard({ mcps: [item(1, "HEALTHY")], activity: activityFixture() });
  act(() => store.apply(boardEvent({ mcps: [item(1, "HEALTHY")], sessions: [rdpSession({ user: "hong", notice_acknowledged: true })] })));
  expect(await screen.findByText(copy.board.connected)).toBeInTheDocument();
  expect(screen.getByText(copy.sessions.noticeAcked)).toBeInTheDocument();
  act(() => store.apply({ event: "sessions", data: '{"sessions":[]}' }));
  expect(await screen.findByText(copy.board.noSession)).toBeInTheDocument();
});
```

```ts
// web/src/lib/board-store.test.ts (추가)
it("routes tamper events to listeners", () => {
  const s = new BoardStore(); const fn = vi.fn(); s.onTamper(fn);
  s.apply({ event: "tamper", data: JSON.stringify(tamperFixture({ event: "log_cleared" })) });
  expect(fn).toHaveBeenCalledWith(tamperFixture({ event: "log_cleared" }));
});
```

- [ ] **Step 3: 실패 확인** — Run: `pnpm test` → FAIL

- [ ] **Step 4: 구현** — 위 Interfaces대로. 표에는 애니메이션이 없습니다. 미확인 고지·처음 보는 IP는 색만으로 구분하지 않습니다(아이콘 + 글자).

- [ ] **Step 5: 통과 확인** — Run: `pnpm typecheck && pnpm lint && pnpm test && pnpm build && pnpm test:budget` → 통과.

- [ ] **Step 6: Playwright 플러그인으로 화면 검증** — 서버를 `--session-source json:<scratch>/s.json --agent-launcher none --activity off --dev-otp-code 246810 --external-host 127.0.0.1`로 띄우고 `s.json`에 세션 2개(하나는 끊김)를 넣어 `/admin/sessions`, 대시보드, 보드를 1366px·360px, dark/light, reduced-motion에서 확인합니다. `sessions.md` 끝에 체크 목록(`dark ✓ light ✓ reduced-motion ✓ 360px ✓ 1366px ✓`, 고친 점).

- [ ] **Step 7: Commit** — `git commit -m "feat(web): sessions page with history, failures and collector status; dashboard tamper card; open sessions nav"`

---
### Task 19: 통합·E2E — 실제 에이전트, 2초 기준, 재연결 고지, 에이전트 종료 재기동

**Files:**
- Create: `server/tests/test_integration_agent.py`
- Create: `web/e2e/sessions.ts`, `web/e2e/sessions.spec.ts`, `web/e2e/notice-display.spec.ts`
- Modify: `web/e2e/backend.ts`, `web/e2e/board.spec.ts`(Plan 3: `sessionsNotReady` → `noSession`), `web/e2e/a11y.spec.ts`(`/admin/sessions` 추가)

**Interfaces:**
- Consumes: Task 1–18 전부. Plan 3 Task 15 `startBackend`/`BackendState`/`adminApi`/`loginAs`.
- Produces:
  - `backend.ts`: 서버를 띄우기 전에 `<root>/sessions.json`에 `{"sessions": []}`을 쓰고, 인자에 `--session-source json:<root>/sessions.json --agent-launcher local --agent-dialog print --activity off`를 더합니다(에이전트 URL 파일은 `<root>/run/agent-<세션 ID>.url`).
  - `web/e2e/sessions.ts`: `rdp(p?: Record<string, unknown>)`(기본 `{session_id: "self", user: "hong", domain: "CORP", client_ip: "10.0.3.21", client_name: "HONG-LAPTOP", logon_at: "2026-11-04T13:00:00+09:00", connected_at: <지금 ISO>, state: "active"}`), `setSessions(s: BackendState, sessions: unknown[]): Promise<void>`(임시 파일에 쓰고 `rename`), `noticeOpens(s): Promise<{ id: number; url: string }[]>`(`<root>/run/agent-*.url`의 `OPEN <id> <url>` 줄), `waitForNoticeUrl(s, n: number, timeoutMs = 20_000): Promise<string>`(OPEN 줄이 n개가 될 때까지 기다려 n번째 URL), `logEvents(s, cat: string): Promise<Record<string, unknown>[]>`(`<root>/logs/*.jsonl` 전체에서 `cat`).
  - 서버 통합 테스트는 같은 프로세스에서 `live_app`으로 Local 앱을 띄우고, 실제 `PsutilPeerResolver`·`LocalLauncher`·`python -m mcp_agent --dialog print`를 씁니다(테스트 프로세스와 에이전트가 같은 Windows 세션이므로 피어 검증이 실제로 동작합니다).

- [ ] **Step 1: 사전 준비** — Run(agent): `uv sync`. Run(web): `pnpm build`. Run(dummy-mcps): `uv sync`.

- [ ] **Step 2: 실패하는 테스트 작성**

```python
# server/tests/test_integration_agent.py
import asyncio
import json
import os
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from app.activity.agent_supervisor import AgentOptions
from app.clock import SystemClock
from app.collect.config import CollectorConfig
from app.services import build_services
from app.sessions.jsonsource import JsonFileWtsSource
from app.web.app_factory import create_app
from app.win.ffi import current_session_id
from app.win.launch import LocalLauncher
from app.win.peer import PsutilPeerResolver
from tests.live import live_app

pytestmark = pytest.mark.integration
REPO = Path(__file__).resolve().parents[2]

def write_sessions(path, *sessions):
    tmp = path.with_suffix(".tmp"); tmp.write_text(json.dumps({"sessions": list(sessions)}), "utf-8"); os.replace(tmp, path)

def rdp(**kw):
    base = {"session_id": "self", "user": "hong", "domain": "CORP", "client_ip": "10.0.3.21", "client_name": "HONG-LAPTOP",
            "logon_at": "2026-11-04T13:00:00+09:00", "connected_at": "2026-11-04T13:00:00+09:00", "state": "active"}
    base.update(kw); return base

def opens(url_file):
    return [line for line in (url_file.read_text("utf-8").splitlines() if url_file.exists() else []) if line.startswith("OPEN ")]

async def wait(pred, timeout=20.0):
    loop = asyncio.get_running_loop(); end = loop.time() + timeout
    while not pred():
        assert loop.time() < end, "timed out"
        await asyncio.sleep(0.1)

async def events(svc, cat):
    await svc.log.flush()
    out = []
    for f in sorted(svc.paths.logs_dir.glob("*.jsonl")):
        out += [e for e in map(json.loads, f.read_text("utf-8").splitlines()) if e["cat"] == cat]
    return out

@pytest.fixture
async def stack(tmp_path):
    sessions = tmp_path / "sessions.json"; write_sessions(sessions)
    run = tmp_path / "run"; run.mkdir()
    cfg = CollectorConfig(wts=JsonFileWtsSource(sessions, SystemClock()), poll_interval_sec=0.2, launcher=LocalLauncher(),
                          agent=AgentOptions(dialog="print", url_dir=run, agent_dir=REPO / "agent", backoff=(0.5, 1, 2),
                                             exit_grace_sec=1.0, tick_sec=0.2))
    svc = build_services(tmp_path, collectors=cfg, peer_resolver=PsutilPeerResolver())
    await svc.log.start(); await svc.monitor.start(run_loops=False)
    try:
        async with live_app(create_app("local", svc)) as base:
            svc.agents.configure(base); svc.agent_supervisor.configure(base)
            await svc.collectors.start()
            try:
                await wait(lambda: svc.sessions.ready)
                yield svc, base, sessions, run / f"agent-{current_session_id()}.url"
            finally:
                await svc.collectors.stop()
    finally:
        await svc.monitor.stop(); await svc.log.stop(); svc.db.close()

async def test_real_agent_shows_and_acknowledges_notice(stack):
    svc, base, sessions, url_file = stack
    write_sessions(sessions, rdp())
    await wait(lambda: len(opens(url_file)) == 1)
    token = parse_qs(urlsplit(opens(url_file)[0].split(" ", 2)[2]).fragment)["t"][0]
    async with httpx.AsyncClient(base_url=base) as c:
        assert (await c.post("/api/notice/display/open", headers={"X-Notice-Token": token})).status_code == 200
        assert (await c.post("/api/notice/display/ack", headers={"X-Notice-Token": token})).status_code == 204
    await wait(lambda: "CLOSE" in url_file.read_text("utf-8"))
    assert [e["event"] for e in await events(svc, "notice")] == ["notice_shown", "notice_acknowledged"]
    assert svc.sessions.board_sessions()[0]["notice_acknowledged"] is True

async def test_killing_the_agent_relaunches_it_and_reshows_pending_notice(stack):
    svc, base, sessions, url_file = stack
    write_sessions(sessions, rdp())
    await wait(lambda: len(opens(url_file)) == 1)
    sid = current_session_id(); first_pid = svc.agents.slot(sid).pid
    subprocess.run(["taskkill", "/PID", str(first_pid), "/T", "/F"], capture_output=True, check=True)
    await wait(lambda: any(r["event"] == "agent_exited" for r in svc.tamper.recent()))
    await wait(lambda: len(opens(url_file)) == 2)
    assert svc.agents.slot(sid).pid not in (None, first_pid)
    assert "agent_exited" in [e["reason"] for e in await events(svc, "notice") if e["event"] == "notice_unacknowledged"]

async def test_reconnect_reshows_notice(stack):
    svc, base, sessions, url_file = stack
    write_sessions(sessions, rdp())
    await wait(lambda: len(opens(url_file)) == 1)
    write_sessions(sessions, rdp(state="disconnected"))
    await wait(lambda: svc.sessions.board_sessions() == [])
    write_sessions(sessions, rdp(connected_at="2026-11-04T13:30:00+09:00"))
    await wait(lambda: len(opens(url_file)) == 2)
    d1, d2 = (int(line.split()[1]) for line in opens(url_file))
    assert d1 != d2 and svc.displays.get(d1).closed_reason == "superseded" and svc.displays.get(d2).kind == "reconnect"
    assert [e["kind"] for e in await events(svc, "session") if e["event"] == "connect"] == ["logon", "reconnect"]
```

```ts
// web/e2e/sessions.spec.ts
import { expect } from "@playwright/test";
import { copy } from "../src/copy/ko";
import { test } from "./fixtures";
import { rdp, setSessions } from "./sessions";

test.afterEach(async ({ state }) => { await setSessions(state, []); });

test("board shows 접속 중 within 2 s of an RDP connection and clears on logoff", async ({ page, state }) => {
  await page.goto(`${state.externalUrl}/`);
  await expect(page.getByText(copy.board.noSession)).toBeVisible();
  await setSessions(state, [rdp({ session_id: 42, client_ip: "10.0.3.21" })]); // not this session: no agent, board only
  await expect(page.getByText(copy.board.connected)).toBeVisible({ timeout: 2_000 });
  await expect(page.getByText("10.0.3.21")).toBeVisible();
  await setSessions(state, []);
  await expect(page.getByText(copy.board.noSession)).toBeVisible({ timeout: 2_000 });
});

test("a developer sees the connection history on the remote channel", async ({ page, state, loginAs }) => {
  await setSessions(state, [rdp({ session_id: 43, user: "kim" })]);
  await loginAs(page, "dev", "external");
  await page.goto(`${state.externalUrl}/admin/sessions`);
  await expect(page.getByTestId("connection-row").filter({ hasText: "kim" }).first()).toBeVisible({ timeout: 5_000 });
});
```

```ts
// web/e2e/notice-display.spec.ts
import { expect } from "@playwright/test";
import { copy } from "../src/copy/ko";
import { adminApi, test } from "./fixtures";
import { logEvents, noticeOpens, rdp, setSessions, waitForNoticeUrl } from "./sessions";

test.afterEach(async ({ state }) => { await setSessions(state, []); });

test("each connection shows the notice and the acknowledgement is recorded", async ({ page, context, state, request }) => {
  const before = (await noticeOpens(state)).length;
  const current = await (await (await adminApi(request, state)).get("/api/notice")).json();
  await setSessions(state, [rdp()]);
  const notice = await context.newPage();
  await notice.goto(await waitForNoticeUrl(state, before + 1));
  await expect(notice.getByRole("dialog")).toContainText(current.title);
  expect(new URL(notice.url()).hash).toBe("");
  await notice.getByRole("button", { name: current.button_text }).click();
  await expect(notice.getByText(copy.notice.acknowledged)).toBeVisible();
  await page.goto(`${state.externalUrl}/`);
  await expect(page.getByText(copy.sessions.noticeAcked)).toBeVisible({ timeout: 2_000 });
  await expect.poll(async () => (await logEvents(state, "notice")).map((e) => e.event))
    .toEqual(expect.arrayContaining(["notice_shown", "notice_acknowledged"]));
});

test("reconnect shows the notice again", async ({ context, state, request }) => {
  const api = await adminApi(request, state);
  const before = (await noticeOpens(state)).length;
  await setSessions(state, [rdp({ connected_at: "2026-11-04T13:00:00+09:00" })]);
  await waitForNoticeUrl(state, before + 1);
  await setSessions(state, [rdp({ state: "disconnected", connected_at: "2026-11-04T13:00:00+09:00" })]);
  await expect.poll(async () => (await (await api.get("/api/sessions/current")).json()).sessions.map((s: { state: string }) => s.state))
    .toEqual(["disconnected"]);
  await setSessions(state, [rdp({ connected_at: "2026-11-04T13:30:00+09:00" })]);
  const p = await context.newPage();
  await p.goto(await waitForNoticeUrl(state, before + 2));
  await p.getByRole("dialog").getByRole("button").click();
  await expect(p.getByText(copy.notice.acknowledged)).toBeVisible();
  const shown = (await logEvents(state, "notice")).filter((e) => e.event === "notice_shown");
  expect(shown.at(-1)?.kind).toBe("reconnect");
});
```

- [ ] **Step 3: 실패 확인** — Run(server): `uv run python -m pytest -m integration tests/test_integration_agent.py -v` → FAIL(구현 전이면). Run(web): `pnpm e2e --project chromium-dark sessions.spec.ts notice-display.spec.ts` → FAIL.

- [ ] **Step 4: 구현** — 위 Interfaces대로 E2E 헬퍼와 백엔드 인자를 바꿉니다. 실패하면 서버 로그(`<root>/logs/*.jsonl`의 `system` `agent.*`·`collector.*`, 백엔드 stdout)로 원인을 찾아 해당 Task 코드를 고칩니다. 대기 시간을 늘려서 통과시키지 않습니다(2초 기준은 바꾸지 않음).

- [ ] **Step 5: 통과 확인** — Run(server): `uv run python -m pytest -m integration -q` → 통과(기존 integration 포함). Run(web): `pnpm e2e` → 전체 통과, 콘솔 오류 0.

- [ ] **Step 6: Commit** — `git commit -m "test: real-agent integration (notice ack, kill-relaunch, reconnect) and E2E for the 2-second board and per-connection notice"`

---

### Task 20: Win 11 Pro 실기기 점검표, 문서 정리, 최종 검증

**Files:**
- Create: `docs/verification/win11-pro-p4-p5.md`
- Modify: `docs/PLAN.md`, `docs/superpowers/plans/carry-forward.md`

- [ ] **Step 1: 실기기 점검표 작성** — `docs/verification/win11-pro-p4-p5.md`. 이 PC(Home)에서는 실행할 수 없으므로 모든 결과 칸은 `대기`입니다. 구성:
  1. **준비**: Windows 11 Pro 실기기 또는 VM, 계정 2개(관리자 1, RDP용 **표준 사용자** `hong`), RDP 허용. 감사 정책(관리자 PowerShell): `auditpol /set /subcategory:"Process Creation" /success:enable`, `auditpol /set /subcategory:"Logon" /success:enable /failure:enable`, `auditpol /set /subcategory:"Logoff" /success:enable`, `auditpol /set /subcategory:"Other Logon/Logoff Events" /success:enable`, `auditpol /set /subcategory:"Audit Policy Change" /success:enable`, `reg add HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System\Audit /v ProcessCreationIncludeCmdLine_Enabled /t REG_DWORD /d 1 /f`, `reg add HKLM\SOFTWARE\Policies\Microsoft\Windows\PowerShell\ScriptBlockLogging /v EnableScriptBlockLogging /t REG_DWORD /d 1 /f`(Plan 5 `install.ps1`이 같은 일을 하게 됩니다). 저장소 복사, `uv sync`(server·agent), `pnpm build`.
  2. **실행 방식 A(간단)**: RDP로 `hong`이 아닌 관리자 계정으로 접속해 관리자 PowerShell에서 `uv run python -m app --root C:\mcpmon --agent-launcher local`(에이전트는 그 RDP 세션에만 뜸). **실행 방식 B(서비스와 같은 권한)**: 관리자 PowerShell에서 `schtasks /create /tn mcpmon-p4 /ru SYSTEM /sc onstart /tr "<repo>\server\.venv\Scripts\python.exe -m app --root C:\mcpmon --static-dir <repo>\web\dist"` 후 `schtasks /run /tn mcpmon-p4`(SYSTEM → `WtsLauncher`, 표준 사용자 `hong`의 세션에 에이전트). 점검 후 `schtasks /delete /tn mcpmon-p4 /f`.
  3. **항목**(각 행: 절차 / 기대 / 결과 `대기` / 비고):
     - P4-1 다른 PC에서 `hong`으로 RDP 접속 → 2초 안에 보드 `● 접속 중`과 카드(사용자·도메인·클라이언트 PC명·IP 전체·PTR·접속 시각·해상도·고지 상태) — §11 P4 완료 기준
     - P4-2 연결 끊기 → 보드 `○ 접속자 없음`, 세션 화면 이력 `disconnect`; P4-3 다시 연결 → `reconnect`; P4-4 로그오프 → `logoff`
     - P4-5 잘못된 암호로 RDP 시도 → 세션 화면 로그인 실패 표(4625), `session` `logon_failed`
     - P4-6 `session` 로그에 1149·21·24·25·4624(유형 10)·4778·4779 줄이 이벤트 시각으로 남음
     - P4-7 IPv6로 접속(가능하면) → `client_ip`가 올바른 IPv6(V9 `raw[2:18]` 확인)
     - P4-8 처음 보는 IP·기기 배지가 첫 접속에만 표시
     - P5-1 로그온·재연결마다 고지 창이 화면 중앙 최상위로 뜸, Edge 첫 실행 화면 없음, 창이 뜨고 내용 표시까지 < 300ms(§15) — §11 P5 완료 기준
     - P5-2 확인 → `notice_acknowledged`(경과 ms), 보드·세션 화면에 확인 표시; P5-3 창의 X로 닫기 → 1초 뒤 다시 뜸, `notice_unacknowledged`(`window_closed`)
     - P5-4 작업 관리자에서 에이전트(`python.exe … mcp_agent`) 종료 → `tamper` `agent_exited`, 수 초 안에 재기동, 확인 전이었다면 고지 재표시 — §11 P5 완료 기준
     - P5-5 표준 사용자 `hong`의 PowerShell에서 에이전트 토큰을 다른 세션(콘솔 관리자)으로 복사해 `/api/agent/heartbeat` 호출 → 403, `agent_impersonation`
     - P5-6 메모장 실행·종료 → `activity.process` start/stop(방식 B에서 `source: "wmi:trace"`, 명령줄 포함)
     - P5-7 `cmd /c dir`, `cmd /c deploy.bat`, cmd에서 `ping` → `activity.command`(4688; `dir`의 내부 명령 자체는 없음, §2 #7); P5-8 PowerShell에서 `Get-Process | Select -First 1` → `script_block`(4104)
     - P5-9 창 전환·최소화·제목 변경 → `activity.window`(병합되어 과도하지 않음); P5-10 5분 유휴 → `activity.idle` `idle`, 입력 → `active`
     - P5-11 `auditpol /set /subcategory:"Process Creation" /success:disable` → `audit_policy_changed`(4719); `wevtutil cl Application` → `log_cleared`(System 104); 레지스트리 `ProcessCreationIncludeCmdLine_Enabled` 0 → 60초 안에 `audit_config_changed`
     - P5-12 `scripts\<id>\start.ps1` 직접 수정 → 60초 안에 `script_file_changed`; `logs\<어제>.jsonl` 잘라내기 → `log_file_truncated`
     - P5-13 성능: 서비스 유휴 CPU < 2%, 에이전트 CPU < 1%(60초 평균, `Get-Counter '\Process(python*)\% Processor Time'`), 창을 빠르게 30번 전환해도 `activity.window` 줄이 병합됨
     - P5-14 서비스(또는 schtasks) 재시작 → 접속 중 세션에 `existing` 연결과 고지(V8), 이전 미확인 고지는 `service_restart`
  4. **알려진 한계**(V3·V4): 고지 창은 Edge 앱 창이라 다른 앱 위에 떠 있어도 진짜 모달은 아님(닫으면 다시 뜸), 관리자 권한 사용자는 에이전트·감사 정책을 끌 수 있고 우리는 그 사실을 기록할 뿐(§2 #4).

- [ ] **Step 2: 문서 정리**
  - `docs/PLAN.md`: 버전 v0.7, 변경 이력 한 행: `v0.7 | 구현 정합 (P4–P5): 에이전트↔서비스는 Named Pipe 대신 Local 채널 HTTP(X-Agent-Token + TCP 피어 → 세션 ID 검증, V4), 고지 창은 pywebview 대신 Edge --app 창(같은 Chromium/WebView2 엔진, V3), WTS 0.5초 폴링 + nudge(V6), 보드 sessions·SSE sessions/tamper, GET /api/sessions/{current,history,collectors}, GET /api/tamper/recent, POST /api/notice/display/{open,ack}(Local, 토큰), /api/agent/*(Local), 마이그레이션 6·7(rdp_connections, rdp_logon_failures, notice_displays), pywin32 312, CLI --session-source/--collect-console/--activity/--agent-launcher/--agent-dialog/--agent-dir`. §3 그림의 "Named Pipe (세션 ID 검증)"을 "loopback HTTP (에이전트 토큰 + 세션 ID 검증)"으로, §5.5 "WebView2로 렌더링"을 "Edge 앱 창(WebView2와 같은 엔진)으로 렌더링"으로, §5.3 "2초 폴링 보정"을 "0.5초 폴링(+ 세션 변경 알림 시 즉시)"으로, §9.2 Windows 연동 행을 "pywin32(이벤트 로그·WMI·CreateProcessAsUser), ctypes(WTS·세션 ID·SetWinEventHook), Edge --app"으로 고칩니다. §8 표에 새 엔드포인트 행을 넣고, 상태 줄을 "P0–P5 구현 완료(Win 11 Pro 실기기 확인 대기, `docs/verification/win11-pro-p4-p5.md`)"로 바꿉니다.
  - `carry-forward.md`: "Plan 4" 절 5개 항목과 Plan 3이 더한 Plan 4 항목에 체크하고 줄 끝에 `(Plan 4 Task N)`(배정은 이 문서 맨 위 표). 새 항목:
    - Plan 5: 보존 정리에 `rdp_connections`·`rdp_logon_failures`·`notice_displays` 포함, 로그 파일을 지울 때 `TamperScanner.expect_log_removed(name)` 호출(안 하면 `log_file_removed` 우회 탐지가 뜸). 서비스 호스트가 `SERVICE_CONTROL_SESSIONCHANGE`에서 `SessionCollector.nudge()`. PyInstaller로 `mcp-agent.exe`를 만들면 `AgentOptions.python`·`argv`를 실행 파일로 바꿈(`-m mcp_agent` 대신). `install.ps1`이 위 감사 정책·레지스트리를 켬. `data/collector-state.json`과 Edge 프로필 폴더(`%LOCALAPPDATA%\mcp-monitor\notice-edge`)를 설치 제거 때 정리. 로그 조회 화면에 `session`·`notice`·`activity.*`·`tamper` 필터와 대시보드 "로그인 실패 추이".
    - 추후: 우회 탐지 알림 채널(토스트·메일·웹훅, §14), GeoIP, `legalnoticecaption`/`legalnoticetext` 반영(§5.5 선택), 고지 창을 진짜 모달로(pywebview로 교체, V3), WTS 세션 알림 창(V6).
    - Win 11 Pro 점검표의 `대기` 항목 전체.

- [ ] **Step 3: 전체 검증**

  Run (server): `uv run python -m pytest -q` → 전체 통과. `uv run python -m pytest -m integration -q` → 통과. `uv run python -m pytest -m winlive -q` → 통과. `uv run python -m ruff check app tests` → 0건. `uv run python -m mypy` → 0건. `uv run python -m pip_audit` → 0건.
  Run (agent): `uv run python -m pytest -q` → 통과. `uv run python -m pytest -m winlive -q` → 통과. `uv run python -m ruff check mcp_agent tests`(server의 ruff를 `uv run --project ../server python -m ruff ...`로) → 0건.
  Run (web): `pnpm typecheck` → 0 errors. `pnpm lint` → 0 problems. `pnpm test` → 통과. `pnpm build` → 성공. `pnpm test:budget` → 통과. `pnpm e2e` → 통과. `pnpm audit` → `No known vulnerabilities found`.

- [ ] **Step 4: Commit** — `git commit -m "docs: Win 11 Pro P4/P5 verification checklist, spec v0.7 and carry-forward for Plan 5"`

---

## 부록 A: 결정 사항 (이 계획의 Ruling V1–V33)

| # | 결정 | 이유 | 틀렸을 때 비용 |
|---|---|---|---|
| V1 | Plan 4는 Plan 3이 끝난(전체 리뷰 수정 포함) 커밋에서 `feat/plan4-windows-collection`으로 시작합니다. Plan 3 구현이 이 문서의 이름(`SessionCard`, `rdpSession`, `renderWithProviders`, `adminApi`, `source.ts` 등)과 다르면 실제 코드를 따르고 보고합니다. | Plan 3이 지금 구현 중이라 이 계획은 Plan 3 문서의 인터페이스를 기준으로 썼습니다. | 이름 맞추기 수정. |
| V2 | 새 Python 의존성은 `pywin32==312` 하나(`sys_platform == 'win32'`). 이벤트 로그(`EvtSubscribe`)·WMI(`win32com`)·`CreateProcessAsUser`·`LookupAccountSid`에 씁니다. WTS 구조체·`ProcessIdToSessionId`·TCP 피어·에이전트 전체는 ctypes/표준 라이브러리입니다. spec §9.2의 comtypes는 쓰지 않습니다(pywin32의 `win32com`으로 충분). PyPI에 `pywin32-312-cp315-cp315-win_amd64.whl`이 있고 3.15.2에서 import를 확인했습니다(2026-11-05). | WTS 정보 클래스(`WTSSessionInfoEx` 등)는 구조체를 정확히 다뤄야 해서 ctypes가 낫고, COM·이벤트 로그 구독은 pywin32가 훨씬 짧습니다. | 앱 제어가 pywin32 DLL을 막으면 ctypes로 `wevtapi.dll`·`ole32` WMI를 다시 짜야 합니다(Task 7·9·13 어댑터만, 상위 코드는 그대로). |
| V3 | **에이전트 기술**: Python 표준 라이브러리 + ctypes 프로세스(`agent/`, `python -m mcp_agent`)이고, 고지 창은 **Edge `--app` 창**(`/notice#d=<id>&t=<토큰>`, 전용 `--user-data-dir`, `--no-first-run`)입니다. pywebview(pythonnet → .NET WinForms + WebView2)는 쓰지 않습니다. 창은 `SetWindowPos(HWND_TOPMOST)`로 중앙 최상위에 두고, 사용자가 닫으면 다시 띄웁니다. Edge가 없으면 기본 브라우저(V25). | Edge는 Windows 11 기본 설치이고 WebView2와 같은 Chromium 엔진이라 웹앱 토큰·애니메이션이 그대로 나옵니다. 의존성이 없어 앱 제어·휠 문제가 없고, 이 Home PC에서 print 모드 + Playwright로 실제 경로 전체를 자동 테스트할 수 있습니다. 확인 신호는 창→에이전트가 아니라 페이지→서버(토큰)라서 호스트 브리지가 필요 없습니다. | Edge 정책·첫 실행 화면이 문제면 `NoticeWindow` 구현만 pywebview(pythonnet 3.2.1 cp315 휠 있음)로 바꿉니다. 서버 API·페이지·토큰 흐름은 그대로입니다. |
| V4 | **에이전트↔서비스 통신은 Named Pipe 대신 Local 채널(127.0.0.1:8700) HTTP**입니다. 인증은 ① 실행 때마다 새로 만든 토큰(`X-Agent-Token`, 서버는 sha256만 보관) ② 요청 TCP 연결의 소유 프로세스 → `ProcessIdToSessionId`로 서버가 직접 구한 세션 ID가 슬롯의 세션과 같아야 함 ③ hello 본문의 `session_id`·`pid`가 피어와 같아야 함. 브라우저 페이지는 사용자 정의 헤더 때문에 교차 출처 요청을 보낼 수 없고(preflight 없음 → 차단), `LocalHostGuard`가 DNS 리바인딩을 막습니다. | spec §3의 "세션 ID 검증"을 같은 강도로 지키면서 FastAPI 검증·오류 형식·테스트 도구를 그대로 씁니다. 파이프의 DACL(표준 사용자 쓰기 허용)과 비동기 파이프 서버를 새로 만들 필요가 없습니다. | TCP 표 조회가 실기기에서 불안정하면(경합) 전송만 Named Pipe(`GetNamedPipeClientProcessId`)로 바꿉니다. 허브 로직은 그대로입니다. |
| V5 | 에이전트는 런타임 의존성 0개이고 `config.db`를 열지 않습니다(Task 15 테스트). 수집 스레드도 DB를 만지지 않고, 이벤트 로그 북마크는 `data/collector-state.json`(V12)에 둡니다. | carry-forward: 두 번째 프로세스가 `config.db`를 열면 `busy_timeout` 때문에 루프가 최대 5초 멈출 수 있습니다. | 없음. |
| V6 | WTS는 **0.5초 폴링**이 주 경로이고 `nudge()`로 즉시 깨울 수 있습니다(Plan 5 서비스 호스트가 `SERVICE_CONTROL_SESSIONCHANGE`에서 부름). WTS 알림용 메시지 창은 만들지 않습니다. | 폴링 0.5초 + SSE 묶음 1초 ≤ 1.5초라 "2초 안에 표시"(§11 P4)를 지키고, 세션 0의 서비스에서 메시지 창 알림이 되는지 불확실합니다. 열 개 남짓한 WTS 호출이라 CPU 부담이 작습니다. | 실기기에서 2초를 넘기면 LSM 이벤트 구독에서 `nudge()`를 부르게 바꿉니다. |
| V7 | 보드 `sessions` = 감시 대상(RDP, 개발용 `--collect-console`이면 콘솔도) 중 **활성** 세션(잠김 포함)뿐. 끊긴 세션은 `GET /api/sessions/current`와 세션 화면에만. `sessions` 키는 첫 스냅숏 전·수집 꺼짐일 때 없습니다(Plan 3 계약: "수집 준비 전"). | 끊긴 세션을 보드에 넣으면 아무도 접속하지 않았는데 "● 접속 중"이 됩니다. | 필터 한 줄. |
| V8 | 연결 종류는 `logon`/`reconnect`/`existing`. 서비스가 시작될 때 이미 활성인 세션은 `existing` 연결을 열고 **고지도 띄웁니다**. 시작 때 끝나지 않은 이전 연결 행은 `service_stop`, 열린 표시 건은 `service_restart`로 닫습니다. | 수집이 다시 시작되는 시점에 사용자에게 기록 사실을 알리는 것이 보수적입니다. | 서비스 재시작 뒤 확인 한 번 더. |
| V9 | 세션 정체성 = `(session_id, logon_at)`. 같은 ID에 로그온 시각이 다르면 새 로그온(ID 재사용). `active → active`인데 `connected_at`이 바뀌면 끊김을 놓친 빠른 재연결로 봅니다. `WTSClientAddress`의 IPv4는 `Address[2:6]`, IPv6는 `Address[2:18]`로 읽습니다(IPv6는 실기기 점검표 P4-7에서 확인). | Windows는 세션 ID를 재사용하고, 0.5초 사이에 끊고 다시 붙을 수 있습니다. | IPv6 오프셋이 다르면 함수 하나 수정. |
| V10 | SSE `sessions`는 보이는 내용이 바뀔 때만 보냅니다. 유휴 시간은 **분이 바뀔 때만** 변화로 칩니다(웹은 분 단위로 표시). | 매초 유휴 값 때문에 모든 보드에 SSE가 흐르면 §7 "화면 갱신 최대 1회/초"와 대역을 낭비합니다. | 표시 정밀도만. |
| V11 | Windows 이벤트에서 온 모든 로그 줄은 `emit(at=<이벤트 시각>)`. 수집 스레드는 `CollectorBridge`(소스별 1만 개, 넘치면 오래된 것부터 버림 + `collector.dropped`)로만 루프에 넘깁니다. `LogWriter.emit_threadsafe`도 제공합니다. | carry-forward 두 항목. 이벤트가 쏟아질 때 메모리를 지키고, 잃은 수를 남깁니다. | 상한 숫자만. |
| V12 | 이벤트 로그는 채널마다 스레드 하나의 `EvtSubscribe` pull 모드. 북마크는 `data/collector-state.json`(5초마다·정지 때 저장), 처음에는 가장 최근 기록 이후부터, 재개 때 24시간보다 오래된 이벤트는 버립니다. 읽을 수 없는 채널(Home의 Security 접근 거부, 없는 `PowerShellCore` 채널)은 상태에 남기고 60초마다 다시 시도합니다. | 서비스 재시작 사이의 이벤트를 잃지 않되, 처음 설치 때 과거 로그를 쏟아내지 않습니다. | 캐치업 한도 조정. |
| V13 | 프로세스 시작·종료는 `Win32_ProcessStartTrace`/`StopTrace`(관리자·SYSTEM), 거부되면 `__InstanceCreationEvent`/`DeletionEvent WITHIN 1`(관리자 아님, 이 PC에서 확인: CommandLine·SessionId 포함). 세션 0은 기록하지 않습니다. 1초 안에 끝나는 프로세스의 명령줄은 4688이 맡습니다(§5.4). | 개발 PC와 서비스 양쪽에서 같은 코드가 돌고, 서비스 프로세스의 소음을 뺍니다. | poll 모드에서 1초 미만 프로세스는 4688에만 남습니다. |
| V14 | `activity.command`: 4688 중 자식이나 부모가 셸(cmd, powershell, pwsh)인 것(`conhost.exe` 제외, SYSTEM·LocalService·NetworkService 제외) + 4104(두 PowerShell 채널, 여러 조각은 5초 안에 합침, 65,536자에서 자름). cmd 내부 명령은 수집하지 않습니다(§2 #7). 4688의 세션은 WMI 캐시 → `ProcessIdToSessionId` → 같은 계정의 유일한 세션 순으로 찾습니다. | 4688에는 세션 ID가 없고, 모든 프로세스를 `activity.command`로 남기면 `activity.process`와 중복입니다. | 필터 조정. |
| V15 | 고지 표시 모델: 연결마다 표시 건 하나, 문구 버전은 만들 때 고정(편집 중에도 같은 내용), 시도마다 새 토큰(URL 조각 `#d=&t=`; 서버는 sha256만 메모리에), 페이지가 열기를 보고하면 `notice_shown`, 확인하면 `notice_acknowledged`(경과 = 확인 − 마지막 표시). 새 연결이 오면 이전 미확인 건은 `superseded`, 로그오프는 `logoff`, 창을 닫으면 `window_closed`로 남기고 1초 뒤 다시 띄웁니다. | §5.5 기록 항목(표시 시각·연결 종류·문구 버전, 확인 시각·걸린 시간, 미확인)을 모두 남기고, 토큰이 서버 로그·히스토리·`Referer`에 남지 않게 합니다. | 다시 띄우는 간격 조정. |
| V16 | 고지 페이지 API(`/api/notice/display/{open,ack}`)는 Local에만, `X-Notice-Token` 필수, 요청 피어의 세션이 표시 건 세션과 같아야 하고, `Sec-Fetch-Site`가 있으면 `same-origin`/`none`만. 문제는 모두 404 `not_found`(교차 사이트만 403). 맞는 토큰을 다른 세션에서 쓰면 `notice_token_misuse` 우회 탐지. 새 오류 코드 없음. | 토큰이 새어도 다른 세션에서 대신 확인할 수 없고, 응답으로 토큰 유효 여부를 알려주지 않습니다. | 상태 코드만. |
| V17 | 런처: `auto` = SYSTEM이면 `WtsLauncher`(`WTSQueryUserToken` → `CreateProcessAsUser`, `winsta0\default`), 아니면 `LocalLauncher`(자기 세션에만, 다른 세션 요청은 `session_mismatch`). 토큰은 **환경 변수** `MCPMON_AGENT_TOKEN`으로 넘기고 에이전트는 읽자마자 지웁니다. | 명령줄로 넘기면 우리 4688·WMI 수집이 토큰을 로그에 남깁니다. 개발 PC는 SE_TCB 권한이 없어 WTS 런처를 쓸 수 없습니다. | 런처 하나 추가. |
| V18 | 감독: 종료 후 3초 유예(그 사이 세션이 사라졌으면 로그오프로 보고 우회 아님), 백오프 1·2·4·8·16·30초(hello 후 60초 넘게 정상이면 리셋), 600초에 5번 이상 죽으면 `agent_restart_storm` 한 번, hello 30초·heartbeat 20초 무응답이면 `agent_unresponsive` 후 강제 종료(우리가 죽인 것은 `agent_exited`가 아님). 서비스 정지 때 `exit` 명령 → 2초 → 강제 종료. | §11 P5 "에이전트를 종료하면 재기동되고 그 사실이 기록됨"과 로그오프 오탐 방지. | 숫자 조정. |
| V19 | 우회 탐지 목록(Global Constraints `tamper` 13종)과 전달: `tamper` 로그 + 로그인 사용자 SSE `tamper` + `GET /api/tamper/recent`(메모리 링 200) + 대시보드 카드. 스크립트·로그 파일·레지스트리 점검은 60초마다. 외부 알림(토스트·메일·웹훅)은 "추후". | §2 #4 "기록하고 알립니다" 중 이번 범위에서 할 수 있는 화면 알림까지. | 알림 채널은 별도 작업. |
| V20 | localhost 로그인의 Windows 계정: Local 채널의 `auth` 줄(`otp_request`·`login`·`logout`·429)에 `windows_user`(브라우저 프로세스의 `DOMAIN\name`, 못 찾으면 null). 외부 채널에는 키가 없습니다. | §4.1.5, carry-forward. 같은 TCP 피어 조회(V4)를 재사용합니다. | 없음. |
| V21 | 잠금·해제는 WTS `SessionFlags`(`source: "wts"`)와 4800/4801(`source: "eventlog:<id>"`) 둘 다 기록합니다. 중복은 `source`로 구분합니다. | §5.4 "4800/4801, 세션 알림" 둘 다 명시. Security 로그를 못 읽는 환경에서도 WTS로 남습니다. | 한쪽을 끄면 됩니다. |
| V22 | 역방향 DNS는 연결이 열린 뒤 스레드에서 2초 제한으로 조회, 성공·실패 10분 캐시, 결과가 오면 이력·보드 갱신. GeoIP는 구현하지 않습니다(spec 선택 사항). | 연결 표시가 DNS를 기다리지 않게 합니다. | 없음. |
| V23 | 세션 이력 API: `days` 1–90, `limit` ≤ 500, `before_id` 커서, 로그인 실패는 4625 전 유형(`rdp_logon_failures`, `(source, record_id)` 중복 제거), 연결의 `notice`는 최신 표시 건. 로그·감사 화면의 일반 필터는 Plan 5. | §6.4 #3 세션 화면에 필요한 만큼만. | 한도 조정. |
| V24 | 개발·E2E 전용: `--session-source json:<경로>`(`"self"` = 서버 자신의 세션 ID, stderr 경고), `--activity off`, 에이전트 `--dialog print`(URL 파일에 `OPEN`/`CLOSE` 줄). | Home PC에 RDP가 없으므로 같은 코드 경로(트래커·표시·감독·실제 에이전트·실제 피어 검증)를 가짜 세션으로 돌립니다. | 없음. |
| V25 | Edge를 찾지 못하면 `webbrowser.open(url)`(기본 브라우저)로 대신 열고 닫힘 감지는 하지 않습니다. | Edge가 없는 시스템은 드물지만 고지 자체는 보여야 합니다. | 기본 브라우저 탭은 최상위가 아님. |
| V26 | 보드 유휴 시간은 서버가 WTS `LastInputTime`으로 계산하고, 에이전트는 300초 기준의 `activity.idle`(유휴·복귀) 로그만 보냅니다. | 에이전트 없이도 보드가 정확하고, 로그는 전이만 남습니다. | 없음. |
| V27 | 창 이벤트: 전경·최소화·복원·(전경 창의) 제목만, 전경 300ms·제목 1초 병합, 1초 묶음 ≤ 200개, 서버가 안 되면 2,000개까지 쌓고 오래된 것부터 버림, 서버에 120초 못 붙으면 에이전트 종료(감독자가 다시 띄움). | §7 "에이전트에서 디바운스·병합, 에이전트 CPU < 1%". | 숫자 조정. |
| V28 | 에이전트가 보낸 `at`이 서버 시각과 300초 넘게 다르면 서버 시각을 쓰고 `clock_skew: true`. | 사용자 세션의 시계 조작으로 로그 날짜를 옮기지 못하게 합니다. | 없음. |
| V29 | 새 테이블(`rdp_connections`, `rdp_logon_failures`, `notice_displays`)의 보존 정리는 Plan 5(carry-forward). | 보존 정리는 Plan 5 범위입니다. | Plan 5 전까지 테이블이 자랍니다(행이 작음). |
| V30 | 웹: 신규 의존성 없음. notice 번들은 `fetch`를 직접 쓰고(`credentials: "omit"`), 토큰은 읽자마자 주소에서 지우며, 확인은 0·1·2초 간격 3번 시도. | notice < 100KB 예산, 토큰 노출 최소화. | 없음. |
| V31 | 내비 "세션"은 `view_session_history`로 두 채널 모두 열립니다. `planned_sessions` 이유는 타입에 남기되 쓰지 않습니다. 대시보드 "우회 탐지 이벤트" 카드는 실제 데이터, "로그인 실패 추이"는 Plan 5까지 `planned_logs`. | §4.3: 세션 이력 조회는 MCP 개발자 이상, 채널 제한 없음. | 없음. |
| V32 | `winlive` 마커(관리자 없이 이 PC의 실제 API)와 `integration`(실제 프로세스)은 기본 실행에서 빼고 과제의 Run 단계가 명시적으로 돌립니다. 관리자·RDP·다른 세션이 필요한 확인은 점검표의 `대기` 항목입니다. | 자동 테스트가 권한에 기대지 않게 합니다(사용자 지시). | 없음. |
| V33 | `legalnoticecaption`/`legalnoticetext` 반영(§5.5 선택)은 이번에 하지 않습니다. | 설치 스크립트(Plan 5)와 함께 다루는 게 맞습니다. | 추후 과제. |

## 부록 B: API·SSE 대응표 (서버 코드 기준)

웹 클라이언트 함수는 `web/src/lib/endpoints.ts`, 에이전트 함수는 `agent/mcp_agent/client.py`·`runner.py`입니다. "신규"는 이 계획에서 더하는 것입니다.

| 메서드·경로 | 채널 | 인증 | 응답(성공) | 주요 오류 | 서버 코드 | 클라이언트 | Query key |
|---|---|---|---|---|---|---|---|
| `GET /api/board` | 둘 다 | 익명 | `{now, mcps, sessions?: RdpSession[]}`(sessions 신규 채움) | — | `mcp_shared.board` → `board_snapshot(services)` | `board()` | (BoardStore) |
| `GET /api/stream` | 둘 다 | 익명 | SSE `board`(sessions 포함), `mcp`, `mcp_removed`, **`sessions` `{sessions}`**(공개), `action`·**`tamper` `TamperEvent`**(로그인 MCP 개발자 이상) | 429, 503 | `board_stream(..., snapshot=)`, `SessionTracker` 게시, `TamperMonitor.report` | `BoardStreamClient` → `BoardStore.apply` / `onTamper` | — |
| `GET /api/sessions/current`(신규) | 둘 다 | `view_session_history` | `{ready, sessions: CurrentSession[]}` | 401 | `sessions_api` | `sessionsCurrent()` | `['sessions','current']` |
| `GET /api/sessions/history?days=1..90&limit=1..500&before_id`(신규) | 둘 다 | `view_session_history` | `{connections: SessionConnection[], failures: LogonFailure[], next_before_id}` | 401, 422 | `sessions_api` + `NoticeDisplays.latest_for_connections` | `sessionsHistory(days, beforeId?)` | `['sessions','history',days]` |
| `GET /api/sessions/collectors`(신규) | 둘 다 | `view_session_history` | `CollectorStatus[]` | 401 | `Collectors.status` | `collectorsStatus()` | `['sessions','collectors']` |
| `GET /api/tamper/recent?limit=1..200`(신규) | 둘 다 | `view_logs` | `TamperEvent[]`(최신순) | 401, 422 | `tamper_api` | `tamperRecent(limit)` | `['tamper']` |
| `POST /api/notice/display/open`(신규) | **Local** | `X-Notice-Token` + 피어 세션 | `{display_id, version, title, body, button_text}` | 404 `not_found`, 403 `forbidden`(교차 사이트) | `notice_display_api` → `NoticeDisplays.open` | notice `loadNoticeContent(src)` | — |
| `POST /api/notice/display/ack`(신규) | **Local** | `X-Notice-Token` + 피어 세션 | 204 | 404, 403 | `NoticeDisplays.acknowledge` | notice `notifyHost(msg, src)` | — |
| `POST /api/agent/hello`(신규) | **Local** | `X-Agent-Token` + 피어 세션 | `{heartbeat_sec: 5, events_max: 200, idle_threshold_sec: 300}` | 401 `login_required`, 403 `forbidden`, 422 | `agent_api` → `AgentHub.hello` | `AgentRunner.run` | — |
| `GET /api/agent/next?timeout=0..30`(신규) | **Local** | 같음 | `{"type":"show_notice","display_id","attempt","url"}` \| `{"type":"close_notice","display_id"}` \| `{"type":"exit"}` / 204 | 401, 403 | `AgentHub.next` | `ServerClient.next` | — |
| `POST /api/agent/heartbeat`(신규) `{idle_sec, locked}` | **Local** | 같음 | 204 | 401, 403, 422 | `AgentHub.heartbeat` | 하트비트 스레드 | — |
| `POST /api/agent/events`(신규) `{events: (WindowEventIn \| IdleEventIn)[] ≤ 200}` | **Local** | 같음 | 204 | 401, 403, 422 | `AgentHub.events` → `activity.window`/`activity.idle` | `EventSender.flush` | — |
| `POST /api/agent/notice/{display_id}/closed`(신규) | **Local** | 같음 | 204 | 401, 403, 422 | `AgentHub.closed` | 명령 루프 | — |
| `GET /notice#d=<id>&t=<token>` | **Local**(F18) | — | notice.html(표시 모드) | — | `static_router(notice=True)` | Edge `--app` 창 | — |
| `POST /api/auth/otp/{request,verify}`, `POST /api/auth/logout` | 둘 다 | — | 기존 그대로; Local 채널 `auth` 로그에 `windows_user` 추가 | 기존 | `shared_api` + `windows_user_of` | 기존 | — |

**SSE·로그 페이로드 모양**

| 이름 | 모양 |
|---|---|
| `RdpSession`(보드 `sessions[]`, SSE `sessions`) | `{session_id, user, domain, client_name, client_ip, reverse_dns, logon_at, connected_at, state: "active"\|"locked", idle_sec, resolution, notice_acknowledged: bool\|null, connection_id, client_build, protocol: "rdp"\|"console"\|"other", first_seen_ip, first_seen_device}` (`SessionTracker.board_sessions`, `RDP_KEYS`) |
| `TamperEvent`(SSE `tamper`, `/api/tamper/recent`) | `{at, event, ...필드}` (`TamperMonitor.report`) |
| `notice` 로그 | `notice_shown {display_id, connection_id, session_id, user, kind, version, attempt}`, `notice_acknowledged {…, elapsed_ms}`, `notice_unacknowledged {display_id, …, reason}` |
| `session` 로그(WTS) | `{event: connect\|disconnect\|logoff\|lock\|unlock, connection_id, session_id, user, domain, client_ip, client_name, client_build, protocol, resolution, kind?, source: "wts"}` |
| `activity.window` 로그 | `{event, pid, exe, title, session_id, user, client_ip, client_name, source: "agent", clock_skew?}` |
| `activity.process` 로그 | `{event: start\|stop, pid, ppid, name, exe?, cmdline?, exit_code?, session_id, user, client_ip, client_name, source: "wmi:trace"\|"wmi:poll"}` |
| `activity.command` 로그 | 4688 `{event: "process_cmdline", shell, parent_shell, pid, ppid, exe, parent_exe, cmdline, …세션 맥락, source: "eventlog:4688", record_id}` / 4104 `{event: "script_block", shell, text, script_block_id, path, parts, truncated, incomplete, pid, …, source: "eventlog:4104", record_id}` |
