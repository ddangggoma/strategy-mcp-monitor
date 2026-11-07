# Plan 5 — 로그 조회·보존 정리·배포 하드닝 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 사용자 지시에 따라 과제마다 리뷰하지 않고, 마지막에 계획 전체 리뷰 한 번 + 수정 한 번만 합니다.

**Goal:** spec P6(로그 조회 + 보존)와 P7(배포·하드닝)을 구현해 프로젝트를 마칩니다. 일일 JSONL을 읽어 `data/index.db`(SQLite WAL + FTS5)에 색인하는 색인기와 조회 엔진, 로그 조회 화면(시간대·사용자 필터, 히스토그램 드래그 필터, 사용자별 타임라인, 키워드 검색, CSV·JSONL 내보내기), 감사 로그 화면, 대시보드 "로그인 실패 추이", 실제 보존 정리 작업(파일·색인·DB 표, 압축, 미리보기와 같은 기준일), Windows 서비스 호스트, 배포 묶음(PyInstaller 또는 서명된 Python 런타임 — 스파이크로 결정), `install.ps1`(서비스·감사 정책·ACL·`-OpenFirewall`), `uninstall.ps1`, 운영 문서, 그리고 carry-forward의 "Plan 5" 항목 전부입니다.

**Architecture:** 원본은 그대로 `logs/YYYY-MM-DD.jsonl`(오래되면 `.jsonl.gz`)이고, 조회용 `data/index.db`는 **언제든 지우고 다시 만들 수 있는 파생 데이터**입니다(spec §5.6). `LogIndex`가 파일을 꼬리 읽기(`\n` 단위, 부분 줄은 다음 차례)로 색인하고, 행마다 정규화 열(`ts_ms`, `day`, `cat`, `event`, `user`, `session_id`, `client_ip`, `outcome`), 원문(`raw`), FTS5 검색 문자열, 분·시간 단위 집계(롤업)를 한 트랜잭션에 씁니다. 쓰기는 `LogIndex`의 단일 직렬화 경로(스레드)만, 읽기는 `IndexReader`의 스레드별 읽기 전용 연결로 `asyncio.to_thread`에서 합니다. 조회 엔진은 필터 값마다 인덱스로 나눠 읽고 병합(fan-out + merge)하며, 커서는 `(ts_ms, id)` 키셋입니다. 히스토그램·사용자별 건수는 조건이 시간·카테고리·사용자뿐이면 롤업에서, 아니면 행을 세어 냅니다. `RetentionJob`은 매일 03:30 KST(그리고 보존 기간을 줄여 저장한 직후)에 Plan 3의 `retention_cutoff`로 파일·색인·DB 표를 정리하고, 파일을 지우기 전에 Plan 4의 `TamperScanner.expect_log_removed`를 부릅니다. 서비스 호스트는 같은 실행 파일의 `service` 하위 명령(pywin32 `ServiceFramework`)이고, `ServeControl`로 다른 스레드에서 정지·세션 알림을 전달합니다. 배포 묶음은 `bundle.json`이 있는 폴더 하나이고, 코드가 그 위치에서 정적 파일·에이전트 실행 명령·데이터 루트 기본값을 찾습니다. 설치 스크립트는 "실행 계획(JSON) → 실행" 한 경로라 `-DryRun`으로 관리자 권한 없이 검증합니다.

**Tech Stack:** 서버: Python 3.15(정확한 패치 고정), FastAPI, uv, pytest, SQLite 3.53(FTS5 `contentless_delete`), pywin32 312(Plan 4), 신규 런타임 의존성 없음. 빌드: PyInstaller 6.22.3(PyPI `py3-none-win_amd64`, Python 3.15 분류자, 2026-09-12 — 스파이크에서 이 PC의 Smart App Control을 통과할 때만, W26) 또는 python.org embeddable 3.15.x(PSF 서명). 웹: Plan 3 스택 + `@tanstack/react-virtual`(spec §6.5 목록에 있음, U18이 Plan 5로 미룸). 설치: Windows PowerShell 5.1, `sc.exe`, `icacls`, `auditpol`, `reg`, `wevtutil`, `netsh`.

**Spec:** `docs/PLAN.md` (v0.5; Plan 3 끝에 v0.6, Plan 4 끝에 v0.7). 이 계획은 §5.6(로그 저장소·보존), §6.4 #1(대시보드 로그인 실패 추이)·#4(로그 조회)·#7(로그 보존 설정의 정리 동작)·#8(감사 로그), §5.1·§5.9(서비스·부팅·복구), §5.8(scripts ACL), §2 #4·#6·#7(우회 탐지, 방화벽 기본 꺼짐, cmd 내부 명령 도움말), §7(로그 조회·보존 정리 성능), §9.1(버전 고정·보안 점검), §9.2(패키징), §10(`install/`), §13(성능·보안 테스트), §15(조회 행위 감사), §11 P6·P7 완료 기준을 구현합니다. 이미 내려진 결정은 `2026-11-04-plan1-rulings.md`, `2026-11-05-plan2-rulings.md`, Plan 3 부록 A(U1–U32), Plan 4 부록 A(V1–V33)와 `controller-rulings.md`(C1–C3)입니다. 이 계획의 결정(W1–W41)은 **부록 A**, API 대응은 **부록 B**에 있습니다. 본문의 `W<n>`은 부록 A의 행입니다.

**§11 완료 기준과 이 계획의 확인 방법**
| 기준 | 확인 |
|---|---|
| P6: 100만 건 기준 필터 < 300ms | Task 4 `tests/perf/test_log_perf.py`(마커 `perf`, 시나리오 S1–S10, 중앙값) — 결과는 `docs/verification/perf-p6.md`(Task 16) |
| P6: 보존 기간 변경 시 미리보기 후 정리 동작 | Task 6 `test_purge_matches_the_preview`, `test_lowering_retention_via_api_runs_the_job`, Task 15 E2E `lowering retention previews and then purges` |
| P7: 깨끗한 Win 11 Pro에서 설치 스크립트 한 번으로 전체 동작 | 이 PC(Win 11 Home, 관리자 아님)에서는 실행할 수 없습니다. `-DryRun` 계획 검증(Task 14)과 묶음 실행 검증(Task 13)까지 자동으로 하고, 실기기 절차는 `docs/verification/win11-pro-p6-p7.md`에 **대기**로 남깁니다(W38). |

**carry-forward 배정** (`docs/superpowers/plans/carry-forward.md`)
| 항목 | 과제 / 결정 |
|---|---|
| Reader·indexer: JSONL은 `\n`으로만 나눔(U+2028/2029가 줄 안에 그대로 있음) | Task 2 `split_lines`, `test_split_on_newline_only_keeps_u2028_inside_a_line` |
| Reader·indexer: 이틀에 걸친 재시도로 생긴 중복 줄 허용 | Task 2·3 `(day, line_hash)` 유일 인덱스(W5), `test_duplicate_lines_from_a_retry_are_indexed_once` |
| Retention: 만료 `auth_sessions`, 미등록 이메일의 `otp_codes`, 오래된 `otp_failures`·`otp_verify_ip` 정리(시각 형식 차이 주의) | Task 6 `test_purges_expired_rows_in_every_table`(W16) |
| `LogWriter.stop()`: 디스크 실패 시 버린 수 경고, 취소 안전, 장애 중 큐 상한 | Task 1 |
| 서비스 호스트: Event 기반 정지 훅, 포트 사용 중 깔끔한 종료, 루트 고정, `build_services` 실패 시 DB 핸들 누수 | Task 8 |
| DB 업그레이드: 더 새 DB 거부, 트랜잭션 안에서 `user_version` 읽기, WAL 확인 | Task 1 |
| 패키징: `.python-version` 정확한 패치, httptools·websockets·watchfiles hiddenimports, pyyaml cp315 휠이 생기면 `uvicorn[standard]` 복귀 | Task 1(버전), Task 13(hiddenimports·pyyaml 재확인, W27) |
| e2e 테스트: `lp != ep`, POST 상태 단언, `stdin=DEVNULL` | Task 7 |
| (Plan 2) `scripts/` ACL(SYSTEM + Administrators) | Task 14 `acl_*` 단계(데이터 루트 전체, W30) |
| (Plan 2) `mcp_actions`·`mcp_transitions` 보존 정리 (두 절에 중복 기재) | Task 6 |
| (Plan 2) 전역 설정의 서비스 시작 유형 반영 | Task 8 `StartTypeManager`(W25), Task 12 화면 |
| (Plan 2) 서비스 정지 때 `Monitor.stop()`이 10초 뒤 스크립트를 버려 둠 | Task 7 `kill_abandoned`(W21) |
| (Plan 2 리뷰) FAILED·자동 조치 예산이 재시작 때 초기화 | **유지(저장하지 않음)** W17, Task 16 운영 문서에 명시 |
| (Plan 2 리뷰) 타임아웃 kill 실패 경로 미검증 | Task 7 `kill_failed`(W20) |
| (Plan 2 리뷰) BodySizeLimit 예외 기록과 테스트 공백 | Task 7 |
| (Plan 2 리뷰) 스크립트 저장의 `os.replace`가 COMMIT 앞 | **실행 시 해시 검사를 안전망으로 채택** W19, Task 7 `test_commit_failure_after_replace_is_caught_by_the_runtime_hash_check` |
| (Plan 2 리뷰) 루프 종료 때 스크립트의 자식 미정리, "Task was destroyed" | Task 7 `kill_all`·`aclose` |
| (Plan 2 리뷰) 방어용 `_apply` 거절의 엔진 측 취소 | **추후** W18(도달 불가) |
| Later: `Alert` 효과의 알림 채널(§14) | **추후** W36 |
| Later: E501 미적용 | **추후** W36(동시 작업과 충돌하는 대량 줄바꿈을 피함) |
| Later: `--open-meteo` 배선 단위 테스트 | Task 7 |
| Later: `MCP_ACTOR` 허용 문자 | Task 7 `safe_actor`(W37) |
| Later(실제 OTP 공급자): 발송 실패·시간 차로 인한 등록 여부 노출 | **추후** W36(공급자가 여전히 Dummy) |
| (Plan 3 Task 16이 더할 항목) 보존 정리는 `retention_cutoff` 사용 | Task 6 |
| (Plan 3) 로그·감사 내비와 대시보드 로그인 실패 카드 채우기, 로그 표는 TanStack Virtual·애니메이션 없음 | Task 10–12 |
| (Plan 3) 패키징 시 `--static-dir` 기본값을 실행 파일 기준으로 | Task 9 |
| (Plan 4 Task 20이 더할 항목) `rdp_connections`·`rdp_logon_failures`·`notice_displays` 보존 정리 | Task 6 |
| (Plan 4) 로그 파일 삭제 전 `TamperScanner.expect_log_removed` | Task 6 |
| (Plan 4) 서비스 호스트가 `SERVICE_CONTROL_SESSIONCHANGE`에서 `nudge()` | Task 8 |
| (Plan 4) `mcp-agent.exe`면 `AgentOptions.python`·`argv` 교체 | Task 9 `AgentOptions.command` |
| (Plan 4) `install.ps1`이 감사 정책·레지스트리를 켬 | Task 14 |
| (Plan 4) 제거 때 `data/collector-state.json`·Edge 프로필 정리 | Task 14 `-RemoveData` |
| (Plan 4) 로그 화면의 `session`·`notice`·`activity.*`·`tamper` 필터, 대시보드 로그인 실패 추이 | Task 10–12 |
| (Plan 4 추후) 우회 탐지 알림 채널, GeoIP, legalnotice, 진짜 모달, WTS 알림 창 | **추후** W36 |

## Global Constraints

- 브랜치 `feat/plan5-logs-packaging`을 **Plan 4가 끝난 커밋**(전체 리뷰 수정까지)에서 만듭니다. 이 문서는 Plan 3·4 **문서**의 인터페이스를 기준으로 썼습니다. 실제 코드의 이름이 다르면 코드를 따르고 보고서에 이름 대응을 적습니다(W1, Plan 4 V1·C3과 같은 규칙).
- 서버 명령은 `server/`에서 `uv run python -m pytest ...`, `uv run python -m app ...`처럼 **`python -m` 형태로만** 부릅니다(Smart App Control이 `.venv\Scripts\*.exe` 콘솔 런처를 막습니다). uv가 PATH에 없으면 `C:\Users\ddang\AppData\Local\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\uv.exe`(E2E는 환경변수 `UV_EXE`). 에이전트는 `agent/`, 웹은 `web/`에서 `pnpm <script>`(Git Bash면 먼저 `export PATH="/c/nvm4w/nodejs:$PATH"`).
- 이 PC는 **Windows 11 Home, 관리자 아님, Smart App Control 켜짐**(`HKLM\SYSTEM\CurrentControlSet\Control\CI\Policy\VerifiedAndReputablePolicyState = 1`, 2026-11-05 확인)입니다. 테스트를 관리자 권한으로 돌리지 않고, 이 PC의 서비스·방화벽·감사 정책·레지스트리·ACL을 바꾸지 않습니다. `install.ps1`/`uninstall.ps1`은 이 PC에서 `-DryRun`과 "관리자가 아니면 아무것도 바꾸지 않고 종료" 확인만 실행합니다. 이미 있는 Windows 서비스 `McpManagementService`(Microsoft)와 이름이 다르게 우리 서비스는 `mcp-monitor`입니다.
- pytest 마커: `integration`(실제 하위 프로세스), `winlive`(관리자 없이 이 PC의 실제 Windows API, Plan 4), **`perf`**(100만 건 성능, 신규), **`bundle`**(빌드한 배포 묶음 실행, 신규). `addopts = "-m 'not integration and not winlive and not perf and not bundle'"`. 각 과제의 Run 단계가 마커를 명시적으로 실행합니다. 권한 부족으로 실패하는 테스트를 `skip`으로 바꾸지 않고 멈춰서 보고합니다.
- 의존성: 서버 **런타임 신규 없음**. 빌드 전용 그룹 `build = ["pyinstaller==6.22.3"]`은 Task 13 스파이크가 PyInstaller 경로(A)를 고른 경우에만 더합니다. 웹은 `@tanstack/react-virtual`(정확한 최신 안정 버전) 하나, 그리고 Plan 3이 아직 설치하지 않았다면 `@tanstack/react-table`. 그 밖은 Ruling 없이 추가하지 않습니다.
- `index.db` 규칙: 쓰기는 `LogIndex` 안의 `asyncio.Lock`으로 직렬화한 `asyncio.to_thread` 호출(`run_exclusive`)에서만, 읽기는 `IndexReader`의 스레드별 읽기 전용 연결에서만 합니다. `config.db` 규칙은 그대로(루프 스레드, `db.transaction()` 안에서 `await`·중첩 금지). `LogWriter.emit`은 루프 스레드(다른 스레드는 Plan 4의 `emit_threadsafe`).
- 오류 본문 `{"error": "<code>"}`. **새 API 오류 코드 없음**(`validation` 422, `login_required` 401, `forbidden` 403, `not_found` 404만). CLI 종료 코드: 0 정상, 1 예기치 않은 오류, 2 인자 오류(argparse), **3 포트 사용 중, 4 데이터 루트 사용 중, 5 DB가 더 새 버전**(W23).
- 로그 카테고리 12개를 고정합니다(spec §5.6): `session`, `notice`, `activity.process`, `activity.command`, `activity.window`, `activity.idle`, `tamper`, `mcp.health`, `mcp.action`, `auth`, `admin.audit`, `system`. 이 계획이 더하는 이름(테스트가 씁니다):
  - `system` `event`: `logstore.dropped {count}`, `logindex.bad_lines {file, count}`, `logindex.file_truncated {file, before, after}`, `logindex.rebuilt {reason}`, `logindex.ready {rows, duration_ms}`, `retention.run {...}`, `monitor.kill_failed {mcp_id, run_id, kind}`, `service.start_type {result, desired, current}`.
  - `admin.audit` `action`: `logs_view`, `logs_export`, `audit_view`, `audit_export`, `retention_purge`, `service_start_type_apply`.
- 시각: 색인은 `ts_ms`(UTC epoch 밀리초)와 `day`(KST 날짜 = 파일 날짜)를 가집니다. API 입력은 오프셋이 있는 ISO 8601만(없으면 422), 출력은 `to_kst_iso`(밀리초, `+09:00`). UI는 항상 KST, 시간 필터는 **분 단위로 맞춘 값**만 보냅니다(W8·W34).
- 웹 규칙은 Plan 3 Global Constraints 그대로입니다: 문구는 `web/src/copy/ko.ts`에만, `aria-disabled` + 이유, reduced-motion, 표·로그 영역에는 애니메이션 없음(`data-anim` 없음), 보드 < 200KB·notice < 100KB(gzip), 외부 채널에서 Local 전용 API를 부르지 않음, MSW 픽스처는 `api-types.ts` 타입을 따름. 이 계획이 더하는 문구 키(이 이름 그대로): `nav.{logs,audit}`(기존), `logs.{title,quick.{1h,today,yesterday,7d},from,to,apply,users,usersCount(n),categories,cats.<LogCategory>,groups.{session,activity,mcp,security,system},session,ip,keyword,keywordHint,moreConditions,clear,view.{table,timeline},export.{menu,csv,jsonl},empty,indexing(files),detail,cmdLimitHelp,histogramLabel(from,to,total),selection(from,to,count),columns.{ts,cat,user,session,ip,event,summary},loadMore}`, `audit.{title,kinds.{admin,auth,all},columns.{ts,actor,channel,ip,action,target,result},results.{ok,fail,denied,error},empty}`, `dashboard.loginFailures.{title,web,rdp,openLogs,empty}`, `settings.{retentionDeleteEvents(n),retentionRunsSoon,service.{title,notInstalled,current(type),mismatch,devMode}}`.
- **창 크기(사용자 지시, W41):** 휴대폰·터치 전용 작업(전용 레이아웃, 터치 제스처, 모바일 테스트)은 범위 밖입니다. 대신 이 계획의 모든 화면(로그 조회, 히스토그램, 타임라인, 필터, 감사 로그, 대시보드 카드, 설정 추가분)은 **640×600px까지 줄인 데스크톱 브라우저 창**에서 쓸 수 있어야 합니다: 페이지 가로 스크롤 없음(`document.documentElement.scrollWidth <= innerWidth`), 필터 막대·히스토그램·타임라인은 컨테이너 쿼리로 줄 바꿈·재배치, 표는 자기 컨테이너 안에서만 가로·세로 스크롤. UI 과제마다 **1920·1280·1024·800·640px** 너비(높이 600·800px)에서 확인합니다(Playwright 플러그인 점검표 + Task 15 E2E `no horizontal page scroll at 1920/1280/1024/800/640`).
- 테스트 본문은 모두 실제 단언입니다(주석만 있는 테스트 금지). `ruff format`을 돌리지 않습니다(W36).

## Review Focus

1. **보존 정리가 미리보기에서 보여 준 것만, 정확히 지우는가**(KST/UTC 경계, `retention_cutoff` 하루 차이, `.jsonl`과 `.jsonl.gz`가 같은 날짜에 함께 있음, 아직 색인이 끝나지 않은 파일의 압축, 정리가 우회 탐지 `log_file_removed`로 오인됨, 시각 형식이 다른 DB 표): → Task 6 `test_purge_matches_the_preview`, `test_compress_skips_files_not_fully_indexed`, `test_late_plain_file_is_merged_into_the_existing_gz`, `test_removals_are_announced_to_the_tamper_scanner`, `test_purges_expired_rows_in_every_table`, Task 15 E2E `lowering retention previews and then purges`
2. **실시간 쓰기 중 색인의 정확성**(쓰다 만 마지막 줄, 재시도로 생긴 중복 줄, 줄 안의 U+2028, 잘린(절단된) 파일, gz, 스키마 버전이 다른 index.db, 잘못된 줄): 행이 빠지거나 두 번 들어가면 안 되고 실패는 기록돼야 합니다. → Task 2 `test_split_on_newline_only_keeps_u2028_inside_a_line`, `test_read_chunk_resumes_plain_and_gz`, Task 3 `test_indexes_complete_lines_and_tails_partial_ones`, `test_duplicate_lines_from_a_retry_are_indexed_once`, `test_truncated_file_is_reread_without_duplicates_and_reported`, `test_version_mismatch_rebuilds_from_jsonl`, `test_rollups_match_rows`
3. **성능 기준**(여러 사용자 필터의 병합, 키워드, 롤업과 스캔 경로의 결과 일치, 깊은 커서, 정리 중 조회): → Task 4 `test_query_under_300ms[S1..S10]`, `test_ingest_rate`, `test_histogram_rollup_equals_scan`, Task 6 `test_purge_keeps_queries_fast`
4. **서비스 수명**(SCM 정지가 다른 스레드에서 옴, 포트 사용 중, 더 새 DB, 같은 루트를 쓰는 두 번째 인스턴스, 멈춘 스크립트가 남긴 SYSTEM 프로세스 트리, 예기치 않은 종료 뒤 SCM 복구): → Task 8 `test_serve_control_stops_from_another_thread`, `test_busy_port_exits_3_without_traceback`, `test_newer_database_exits_5`, `test_root_in_use_exits_4`, `test_service_host_runs_until_stop`, Task 7 `test_service_stop_kills_abandoned_script_tree`(integration), `test_kill_failure_is_reported_and_holds_the_mcp_lock`
5. **권한·개인정보**(로그는 MCP 개발자 이상만, 외부 채널에서도 로그인하면 조회 가능, 내보내기와 조회가 감사에 남되 새로 고침마다 쌓이지 않음, CSV 수식 주입, Local 전용 `/api/service`): → Task 5 `test_logs_require_login`, `test_first_page_views_are_audited_with_throttle`, `test_export_csv_escapes_formulas_and_has_bom`, `test_logs_work_on_both_channels`, Task 8 `test_service_route_is_local_admin_only`
6. **설치 스크립트의 안전성**(관리자 확인이 어떤 변경보다 먼저, 한국어 Windows에서도 맞는 SID·GUID, 방화벽 기본 꺼짐, 제거가 기본으로 데이터를 남김): → Task 14 `test_install_plan_default`, `test_install_plan_open_firewall`, `test_install_refuses_without_admin`, `test_uninstall_plan_keeps_data_by_default`
7. **히스토그램 드래그와 URL 상태 왕복**(분 경계 정렬, 키보드만으로 선택, 상대 범위 "최근 1시간"의 재계산): → Task 10 `resolves %s in KST minutes`, Task 11 `drag across buckets selects their minute-aligned span`, `selects with Shift+Arrow and applies with Enter`, `writes the selection to the URL and drops the quick range`, Task 15 E2E `dragging the histogram sets a custom range in the URL`
8. **작은 창(640×600)에서의 사용성**(필터 막대가 넘침, 히스토그램 막대가 1px 미만, 표가 페이지를 가로로 밀어냄, 상세 패널이 화면을 덮어 닫을 수 없음): → Task 11 `histogram keeps a 2px minimum bar and drops labels when narrow`, Task 15 E2E `no horizontal page scroll at 1920/1280/1024/800/640`, `the log table scrolls inside its own container at 640`

---

### Task 1: 기반 하드닝 — DB 업그레이드 안전장치, LogWriter 큐 상한·정지, 버전 고정

**Files:**
- Modify: `server/app/db.py`, `server/app/logstore/writer.py`
- Modify: `server/.python-version`, `agent/.python-version`, `dummy-mcps/.python-version`, `server/uv.lock`·`agent/uv.lock`·`dummy-mcps/uv.lock`(`uv sync` 결과만)
- Modify (tests): `server/tests/test_db.py`, `server/tests/test_log_writer.py`

**Interfaces:**
- Produces:
  - `app.db.DatabaseTooNewError(RuntimeError)`: 속성 `found: int`, `supported: int`, 메시지 `"database schema {found} is newer than this program supports ({supported})"`.
  - `Database.__init__`: `PRAGMA journal_mode=WAL`의 **반환값**이 `"wal"`이 아니면 연결을 닫고 `RuntimeError("journal_mode is <값>; WAL is required")`.
  - `Database.migrate()`: 마이그레이션 하나마다 `conn.execute("BEGIN IMMEDIATE")` → 바로 다음 문장으로 `conn.execute("PRAGMA user_version")`(정확히 이 문자열)을 읽고 → `current > len(MIGRATIONS)`면 ROLLBACK 후 `DatabaseTooNewError`, `current == len(MIGRATIONS)`면 COMMIT 후 종료, 아니면 `MIGRATIONS[current]`를 적용하고 `PRAGMA user_version = {current + 1}` → COMMIT → 반복. 두 프로세스(연결)가 동시에 불러도 같은 마이그레이션을 두 번 실행하지 않습니다.
  - `LogWriter(daily, clock, flush_interval=0.2, max_batch=500, max_queue=100_000)`: 내부 큐를 `collections.deque`로 바꿉니다. `emit`/`emit_threadsafe`(Plan 4)가 넣을 때 길이가 `max_queue`면 가장 오래된 것을 버리고 `_dropped += 1`(처음 버릴 때만 `_warn("log queue full; dropping oldest events")`). 실패한 재시도 묶음을 버릴 때도 그 수를 `_dropped`에 더합니다. 쓰기가 다시 성공한 직후 `_dropped > 0`이면 `{"ts": now, "cat": "system", "event": "logstore.dropped", "count": n}`을 다음 묶음 맨 앞에 넣고 `_dropped = 0`.
  - `LogWriter.pending: int`(큐 + 재시도 대기 수), `LogWriter.stopped: bool`.
  - `LogWriter.stop()`: 본문 전체를 `try/finally`로 감쌉니다. `finally`에서 ① 배경 태스크가 끝나지 않았으면 `cancel()` 후 `await asyncio.gather(task, return_exceptions=True)`(취소 중이면 `asyncio.shield` 없이 바로 취소) ② `lost = _dropped + len(queue) + len(retry or [])`가 0보다 크면 `_warn(f"stop: {lost} log event(s) were not written")` ③ `_stopped = True`. `stop()` 자체가 취소되면 위 정리를 마친 뒤 `CancelledError`를 다시 던집니다.
  - `LogWriter.add_flush_listener(fn: Callable[[], None]) -> None`: 묶음 쓰기가 성공할 때마다(루프 스레드) 등록 순서대로 호출. 리스너 예외는 `_warn(f"flush listener failed: {exc!r}")` 후 계속.
  - `.python-version` 3곳: `uv python list 3.15 --only-downloads`에서 가장 높은 3.15.x(지금 3.15.2)이고 python.org 릴리스 노트에 그보다 새 보안 패치가 없음을 확인한 **정확한 버전 문자열**(예: `3.15.2`). `requires-python`은 그대로 `>=3.15,<3.16`.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_db.py (추가)
import threading
from pathlib import Path

import pytest

from app.db import MIGRATIONS, Database, DatabaseTooNewError


def test_migrate_rejects_a_newer_database(paths):
    db = Database(paths.db_path); db.migrate()
    db.execute(f"PRAGMA user_version = {len(MIGRATIONS) + 1}")
    with pytest.raises(DatabaseTooNewError) as e:
        db.migrate()
    assert (e.value.found, e.value.supported) == (len(MIGRATIONS) + 1, len(MIGRATIONS))
    db.close()


def test_migrate_reads_user_version_inside_the_transaction(paths):
    db = Database(paths.db_path); seen: list[str] = []
    db._conn.set_trace_callback(seen.append)
    db.migrate()
    first = seen.index("BEGIN IMMEDIATE")
    assert seen[first + 1] == "PRAGMA user_version"
    assert "PRAGMA user_version" not in seen[:first]
    db.close()


def test_two_connections_migrate_concurrently(paths):
    a, b = Database(paths.db_path), Database(paths.db_path)
    barrier, errors = threading.Barrier(2), []

    def run(db):
        barrier.wait()
        try:
            db.migrate()
        except Exception as exc:  # collected and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(d,)) for d in (a, b)]
    for t in threads: t.start()
    for t in threads: t.join(30)
    assert errors == [] and a.query("PRAGMA user_version")[0][0] == len(MIGRATIONS)
    a.close(); b.close()


def test_wal_is_required():
    with pytest.raises(RuntimeError, match="WAL is required"):
        Database(Path(":memory:"))
```

```python
# server/tests/test_log_writer.py (추가)
import asyncio
import json
import time

from app.logstore.writer import DailyJsonlWriter, LogWriter


class FlakyDaily(DailyJsonlWriter):
    def __init__(self, d):
        super().__init__(d); self.fail = True

    def write_batch(self, events):
        if self.fail:
            raise OSError("disk full")
        super().write_batch(events)


class SlowDaily(DailyJsonlWriter):
    def write_batch(self, events):
        time.sleep(1.0); super().write_batch(events)


def lines(d):
    return [json.loads(x) for f in sorted(d.glob("*.jsonl")) for x in f.read_text("utf-8").split("\n") if x]


async def test_queue_is_bounded_and_drops_are_reported(tmp_path, clock):
    flaky = FlakyDaily(tmp_path)
    w = LogWriter(flaky, clock, flush_interval=0.01, max_batch=10, max_queue=50); await w.start()
    for i in range(200): w.emit("system", event="x", i=i)
    assert w.pending <= 60
    await asyncio.sleep(0.1)
    flaky.fail = False; await w.flush(); await w.stop()
    got = lines(tmp_path)
    dropped = [e for e in got if e.get("event") == "logstore.dropped"]
    written = [e for e in got if e.get("event") == "x"]
    assert len(dropped) == 1 and dropped[0]["count"] + len(written) == 200


async def test_stop_warns_about_events_not_written(tmp_path, clock, capsys):
    w = LogWriter(FlakyDaily(tmp_path), clock, flush_interval=0.01); await w.start()
    for i in range(5): w.emit("system", event="x", i=i)
    await w.stop()
    assert "stop: 5 log event(s) were not written" in capsys.readouterr().err and w.stopped


async def test_stop_survives_cancellation(tmp_path, clock):
    w = LogWriter(SlowDaily(tmp_path), clock, flush_interval=0.01); await w.start()
    w.emit("system", event="x"); await asyncio.sleep(0.05)
    t = asyncio.create_task(w.stop()); await asyncio.sleep(0.05); t.cancel()
    with pytest.raises(asyncio.CancelledError):
        await t
    assert w.stopped and w._task is not None and w._task.done()
    w.emit("system", event="after")  # ignored, never raises
    assert w.pending <= 1


async def test_flush_listeners_run_after_each_successful_write(tmp_path, clock):
    calls = []
    w = LogWriter(DailyJsonlWriter(tmp_path), clock, flush_interval=0.01); await w.start()
    w.add_flush_listener(lambda: calls.append(1))
    w.add_flush_listener(lambda: 1 / 0)  # a failing listener does not stop the others
    w.add_flush_listener(lambda: calls.append(2))
    w.emit("system", event="x"); await w.flush(); await w.stop()
    assert calls[:2] == [1, 2]
```

- [ ] **Step 2: 실패 확인** — Run: `uv run python -m pytest tests/test_db.py tests/test_log_writer.py -v` → FAIL

- [ ] **Step 3: 구현** — 위 Interfaces대로. `test_db.py`의 기존 테이블 목록 테스트는 그대로 통과해야 합니다(Plan 4의 마이그레이션 6·7 포함).

- [ ] **Step 4: 버전 고정** — 위 Interfaces의 절차로 버전을 고르고 3개 파일에 쓴 뒤 각 폴더에서 Run: `uv sync` → 성공, `uv run python --version` → `Python <그 버전>`.

- [ ] **Step 5: 통과 확인** — Run: `uv run python -m pytest -q` → 전체 통과, `uv run python -m ruff check app tests`, `uv run python -m mypy` → 0건

- [ ] **Step 6: Commit** — `git commit -m "fix: reject newer databases, read schema version inside the migration transaction, bound the log queue and make LogWriter.stop cancellation-safe"`

---

### Task 2: 로그 파일 읽기, 정규화, 색인 스키마, FTS 식

**Files:**
- Create: `server/app/logstore/files.py`, `server/app/logstore/reader.py`, `server/app/logstore/normalize.py`, `server/app/logstore/index_db.py`, `server/app/logstore/fts.py`
- Create: `server/tests/test_log_reader.py`, `server/tests/test_log_normalize.py`, `server/tests/test_index_db.py`
- Modify: `server/app/logstore/retention.py`(`_LOG_NAME`·`_log_files`를 `files.py`로 옮기고 import), `server/app/paths.py`(`index_db_path`)

**Interfaces:**
- Produces:
  - `app.paths.AppPaths.index_db_path` = `data_dir / "index.db"`.
  - `app.logstore.files`: `LOG_NAME = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2})\.jsonl(\.gz)?", re.ASCII)`; `@dataclass(frozen=True) LogFile(name: str, day: date, compressed: bool, path: Path, size: int)`; `list_log_files(logs_dir: Path) -> list[LogFile]`(정규 파일, 실제 날짜만, `(day, compressed)` 순; 폴더 없음·읽기 실패 → `[]`). `retention.preview`는 이 함수를 씁니다(동작 동일, Plan 3 테스트 그대로 통과).
  - `app.logstore.reader`:
    - `MAX_LINE_BYTES = 4 * 1024 * 1024`, `CHUNK_BYTES = 8 * 1024 * 1024`
    - `split_lines(data: bytes) -> tuple[list[bytes], int]`: `b"\n"`으로만 나눕니다(`str.splitlines` 금지 — U+2028/2029·`\x1c`–`\x1e`도 줄 경계로 봄). 마지막 `\n` 뒤의 조각은 돌려주지 않고, 두 번째 값은 소비한 바이트 수(마지막 `\n` 포함). 빈 줄은 버립니다.
    - `@dataclass(frozen=True) Chunk(lines: list[tuple[int, bytes]], next_offset: int, eof: bool, oversized: int)` — `lines`의 첫 값은 줄 시작 오프셋(압축 해제 기준).
    - `open_log(path: Path) -> BinaryIO`: `.gz`면 `gzip.open(path, "rb")`, 아니면 `open(path, "rb")`. 컨텍스트 매니저로 씁니다.
    - `read_chunk(fh: BinaryIO, offset: int, max_bytes: int = CHUNK_BYTES, *, final: bool = False) -> Chunk`: `fh.seek(offset)` 후 `max_bytes`를 읽습니다. 그 안에 `\n`이 없고 파일이 더 있으면 1MiB씩 더 읽어 `\n`이나 EOF까지; 줄 길이가 `MAX_LINE_BYTES`를 넘으면 다음 `\n`까지 건너뛰고 `oversized += 1`. `final=True`(불변인 `.gz`)이고 EOF에서 끝 조각이 남으면 그것도 한 줄로 돌려줍니다. `eof`는 읽기가 파일 끝에 닿았는지입니다.
    - `parse_line(raw: bytes) -> dict[str, Any] | None`: `json.loads(raw.decode("utf-8", "replace"))`가 dict이고 `ts`가 오프셋 있는 ISO 문자열(`datetime.fromisoformat` 성공 + `tzinfo` 있음), `cat`이 문자열일 때만 그 dict, 아니면 `None`.
  - `app.logstore.normalize`:
    - `CATEGORIES: tuple[str, ...]`(Global Constraints의 12개, 그 순서), `OUTCOMES = ("ok", "fail", "denied", "error", "failed", "timeout")`, `SEARCH_MAX_CHARS = 8192`
    - `@dataclass(frozen=True) Row(ts_ms: int, day: str, cat: str, event: str | None, user: str | None, session_id: int | None, client_ip: str | None, outcome: str | None, search: str, raw: str, line_hash: bytes)`
    - `normalize(obj: dict[str, Any], raw: bytes, day: str) -> Row` (W6):
      - `ts_ms = round(datetime.fromisoformat(obj["ts"]).timestamp() * 1000)`
      - `event`: `obj["event"]`가 문자열이면 그것, 아니면 `cat == "admin.audit"`일 때 `obj["action"]`, 아니면 None. 100자에서 자름.
      - `user`: 키 `user`, `actor_email`, `email`, `actor` 순으로 처음 나오는 비어 있지 않은 문자열(`actor`의 값 `"system"`은 건너뜀). 256자에서 자름.
      - `session_id`: `obj["session_id"]`가 `int`(bool 제외)일 때만.
      - `client_ip`: `obj["client_ip"]` → 없으면 `obj["ip"]`(문자열), 64자에서 자름.
      - `outcome`: `auth`면 `ok`가 bool일 때 `"ok"`/`"fail"`; `admin.audit`면 `result`; `mcp.action`면 `status`; `session`이고 `event == "logon_failed"`면 `"fail"`; 그 밖 None. 값이 `OUTCOMES` 밖이면 None.
      - `search`: `ts`·`cat` 키를 뺀 모든 값을 깊이 3까지 훑어 문자열과 정수(bool 제외)를 공백으로 이은 것, `SEARCH_MAX_CHARS`에서 자름.
      - `raw` = `raw.decode("utf-8", "replace")`, `line_hash = hashlib.blake2b(raw, digest_size=8).digest()`
  - `app.logstore.fts`: `MAX_TERMS = 10`, `MAX_TERM_CHARS = 100`; `class InvalidQuery(ValueError)`; `fts_expression(q: str | None) -> str | None`: 공백으로 나눈 각 낱말 중 글자·숫자가 하나라도 있는 것만 → `"` 를 `""`로 바꿔 `"<낱말>"*`로 감싸고 공백으로 이음(암묵적 AND, 마지막 토큰 접두사 검색, W3). 낱말 > 10개 또는 한 낱말 > 100자 → `InvalidQuery`. 남는 낱말이 없으면 None.
  - `app.logstore.index_db`:
    - `INDEX_SCHEMA_VERSION = 1`, `SCHEMA: str`(아래 DDL)
      ```sql
      CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
      CREATE TABLE files (
          name TEXT PRIMARY KEY,
          day TEXT NOT NULL,
          offset INTEGER NOT NULL DEFAULT 0,      -- uncompressed bytes consumed
          size INTEGER NOT NULL DEFAULT 0,        -- on-disk size at the last look
          lines INTEGER NOT NULL DEFAULT 0,
          bad_lines INTEGER NOT NULL DEFAULT 0,
          done INTEGER NOT NULL DEFAULT 0         -- 1 = .gz read to the end (immutable)
      );
      CREATE TABLE events (
          id INTEGER PRIMARY KEY,
          ts_ms INTEGER NOT NULL,
          day TEXT NOT NULL,
          cat TEXT NOT NULL,
          event TEXT,
          user TEXT COLLATE NOCASE,
          session_id INTEGER,
          client_ip TEXT,
          outcome TEXT,
          line_hash BLOB NOT NULL,
          raw TEXT NOT NULL
      );
      CREATE UNIQUE INDEX ux_events_line ON events(day, line_hash);
      CREATE INDEX ix_events_ts ON events(ts_ms);
      CREATE INDEX ix_events_user ON events(user, ts_ms);
      CREATE INDEX ix_events_cat ON events(cat, ts_ms);
      CREATE INDEX ix_events_session ON events(session_id, ts_ms) WHERE session_id IS NOT NULL;
      CREATE INDEX ix_events_ip ON events(client_ip, ts_ms) WHERE client_ip IS NOT NULL;
      CREATE VIRTUAL TABLE events_fts USING fts5(search, content='', contentless_delete=1, tokenize='unicode61 remove_diacritics 2');
      CREATE TABLE counts_min (bucket INTEGER NOT NULL, cat TEXT NOT NULL, user TEXT NOT NULL COLLATE NOCASE, n INTEGER NOT NULL, PRIMARY KEY (bucket, cat, user)) WITHOUT ROWID;
      CREATE TABLE counts_hour (bucket INTEGER NOT NULL, cat TEXT NOT NULL, user TEXT NOT NULL COLLATE NOCASE, n INTEGER NOT NULL, PRIMARY KEY (bucket, cat, user)) WITHOUT ROWID;
      ```
      (`counts_min.bucket = ts_ms // 60000`, `counts_hour.bucket = ts_ms // 3600000`, `user`가 None이면 `''`.)
    - `prepare_index(path: Path) -> tuple[sqlite3.Connection, bool]`(쓰기 연결, `check_same_thread=False`, `isolation_level=None`): 열고 `PRAGMA journal_mode=WAL`(반환 `wal` 확인), `synchronous=NORMAL`, `busy_timeout=5000`. `user_version`이 0이면 `SCHEMA` 적용 + `user_version = INDEX_SCHEMA_VERSION` → `(conn, True)`. 0도 아니고 `INDEX_SCHEMA_VERSION`도 아니면(작든 크든) 닫고 `path`, `path-wal`, `path-shm`을 지운 뒤 새로 만들어 `(conn, True)`(W2). 같으면 `(conn, False)`.
    - `open_reader(path: Path) -> sqlite3.Connection`: `sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, check_same_thread=False)`, `PRAGMA query_only=1`, `cache_size=-16384`, `mmap_size=268435456`, `busy_timeout=5000`, `row_factory = sqlite3.Row`.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_log_reader.py
import gzip
import json

import pytest

from app.logstore.files import list_log_files
from app.logstore.reader import open_log, parse_line, read_chunk, split_lines


def line(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False).encode("utf-8")


def test_split_on_newline_only_keeps_u2028_inside_a_line():
    a = line({"ts": "2026-11-04T14:00:00.000+09:00", "cat": "system", "text": "x\u2028y\u2029z\x1c"})
    lines, used = split_lines(a + b"\n\n" + b'{"ts": "partial')
    assert lines == [a] and used == len(a) + 2


def test_read_chunk_resumes_plain_and_gz(tmp_path):
    rows = [line({"ts": f"2026-11-04T14:00:0{i}.000+09:00", "cat": "system", "i": i}) for i in range(3)]
    body = b"\n".join(rows) + b"\n"
    (tmp_path / "2026-11-04.jsonl").write_bytes(body)
    (tmp_path / "2026-11-03.jsonl.gz").write_bytes(gzip.compress(body))
    for f in list_log_files(tmp_path):
        with open_log(f.path) as fh:
            c1 = read_chunk(fh, 0, max_bytes=len(rows[0]) + 5)
            assert [r for _, r in c1.lines] == [rows[0]] and c1.next_offset == len(rows[0]) + 1
            c2 = read_chunk(fh, c1.next_offset)
            assert [r for _, r in c2.lines] == rows[1:] and c2.eof and c2.lines[0][0] == c1.next_offset


def test_final_gz_tail_without_newline_is_a_line(tmp_path):
    a = line({"ts": "2026-11-04T14:00:00.000+09:00", "cat": "system"})
    p = tmp_path / "2026-11-04.jsonl.gz"; p.write_bytes(gzip.compress(a))
    with open_log(p) as fh:
        assert [r for _, r in read_chunk(fh, 0, final=True).lines] == [a]


def test_oversized_line_is_skipped_and_counted(tmp_path, monkeypatch):
    import app.logstore.reader as reader
    monkeypatch.setattr(reader, "MAX_LINE_BYTES", 64)
    ok = line({"ts": "2026-11-04T14:00:00.000+09:00", "cat": "system"})
    p = tmp_path / "2026-11-04.jsonl"; p.write_bytes(b"x" * 200 + b"\n" + ok + b"\n")
    with open_log(p) as fh:
        c = read_chunk(fh, 0, max_bytes=32)
    assert c.oversized == 1 and [r for _, r in c.lines] == [ok]


@pytest.mark.parametrize("raw", [b"[]", b'"x"', b'{"cat": "system"}', b'{"ts": "nope", "cat": "system"}',
                                 b'{"ts": "2026-11-04T14:00:00+09:00"}', b"{broken",
                                 b'{"ts": "2026-11-04T14:00:00", "cat": "system"}'])
def test_parse_line_rejects(raw):
    assert parse_line(raw) is None


def test_list_log_files_ignores_other_names(tmp_path):
    for n in ("2026-11-04.jsonl", "2026-11-03.jsonl.gz", "2026-13-01.jsonl", "notes.txt", "2026-11-04.jsonl.gz.tmp"):
        (tmp_path / n).write_bytes(b"x")
    assert [f.name for f in list_log_files(tmp_path)] == ["2026-11-03.jsonl.gz", "2026-11-04.jsonl"]
```

```python
# server/tests/test_log_normalize.py
import json
from datetime import UTC, datetime

import pytest

from app.logstore.normalize import SEARCH_MAX_CHARS, normalize

TS = "2026-11-04T14:03:22.418+09:00"


def row(obj):
    obj = {"ts": TS, **obj}
    return normalize(obj, json.dumps(obj, ensure_ascii=False).encode(), "2026-11-04")


@pytest.mark.parametrize("obj,user,event,outcome,ip", [
    ({"cat": "activity.command", "event": "script_block", "user": "CORP\\hong", "client_ip": "10.0.3.21", "session_id": 2},
     "CORP\\hong", "script_block", None, "10.0.3.21"),
    ({"cat": "auth", "event": "login", "email": "a@x.com", "ip": "1.2.3.4", "ok": False}, "a@x.com", "login", "fail", "1.2.3.4"),
    ({"cat": "admin.audit", "action": "user_create", "actor_email": "a@x.com", "ip": "127.0.0.1", "result": "denied"},
     "a@x.com", "user_create", "denied", "127.0.0.1"),
    ({"cat": "mcp.action", "actor": "system", "status": "timeout", "name": "calc"}, None, None, "timeout", None),
    ({"cat": "session", "event": "logon_failed", "user": "hong"}, "hong", "logon_failed", "fail", None),
    ({"cat": "mcp.action", "actor": "d@x.com", "status": "weird"}, "d@x.com", None, None, None),
])
def test_normalize_actor_event_outcome(obj, user, event, outcome, ip):
    r = row(obj)
    assert (r.user, r.event, r.outcome, r.client_ip, r.cat, r.day) == (user, event, outcome, ip, obj["cat"], "2026-11-04")


def test_timestamp_and_session():
    r = row({"cat": "session", "session_id": 3})
    assert datetime.fromtimestamp(r.ts_ms / 1000, UTC) == datetime(2026, 11, 4, 5, 3, 22, 418000, tzinfo=UTC)
    assert r.session_id == 3 and row({"cat": "session", "session_id": True}).session_id is None


def test_search_text_flattens_and_caps():
    r = row({"cat": "admin.audit", "action": "mcp_update", "actor_email": "a@x.com", "target": {"id": 3, "fields": ["name", "port"]}})
    for word in ("mcp_update", "a@x.com", "3", "name", "port"):
        assert word in r.search.split()
    assert "admin.audit" not in r.search
    assert len(row({"cat": "system", "text": "x" * 10_000}).search) == SEARCH_MAX_CHARS


def test_same_line_same_hash():
    assert row({"cat": "system"}).line_hash == row({"cat": "system"}).line_hash
    assert len(row({"cat": "system"}).line_hash) == 8
```

```python
# server/tests/test_index_db.py
import pytest

from app.logstore.fts import InvalidQuery, fts_expression
from app.logstore.index_db import INDEX_SCHEMA_VERSION, open_reader, prepare_index


def test_prepare_index_recreates_on_version_mismatch(tmp_path):
    p = tmp_path / "index.db"
    conn, rebuilt = prepare_index(p); assert rebuilt
    conn.execute("INSERT INTO meta (key, value) VALUES ('x', '1')")
    conn.execute(f"PRAGMA user_version = {INDEX_SCHEMA_VERSION + 1}"); conn.close()
    conn2, rebuilt2 = prepare_index(p)
    assert rebuilt2 and conn2.execute("SELECT COUNT(*) FROM meta").fetchone()[0] == 0
    conn2.close()
    conn3, rebuilt3 = prepare_index(p); assert not rebuilt3; conn3.close()


def test_reader_is_read_only(tmp_path):
    p = tmp_path / "index.db"; prepare_index(p)[0].close()
    r = open_reader(p)
    with pytest.raises(Exception):
        r.execute("INSERT INTO meta (key, value) VALUES ('x', '1')")
    r.close()


def test_fts_matches_prefixes_korean_particles_and_hyphenated_commands(tmp_path):
    conn, _ = prepare_index(tmp_path / "index.db")
    conn.execute("INSERT INTO events_fts (rowid, search) VALUES (1, ?)", ("Get-Process | Stop-Process -Name notepad 로그를 메모장",))
    hit = lambda q: conn.execute("SELECT rowid FROM events_fts WHERE events_fts MATCH ?", (fts_expression(q),)).fetchall()
    for q in ("Stop-Process", "notep", "로그", "메모장 notepad", 'get"process'):
        assert hit(q) == [(1,)], q
    assert hit("otepad") == [] and hit("notepad zebra") == []
    conn.close()


def test_fts_expression_rules():
    assert fts_expression('a "b"') == '"a"* """b"""*'
    assert fts_expression("| --  ") is None and fts_expression(None) is None
    with pytest.raises(InvalidQuery):
        fts_expression(" ".join(f"w{i}" for i in range(11)))
    with pytest.raises(InvalidQuery):
        fts_expression("x" * 101)
```

- [ ] **Step 2: 실패 확인** — Run: `uv run python -m pytest tests/test_log_reader.py tests/test_log_normalize.py tests/test_index_db.py tests/test_retention_preview.py -v` → FAIL(새 모듈 없음)

- [ ] **Step 3: 구현** — 위 Interfaces대로. `test_fts_matches...`의 `'get"process'`는 `"get""process"*` → 토큰 `get`, `process`(접두사)로 맞습니다.

- [ ] **Step 4: 통과 확인** — Run: `uv run python -m pytest -q` → 전체 통과, ruff·mypy 0건

- [ ] **Step 5: Commit** — `git commit -m "feat: JSONL/gz log reader, event normalization and the FTS5 index schema"`

---

### Task 3: 색인기 `LogIndex`와 배선, `reindex` 명령

**Files:**
- Create: `server/app/logstore/indexer.py`, `server/tests/log_helpers.py`, `server/tests/test_log_index.py`
- Modify: `server/app/services.py`(`log_index`, 플러시 리스너), `server/app/main.py`(`serve`에서 시작·정지), `server/app/__main__.py`(`reindex` 하위 명령, `main() -> int`), `server/tests/conftest.py`(`services` 픽스처)

**Interfaces:**
- Consumes: Task 1 `LogWriter.add_flush_listener`, Task 2 전부, Plan 4 `LogSink`·`tests.winfakes.ListLog`·`eventually`.
- Produces:
  - `app.logstore.indexer`:
    - `@dataclass(frozen=True) FileState(name: str, day: str, offset: int, size: int, lines: int, bad_lines: int, done: bool)`
    - `@dataclass(frozen=True) IndexStatus(ready: bool, rebuilding: bool, files: int, pending_files: int, pending_bytes: int, rows: int, bad_lines: int, oldest_day: str | None, newest_day: str | None, last_indexed_at: datetime | None)`
    - `@dataclass(frozen=True) IndexSummary(rows: int, oldest_day: str | None, newest_day: str | None)`
    - `class IndexReader(path: Path)`: 스레드마다 `open_reader` 연결 하나(`threading.local`, 만든 연결 목록을 잠금과 함께 보관), `close_all()`. Task 3에서 만드는 메서드: `summary() -> IndexSummary`, `days() -> dict[str, int]`(`SELECT day, COUNT(*) ... GROUP BY day`), `count_before_day(day: str) -> int`. Task 4가 조회 메서드를 더합니다. 모두 블로킹이며 `asyncio.to_thread`로 부릅니다.
    - `class LogIndex(path: Path, logs_dir: Path, clock: Clock, log: LogSink, *, batch_lines: int = 5000, poll_sec: float = 1.0, backlog_lines_per_cycle: int = 50_000)`:
      - `async start(run_loop: bool = True) -> None`: `await asyncio.to_thread(prepare_index, path)`; 새로 만들었고 `logs_dir`에 로그 파일이 있으면 `log.emit("system", event="logindex.rebuilt", reason="schema"|"new")`(첫 실행의 빈 루트에서는 기록하지 않음). `run_loop`이면 배경 태스크(`poll_sec`마다 또는 `wake()` 때 `index_once()`; 예외는 `system` `logindex.cycle_failed {error}` 후 계속).
      - `async stop()`: 태스크 취소·대기 → 쓰기 연결 닫기 → `reader().close_all()`.
      - `wake() -> None`(루프 스레드; `LogWriter` 플러시 리스너로 등록).
      - `async index_once() -> int`(새로 넣은 행 수). 한 번의 차례:
        1. `list_log_files` + `files` 표 상태. 디스크에 없는 상태 행은 지웁니다(색인 행은 남김 — 보존 정리가 날짜로 지움).
        2. **실시간 집합** = 오늘·어제(KST, `clock` 기준)의 `.jsonl`: EOF까지 처리. 그다음 **밀린 집합** = 나머지에서 처리할 것이 있는 파일을 날짜 **내림차순**: 이번 차례에 처리한 줄 수가 `backlog_lines_per_cycle` 이상이 되면 그 묶음 뒤에 멈춤(W10).
        3. `.jsonl`: 크기 < `offset`이면 잘린 것 → `offset = 0`부터 다시 읽고 `system` `logindex.file_truncated {file, before: offset, after: size}`. `.jsonl.gz`: `done`이면 건너뜀, 아니면 `final=True`로 끝까지 읽고 `done = 1`.
        4. 묶음(≤ `batch_lines`줄)마다 `run_exclusive` 안에서 한 트랜잭션: `BEGIN IMMEDIATE` → 줄마다 `parse_line` → None이면 `bad += 1` → `normalize` → `INSERT OR IGNORE INTO events` → 넣어졌으면(`rowcount == 1`) `INSERT INTO events_fts (rowid, search)`와 롤업 누적 → 롤업 `INSERT ... ON CONFLICT (bucket, cat, user) DO UPDATE SET n = n + excluded.n`(두 표) → `files` upsert(`offset`, `size`, `lines += n`, `bad_lines += bad`, `done`) → `COMMIT`.
        5. 파일별 잘못된 줄(+ `oversized`)이 이번 차례에 있었으면 `system` `logindex.bad_lines {file, count}`를 그 파일·그 차례에 한 번.
        6. 상태 갱신: `pending_bytes` = Σ(`.jsonl`: 크기 − offset, `.gz` 미완료: 디스크 크기), `ready = pending_files == 0`. 처음 `ready`가 되면 `system` `logindex.ready {rows, duration_ms}`(시작부터).
      - `async run_exclusive(fn: Callable[[sqlite3.Connection], T]) -> T`: `asyncio.Lock` 안에서 `await asyncio.to_thread(fn, conn)`.
      - `status() -> IndexStatus`(마지막 차례 결과, 루프 스레드), `reader() -> IndexReader`(하나를 공유).
  - `Services.log_index: LogIndex`(`build_services`: `LogIndex(paths.index_db_path, paths.logs_dir, clock, log)`, `log.add_flush_listener(log_index.wake)`).
  - `serve()`: `await services.log.start()` 다음 `await services.log_index.start()`, 정지 때 `log.stop()` 전에 `await services.log_index.stop()`.
  - `tests/conftest.py`의 `services` 픽스처: `await svc.log_index.start(run_loop=False)`, 정리 때 `await svc.log_index.stop()`(모니터 정지 다음, 로그 정지 전).
  - `app.__main__.main(argv: list[str] | None = None) -> int`, `if __name__ == "__main__": sys.exit(main())`. 첫 인자가 `reindex`면 `python -m app reindex [--root PATH]`: 루트 잠금(Task 8 `RootLock`; Task 8 전까지는 잠금 없이) → `index.db`·`-wal`·`-shm` 삭제 → `LogIndex(... run_loop=False)`로 `ready`가 될 때까지 `index_once()` → stdout에 `indexed <rows> rows from <files> files` → 0.
  - `tests/log_helpers.py`: `ev(ts: str, cat: str, **fields) -> bytes`(`json.dumps({"ts": ts, "cat": cat, **fields}, ensure_ascii=False).encode()`), `write_lines(logs_dir: Path, day: str, lines: list[bytes]) -> Path`(이어 쓰기, 각 줄 뒤 `\n`), `write_gz(logs_dir, day, lines) -> Path`, `async index_all(services) -> None`(`await services.log.flush()` 후 `status().ready`가 될 때까지 `index_once()`, 최대 1,000번).

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_log_index.py
import sqlite3

import pytest_asyncio

from app.__main__ import main
from app.logstore.index_db import INDEX_SCHEMA_VERSION
from app.logstore.indexer import LogIndex
from app.logstore.writer import DailyJsonlWriter, LogWriter
from tests.log_helpers import ev, write_gz, write_lines
from tests.winfakes import ListLog, eventually


@pytest_asyncio.fixture
async def env(tmp_path, clock):  # clock: 2026-11-04 14:00 KST
    logs = tmp_path / "logs"; logs.mkdir()
    log = ListLog()
    idx = LogIndex(tmp_path / "index.db", logs, clock, log, batch_lines=3, backlog_lines_per_cycle=4)
    await idx.start(run_loop=False)
    yield idx, logs, log
    await idx.stop()


def sys_events(log, name):
    return [f for cat, _at, f in log.events if cat == "system" and f.get("event") == name]


async def test_indexes_complete_lines_and_tails_partial_ones(env):
    idx, logs, _ = env
    a = ev("2026-11-04T14:00:00.000+09:00", "system", event="a")
    b = ev("2026-11-04T14:00:01.000+09:00", "system", event="b")
    (logs / "2026-11-04.jsonl").write_bytes(a + b"\n" + b[:10])
    assert await idx.index_once() == 1
    with (logs / "2026-11-04.jsonl").open("ab") as fh: fh.write(b[10:] + b"\n")
    assert await idx.index_once() == 1 and idx.reader().summary().rows == 2 and idx.status().ready


async def test_duplicate_lines_from_a_retry_are_indexed_once(env):
    idx, logs, _ = env
    a = ev("2026-11-04T14:00:00.000+09:00", "auth", event="login", email="a@x.com", ok=True)
    write_lines(logs, "2026-11-04", [a, a, a])
    assert await idx.index_once() == 1


async def test_recent_days_first_then_backlog_newest_first(env):
    idx, logs, _ = env
    for day in ("2026-10-01", "2026-10-02", "2026-10-03", "2026-11-04"):
        write_lines(logs, day, [ev(f"{day}T10:00:0{i}.000+09:00", "system", i=i) for i in range(3)])
    await idx.index_once()
    assert idx.reader().days() == {"2026-11-04": 3, "2026-10-03": 3, "2026-10-02": 3}
    assert not idx.status().ready and idx.status().pending_files == 1
    await idx.index_once()
    assert idx.reader().days()["2026-10-01"] == 3 and idx.status().ready


async def test_gz_files_are_read_once(env):
    idx, logs, _ = env
    write_gz(logs, "2026-10-30", [ev("2026-10-30T09:00:00.000+09:00", "system", i=i) for i in range(2)])
    assert await idx.index_once() == 2 and await idx.index_once() == 0


async def test_truncated_file_is_reread_without_duplicates_and_reported(env):
    idx, logs, log = env
    lines = [ev(f"2026-11-04T13:00:0{i}.000+09:00", "system", i=i) for i in range(3)]
    write_lines(logs, "2026-11-04", lines); await idx.index_once()
    (logs / "2026-11-04.jsonl").write_bytes(lines[0] + b"\n" + ev("2026-11-04T13:30:00.000+09:00", "system", i=9) + b"\n")
    assert await idx.index_once() == 1 and idx.reader().summary().rows == 4
    assert sys_events(log, "logindex.file_truncated")[0]["file"] == "2026-11-04.jsonl"


async def test_bad_lines_are_skipped_counted_and_reported_once(env):
    idx, logs, log = env
    good = ev("2026-11-04T13:00:00.000+09:00", "system")
    (logs / "2026-11-04.jsonl").write_bytes(b"{broken\n" + good + b"\n[]\n")
    assert await idx.index_once() == 1
    assert idx.status().bad_lines == 2 and [e["count"] for e in sys_events(log, "logindex.bad_lines")] == [2]


async def test_rollups_match_rows(env, tmp_path):
    idx, logs, _ = env
    write_lines(logs, "2026-11-04", [ev(f"2026-11-04T13:{i:02d}:00.000+09:00", "activity.window", user=f"u{i % 2}") for i in range(7)])
    await idx.index_once()
    with sqlite3.connect(tmp_path / "index.db") as c:
        assert c.execute("SELECT SUM(n) FROM counts_min").fetchone()[0] == 7
        assert c.execute("SELECT SUM(n) FROM counts_hour").fetchone()[0] == 7
        assert c.execute("SELECT COUNT(*) FROM events_fts").fetchone()[0] == 7


async def test_version_mismatch_rebuilds_from_jsonl(tmp_path, clock):
    logs = tmp_path / "logs"; logs.mkdir()
    write_lines(logs, "2026-11-04", [ev("2026-11-04T13:00:00.000+09:00", "system")])
    idx = LogIndex(tmp_path / "index.db", logs, clock, ListLog()); await idx.start(run_loop=False)
    await idx.index_once(); await idx.stop()
    with sqlite3.connect(tmp_path / "index.db") as c:
        c.execute(f"PRAGMA user_version = {INDEX_SCHEMA_VERSION + 7}")
    log = ListLog()
    idx2 = LogIndex(tmp_path / "index.db", logs, clock, log); await idx2.start(run_loop=False)
    assert idx2.reader().summary().rows == 0 and sys_events(log, "logindex.rebuilt")[0]["reason"] == "schema"
    await idx2.index_once(); assert idx2.reader().summary().rows == 1
    await idx2.stop()


async def test_flush_listener_wakes_the_indexer(tmp_path, clock):
    logs = tmp_path / "logs"; logs.mkdir()
    w = LogWriter(DailyJsonlWriter(logs), clock, flush_interval=0.01); await w.start()
    idx = LogIndex(tmp_path / "index.db", logs, clock, w, poll_sec=60); await idx.start()
    w.add_flush_listener(idx.wake)
    w.emit("system", event="hello"); await w.flush()
    await eventually(lambda: idx.status().rows >= 1)
    await idx.stop(); await w.stop()


def test_reindex_command(tmp_path):
    write_lines(tmp_path / "logs", "2026-11-04", [ev("2026-11-04T13:00:00.000+09:00", "system", i=i) for i in range(4)])
    assert main(["reindex", "--root", str(tmp_path)]) == 0
    with sqlite3.connect(tmp_path / "data" / "index.db") as c:
        assert c.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 4
```

`write_lines`는 `logs_dir`가 없으면 만듭니다.

- [ ] **Step 2: 실패 확인** — Run: `uv run python -m pytest tests/test_log_index.py -v` → FAIL

- [ ] **Step 3: 구현** — 위 Interfaces대로. 줄 읽기와 파싱·정규화는 `run_exclusive`에 넘기는 함수 안(스레드)에서 하고, 루프 스레드는 결과(넣은 행 수, 잘못된 줄 수, 잘림 여부)만 받아 로그를 남깁니다. `main()`의 기존 서버 실행 경로는 `return 0`으로 끝납니다(Plan 3 `test_main_cli.py`의 `parse_args` 테스트는 그대로).

- [ ] **Step 4: 통과 확인** — Run: `uv run python -m pytest -q` → 전체 통과(기존 테스트의 `services`도 색인기를 가짐), ruff·mypy 0건

- [ ] **Step 5: Commit** — `git commit -m "feat: tailing log indexer with dedup, recent-first backlog, rollups and a reindex command"`

---
### Task 4: 조회 엔진(`IndexReader` 확장)과 100만 건 성능 하네스

**Files:**
- Create: `server/app/logstore/query.py`, `server/tests/test_log_query.py`
- Create: `server/tests/perf/__init__.py`, `server/tests/perf/gen.py`, `server/tests/perf/conftest.py`, `server/tests/perf/test_log_perf.py`
- Modify: `server/app/logstore/indexer.py`(`IndexReader`가 `query.py`의 함수를 메서드로 노출), `server/pyproject.toml`(마커 `perf`, `bundle`; `addopts`), `.gitignore`(`server/.cache/`)

**Interfaces:**
- Consumes: Task 2 `fts_expression`·`InvalidQuery`·`CATEGORIES`·`OUTCOMES`, Task 3 `IndexReader`·`LogIndex`.
- Produces (`app.logstore.query`):
  - 상수: `DEFAULT_PAGE = 200`, `MAX_PAGE = 1000`, `MAX_USERS = 50`, `MAX_EVENTS = 20`, `MAX_SPAN_MS = 3660 * 86_400_000`, `BUCKET_LADDER_SEC = (60, 300, 600, 1800, 3600, 10800, 21600, 43200, 86400)`, `KST_OFFSET_MS = 9 * 3_600_000`, `TOP_USERS = 10`.
  - `@dataclass(frozen=True) LogFilter(from_ms: int, to_ms: int, users: tuple[str, ...] = (), cats: tuple[str, ...] = (), events: tuple[str, ...] = (), outcomes: tuple[str, ...] = (), session_id: int | None = None, client_ip: str | None = None, q: str | None = None, channel: str | None = None)`. 구간은 `[from_ms, to_ms)`. `__post_init__`에서 `from_ms < to_ms`, 폭 ≤ `MAX_SPAN_MS`, `users` ≤ 50(각 1–256자), `cats ⊆ CATEGORIES`, `events` ≤ 20(각 1–64자), `outcomes ⊆ OUTCOMES`, `channel ∈ {None, "local", "external"}`, `fts_expression(q)`가 예외 없이 계산됨 — 어기면 `InvalidQuery`. 계산된 FTS 식은 속성 `fts: str | None`(`object.__setattr__`로 저장).
  - `@dataclass(frozen=True) Cursor(ts_ms: int, id: int)`; `encode_cursor(c) -> str`(`[ts_ms, id]` JSON의 base64url, 패딩 제거), `decode_cursor(s: str) -> Cursor`(디코딩·JSON·모양(정수 2개)이 틀리면 `InvalidQuery`).
  - `@dataclass(frozen=True) LogRow(id: int, ts_ms: int, cat: str, event: str | None, user: str | None, session_id: int | None, client_ip: str | None, outcome: str | None, data: dict[str, Any])`
  - `@dataclass(frozen=True) Page(rows: list[LogRow], next_cursor: str | None)`
  - `@dataclass(frozen=True) Histogram(start_ms: int, to_ms: int, bucket_sec: int, starts_ms: list[int], series: list[tuple[str | None, list[int]]], total: int, source: Literal["rollup", "scan"])`
  - `choose_bucket(span_ms: int, max_buckets: int) -> int`: `BUCKET_LADDER_SEC`에서 `ceil(span / b) <= max_buckets`인 가장 작은 값, 없으면 `86400 * ceil(span_sec / 86400 / max_buckets)`.
  - `bucket_start(from_ms: int, bucket_sec: int) -> int` = `((from_ms + KST_OFFSET_MS) // b_ms) * b_ms - KST_OFFSET_MS`(KST 경계 정렬, W8).
  - `IndexReader`(Task 3 클래스에 추가, 모두 블로킹):
    - `page(f: LogFilter, cursor: Cursor | None, limit: int = DEFAULT_PAGE) -> Page`: 최신순(`ts_ms DESC, id DESC`), 커서가 있으면 `(ts_ms, id) < (c.ts_ms, c.id)`. **구동 차원**(W7): `session_id` → `client_ip` → `users`(값마다 한 질의) → `cats`(값마다 한 질의) → 시간만. 여러 값이면 질의마다 `LIMIT limit + 1`로 읽어 `heapq.merge`(키 `(-ts_ms, -id)`)로 합친 뒤 `limit + 1`개를 취합니다. 나머지 조건은 같은 질의의 잔여 조건: `ts_ms >= ? AND ts_ms < ?`, `user IN (...)`, `cat IN (...)`, `event IN (...)`, `outcome IN (...)`, `session_id = ?`, `client_ip = ?`, `json_extract(raw, '$.channel') = ?`, `id IN (SELECT rowid FROM events_fts WHERE events_fts MATCH ?)`. 단, 키워드만 있고 다른 구동 차원이 없으면 FTS가 구동합니다(`FROM events_fts JOIN events e ON e.id = events_fts.rowid WHERE events_fts MATCH ? AND ...`). `limit + 1`개를 얻으면 `limit`개를 돌려주고 `next_cursor` = 돌려준 마지막 행, 아니면 None. `data = json.loads(raw)`.
    - `histogram(f: LogFilter, buckets: int = 60, group: Literal["none", "cat", "user"] = "none") -> Histogram`: `b = choose_bucket(to − from, buckets)`, `start = bucket_start(f.from_ms, b)`, 막대 수 `n = ceil((to − start) / b_ms)`, `starts_ms = [start + i·b_ms]`. **롤업 경로**는 `q`·`session_id`·`client_ip`·`events`·`outcomes`·`channel`이 모두 없고 `from_ms`·`to_ms`가 60,000의 배수일 때: `from_ms`·`to_ms`가 3,600,000의 배수이고 `b ≥ 3600`이면 `counts_hour`, 아니면 `counts_min`에서 `bucket >= from/단위 AND bucket < to/단위`(+ `cat IN`, `user IN`)를 막대로 모읍니다. 그 밖은 **스캔 경로**: `page`와 같은 조건으로 `SELECT (ts_ms - :start) / :b_ms AS k [, cat | user], COUNT(*) ... GROUP BY ...`. `group="user"`는 기간 합계 상위 `TOP_USERS`명(합계 내림차순, 같으면 소문자 이름순) + 나머지 키 `"__other__"`(0이면 생략), 사용자 없는 행은 키 `None` 계열. `group="cat"`은 나타난 카테고리마다 한 계열(`CATEGORIES` 순). `group="none"`은 키 `None` 한 계열.
    - `users(f: LogFilter, limit: int = 200) -> list[tuple[str, int]]`: **`f.users`를 무시하고** 나머지 조건으로 사용자별 건수(빈 사용자 제외), `(-count, user.lower())` 순. 경로 선택은 `histogram`과 같습니다.
    - `iter_rows(f: LogFilter, limit: int, chunk: int = 5000) -> Iterator[LogRow]`: 전용 연결(`open_reader`, 끝나거나 생성기가 닫히면 닫음)로 `page`와 같은 질의를 커서로 이어 부르며 최대 `limit`행(최신순).
- Produces (성능 하네스, W9):
  - `tests/perf/gen.py`: `GEN_VERSION = 1`, `generate(logs_dir: Path, rows: int, days: int, end_day: date, seed: int) -> GenInfo` — 날짜별 `YYYY-MM-DD.jsonl`을 시간순으로 씁니다. 카테고리 비율 `activity.window` 40%, `activity.process` 25%, `activity.command` 10%, `mcp.health` 8%, `system` 7%, `session` 3%, `auth` 2%, `activity.idle` 1.5%, `mcp.action` 1%, `admin.audit` 1%, `notice` 1%, `tamper` 0.5%. 사용자 `CORP\user01`–`CORP\user20`(Windows 범주, `user` 필드) + `dev1@x.com`–`dev5@x.com`(`auth`의 `email`, `admin.audit`의 `actor_email`, `mcp.action`의 `actor`), 사용자 k의 세션 `(k % 8) + 2`, IP 30개(`10.0.3.1`–`10.0.3.30`), 본문은 `random.Random(seed)`로 만든 고정 낱말 2,000개(영문·한글 섞음)에서 4–12개, `activity.command`의 5%에 `zebra-<n>` 포함(전체의 0.5%). `GenInfo(rows, days, users: list[str], sessions: dict[str, int], end_day)`.
  - `tests/perf/conftest.py`: 세션 범위 픽스처 `perf_index`: 캐시 폴더 `server/.cache/perf-v{GEN_VERSION}-1000000/`(없으면 `generate(rows=1_000_000, days=30, end_day=date(2026, 11, 4), seed=20261108)` → `LogIndex(..., backlog_lines_per_cycle=200_000)`로 `ready`까지 색인, 걸린 시간으로 `ingest_rate`(줄/초)를 `meta.json`에 기록). `PerfIndex(reader: IndexReader, info: GenInfo, ingest_rate: float)`. `record(name, value)`는 `server/.cache/perf-results.json`에 이름별 값(초 또는 수)을 씁니다. `SCENARIOS: dict[str, Callable[[PerfIndex], object]]`(아래 표). 픽스처 `perf_purge`는 Task 6이 더합니다.
  - 시나리오(`end` = 2026-11-05 00:00 KST, 모든 경계는 분 단위):
    | 이름 | 질의 |
    |---|---|
    | S1 | `page`, 최근 24시간, 조건 없음 |
    | S2 | `page`, 최근 7일, `users` = (`CORP\user03`, `CORP\user11`) |
    | S3 | `page`, 30일, `cats` = (`activity.command`,) |
    | S4 | `page`, 30일, `q` = `"zebra"` |
    | S5 | `page`, 7일, `users` = (`CORP\user05`,), `cats` = (`activity.window`,), `session_id` = `info.sessions["CORP\\user05"]` |
    | S6 | `histogram`, 30일, `group="cat"`, 60막대(롤업) |
    | S7 | `histogram`, 7일, `users` = S2와 같음, `group="none"`(롤업) |
    | S8 | `users`, 30일, 조건 없음(롤업) |
    | S9 | `histogram`, 30일, `q` = `"zebra"`(스캔) |
    | S10 | `page`, 30일, 커서 = 15일째 정오~`end` 구간 `page`의 첫 행(깊은 커서) |
    각 시나리오: 한 번 예열 → 5번 측정 → **중앙값 < 300ms**.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_log_query.py
from datetime import datetime

import pytest
import pytest_asyncio

from app.logstore.fts import InvalidQuery
from app.logstore.indexer import LogIndex
from app.logstore.query import Cursor, LogFilter, choose_bucket, decode_cursor, encode_cursor
from tests.log_helpers import ev, write_lines
from tests.winfakes import ListLog

USERS = ["CORP\\hong", "CORP\\kim", "a@x.com"]
CATS = ["activity.command", "activity.window", "auth"]


def ms(kst: str) -> int:
    return int(datetime.fromisoformat(kst).timestamp() * 1000)


def F(**kw) -> LogFilter:
    return LogFilter(from_ms=ms("2026-11-04T13:00:00+09:00"), to_ms=ms("2026-11-04T14:00:00+09:00"), **kw)


@pytest_asyncio.fixture
async def reader(tmp_path, clock):
    logs = tmp_path / "logs"; lines = []
    for i in range(30):
        cat, user = CATS[i % 3], USERS[i % 3]
        extra = {"email": user, "event": "login", "ok": i % 2 == 0} if cat == "auth" else {"user": user, "session_id": 2}
        lines.append(ev(f"2026-11-04T13:{i:02d}:00.000+09:00", cat, text="cmd-7 zebra" if i == 7 else f"cmd-{i}", **extra))
    write_lines(logs, "2026-11-04", lines)
    idx = LogIndex(tmp_path / "index.db", logs, clock, ListLog()); await idx.start(run_loop=False)
    await idx.index_once()
    yield idx.reader()
    await idx.stop()


def test_page_newest_first_with_cursor(reader):
    p1 = reader.page(F(), None, 10)
    assert [r.data["text"] for r in p1.rows][:2] == ["cmd-29", "cmd-28"] and p1.next_cursor
    p2 = reader.page(F(), decode_cursor(p1.next_cursor), 10)
    assert p2.rows[0].data["text"] == "cmd-19"
    p3 = reader.page(F(), decode_cursor(p2.next_cursor), 10)
    assert len(p3.rows) == 10 and p3.next_cursor is None


def test_filters_fan_out_and_merge(reader):
    rows = reader.page(F(users=("corp\\HONG", "a@x.com")), None, 100).rows
    assert len(rows) == 20 and [r.ts_ms for r in rows] == sorted((r.ts_ms for r in rows), reverse=True)
    assert {r.user.lower() for r in rows} == {"corp\\hong", "a@x.com"}
    assert len(reader.page(F(cats=("auth",), outcomes=("fail",)), None, 100).rows) == 5
    assert [r.data["text"] for r in reader.page(F(q="zeb"), None, 100).rows] == ["cmd-7 zebra"]
    assert len(reader.page(F(session_id=2, cats=("activity.window",)), None, 100).rows) == 10
    merged = reader.page(F(users=tuple(USERS)), None, 7)
    assert [r.data["text"] for r in merged.rows] == [f"cmd-{i}" for i in range(29, 22, -1)] and merged.next_cursor


def test_histogram_rollup_equals_scan(reader):
    h1 = reader.histogram(F(), buckets=6)
    assert (h1.source, h1.bucket_sec, h1.series) == ("rollup", 600, [(None, [10, 10, 10, 0, 0, 0])])
    h2 = reader.histogram(F(q="cmd"), buckets=6)
    assert h2.source == "scan" and h2.series == h1.series and h2.total == 30
    hc = reader.histogram(F(), buckets=6, group="cat")
    assert [k for k, _ in hc.series] == ["activity.command", "activity.window", "auth"]
    hu = reader.histogram(F(cats=("activity.command",)), buckets=6, group="user")
    assert hu.series == [("CORP\\hong", [4, 3, 3, 0, 0, 0])]


def test_users_facet_ignores_the_users_filter(reader):
    assert reader.users(F(users=("CORP\\hong",))) == [("a@x.com", 10), ("CORP\\hong", 10), ("CORP\\kim", 10)]
    assert reader.users(F(cats=("auth",))) == [("a@x.com", 10)]


def test_iter_rows_streams_in_chunks(reader):
    rows = list(reader.iter_rows(F(), limit=25, chunk=10))
    assert len(rows) == 25 and rows[0].data["text"] == "cmd-29"


@pytest.mark.parametrize("span_ms,max_b,want", [(3_600_000, 60, 60), (7 * 86_400_000, 60, 10800),
                                                (30 * 86_400_000, 60, 43200), (180 * 86_400_000, 60, 259200)])
def test_choose_bucket(span_ms, max_b, want):
    assert choose_bucket(span_ms, max_b) == want


def test_cursor_round_trip_and_validation():
    assert decode_cursor(encode_cursor(Cursor(1793000000000, 42))) == Cursor(1793000000000, 42)
    for bad in ("!!", "W10", encode_cursor(Cursor(1, 2))[:-3]):
        with pytest.raises(InvalidQuery):
            decode_cursor(bad)
    with pytest.raises(InvalidQuery):
        F(cats=("nope",))
    with pytest.raises(InvalidQuery):
        LogFilter(from_ms=5, to_ms=5)
    with pytest.raises(InvalidQuery):
        F(users=tuple(f"u{i}" for i in range(51)))
```

`hu` 기대값의 근거: `activity.command`는 `i % 3 == 0`(사용자 hong) — 13:00·03·06·09(4개), 13:12·15·18(3개), 13:21·24·27(3개).

```python
# server/tests/perf/test_log_perf.py
import statistics
import time

import pytest

from tests.perf.conftest import SCENARIOS, record

pytestmark = pytest.mark.perf


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_query_under_300ms(perf_index, name):
    run = SCENARIOS[name]
    run(perf_index)  # warm-up
    times = []
    for _ in range(5):
        t = time.perf_counter(); run(perf_index); times.append(time.perf_counter() - t)
    med = statistics.median(times)
    record(name, med)
    assert med < 0.300, f"{name}: median {med * 1000:.0f} ms"


def test_ingest_rate(perf_index):
    record("ingest_lines_per_sec", perf_index.ingest_rate)
    assert perf_index.ingest_rate >= 2000
```

- [ ] **Step 2: 실패 확인** — Run: `uv run python -m pytest tests/test_log_query.py -v` → FAIL

- [ ] **Step 3: 구현** — 위 Interfaces대로. SQL은 바인딩 변수만 쓰고(`IN` 목록은 `?` 개수만큼) 값을 문자열에 끼워 넣지 않습니다. `EXPLAIN QUERY PLAN`으로 S1–S3·S5·S10이 `USE TEMP B-TREE FOR ORDER BY`를 쓰지 않는지 확인하고 보고서에 적습니다(키워드 구동 S4는 예외).

- [ ] **Step 4: 통과 확인** — Run: `uv run python -m pytest -q` → 전체 통과. Run: `uv run python -m pytest -m perf -q -s tests/perf/test_log_perf.py` → 통과(처음에는 1M 생성·색인으로 수 분, 이후 캐시). 300ms를 넘는 시나리오가 있으면 기준이나 시나리오를 바꾸지 말고 인덱스·질의 형태를 고칩니다. 그래도 넘으면 측정값과 `EXPLAIN QUERY PLAN`을 붙여 멈추고 보고합니다.

- [ ] **Step 5: Commit** — `git commit -m "feat: log query engine with fan-out keyset paging, rollup/scan histograms, user facets and a 1M-row perf harness"`

---

### Task 5: 로그·감사 API, 조회 감사 기록, 내보내기

**Files:**
- Create: `server/app/web/logs_api.py`, `server/tests/test_logs_api.py`
- Modify: `server/app/web/app_factory.py`(두 채널에 `logs_api.router`), `server/app/logstore/indexer.py`(`LogIndex.query_slots`)

**Interfaces:**
- Consumes: Task 4 전부, `require`, `AuditLogger.admin`, `to_kst_iso`.
- Produces (`app.web.logs_api`):
  - 공통 의존성 `log_filter(request, from_: str | None = Query(None, alias="from"), to: str | None = None, users: list[str] = Query([]), cat: list[str] = Query([]), event: list[str] = Query([]), outcome: list[str] = Query([]), session: int | None = Query(None, ge=0, le=2**31 - 1), ip: str | None = Query(None, min_length=1, max_length=64), q: str | None = Query(None, max_length=500)) -> LogFilter`. 시각은 `datetime.fromisoformat` + `tzinfo` 필수(없거나 파싱 실패 → 422). 기본값: `to` = 지금, `from` = `to − 1시간`. `InvalidQuery` → `ApiError(422, "validation")`.
  - `LogIndex.query_slots: asyncio.Semaphore(4)`: 모든 색인 질의는 이 슬롯 안에서 `asyncio.to_thread`로 부릅니다.
  - `log_item(row: LogRow) -> dict` = `{"id", "ts": to_kst_iso(datetime.fromtimestamp(ts_ms / 1000, UTC)), "cat", "event", "user", "session_id", "client_ip", "outcome", "data"}`.
  - `GET /api/logs?…&cursor=&limit=200`(1–1000, `require(Action.VIEW_LOGS)`) → `{"items": [log_item], "next_cursor": str | None, "index": {"ready": bool}}`.
  - `GET /api/logs/histogram?…&buckets=60`(10–200)`&group=none|cat|user` (`VIEW_LOGS`) → `{"from": to_kst_iso(start_ms), "to": to_kst_iso(to_ms), "bucket_sec", "starts": [to_kst_iso, ...], "series": [{"key", "counts"}], "total", "source"}`.
  - `GET /api/logs/users?…&limit=200`(1–500, `VIEW_LOGS`) → `[{"user", "count"}]`.
  - `GET /api/logs/status`(`VIEW_LOGS`) → `IndexStatus`의 필드(`last_indexed_at`은 KST 또는 null).
  - `GET /api/logs/export?…&format=csv|jsonl&limit=100000`(1–100,000, `require(Action.EXPORT_LOGS)`) → `StreamingResponse`(본문은 `iter_rows`를 1,000행씩 `asyncio.to_thread`로 꺼내 인코딩). 헤더: `Content-Disposition: attachment; filename="mcp-logs-<from>-<to>.<csv|jsonl>"`(KST `YYYYMMDD-HHMM`), `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`. CSV는 `text/csv; charset=utf-8`(본문 맨 앞 BOM `﻿`, `csv.writer(lineterminator="\r\n")`), JSONL은 `application/x-ndjson; charset=utf-8`(각 행의 원문 `raw` + `\n`).
    - CSV 열(고정): `ts,cat,event,user,session_id,client_ip,client_name,outcome,summary`. 빈 값은 빈 칸. `client_name` = `data.get("client_name")`, `summary` = `data`의 `text`, `cmdline`, `title`, `exe`, `name`, `email`, `action` 중 처음 나오는 문자열(2,000자에서 자름). 셀이 `=`, `+`, `-`, `@`, `\t`, `\r`로 시작하면 앞에 `'`를 붙입니다(W12).
  - `GET /api/audit?kind=admin|auth|all&from&to&users&result&channel&q&cursor&limit`(`require(Action.VIEW_AUDIT)`): `cats` = `admin`→(`admin.audit`,), `auth`→(`auth`,), `all`→둘 다(기본 `admin`); `result`(반복) → `outcomes`; `channel` ∈ `local`/`external` → `LogFilter.channel`. 응답 모양은 `/api/logs`와 같습니다. `GET /api/audit/export?…&format`(`require(Action.EXPORT_LOGS)`).
  - 조회 감사(W11): 커서 **없는** `/api/logs`·`/api/audit` 요청은 `audit.admin(actor, "logs_view" | "audit_view", channel, ip, {"filters": filters_json}, "ok")`를 남기되, `ViewAuditThrottle(clock, window_sec=60, max_keys=1000)`이 `(user.id, channel, sha256(키 정렬 filters JSON))`별 60초에 한 번만 허용합니다(키가 가득 차면 가장 오래된 키부터 버림). 내보내기는 매번 `logs_export`/`audit_export` `{"filters", "format", "limit"}`. `filters_json` = 비어 있지 않은 것만 `{"from", "to", "users", "cat", "event", "outcome", "session", "ip", "q", "kind", "channel"}`(시각은 KST 문자열). `limit`·`cursor`는 조건에 넣지 않습니다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_logs_api.py
import pytest

from tests.log_helpers import ev, index_all, write_lines
from tests.mcp_helpers import login_as, make_user
from tests.test_auth_api import audit_events

FROM, TO = "2026-11-04T13:00:00.000+09:00", "2026-11-04T14:00:00.000+09:00"
P = {"from": FROM, "to": TO}
AUTH_LINE = dict(event="login", email="a@x.com", channel="local", ip="127.0.0.1", ok=False)


async def seed(services):
    write_lines(services.paths.logs_dir, "2026-11-04", [
        ev(f"2026-11-04T13:{i:02d}:00.000+09:00", "activity.command", user="CORP\\hong", session_id=2,
           client_ip="10.0.3.21", client_name="HONG-LAPTOP", text=f"=cmd {i}") for i in range(5)])
    write_lines(services.paths.logs_dir, "2026-11-04", [
        ev("2026-11-04T13:30:00.000+09:00", "admin.audit", action="user_create", actor_email="a@x.com",
           channel="local", ip="127.0.0.1", target={"email": "b@x.com"}, result="ok"),
        ev("2026-11-04T13:31:00.000+09:00", "admin.audit", action="settings_update", actor_email="d@x.com",
           channel="external", ip="10.0.0.9", target={"path": "/api/settings"}, result="denied"),
        ev("2026-11-04T13:32:00.000+09:00", "auth", **AUTH_LINE)])
    await index_all(services)


def dev(client, services, channel="external"):
    return login_as(client, services, make_user(services, f"d-{channel}@x.com"), channel)


async def test_logs_require_login(external_client):
    r = await external_client.get("/api/logs", params=P)
    assert (r.status_code, r.json()) == (401, {"error": "login_required"})


async def test_list_items_shape_and_cursor(external_client, services):
    dev(external_client, services); await seed(services)
    q = {**P, "limit": 2, "users": ["corp\\hong"], "cat": ["activity.command"]}
    body = (await external_client.get("/api/logs", params=q)).json()
    item = body["items"][0]
    assert set(item) == {"id", "ts", "cat", "event", "user", "session_id", "client_ip", "outcome", "data"}
    assert (item["ts"], item["data"]["text"], item["session_id"]) == ("2026-11-04T13:04:00.000+09:00", "=cmd 4", 2)
    assert body["index"] == {"ready": True}
    r2 = (await external_client.get("/api/logs", params={**q, "cursor": body["next_cursor"]})).json()
    assert [i["data"]["text"] for i in r2["items"]] == ["=cmd 2", "=cmd 1"]


@pytest.mark.parametrize("params", [
    {"from": "2026-11-04T13:00:00", "to": TO}, {"from": TO, "to": FROM}, {**P, "cat": "nope"},
    {**P, "users": [f"u{i}" for i in range(51)]}, {**P, "cursor": "!!"}, {**P, "limit": 1001},
    {**P, "q": "x" * 501}, {**P, "outcome": "maybe"}, {"from": "yesterday", "to": TO}])
async def test_validation_422(external_client, services, params):
    dev(external_client, services)
    r = await external_client.get("/api/logs", params=params)
    assert (r.status_code, r.json()) == (422, {"error": "validation"})


async def test_defaults_to_the_last_hour(external_client, services):
    dev(external_client, services)
    assert (await external_client.get("/api/logs")).status_code == 200


async def test_histogram_users_and_status(external_client, services):
    dev(external_client, services); await seed(services)
    h = (await external_client.get("/api/logs/histogram", params={**P, "buckets": 6, "group": "cat"})).json()
    assert h["bucket_sec"] == 600 and h["starts"][0] == FROM and h["source"] == "rollup"
    assert {s["key"]: sum(s["counts"]) for s in h["series"]} == {"activity.command": 5, "auth": 1, "admin.audit": 2}
    users = (await external_client.get("/api/logs/users", params=P)).json()
    assert users[0] == {"user": "CORP\\hong", "count": 5}
    st = (await external_client.get("/api/logs/status")).json()
    assert st["ready"] is True and st["rows"] == 8 and st["newest_day"] == "2026-11-04"


async def test_export_csv_escapes_formulas_and_has_bom(external_client, services):
    dev(external_client, services); await seed(services)
    r = await external_client.get("/api/logs/export", params={**P, "format": "csv", "cat": ["activity.command"]})
    assert r.headers["content-type"] == "text/csv; charset=utf-8" and r.headers["cache-control"] == "no-store"
    assert r.headers["content-disposition"] == 'attachment; filename="mcp-logs-20261104-1300-20261104-1400.csv"'
    text = r.content.decode("utf-8")
    assert text.startswith("﻿ts,cat,event,user,session_id,client_ip,client_name,outcome,summary\r\n")
    assert "2026-11-04T13:04:00.000+09:00,activity.command,,CORP\\hong,2,10.0.3.21,HONG-LAPTOP,,'=cmd 4\r\n" in text


async def test_export_jsonl_is_the_raw_lines(external_client, services):
    dev(external_client, services); await seed(services)
    r = await external_client.get("/api/logs/export", params={**P, "format": "jsonl", "cat": ["auth"]})
    assert r.headers["content-type"] == "application/x-ndjson; charset=utf-8"
    assert r.text == ev("2026-11-04T13:32:00.000+09:00", "auth", **AUTH_LINE).decode() + "\n"


async def test_first_page_views_are_audited_with_throttle(external_client, services):
    dev(external_client, services); await seed(services)
    await external_client.get("/api/logs", params=P)                      # recorded
    await external_client.get("/api/logs", params=P)                      # same filters within 60 s: skipped
    services.clock.advance(61)
    await external_client.get("/api/logs", params=P)                      # recorded
    await external_client.get("/api/logs", params={**P, "q": "cmd"})      # other filters: recorded
    body = (await external_client.get("/api/logs", params={**P, "limit": 1})).json()   # limit is not a filter: skipped
    await external_client.get("/api/logs", params={**P, "limit": 1, "cursor": body["next_cursor"]})  # cursor: never
    await external_client.get("/api/logs/export", params={**P, "format": "jsonl"})
    events = await audit_events(services, "admin.audit")
    views = [e for e in events if e["action"] == "logs_view"]
    assert len(views) == 3 and views[2]["target"]["filters"]["q"] == "cmd"
    exports = [e for e in events if e["action"] == "logs_export"]
    assert len(exports) == 1 and exports[0]["target"]["format"] == "jsonl"


async def test_audit_endpoint_restricts_categories_and_filters(external_client, services):
    dev(external_client, services); await seed(services)
    admin = (await external_client.get("/api/audit", params=P)).json()["items"]
    assert {i["cat"] for i in admin} == {"admin.audit"} and len(admin) == 2
    denied = (await external_client.get("/api/audit", params={**P, "result": ["denied"]})).json()["items"]
    assert [i["event"] for i in denied] == ["settings_update"]
    local = (await external_client.get("/api/audit", params={**P, "kind": "all", "channel": "local"})).json()["items"]
    assert {i["cat"] for i in local} == {"admin.audit", "auth"} and len(local) == 2


async def test_logs_work_on_both_channels(local_client, external_client, services):
    await seed(services)
    for client, channel in ((local_client, "local"), (external_client, "external")):
        dev(client, services, channel)
        assert (await client.get("/api/logs", params=P)).status_code == 200
```

- [ ] **Step 2: 실패 확인** — Run: `uv run python -m pytest tests/test_logs_api.py -v` → FAIL

- [ ] **Step 3: 구현** — 위 Interfaces대로.

- [ ] **Step 4: 통과 확인** — Run: `uv run python -m pytest -q` → 전체 통과, ruff·mypy 0건

- [ ] **Step 5: Commit** — `git commit -m "feat: log and audit query APIs with histogram, user facets, CSV/JSONL export and throttled view auditing"`

---

### Task 6: 보존 정리 작업 `RetentionJob`

**Files:**
- Modify: `server/app/logstore/retention.py`(작업 추가), `server/app/logstore/indexer.py`(`delete_before`, `file_state`, `rename_file`), `server/app/services.py`(`retention`), `server/app/main.py`(시작·정지), `server/app/web/local_api.py`(설정 저장 뒤 실행 요청, 미리보기의 `delete_events`)
- Create: `server/tests/test_retention_job.py`, `server/tests/perf/test_retention_perf.py`
- Modify (tests): `server/tests/perf/conftest.py`(`perf_purge`), `server/tests/test_retention_preview.py`(응답 키에 `delete_events`)

**Interfaces:**
- Consumes: Plan 3 `retention_cutoff`·`preview`, Plan 4 `TamperScanner.expect_log_removed`·`Services.tamper_scanner`·`Services.tamper`, Task 3 `LogIndex`, Plan 1 `SESSION_ABSOLUTE_SEC`·`SESSION_IDLE_SEC`·`OTP_EMAIL_FAIL_WINDOW_SEC`·`OTP_VERIFY_IP_WINDOW_SEC`·`OTP_IP_WINDOW_SEC`.
- Produces:
  - `LogIndex.delete_before(day: str, chunk: int = 5000) -> int`(async): `run_exclusive`로 한 번에 `chunk`개씩 `SELECT id FROM events WHERE day < ? LIMIT ?` → `DELETE FROM events_fts WHERE rowid IN (...)` → `DELETE FROM events WHERE id IN (...)`(한 트랜잭션), 0개가 될 때까지 반복하며 묶음 사이에 `await asyncio.sleep(0)`. 끝으로 `counts_min`·`counts_hour`에서 그 날짜 KST 자정보다 이른 버킷, `files`에서 `day < ?` 행을 지웁니다. 지운 `events` 수를 돌려줍니다.
  - `LogIndex.file_state(name: str) -> FileState | None`(async), `LogIndex.rename_file(old: str, new: str, offset: int) -> None`(async; `new` 행을 `offset`, `size` = 새 파일 크기, `done = 1`로 upsert하고 `old` 행 삭제).
  - `app.logstore.retention`:
    - 상수 `RUN_AT_KST = time(3, 30)`, `MIN_COMPRESS_AGE_DAYS = 2`, `LOG_DB_TABLES = ("mcp_actions", "mcp_transitions", "notice_displays", "rdp_connections", "rdp_logon_failures")`.
    - `compress_cutoff(today: date, compress_after_days: int) -> date` = `retention_cutoff(today, max(compress_after_days, MIN_COMPRESS_AGE_DAYS))`(W15).
    - `@dataclass(frozen=True) RetentionResult(reason: str, cutoff: date, compress_cutoff: date, deleted_files: list[str], deleted_bytes: int, deleted_from: date | None, deleted_to: date | None, index_rows: int, compressed: list[str], skipped_compress: list[str], db_rows: dict[str, int], errors: list[str], duration_ms: int)`
    - `class RetentionJob(paths, db: Database, settings: SettingsStore, index: LogIndex, log: LogWriter, audit: AuditLogger, clock: Clock, tamper_scanner: TamperScanner | None, *, run_at: time = RUN_AT_KST, startup_delay_sec: float = 60, request_delay_sec: float = 5, delete_chunk: int = 5000)`(`request_delay_sec`는 공개 속성):
      - `async run_once(reason: Literal["schedule", "startup", "settings", "manual"]) -> RetentionResult`(내부 `asyncio.Lock`으로 겹치지 않음). 순서(각 단계를 `try`로 감싸 오류를 `errors`에 `"<단계>: <repr>"`로 모으고 계속):
        1. `s = settings.get()`, `today` = `clock.now()`의 KST 날짜, `cutoff = retention_cutoff(today, s.log_retention_days)`.
        2. **만료 파일**: `list_log_files`에서 `day < cutoff`인 모든 파일(평문·gz). 이름마다 `tamper_scanner.expect_log_removed(name)`를 **먼저** 부르고 `unlink`(`asyncio.to_thread`). 이름·크기·날짜 범위를 기록.
        3. **색인**: `index.delete_before(cutoff.isoformat(), delete_chunk)`.
        4. **압축**: `cc = compress_cutoff(today, s.log_compress_after_days)`. `day < cc`인 `.jsonl`마다(이름순): `index.file_state(name)`가 없거나 `offset != 파일 크기`면 `skipped_compress`에 넣고 건너뜀. 아니면 스레드에서 `<day>.jsonl.gz.tmp`에 씀(같은 날짜 `.jsonl.gz`가 이미 있으면 그 압축 해제 내용 + 평문 내용, 없으면 평문 내용; `gzip.GzipFile(fileobj=..., mode="wb", compresslevel=6, mtime=0)`) → `fsync` → `os.replace(tmp, gz)` → `index.rename_file(plain, gz, offset = 기존 gz 상태의 offset(없으면 0) + 평문 offset)` → `expect_log_removed(plain)` → 평문 `unlink`.
        5. **DB 표**(`config.db`, 루프 스레드, 표마다 짧은 트랜잭션, W16):
           - `auth_sessions`: 모든 행을 읽어 Python에서 `created_at`·`last_seen_at`을 파싱(UTC; 마이크로초가 있을 수도 없을 수도 있음)해 `SESSION_ABSOLUTE_SEC` 또는 `SESSION_IDLE_SEC`를 넘긴 `id_hash`를 지움.
           - `otp_codes`: `last_sent_at < to_kst_iso(now − 3600초) AND (code_hash IS NULL OR email NOT IN (SELECT email FROM users))`.
           - `otp_failures`: `at < to_kst_iso(now − OTP_EMAIL_FAIL_WINDOW_SEC)`; `otp_verify_ip`: `at < to_kst_iso(now − OTP_VERIFY_IP_WINDOW_SEC)`; `otp_ip_requests`: `at < to_kst_iso(now − OTP_IP_WINDOW_SEC)` (OTP 표는 모두 KST 밀리초 문자열이라 같은 형식의 문자열 비교).
           - `cut = datetime.combine(cutoff, time(0), KST).astimezone(UTC).isoformat()`(Plan 2 UTC `isoformat` 저장 형식과 같은 접두사 순서라 문자열 비교가 안전): `mcp_actions`·`mcp_transitions`: `at < cut`; `notice_displays`: `connection_id IN (SELECT id FROM rdp_connections WHERE ended_at IS NOT NULL AND ended_at < cut)` — **연결보다 먼저**; `rdp_connections`: `ended_at IS NOT NULL AND ended_at < cut`(진행 중 연결은 남김); `rdp_logon_failures`: `at < cut`.
           - `db_rows`는 위 10개 표 이름을 키로 한 지운 행 수(0 포함).
        6. 기록: `log.emit("system", event="retention.run", reason=..., cutoff=..., compress_cutoff=..., deleted_files=<개수>, deleted_bytes, deleted_from, deleted_to, index_rows, compressed=<개수>, skipped_compress=<개수>, db_rows, errors, duration_ms)`(날짜는 ISO 문자열 또는 null). 지운 파일·색인 행·`LOG_DB_TABLES` 행이 하나라도 있으면 `audit.admin(None, "retention_purge", "local", None, {"reason", "cutoff", "deleted_from", "deleted_to", "files", "bytes", "index_rows", "db_rows"}, "error" if errors else "ok")`. 끝으로 `index.run_exclusive`로 `meta`에 `retention_last_run = today.isoformat()`.
      - `next_run_at(now: datetime) -> datetime`: `now`보다 **엄격히 뒤**인 가장 가까운 KST `run_at`(UTC aware).
      - `request_run(reason="settings") -> None`(루프 스레드): 이미 예약돼 있지 않으면 `request_delay_sec` 뒤 `run_once(reason)`를 예약(태스크 참조 보관).
      - `async start()`: 배경 태스크 — 처음에 `meta.retention_last_run != today`이고 지금이 오늘 `run_at` 이후면 `startup_delay_sec` 뒤 `run_once("startup")`; 그 뒤 `next_run_at`까지 `asyncio.sleep`하고 `run_once("schedule")`를 반복. 예외는 `system` `retention.failed {error}` 후 계속. `async stop()`: 예약·배경 태스크 취소.
  - `Services.retention: RetentionJob`. `serve()`가 색인기 다음에 `start()`, 정지 때 맨 먼저 `stop()`. conftest는 시작하지 않습니다(테스트가 `run_once`를 직접 부름).
  - `PUT /api/settings`: 저장에 성공하고 `log_retention_days`가 줄었거나 `log_compress_after_days`가 바뀌었으면 `services.retention.request_run("settings")`(W14).
  - `GET /api/settings/retention/preview` 응답에 `"delete_events": int | None` — 색인에 파일 상태가 하나라도 있으면 `count_before_day(cutoff)`(질의 슬롯 안 `to_thread`), 아니면 None.
  - `perf_purge` 픽스처(`tests/perf/conftest.py`): 200,000행/10일(`end_day = 2026-11-04`)을 생성·색인한 템플릿을 `server/.cache/perf-purge-v{GEN_VERSION}/`에 캐시하고, 테스트마다 tmp 루트로 `logs/`와 `index.db`를 복사해 `LogIndex`를 열고, 보존 5일로 설정한 `SettingsStore`(tmp `config.db`)와 `RetentionJob(tamper_scanner=None)`을 만듭니다. `PurgeEnv(job, reader, recent_filter)`(`recent_filter` = 최근 24시간, 조건 없음).

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_retention_job.py
import gzip
import sqlite3
from datetime import UTC, date, datetime, timedelta

import pytest

from app.clock import to_kst_iso
from app.logstore.retention import preview
from tests.log_helpers import ev, index_all, write_lines
from tests.mcp_helpers import make_user, seed_mcp
from tests.test_auth_api import audit_events, bootstrap, login
from tests.winfakes import eventually

DAYS = ["2026-10-25", "2026-10-28", "2026-10-29", "2026-11-03", "2026-11-04"]


async def seed_days(services):
    for d in DAYS:
        write_lines(services.paths.logs_dir, d, [ev(f"{d}T10:00:0{i}.000+09:00", "system", event="x", i=i) for i in range(2)])
    await index_all(services)


def fts_and_events(services):
    with sqlite3.connect(services.paths.index_db_path) as c:
        return c.execute("SELECT COUNT(*) FROM events_fts").fetchone()[0], c.execute("SELECT COUNT(*) FROM events").fetchone()[0]


async def test_purge_matches_the_preview(services):
    await seed_days(services)
    services.settings.update({"log_retention_days": 7, "log_compress_after_days": 7})
    p = preview(services.paths.logs_dir, date(2026, 11, 4), 7)
    res = await services.retention.run_once("manual")
    assert sorted(res.deleted_files) == ["2026-10-25.jsonl", "2026-10-28.jsonl"] and res.deleted_bytes == p.delete_bytes
    assert (res.deleted_from, res.deleted_to, res.cutoff) == (p.delete_from, p.delete_to, p.cutoff) and res.index_rows == 4
    days = services.log_index.reader().days()
    assert "2026-10-28" not in days and days["2026-10-29"] == 2 and res.errors == []
    fts, events = fts_and_events(services); assert fts == events


async def test_compresses_old_indexed_files_and_keeps_them_searchable(services):
    await seed_days(services)
    services.settings.update({"log_retention_days": 180, "log_compress_after_days": 3})
    res = await services.retention.run_once("manual")
    assert sorted(res.compressed) == ["2026-10-25.jsonl", "2026-10-28.jsonl", "2026-10-29.jsonl"]
    logs = services.paths.logs_dir
    assert (logs / "2026-10-29.jsonl.gz").exists() and not (logs / "2026-10-29.jsonl").exists()
    assert (logs / "2026-11-03.jsonl").exists()
    await services.log_index.index_once()
    assert services.log_index.reader().days()["2026-10-29"] == 2
    assert gzip.decompress((logs / "2026-10-29.jsonl.gz").read_bytes()).count(b"\n") == 2


async def test_compress_skips_files_not_fully_indexed(services):
    write_lines(services.paths.logs_dir, "2026-10-20", [ev("2026-10-20T10:00:00.000+09:00", "system")])
    services.settings.update({"log_compress_after_days": 3})
    res = await services.retention.run_once("manual")
    assert res.skipped_compress == ["2026-10-20.jsonl"] and (services.paths.logs_dir / "2026-10-20.jsonl").exists()


async def test_late_plain_file_is_merged_into_the_existing_gz(services):
    await seed_days(services); services.settings.update({"log_compress_after_days": 3})
    await services.retention.run_once("manual")
    write_lines(services.paths.logs_dir, "2026-10-29", [ev("2026-10-29T23:59:59.000+09:00", "system", event="late")])
    await index_all(services)
    res = await services.retention.run_once("manual")
    logs = services.paths.logs_dir
    assert res.compressed == ["2026-10-29.jsonl"] and not (logs / "2026-10-29.jsonl").exists()
    assert gzip.decompress((logs / "2026-10-29.jsonl.gz").read_bytes()).count(b"\n") == 3
    await services.log_index.index_once()
    assert services.log_index.reader().days()["2026-10-29"] == 3


async def test_removals_are_announced_to_the_tamper_scanner(services):
    await seed_days(services); services.tamper_scanner.scan()
    services.settings.update({"log_retention_days": 7, "log_compress_after_days": 3})
    await services.retention.run_once("manual"); services.tamper_scanner.scan()
    assert [r for r in services.tamper.recent(50) if r["event"] in ("log_file_removed", "log_file_truncated")] == []


async def test_purges_expired_rows_in_every_table(services):
    db, now = services.db, services.clock.now()  # 2026-11-04T05:00Z
    old_utc, new_utc = (now - timedelta(days=200)).isoformat(), (now - timedelta(days=1)).isoformat()
    live_utc = (now - timedelta(minutes=1)).isoformat()
    old_kst, new_kst = to_kst_iso(now - timedelta(hours=2)), to_kst_iso(now - timedelta(seconds=30))
    u = make_user(services, "u@x.com")
    sess = ("INSERT INTO auth_sessions (id_hash, user_id, channel, csrf_token, created_at, last_seen_at)"
            " VALUES (?, ?, 'local', 'c', ?, ?)")
    db.execute(sess, ("old", u.id, old_utc, old_utc)); db.execute(sess, ("live", u.id, live_utc, live_utc))
    otp = "INSERT INTO otp_codes (email, code_hash, expires_at, attempts, last_sent_at) VALUES (?, ?, NULL, 0, ?)"
    db.execute(otp, ("ghost@x.com", None, old_kst)); db.execute(otp, ("u@x.com", "h", old_kst))
    for table, col in (("otp_failures", "email"), ("otp_verify_ip", "ip"), ("otp_ip_requests", "ip")):
        db.execute(f"INSERT INTO {table} ({col}, at) VALUES ('k', ?), ('k', ?)", (old_kst, new_kst))
    m = seed_mcp(services, u)
    for at in (old_utc, new_utc):
        db.execute("INSERT INTO mcp_transitions (mcp_id, at, from_state, to_state) VALUES (?, ?, 'HEALTHY', 'SUSPECT')", (m.id, at))
        db.execute("INSERT INTO mcp_actions (run_id, mcp_id, at, requested, kind, trigger, reason, status, duration_ms)"
                   " VALUES ('r', ?, ?, 'start', 'start', 'manual', 'manual', 'ok', 1)", (m.id, at))
    conn = ("INSERT INTO rdp_connections (session_id, kind, user, protocol, connected_at, ended_at, end_reason)"
            " VALUES (2, 'logon', 'hong', 'rdp', ?, ?, ?)")
    old_conn = db.execute(conn, (old_utc, old_utc, "logoff"))
    db.execute(conn, (old_utc, None, None)); db.execute(conn, (new_utc, new_utc, "logoff"))
    db.execute("INSERT INTO notice_displays (connection_id, session_id, user, kind, version, created_at)"
               " VALUES (?, 2, 'hong', 'logon', 0, ?)", (old_conn, old_utc))
    for at in (old_utc, new_utc):
        db.execute("INSERT INTO rdp_logon_failures (at, source) VALUES (?, 'eventlog:4625')", (at,))
    res = await services.retention.run_once("manual")
    assert res.db_rows == {"auth_sessions": 1, "otp_codes": 1, "otp_failures": 1, "otp_verify_ip": 1, "otp_ip_requests": 1,
                           "mcp_actions": 1, "mcp_transitions": 1, "notice_displays": 1, "rdp_connections": 1,
                           "rdp_logon_failures": 1}
    assert [r["id_hash"] for r in db.query("SELECT id_hash FROM auth_sessions")] == ["live"]
    assert db.query("SELECT COUNT(*) AS n FROM rdp_connections WHERE ended_at IS NULL")[0]["n"] == 1
    assert [r["email"] for r in db.query("SELECT email FROM otp_codes")] == ["u@x.com"]


async def test_run_is_logged_and_audited(services):
    await seed_days(services); services.settings.update({"log_retention_days": 7, "log_compress_after_days": 7})
    await services.retention.run_once("manual")
    purge = [e for e in await audit_events(services, "admin.audit") if e["action"] == "retention_purge"]
    assert len(purge) == 1 and purge[0]["result"] == "ok" and purge[0]["actor_id"] is None
    assert (purge[0]["target"]["deleted_from"], purge[0]["target"]["files"]) == ("2026-10-25", 2)
    runs = [e for e in await audit_events(services, "system") if e.get("event") == "retention.run"]
    assert runs[-1]["index_rows"] == 4 and runs[-1]["reason"] == "manual"


async def test_lowering_retention_via_api_runs_the_job(local_client, services):
    services.retention.request_delay_sec = 0.01
    await seed_days(services); await bootstrap(local_client); await login(local_client, services)
    r = await local_client.put("/api/settings", json={"log_retention_days": 7, "log_compress_after_days": 7},
                               headers={"X-CSRF-Token": local_client.csrf})
    assert r.status_code == 200
    await eventually(lambda: not (services.paths.logs_dir / "2026-10-25.jsonl").exists())


async def test_preview_reports_index_rows(local_client, services):
    await seed_days(services); await bootstrap(local_client); await login(local_client, services)
    body = (await local_client.get("/api/settings/retention/preview", params={"days": 7})).json()
    assert body["delete_events"] == 4 and body["delete_files"] == 2


@pytest.mark.parametrize("now,want", [
    (datetime(2026, 11, 4, 5, 0, tzinfo=UTC), datetime(2026, 11, 4, 18, 30, tzinfo=UTC)),
    (datetime(2026, 11, 3, 18, 0, tzinfo=UTC), datetime(2026, 11, 3, 18, 30, tzinfo=UTC)),
    (datetime(2026, 11, 3, 18, 30, tzinfo=UTC), datetime(2026, 11, 4, 18, 30, tzinfo=UTC))])
def test_next_run_is_0330_kst(services, now, want):
    assert services.retention.next_run_at(now) == want
```

`db.execute`는 INSERT의 `lastrowid`를 돌려주므로 `old_conn`은 연결 id입니다. `u@x.com`은 `users`에 있으므로 그 코드는 남고 `ghost@x.com`만 지워집니다. `test_purge_matches_the_preview`에서 압축 기준일은 10-29라 남는 10-29·11-03·11-04는 압축 대상이 아닙니다.

```python
# server/tests/perf/test_retention_perf.py
import asyncio
import statistics
import time

import pytest

from tests.perf.conftest import record

pytestmark = pytest.mark.perf


async def test_purge_keeps_queries_fast(perf_purge):
    job, reader, recent = perf_purge.job, perf_purge.reader, perf_purge.recent_filter
    latencies: list[float] = []
    done = asyncio.Event()

    async def query_loop():
        while not done.is_set():
            t = time.perf_counter(); await asyncio.to_thread(reader.page, recent, None, 200)
            latencies.append(time.perf_counter() - t); await asyncio.sleep(0.05)

    q = asyncio.create_task(query_loop())
    res = await job.run_once("manual")
    done.set(); await q
    p95 = statistics.quantiles(latencies, n=20)[18]
    record("purge_query_p95", p95); record("purge_rows", res.index_rows)
    assert res.index_rows >= 90_000 and p95 < 0.300
```

- [ ] **Step 2: 실패 확인** — Run: `uv run python -m pytest tests/test_retention_job.py tests/test_retention_preview.py -v` → FAIL

- [ ] **Step 3: 구현** — 위 Interfaces대로. 큰 파일의 압축·삭제는 모두 `asyncio.to_thread`에서 합니다.

- [ ] **Step 4: 통과 확인** — Run: `uv run python -m pytest -q` → 전체 통과. Run: `uv run python -m pytest -m perf -q tests/perf/test_retention_perf.py` → 통과

- [ ] **Step 5: Commit** — `git commit -m "feat: daily retention job: delete expired logs and index rows with the preview cutoff, compress old files, purge expired DB rows"`

---

### Task 7: 실행기·모니터 종료·미들웨어 하드닝 (carry-forward 묶음)

**Files:**
- Modify: `server/app/monitor/runner.py`, `server/app/monitor/supervisor.py`, `server/app/web/app_factory.py`(`BodySizeLimit`), `server/tests/fakes.py`(`FakeRunner.kill_all`·`aclose`)
- Modify (tests): `server/tests/test_script_runner.py`, `server/tests/test_monitor.py`, `server/tests/test_input_limits.py`, `server/tests/test_e2e_serve.py`, `server/tests/test_script_store.py`, `server/tests/test_integration_monitor.py`
- Modify: `dummy-mcps/tests/test_tools.py`

**Interfaces:**
- Produces:
  - `app.monitor.runner`: `KILL_FAILED_HOLD_SEC = 30.0`. 타임아웃 분기에서 `kill_tree` + `PIPE_DRAIN_SEC` 대기 뒤에도 `proc.returncode is None`이면 결과의 `error = "kill_failed"`(상태는 `timeout`)이고, 반환하기 전에 `asyncio.wait_for(proc.wait(), KILL_FAILED_HOLD_SEC)`까지 기다립니다(시간 초과는 무시하고 기존처럼 `_detach`). 이 대기는 MCP 잠금 안에서 하므로 같은 MCP의 다음 실행은 옛 프로세스가 끝나거나 30초가 지나야 시작합니다(W20).
  - `ScriptRunner._procs: set[asyncio.subprocess.Process]`(생성 직후 추가, 종료·분리 정리 때 제거), `async kill_all() -> int`: 아직 살아 있는 스크립트 프로세스마다 `asyncio.to_thread(kill_tree, pid)`를 병렬로 부르고 끝난 프로세스 수 합계를 돌려줍니다. `async aclose(timeout: float = 2.0) -> None`: `_detached` 태스크를 `timeout`까지 기다리고 남은 것은 취소 후 `gather(..., return_exceptions=True)`("Task was destroyed" 경고 제거).
  - `ScriptRunnerLike` 프로토콜에 `kill_all`·`aclose`. `FakeRunner.kill_all()` → `self.killed_all += 1; return 0`, `aclose()` → no-op.
  - `Monitor.stop(grace_sec: float = DEFAULT_GRACE_SEC, *, kill_abandoned: bool = False)`: 유예 뒤 남은 스크립트가 있고 `kill_abandoned`이면 `killed = await self._runner.kill_all()`을 먼저 부르고, 짧게(`PIPE_DRAIN_SEC + 1`초) 태스크가 끝나기를 기다린 뒤 남은 것만 취소합니다. `system` `monitor.stop {abandoned, killed}`. 마지막에 `await self._runner.aclose()`(W21).
  - `Monitor._run_step`: `result.error == "kill_failed"`이면 `system` `monitor.kill_failed {mcp_id, run_id, kind}`.
  - `app.monitor.supervisor.safe_actor(user: User | None) -> str`: None → `"system"`, 이메일이 `re.fullmatch(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+", email, re.ASCII)`이면 그 이메일, 아니면 `f"user-{user.id}"`. `MCP_ACTOR`가 이 값을 씁니다(W37). `mcp.action` 로그의 `actor`는 원래 이메일 그대로.
  - `BodySizeLimit`: 413을 보낸 뒤 앱이 던진 예외를 삼킬 때 `print(f"body limit: suppressed {exc!r} after 413", file=sys.stderr)`(예외 처리 안에서도 절대 다시 던지지 않음).
  - `tests/test_e2e_serve.py::_running_server`: `assert lp != ep`(같으면 `free_port()`를 다시), `subprocess.Popen(..., stdin=subprocess.DEVNULL)`; `test_dummy_otp_outbox_written`의 두 POST에 상태 단언(`201`, `202`).
  - 스크립트 저장의 replace-before-COMMIT은 코드를 바꾸지 않고 실행 시 해시 검사를 안전망으로 둡니다(W19). 아래 테스트가 그 안전망을 고정합니다.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_script_runner.py (추가)
import asyncio
import hashlib
import time

import app.monitor.runner as runner_mod


def _sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


async def test_kill_failure_is_reported_and_holds_the_mcp_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(runner_mod, "kill_tree", lambda pid: 0)  # the kill "fails": nothing dies
    monkeypatch.setattr(runner_mod, "KILL_FAILED_HOLD_SEC", 15.0)
    slow = tmp_path / "slow.bat"; slow.write_bytes(b"@ping -n 5 127.0.0.1 > nul\r\n")  # about 4 s
    fast = tmp_path / "fast.bat"; fast.write_bytes(b"@exit /b 0\r\n")
    r = runner_mod.ScriptRunner(); t0 = time.perf_counter()
    first = asyncio.create_task(r.run(slow, expected_sha256=_sha(slow), timeout_sec=1, env={}, lock_key=1))
    await asyncio.sleep(0.2)
    second = await r.run(fast, expected_sha256=_sha(fast), timeout_sec=10, env={}, lock_key=1)
    res = await first
    assert (res.status, res.error) == ("timeout", "kill_failed")
    assert second.status == "ok" and time.perf_counter() - t0 >= 3.5


async def test_kill_all_kills_running_script_trees(tmp_path):
    pidfile = tmp_path / "child.pid"
    script = tmp_path / "hang.ps1"
    script.write_text(f"$c = Start-Process ping -ArgumentList '-n','60','127.0.0.1' -PassThru -WindowStyle Hidden\n"
                      f"Set-Content -Path '{pidfile}' -Value $c.Id\nStart-Sleep 60\n", "utf-8")
    r = runner_mod.ScriptRunner()
    task = asyncio.create_task(r.run(script, expected_sha256=_sha(script), timeout_sec=120, env={}, lock_key=1))
    for _ in range(100):
        if pidfile.exists() and pidfile.read_text().strip(): break
        await asyncio.sleep(0.1)
    child = int(pidfile.read_text().strip())
    assert await r.kill_all() >= 2
    res = await asyncio.wait_for(task, 10)
    assert res.status == "failed" and not psutil.pid_exists(child)
    await r.aclose()
```

`test_kill_all_kills_running_script_trees`는 `import psutil`을 파일 위에 더합니다(실제 PowerShell 실행, 기존 실행기 테스트와 같은 조건).

```python
# server/tests/test_monitor.py (추가; 파일의 crash_to_action, logs 헬퍼 사용)
async def test_kill_failed_is_logged(services):
    m = seed_mcp(services, make_user(services, "o@x.com"))
    services.monitor._runner.results.append(ok_result(status="timeout", exit_code=None, error="kill_failed"))
    await crash_to_action(services, m)
    e = [x for x in await logs(services, "system") if x.get("event") == "monitor.kill_failed"]
    assert e and (e[0]["mcp_id"], e[0]["kind"]) == (m.id, "start")


async def test_stop_kills_abandoned_scripts_when_asked(services):
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner)
    services.monitor._runner.gate = asyncio.Event()
    services.monitor.manual_action(m.id, "start", owner); await asyncio.sleep(0)
    await services.monitor.stop(grace_sec=0.05, kill_abandoned=True)
    stop = [x for x in await logs(services, "system") if x.get("event") == "monitor.stop"][-1]
    assert services.monitor._runner.killed_all == 1 and stop["abandoned"] == 1 and "killed" in stop


async def test_mcp_actor_is_restricted_to_safe_emails(services):
    weird = make_user(services, "a&calc@x.com"); m = seed_mcp(services, weird)
    services.monitor.manual_action(m.id, "start", weird); await services.monitor.wait_idle()
    assert services.monitor._runner.calls[-1].env["MCP_ACTOR"] == f"user-{weird.id}"
    plain = make_user(services, "dev.ops+1@x.com")
    services.monitor.manual_action(m.id, "stop", plain); await services.monitor.wait_idle()
    assert services.monitor._runner.calls[-1].env["MCP_ACTOR"] == "dev.ops+1@x.com"
```

`make_user`가 `a&calc@x.com`을 받는지는 Plan 1 `_EMAIL_RE`(`^[^@\s]+@[^@\s]+\.[^@\s]+$`)로 확인됩니다.

```python
# server/tests/test_integration_monitor.py (추가; 파일 전체가 integration 마커)
import json

from app.monitor.scripts import ScriptUpload
from tests.fakes import FakeProber
from tests.mcp_helpers import make_user, seed_mcp


async def test_service_stop_kills_abandoned_script_tree(tmp_path):
    from app.clock import SystemClock
    clock = SystemClock()
    svc = build_services(tmp_path, clock=clock, otp_provider=CapturingOtpProvider(), prober=FakeProber(clock))
    await svc.log.start()
    pidfile = tmp_path / "child.pid"
    hang = (f"$c = Start-Process ping -ArgumentList '-n','60','127.0.0.1' -PassThru -WindowStyle Hidden\n"
            f"Set-Content -Path '{pidfile}' -Value $c.Id\nStart-Sleep 60\n")
    owner = make_user(svc, "o@x.com")
    m = seed_mcp(svc, owner, scripts={"start": ScriptUpload(".ps1", hang), "stop": ScriptUpload(".ps1", "exit 0\n")})
    svc.monitor.manual_action(m.id, "start", owner)
    for _ in range(150):
        if pidfile.exists() and pidfile.read_text("utf-8-sig").strip(): break
        await asyncio.sleep(0.1)
    child = int(pidfile.read_text("utf-8-sig").strip())
    await svc.monitor.stop(grace_sec=0.5, kill_abandoned=True)
    await svc.log.stop(); svc.db.close()
    stop = [json.loads(x) for x in next((tmp_path / "logs").glob("*.jsonl")).read_text("utf-8").split("\n")
            if x and '"monitor.stop"' in x][-1]
    assert not psutil.pid_exists(child) and stop["killed"] >= 2 and stop["abandoned"] == 1
```

`ScriptUpload(ext, text)`은 Plan 2의 업로드 형식(`tests/mcp_helpers.BAT`와 같음)입니다. `services`를 직접 만드는 것은 기존 파일의 실제 러너 시나리오와 같은 방식이며 모니터 루프는 시작하지 않습니다(수동 조치만).

```python
# server/tests/test_input_limits.py (추가)
import httpx

from app.web.app_factory import MAX_BODY_BYTES, BodySizeLimit, create_app


async def test_oversize_with_a_bad_host_is_bad_host(services):
    app = create_app("local", services)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://evil.example") as c:
        r = await c.post("/api/bootstrap", content=b"x" * (MAX_BODY_BYTES + 1))
    assert (r.status_code, r.json()) == (400, {"error": "bad_host"})


async def _drive(app, body_chunks):
    sent = []
    chunks = [{"type": "http.request", "body": b, "more_body": i < len(body_chunks) - 1} for i, b in enumerate(body_chunks)]

    async def receive():
        return chunks.pop(0) if chunks else {"type": "http.disconnect"}

    async def send(m):
        sent.append(m)

    await app({"type": "http", "method": "POST", "path": "/x", "headers": []}, receive, send)
    return sent


async def test_streamed_oversize_sends_exactly_one_413(capsys):
    async def inner(scope, receive, send):
        while (await receive()).get("more_body"): pass
        raise RuntimeError("body cut off")

    sent = await _drive(BodySizeLimit(inner), [b"x" * MAX_BODY_BYTES, b"y"])
    starts = [m for m in sent if m["type"] == "http.response.start"]
    assert [m["status"] for m in starts] == [413]
    assert "body limit: suppressed RuntimeError('body cut off') after 413" in capsys.readouterr().err


async def test_websocket_scope_passes_through():
    seen = []

    async def inner(scope, receive, send):
        seen.append(scope["type"])

    await BodySizeLimit(inner)({"type": "websocket", "path": "/ws", "headers": []}, None, None)
    assert seen == ["websocket"]
```

```python
# server/tests/test_script_store.py (추가)
import contextlib
import sqlite3

from app.monitor.runner import ScriptRunner


async def test_commit_failure_after_replace_is_caught_by_the_runtime_hash_check(services, monkeypatch):
    owner = make_user(services, "o@x.com"); m = seed_mcp(services, owner)
    before = services.scripts.get(m.id, "start")
    real = services.db.transaction

    @contextlib.contextmanager
    def failing_commit():
        with real() as conn:
            yield conn
            raise sqlite3.OperationalError("disk I/O error during COMMIT")

    monkeypatch.setattr(services.db, "transaction", failing_commit)
    with pytest.raises(sqlite3.OperationalError):
        services.scripts.put(m.id, "start", upload(".bat", "@exit /b 7\r\n"), owner.id)
    monkeypatch.undo()
    info = services.scripts.get(m.id, "start")
    assert info.sha256 == before.sha256                    # DB rolled back
    assert b"exit /b 7" in info.path.read_bytes()          # file already replaced
    res = await ScriptRunner().run(info.path, expected_sha256=info.sha256, timeout_sec=10, env={}, lock_key=m.id)
    assert (res.status, res.error) == ("error", "hash_mismatch")   # never executed
```

`upload(ext, text)`은 이 파일에 이미 있는 업로드 생성 헬퍼를 씁니다(없으면 `ScriptUpload`를 만드는 같은 이름의 작은 함수를 이 파일에 더합니다).

```python
# dummy-mcps/tests/test_tools.py (추가)
import seoul_weather.__main__ as weather_main
from common.server import build_parser


def test_open_meteo_flag_wires_the_live_fetcher(monkeypatch):
    calls = []
    live = {"current": {"temperature_2m": 1.5, "relative_humidity_2m": 50, "weather_code": 0}}
    monkeypatch.setattr(weather_main.tools, "fetch_open_meteo", lambda: calls.append(1) or live)
    parser = build_parser("seoul-weather", 9101); weather_main._extra_args(parser)
    on = weather_main._build_tools(parser.parse_args(["--open-meteo"]))[0]
    off = weather_main._build_tools(parser.parse_args([]))[0]
    assert on("중구")["source"] == "open-meteo" and calls == [1]
    assert off("중구")["source"] == "dummy" and calls == [1]
```

- [ ] **Step 2: 실패 확인** — Run(server): `uv run python -m pytest tests/test_script_runner.py tests/test_monitor.py tests/test_input_limits.py tests/test_script_store.py tests/test_e2e_serve.py -v` → FAIL. Run(dummy-mcps): `uv run python -m pytest tests/test_tools.py -v` → `test_open_meteo_flag_wires_the_live_fetcher`는 이미 통과할 수 있음(배선 고정 테스트) — 통과하면 그대로 둡니다.

- [ ] **Step 3: 구현** — 위 Interfaces대로.

- [ ] **Step 4: 통과 확인** — Run(server): `uv run python -m pytest -q` → 통과, `uv run python -m pytest -m integration -q` → 통과. Run(dummy-mcps): `uv run python -m pytest -q` → 통과

- [ ] **Step 5: Commit** — `git commit -m "fix: hold the MCP lock after a failed timeout kill, kill abandoned script trees on stop, log suppressed body-limit errors, safe MCP_ACTOR"`

---

### Task 8: 서비스 호스트 — ServeControl, 포트 선점, 종료 코드, RootLock, Windows 서비스, 시작 유형

**Files:**
- Create: `server/app/rootlock.py`, `server/app/winsvc/__init__.py`, `server/app/winsvc/host.py`, `server/app/winsvc/service.py`, `server/app/winsvc/start_type.py`, `server/app/web/service_api.py`
- Create: `server/tests/test_service_host.py`, `server/tests/test_start_type.py`
- Modify: `server/app/main.py`, `server/app/__main__.py`, `server/app/services.py`(`start_type`, `build_services` 실패 시 DB 닫기, `service_configurator` 인자), `server/app/collect/manager.py`(`Collectors.nudge_sessions`), `server/app/sessions/collector.py`의 `SessionsComponent`(`nudge`), `server/app/web/app_factory.py`(Local에 `service_api.router`), `server/app/web/local_api.py`(설정 저장 시 시작 유형 적용), `server/app/__init__.py`(`__version__ = "1.0.0"`), `server/pyproject.toml`(`version = "1.0.0"`), `server/tests/fakes.py`(`FakeScm`), `server/tests/conftest.py`, `server/tests/test_channels.py`(`_local_only_routes`에 `service_api.router`)

**Interfaces:**
- Produces:
  - `app.main`:
    - `class PortInUseError(OSError)`(속성 `host`, `port`), `bind_socket(host: str, port: int) -> socket.socket`: Windows면 `SO_EXCLUSIVEADDRUSE`(포트 가로채기 방지, W23)를 켠 뒤 `bind`; `OSError`(사용 중·권한) → `PortInUseError`.
    - `class ServeControl(*, as_service: bool = False)`: 스레드 안전. `request_stop()`(어느 스레드에서든, 여러 번 불러도 됨; 서버가 뜨기 전이면 뜬 직후 정지), `nudge_sessions()`(어느 스레드에서든; 수집이 꺼져 있거나 아직 시작 전이면 no-op), `wait_started(timeout: float | None = None) -> bool`(두 서버가 모두 `started`가 되면 설정되는 `threading.Event`), `wait_stopped(timeout=None) -> bool`, `as_service: bool`.
    - `serve(root, local_port=8700, external_port=8701, *, external_host="0.0.0.0", static_dir=None, dev_otp_code=None, collectors=None, control: ServeControl | None = None, kill_scripts_on_stop: bool = True)`: ① `root = Path(root).resolve()` ② 두 소켓을 `bind_socket`으로 **먼저** 잡음(실패 → `PortInUseError`, 루트를 건드리기 전) ③ `RootLock(root).acquire()`(→ `RootInUseError`) ④ `build_services(...)` ⑤ 로그 → 색인기 → 모니터 → 수집기 → 보존 작업 시작, `control.as_service`면 `services.start_type.running_as_service = True` 후 `await asyncio.to_thread(services.start_type.reconcile)` ⑥ `_Server.serve(sockets=[sock])` 두 개 ⑦ 정지는 역순이며 `monitor.stop(kill_abandoned=kill_scripts_on_stop)`, 마지막에 소켓 닫기·잠금 해제. `control`이 있으면 `control._attach(loop, servers, services.collectors.nudge_sessions)`.
  - `app.services.build_services(..., service_configurator: ServiceConfigurator | None = None)`: 기본값은 Windows면 `ScmConfigurator()`, 아니면 `NullConfigurator()`. `db.migrate()` 이후 어느 단계에서든 예외가 나면 `db.close()` 후 다시 던집니다.
  - `Collectors.nudge_sessions() -> None`: `nudge` 메서드를 가진 컴포넌트마다 호출(Plan 4 `SessionsComponent.nudge()` = 시작된 `SessionCollector.nudge()`; 이벤트만 설정하므로 스레드 안전).
  - `app.rootlock`: `class RootInUseError(RuntimeError)`, `class RootLock(root: Path)`: `acquire()` = `data/.lock`을 열고 `msvcrt.locking(fd, LK_NBLCK, 1)`(실패 → `RootInUseError`), `release()`, 컨텍스트 매니저(W24). Task 3의 `reindex`는 잠금 없이 만들었으므로 이 Task에서 `RootLock`을 더합니다(잡지 못하면 종료 코드 4).
  - `app.db.DatabaseTooNewError`(Task 1)가 `build_services`에서 나오면 종료 코드 5.
  - `app.__main__`:
    - `run_server(ns: argparse.Namespace, control: ServeControl | None = None) -> int`: `serve(...)`를 `asyncio.run`으로 돌리고 오류를 종료 코드로 바꿉니다 — `PortInUseError` → stderr `ERROR: port <port> is already in use (<host>)` + 3, `RootInUseError` → `ERROR: data root <root> is already in use by another MCP Monitor process` + 4, `DatabaseTooNewError` → `ERROR: <root>\data\config.db was written by a newer version (schema <found> > <supported>); install that version or restore a backup` + 5. 이 셋은 트레이스백을 찍지 않습니다. 정상 종료 0.
    - `main(argv=None) -> int`: 첫 인자 `service` → `app.winsvc.service.dispatch(argv[1:])`; `reindex` → Task 3; 그 밖 → `parse_args` → `run_server`. `parse_args`에 `--version`(`action="version"`, `version=f"mcp-monitor {__version__}"`).
  - `app.winsvc.host`: `SERVICE_NAME = "mcp-monitor"`, `DISPLAY_NAME = "MCP Monitor"`, `DESCRIPTION = "MCP 상태 감시와 RDP 접속·행동 감사 (127.0.0.1:8700 / 0.0.0.0:8701)"`, `STOP_WAIT_HINT_MS = 30_000`. `class ServiceHost(argv: list[str], *, chdir: Callable[[Path], None] = os.chdir)`: `control = ServeControl(as_service=True)`; `run() -> int` = `ns = parse_args(argv)` → `chdir(ns.root.resolve())`(서비스의 작업 폴더는 System32, W22) → `run_server(ns, control)`; `stop()` → `control.request_stop()`; `session_change(event_type: int, session_id: int)` → `control.nudge_sessions()`.
  - `app.winsvc.service`(pywin32, Windows에서만 import): `class McpMonitorService(win32serviceutil.ServiceFramework)`: `_svc_name_`/`_svc_display_name_`/`_svc_description_` = 위 상수, 클래스 속성 `host_argv: list[str] = []`. `__init__`에서 `self.host = ServiceHost(self.host_argv)`. `GetAcceptedControls()` = 부모 값 `| SERVICE_ACCEPT_SHUTDOWN | SERVICE_ACCEPT_SESSIONCHANGE`. `SvcStop`/`SvcShutdown` = `ReportServiceStatus(SERVICE_STOP_PENDING, waitHint=STOP_WAIT_HINT_MS)` 후 `host.stop()`. `SvcOtherEx(control, event_type, data)`: `SERVICE_CONTROL_SESSIONCHANGE`면 `host.session_change(event_type, data[0])`. `SvcDoRun`: `ReportServiceStatus(SERVICE_RUNNING)` → `code = host.run()` → SCM이 정지를 요청하지 않았는데 끝났거나 `code != 0`이면 `servicemanager.LogErrorMsg(f"mcp-monitor exited with code {code}")` 후 `os._exit(code or 1)`(SCM 복구 동작이 다시 띄우게, W22). `dispatch(argv)`: `McpMonitorService.host_argv = argv` → `servicemanager.Initialize()` → `PrepareToHostSingle(McpMonitorService)` → `StartServiceCtrlDispatcher()`; 콘솔에서 실행해 `pywintypes.error`의 winerror 1063이 나면 stderr `ERROR: service mode must be started by the Service Control Manager; run "python -m app" for a console server` + 종료 코드 2. 정적 분석을 위해 PyInstaller hidden import에 `win32timezone`이 필요합니다(Task 13).
  - `app.winsvc.start_type`:
    - `StartType = Literal["auto", "delayed-auto", "manual"]`
    - `class ServiceConfigurator(Protocol)`: `def query(self) -> StartType | None`(설치 안 됨 → None), `def apply(self, st: StartType) -> None`(권한 부족 → `PermissionError`, 그 밖 → `OSError`).
    - `class ScmConfigurator(name: str = SERVICE_NAME)`: `OpenSCManager(None, None, SC_MANAGER_CONNECT)` → `OpenService(SERVICE_QUERY_CONFIG [| SERVICE_CHANGE_CONFIG])`(오류 1060 → 설치 안 됨) → `QueryServiceConfig`의 시작 유형(2 auto, 3 demand → `"manual"`) + `QueryServiceConfig2(SERVICE_CONFIG_DELAYED_AUTO_START_INFO)`(auto이고 지연이면 `"delayed-auto"`). `apply`: `ChangeServiceConfig(h, SERVICE_NO_CHANGE, <2|3>, SERVICE_NO_CHANGE, None, None, 0, None, None, None, None)` + `ChangeServiceConfig2(h, SERVICE_CONFIG_DELAYED_AUTO_START_INFO, st == "delayed-auto")`. 오류 5 → `PermissionError`.
    - `class NullConfigurator`: `query` → None, `apply` → `LookupError`.
    - `class StartTypeManager(configurator, settings: SettingsStore, log: LogWriter)`: `running_as_service: bool = False`; `status() -> dict` = `{"installed": bool, "running_as_service": bool, "start_type": StartType | None, "desired": settings.get().service_start_type, "in_sync": bool}`; `reconcile() -> Literal["applied", "in_sync", "not_installed", "denied", "error"]`(블로킹: 설치 안 됨 → `not_installed`, 같으면 `in_sync`, 다르면 `apply(desired)` → `applied` / `PermissionError` → `denied` / `OSError`·`LookupError` → `error`; 결과를 `system` `service.start_type {result, desired, current}`로 기록 — 루프 밖 스레드에서 부르므로 `log.emit_threadsafe`).
  - `Services.start_type: StartTypeManager`. `PUT /api/settings`가 `service_start_type`을 바꿔 저장하면 `result = await asyncio.to_thread(services.start_type.reconcile)` 후 `audit.admin(user, "service_start_type_apply", channel, ip, {"start_type": 새 값, "result": result}, "ok" if result in ("applied", "in_sync", "not_installed") else "error")`. 응답은 지금처럼 `Settings`.
  - `app.web.service_api.router`(Local만): `GET /api/service`(`require(Action.EDIT_GLOBAL_SETTINGS)`) → `await asyncio.to_thread(services.start_type.status)`.
  - `tests/fakes.FakeScm(installed: bool = True, start: StartType = "delayed-auto", fail: Exception | None = None)`: `query`, `apply`(`fail`이 있으면 던짐, 아니면 `applied.append(st)`; `start = st`). conftest의 `build_services`에 `service_configurator=FakeScm()`.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_service_host.py
import asyncio
import socket
import subprocess
import sys
import threading
from pathlib import Path

from app.db import MIGRATIONS, Database
from app.main import ServeControl, serve
from app.paths import AppPaths
from app.rootlock import RootLock
from app.winsvc.host import ServiceHost
from tests.live import free_port

SERVER_DIR = Path(__file__).resolve().parents[1]


def run_app(*args, timeout=60):
    return subprocess.run([sys.executable, "-m", "app", *args], cwd=SERVER_DIR, capture_output=True, text=True,
                          timeout=timeout, stdin=subprocess.DEVNULL)


def test_busy_port_exits_3_without_traceback(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); s.listen(); busy = s.getsockname()[1]
        p = run_app("--root", str(tmp_path / "r"), "--local-port", str(busy), "--external-port", str(free_port()),
                    "--external-host", "127.0.0.1")
    assert p.returncode == 3 and f"port {busy} is already in use" in p.stderr and "Traceback" not in p.stderr
    assert not (tmp_path / "r" / "data" / "config.db").exists()


def test_newer_database_exits_5(tmp_path):
    AppPaths(tmp_path).ensure()
    db = Database(AppPaths(tmp_path).db_path); db.migrate()
    db.execute(f"PRAGMA user_version = {len(MIGRATIONS) + 3}"); db.close()
    p = run_app("--root", str(tmp_path), "--local-port", str(free_port()), "--external-port", str(free_port()),
                "--external-host", "127.0.0.1")
    assert p.returncode == 5 and "written by a newer version" in p.stderr and "Traceback" not in p.stderr


def test_root_in_use_exits_4(tmp_path):
    AppPaths(tmp_path).ensure()
    with RootLock(tmp_path):
        p = run_app("--root", str(tmp_path), "--local-port", str(free_port()), "--external-port", str(free_port()),
                    "--external-host", "127.0.0.1")
    assert p.returncode == 4 and "already in use by another MCP Monitor process" in p.stderr


def test_version_flag():
    p = run_app("--version")
    assert p.returncode == 0 and p.stdout.strip() == "mcp-monitor 1.0.0"


def test_serve_control_stops_from_another_thread(tmp_path):
    ctrl = ServeControl()
    t = threading.Thread(target=lambda: asyncio.run(serve(tmp_path, free_port(), free_port(), external_host="127.0.0.1",
                                                          control=ctrl)))
    t.start()
    assert ctrl.wait_started(30)
    ctrl.nudge_sessions()  # no session collection configured: a no-op
    ctrl.request_stop(); t.join(30)
    assert not t.is_alive() and ctrl.wait_stopped(0)


def test_request_stop_before_start_still_stops(tmp_path):
    ctrl = ServeControl(); ctrl.request_stop()
    t = threading.Thread(target=lambda: asyncio.run(serve(tmp_path, free_port(), free_port(), external_host="127.0.0.1",
                                                          control=ctrl)))
    t.start(); t.join(30)
    assert not t.is_alive()


def test_service_host_runs_until_stop(tmp_path):
    moved = []
    host = ServiceHost(["--root", str(tmp_path), "--local-port", str(free_port()), "--external-port", str(free_port()),
                        "--external-host", "127.0.0.1"], chdir=moved.append)
    codes = []
    t = threading.Thread(target=lambda: codes.append(host.run())); t.start()
    assert host.control.wait_started(30)
    host.session_change(5, 2); host.stop(); t.join(30)
    assert codes == [0] and moved == [tmp_path.resolve()] and host.control.as_service


def test_service_host_reports_a_busy_port(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); s.listen()
        host = ServiceHost(["--root", str(tmp_path), "--local-port", str(s.getsockname()[1]),
                            "--external-port", str(free_port()), "--external-host", "127.0.0.1"], chdir=lambda p: None)
        assert host.run() == 3


def test_service_class_contract():
    from app.winsvc import service
    assert service.McpMonitorService._svc_name_ == "mcp-monitor"
    assert callable(service.McpMonitorService.SvcOtherEx) and callable(service.dispatch)
```

```python
# server/tests/test_start_type.py
import pytest

from app.winsvc.start_type import ScmConfigurator, StartTypeManager
from tests.fakes import FakeScm
from tests.mcp_helpers import login_as, make_user
from tests.test_auth_api import audit_events, bootstrap, login
from tests.winfakes import ListLog


@pytest.mark.parametrize("scm,result,applied", [
    (FakeScm(start="auto"), "applied", ["delayed-auto"]),
    (FakeScm(start="delayed-auto"), "in_sync", []),
    (FakeScm(installed=False), "not_installed", []),
    (FakeScm(start="manual", fail=PermissionError(5, "denied")), "denied", []),
    (FakeScm(start="manual", fail=OSError(1, "x")), "error", []),
])
def test_reconcile(services, scm, result, applied):
    m = StartTypeManager(scm, services.settings, ListLog())
    assert m.reconcile() == result and scm.applied == applied


async def test_put_start_type_applies_and_audits(local_client, services):
    scm = FakeScm(start="delayed-auto"); services.start_type.configurator = scm
    await bootstrap(local_client); await login(local_client, services)
    r = await local_client.put("/api/settings", json={"service_start_type": "manual"}, headers={"X-CSRF-Token": local_client.csrf})
    assert r.status_code == 200 and scm.applied == ["manual"]
    e = [x for x in await audit_events(services, "admin.audit") if x["action"] == "service_start_type_apply"]
    assert e[-1]["target"] == {"start_type": "manual", "result": "applied"} and e[-1]["result"] == "ok"
    st = (await local_client.get("/api/service")).json()
    assert st == {"installed": True, "running_as_service": False, "start_type": "manual", "desired": "manual", "in_sync": True}


async def test_service_route_is_local_admin_only(local_client, external_client, services):
    await bootstrap(local_client)
    login_as(local_client, services, make_user(services, "d@x.com"), "local")
    assert (await local_client.get("/api/service")).status_code == 403
    assert (await external_client.get("/api/service")).status_code == 404


@pytest.mark.winlive
def test_scm_query_without_admin():
    assert ScmConfigurator("EventLog").query() in ("auto", "delayed-auto", "manual")
    assert ScmConfigurator("mcp-monitor-does-not-exist-7f3a").query() is None
```

`StartTypeManager.configurator`는 공개 속성입니다(테스트가 바꿉니다).

- [ ] **Step 2: 실패 확인** — Run: `uv run python -m pytest tests/test_service_host.py tests/test_start_type.py tests/test_channels.py -v` → FAIL

- [ ] **Step 3: 구현** — 위 Interfaces대로. Plan 2의 `_stop_on_signals`는 그대로 둡니다(메인 스레드가 아니면 신호 처리기를 달지 않음). `test_e2e_serve.py::test_graceful_shutdown_stops_monitor`가 그대로 통과해야 합니다.

- [ ] **Step 4: 통과 확인** — Run: `uv run python -m pytest -q` → 통과. Run: `uv run python -m pytest -m winlive -q tests/test_start_type.py` → 통과. Run: `uv run python -m pytest -m integration -q` → 통과

- [ ] **Step 5: Commit** — `git commit -m "feat: Windows service host with cross-thread stop and session nudges, pre-bound ports, clean exit codes, root lock and start-type reconciliation"`

---

### Task 9: 배포 묶음 위치, 기본 경로, 에이전트 실행 명령

**Files:**
- Create: `server/app/bundle.py`, `server/tests/test_bundle_paths.py`
- Modify: `server/app/__main__.py`(기본값), `server/app/collect/cli.py`(`--agent-dir` 기본값과 `AgentOptions.command`), `server/app/activity/agent_supervisor.py`(`AgentOptions.command`, `agent_argv`·`agent_env`), `agent/mcp_agent/__init__.py`(`VERSION = "1.0.0"`)

**Interfaces:**
- Produces:
  - `app.bundle`:
    - `@dataclass(frozen=True) Bundle(root: Path, layout: Literal["pyinstaller", "runtime"], version: str)`
    - `find_bundle(executable: Path | None = None) -> Bundle | None`: `executable`(기본 `Path(sys.executable)`)의 부모부터 위로 최대 3단계에서 `bundle.json`을 찾습니다. JSON이 `{"layout": "pyinstaller" | "runtime", "version": str, ...}`가 아니면 무시(None).
    - `default_static_dir(b: Bundle | None) -> Path`: 묶음이면 `b.root / "web"`, 아니면 `<repo>/web/dist`(지금 값).
    - `default_root(b: Bundle | None) -> Path`: 묶음이면 `Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "MCP Monitor"`, 아니면 `Path.cwd()`.
    - `agent_command(b: Bundle | None, python: str = sys.executable) -> tuple[str, ...]`: `pyinstaller` → `(str(b.root / "bin" / "agent" / "mcp-agent.exe"),)`, `runtime` → `(str(b.root / "runtime" / "python.exe"), "-m", "mcp_agent")`, None → `(python, "-m", "mcp_agent")`.
  - `parse_args`: `--root` 기본 `default_root(find_bundle())`, `--static-dir` 기본 `default_static_dir(find_bundle())`. Plan 3 `test_main_cli.py::test_defaults`는 그대로 통과합니다(개발 환경에는 `bundle.json`이 없음).
  - Plan 4 `AgentOptions`에 `command: tuple[str, ...] | None = None`. `agent_argv(options, server_url: str, session_id: int) -> list[str]` = `[*(options.command or (options.python, "-m", "mcp_agent")), "--server", server_url, "--dialog", options.dialog]` + print면 `["--url-file", str(url_dir / f"agent-{session_id}.url")]`. `agent_env(options, token: str) -> dict[str, str]` = `{"MCPMON_AGENT_TOKEN": token}` + `command`가 None일 때만 `"PYTHONPATH": str(options.agent_dir)`. `_launch`가 이 두 함수를 씁니다(동작은 개발 환경에서 지금과 같음). CLI는 묶음이 있으면 `command = agent_command(bundle)`, `cwd` = 묶음 루트.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_bundle_paths.py
import json
import sys
from pathlib import Path

from app.activity.agent_supervisor import AgentOptions, agent_argv, agent_env
from app.bundle import Bundle, agent_command, default_root, default_static_dir, find_bundle


def make_bundle(root: Path, layout: str) -> None:
    (root / "bundle.json").write_text(json.dumps({"layout": layout, "version": "1.0.0", "python": "3.15.2"}), "utf-8")


def test_runtime_layout(tmp_path):
    make_bundle(tmp_path, "runtime")
    exe = tmp_path / "runtime" / "python.exe"; exe.parent.mkdir(); exe.write_bytes(b"")
    b = find_bundle(exe)
    assert b == Bundle(tmp_path, "runtime", "1.0.0")
    assert agent_command(b) == (str(tmp_path / "runtime" / "python.exe"), "-m", "mcp_agent")
    assert default_static_dir(b) == tmp_path / "web"


def test_pyinstaller_layout(tmp_path):
    make_bundle(tmp_path, "pyinstaller")
    exe = tmp_path / "bin" / "monitor" / "mcp-monitor.exe"; exe.parent.mkdir(parents=True); exe.write_bytes(b"")
    assert agent_command(find_bundle(exe)) == (str(tmp_path / "bin" / "agent" / "mcp-agent.exe"),)


def test_no_or_invalid_bundle(tmp_path):
    assert find_bundle(Path(sys.executable)) is None
    (tmp_path / "bundle.json").write_text('{"layout": "zip"}', "utf-8")
    exe = tmp_path / "x.exe"; exe.write_bytes(b"")
    assert find_bundle(exe) is None


def test_default_root(monkeypatch, tmp_path):
    monkeypatch.setenv("ProgramData", str(tmp_path))
    assert default_root(Bundle(tmp_path, "runtime", "1.0.0")) == tmp_path / "MCP Monitor"
    assert default_root(None) == Path.cwd()


def test_agent_argv_and_env_use_the_bundle_command(tmp_path):
    o = AgentOptions(command=("C:/MCP/bin/agent/mcp-agent.exe",), dialog="edge")
    assert agent_argv(o, "http://127.0.0.1:8700", 2) == ["C:/MCP/bin/agent/mcp-agent.exe", "--server", "http://127.0.0.1:8700", "--dialog", "edge"]
    assert agent_env(o, "tok") == {"MCPMON_AGENT_TOKEN": "tok"}
    dev = AgentOptions(agent_dir=tmp_path, python="py.exe", dialog="print", url_dir=tmp_path)
    assert agent_argv(dev, "http://127.0.0.1:8700", 3)[:3] == ["py.exe", "-m", "mcp_agent"]
    assert agent_argv(dev, "http://127.0.0.1:8700", 3)[-2:] == ["--url-file", str(tmp_path / "agent-3.url")]
    assert agent_env(dev, "tok") == {"MCPMON_AGENT_TOKEN": "tok", "PYTHONPATH": str(tmp_path)}
```

- [ ] **Step 2: 실패 확인** — Run: `uv run python -m pytest tests/test_bundle_paths.py tests/test_main_cli.py -v` → FAIL

- [ ] **Step 3: 구현** — 위 Interfaces대로. Plan 4의 감독자 테스트(`test_agent_supervisor.py`)는 그대로 통과해야 합니다.

- [ ] **Step 4: 통과 확인** — Run(server): `uv run python -m pytest -q` → 통과. Run(agent): `uv run python -m pytest -q` → 통과

- [ ] **Step 5: Commit** — `git commit -m "feat: locate the deployment bundle for default root, static dir and agent command"`

---

### Task 10: 웹 — 로그 조회 기반 (타입, 엔드포인트, URL 상태, 서식, 문구, 내비)

**Files:**
- Create: `web/src/admin/logs/search.ts`, `web/src/admin/logs/search.test.ts`, `web/src/admin/logs/categories.ts`, `web/src/admin/logs/log-format.ts`, `web/src/admin/logs/log-format.test.ts`
- Modify: `web/src/lib/api-types.ts`, `web/src/lib/api.ts`(배열 쿼리), `web/src/lib/api.test.ts`, `web/src/lib/endpoints.ts`, `web/src/lib/time.ts`(`formatKstMs`), `web/src/lib/time.test.ts`, `web/src/admin/query-keys.ts`, `web/src/admin/queries.ts`, `web/src/admin/router.tsx`(`/admin/logs`, `/admin/audit` 자리 표시), `web/src/admin/shell/Nav.tsx`, `web/src/admin/shell/CommandPalette.tsx`, `web/src/admin/shell/shell.test.tsx`, `web/src/copy/ko.ts`, `web/src/copy/ko.test.ts`, `web/src/styles/tokens.css`, `web/src/styles/tokens.contrast.test.ts`, `web/tests/msw/fixtures.ts`, `web/tests/msw/handlers.ts`, `web/tests/setup.ts`(PointerEvent·ResizeObserver 대체), `web/tests/budget/bundle-budget.test.ts`, `web/package.json`·`web/pnpm-lock.yaml`

**Interfaces:**
- Consumes: Task 5 API(부록 B), Plan 3 `api()`·`can()`·`denyReason()`·`WithReason`·`renderWithProviders`.
- Produces:
  - `api-types.ts`:
    ```ts
    export type LogCategory = "session" | "notice" | "activity.process" | "activity.command" | "activity.window" | "activity.idle"
      | "tamper" | "mcp.health" | "mcp.action" | "auth" | "admin.audit" | "system";
    export type LogOutcome = "ok" | "fail" | "denied" | "error" | "failed" | "timeout";
    export interface LogItem { id: number; ts: string; cat: LogCategory; event: string | null; user: string | null; session_id: number | null;
      client_ip: string | null; outcome: LogOutcome | null; data: Record<string, unknown> }
    export interface LogPage { items: LogItem[]; next_cursor: string | null; index: { ready: boolean } }
    export interface LogHistogram { from: string; to: string; bucket_sec: number; starts: string[];
      series: { key: string | null; counts: number[] }[]; total: number; source: "rollup" | "scan" }
    export interface LogUserCount { user: string; count: number }
    export interface LogIndexStatus { ready: boolean; rebuilding: boolean; files: number; pending_files: number; pending_bytes: number;
      rows: number; bad_lines: number; oldest_day: string | null; newest_day: string | null; last_indexed_at: string | null }
    export interface LogQuery { from: string; to: string; users?: string[]; cat?: LogCategory[]; event?: string[]; outcome?: LogOutcome[];
      session?: number; ip?: string; q?: string }
    export interface AuditQuery extends Omit<LogQuery, "cat" | "event" | "outcome" | "session" | "ip"> { kind?: "admin" | "auth" | "all";
      result?: LogOutcome[]; channel?: Channel }
    export interface ServiceStatus { installed: boolean; running_as_service: boolean; start_type: Settings["service_start_type"] | null;
      desired: Settings["service_start_type"]; in_sync: boolean }
    // RetentionPreview에 추가: delete_events: number | null
    ```
  - `api.ts`: `query?: Record<string, string | number | readonly (string | number)[] | undefined>` — 배열은 같은 키로 여러 번 `append`, `undefined`·빈 배열·빈 문자열은 생략. `apiUrl`도 같은 규칙.
  - `endpoints.ts`: `logs(q: LogQuery, cursor?: string, limit = 200): Promise<LogPage>`, `logHistogram(q: LogQuery, opts?: { buckets?: number; group?: "none" | "cat" | "user" }): Promise<LogHistogram>`, `logUsers(q: LogQuery): Promise<LogUserCount[]>`, `logStatus(): Promise<LogIndexStatus>`, `logExportUrl(q: LogQuery, format: "csv" | "jsonl"): string`, `audit(q: AuditQuery, cursor?: string, limit = 200): Promise<LogPage>`, `auditExportUrl(q: AuditQuery, format): string`, `serviceStatus(): Promise<ServiceStatus>`.
  - `query-keys.ts`: `logs: (q) => ["logs", "page", q]`, `logHistogram: (q, group, buckets) => ["logs", "histogram", q, group, buckets]`, `logUsers: (q) => ["logs", "users", q]`, `logStatus: ["logs", "status"]`, `audit: (q) => ["audit", q]`, `service: ["service"]`. `queries.ts`: `useLogPages(q)`(`useInfiniteQuery`, `getNextPageParam = p => p.next_cursor ?? undefined`), `useLogHistogram(q, group, buckets)`, `useLogUsers(q)`, `useLogStatus()`(준비 전이면 5초마다 다시 읽음, 준비되면 멈춤), `useAuditPages(q)`, `useServiceStatus({ enabled })` — 로그는 `enabled: can(me, "view_logs")`, 감사는 `view_audit`, 서비스는 `edit_global_settings`(외부 채널에서는 부르지 않음).
  - `search.ts`:
    ```ts
    export type QuickRange = "1h" | "today" | "yesterday" | "7d";
    export interface LogSearch { range?: QuickRange; from?: string; to?: string; users?: string[]; cat?: LogCategory[]; event?: string[];
      outcome?: LogOutcome[]; session?: number; ip?: string; q?: string; view?: "table" | "timeline" }
    export function parseLogSearch(raw: Record<string, unknown>): LogSearch        // 라우트 validateSearch; 틀린 값은 버림
    export function resolveRange(s: LogSearch, now: Date): { from: string; to: string }
    export function toLogQuery(s: LogSearch, now: Date): LogQuery
    export function floorKstMinute(iso: string): string
    ```
    규칙(W34): `from`·`to`가 둘 다 있으면 그 값을 KST 분으로 내림(밀리초·초 버림)해 씁니다. 없으면 `range`(기본 `"1h"`): `1h` → `to` = 지금을 분 단위로 **올림**, `from` = `to − 60분`; `today` → KST 오늘 00:00 ~ 올림한 지금; `yesterday` → 어제 00:00 ~ 오늘 00:00; `7d` → (오늘 − 6일) 00:00 ~ 올림한 지금. 출력 형식 `YYYY-MM-DDTHH:mm:00.000+09:00`. `parseLogSearch`: `range`는 4값만, `cat`·`outcome`은 허용 값만 남김, `users`·`event`는 문자열 배열만(배열이 아니면 버림), `session`은 0 이상 정수, `view`는 2값만, `from`/`to`는 오프셋 있는 ISO만.
  - `categories.ts`: `LOG_CATEGORIES: readonly LogCategory[]`(서버 순서), `CATEGORY_GROUP: Record<LogCategory, "session" | "activity" | "mcp" | "security" | "system">`(`session`·`notice` → session, `activity.*` → activity, `mcp.*` → mcp, `auth`·`admin.audit`·`tamper` → security, `system` → system), `GROUP_COLOR_VAR: Record<Group, string>` = `var(--color-cat-<group>)`.
  - `tokens.css`: `--color-cat-{session,activity,mcp,security,system}`(light/dark `light-dark()`), 대비 테스트에 "UI 3:1 대비 surface" 항목 5개 추가(W32).
  - `log-format.ts`: `summarize(item: LogItem): string` — `activity.command`: `data.text ?? data.cmdline`; `activity.process`: `` `${event} ${data.name} (${data.pid})` ``; `activity.window`: `data.title ?? data.exe`; `activity.idle`: `event`; `session`: `` `${event} ${client_ip ?? ""}` ``(끝 공백 제거); `notice`: `` `${event} v${data.version}` ``; `auth`: `` `${event} ${user}` ``; `admin.audit`: `` `${event} ${targetSummary(data.target)}` ``(`target`의 `email` → `name` → `path` → `id` 중 처음 값, 없으면 빈 칸; 끝 공백 제거); `mcp.action`: `` `${data.name} ${data.kind} ${outcome}` ``; `mcp.health`: `` `${data.name} ${data.issue ?? (data.alert ? "alert" : "")}` ``; `tamper`·`system`: `event`. 값이 없으면 그 조각을 빼고 공백을 정리하며 300자에서 자릅니다. 한국어 문구는 쓰지 않습니다(식별자·데이터만).
  - `time.ts`: `formatKstMs(iso): string` → `YYYY-MM-DD HH:mm:ss.SSS`.
  - 내비: 로그는 `denyReason(me, "view_logs")`, 감사 로그는 `denyReason(me, "view_audit")`(로그인한 사용자에게 두 채널 모두 열림). `planned_logs`·`planned_audit`은 `DisabledReason` 타입과 문구에 남기되 더는 쓰지 않습니다(W31과 같은 처리). 명령 팔레트에 두 항목. 라우트 `/admin/logs`(search = `parseLogSearch`), `/admin/audit`(search: `range`, `from`, `to`, `kind`, `users`, `result`, `channel`, `q`)는 이 Task에서 제목만 있는 자리 표시, `lazyRouteComponent`.
  - 설치: `@tanstack/react-virtual`(정확한 최신 안정 버전), Plan 3이 아직 설치하지 않았다면 `@tanstack/react-table`. 예산 테스트의 보드 금지 목록 정규식에 `@tanstack\/react-virtual|@tanstack\/react-table`을 더합니다.
  - `tests/setup.ts`: `globalThis.PointerEvent`가 없으면 `MouseEvent`를 상속해 `pointerId`를 받는 대체 클래스, `ResizeObserver`가 없으면 아무것도 하지 않는 대체 클래스.
  - `fixtures.ts`: `logItem(p?: Partial<LogItem>)`, `logPage(items: LogItem[], next?: string | null)`, `histogramFixture(p?)`(기본: 13:00–14:00 KST, 600초 막대 6개, `[1, 2, 3, 0, 0, 4]`), `userCounts()`, `logStatusFixture(p?)`, `serviceStatusFixture(p?)`; `previewFixture`에 `delete_events: 0`. `handlers.ts` 기본 핸들러: `/api/logs`, `/api/logs/histogram`, `/api/logs/users`, `/api/logs/status`, `/api/audit`, `/api/service`.

- [ ] **Step 1: 실패하는 테스트 작성**

```ts
// web/src/admin/logs/search.test.ts
import { parseLogSearch, resolveRange, toLogQuery } from "./search";
const NOW = new Date("2026-11-04T05:03:27.123Z"); // 14:03:27 KST
it.each([
  ["1h", "2026-11-04T13:04:00.000+09:00", "2026-11-04T14:04:00.000+09:00"],
  ["today", "2026-11-04T00:00:00.000+09:00", "2026-11-04T14:04:00.000+09:00"],
  ["yesterday", "2026-11-03T00:00:00.000+09:00", "2026-11-04T00:00:00.000+09:00"],
  ["7d", "2026-10-29T00:00:00.000+09:00", "2026-11-04T14:04:00.000+09:00"],
] as const)("resolves %s in KST minutes", (range, from, to) => {
  expect(resolveRange({ range }, NOW)).toEqual({ from, to });
});
it("custom from/to win over range and are minute-aligned", () => {
  expect(resolveRange({ range: "7d", from: "2026-11-04T01:15:42.000Z", to: "2026-11-04T11:00:00.000+09:00" }, NOW))
    .toEqual({ from: "2026-11-04T10:15:00.000+09:00", to: "2026-11-04T11:00:00.000+09:00" });
});
it("defaults to the last hour", () => { expect(resolveRange({}, NOW)).toEqual(resolveRange({ range: "1h" }, NOW)); });
it("drops invalid search values", () => {
  expect(parseLogSearch({ range: "2y", cat: ["auth", "nope"], users: "x", session: -1, view: "grid", from: "2026-11-04T10:00:00" }))
    .toEqual({ cat: ["auth"] });
});
it("builds the API query without empty filters", () => {
  expect(toLogQuery({ range: "1h", users: [], cat: ["auth"], q: "" }, NOW))
    .toEqual({ from: "2026-11-04T13:04:00.000+09:00", to: "2026-11-04T14:04:00.000+09:00", cat: ["auth"] });
});
```

```ts
// web/src/lib/api.test.ts (추가)
it("encodes repeated filter params and skips empty ones", async () => {
  const seen: string[] = [];
  server.use(http.get("/api/logs", ({ request }) => { seen.push(new URL(request.url).search); return HttpResponse.json(logPage([])); }));
  await endpoints.logs({ from: "2026-11-04T13:00:00.000+09:00", to: "2026-11-04T14:00:00.000+09:00", users: ["CORP\\hong", "a@x.com"],
    cat: ["auth"], event: [], q: "" }, undefined, 200);
  const p = new URLSearchParams(seen[0]);
  expect(p.getAll("users")).toEqual(["CORP\\hong", "a@x.com"]); expect(p.getAll("cat")).toEqual(["auth"]);
  expect(p.get("from")).toBe("2026-11-04T13:00:00.000+09:00"); expect(p.get("limit")).toBe("200");
  expect(p.has("event")).toBe(false); expect(p.has("q")).toBe(false);
});
it("builds export URLs with the same params", () => {
  const u = new URL(endpoints.logExportUrl({ from: "2026-11-04T13:00:00.000+09:00", to: "2026-11-04T14:00:00.000+09:00", cat: ["auth"] }, "csv"), "http://x");
  expect(u.pathname).toBe("/api/logs/export"); expect(u.searchParams.get("format")).toBe("csv"); expect(u.searchParams.getAll("cat")).toEqual(["auth"]);
});
```

```ts
// web/src/admin/logs/log-format.test.ts
import { summarize } from "./log-format";
import { logItem } from "../../../tests/msw/fixtures";
it.each([
  [logItem({ cat: "activity.command", data: { text: "Get-Process", shell: "powershell" } }), "Get-Process"],
  [logItem({ cat: "activity.process", event: "start", data: { name: "notepad.exe", pid: 8812 } }), "start notepad.exe (8812)"],
  [logItem({ cat: "auth", event: "login", user: "a@x.com", outcome: "fail", data: {} }), "login a@x.com"],
  [logItem({ cat: "admin.audit", event: "user_create", data: { target: { email: "b@x.com" } } }), "user_create b@x.com"],
  [logItem({ cat: "session", event: "connect", client_ip: null, data: {} }), "connect"],
  [logItem({ cat: "mcp.action", outcome: "timeout", data: { name: "calc", kind: "start" } }), "calc start timeout"],
])("summarizes %#", (item, text) => { expect(summarize(item)).toBe(text); });
it("caps long summaries at 300 chars", () => {
  expect(summarize(logItem({ cat: "activity.command", data: { text: "x".repeat(500) } }))).toHaveLength(300);
});
```

```tsx
// web/src/admin/shell/shell.test.tsx (기존 "planned and forbidden nav items" 테스트에서 logs 항목을 지우고 추가)
it("opens the logs and audit nav for signed-in users on both channels", () => {
  for (const channel of ["local", "external"] as const) {
    const { unmount } = renderShell(meFixture("developer", channel));
    for (const name of [copy.nav.logs, copy.nav.audit])
      expect(screen.getByRole("link", { name })).not.toHaveAttribute("aria-disabled");
    unmount();
  }
});
```

```ts
// web/src/lib/time.test.ts (추가)
it("formats with milliseconds", () => { expect(formatKstMs("2026-11-04T05:03:22.418Z")).toBe("2026-11-04 14:03:22.418"); });
// web/src/copy/ko.test.ts (추가)
it("names every log category and group", () => {
  for (const c of LOG_CATEGORIES) expect(copy.logs.cats[c]).toMatch(/\S/);
  for (const g of ["session", "activity", "mcp", "security", "system"] as const) expect(copy.logs.groups[g]).toMatch(/\S/);
  expect(copy.logs.cmdLimitHelp).toContain("cmd");
});
```

- [ ] **Step 2: 실패 확인** — Run: `pnpm test` → FAIL

- [ ] **Step 3: 구현** — 위 Interfaces대로. 문구는 `design:ux-copy` 스킬로 Plan 3 Task 6의 어조에 맞춥니다(입력: Global Constraints의 키 목록, 카테고리 12개·묶음 5개 이름, cmd 내부 명령을 수집하지 않는다는 도움말(spec §2 #7: `cmd.exe` 실행·인자, cmd가 실행한 외부 프로그램, `cmd /c`, 배치 파일은 기록, `dir`·`cd`·`del` 같은 내부 명령은 기록하지 않음, 키 입력·클립보드·화면도 수집하지 않음), 색인 중 안내, 빈 상태).

- [ ] **Step 4: 통과 확인** — Run: `pnpm typecheck && pnpm lint && pnpm test && pnpm build && pnpm test:budget` → 통과

- [ ] **Step 5: Commit** — `git commit -m "feat(web): log query types, endpoints, URL search state, summaries, category tokens and open logs/audit nav"`

---

### Task 11: 웹 — 로그 조회 화면 (히스토그램 드래그, 사용자 필터, 가상 표, 타임라인, 내보내기)

**Files:**
- Create: `docs/design/screens/logs.md`
- Create: `web/src/components/data/VirtualTable.tsx`, `web/src/components/data/VirtualTable.test.tsx`
- Create: `web/src/admin/logs/{LogsPage,FilterBar,TimeRangePicker,LogHistogram,UserFilter,CategoryChips,LogTable,LogDetail,UserTimeline,ExportMenu,IndexBanner}.tsx`, `web/src/admin/logs/histogram.test.tsx`, `web/src/admin/logs/logs.test.tsx`
- Modify: `web/src/admin/router.tsx`(`/admin/logs` → `LogsPage`), `web/src/copy/ko.ts`

**Interfaces:**
- Consumes: Task 10 전부, Plan 3 `WithReason`, shadcn `popover`·`command`·`dialog`·`dropdown-menu`·`input`·`button`·`badge`·`tooltip`, `useSession`.
- Produces:
  - `VirtualTable<T>({ rows: T[]; columns: ColumnDef<T>[]; rowHeight?: number /* 32 */; getRowId(r: T): string; onRowOpen(r: T): void; hasMore: boolean; onLoadMore(): void; ariaLabel: string; initialRect?: { width: number; height: number } })`: TanStack Table(열 정의·머리글) + `useVirtualizer`(`overscan: 20`, `initialRect` 전달). 시맨틱 `<table>`, 위·아래 여백 `<tr aria-hidden>`, 행 `tabIndex={0}`·`aria-rowindex`, ↑/↓로 행 포커스 이동(`scrollToIndex`), Enter로 `onRowOpen`. 보이는 마지막 항목 인덱스가 `rows.length − 20` 이상이고 `hasMore`면 `onLoadMore` 한 번. 표는 자기 스크롤 컨테이너(`overflow: auto`, 높이 = 남은 뷰포트)를 가지며 페이지를 가로로 밀어내지 않습니다(W41). 애니메이션 없음.
  - `LogHistogram({ data: LogHistogram; onSelect(from: string, to: string): void; compact?: boolean })`: 직접 그린 SVG(Recharts 아님, W32). 루트 `<svg data-testid="log-histogram" role="group" tabIndex={0} aria-label={copy.logs.histogramLabel(from, to, total)}>`. 계열은 `CATEGORY_GROUP`으로 묶어 5색 누적(그룹 없음이면 단색). 막대 폭 = `max(2, 너비 / n − 1)`px(W41: 640px 창에서도 막대 200개까지 2px 보장, 넘치면 `buckets`를 줄이는 것은 `LogsPage`의 몫), 축 글자는 컨테이너 너비 < 480px이면 처음·끝만. 드래그: `pointerdown`에서 `setPointerCapture?.(pointerId)`, 버킷 인덱스 = `floor((clientX − rect.left) / (rect.width / n))`(0..n−1로 자름), `pointermove`로 범위 갱신(선택 영역 사각형), `pointerup`에서 `onSelect(starts[lo], lo..hi의 끝 = starts[hi] + bucket_sec)`(끝은 `data.to`를 넘지 않게 자름). 키보드: 포커스 버킷(처음 0) ←/→ 이동, Shift+←/→ 선택 확장, Enter 적용, Escape 선택 해제. 선택·포커스는 `aria-live="polite"` 영역에 `copy.logs.selection(from, to, count)`. 호버 툴팁(버킷 시각·건수). 애니메이션 없음.
  - `LogsPage`: URL search(`LogSearch`)가 유일한 상태. 구성(위→아래): `IndexBanner`(`useLogStatus`가 준비 전이면 `copy.logs.indexing(pending_files)`), `FilterBar`(`TimeRangePicker` 빠른 선택 4개 + `datetime-local` 두 칸(분 단위) + 적용; `CategoryChips`(그룹별 묶음, 칩마다 토글); `UserFilter`(팝오버 + cmdk 목록, 각 항목 체크 + `useLogUsers` 건수, 선택 수 배지); 세션 번호·클라이언트 IP·키워드 입력(키워드는 300ms 디바운스); `event`·`outcome`이 URL에 있으면 "추가 조건" 칩(지울 수 있음); 도움말 팝오버 `copy.logs.cmdLimitHelp`; `ExportMenu`), `LogHistogram`(`group="cat"`, 버킷 수 = 컨테이너 너비 ≥ 1024px면 60, ≥ 640px면 40, 아니면 24), 보기 전환(표/타임라인), 본문. 히스토그램 선택 → `navigate({ search: s => ({ ...s, from, to, range: undefined }) })`. 필터는 컨테이너 쿼리로 640px 창에서 두 줄 이상으로 접힙니다.
  - `LogTable`: `VirtualTable<LogItem>` 열 = 시각(`formatKstMs`), 카테고리(`copy.logs.cats`), 사용자, 세션, IP, 이벤트, 요약(`summarize`). 데이터 = `useLogPages`의 페이지를 이어 붙임. 행 열기 → `LogDetail`(대화상자: 시각, 카테고리, 원문 JSON을 `<pre>`로, "이 사용자로 거르기"·"이 세션으로 거르기" 버튼). 640px 창에서 대화상자는 `max-inline-size: calc(100vw − 32px)`, 닫기 버튼이 항상 보임.
  - `UserTimeline`: `useLogHistogram(q, "user", buckets)`의 계열마다 한 줄(사용자 이름 + 합계 + 막대 칸 띠, 칸 진하기 = `color-mix(in oklch, var(--color-accent) <비율>%, transparent)`). 줄 하나가 `role="group"` 하나(로빙 tabindex, ←/→로 칸 이동, Enter → `{ users: [사용자], from: 칸 시작, to: 칸 끝, view: "table" }`로 이동). `"__other__"`와 `null` 계열은 클릭할 수 없는 줄. 640px에서는 이름 열이 칸 위로 올라갑니다(컨테이너 쿼리).
  - `ExportMenu`: `export_logs`가 막히면 `WithReason`. 메뉴의 두 항목은 `<a href={endpoints.logExportUrl(query, fmt)} download>`.
  - `docs/design/screens/logs.md`: `frontend-design` 스킬과 `dataviz` 스킬로 정한 배치(1920·1280·1024·800·640px), 색(카테고리 묶음 5색), 밀도, 빈·색인 중 상태, 키보드 경로, Playwright 플러그인 점검 목록.

- [ ] **Step 1: `frontend-design`·`dataviz` 스킬로 로그 화면 설계** — 입력: spec §6.4 #4, Plan 3 `docs/design/direction.md`, 위 Interfaces, Global Constraints의 창 크기 규칙. 출력: `docs/design/screens/logs.md`.

- [ ] **Step 2: 실패하는 테스트 작성**

```tsx
// web/src/admin/logs/histogram.test.tsx
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { histogramFixture } from "../../../tests/msw/fixtures";
import { LogHistogram } from "./LogHistogram";

const H = histogramFixture(); // 13:00–14:00 KST, 600 s buckets, counts [1, 2, 3, 0, 0, 4]
const rect = (width: number) => ({ left: 0, top: 0, width, height: 120, right: width, bottom: 120, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect;

it("drag across buckets selects their minute-aligned span", () => {
  const onSelect = vi.fn(); render(<LogHistogram data={H} onSelect={onSelect} />);
  const svg = screen.getByTestId("log-histogram"); vi.spyOn(svg, "getBoundingClientRect").mockReturnValue(rect(600));
  fireEvent.pointerDown(svg, { clientX: 150, pointerId: 1 }); fireEvent.pointerMove(svg, { clientX: 350, pointerId: 1 });
  fireEvent.pointerUp(svg, { clientX: 350, pointerId: 1 });
  expect(onSelect).toHaveBeenCalledWith("2026-11-04T13:10:00.000+09:00", "2026-11-04T13:40:00.000+09:00");
});
it("selects with Shift+Arrow and applies with Enter", async () => {
  const onSelect = vi.fn(); render(<LogHistogram data={H} onSelect={onSelect} />);
  screen.getByTestId("log-histogram").focus();
  await userEvent.keyboard("{ArrowRight}{Shift>}{ArrowRight}{ArrowRight}{/Shift}{Enter}");
  expect(onSelect).toHaveBeenCalledWith("2026-11-04T13:10:00.000+09:00", "2026-11-04T13:40:00.000+09:00");
});
it("Escape clears the selection without applying", async () => {
  const onSelect = vi.fn(); render(<LogHistogram data={H} onSelect={onSelect} />);
  screen.getByTestId("log-histogram").focus();
  await userEvent.keyboard("{Shift>}{ArrowRight}{/Shift}{Escape}{Enter}");
  expect(onSelect).toHaveBeenCalledWith("2026-11-04T13:00:00.000+09:00", "2026-11-04T13:10:00.000+09:00");
});
it("histogram keeps a 2px minimum bar and drops labels when narrow", () => {
  const many = histogramFixture({ bucket_sec: 60, starts: Array.from({ length: 200 }, (_, i) => new Date(Date.UTC(2026, 10, 4, 4, 0) + i * 60000).toISOString()),
    series: [{ key: null, counts: Array.from({ length: 200 }, () => 1) }] });
  render(<LogHistogram data={many} onSelect={vi.fn()} width={400} />);
  const bars = screen.getByTestId("log-histogram").querySelectorAll("rect[data-bucket]");
  expect(bars).toHaveLength(200);
  for (const b of bars) expect(Number(b.getAttribute("width"))).toBeGreaterThanOrEqual(2);
  expect(screen.getByTestId("log-histogram").querySelectorAll("text[data-axis]")).toHaveLength(2);
});
it("has no animation markers", () => {
  render(<LogHistogram data={H} onSelect={vi.fn()} />);
  expect(document.querySelector("[data-anim]")).toBeNull();
});
```

`width`는 테스트·SSR용 선택 prop(없으면 `ResizeObserver`로 잰 컨테이너 너비)입니다.

```tsx
// web/src/admin/logs/logs.test.tsx (MSW, renderWithProviders(null, { me, route }))
const ME = meFixture("developer", "external");
beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({ left: 0, top: 0, width: 1200, height: 800, right: 1200, bottom: 800, x: 0, y: 0, toJSON: () => ({}) } as DOMRect);
});

it("loads the first page and renders summarized rows", async () => {
  server.use(http.get("/api/logs", () => HttpResponse.json(logPage([logItem({ id: 2, cat: "activity.command", data: { text: "Get-Process" } })]))));
  renderWithProviders(null, { me: ME, route: "/admin/logs?range=1h" });
  expect(await screen.findByText("Get-Process")).toBeInTheDocument();
  expect(screen.getByRole("table", { name: copy.logs.title })).toBeInTheDocument();
});
it("writes the selection to the URL and drops the quick range", async () => {
  const { router } = renderWithProviders(null, { me: ME, route: "/admin/logs?range=1h" });
  const svg = await screen.findByTestId("log-histogram"); svg.focus();
  await userEvent.keyboard("{ArrowRight}{Enter}");
  await waitFor(() => expect(router.state.location.search).toMatchObject({ from: "2026-11-04T13:10:00.000+09:00", to: "2026-11-04T13:20:00.000+09:00" }));
  expect(router.state.location.search).not.toHaveProperty("range");
});
it("toggles a category chip into the URL and the request", async () => {
  const tracker = trackRequests();
  const { router } = renderWithProviders(null, { me: ME, route: "/admin/logs" });
  await userEvent.click(await screen.findByRole("button", { name: copy.logs.cats.auth }));
  await waitFor(() => expect(router.state.location.search).toMatchObject({ cat: ["auth"] }));
  await waitFor(() => expect(tracker.urls().some((u) => new URL(u, "http://x").searchParams.getAll("cat").includes("auth"))).toBe(true));
});
it("shows user counts and filters by a picked user", async () => {
  server.use(http.get("/api/logs/users", () => HttpResponse.json([{ user: "CORP\\hong", count: 12 }, { user: "a@x.com", count: 3 }])));
  const { router } = renderWithProviders(null, { me: ME, route: "/admin/logs" });
  await userEvent.click(await screen.findByRole("button", { name: copy.logs.users }));
  await userEvent.click(await screen.findByRole("option", { name: /CORP\\hong.*12/ }));
  await waitFor(() => expect(router.state.location.search).toMatchObject({ users: ["CORP\\hong"] }));
});
it("debounces the keyword into q", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const { router } = renderWithProviders(null, { me: ME, route: "/admin/logs" });
  await userEvent.type(await screen.findByLabelText(copy.logs.keyword), "notepad");
  expect(router.state.location.search).not.toHaveProperty("q");
  await vi.advanceTimersByTimeAsync(300);
  await waitFor(() => expect(router.state.location.search).toMatchObject({ q: "notepad" }));
  vi.useRealTimers();
});
it("loads the next page near the end of the table", async () => {
  const first = Array.from({ length: 30 }, (_, i) => logItem({ id: 100 - i }));
  let calls = 0;
  server.use(http.get("/api/logs", ({ request }) => { calls++; return HttpResponse.json(new URL(request.url).searchParams.get("cursor") ? logPage([logItem({ id: 1 })]) : logPage(first, "c1")); }));
  renderWithProviders(null, { me: ME, route: "/admin/logs" });
  await screen.findAllByRole("row");
  await waitFor(() => expect(calls).toBe(2));
});
it("opens the detail dialog with the raw JSON", async () => {
  server.use(http.get("/api/logs", () => HttpResponse.json(logPage([logItem({ id: 7, data: { text: "secret-cmd" } })]))));
  renderWithProviders(null, { me: ME, route: "/admin/logs" });
  (await screen.findByText("secret-cmd")).closest("tr")!.focus(); await userEvent.keyboard("{Enter}");
  expect(await screen.findByRole("dialog", { name: copy.logs.detail })).toHaveTextContent('"text": "secret-cmd"');
});
it("timeline lanes link to a filtered table", async () => {
  server.use(http.get("/api/logs/histogram", ({ request }) => HttpResponse.json(new URL(request.url).searchParams.get("group") === "user"
    ? histogramFixture({ series: [{ key: "CORP\\hong", counts: [0, 5, 0, 0, 0, 0] }] }) : histogramFixture())));
  const { router } = renderWithProviders(null, { me: ME, route: "/admin/logs?view=timeline" });
  const lane = await screen.findByRole("group", { name: /CORP\\hong/ }); lane.focus();
  await userEvent.keyboard("{ArrowRight}{Enter}");
  await waitFor(() => expect(router.state.location.search).toMatchObject({ users: ["CORP\\hong"], view: "table",
    from: "2026-11-04T13:10:00.000+09:00", to: "2026-11-04T13:20:00.000+09:00" }));
});
it("export links carry the current filters", async () => {
  renderWithProviders(null, { me: ME, route: `/admin/logs?cat=${encodeURIComponent(JSON.stringify(["auth"]))}` });
  await userEvent.click(await screen.findByRole("button", { name: copy.logs.export.menu }));
  const href = (await screen.findByRole("menuitem", { name: copy.logs.export.csv })).closest("a")!.getAttribute("href")!;
  const u = new URL(href, "http://x"); expect(u.pathname).toBe("/api/logs/export"); expect(u.searchParams.getAll("cat")).toEqual(["auth"]);
});
it("shows the indexing banner until the index is ready", async () => {
  server.use(http.get("/api/logs/status", () => HttpResponse.json(logStatusFixture({ ready: false, pending_files: 3 }))));
  renderWithProviders(null, { me: ME, route: "/admin/logs" });
  expect(await screen.findByText(copy.logs.indexing(3))).toBeInTheDocument();
});
it("explains what is never collected", async () => {
  renderWithProviders(null, { me: ME, route: "/admin/logs" });
  await userEvent.click(await screen.findByRole("button", { name: copy.common.help }));
  expect(await screen.findByText(copy.logs.cmdLimitHelp)).toBeInTheDocument();
  expect(document.querySelector("main [data-anim]")).toBeNull();
});
```

`trackRequests()`가 경로만 돌려준다면(Plan 3) 이 Task에서 `urls(): string[]`(쿼리 포함)을 더합니다. `copy.common.help`가 없으면 `ko.ts`에 더합니다. `histogramFixture`의 `starts`는 13:00·13:10·…·13:50 KST입니다.

- [ ] **Step 3: 실패 확인** — Run: `pnpm test` → FAIL

- [ ] **Step 4: 구현** — 위 Interfaces대로. 표·히스토그램·타임라인에 `transition`/`animation`을 쓰지 않습니다.

- [ ] **Step 5: 통과 확인** — Run: `pnpm typecheck && pnpm lint && pnpm test && pnpm build && pnpm test:budget` → 통과

- [ ] **Step 6: Playwright 플러그인으로 확인** — 실제 백엔드(Plan 3 E2E 백엔드와 같은 방식, `--dev-otp-code`)에 로그를 만든 뒤 `/admin/logs`를 dark/light에서 **1920×1080, 1280×800, 1024×768, 800×600, 640×600**으로 열어 확인합니다: 페이지 가로 스크롤 없음(`scrollWidth <= innerWidth`), 필터 막대 줄바꿈, 히스토그램 드래그, 표가 자기 컨테이너에서만 스크롤, 상세 대화상자 닫기 가능, 타임라인 줄 배치, 키보드만으로 히스토그램 선택. 결과를 `docs/design/screens/logs.md` 점검 목록에 채웁니다(스크린샷은 커밋하지 않음, U30).

- [ ] **Step 7: Commit** — `git commit -m "feat(web): log viewer with drag-to-filter histogram, user facets, virtual table, per-user timeline and export"`

---

### Task 12: 웹 — 감사 로그 화면, 대시보드 로그인 실패 추이, 설정 보강

**Files:**
- Create: `docs/design/screens/audit.md`
- Create: `web/src/admin/audit/AuditPage.tsx`, `web/src/admin/audit/audit.test.tsx`, `web/src/admin/dashboard/LoginFailuresCard.tsx`, `web/src/admin/settings/ServiceSection.tsx`
- Modify: `web/src/admin/router.tsx`(`/admin/audit` → `AuditPage`), `web/src/admin/dashboard/DashboardPage.tsx`, `web/src/admin/dashboard/DashboardPage.test.tsx`, `web/src/admin/settings/RetentionSection.tsx`, `web/src/admin/settings/SettingsPage.tsx`, `web/src/admin/settings/settings.test.tsx`, `web/src/copy/ko.ts`

**Interfaces:**
- Consumes: Task 10·11(`VirtualTable`, `TimeRangePicker`, `UserFilter`, `LogHistogram`(`compact`)), Plan 3 설정 화면, Task 6 `delete_events`, Task 8 `/api/service`.
- Produces:
  - `AuditPage`(`view_audit`): 탭 `copy.audit.kinds.{admin,auth,all}`(URL `kind`, 기본 `admin`), 시간 범위(`TimeRangePicker` 재사용), 행위자(`UserFilter` 재사용 — 건수는 `/api/logs/users?cat=admin.audit|auth`), 결과 칩(`admin`: ok/denied/error, `auth`: ok/fail), 채널 선택(전체/로컬/원격), 키워드. `VirtualTable` 열 = 시각, 행위자(`user`), 채널(`data.channel` → `copy.channel`), IP, 작업(`event`), 대상(`admin`: `target`의 키=값 요약 120자, `auth`: `data.user_agent` 앞 60자 + Plan 4 `windows_user`가 있으면 그것), 결과(`copy.audit.results`, 아이콘 + 글자, 색만으로 구분하지 않음). 내보내기 = `auditExportUrl`. 640px 창 규칙은 Task 11과 같음.
  - `LoginFailuresCard`(대시보드의 `PlannedFeature planned_logs` 자리): `useLogHistogram({ from: 지금 올림 − 24시간, to: 지금 올림, cat: ["auth", "session"], event: ["login", "logon_failed"], outcome: ["fail"] }, "cat", 24)` → 두 계열(`auth` = `copy.dashboard.loginFailures.web`, `session` = `.rdp`)의 작은 막대(`LogHistogram compact`, 상호작용 없음), 합계, "로그에서 보기" 링크(`/admin/logs`에 같은 조건 + `range: "today"`가 아니라 `from`/`to`). 0건이면 `copy.dashboard.loginFailures.empty`.
  - `RetentionSection`: 확인 대화상자에 `delete_events`가 숫자면 `copy.settings.retentionDeleteEvents(n)`, 그리고 `copy.settings.retentionRunsSoon`("저장하면 몇 초 안에 정리가 실행됩니다").
  - `ServiceSection`(Local + `edit_global_settings`, 설정 화면의 부팅 시작 유형 옆): `useServiceStatus` → 설치 안 됨이면 `copy.settings.service.notInstalled`(개발 실행이면 `devMode`), 설치됐으면 `current(start_type)`, `in_sync`가 거짓이면 `mismatch`. Plan 3의 `startTypeNote`는 이것으로 바꿉니다.

- [ ] **Step 1: `frontend-design` 스킬로 감사 화면 설계** — 출력 `docs/design/screens/audit.md`(열·탭·결과 표현, 1920·1280·1024·800·640px 배치, Playwright 점검 목록).

- [ ] **Step 2: 실패하는 테스트 작성**

```tsx
// web/src/admin/audit/audit.test.tsx
const ME = meFixture("developer", "external");
it("lists admin actions with channel and result", async () => {
  server.use(http.get("/api/audit", () => HttpResponse.json(logPage([logItem({ cat: "admin.audit", event: "user_create", user: "a@x.com",
    outcome: "denied", client_ip: "127.0.0.1", data: { channel: "local", target: { email: "b@x.com" }, result: "denied" } })]))));
  renderWithProviders(null, { me: ME, route: "/admin/audit" });
  const row = (await screen.findByText("user_create")).closest("tr")!;
  expect(row).toHaveTextContent("a@x.com"); expect(row).toHaveTextContent(copy.channel.local);
  expect(row).toHaveTextContent(copy.audit.results.denied); expect(row).toHaveTextContent("email=b@x.com");
});
it("switching to the login tab requests kind=auth", async () => {
  const tracker = trackRequests();
  const { router } = renderWithProviders(null, { me: ME, route: "/admin/audit" });
  await userEvent.click(await screen.findByRole("tab", { name: copy.audit.kinds.auth }));
  await waitFor(() => expect(router.state.location.search).toMatchObject({ kind: "auth" }));
  await waitFor(() => expect(tracker.urls().some((u) => new URL(u, "http://x").searchParams.get("kind") === "auth")).toBe(true));
});
it("filters by result through chips", async () => {
  const { router } = renderWithProviders(null, { me: ME, route: "/admin/audit" });
  await userEvent.click(await screen.findByRole("button", { name: copy.audit.results.denied }));
  await waitFor(() => expect(router.state.location.search).toMatchObject({ result: ["denied"] }));
});
```

```tsx
// web/src/admin/dashboard/DashboardPage.test.tsx (기존 planned_logs 두 개 → 한 개도 없음으로 바꾸고 추가)
it("shows the login failure trend for web and RDP", async () => {
  server.use(http.get("/api/logs/histogram", ({ request }) => {
    const p = new URL(request.url).searchParams;
    expect(p.getAll("outcome")).toEqual(["fail"]); expect(p.getAll("cat").sort()).toEqual(["auth", "session"]);
    return HttpResponse.json(histogramFixture({ series: [{ key: "auth", counts: [1, 0, 2, 0, 0, 0] }, { key: "session", counts: [0, 0, 0, 0, 3, 0] }], total: 6 }));
  }));
  renderDashboard(meFixture("developer", "external"));
  const card = (await screen.findByRole("heading", { name: copy.dashboard.loginFailures.title })).closest("section")!;
  expect(card).toHaveTextContent(copy.dashboard.loginFailures.web); expect(card).toHaveTextContent(copy.dashboard.loginFailures.rdp);
  expect(within(card).getByRole("link", { name: copy.dashboard.loginFailures.openLogs }).getAttribute("href")).toContain("/admin/logs");
  expect(screen.queryByText(copy.deny.planned_logs)).toBeNull();
});
```

`renderDashboard`는 Plan 3 `DashboardPage.test.tsx`의 기존 헬퍼입니다.

```tsx
// web/src/admin/settings/settings.test.tsx (추가)
it("the retention confirm shows index rows and that cleanup runs soon", async () => {
  renderSettings(settingsFixture({ log_retention_days: 180 }), previewFixture({ days: 90, delete_files: 3, delete_bytes: 3_000_000,
    delete_from: "2026-05-09", delete_to: "2026-08-05", delete_events: 41_200 }));
  await setNumber(copy.settings.fields.log_retention_days, 90); await userEvent.click(screen.getByRole("button", { name: copy.common.save }));
  const dialog = await screen.findByRole("alertdialog");
  expect(dialog).toHaveTextContent(copy.settings.retentionDeleteEvents(41_200)); expect(dialog).toHaveTextContent(copy.settings.retentionRunsSoon);
});
it("shows the installed service start type and a mismatch", async () => {
  server.use(http.get("/api/service", () => HttpResponse.json(serviceStatusFixture({ installed: true, start_type: "auto", desired: "delayed-auto", in_sync: false }))));
  renderSettings(settingsFixture());
  expect(await screen.findByText(copy.settings.service.current("auto"))).toBeInTheDocument();
  expect(screen.getByText(copy.settings.service.mismatch)).toBeInTheDocument();
});
it("does not call /api/service on the external channel", async () => {
  const tracker = trackRequests();
  renderSettings(settingsFixture(), undefined, meFixture("admin", "external"));
  await screen.findByText(copy.deny.local_only);
  expect(tracker.paths()).not.toContain("/api/service");
});
```

`renderSettings(settings, preview?, me?)`는 Plan 3 `settings.test.tsx`의 헬퍼이며, 세 번째 인자가 없으면 이 Task에서 더합니다(기본 Local Admin).

- [ ] **Step 3: 실패 확인** — Run: `pnpm test` → FAIL

- [ ] **Step 4: 구현** — 위 Interfaces대로.

- [ ] **Step 5: 통과 확인** — Run: `pnpm typecheck && pnpm lint && pnpm test && pnpm build && pnpm test:budget` → 통과

- [ ] **Step 6: Playwright 플러그인으로 확인** — `/admin/audit`, 대시보드, 설정을 dark/light × 1920·1280·1024·800·640px(높이 600·800)로 열어 Task 11 Step 6과 같은 항목을 확인하고 `docs/design/screens/audit.md`에 채웁니다.

- [ ] **Step 7: Commit** — `git commit -m "feat(web): audit log viewer, dashboard login failure trend, retention index rows and service start-type status"`

---

### Task 13: 패키징 — 스파이크, `build.ps1`, 묶음 검증

**Files:**
- Create: `install/LAYOUT`, `install/build.ps1`, `install/runtime/python._pth.template`, `server/tests/test_bundle.py`
- Create (경로 A만): `install/pyinstaller/entry_monitor.py`, `install/pyinstaller/entry_agent.py`, `install/pyinstaller/mcp-monitor.spec`, `install/pyinstaller/mcp-agent.spec`; `server/pyproject.toml` `[dependency-groups] build`, `server/uv.lock`
- Modify: `.gitignore`(`/build/`), `web/package.json`(`"version": "1.0.0"`)

**Interfaces:**
- Produces:
  - **스파이크(W26)** — 저장소 밖 `%TEMP%\mcpmon-spike\`에서만 합니다:
    1. `spike.py`: `import sqlite3, ctypes, json; print("spike-ok", sqlite3.sqlite_version)`.
    2. Run: `uv run --no-project --python <server/.python-version> --with pyinstaller==6.22.3 python -m PyInstaller --onedir --name spike --distpath %TEMP%\mcpmon-spike\dist --workpath %TEMP%\mcpmon-spike\build --specpath %TEMP%\mcpmon-spike spike.py`
    3. Run: `%TEMP%\mcpmon-spike\dist\spike\spike.exe` → stdout가 `spike-ok`로 시작하고 종료 코드 0이면 **A(`pyinstaller`)**. 실행이 막히면(앱 제어/Smart App Control 차단 메시지, 0이 아닌 종료 코드) **B(`runtime`)**.
    4. B일 때 추가 확인: python.org `python-<ver>-embed-amd64.zip`을 `%TEMP%\mcpmon-spike\embed\`에 받아 풀고 `Get-AuthenticodeSignature python.exe`가 `Valid`·주체에 `Python Software Foundation`인지, `python.exe -c "print(1)"`이 되는지 확인. 이것도 막히면 **멈추고 보고**합니다(두 경로 모두 막힘).
    5. 결과를 `install/LAYOUT`(한 줄: `pyinstaller` 또는 `runtime`)에 쓰고, 보고서에 근거(명령, 출력, 오류 문구)를 적습니다. 스파이크 폴더는 지웁니다.
  - `install/build.ps1 [-Layout pyinstaller|runtime] [-Out <dir>] [-SkipAudit]`(기본 `-Layout` = `install/LAYOUT` 내용, `-Out` = `dist\mcp-monitor-<버전>`; 버전은 `server/app/__init__.py`의 `__version__`). 모든 외부 명령 뒤 `$LASTEXITCODE`를 검사하고 0이 아니면 `throw`.
    1. 보안 점검(§9.1): `server`에서 `uv run python -m pip_audit`(0건), `web`에서 `pnpm audit`(`No known vulnerabilities found`). `-SkipAudit`이 아니면 실패 시 중단.
    2. pyyaml 재확인(W27): `https://pypi.org/pypi/pyyaml/json`의 최신 버전 파일 중 `cp<버전>-win_amd64`가 있으면 경고 한 줄(`pyyaml now has a cp315 wheel: consider uvicorn[standard]`)만 출력(빌드는 계속).
    3. 웹: `web`에서 `pnpm build`.
    4. 공통: `$Out`을 지우고 다시 만든 뒤 `web\dist`를 `$Out\web`으로 복사(`.vite` 폴더 제외), `install\install.ps1`·`uninstall.ps1`·`audit-policy.ps1` → `$Out\install\`, `docs\ops\OPERATIONS.md` → `$Out\docs\`.
    5. **B(`runtime`)**: embeddable zip(`https://www.python.org/ftp/python/<ver>/python-<ver>-embed-amd64.zip`)을 `%TEMP%`에 받아 서명 확인(위 4번과 같은 조건, 아니면 중단) → `$Out\runtime`에 풀기 → 원래 `python3XX._pth`를 지우고 `install/runtime/python._pth.template`(줄: `python<XY>.zip`, `.`, `Lib\site-packages`, `..\server`, `..\agent`, `import site`)으로 `python<XY>._pth` 작성(W28: `PYTHONPATH`·현재 폴더를 무시) → `uv export --project server --frozen --no-dev --no-emit-project --format requirements-txt -o %TEMP%\mcpmon-req.txt` → `uv pip install --python $Out\runtime\python.exe --target $Out\runtime\Lib\site-packages --require-hashes --only-binary :all: -r %TEMP%\mcpmon-req.txt` → `server\app`을 `$Out\server\app`으로, `agent\mcp_agent`를 `$Out\agent\mcp_agent`로 복사(`__pycache__` 제외) → `$Out\mcp-monitor.cmd`(`@"%~dp0runtime\python.exe" -m app %*`).
    6. **A(`pyinstaller`)**: `server`에서 `uv run --group build python -m PyInstaller ..\install\pyinstaller\mcp-monitor.spec --distpath $Out\bin --workpath ..\build\pyinstaller --noconfirm`, 같은 방법으로 `mcp-agent.spec`. `mcp-monitor.spec`: `Analysis(["entry_monitor.py"], pathex=["<repo>/server"], hiddenimports=collect_submodules("uvicorn") + ["httptools", "websockets", "app.winsvc.service", "win32timezone", "win32serviceutil", "servicemanager"], excludes=["watchfiles", "tkinter"])`, `EXE(name="mcp-monitor", console=True)`, `COLLECT(name="monitor")`. `mcp-agent.spec`: `Analysis(["entry_agent.py"], pathex=["<repo>/agent"])`, `EXE(name="mcp-agent", console=False)`, `COLLECT(name="agent")`. 진입점: `from app.__main__ import main; raise SystemExit(main())` / `from mcp_agent.__main__ import main; raise SystemExit(main())`.
    7. `$Out\bundle.json` = `{"layout", "version", "python": <정확한 버전>, "built_at": <UTC ISO>, "commit": <git rev-parse HEAD>}`(UTF-8, BOM 없음).
    8. `$Out.zip`(Compress-Archive)과 `$Out.zip.sha256`(`Get-FileHash -Algorithm SHA256`).
  - `server/tests/test_bundle.py`(마커 `bundle`; 환경변수 `MCPMON_BUNDLE` = 묶음 폴더):

```python
# server/tests/test_bundle.py
import json
import os
import subprocess
import time
from pathlib import Path

import httpx
import pytest

from app import __version__
from tests.live import free_port

pytestmark = pytest.mark.bundle
B = Path(os.environ.get("MCPMON_BUNDLE", "missing"))


def meta():
    return json.loads((B / "bundle.json").read_text("utf-8"))


def monitor_cmd():
    return [str(B / "bin" / "monitor" / "mcp-monitor.exe")] if meta()["layout"] == "pyinstaller" \
        else [str(B / "runtime" / "python.exe"), "-m", "app"]


def agent_cmd():
    return [str(B / "bin" / "agent" / "mcp-agent.exe")] if meta()["layout"] == "pyinstaller" \
        else [str(B / "runtime" / "python.exe"), "-m", "mcp_agent"]


def test_bundle_metadata_and_files():
    m = meta()
    assert set(m) == {"layout", "version", "python", "built_at", "commit"} and m["version"] == __version__
    for rel in ("web/board.html", "web/admin.html", "install/install.ps1", "install/uninstall.ps1", "docs/OPERATIONS.md"):
        assert (B / rel).is_file(), rel


def test_bundle_version():
    p = subprocess.run([*monitor_cmd(), "--version"], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    assert p.returncode == 0 and p.stdout.strip() == f"mcp-monitor {__version__}"


def test_bundle_serves_the_built_board(tmp_path):
    lp, ep = free_port(), free_port(); assert lp != ep
    p = subprocess.Popen([*monitor_cmd(), "--root", str(tmp_path), "--local-port", str(lp), "--external-port", str(ep),
                          "--external-host", "127.0.0.1"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                if httpx.get(f"http://127.0.0.1:{lp}/api/channel", timeout=0.5).json()["channel"] == "local": break
            except httpx.HTTPError:
                pass
            assert p.poll() is None and time.monotonic() < deadline
            time.sleep(0.2)
        r = httpx.get(f"http://127.0.0.1:{ep}/")
        assert r.status_code == 200 and r.text == (B / "web" / "board.html").read_text("utf-8")
    finally:
        p.terminate(); p.wait(15)


def test_bundle_agent_starts():
    p = subprocess.run([*agent_cmd(), "--help"], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    assert p.returncode == 0 and "--server" in p.stdout


def test_bundle_ignores_pythonpath(tmp_path):
    if meta()["layout"] == "runtime":
        env = {**os.environ, "PYTHONPATH": str(tmp_path / "evil")}
        p = subprocess.run([str(B / "runtime" / "python.exe"), "-c", "import sys; print(sys.path)"], capture_output=True,
                           text=True, timeout=60, env=env, stdin=subprocess.DEVNULL)
        assert p.returncode == 0 and "evil" not in p.stdout and "server" in p.stdout
    else:
        assert (B / "bin" / "monitor" / "_internal").is_dir() and (B / "bin" / "agent" / "_internal").is_dir()
```

`mcp_agent`의 `--help`는 토큰 검사보다 먼저 argparse가 처리하므로 토큰 없이 0으로 끝납니다(Plan 4 `parse_args`가 그렇지 않다면 `--help`를 먼저 처리하도록 고칩니다).

- [ ] **Step 1: 스파이크** — 위 절차대로 실행하고 `install/LAYOUT`을 씁니다. A면 Run(server): `uv add --group build "pyinstaller==6.22.3"`(→ `pyproject.toml`·`uv.lock`), B면 빌드 의존성을 더하지 않습니다.

- [ ] **Step 2: 실패 확인** — Run(server): `$env:MCPMON_BUNDLE = "<repo>\dist\mcp-monitor-1.0.0"; uv run python -m pytest -m bundle -v` → FAIL(묶음 없음)

- [ ] **Step 3: 구현** — `install/build.ps1`과 선택한 경로의 파일을 위 Interfaces대로 작성합니다(선택하지 않은 경로의 파일은 만들지 않음).

- [ ] **Step 4: 빌드와 통과 확인** — Run(저장소 루트, Windows PowerShell): `powershell -NoProfile -ExecutionPolicy Bypass -File install\build.ps1` → 성공, `dist\mcp-monitor-1.0.0.zip`과 `.sha256` 생성. Run(server): `uv run python -m pytest -m bundle -v` → 5 passed. 빌드한 실행 파일이 Smart App Control에 막히면(스파이크와 결과가 다르면) 멈추고 보고합니다.

- [ ] **Step 5: Commit** — `git commit -m "build: deployment bundle (layout chosen by spike), security gates and bundle smoke tests"`

---

### Task 14: 설치·제거 스크립트 (`install.ps1`, `uninstall.ps1`, `audit-policy.ps1`)

**Files:**
- Create: `install/install.ps1`, `install/uninstall.ps1`, `install/audit-policy.ps1`, `server/tests/test_install_scripts.py`

**Interfaces:**
- Produces (모두 Windows PowerShell 5.1, `Set-StrictMode -Version Latest`, `$ErrorActionPreference = "Stop"`; 한 경로 "계획을 만든다 → `-DryRun`이면 JSON으로 출력하고 끝 / 아니면 실행", W29):
  - 계획의 단계 = `@{ id; cmd; args; ok = @(0) ; when = $null }`. `cmd`는 실행 파일 이름 또는 내부 동작 `(admin)`, `(check-os)`, `(mkdir)`, `(write-state)`, `(wait)`, `(remove)`. `-DryRun`은 `{"script", "version", "layout", "install_dir", "data_root", "service_mode": "create"|"update", "steps": [...]}`를 `ConvertTo-Json -Depth 6 -Compress`로 stdout에 한 번 출력하고 0으로 끝납니다(관리자 불필요, 아무것도 바꾸지 않음). 실행 모드는 단계를 차례로 실행하고 `ok`에 없는 종료 코드면 `"[실패] <id>: ..."`를 출력하고 종료 코드 1.
  - `install.ps1 [-Source <묶음 폴더, 기본 = 스크립트의 상위 폴더>] [-InstallDir "$env:ProgramFiles\MCP Monitor"] [-DataRoot "$env:ProgramData\MCP Monitor"] [-OpenFirewall] [-SkipAuditPolicy] [-LocalPort 8700] [-ExternalPort 8701] [-DryRun]`. `-Source`의 `bundle.json`이 없거나 `-Source`가 `-InstallDir`와 같으면 오류(종료 2). 단계 id(이 순서 그대로):
    1. `require_admin` `(admin)`: 관리자가 아니면 `"관리자 권한(Administrator)으로 PowerShell을 열고 다시 실행하세요."`를 출력하고 **어떤 변경도 하기 전에** 종료 1.
    2. `check_os` `(check-os)`: `Win32_OperatingSystem.Caption`이 Home이면 경고(RDP 호스트가 아니라 세션 수집은 동작하지 않음)만 하고 계속.
    3. `stop_existing` `sc.exe stop mcp-monitor`, `when = "service_exists"`, `ok = @(0, 1062)` 후 정지 대기.
    4. `copy_bundle` `robocopy <Source> <InstallDir> /MIR /XD logs data scripts /NFL /NDL /NJH /NJS /NP`, `ok = 0..7`.
    5. `create_dirs` `(mkdir)` `<DataRoot>\logs`, `\data`, `\scripts`.
    6. `acl_data` `icacls <DataRoot> /inheritance:r /grant:r *S-1-5-18:(OI)(CI)F *S-1-5-32-544:(OI)(CI)F`(이름 대신 SID — 한국어 Windows에서도 같음, W30). 7. `acl_children` `icacls <DataRoot>\* /reset /T /C /Q`. 8. `acl_owner` `icacls <DataRoot> /setowner *S-1-5-32-544 /T /C /Q`.
    9. `audit_backup` `auditpol /backup /file:<DataRoot>\data\auditpol-backup.csv`, `when = "no_backup_yet"`(한 번만 — 재설치가 원래 정책 백업을 덮지 않게).
    10. `audit_policy_success` `auditpol /set /subcategory:{0CCE922B-69AE-11D9-BED3-505054503030},{0CCE9215-69AE-11D9-BED3-505054503030},{0CCE9216-69AE-11D9-BED3-505054503030},{0CCE921C-69AE-11D9-BED3-505054503030},{0CCE922F-69AE-11D9-BED3-505054503030} /success:enable`(프로세스 만들기, 로그온, 로그오프, 기타 로그온/로그오프, 감사 정책 변경 — GUID라 언어와 무관). 11. `audit_policy_failure` `auditpol /set /subcategory:{0CCE9215-...},{0CCE921C-...} /failure:enable`.
    12. `registry_cmdline` `reg add HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System\Audit /v ProcessCreationIncludeCmdLine_Enabled /t REG_DWORD /d 1 /f`. 13. `registry_scriptblock` `reg add HKLM\SOFTWARE\Policies\Microsoft\Windows\PowerShell\ScriptBlockLogging /v EnableScriptBlockLogging /t REG_DWORD /d 1 /f`.
    14. `security_log_size` `wevtutil sl Security /ms:268435456`. 15. `powershell_log_size` `wevtutil sl Microsoft-Windows-PowerShell/Operational /ms:67108864`.
    (`-SkipAuditPolicy`면 9–15를 뺍니다.)
    16. `service_install` `sc.exe create|config mcp-monitor binPath= "<명령>" start= delayed-auto DisplayName= "MCP Monitor" obj= LocalSystem`(서비스가 있으면 `config`, `service_mode = "update"`). `<명령>` = A: `"<InstallDir>\bin\monitor\mcp-monitor.exe" service --root "<DataRoot>" --local-port <LP> --external-port <EP>`, B: `"<InstallDir>\runtime\python.exe" -m app service --root "<DataRoot>" --local-port <LP> --external-port <EP>`. 시작 유형은 항상 `delayed-auto`로 만들고 이후에는 서비스가 설정값으로 맞춥니다(W25).
    17. `service_description` `sc.exe description mcp-monitor "<DESCRIPTION>"`. 18. `service_failure` `sc.exe failure mcp-monitor reset= 86400 actions= restart/5000/restart/10000/restart/60000`. 19. `service_failureflag` `sc.exe failureflag mcp-monitor 1`.
    20. `firewall`(`-OpenFirewall`일 때만) `netsh advfirewall firewall add rule name="MCP Monitor (<EP>)" dir=in action=allow protocol=TCP localport=<EP> profile=domain,private`(spec §2 #6: 기본 꺼짐).
    21. `install_state` `(write-state)` `<DataRoot>\data\install-state.json` = `{installed_at, version, layout, install_dir, data_root, local_port, external_port, firewall: bool, registry_before: {"<경로>\<값>": <이전 값 또는 null>}, audit_backup}`(레지스트리 이전 값은 계획을 만들 때 읽음).
    22. `service_start` `sc.exe start mcp-monitor`, `ok = @(0, 1056)`. 23. `wait_ready` `(wait)` `http://127.0.0.1:<LP>/api/channel`를 30초까지 1초마다 → 성공하면 `"설치 완료: http://127.0.0.1:<LP>/admin/setup 에서 첫 Admin 계정을 만드세요."`.
  - `uninstall.ps1 [-InstallDir ...] [-DataRoot ...] [-RemoveData] [-RestoreAuditPolicy] [-DryRun]`. 단계 id: `require_admin`, `stop_service`(`sc.exe stop`, `ok = @(0, 1060, 1062)`), `delete_service`(`sc.exe delete mcp-monitor`, `ok = @(0, 1060)`), `firewall_delete`(`netsh advfirewall firewall delete rule name="MCP Monitor (<EP>)"`, `ok = @(0, 1)`; `EP`는 상태 파일, 없으면 8701), [`-RestoreAuditPolicy`: `restore_audit_policy`(`auditpol /restore /file:<백업>`), `restore_registry`(상태 파일의 이전 값으로 `reg add`/`reg delete`)], `remove_install_dir` `(remove)`, [`-RemoveData`: `remove_data` `(remove)` `<DataRoot>`(로그·설정·스크립트·`data\collector-state.json` 포함), `remove_edge_profiles` `(remove)` `C:\Users\*\AppData\Local\mcp-monitor`(Plan 4 고지 창 Edge 프로필)]. 기본은 데이터를 남깁니다(W31).
  - `audit-policy.ps1 [-Enable | -Restore <백업 파일>] [-DryRun]`: install의 9–15 단계(또는 복원 단계)만 따로 실행하는 같은 구조의 스크립트(Plan 4 실기기 점검표 준비 단계에서 씀).

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_install_scripts.py
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
INSTALL = REPO / "install"
PS = [str(Path(os.environ["SystemRoot"]) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"),
      "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass"]
GUID = re.compile(r"\{0CCE92[0-9A-F]{2}-69AE-11D9-BED3-505054503030\}")


def ps(*args, timeout=120):
    return subprocess.run([*PS, *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, stdin=subprocess.DEVNULL)


def dry(script, *args):
    p = ps("-File", str(INSTALL / script), "-DryRun", *args)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


@pytest.fixture
def bundle(tmp_path):
    (tmp_path / "bundle.json").write_text(json.dumps({"layout": "runtime", "version": "1.0.0", "python": "3.15.2",
                                                      "built_at": "x", "commit": "y"}), "utf-8")
    (tmp_path / "runtime").mkdir(); (tmp_path / "runtime" / "python.exe").write_bytes(b"")
    return tmp_path


def step(plan, sid):
    return next(s for s in plan["steps"] if s["id"] == sid)


@pytest.mark.parametrize("name", ["install.ps1", "uninstall.ps1", "audit-policy.ps1", "build.ps1"])
def test_scripts_parse(name):
    p = ps("-Command", f"$e = $null; [void][System.Management.Automation.Language.Parser]::ParseFile('{INSTALL / name}', [ref]$null, [ref]$e); $e.Count")
    assert p.returncode == 0 and p.stdout.strip() == "0", p.stdout + p.stderr


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


def test_install_plan_open_firewall_and_skip_audit(bundle, tmp_path):
    plan = dry("install.ps1", "-Source", str(bundle), "-InstallDir", str(tmp_path / "i"), "-DataRoot", str(tmp_path / "d"),
               "-OpenFirewall", "-SkipAuditPolicy", "-ExternalPort", "9701")
    ids = [s["id"] for s in plan["steps"]]
    assert "audit_policy_success" not in ids and "registry_cmdline" not in ids
    assert step(plan, "firewall")["args"] == ["advfirewall", "firewall", "add", "rule", "name=MCP Monitor (9701)", "dir=in",
                                              "action=allow", "protocol=TCP", "localport=9701", "profile=domain,private"]
    assert ids.index("firewall") == ids.index("service_failureflag") + 1


def test_install_refuses_without_admin(bundle, tmp_path):
    p = ps("-File", str(INSTALL / "install.ps1"), "-Source", str(bundle), "-InstallDir", str(tmp_path / "i"), "-DataRoot", str(tmp_path / "d"))
    assert p.returncode == 1 and "관리자 권한" in (p.stdout + p.stderr)
    assert not (tmp_path / "i").exists() and not (tmp_path / "d").exists()


def test_uninstall_plan_keeps_data_by_default(tmp_path):
    base = ["-InstallDir", str(tmp_path / "i"), "-DataRoot", str(tmp_path / "d")]
    assert [s["id"] for s in dry("uninstall.ps1", *base)["steps"]] == [
        "require_admin", "stop_service", "delete_service", "firewall_delete", "remove_install_dir"]
    full = [s["id"] for s in dry("uninstall.ps1", *base, "-RemoveData", "-RestoreAuditPolicy")["steps"]]
    assert full == ["require_admin", "stop_service", "delete_service", "firewall_delete", "restore_audit_policy",
                    "restore_registry", "remove_install_dir", "remove_data", "remove_edge_profiles"]


def test_audit_policy_script_plan():
    plan = dry("audit-policy.ps1", "-Enable")
    assert [s["id"] for s in plan["steps"]][1:] == ["audit_backup", "audit_policy_success", "audit_policy_failure",
                                                    "registry_cmdline", "registry_scriptblock", "security_log_size", "powershell_log_size"]
```

이 PC는 관리자가 아니므로 `test_install_refuses_without_admin`은 실제 실행이 첫 단계에서 멈추는 것을 확인합니다. 관리자 권한 PowerShell에서 이 테스트를 돌리지 않습니다(Global Constraints).

- [ ] **Step 2: 실패 확인** — Run: `uv run python -m pytest tests/test_install_scripts.py -v` → FAIL

- [ ] **Step 3: 구현** — 위 Interfaces대로. 스크립트 파일은 UTF-8 **BOM 포함**으로 저장합니다(Windows PowerShell 5.1이 한국어 문자열을 올바르게 읽도록).

- [ ] **Step 4: 통과 확인** — Run: `uv run python -m pytest tests/test_install_scripts.py -v` → 통과. 묶음을 다시 빌드(Task 13 Step 4)하고 `uv run python -m pytest -m bundle -q` → 통과.

- [ ] **Step 5: Commit** — `git commit -m "feat: install, uninstall and audit-policy scripts with a dry-run plan (service, ACL by SID, audit policy by GUID, opt-in firewall)"`

---

### Task 15: E2E·접근성 — 로그·감사·보존 시연과 창 크기

**Files:**
- Create: `web/e2e/logs.spec.ts`, `web/e2e/audit.spec.ts`, `web/e2e/retention.spec.ts`, `web/e2e/window-sizes.spec.ts`
- Modify: `web/e2e/backend.ts`(시드 전에 오래된 로그 파일 작성), `web/e2e/a11y.spec.ts`, `web/e2e/visual.spec.ts`

**Interfaces:**
- Consumes: Plan 3 E2E 하네스(`state`, `loginAs`, `copy`), Task 5·6·10–12.
- Produces:
  - `backend.ts`: 백엔드를 띄우기 **전에** `<root>/logs/<오늘 − 400일>.jsonl`, `<오늘 − 30일>.jsonl`에 `system` 줄 각 3개를 씁니다(KST 날짜). 상태 파일에 `oldLogDays: [string, string]`.
  - 모든 로그 단언은 색인 지연(≈1초)을 `expect.poll`/`toBeVisible({ timeout: 10_000 })`로 기다립니다(대기 시간을 늘려 통과시키지 않음 — Plan 3 규칙).

```ts
// web/e2e/logs.spec.ts
test("finds the bootstrap audit line by category on the external channel", async ({ page, state, loginAs }) => {
  await loginAs(page, "dev", "external");
  await page.goto(`${state.externalUrl}/admin/logs?range=today`);
  await page.getByRole("button", { name: copy.logs.cats["admin.audit"] }).click();
  await expect(page.getByRole("row").filter({ hasText: "bootstrap" })).toBeVisible({ timeout: 10_000 });
});
test("keyword search narrows rows", async ({ page, state, loginAs }) => {
  await loginAs(page, "admin", "local");
  await page.goto(`${state.localUrl}/admin/logs?range=today`);
  await page.getByLabel(copy.logs.keyword).fill("calculator");
  await expect(page).toHaveURL(/q=/);
  const rows = page.getByRole("row").filter({ hasText: "calculator" });
  await expect(rows.first()).toBeVisible({ timeout: 10_000 });
});
test("dragging the histogram sets a custom range in the URL", async ({ page, state, loginAs }) => {
  await loginAs(page, "admin", "local");
  await page.goto(`${state.localUrl}/admin/logs?range=1h`);
  const box = (await page.getByTestId("log-histogram").boundingBox())!;
  await page.mouse.move(box.x + box.width * 0.2, box.y + box.height / 2); await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.6, box.y + box.height / 2, { steps: 5 }); await page.mouse.up();
  await expect(page).toHaveURL(/from=/); await expect(page).not.toHaveURL(/range=/);
});
test("keyboard-only histogram selection", async ({ page, state, loginAs }) => {
  await loginAs(page, "admin", "local");
  await page.goto(`${state.localUrl}/admin/logs?range=1h`);
  await page.getByTestId("log-histogram").focus();
  await page.keyboard.press("ArrowRight"); await page.keyboard.press("Shift+ArrowRight"); await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/from=/);
});
test("export CSV downloads a file with the header", async ({ page, state, loginAs }) => {
  await loginAs(page, "admin", "local");
  await page.goto(`${state.localUrl}/admin/logs?range=today`);
  await page.getByRole("button", { name: copy.logs.export.menu }).click();
  const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("menuitem", { name: copy.logs.export.csv }).click()]);
  const text = await (await import("node:fs/promises")).readFile((await download.path())!, "utf-8");
  expect(text.startsWith("\ufeffts,cat,event,user,session_id,client_ip,client_name,outcome,summary")).toBe(true);
});
test("anonymous visitors are sent to login", async ({ page, state }) => {
  await page.goto(`${state.externalUrl}/admin/logs`);
  await expect(page).toHaveURL(/\/admin\/login\?redirect=/);
});
```

```ts
// web/e2e/audit.spec.ts
test("audit page lists the admin's actions with channel and result", async ({ page, state, loginAs }) => {
  await loginAs(page, "admin", "local");
  await page.goto(`${state.localUrl}/admin/audit?range=today`);
  const row = page.getByRole("row").filter({ hasText: "user_create" }).first();
  await expect(row).toContainText(copy.channel.local, { timeout: 10_000 }); await expect(row).toContainText(copy.audit.results.ok);
  await page.getByRole("tab", { name: copy.audit.kinds.auth }).click();
  await expect(page.getByRole("row").filter({ hasText: "login" }).first()).toBeVisible({ timeout: 10_000 });
});
```

```ts
// web/e2e/retention.spec.ts
test("lowering retention previews and then purges", async ({ page, state, loginAs }) => {
  await loginAs(page, "admin", "local");
  await page.goto(`${state.localUrl}/admin/settings`);
  await page.getByLabel(copy.settings.fields.log_compress_after_days).fill("30");
  await page.getByLabel(copy.settings.fields.log_retention_days).fill("60");
  await page.getByRole("button", { name: copy.common.save }).click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toContainText(state.oldLogDays[0]); await expect(dialog).toContainText(copy.settings.retentionRunsSoon);
  await dialog.getByRole("button", { name: copy.settings.confirmDelete }).click();
  await expect.poll(async () => {
    const st = await (await page.request.get(`${state.localUrl}/api/logs/status`)).json();
    return st.oldest_day;
  }, { timeout: 20_000 }).not.toBe(state.oldLogDays[0]);
  // restore the default for later specs
  await page.getByLabel(copy.settings.fields.log_retention_days).fill("180");
  await page.getByRole("button", { name: copy.common.save }).click();
  await expect(page.getByRole("alertdialog")).toHaveCount(0);
});
```

```ts
// web/e2e/window-sizes.spec.ts
const WIDTHS = [1920, 1280, 1024, 800, 640] as const;
const PAGES = ["/admin/logs?range=today", "/admin/logs?range=today&view=timeline", "/admin/audit?range=today", "/admin", "/admin/settings"];
for (const width of WIDTHS)
  test(`no horizontal page scroll at ${width}`, async ({ page, state, loginAs }) => {
    await page.setViewportSize({ width, height: width === 640 ? 600 : 800 });
    await loginAs(page, "admin", "local");
    for (const path of PAGES) {
      await page.goto(`${state.localUrl}${path}`); await page.waitForLoadState("networkidle");
      const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(over, `${path} at ${width}px`).toBeLessThanOrEqual(0);
    }
  });
test("the log table scrolls inside its own container at 640", async ({ page, state, loginAs }) => {
  await page.setViewportSize({ width: 640, height: 600 });
  await loginAs(page, "admin", "local");
  await page.goto(`${state.localUrl}/admin/logs?range=today`);
  const table = page.getByRole("table", { name: copy.logs.title });
  const scroller = table.locator("xpath=ancestor::*[@data-scroll-container][1]");
  await expect(scroller).toBeVisible();
  expect(await scroller.evaluate((el) => getComputedStyle(el).overflowX)).toMatch(/auto|scroll/);
  await table.getByRole("row").nth(1).focus(); await page.keyboard.press("Enter");
  await expect(page.getByRole("dialog", { name: copy.logs.detail }).getByRole("button", { name: copy.common.close })).toBeInViewport();
});
```

`VirtualTable`의 스크롤 컨테이너에 `data-scroll-container` 속성을 둡니다(Task 11에서 빠졌다면 이 Task에서 더함). `copy.common.close`가 없으면 더합니다.

  - `a11y.spec.ts`의 경로 목록에 `/admin/logs?range=today`, `/admin/logs?range=today&view=timeline`, `/admin/audit?range=today`를 더하고, 같은 axe 검사를 **640×600** 창에서도 한 번 더 돌리는 매개변수를 더합니다. `visual.spec.ts`에 `logs`, `audit` 기준 이미지(1280px, dark/light, `[data-volatile]` 마스크 — 로그 시각·건수·히스토그램에 `data-volatile`).

- [ ] **Step 1: 실패하는 테스트 작성** — 위 spec 파일들.

- [ ] **Step 2: 실패 확인** — Run(web): `pnpm build && pnpm e2e --project chromium-dark logs.spec.ts audit.spec.ts retention.spec.ts window-sizes.spec.ts` → FAIL

- [ ] **Step 3: 구현** — 위 Interfaces대로 `backend.ts`를 고치고, 실패가 화면 코드 때문이면 해당 Task 코드를 고칩니다. 새 기준 이미지는 `--update-snapshots`로 만든 뒤 Read 도구로 하나씩 열어 확인합니다.

- [ ] **Step 4: 통과 확인** — Run(web): `pnpm e2e` → 전체 통과, 콘솔 오류 0

- [ ] **Step 5: Commit** — `git commit -m "test(web): E2E for log viewer, audit log, retention purge and window sizes down to 640x600"`

---

### Task 16: 운영 문서, 실기기 점검표, 성능 기록, 리뷰, 스펙 v0.8, 최종 검증

**Files:**
- Create: `docs/ops/OPERATIONS.md`, `docs/verification/win11-pro-p6-p7.md`, `docs/verification/perf-p6.md`, `docs/design/a11y-review-p5.md`, `docs/design/critique-p5.md`
- Modify: `docs/PLAN.md`, `docs/superpowers/plans/carry-forward.md`, 리뷰에서 고친 `web/src/**`·`server/app/**`

- [ ] **Step 1: 운영 문서 `docs/ops/OPERATIONS.md`(한국어)** — 절: ① 구성 요약(설치 폴더, 데이터 루트, 두 포트, 서비스 이름 `mcp-monitor` — 기본 서비스 `McpManagementService`와 다름) ② 설치(`install.ps1` 매개변수 표, 첫 Admin 만들기, `-OpenFirewall`은 기본 꺼짐, Smart App Control이 켜진 PC에서의 주의(W26)) ③ 업그레이드(같은 스크립트 재실행, 데이터 유지, 감사 정책 백업은 첫 설치 것 유지) ④ 제거(`uninstall.ps1`, `-RemoveData`, `-RestoreAuditPolicy`) ⑤ 서비스 운영(시작 유형은 웹 설정이 기준, 복구 동작, 종료 코드 3/4/5의 뜻과 조치, 이벤트 뷰어의 오류 위치) ⑥ 로그(파일 구조, 압축, 보존 정리 시각 03:30 KST, 보존 기간을 줄이면 몇 초 안에 정리, `python -m app reindex`/`mcp-monitor.cmd reindex`로 색인 다시 만들기 — 서비스 정지 필요) ⑦ 백업·복원(서비스 정지 → `data\config.db`·`scripts\`·`logs\` 복사; `index.db`는 백업 불필요) ⑧ 보안(8700 앞에 리버스 프록시 금지 §4.4, 8701은 HTTP 평문 §2 #5, RDP 계정은 표준 사용자 §14, 관리자 권한 사용자는 기록을 끌 수 있으며 우회 탐지로만 남음 §2 #4, 데이터 루트 ACL) ⑨ 알려진 동작(서비스 재시작 시 FAILED·자동 조치 횟수 초기화 W17, 스크립트 저장 중 디스크 오류 뒤 첫 실행이 해시 불일치로 막히면 소유자가 다시 저장 W19, cmd 내부 명령 미수집 §2 #7) ⑩ 문제 해결 표.

- [ ] **Step 2: 실기기 점검표 `docs/verification/win11-pro-p6-p7.md`** — 모든 결과 칸 `대기`(W38). 준비(깨끗한 Win 11 Pro VM, 관리자 계정, RDP용 표준 사용자 `hong`, 묶음 zip과 sha256 확인). 항목(절차 / 기대 / 결과 / 비고):
  - P7-1 관리자 PowerShell에서 `install.ps1` **한 번** 실행 → 23단계 성공, `http://127.0.0.1:8700/admin/setup` 열림 — §11 P7 완료 기준
  - P7-2 재부팅 → 로그인 없이 지연 자동 시작, 보드 표시(8701, 다른 PC에서는 `-OpenFirewall` 후)
  - P7-3 `sc.exe qc mcp-monitor`·`sc.exe qfailure mcp-monitor` 값 확인, 웹에서 시작 유형을 `수동`으로 바꾸면 `sc.exe qc`가 `DEMAND_START`
  - P7-4 `icacls "C:\ProgramData\MCP Monitor"` → SYSTEM·Administrators만, `hong`으로 `logs` 열기 거부
  - P7-5 `auditpol /get /category:*`(GUID로 확인), 레지스트리 두 값, Security 로그 최대 크기
  - P7-6 작업 관리자에서 서비스 프로세스 강제 종료 → 5초 뒤 재시작(복구 동작)
  - P7-7 RDP `hong` 접속 → 세션 서비스 알림으로 2초 안 보드 표시(Plan 4 V6 + Task 8 `nudge`)
  - P7-8 Smart App Control 켜진 상태에서 실행 파일이 막히지 않음(막히면 W26 결과와 대조)
  - P7-9 업그레이드(새 묶음으로 `install.ps1` 재실행) → 데이터·설정·스크립트 유지, 감사 백업 파일 유지
  - P7-10 `uninstall.ps1` → 서비스·방화벽 규칙·설치 폴더 삭제, 데이터 유지; `-RemoveData -RestoreAuditPolicy` → 데이터·Edge 프로필 삭제, 감사 정책 원복
  - P6-1 실제 수집 로그로 로그 화면 필터·히스토그램 드래그·내보내기, 감사 화면, 로그인 실패 추이(잘못된 RDP 암호 시도 포함)
  - P6-2 보존 기간 7일로 낮춤 → 미리보기 → 확인 → 몇 초 안에 정리, `retention.run`·`retention_purge` 기록, `log_file_removed` 우회 탐지 없음
  - 그리고 Plan 4 점검표(`win11-pro-p4-p5.md`)를 **서비스 설치 상태**로 다시 수행한다는 안내.

- [ ] **Step 3: 성능 기록 `docs/verification/perf-p6.md`** — Run(server): `uv run python -m pytest -m perf -q` → 통과. `server/.cache/perf-results.json`의 값으로 표(S1–S10 중앙값 ms, 색인 속도 줄/초, 정리 중 p95, 정리 행 수)와 측정 환경(CPU, 디스크, Python·SQLite 버전, 데이터 분포 = Task 4 생성 규칙)을 적습니다. "키워드가 많은 행에 맞으면(예: 전체의 30%) 300ms를 넘을 수 있음"이라는 한계(W9)를 측정값과 함께 적습니다(S4 변형으로 한 번 측정해 기록, 테스트로 고정하지 않음).

- [ ] **Step 4: 리뷰 스킬** — `design:accessibility-review`(새 화면: 로그, 타임라인, 감사, 대시보드 카드, 설정 추가분; 키보드 경로·`aria-live`·대비·640×600 창 확대 200%) → `docs/design/a11y-review-p5.md`. `design:design-critique`(Task 15 기준 이미지 + 640px 확인 결과) → `docs/design/critique-p5.md`. `audit-suite:vercel-react-best-practices`와 `audit-suite:web-design-guidelines`로 로그 화면 코드를 점검(이제 설치돼 있음, W40). 고칠 가치가 있는 항목을 고치고 해당 테스트를 추가·갱신합니다.

- [ ] **Step 5: 문서 정리**
  - `docs/PLAN.md`: 버전 v0.8, 변경 이력 한 행: `v0.8 | 구현 정합 (P6–P7): data/index.db(FTS5 unicode61 접두사 검색, 분·시간 롤업, 파생 데이터라 스키마가 다르면 다시 만듦), GET /api/logs·/histogram·/users·/status·/export, GET /api/audit[/export], 조회·내보내기 감사(logs_view 60초 제한), 보존 정리 03:30 KST + 보존 기간을 줄이면 즉시(미리보기와 같은 retention_cutoff, 압축은 최소 2일·색인 완료 파일만), DB 표 정리(auth_sessions·otp_*·mcp_actions·mcp_transitions·rdp_*·notice_displays), GET /api/settings/retention/preview delete_events, GET /api/service, 서비스 호스트(service 하위 명령, SESSIONCHANGE→nudge, 종료 코드 3/4/5, data/.lock), 배포 묶음(<A 또는 B>, bundle.json), install.ps1/uninstall.ps1/audit-policy.ps1(SID·GUID, -DryRun), 버전 1.0.0`. §9.2 패키징 행을 스파이크 결과대로 고칩니다(B면 "python.org embeddable(PSF 서명) + 묶음 런타임, Smart App Control 때문"). §8 표에 새 엔드포인트 행. §10 디렉터리 구조에 `server/app/{bundle.py,rootlock.py,winsvc/}`, `install/build.ps1`, `docs/ops/`. 상태 줄을 "P0–P7 구현 완료(Win 11 Pro 실기기 확인 대기: `docs/verification/win11-pro-p4-p5.md`, `win11-pro-p6-p7.md`)"로.
  - `carry-forward.md`: "Plan 5" 두 절과 Plan 3·4가 더한 Plan 5 항목에 체크하고 줄 끝에 `(Plan 5 Task N)` 또는 `(Plan 5 W<n>: 추후/유지)`(배정은 이 문서 맨 위 표). "Later"의 처리한 항목(`--open-meteo` 테스트, `MCP_ACTOR`)에도 체크. 새 절 "After Plan 5 (추후)": 알림 채널(§14, `Alert` 효과·우회 탐지), 실제 OTP 공급자와 발송 비동기화, 외부 채널 HTTPS(§14), 설정 백업·가져오기(§14), 로그 해시 체인(§5.6 선택), syslog/SIEM·GeoIP(§14 선택), legalnotice(§5.5 선택), 고지 창 진짜 모달(Plan 4 V3), WTS 알림 창(Plan 4 V6), 코드 서명(W26), E501 적용, `_apply` 거절의 엔진 측 취소(W18), 키워드가 넓을 때의 질의 속도(W9), 그리고 두 실기기 점검표의 `대기` 항목 전체.

- [ ] **Step 6: 전체 검증**

  Run (server): `uv run python -m pytest -q` → 통과. `-m integration` → 통과. `-m winlive` → 통과. `-m perf` → 통과. `-m bundle`(`MCPMON_BUNDLE` 설정, 최신 빌드) → 통과. `uv run python -m ruff check app tests` → 0건. `uv run python -m mypy` → 0건. `uv run python -m pip_audit` → 0건.
  Run (agent): `uv run python -m pytest -q` → 통과. Run (dummy-mcps): `uv run python -m pytest -q` → 통과.
  Run (web): `pnpm typecheck` → 0 errors. `pnpm lint` → 0 problems. `pnpm test` → 통과. `pnpm build` → 성공. `pnpm test:budget` → 통과. `pnpm e2e` → 통과. `pnpm audit` → `No known vulnerabilities found`.
  Run (install): `uv run python -m pytest tests/test_install_scripts.py -q`(server) → 통과.

- [ ] **Step 7: Commit** — `git commit -m "docs: operations guide, Win 11 Pro P6/P7 checklist, P6 performance record, spec v0.8 and final carry-forward"`

---

## 부록 A: 결정 사항 (이 계획의 Ruling W1–W41)

| # | 결정 | 이유 | 틀렸을 때 비용 |
|---|---|---|---|
| W1 | Plan 4가 끝난(전체 리뷰 수정 포함) 커밋에서 `feat/plan5-logs-packaging`으로 시작합니다. Plan 3·4 문서와 실제 코드의 이름이 다르면 코드를 따르고 이름 대응을 보고합니다. | Plan 3은 구현 중, Plan 4는 실행 전이라 이 계획은 두 문서의 인터페이스를 기준으로 썼습니다. | 이름 맞추기 수정. |
| W2 | 조회용 색인은 `data/index.db` **별도 파일**, 파생 데이터입니다. 스키마 버전이 다르면(작든 크든) 지우고 JSONL에서 다시 만듭니다. `synchronous=NORMAL`. | spec §5.6 "JSONL에서 언제든 다시 만들 수 있습니다". `config.db`와 쓰기 경합을 나누고, 업그레이드를 마이그레이션 없이 처리합니다. | 다시 만드는 시간(180일 ≈ 수 분); 그동안 조회는 부분 결과 + "색인 중". |
| W3 | FTS5 `unicode61 remove_diacritics 2`, `contentless_delete=1`. 검색어는 공백으로 나눈 낱말마다 `"낱말"*`(접두사), 모두 AND, 최대 10낱말. trigram은 쓰지 않습니다. | 색인 크기가 trigram의 약 1/3이고, 한국어 조사("로그를")와 하이픈 명령("Stop-Process")은 접두사 검색으로 찾힙니다(이 PC에서 확인). | 낱말 가운데 부분 검색("otepad")이 안 됨. 바꾸려면 스키마 버전을 올려 다시 색인. |
| W4 | 색인에 원문 `raw`를 그대로 둡니다(파일 오프셋 참조 아님). | 30일 뒤 `.gz`로 압축되면 임의 위치 읽기가 불가능합니다. | 디스크가 원본의 약 2배. |
| W5 | 중복 제거 키 = `(day, blake2b-8(원문 줄))`. | carry-forward: 이틀에 걸친 재시도가 같은 줄을 다시 씁니다. 같은 밀리초의 완전히 같은 두 줄은 하나로 합쳐집니다. | 진짜로 같은 두 이벤트가 한 건으로 셈(밀리초·모든 필드 동일일 때만). |
| W6 | 정규화 열: `user` = `user` → `actor_email` → `email` → `actor`(`system` 제외), `NOCASE`; `event` = `event` 또는 `admin.audit`의 `action`; `outcome` = auth `ok`, `admin.audit` `result`, `mcp.action` `status`, `logon_failed`; `client_ip` = `client_ip` → `ip`. | §6.4 "사용자별"에 Windows 계정(행동 로그)과 웹 계정(감사·인증)이 함께 나와야 하고, Windows 계정은 대소문자를 구분하지 않습니다. | 사용자 필터에서 두 종류가 섞여 보임(목록에 그대로 표시). |
| W7 | 목록은 최신순 키셋 커서 `(ts_ms, id)`, 페이지 200(최대 1,000). 여러 값 필터는 값마다 인덱스로 읽어 병합(fan-out + merge), 구동 순서 세션 → IP → 사용자 → 카테고리 → 시간. | 여러 사용자·카테고리 필터에서 정렬용 임시 B-tree를 피해야 100만 건 < 300ms를 지킵니다. | 질의 수가 값 수만큼 늘어남(최대 50 + 12). |
| W8 | 히스토그램·사용자 건수는 조건이 시간·카테고리·사용자뿐이고 경계가 분 단위면 분/시간 롤업에서, 아니면 행을 셉니다. 막대 크기는 정해진 사다리, KST 경계로 정렬. UI는 항상 분 단위 경계를 보냅니다. | 30일 전체 히스토그램을 행 스캔으로 세면 수백 ms입니다. 분 경계로 맞추면 롤업과 스캔 결과가 정확히 같습니다(테스트). | 분 경계가 아닌 API 직접 호출은 느린 스캔 경로. |
| W9 | 성능 기준(§11 P6)의 정의: Task 4 생성 규칙의 100만 건/30일, 시나리오 S1–S10, 이 PC에서 5회 중앙값 < 300ms, 키워드는 전체의 약 0.5%에 맞는 낱말. 넓은 키워드(예: 30%)는 기준에서 빼고 측정값만 기록합니다. | 키워드 비용은 맞는 행 수에 비례해 어떤 색인으로도 상한을 보장할 수 없습니다. | 실제로 넓은 키워드 검색이 느릴 수 있음(문서화). |
| W10 | 색인 순서: 오늘·어제 파일 먼저 끝까지, 그다음 밀린 파일을 최신 날짜부터 차례당 5만 줄. 1초 폴링 + `LogWriter` 플러시 알림. | 재구축 중에도 최근 로그가 먼저 보이고, 색인 지연은 보통 1초 이내입니다. | 재구축 동안 오래된 날짜는 늦게 보임. |
| W11 | 조회 감사: 내보내기는 매번, 목록·감사 첫 페이지는 (사용자, 채널, 조건)별 60초에 한 번 `logs_view`/`audit_view`. 커서 요청·히스토그램·건수 요청은 기록하지 않습니다. | spec §15 "조회 행위도 감사 기록". 새로 고침·자동 갱신마다 기록하면 감사 로그가 조회 기록으로 덮입니다. | 60초 안의 같은 조건 반복 조회는 한 건으로 남음. |
| W12 | 내보내기: CSV(BOM, `\r\n`, 고정 열, 수식 시작 문자 `'` 처리) / JSONL(원문 줄), 요청당 최대 10만 행, 스트리밍. | Excel 한글 표시, CSV 수식 주입 방지, 메모리 상한. | 더 많은 행은 기간을 나눠 내보내기. |
| W13 | 감사 로그 화면은 `admin.audit`(관리 작업)과 `auth`(로그인)를 `/api/audit`(`view_audit`)로 같은 엔진에서 읽습니다. | §6.4 #8과 §4.1.5(모든 로그인 시도) 둘 다 "누가·언제·어느 채널·무엇"입니다. | 없음. |
| W14 | 보존 정리는 매일 03:30 KST, 놓친 날은 시작 60초 뒤, 그리고 보존 기간을 **줄여 저장하면 5초 뒤** 실행합니다. 기준일은 Plan 3 `retention_cutoff`(미리보기와 같음). | §5.6 "새벽 정리"와 §11 P6 "미리보기 후 정리 동작". 미리보기에서 확인한 삭제가 다음 날 새벽까지 미뤄지면 확인 의미가 흐려집니다. | 낮에 큰 삭제가 돌 수 있음(청크 삭제, Task 6 성능 테스트로 응답 확인). |
| W15 | 압축: `max(압축 시작 일수, 2)`일보다 오래되고 **색인이 끝난** `.jsonl`만 gzip(level 6). 같은 날짜 `.gz`가 있으면 합칩니다. 지우기 전 `expect_log_removed`. | 수집기의 지난 이벤트(최대 24시간, Plan 4 V12)가 어제 파일에 늦게 쓰일 수 있고, 색인 전 압축은 행 누락을 부릅니다. | 압축이 하루 늦어짐. |
| W16 | DB 표 정리: `auth_sessions`(만료 규칙, Python에서 시각 파싱), `otp_codes`(1시간 지난 미등록·무효 이메일 행), `otp_failures`(1시간), `otp_verify_ip`·`otp_ip_requests`(10분), `mcp_actions`·`mcp_transitions`·`rdp_logon_failures`·끝난 `rdp_connections`와 그 `notice_displays`(로그 보존 기간). 버전 표(스크립트·고지)는 남깁니다. | carry-forward 항목 전부. UTC `isoformat`과 KST 밀리초 문자열은 각 표 안에서 형식이 같아 문자열 비교가 안전하고, 마이크로초가 섞인 `auth_sessions`만 파싱합니다. | MCP 조치 이력이 로그와 같은 기간만 남음. |
| W17 | FAILED 상태와 자동 조치 예산은 저장하지 않습니다(서비스 재시작 때 초기화). 운영 문서에 적습니다. | 재부팅 뒤 감시를 새로 시작하는 편이 자연스럽고, 예산은 재시작마다 3회로 제한됩니다. | 서비스가 반복 재시작되면 그만큼 자동 조치가 더 돎. |
| W18 | 방어용 `_apply` 거절의 엔진 측 취소는 하지 않습니다(추후). | 지금 도달할 수 없는 경로입니다(Plan 2 리뷰). | 도달하면 예산 한 칸 소모. |
| W19 | 스크립트 저장의 replace-before-COMMIT은 바꾸지 않고, 실행 직전 해시 검사(+ Plan 4 `TamperScanner`)를 안전망으로 둡니다. 테스트로 고정합니다. | 순서를 바꿔도 반대쪽 불일치가 생기고, 여러 파일을 한 트랜잭션에서 되돌리는 코드는 위험 대비 큽니다. | COMMIT 실패 뒤 첫 실행이 `hash_mismatch`로 막힘(소유자가 다시 저장). |
| W20 | 타임아웃 kill이 실패하면 `error="kill_failed"`, MCP 잠금을 최대 30초 더 잡아 옛 프로세스가 살아 있는 동안 다음 실행을 막고 `monitor.kill_failed`를 남깁니다. | carry-forward: 다음 실행이 옛 스크립트와 겹칠 수 있었습니다. | 그 MCP의 다음 조치가 최대 30초 늦어짐. |
| W21 | 서비스(및 콘솔 서버) 정지 때 10초 유예 뒤 남은 스크립트의 **프로세스 트리**를 죽입니다. | 서비스가 끝난 뒤 SYSTEM 권한 스크립트·자식이 남으면 안 됩니다(carry-forward 두 항목). | 정지 직전 시작된 스크립트가 중간에 끊김. |
| W22 | 서비스 호스트 = 같은 실행 파일의 `service` 하위 명령(pywin32 `ServiceFramework`, `servicemanager` 디스패처). SCM 정지·종료 → `ServeControl.request_stop`, `SESSIONCHANGE` → `nudge_sessions`. SCM 요청 없이 끝나면 `os._exit`로 실패를 알려 복구 동작(5s/10s/60s, 1일 초기화)이 다시 띄웁니다. 시작 때 작업 폴더를 데이터 루트로. | 실행 파일·코드 경로를 하나로 유지하고, pywin32는 Plan 4 의존성입니다. 서비스 작업 폴더는 System32입니다. | 없음. |
| W23 | 포트는 서비스 구성 전에 `SO_EXCLUSIVEADDRUSE`로 먼저 잡습니다. 종료 코드 3 포트 사용 중, 4 루트 사용 중, 5 더 새 DB(트레이스백 없음). | carry-forward: 포트 사용 중이 종료 코드 3 + CancelledError 트레이스백이었습니다. 같은 PC의 다른 프로세스가 포트를 가로채지 못하게 합니다. | 없음. |
| W24 | 데이터 루트 잠금 `data/.lock`(`msvcrt.locking`). 서버와 `reindex`가 씁니다. | 두 인스턴스가 같은 로그·색인을 동시에 쓰면 색인이 깨집니다. | 비정상 종료 뒤에는 OS가 잠금을 풀어 문제 없음. |
| W25 | 서비스 시작 유형은 웹 설정값이 기준입니다. 설치는 항상 `delayed-auto`로 만들고, 서비스가 시작할 때와 설정을 저장할 때 SCM을 설정값으로 맞춥니다(`/api/service`로 상태 표시). | 설치 스크립트와 설정이 서로 되돌리는 일을 막습니다(carry-forward "시작 유형 반영"). | 설치 직후 한 번 바뀔 수 있음. |
| W26 | 패키징은 Task 13 스파이크로 정합니다: PyInstaller 6.22.3 onedir(spec, PyPI에 3.15 지원·`py3-none-win_amd64`, 2026-09-12)이 이 PC에서 실행되면 A, Smart App Control(이 PC에서 켜짐, `VerifiedAndReputablePolicyState=1`)이 막으면 B = python.org embeddable(PSF 서명 확인) + `._pth`로 고립한 묶음 런타임. 두 경로 모두 막히면 멈춰서 보고. 코드 서명은 추후. | 새로 빌드한 서명 없는 exe는 평판이 없어 SAC에 막힐 가능성이 큽니다. 깨끗한 Win 11 Pro에도 SAC가 켜져 있을 수 있습니다. | 고르지 않은 경로는 구현하지 않으므로, 실기기 결과가 다르면 다른 경로를 새로 구현(Task 13 규모). |
| W27 | A의 hiddenimports = `collect_submodules("uvicorn")` + `httptools`, `websockets`, `win32timezone`, `win32serviceutil`, `servicemanager`, `app.winsvc.service`; `watchfiles`는 제외(리로드를 쓰지 않음). pyyaml cp315 휠은 2026-11-05에도 없어 `uvicorn[standard]`로 돌아가지 않고, 빌드 때 다시 확인해 경고만 냅니다. | carry-forward 패키징 항목. | 없음. |
| W28 | 묶음 = `bundle.json`이 있는 폴더(`web/`, `install/`, `docs/`, A: `bin/monitor`·`bin/agent`, B: `runtime/`·`server/`·`agent/`). 코드는 실행 파일에서 위로 3단계까지 찾아 정적 폴더·데이터 루트(`%ProgramData%\MCP Monitor`)·에이전트 명령을 정합니다. B의 `._pth`는 `PYTHONPATH`·현재 폴더를 무시합니다. | carry-forward(`--static-dir` 기본값, 에이전트 실행 파일). SYSTEM으로 도는 파이썬이 환경 변수로 다른 코드를 읽으면 안 됩니다. | 없음. |
| W29 | 설치 스크립트는 "계획 JSON → 실행" 한 경로이고 `-DryRun`이 같은 계획을 출력합니다. 관리자 확인이 첫 단계입니다. | 이 PC는 관리자가 아니므로 실제 설치 없이 계획 전체를 자동 테스트할 수 있어야 합니다. | 없음. |
| W30 | ACL은 이름이 아니라 SID(`S-1-5-18`, `S-1-5-32-544`)로, 감사 정책은 하위 범주 GUID로 지정합니다. 데이터 루트 전체(로그·데이터·스크립트)를 SYSTEM + Administrators만. 설치 폴더는 Program Files 기본 ACL(사용자 읽기·실행 — 에이전트가 사용자 세션에서 실행). | 한국어 Windows에서 "Administrators"·감사 범주 이름이 다릅니다. spec §5.6·§5.8 ACL. | 없음. |
| W31 | 제거는 기본으로 데이터를 남기고, `-RemoveData`일 때만 데이터·Edge 프로필을, `-RestoreAuditPolicy`일 때만 감사 정책·레지스트리를 되돌립니다. | 감사 기록은 쉽게 지우면 안 됩니다. | 수동 정리 필요. |
| W32 | 로그 히스토그램은 직접 그린 SVG(Recharts 아님)이고 포인터 드래그 + 키보드(Shift+화살표, Enter, Escape)로 선택합니다. 카테고리 12개는 색 5개 묶음으로 보여 줍니다. 애니메이션 없음. | 드래그 선택·키보드 접근·2px 최소 막대를 정확히 다루고, §6.5 "로그 테이블에는 애니메이션 없음"을 로그 영역 전체에 적용합니다. 12색은 구분이 안 됩니다. | 차트 코드를 직접 유지. |
| W33 | 웹 신규 의존성은 `@tanstack/react-virtual` 하나(+ Plan 3이 아직 안 깔았으면 `@tanstack/react-table`). 로그·감사 라우트는 지연 로드, 보드 예산 테스트에 금지 목록 추가. | spec §6.5 스택에 있고 U18이 Plan 5로 미뤘습니다. | 없음. |
| W34 | 필터 상태는 URL search(TanStack Router 기본 JSON 직렬화)에만 둡니다. 빠른 범위는 열 때마다 다시 계산하고, 모든 경계는 KST 분 단위입니다. | §6.4 "필터 상태가 URL에 유지되어 링크로 공유". 분 단위가 롤업 경로의 조건입니다(W8). | URL이 길어 보임. |
| W35 | 버전을 1.0.0으로 올리고(서버·에이전트·웹), spec은 v0.8. | 첫 배포 가능한 묶음입니다. | 없음. |
| W36 | 추후로 남기는 것: 알림 채널(§14), 실제 OTP 공급자와 발송 비동기화, HTTPS 옵션, 설정 백업·가져오기, 해시 체인, syslog/SIEM·GeoIP, legalnotice, 진짜 모달 고지 창, WTS 알림 창, 코드 서명, E501(대량 줄바꿈이 동시 작업과 충돌), `ruff format` 금지. | 이번 범위(P6·P7 완료 기준) 밖이거나 선택 사항입니다. | carry-forward에 남김. |
| W37 | `MCP_ACTOR`는 안전한 이메일(`[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+`)일 때만 그대로, 아니면 `user-<id>`. | cmd가 `%VAR%`를 해석하므로 `&` 등이 든 이메일이 SYSTEM 명령 주입이 될 수 있습니다(carry-forward). 로그의 행위자는 원래 이메일. | 특이한 이메일의 스크립트는 `user-<id>`를 봄. |
| W38 | §11 P7 "깨끗한 Win 11 Pro에서 한 번에 설치"는 이 PC에서 확인할 수 없어 점검표의 `대기`로 남깁니다. 자동으로는 `-DryRun` 계획, 관리자 확인, 묶음 실행까지 검증합니다. | 개발 PC가 Home·비관리자입니다(사용자 환경). | 실기기에서만 드러나는 문제(SCM·ACL·감사 정책)는 그때 고침. |
| W39 | 성능 데이터와 결과는 `server/.cache/`(gitignore)에 캐시합니다. | 100만 건 생성·색인을 매번 하지 않습니다. | 생성 규칙을 바꾸면 `GEN_VERSION`을 올려야 함. |
| W40 | 리뷰에 `audit-suite`의 `vercel-react-best-practices`·`web-design-guidelines`를 씁니다(Plan 3 U32 때는 없었고 지금은 설치돼 있음). | §12 "설치한 경우". | 없음. |
| W41 | (사용자 지시) 휴대폰·터치 전용 작업은 하지 않습니다. 모든 Plan 5 화면은 640×600px까지 줄인 데스크톱 창에서 페이지 가로 스크롤 없이 쓸 수 있고, 표는 자기 컨테이너에서 스크롤합니다. UI 과제마다 1920·1280·1024·800·640px에서 확인하고 E2E로 고정합니다. | 사용자가 작은 브라우저 창을 씁니다. | 레이아웃 조정. |

## 부록 B: API 대응표 (서버 코드 기준)

웹 클라이언트 함수는 `web/src/lib/endpoints.ts`입니다. 모두 "신규"이며 두 채널 공통 경로는 로그인한 MCP 개발자 이상입니다. 목록 조건 `*`는 같은 이름을 여러 번 쓰는 매개변수입니다.

| 메서드·경로 | 채널 | 권한 | 응답(성공) | 주요 오류 | 서버 코드 | 클라이언트 | Query key |
|---|---|---|---|---|---|---|---|
| `GET /api/logs?from&to&users*&cat*&event*&outcome*&session&ip&q&cursor&limit=1..1000` | 둘 다 | `view_logs` | `LogPage {items, next_cursor, index: {ready}}` | 401, 422 `validation` | `logs_api` → `IndexReader.page` | `logs(q, cursor, limit)` | `['logs','page',q]`(infinite) |
| `GET /api/logs/histogram?…&buckets=10..200&group=none\|cat\|user` | 둘 다 | `view_logs` | `LogHistogram {from, to, bucket_sec, starts, series, total, source}` | 401, 422 | `IndexReader.histogram` | `logHistogram(q, {buckets, group})` | `['logs','histogram',q,group,buckets]` |
| `GET /api/logs/users?…&limit=1..500` | 둘 다 | `view_logs` | `[{user, count}]`(users 조건 무시) | 401, 422 | `IndexReader.users` | `logUsers(q)` | `['logs','users',q]` |
| `GET /api/logs/status` | 둘 다 | `view_logs` | `LogIndexStatus` | 401 | `LogIndex.status` | `logStatus()` | `['logs','status']` |
| `GET /api/logs/export?…&format=csv\|jsonl&limit=1..100000` | 둘 다 | `export_logs` | 스트림(CSV BOM / NDJSON) | 401, 422 | `IndexReader.iter_rows` | `logExportUrl(q, format)` | — |
| `GET /api/audit?kind=admin\|auth\|all&from&to&users*&result*&channel&q&cursor&limit` | 둘 다 | `view_audit` | `LogPage` | 401, 422 | `logs_api` | `audit(q, cursor)` | `['audit',q]` |
| `GET /api/audit/export?…&format` | 둘 다 | `export_logs` | 스트림 | 401, 422 | `logs_api` | `auditExportUrl(q, format)` | — |
| `GET /api/settings/retention/preview?days=7..3650` | Local | `edit_retention` | 기존 + `delete_events: int \| null` | 403, 422 | `local_api` + `count_before_day` | `retentionPreview(days)` | `['retention-preview', days]` |
| `PUT /api/settings` | Local | `edit_global_settings`/`edit_retention` | 기존 `Settings`(보존을 줄이면 정리 예약, 시작 유형을 바꾸면 SCM 적용 + 감사) | 기존 | `local_api` | `updateSettings(patch)` | — |
| `GET /api/service` | Local | `edit_global_settings` | `{installed, running_as_service, start_type, desired, in_sync}` | 403(외부 404) | `service_api` → `StartTypeManager.status` | `serviceStatus()` | `['service']` |

**CLI**
| 명령 | 동작 | 종료 코드 |
|---|---|---|
| `python -m app [--root] [--local-port] [--external-port] [--external-host] [--static-dir] [--dev-otp-code] [Plan 4 수집 옵션]` | 콘솔 서버(기본값은 묶음 위치 기준, W28) | 0, 1, 2, 3 포트, 4 루트, 5 DB |
| `python -m app service [같은 옵션]` | SCM 디스패처(서비스 전용; 콘솔에서는 2) | SCM이 관리 |
| `python -m app reindex [--root]` | `index.db`를 지우고 JSONL에서 다시 색인 | 0, 4 |
| `python -m app --version` | `mcp-monitor 1.0.0` | 0 |

**로그 이벤트(이 계획이 더하는 것)**
| 카테고리 | 이름 | 필드 |
|---|---|---|
| `system` | `logstore.dropped` | `count` |
| `system` | `logindex.bad_lines` / `logindex.file_truncated` / `logindex.rebuilt` / `logindex.ready` / `logindex.cycle_failed` | `file, count` / `file, before, after` / `reason` / `rows, duration_ms` / `error` |
| `system` | `retention.run` / `retention.failed` | `reason, cutoff, compress_cutoff, deleted_files, deleted_bytes, deleted_from, deleted_to, index_rows, compressed, skipped_compress, db_rows, errors, duration_ms` / `error` |
| `system` | `monitor.kill_failed` / `monitor.stop`(+`killed`) / `service.start_type` | `mcp_id, run_id, kind` / `abandoned, killed` / `result, desired, current` |
| `admin.audit` | `logs_view`, `audit_view` | `target: {filters}` |
| `admin.audit` | `logs_export`, `audit_export` | `target: {filters, format, limit}` |
| `admin.audit` | `retention_purge`(행위자 없음, 채널 `local`) | `target: {reason, cutoff, deleted_from, deleted_to, files, bytes, index_rows, db_rows}` |
| `admin.audit` | `service_start_type_apply` | `target: {start_type, result}` |
