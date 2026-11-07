# Plan 6 — Rust 단일 실행 파일(데스크톱 앱) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 사용자 지시에 따라 과제마다 리뷰하지 않고, 마지막에 계획 전체 리뷰 한 번 + 수정 한 번만 합니다. 구현자는 원장(ledger)에서 과제를 하나씩 받습니다. 과제마다 필요한 값은 그 과제 안에 모두 적었습니다(다른 과제를 읽지 않아도 됨).

**Goal:** 확정 설계 `docs/design/desktop-app-rust.md`(설치 모드 하나, D2–D5)를 구현합니다. Rust(Tauri 2) 실행 파일 `mcp-monitor.exe` 하나가 ① 기존 Python 서버 묶음(PyInstaller onedir)을 zstd tar로 **안에 품고**(`include_bytes!`), ② `install`/`uninstall`/`audit-policy` 모드에서 지금 `install.ps1`·`uninstall.ps1`·`audit-policy.ps1`이 하는 일을 **같은 검사·같은 규칙으로** 수행하고(데이터 루트 ACL을 처음부터 만들고 다시 읽어 확인, 상위 폴더·링크·경로 형태 검사, 마커를 확인하는 데이터 삭제, GUID 감사 정책과 백업·복원, 방화벽 선택, 지연 자동 시작 LocalSystem 서비스, "앱 및 기능" 항목, 시작 메뉴 바로 가기, 선택 HKCU `Run`), 실행 중인 서비스 위로 업그레이드하며, ③ `app` 모드에서 `http://127.0.0.1:8700`만 여는 WebView2 창과 트레이를 띄우고(단일 인스턴스), ④ `agent` 모드에서 Python 에이전트를 대신해 RDP 세션마다 **최상위 모달 WebView2 고지 창**과 창 이벤트·유휴 수집을 같은 `/api/agent/*` 규약(실행마다 토큰·서버 키, 요청마다 nonce, 응답마다 `X-Server-Proof`, 증명 실패면 종료 코드 5)으로 수행합니다. 서버는 묶음의 `bundle.json`(`"agent": "desktop"`)을 보고 `mcp-monitor.exe agent`를 띄웁니다. 끝에 PowerShell 설치 스크립트는 은퇴하고, Python 에이전트는 개발·테스트용으로만 남습니다(Y7·Y8).

**Architecture:** 실행 파일은 GUI 서브시스템(`windows_subsystem = "windows"`) 하나이고 `main`이 인자를 먼저 해석해 모드를 고릅니다(Tauri 런타임은 `app`과 `agent --dialog webview`에서만 시작). 설치 계열은 Plan 5와 같은 **"계획(단계 목록 JSON) → 실행"** 한 경로입니다: 순수 함수가 `Host`(관리자 여부, 서비스 존재, 레지스트리 읽기, 볼륨 목록, 환경 변수)를 받아 `Plan`을 만들고, `--dry-run`이면 JSON 한 줄을 출력하고 끝, 아니면 `Executor`가 차례로 실행합니다. System32 도구(`sc.exe`, `auditpol`, `reg`, `wevtutil`, `netsh`)는 지금처럼 절대 경로로 부르고, ACL·파일·레지스트리 쓰기·바로 가기는 `windows` 크레이트로 직접 합니다. payload는 `install\build.ps1`이 만든 폴더(`dist\payload`)를 `build.rs`가 결정적으로 묶고(정렬, mtime 0) 파일마다 SHA-256 매니페스트와 전체 해시를 함께 내장합니다. 설치는 `<InstallDir>.staging`(Program Files 아래, 관리자만 씀)에 풀며 파일마다 해시를 확인한 뒤 서비스를 멈추고 폴더를 통째로 바꿉니다(`.old`로 옮기고 실패하면 되돌림). 에이전트는 Python 에이전트의 모듈 구성을 그대로 옮깁니다(config → client(HMAC) → runner → coalesce/sender/pump/idle/hooks). 고지 창은 서버가 주는 `/notice#d=<id>&t=<token>` 주소를 **명령줄이 아닌 WebView2 API로** 엽니다(웹 변경 없음, Y9).

**Tech Stack:** Rust 1.99.1(stable, MSVC, `desktop/rust-toolchain.toml`), Tauri 2.12.5 + tauri-build 2.7.4 + tauri-plugin-single-instance 2.5.5(WebView2 Evergreen), `windows` 0.62.2, `webview2-com` 0.39.1, ureq 3.5.1(기본 기능 끔: 평문 HTTP만), serde 1.0.229, serde_json 1.0.154, sha2 0.11.1, hmac 0.13.0, hex 0.4.3, getrandom 0.4.3, zstd 0.13.4, tar 0.4.46, time 0.3.55, regex 1.13.1, (빌드) walkdir 2.5.0, (테스트) tempfile 3.27.0. 정확한 버전 고정 + `Cargo.lock` 커밋(Y3). 새 개발 도구 cargo-audit 0.22.2(Y4). Visual Studio Build Tools 2026(VCTools + Windows 11 SDK; `dumpbin`, 선택 시 `signtool`). 서버·웹은 Plan 5 스택 그대로(새 런타임 의존성 없음).

**Spec:** `docs/PLAN.md` v0.8(끝에 v0.9), 설계 `docs/design/desktop-app-rust.md`(확정, D2–D5), 운영 문서 `docs/ops/OPERATIONS.md`. 이미 내려진 결정은 Plan 1–5 부록(…, Plan 4 V1–V33, Plan 5 W1–W41)입니다. 이 계획의 결정(Y1–Y34)은 **부록 A**, 대응표(CLI·파일·레지스트리·에이전트 규약)는 **부록 B**에 있습니다. 본문의 `Y<n>`은 부록 A의 행입니다.

**설계 요구사항과 이 계획의 확인 방법**
| 요구 | 확인 |
|---|---|
| R1 WebView를 포함한 윈도우 앱 | Task 12 `classify_navigation` 표 테스트, `tests/app_window.rs`(ignored, `--features dev`, CDP로 창 주소 확인); 실기기 P8-2·P8-14 |
| R2 Rust exe 하나가 셋업·실행 | Task 3 `embedded_payload_verifies_and_matches_its_manifest`, Task 13 `verify-payload` + `-m desktop` `test_desktop_exe_runs_the_embedded_server`; 실기기 P8-2 |
| R4 설치 절차 후 exe로 실행 | Task 6–8 계획 테스트, Task 12 `auto_mode_decisions`; 실기기 P8-2·P8-3 |
| R5 Windows 시작 시 자동 실행 | Task 6 `install_plan_default`(`start= delayed-auto`, `obj= LocalSystem`); 실기기 P8-3 |
| S2 연결마다 최상위 모달 고지(WebView2) | Task 11 `notice_window_spec_is_a_topmost_modal`, `tests/agent_webview.rs`(ignored, 이 PC에서 실행); 실기기 P8-6–P8-8 |
| S3·S4 채널 분리, 런타임 외부 네트워크 금지 | Task 12 탐색 제한(8700만), Task 9 프록시 무시, 자동 업데이트 없음(Y31) |
| D5 서명 없음 | Task 1 스파이크(이 PC의 SAC), Task 13 `-SignThumbprint` 선택 단계(기본 꺼짐); 실기기 P8-1 |

**carry-forward 배정** (`docs/superpowers/plans/carry-forward.md` "After Plan 5" 등)
| 항목 | 과제 / 결정 |
|---|---|
| True modal notice window (WebView2 host instead of Edge `--app`, Plan 4 V3) — Product 목록과 Plan 4 Later 두 곳 | **닫음**: Task 11(최상위·닫기 없음·작업 표시줄 없음·Alt+F4 무시), Y10 |
| A reinstall with a different `-ExternalPort` leaves the old firewall rule | **닫음**: Task 6 `firewall_delete_old` 단계, `reinstall_with_another_external_port_removes_the_old_rule` |
| Code signing for `mcp-monitor.exe` and `mcp-agent.exe` (W26) | **부분**: Task 13 선택 서명 단계(인증서가 생기면 켬, D5). 인증서가 없어 항목은 열린 채로 남기고 문구를 "mcp-monitor.exe + 내장 서버 exe"로 고침 |
| Window events: proof and data on one keep-alive connection (R2) | **유지**(추후): ureq 연결 풀은 연결을 고정할 수 없음. 위험은 HMAC 증명 + `verified_only`로 Python과 같음(Y22) |
| Win 11 Pro 실기기 `대기` 항목(P4–P7) | 유지 + 새 점검표 `docs/verification/win11-pro-p8.md`(Task 15), "데스크톱 설치 상태로 다시 수행" 안내 |
| 그 밖의 After Plan 5 항목 | 이 계획 범위 밖(유지) |

## Global Constraints

- 브랜치 `feat/plan6-desktop-app`(이미 있음, `main` 1ef47f0 기준)에서 작업합니다. 이 문서와 실제 코드의 이름이 다르면 코드를 따르고 보고서에 이름 대응을 적습니다(Y1).
- 이 PC는 **Windows 11 Home, 관리자 아님, Smart App Control(SAC) 켜짐**, WebView2 Evergreen 156 설치됨. 테스트를 관리자 권한으로 돌리지 않고, 이 PC의 서비스·방화벽·감사 정책·HKLM 레지스트리·Program Files·ProgramData ACL을 바꾸지 않습니다. 설치 계열은 `--dry-run`, "관리자가 아니면 아무것도 바꾸지 않고 종료 1", 그리고 `%LOCALAPPDATA%\mcp-monitor-install-tests\<임의>` 임시 폴더 안의 파일·ACL만 실제로 다룹니다. 실제로 바꾸는 코드는 `Executor`/`Host`/`Registry` 트레이트 뒤에 두고 테스트는 가짜를 씁니다. 바꿀 수 있는 테스트 진입점은 모두 `crate::winutil::assert_not_elevated()`를 먼저 부릅니다(승격된 셸이면 테스트 실패).
- **앱 제어 정책:** `cargo`, `rustc`, 빌드 스크립트(`build.rs`가 컴파일된 exe), 테스트 exe, `cargo-audit`가 SAC/앱 제어에 막히면(`CodeIntegrity/Operational` 이벤트, "이 앱은 차단되었습니다", 0xC0000428 등) **우회하지 말고 멈춰서 보고**합니다(Y2). 권한 부족으로 실패하는 테스트를 `#[ignore]`나 skip으로 바꾸지 않습니다.
- 명령 위치: Rust는 `desktop/`에서 `cargo ... --locked`. 서버는 `server/`에서 `uv run python -m pytest ...`(**`python -m` 형태로만**; uv가 PATH에 없으면 `C:\Users\ddang\AppData\Local\Microsoft\WinGet\Packages\astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe\uv.exe`, E2E는 `UV_EXE`). 웹은 `web/`에서 `pnpm <script>`(Git Bash면 먼저 `export PATH="/c/nvm4w/nodejs:$PATH"`). 에이전트(Python)는 `agent/`에서 `uv run python -m pytest -q`.
- Rust 검사(모든 Rust 과제의 마지막 단계): `cargo fmt --check`, `cargo clippy --locked --all-targets -- -D warnings`, `cargo test --locked`. `#[ignore]` 테스트는 과제가 명시한 단계에서만 `-- --ignored`로 돌립니다(실제 WebView2 창을 이 PC 화면에 띄움, 관리자 불필요).
- **의존성:** 부록 A Y3 표의 크레이트만, `=` 정확한 버전으로. 표에 있는 크레이트의 **기능(feature)** 추가는 자유(보고서에 기록), 새 크레이트는 Ruling 없이 추가하지 않습니다. `cargo tree -d -e normal`에 `windows`·`webview2-com`·`tauri-utils`가 두 버전으로 나오면 안 됩니다(Y3). 서버·웹·Python 에이전트는 새 의존성 없음.
- **버전:** 제품 1.1.0(서버 `app.__version__`, `web/package.json`, `desktop/Cargo.toml`, `tauri.conf.json`). Python 에이전트는 1.0.0 그대로(개발용, Y5·Y7).
- 문구: 사용자에게 보이는 문구(메시지 상자, 오류, 진행 줄, 트레이, 연결 중 페이지)는 **한국어**, 코드·식별자·로그 이벤트 이름은 영어. 오류 출력 형식은 Plan 5 그대로: 인자 오류는 표준 오류 `오류: <내용>` + 종료 코드 2, 실행 실패는 `[실패] <id>: <내용>` + 1, 관리자 아님은 `관리자 권한으로 다시 실행하세요. (mcp-monitor.exe를 마우스 오른쪽 단추로 눌러 "관리자 권한으로 실행" 또는 관리자 PowerShell)` + 1. 진행 줄 `[i/n] <id>`, 건너뜀 `[i/n] <id>: 건너뜀 (<when> 아님)`.
- 콘솔: GUI 서브시스템이므로 CLI 모드는 시작할 때 표준 핸들이 없으면 `AttachConsole(ATTACH_PARENT_PROCESS)`로 부모 콘솔에 붙습니다. PowerShell에서 결과를 기다리려면 `& .\mcp-monitor.exe install --dry-run | Write-Output` 형태(운영 문서에 적음, Y13).
- 서버 규칙(Plan 5 Global Constraints)은 그대로입니다: 오류 본문 `{"error": "<code>"}`, 새 API 없음, 로그 카테고리 12개, `ruff format` 금지. 웹은 **변경 없음**(Y9·Y27): `pnpm typecheck`·`lint`·`test`·`build`·`test:budget`·`e2e`가 그대로 통과해야 합니다.
- **창 크기(사용자 지시):** 휴대폰 작업 없음. 이 계획이 만드는 화면(연결 중 페이지 `desktop/ui/index.html`, 앱 창 최소 크기, 고지 창)은 **640×600까지** 쓸 수 있어야 합니다: 앱 창 `min_inner_size(640, 600)`, 연결 중 페이지는 가로 스크롤 없음, 고지 창은 640×600을 작업 영역에 맞춰 줄임(Y30).
- 테스트 본문은 모두 실제 단언입니다(주석만 있는 테스트 금지). 공유 테스트 자료: `server/tests/fixtures/agent-events.json`(이벤트 본문), HMAC 벡터(키 `"11"×32` hex, nonce `"abc"` → `8094a4aa0311ceadd62bd4b17fa76cb0066cff4f125cbfc64dea5bab2493f2cd`).

## Review Focus

1. **승격과 자기 재실행**(관리자 아님에서 아무것도 바꾸지 않음, 재실행 인자는 해석한 옵션으로만 다시 만듦, `--dry-run`은 승격하지 않음, 승격된 프로세스가 호출자가 고른 임의 경로에 쓰지 않음, Downloads 폴더의 DLL 심기): → Task 4 `relaunch_args_carry_only_parsed_options_and_add_interactive`, `quoting_survives_command_line_to_argv`, `dry_run_is_never_elevated`, Task 6 `install_without_admin_exits_1_and_changes_nothing`(바이너리), `require_admin_comes_first_and_stops_without_admin`, Task 13 `dumpbin` DependentLoadFlags 검사, 실기기 P8-2·P8-17
2. **payload 무결성**(잘린 exe, 바뀐 파일, 매니페스트에 없는 항목, `..`·절대 경로·링크 항목, 이미 있는 대상, 개발용 payload로 실제 설치): → Task 3 `pack_is_deterministic_and_extract_round_trips`, `a_wrong_archive_hash_is_refused`, `a_file_whose_bytes_differ_from_the_manifest_is_refused`, `an_entry_missing_from_the_manifest_is_refused`, `a_manifest_file_missing_from_the_archive_is_refused`, `traversal_absolute_and_link_entries_are_refused`, `release_layout_needs_the_server_web_and_matching_version`, `pack_refuses_links`, Task 7 `stage_refuses_the_fixture_payload`, `stage_refuses_a_staging_folder_it_did_not_make`, Task 13 `test_verify_payload_runs_the_embedded_server`
3. **실행 중인 서비스 위로 업그레이드**(정지 대기, 세션의 앱·에이전트가 잡은 파일, 폴더 교체 실패 시 되돌림, 시작 뒤에는 되돌리지 않음, 다운그레이드, 이전 포트·방화벽 유지, 1.0.0 PowerShell 설치에서 올라옴): → Task 6 `upgrade_plan_stages_before_stopping_and_cleans_up_after_ready`, `downgrade_is_refused`, `reinstall_reuses_previous_ports_and_firewall`, `upgrade_from_a_powershell_install_keeps_its_state`, Task 7 `swap_moves_the_old_install_aside_and_puts_staging_in_place`, `swap_rolls_back_when_staging_cannot_be_moved`, `stop_apps_targets_only_processes_inside_the_install_dir`, Task 12 `auto_mode_decisions`; 실기기 P8-11·P8-12
4. **제거의 데이터 안전**(기본은 데이터 유지, 마커 없는 폴더·드라이브 루트·시스템 폴더·장치/UNC/정션 경로 거부, 설치 폴더 안 데이터 루트, 실행 중인 자신, 다른 사용자 프로필): → Task 8 `uninstall_plan_keeps_data_by_default`, `uninstall_refuses_to_remove_unsafe_roots`, `uninstall_refuses_device_unc_and_linked_paths`, `only_a_marked_data_root_and_a_bundle_install_dir_are_removed`, `remove_install_dir_keeps_the_running_exe_for_reboot`, `webview_profiles_are_removed_and_nothing_else`, `uninstall_without_admin_exits_1_and_changes_nothing`(바이너리); 실기기 P8-13
5. **에이전트 사칭과 서버 증명**(키 없는 서버, 도중에 포트를 가로챈 프로세스, 증명 없는 401, 창 제목은 증명된 서버에만, 다른 주소의 고지 URL, 토큰·키가 자식(WebView2)에 상속): → Task 9 `proof_matches_the_python_vectors`, `a_server_without_the_key_is_dropped_at_once_and_nothing_is_opened`, `a_rogue_that_takes_over_mid_run_gets_no_window_opened`, `an_unproven_401_after_a_proven_answer_drops_the_trust`, `only_notice_urls_of_the_configured_server_are_opened`, `sensitive_posts_wait_for_a_proven_answer_after_an_outage`, `secrets_are_taken_out_of_the_environment`, `tests/agent_print.rs::a_rogue_server_is_left_within_seconds_with_exit_5`, Task 10 `sender_batches_and_buffers_while_unavailable`(창 이벤트는 모두 `verified_only`), `the_final_flush_sends_nothing_after_an_unproven_401`, Task 11 서버 통합 `test_real_agent_shows_and_acknowledges_notice[desktop]`; 실기기 P8-9
6. **세션별 고지 모달성**(최상위, 닫기 버튼 없음, Alt+F4/`WM_CLOSE` 무시, 작업 표시줄 없음, 다른 세션에 안 보임, WebView2 프로세스가 죽으면 다시 표시, 확인 뒤 닫힘): → Task 11 `notice_window_spec_is_a_topmost_modal`, `notice_size_fits_the_work_area`, `close_requests_are_refused_unless_we_close`, `a_failed_webview_counts_as_closed_by_the_user`, `tests/agent_webview.rs::webview_notice_is_topmost_ignores_wm_close_and_closes_on_command`(ignored, 이 PC); 실기기 P8-6–P8-8
7. **WebView2 탐색 제한**(앱 창은 `127.0.0.1:<LP>`와 연결 중 페이지만, 나머지 http(s)는 기본 브라우저, 다른 스킴 차단, userinfo·비슷한 호스트, 고지 창은 `/notice`만, 새 창, 개발자 도구, `WEBVIEW2_*` 환경 변수): → Task 12 `classify_navigation_table`, Task 11 `notice_navigation_allows_only_the_notice_page`, Task 9 `webview2_variables_are_removed`, Task 13 release 빌드 기능 검사(`devtools`·`dev` 꺼짐); 실기기 P8-15
8. **데이터 루트·설치 폴더 ACL 이식의 동등성**(처음부터 만들고 다시 읽기, 남이 먼저 만든 폴더, 상위 폴더·드라이브 루트의 위험 권한, 상속 전용 ACE, 열린 핸들 위험 권한, 파일이 사라지는 동안의 검사): → Task 5 `acl.rs`·`paths.rs` 테스트 전체(`initialize_data_root_rebuilds_the_acl_from_scratch`, `initialize_data_root_refuses_a_root_made_just_before_it`, `ancestor_check_includes_the_drive_root`, `an_existing_data_root_others_may_delete_or_rechmod_is_refused`, `unsafe_roots_are_refused` 등), `an_install_tree_others_may_write_is_refused`(신규), Task 7 `swap_refuses_an_install_tree_others_may_write`

---

### Task 1: 툴체인, `desktop/` 작업 공간, 스파이크(SAC·WebView2·DLL 검색)

**Files:**
- Create: `desktop/rust-toolchain.toml`, `desktop/Cargo.toml`, `desktop/Cargo.lock`, `desktop/.cargo/config.toml`, `desktop/build.rs`, `desktop/tauri.conf.json`, `desktop/icons/make-icon.ps1`, `desktop/icons/icon.ico`, `desktop/ui/index.html`, `desktop/ui/style.css`, `desktop/src/lib.rs`, `desktop/src/main.rs`, `desktop/src/version.rs`
- Modify: `.gitignore`(`desktop/target/` 추가)
- 커밋하지 않음: `desktop/examples/spike_window.rs`(스파이크 뒤 삭제)

**Interfaces:**
- Produces:
  - 사용자가 설치할 도구(UAC가 필요하므로 **구현자가 아니라 사용자가** 실행; 구현자는 이 명령을 보고서 맨 위에 그대로 적고, 설치가 끝났다는 답을 받은 뒤 진행):
    ```powershell
    winget install --id Rustlang.Rustup --version 1.29.3 -e --source winget
    winget install --id Microsoft.VisualStudio.BuildTools -e --source winget --override "--quiet --wait --norestart --nocache --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
    ```
    (`--includeRecommended`가 MSVC x64/x86 빌드 도구와 최신 Windows 11 SDK를 함께 넣습니다. 새 PowerShell을 연 뒤) `rustup toolchain install 1.99.1 --profile minimal --component rustfmt,clippy --target x86_64-pc-windows-msvc`
  - `desktop/rust-toolchain.toml`:
    ```toml
    [toolchain]
    channel = "1.99.1"
    profile = "minimal"
    components = ["rustfmt", "clippy"]
    targets = ["x86_64-pc-windows-msvc"]
    ```
  - `desktop/.cargo/config.toml`(정적 CRT: 깨끗한 PC에 VC 재배포 패키지가 없어도 됨; 정적 import의 DLL은 System32에서만 찾음, Y13):
    ```toml
    [target.x86_64-pc-windows-msvc]
    rustflags = ["-C", "target-feature=+crt-static", "-C", "link-arg=/DEPENDENTLOADFLAG:0x800"]
    ```
  - `desktop/Cargo.toml`(이 과제에서 모든 의존성을 한 번에 고정; 이후 과제는 기능만 더함):
    ```toml
    [package]
    name = "mcp-monitor"
    version = "1.1.0"
    edition = "2024"
    rust-version = "1.99"
    publish = false
    build = "build.rs"

    [lib]
    name = "mcp_monitor"
    path = "src/lib.rs"

    [[bin]]
    name = "mcp-monitor"
    path = "src/main.rs"

    [features]
    default = []
    # Development only (Y24): `app --server-url`, keeps WEBVIEW2_* variables. Never in a release build.
    dev = []

    [dependencies]
    tauri = { version = "=2.12.5", features = ["tray-icon", "image-ico"] }
    tauri-plugin-single-instance = "=2.5.5"
    webview2-com = "=0.39.1"
    windows = { version = "=0.62.2", features = [
        "Win32_Foundation", "Win32_Security", "Win32_Security_Authorization", "Win32_Storage_FileSystem",
        "Win32_System_Services", "Win32_System_Registry", "Win32_System_Threading", "Win32_System_Console",
        "Win32_System_LibraryLoader", "Win32_System_RemoteDesktop", "Win32_System_Diagnostics_ToolHelp",
        "Win32_System_Com", "Win32_System_Memory", "Win32_System_SystemInformation", "Win32_System_ProcessStatus",
        "Win32_UI_Accessibility", "Win32_UI_WindowsAndMessaging", "Win32_UI_Input_KeyboardAndMouse",
        "Win32_UI_Shell", "Win32_Graphics_Gdi",
    ] }
    ureq = { version = "=3.5.1", default-features = false }
    serde = { version = "=1.0.229", features = ["derive"] }
    serde_json = "=1.0.154"
    sha2 = "=0.11.1"
    hmac = "=0.13.0"
    hex = "=0.4.3"
    getrandom = "=0.4.3"
    zstd = "=0.13.4"
    tar = "=0.4.46"
    time = { version = "=0.3.55", features = ["formatting", "macros"] }
    regex = "=1.13.1"

    [build-dependencies]
    tauri-build = { version = "=2.7.4", features = [] }
    serde = { version = "=1.0.229", features = ["derive"] }
    serde_json = "=1.0.154"
    sha2 = "=0.11.1"
    hex = "=0.4.3"
    zstd = "=0.13.4"
    tar = "=0.4.46"
    walkdir = "=2.5.0"

    [dev-dependencies]
    tempfile = "=3.27.0"

    [profile.release]
    lto = true
    codegen-units = 1
    strip = "symbols"
    ```
    (`panic = "abort"`를 쓰지 않습니다: 훅 콜백의 `catch_unwind`가 릴리스에서도 동작해야 함, Task 10.) 크레이트는 라이브러리(`src/lib.rs`, 모든 모듈과 `pub fn run(args: Vec<OsString>) -> i32`) + 얇은 바이너리(`src/main.rs`) 구조입니다 — 통합 테스트(`desktop/tests/*.rs`)가 라이브러리 API를 씁니다.
    `tauri`가 끌어오는 `webview2-com`·`windows`·`tauri-utils`가 위 버전과 다르면(`cargo tree -i webview2-com`, `cargo tree -i windows -e normal`), **tauri가 쓰는 버전으로** 이 파일을 고쳐 한 벌만 남기고 보고서에 적습니다(Y3). `tauri-build`도 `tauri 2.12.5`의 `tauri-utils`와 같은 버전을 쓰는 릴리스로 맞춥니다.
  - `desktop/tauri.conf.json`(창은 코드에서 만듦; IPC 없음; 원격 주소에는 권한 없음; 번들러 끔 — MSI 없음, D2):
    ```json
    {
      "$schema": "https://schema.tauri.app/config/2",
      "productName": "MCP Monitor",
      "version": "1.1.0",
      "identifier": "local.mcpmonitor.desktop",
      "build": { "frontendDist": "ui" },
      "app": {
        "withGlobalTauri": false,
        "windows": [],
        "security": { "csp": "default-src 'self'; style-src 'self'; img-src 'self'; script-src 'none'; connect-src 'none'; frame-ancestors 'none'" }
      },
      "bundle": { "active": false, "icon": ["icons/icon.ico"] }
    }
    ```
  - `desktop/build.rs`(이 과제에서는 `fn main() { tauri_build::build() }`; Task 3이 payload를 더함).
  - `desktop/src/version.rs`:
    - `#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)] pub struct Version(pub u32, pub u32, pub u32)`; `Version::parse(s: &str) -> Option<Version>`는 정확히 `숫자.숫자.숫자`(앞뒤 공백·접미사·선행 `+` 거부, 각 부분 `u32`).
    - `pub const PRODUCT: &str = env!("CARGO_PKG_VERSION");`
    - `pub fn version_line(product: &str, payload_sha: &str, kind: &str, dev: bool) -> String` = `mcp-monitor <product> (payload <sha 앞 12자>, <kind>[, dev])`.
  - `desktop/src/lib.rs`(`pub mod version;` + `pub fn run(args: Vec<OsString>) -> i32`: `--version`이면 `version_line(PRODUCT, "000000000000", "none", cfg!(feature = "dev"))`를 출력하고 0, 그 밖은 `eprintln!("오류: 아직 지원하지 않는 명령입니다")` + 2)와 `desktop/src/main.rs`(`#![cfg_attr(not(test), windows_subsystem = "windows")]`, `std::process::exit(mcp_monitor::run(std::env::args_os().skip(1).collect()))`). Task 4가 `run`을 채웁니다.
  - 아이콘: `desktop/icons/make-icon.ps1`(아래 코드)을 한 번 실행해 `icon.ico`(16/32/48/256, PNG 프레임)를 만들고 둘 다 커밋합니다.
  - `desktop/ui/index.html` + `style.css`(연결 중 페이지; 스크립트 없음, `:target`으로 상태 전환, 640×600에서 가로 스크롤 없음): 기본 `<section id="waiting">`: 제목 "MCP Monitor", 본문 "MCP Monitor 서비스에 연결하는 중입니다…"; `<section id="stopped">`(`#stopped`일 때만 보임): "서비스가 응답하지 않습니다. 관리자 PowerShell에서 `sc.exe start mcp-monitor`로 서비스를 시작하세요. 이 창은 5초마다 다시 연결합니다."; `prefers-color-scheme: dark` 대응, 시스템 글꼴, `max-width: 36rem; margin: 0 auto; padding: 24px`. 외부 리소스 없음.

```powershell
# desktop/icons/make-icon.ps1 — draws icon.ico (16, 32, 48, 256; PNG frames). Run once; the .ico is committed.
Add-Type -AssemblyName System.Drawing
$sizes = 16, 32, 48, 256
$frames = foreach ($s in $sizes) {
    $bmp = New-Object System.Drawing.Bitmap $s, $s
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.Clear([System.Drawing.Color]::Transparent)
    $g.FillEllipse((New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 37, 99, 235))), 0, 0, $s - 1, $s - 1)
    $pen = New-Object System.Drawing.Pen ([System.Drawing.Color]::White), ([single][Math]::Max(1, $s / 10))
    $m = [single]($s * 0.28)
    $pts = [System.Drawing.PointF[]]@(
        (New-Object System.Drawing.PointF $m, ([single]$s - $m)), (New-Object System.Drawing.PointF $m, $m),
        (New-Object System.Drawing.PointF ([single]($s / 2)), ([single]($s * 0.55))),
        (New-Object System.Drawing.PointF ([single]$s - $m), $m), (New-Object System.Drawing.PointF ([single]$s - $m), ([single]$s - $m)))
    $g.DrawLines($pen, $pts)
    $g.Dispose()
    $ms = New-Object System.IO.MemoryStream
    $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png); $bmp.Dispose()
    , $ms.ToArray()
}
$out = New-Object System.IO.MemoryStream
$w = New-Object System.IO.BinaryWriter $out
$w.Write([uint16]0); $w.Write([uint16]1); $w.Write([uint16]$sizes.Count)
$offset = 6 + 16 * $sizes.Count
for ($i = 0; $i -lt $sizes.Count; $i++) {
    $s = $sizes[$i]; $len = $frames[$i].Length
    $w.Write([byte]($s % 256)); $w.Write([byte]($s % 256)); $w.Write([byte]0); $w.Write([byte]0)
    $w.Write([uint16]1); $w.Write([uint16]32); $w.Write([uint32]$len); $w.Write([uint32]$offset)
    $offset += $len
}
foreach ($f in $frames) { $w.Write($f) }
[System.IO.File]::WriteAllBytes((Join-Path $PSScriptRoot "icon.ico"), $out.ToArray())
```

- [ ] **Step 1: 도구 확인(사용자 설치 뒤)** — Run(새 PowerShell): `rustup --version` → `rustup 1.29.3`, `cargo --version` → `cargo 1.99.1 …`(`desktop/`에서), `rustc -vV` → `host: x86_64-pc-windows-msvc`, `& "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath` → 경로 한 줄. 하나라도 다르면 멈추고 보고합니다.

- [ ] **Step 2: 실패하는 테스트 작성**

```rust
// desktop/src/version.rs (tests)
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_and_compares_versions() {
        assert_eq!(Version::parse("1.1.0"), Some(Version(1, 1, 0)));
        assert!(Version::parse("1.10.0").unwrap() > Version::parse("1.9.9").unwrap());
        assert!(Version::parse("2.0.0").unwrap() > Version::parse("1.99.99").unwrap());
        for bad in ["1.1", "1.1.0-rc1", " 1.1.0", "1.1.0 ", "+1.1.0", "1..0", "a.b.c", "1.1.0.0", ""] {
            assert_eq!(Version::parse(bad), None, "{bad:?}");
        }
    }

    #[test]
    fn version_line_names_the_payload() {
        assert_eq!(version_line("1.1.0", "0123456789abcdef", "fixture", false), "mcp-monitor 1.1.0 (payload 0123456789ab, fixture)");
        assert_eq!(version_line("1.1.0", "0123456789abcdef", "release", true), "mcp-monitor 1.1.0 (payload 0123456789ab, release, dev)");
        assert_eq!(PRODUCT, "1.1.0");
    }
}
```

- [ ] **Step 3: 실패 확인** — Run: `cargo test --locked` → 컴파일 실패(구현 없음). 이 단계에서 `Cargo.lock`이 처음 생기므로 처음 한 번은 `cargo generate-lockfile` 뒤 `--locked`.

- [ ] **Step 4: 구현** — 위 Interfaces대로. `make-icon.ps1` 실행: `powershell -NoProfile -ExecutionPolicy Bypass -File desktop\icons\make-icon.ps1`.

- [ ] **Step 5: 스파이크(커밋하지 않음)** — 결과를 보고서의 "스파이크" 절에 적습니다(각 항목 통과/실패와 증거).
  1. `cargo build --locked` → `build.rs`(tauri-build)가 실행되고 `target\debug\mcp-monitor.exe`가 생김. SAC가 빌드 스크립트·exe를 막으면 멈춤.
  2. `target\debug\mcp-monitor.exe --version | Write-Output` → `mcp-monitor 1.1.0 (payload 000000000000, none)`. `cargo build --release --locked` 뒤 같은 명령. 둘 다 SAC에 막히지 않음(`Get-WinEvent -LogName Microsoft-Windows-CodeIntegrity/Operational -MaxEvents 20`에 `mcp-monitor.exe` 차단 없음).
  3. `desktop/examples/spike_window.rs`: `tauri::Builder::default().setup(|app| { WebviewWindowBuilder::new(app, "spike", WebviewUrl::External("http://127.0.0.1:<P>/board".parse()?)).always_on_top(true).closable(false).skip_taskbar(true).incognito(true).inner_size(640.0, 600.0).center().build()?; Ok(()) }).run(tauri::generate_context!())`. 서버를 `server/`에서 `uv run python -m app --root %TEMP%\mcpmon-spike --local-port <P> --external-port <P+1> --session-source none`로 띄우고 `cargo run --example spike_window` → 보드가 640×600 창에 보이고, 최상위이며, 닫기 단추가 비활성, 작업 표시줄에 없음. 스크린숏을 보고서에 첨부(경로).
  4. 같은 예제의 `main` 첫 줄에 `SetDefaultDllDirectories(LOAD_LIBRARY_SEARCH_SYSTEM32)`를 넣고 다시 실행 → 창이 똑같이 뜨면 Y13의 `SYSTEM32` 확정. WebView2 만들기가 실패하면 `LOAD_LIBRARY_SEARCH_DEFAULT_DIRS`로 바꿔 확인하고 그 값을 보고(Task 4가 그 값을 씀).
  5. `cargo install cargo-audit --version 0.22.2 --locked` → `cargo audit --version` → `cargo-audit 0.22.2`; `desktop/`에서 `cargo audit` → 취약점 0(경고는 목록으로 보고, Y4). SAC가 `cargo-audit.exe`를 막으면 멈춤.
  6. `dumpbin /loadconfig target\release\mcp-monitor.exe | findstr /i "Dependent"`(개발자 PowerShell 또는 vswhere로 찾은 `dumpbin.exe`) → `800 Dependent Load Flag`.
  스파이크 뒤 `desktop/examples/`를 지웁니다.

- [ ] **Step 6: 통과 확인** — Run: `cargo fmt --check`, `cargo clippy --locked --all-targets -- -D warnings`, `cargo test --locked` → 통과. `cargo tree -d -e normal | findstr /i "windows webview2-com tauri-utils"` → 같은 이름이 두 버전으로 나오지 않음.

- [ ] **Step 7: Commit** — `git add .gitignore desktop && git commit -m "build: Rust 1.99.1 desktop workspace (Tauri 2.12.5, pinned crates, static CRT, System32-only DLL loading)"`

---

### Task 2: 서버 쪽 — 데스크톱 묶음(`agent: desktop`, `webview` 고지), payload 출력, 서버 exe 이름, 버전 1.1.0

**Files:**
- Modify: `server/app/bundle.py`, `server/app/activity/agent_supervisor.py`(`AgentOptions.dialog`), `server/app/collect/cli.py`(`--agent-dialog`), `server/app/__init__.py`(`__version__ = "1.1.0"`), `web/package.json`(`"version": "1.1.0"`), `install/build.ps1`, `install/pyinstaller/mcp-monitor.spec`(이름 `mcp-monitor-server`)
- Delete: `install/pyinstaller/mcp-agent.spec`, `install/pyinstaller/entry_agent.py`
- Modify (tests): `server/tests/test_bundle_paths.py`, `server/tests/test_main_cli.py`, `server/tests/test_bundle.py`

**Interfaces:**
- Produces:
  - `app.bundle`: `AgentKind = Literal["python", "desktop"]`; `Bundle(root, layout, version, agent: AgentKind = "python")`(기본값이 있어 기존 `Bundle(root, layout, version)` 비교가 그대로 맞음). `find_bundle`은 `bundle.json`의 `"agent"`가 없으면 `"python"`, `"python"`/`"desktop"`이면 그 값, 그 밖이면 묶음 아님(None).
  - `agent_command(b)`: `b.agent == "desktop"` → `(str(b.root / "mcp-monitor.exe"), "agent")`; 그 밖은 지금과 같음.
  - `default_agent_dialog(b: Bundle | None) -> Literal["edge", "webview"]`: desktop 묶음이면 `"webview"`, 아니면 `"edge"`.
  - `AgentOptions.dialog: Literal["edge", "print", "webview"]`. `agent_argv`·`agent_env`는 그대로(`--dialog webview`가 그대로 전달됨; `command`가 있으면 `PYTHONPATH` 없음).
  - CLI `--agent-dialog` 선택지 `("edge", "print", "webview")`, 기본값 `default_agent_dialog(bundle)`. 도움말: `"notice window: webview (the desktop agent's WebView2 window; default in a desktop bundle), edge (the development agent's Edge app window), or print (DEV/E2E: the agent writes the notice URL to <root>/run/agent-<session>.url)"`.
  - `install/pyinstaller/mcp-monitor.spec`: `EXE(name="mcp-monitor-server")`, `COLLECT(name="monitor")` → `<payload>\bin\monitor\mcp-monitor-server.exe`. 콘솔 프로그램 그대로.
  - `install/build.ps1`(이제 **payload 빌더**): 매개변수 `[-Out]`(기본 `<repo>\dist\payload`), `[-SkipAudit]`, `-Layout`은 없앰(항상 pyinstaller). 단계: pip-audit·pnpm audit(그대로) → pyyaml 휠 확인(그대로) → `pnpm build` → 폴더(`.partial` 규칙 그대로) → `web\`(`.vite` 제외) → `docs\OPERATIONS.md` → PyInstaller `mcp-monitor.spec` **하나만** → `bundle.json` = `{layout: "pyinstaller", version, python, built_at, commit, agent: "desktop"}`(UTF-8 BOM 없음) → `.partial` 삭제. **zip·sha256·`install\` 스크립트 복사는 하지 않습니다**(설치기는 Rust exe, Y8). 마지막 줄 `==> done: <Out>`.
  - `test_bundle.py`(마커 `bundle`, `MCPMON_BUNDLE` = payload 폴더): `monitor_cmd()` = `[B\bin\monitor\mcp-monitor-server.exe]`; `test_bundle_metadata_and_files`는 키 집합 `{"layout","version","python","built_at","commit","agent"}`, `agent == "desktop"`, `install\`·`bin\agent\` 없음; `test_bundle_install_scripts_plan_from_the_bundle`·`test_bundle_agent_starts` 삭제(에이전트는 Task 13의 `-m desktop`); `test_bundle_ignores_pythonpath`는 monitor만; 그리고 `test_install_scripts`에서 `ps`·`scratch_path`를 가져오던 import를 없애고 `scratch_path` 픽스처를 `tests/live.py`로 옮겨 씁니다(Task 14에서 `test_install_scripts.py`를 지우기 위함).

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_bundle_paths.py (추가)
from app.bundle import default_agent_dialog


def write_bundle(root: Path, **kw) -> None:
    (root / "bundle.json").write_text(json.dumps({"layout": "pyinstaller", "version": "1.1.0", **kw}), "utf-8")


def server_exe(root: Path) -> Path:
    exe = root / "bin" / "monitor" / "mcp-monitor-server.exe"
    exe.parent.mkdir(parents=True, exist_ok=True); exe.write_bytes(b"")
    return exe


def test_desktop_bundle_runs_the_rust_agent_with_a_webview_notice(tmp_path):
    write_bundle(tmp_path, agent="desktop")
    b = find_bundle(server_exe(tmp_path))
    assert b == Bundle(tmp_path, "pyinstaller", "1.1.0", "desktop")
    assert agent_command(b) == (str(tmp_path / "mcp-monitor.exe"), "agent")
    assert default_agent_dialog(b) == "webview"


def test_python_agent_is_the_default_and_an_unknown_agent_is_no_bundle(tmp_path):
    write_bundle(tmp_path)
    b = find_bundle(server_exe(tmp_path))
    assert b is not None and b.agent == "python" and default_agent_dialog(b) == "edge"
    assert default_agent_dialog(None) == "edge"
    write_bundle(tmp_path, agent="java")
    assert find_bundle(server_exe(tmp_path)) is None


def test_webview_dialog_argv_and_env():
    o = AgentOptions(command=("C:/P/mcp-monitor.exe", "agent"), dialog="webview")
    assert agent_argv(o, "http://127.0.0.1:8700", 2) == [
        "C:/P/mcp-monitor.exe", "agent", "--server", "http://127.0.0.1:8700", "--dialog", "webview"]
    assert agent_env(o, "tok", "ab" * 32) == {"MCPMON_AGENT_TOKEN": "tok", "MCPMON_AGENT_SERVER_KEY": "ab" * 32}
```

```python
# server/tests/test_main_cli.py (추가)
def test_agent_dialog_defaults_to_webview_in_a_desktop_bundle(tmp_path, monkeypatch):
    (tmp_path / "bundle.json").write_text(json.dumps({"layout": "pyinstaller", "version": "1.1.0", "agent": "desktop"}), "utf-8")
    exe = tmp_path / "bin" / "monitor" / "mcp-monitor-server.exe"; exe.parent.mkdir(parents=True); exe.write_bytes(b"")
    monkeypatch.setattr(sys, "executable", str(exe))
    ns = parse_args([])
    assert ns.agent_dialog == "webview" and ns.agent_command == (str(tmp_path / "mcp-monitor.exe"), "agent")
    assert parse_args(["--agent-dialog", "print"]).agent_dialog == "print"
```

(`test_main_cli.py`의 기존 `parse_args`·`sys`·`json` import를 그대로 씁니다. `parse_args`가 `find_bundle()`을 `sys.executable` 기준으로 부르지 않는다면, 그 함수가 쓰는 진입점을 monkeypatch하고 이름 대응을 보고합니다.)

- [ ] **Step 2: 실패 확인** — Run: `uv run python -m pytest tests/test_bundle_paths.py tests/test_main_cli.py -v` → FAIL

- [ ] **Step 3: 구현** — 위 Interfaces대로. `server/tests/test_agent_supervisor.py`·`test_integration_agent.py`는 그대로 통과해야 합니다. `scratch_path`를 `tests/live.py`로 옮길 때 `test_install_scripts.py`는 `from tests.live import scratch_path`로 바꿔 같은 이름의 픽스처(`tmp_path`)를 그대로 씁니다.

- [ ] **Step 4: payload 빌드** — Run(저장소 루트, PowerShell): `powershell -NoProfile -ExecutionPolicy Bypass -File install\build.ps1` → `==> done: …\dist\payload`. `dist\payload\bin\monitor\mcp-monitor-server.exe --version | Write-Output` → `mcp-monitor 1.1.0`. Run(server): `$env:MCPMON_BUNDLE = "<repo>\dist\payload"; uv run python -m pytest -m bundle -q` → 통과.

- [ ] **Step 5: 통과 확인** — Run(server): `uv run python -m pytest -q`, `uv run python -m ruff check app tests`, `uv run python -m mypy` → 통과/0건. Run(web): `pnpm test` → 통과(버전 문자열을 단언하는 테스트가 있으면 1.1.0으로).

- [ ] **Step 6: Commit** — `git commit -m "feat: desktop bundle (agent: desktop, webview notice dialog), payload-only build.ps1, server exe renamed mcp-monitor-server.exe, version 1.1.0"`

---

### Task 3: payload 내장 — 결정적 tar.zst, 파일별 SHA-256 매니페스트, 안전한 풀기

**Files:**
- Create: `desktop/src/payload_pack.rs`(빌드 스크립트와 크레이트가 함께 씀), `desktop/src/payload.rs`, `desktop/src/winutil.rs`(이 과제에서는 `system_dir`·`system_tool`만), `desktop/tests/fixtures/payload/**`
- Modify: `desktop/build.rs`, `desktop/src/lib.rs`(모듈 등록)

**Interfaces:**
- Produces:
  - `payload_pack`(build.rs에서 `#[path = "src/payload_pack.rs"] mod payload_pack;`로 포함):
    - `#[derive(Serialize, Deserialize, Clone, Debug, PartialEq)] pub struct ManifestFile { pub path: String, pub size: u64, pub sha256: String }` — `path`는 `/`로 나눈 상대 경로.
    - `#[derive(Serialize, Deserialize, Clone, Debug, PartialEq)] pub struct Manifest { pub files: Vec<ManifestFile>, pub bundle: serde_json::Value }` — `files`는 `path`의 바이트 순 정렬, `bundle`은 payload의 `bundle.json` 내용.
    - `pub struct PackedPayload { pub archive: Vec<u8>, pub manifest: Manifest, pub sha256: String }`
    - `pub fn sha256_hex(bytes: &[u8]) -> String`(소문자 64자)
    - `pub fn pack_dir(dir: &Path, level: i32) -> Result<PackedPayload, String>`: `walkdir`로 정규 파일만 모아 상대 경로 바이트 순으로 정렬. 정션·심볼릭 링크(`FILE_ATTRIBUTE_REPARSE_POINT`)가 하나라도 있으면 `Err("<상대 경로>: 링크는 payload에 넣을 수 없습니다")`. 이름의 각 부분은 비어 있지 않고 `.`/`..`가 아니며 `\ / : * ? " < > |`와 제어 문자를 포함하지 않음(위반이면 Err). tar(GNU 헤더) 항목은 **파일만**(디렉터리 항목 없음), `mode 0o644`, `mtime 0`, `uid/gid 0`, 사용자·그룹 이름 빈 값. zstd `level`(릴리스 19, fixture 3). `bundle.json`이 없거나 JSON 객체가 아니면 Err.
    - `pub fn check_release_layout(m: &Manifest, cargo_version: &str) -> Result<(), String>`: 필수 파일 `bundle.json`, `bin/monitor/mcp-monitor-server.exe`, `web/board.html`, `web/admin.html`, `web/notice.html`; `bundle.layout == "pyinstaller"`, `bundle.agent == "desktop"`, `bundle.version == cargo_version`; 루트에 `mcp-monitor.exe`가 없어야 함(설치기가 자신을 넣음). 오류 문구는 문제 된 이름을 포함.
  - `desktop/build.rs`:
    ```rust
    #[path = "src/payload_pack.rs"]
    mod payload_pack;

    use std::{env, fs, path::PathBuf};

    fn main() {
        println!("cargo:rerun-if-env-changed=MCPMON_PAYLOAD_DIR");
        let out = PathBuf::from(env::var("OUT_DIR").unwrap());
        let (dir, kind) = match env::var("MCPMON_PAYLOAD_DIR") {
            Ok(d) if !d.is_empty() => (PathBuf::from(d), "release"),
            _ => (PathBuf::from("tests/fixtures/payload"), "fixture"),
        };
        let packed = payload_pack::pack_dir(&dir, if kind == "release" { 19 } else { 3 })
            .unwrap_or_else(|e| panic!("payload {}: {e}", dir.display()));
        println!("cargo:rerun-if-changed={}", dir.display());
        for f in &packed.manifest.files {
            println!("cargo:rerun-if-changed={}", dir.join(&f.path).display());
        }
        if kind == "release" {
            payload_pack::check_release_layout(&packed.manifest, &env::var("CARGO_PKG_VERSION").unwrap())
                .unwrap_or_else(|e| panic!("release payload: {e}"));
        }
        fs::write(out.join("payload.tar.zst"), &packed.archive).unwrap();
        fs::write(out.join("payload.sha256"), &packed.sha256).unwrap();
        fs::write(out.join("payload-manifest.json"), serde_json::to_string(&packed.manifest).unwrap()).unwrap();
        fs::write(out.join("payload-kind.txt"), kind).unwrap();
        tauri_build::build();
    }
    ```
  - `payload`:
    - `pub static ARCHIVE: &[u8] = include_bytes!(concat!(env!("OUT_DIR"), "/payload.tar.zst"));`, `pub const ARCHIVE_SHA256: &str = include_str!(…"/payload.sha256")`, `const MANIFEST_JSON: &str = include_str!(…"/payload-manifest.json")`, `pub const KIND: &str = include_str!(…"/payload-kind.txt")`(`"fixture"` | `"release"`).
    - `pub fn manifest() -> Manifest`(파싱 실패는 빌드 결함이므로 panic), `pub const STAGING_MARKER: &str = ".mcp-monitor-staging"`.
    - `#[derive(Debug)] pub enum PayloadError { ArchiveHash, Corrupt(String), UnexpectedEntry(String), FileHash(String), Size(String), Missing(String), DestinationExists(String), Io(String) }` + `Display`(한국어: `ArchiveHash` = "실행 파일 안의 payload가 손상되었습니다(해시 불일치). 실행 파일을 다시 받으세요.", `FileHash(p)` = "<p>의 해시가 매니페스트와 다릅니다" 등).
    - `pub fn verify_archive(archive: &[u8], sha256: &str) -> Result<(), PayloadError>`(둘 다 소문자 hex로 비교).
    - `pub fn extract(archive: &[u8], m: &Manifest, dest: &Path) -> Result<u64, PayloadError>`: `dest`가 있으면 `DestinationExists`. `create_dir_all(dest)` 뒤 **가장 먼저** `dest\.mcp-monitor-staging`(내용 `{"product":"mcp-monitor"}`)을 씁니다. 항목마다: 종류가 `Regular`가 아니면 `UnexpectedEntry(이름)`; `entry.path()`의 모든 부분이 `Component::Normal`이 아니면(절대·`..`·드라이브 접두어·`C:x`) `UnexpectedEntry`; `/`로 이은 이름이 매니페스트에 없거나 두 번째로 나오면 `UnexpectedEntry`; 부모 폴더를 만들고 `OpenOptions::new().write(true).create_new(true)`로 쓰면서 SHA-256을 계산해 크기(`Size`)·해시(`FileHash`) 비교. zstd·tar 읽기 오류는 `Corrupt`. 끝나면 매니페스트의 모든 파일이 나왔는지(`Missing(첫 번째)`) 확인하고 쓴 바이트 합을 돌려줍니다. 실패하면 `dest`를 그대로 둡니다(호출자가 마커로 확인 후 지움, Task 7).
  - `winutil::system_dir() -> PathBuf`(`GetSystemDirectoryW`), `winutil::system_tool(name: &str) -> PathBuf`(= `system_dir().join(name)`; 현재 폴더·PATH를 절대 쓰지 않음).
  - fixture payload `desktop/tests/fixtures/payload/`: `bundle.json` = `{"layout": "pyinstaller", "version": "1.1.0", "python": "3.15.2", "built_at": "fixture", "commit": "fixture", "agent": "desktop"}`, `bin/monitor/mcp-monitor-server.exe`(텍스트 `fixture: not a program`), `web/board.html`·`web/admin.html`·`web/notice.html`(각 `<!doctype html><title>fixture</title>`), `docs/OPERATIONS.md`(`# fixture`).

- [ ] **Step 1: 실패하는 테스트 작성**

```rust
// desktop/src/payload.rs (tests)
#[cfg(test)]
mod tests {
    use super::*;
    use crate::payload_pack::{check_release_layout, pack_dir, sha256_hex, Manifest, ManifestFile, PackedPayload};
    use std::fs;
    use std::path::Path;

    fn sample(dir: &Path) {
        for d in ["bin/monitor", "web", "docs"] {
            fs::create_dir_all(dir.join(d)).unwrap();
        }
        fs::write(dir.join("bundle.json"), r#"{"layout":"pyinstaller","version":"1.1.0","python":"3.15.2","built_at":"x","commit":"y","agent":"desktop"}"#).unwrap();
        fs::write(dir.join("bin/monitor/mcp-monitor-server.exe"), b"MZ fake server").unwrap();
        for page in ["board", "admin", "notice"] {
            fs::write(dir.join(format!("web/{page}.html")), format!("<!doctype html>{page} 보드")).unwrap();
        }
        fs::write(dir.join("docs/OPERATIONS.md"), "# 운영").unwrap();
    }

    fn packed() -> (tempfile::TempDir, PackedPayload) {
        let src = tempfile::tempdir().unwrap();
        sample(src.path());
        let p = pack_dir(src.path(), 3).unwrap();
        (src, p)
    }

    #[test]
    fn pack_is_deterministic_and_extract_round_trips() {
        let (src, a) = packed();
        std::thread::sleep(std::time::Duration::from_millis(20));
        fs::write(src.path().join("web/board.html"), "<!doctype html>board 보드").unwrap(); // same bytes, newer mtime
        let b = pack_dir(src.path(), 3).unwrap();
        assert_eq!(a.archive, b.archive);
        assert_eq!(a.sha256, sha256_hex(&a.archive));
        verify_archive(&a.archive, &a.sha256).unwrap();
        let out = tempfile::tempdir().unwrap();
        let dest = out.path().join("MCP Monitor.staging");
        let written = extract(&a.archive, &a.manifest, &dest).unwrap();
        assert_eq!(written, a.manifest.files.iter().map(|f| f.size).sum::<u64>());
        assert_eq!(fs::read(dest.join("bin/monitor/mcp-monitor-server.exe")).unwrap(), b"MZ fake server");
        assert_eq!(fs::read_to_string(dest.join("web/board.html")).unwrap(), "<!doctype html>board 보드");
        assert!(dest.join(STAGING_MARKER).is_file());
        let paths: Vec<&str> = a.manifest.files.iter().map(|f| f.path.as_str()).collect();
        assert_eq!(paths, ["bin/monitor/mcp-monitor-server.exe", "bundle.json", "docs/OPERATIONS.md", "web/admin.html", "web/board.html", "web/notice.html"]);
        assert_eq!(a.manifest.bundle["agent"], "desktop");
    }

    #[test]
    fn a_wrong_archive_hash_is_refused() {
        let (_src, a) = packed();
        assert!(matches!(verify_archive(&a.archive, &"0".repeat(64)), Err(PayloadError::ArchiveHash)));
        let mut cut = a.archive.clone();
        cut.truncate(cut.len() / 2);
        assert!(matches!(verify_archive(&cut, &a.sha256), Err(PayloadError::ArchiveHash)));
        let out = tempfile::tempdir().unwrap();
        assert!(extract(&cut, &a.manifest, &out.path().join("s")).is_err());
    }

    #[test]
    fn a_file_whose_bytes_differ_from_the_manifest_is_refused() {
        let (_src, a) = packed();
        let mut m = a.manifest.clone();
        m.files[0].sha256 = "0".repeat(64);
        let out = tempfile::tempdir().unwrap();
        match extract(&a.archive, &m, &out.path().join("s")) {
            Err(PayloadError::FileHash(p)) => assert_eq!(p, "bin/monitor/mcp-monitor-server.exe"),
            other => panic!("{other:?}"),
        }
    }

    #[test]
    fn an_entry_missing_from_the_manifest_is_refused() {
        let (_src, a) = packed();
        let mut m = a.manifest.clone();
        m.files.retain(|f| f.path != "web/notice.html");
        let out = tempfile::tempdir().unwrap();
        assert!(matches!(extract(&a.archive, &m, &out.path().join("s")), Err(PayloadError::UnexpectedEntry(p)) if p == "web/notice.html"));
    }

    #[test]
    fn a_manifest_file_missing_from_the_archive_is_refused() {
        let (_src, a) = packed();
        let mut m = a.manifest.clone();
        m.files.push(ManifestFile { path: "web/extra.html".into(), size: 1, sha256: "0".repeat(64) });
        let out = tempfile::tempdir().unwrap();
        assert!(matches!(extract(&a.archive, &m, &out.path().join("s")), Err(PayloadError::Missing(p)) if p == "web/extra.html"));
    }

    /// A one-entry tar.zst whose header name is written byte for byte (`Header::set_path` refuses `..`).
    fn raw_archive(name: &str, kind: tar::EntryType) -> Vec<u8> {
        let mut header = tar::Header::new_gnu();
        let bytes = name.as_bytes();
        header.as_gnu_mut().unwrap().name[..bytes.len()].copy_from_slice(bytes);
        header.set_entry_type(kind);
        header.set_size(if kind == tar::EntryType::Regular { 1 } else { 0 });
        header.set_mode(0o644);
        if kind != tar::EntryType::Regular {
            header.set_link_name("target").unwrap();
        }
        header.set_cksum();
        let mut b = tar::Builder::new(Vec::new());
        let data: &[u8] = if kind == tar::EntryType::Regular { b"x" } else { b"" };
        b.append(&header, data).unwrap();
        zstd::encode_all(&b.into_inner().unwrap()[..], 3).unwrap()
    }

    #[test]
    fn traversal_absolute_and_link_entries_are_refused() {
        let out = tempfile::tempdir().unwrap();
        let cases = [("../evil.exe", tar::EntryType::Regular), ("a/../../evil.exe", tar::EntryType::Regular),
                     ("/evil.exe", tar::EntryType::Regular), ("C:/evil.exe", tar::EntryType::Regular),
                     ("C:evil.exe", tar::EntryType::Regular), ("web/link", tar::EntryType::Symlink),
                     ("web/hard", tar::EntryType::Link), ("web/dir/", tar::EntryType::Directory)];
        for (i, (name, kind)) in cases.into_iter().enumerate() {
            let m = Manifest { files: vec![ManifestFile { path: name.into(), size: 1, sha256: sha256_hex(b"x") }], bundle: serde_json::json!({}) };
            let dest = out.path().join(format!("s{i}"));
            assert!(matches!(extract(&raw_archive(name, kind), &m, &dest), Err(PayloadError::UnexpectedEntry(_))), "{name}");
        }
        assert!(!out.path().join("evil.exe").exists());
        assert!(!Path::new("C:/evil.exe").exists());
    }

    #[test]
    fn extract_refuses_an_existing_destination() {
        let (_src, a) = packed();
        let out = tempfile::tempdir().unwrap();
        let dest = out.path().join("s");
        fs::create_dir(&dest).unwrap();
        assert!(matches!(extract(&a.archive, &a.manifest, &dest), Err(PayloadError::DestinationExists(_))));
        assert_eq!(fs::read_dir(&dest).unwrap().count(), 0);
    }

    #[test]
    fn release_layout_needs_the_server_web_and_matching_version() {
        let (src, a) = packed();
        check_release_layout(&a.manifest, "1.1.0").unwrap();
        assert!(check_release_layout(&a.manifest, "1.2.0").unwrap_err().contains("1.2.0"));
        fs::remove_file(src.path().join("web/notice.html")).unwrap();
        assert!(check_release_layout(&pack_dir(src.path(), 3).unwrap().manifest, "1.1.0").unwrap_err().contains("web/notice.html"));
        sample(src.path());
        fs::write(src.path().join("mcp-monitor.exe"), b"x").unwrap();
        assert!(check_release_layout(&pack_dir(src.path(), 3).unwrap().manifest, "1.1.0").unwrap_err().contains("mcp-monitor.exe"));
        fs::remove_file(src.path().join("mcp-monitor.exe")).unwrap();
        fs::write(src.path().join("bundle.json"), r#"{"layout":"pyinstaller","version":"1.1.0","agent":"python"}"#).unwrap();
        assert!(check_release_layout(&pack_dir(src.path(), 3).unwrap().manifest, "1.1.0").unwrap_err().contains("agent"));
    }

    #[test]
    fn pack_refuses_links() {
        let src = tempfile::tempdir().unwrap();
        sample(src.path());
        let target = tempfile::tempdir().unwrap();
        let ok = std::process::Command::new(crate::winutil::system_tool("cmd.exe"))
            .args(["/d", "/c", "mklink", "/J"]).arg(src.path().join("web").join("j")).arg(target.path())
            .output().unwrap().status.success();
        assert!(ok);
        assert!(pack_dir(src.path(), 3).unwrap_err().contains("web/j"));
    }

    #[test]
    fn embedded_payload_verifies_and_matches_its_manifest() {
        verify_archive(ARCHIVE, ARCHIVE_SHA256).unwrap();
        let m = manifest();
        assert_eq!((m.bundle["layout"].as_str(), m.bundle["agent"].as_str()), (Some("pyinstaller"), Some("desktop")));
        assert!(["fixture", "release"].contains(&KIND));
        let out = tempfile::tempdir().unwrap();
        extract(ARCHIVE, &m, &out.path().join("s")).unwrap();
        assert!(out.path().join("s/bin/monitor/mcp-monitor-server.exe").is_file());
    }
}
```

- [ ] **Step 2: 실패 확인** — Run: `cargo test --locked payload` → FAIL(컴파일)

- [ ] **Step 3: 구현** — 위 Interfaces대로. `tempfile`은 `%TEMP%`를 씁니다: 여기서는 ACL을 다루지 않으므로 괜찮습니다(ACL 테스트는 Task 5의 `Scratch`).

- [ ] **Step 4: 통과 확인** — Rust 검사 3종 → 통과. Run: `$env:MCPMON_PAYLOAD_DIR = "<repo>\dist\payload"; cargo build --locked; Remove-Item Env:MCPMON_PAYLOAD_DIR` → 성공(Task 2의 payload로 릴리스 배치 검사 통과). 그 뒤 `cargo build --locked`로 다시 fixture를 내장합니다.

- [ ] **Step 5: Commit** — `git commit -m "feat(desktop): embed the server payload as a deterministic tar.zst with a per-file SHA-256 manifest and verified extraction"`

---

### Task 4: CLI, 모드 판별 진입점, 승격 재실행, DLL 검색 하드닝, `--version`

**Files:**
- Create: `desktop/src/cli.rs`, `desktop/tests/cli.rs`, `desktop/tests/common/mod.rs`
- Modify: `desktop/src/main.rs`, `desktop/src/lib.rs`, `desktop/src/winutil.rs`

**Interfaces:**
- Produces:
  - `cli`(손으로 쓴 해석기; 새 크레이트 없음):
    ```rust
    #[derive(Debug, Clone, PartialEq)]
    pub enum Command { Auto, App(AppArgs), Install(InstallArgs), Uninstall(UninstallArgs), AuditPolicy(AuditArgs),
                       Agent(AgentArgs), Autostart(bool), VerifyPayload(PathBuf), Version }
    #[derive(Debug, Clone, PartialEq, Default)]
    pub struct InstallArgs { pub install_dir: Option<PathBuf>, pub data_root: Option<PathBuf>, pub open_firewall: bool,
                             pub skip_audit_policy: bool, pub local_port: Option<u16>, pub external_port: Option<u16>,
                             pub dry_run: bool, pub interactive: bool }
    #[derive(Debug, Clone, PartialEq, Default)]
    pub struct UninstallArgs { pub install_dir: Option<PathBuf>, pub data_root: Option<PathBuf>, pub remove_data: bool,
                               pub restore_audit_policy: bool, pub dry_run: bool, pub interactive: bool }
    #[derive(Debug, Clone, PartialEq, Default)]
    pub struct AuditArgs { pub enable: bool, pub restore: Option<PathBuf>, pub data_root: Option<PathBuf>, pub dry_run: bool, pub interactive: bool }
    #[derive(Debug, Clone, Copy, PartialEq)] pub enum Dialog { Webview, Print }
    #[derive(Debug, Clone, PartialEq)]
    pub struct AgentArgs { pub server: String, pub dialog: Dialog, pub url_file: Option<PathBuf>, pub unreachable_exit_sec: f64 }
    #[derive(Debug, Clone, PartialEq, Default)]
    pub struct AppArgs { pub background: bool, pub server_url: Option<String> }
    #[derive(Debug, Clone, PartialEq)] pub struct ArgError(pub String);
    pub fn parse(args: &[String]) -> Result<Command, ArgError>;
    pub fn relaunch_args(cmd: &Command) -> Vec<String>;
    pub fn quote_arg(a: &str) -> String;           // MSVCRT rules (Plan 5 ConvertTo-CommandLineArg)
    pub fn join_command_line(args: &[String]) -> String;
    pub fn needs_relaunch(cmd: &Command, elevated: bool) -> bool;
    pub const DOCUMENTED_OPTIONS: &[&str];        // checked against the operations guide (Task 15)
    ```
    문법(부록 B 표와 같음): 인자 없음 → `Auto`; `--version` → `Version`; `app [--background] [--server-url <url>]`(`--server-url`은 `cfg!(feature = "dev")`일 때만, 아니면 ArgError); `install [--install-dir <p>] [--data-root <p>] [--open-firewall] [--skip-audit-policy] [--local-port <1-65535>] [--external-port <1-65535>] [--dry-run] [--interactive]`; `uninstall [--install-dir] [--data-root] [--remove-data] [--restore-audit-policy] [--dry-run] [--interactive]`; `audit-policy (--enable | --restore <file>) [--data-root] [--dry-run] [--interactive]`(둘 다 또는 둘 다 없음 → ArgError); `agent --server <url> [--dialog webview|print] [--url-file <p>] [--unreachable-exit-sec <초>]`(기본 webview, 120; `print`에 `--url-file` 필수; `edge`는 ArgError `"--dialog는 webview 또는 print입니다"`); `autostart on|off`; `verify-payload <빈 폴더>`. 같은 옵션 두 번, 알 수 없는 옵션·명령, 값 없는 옵션, 숫자가 아닌 값, 포트 0·65536 이상 → ArgError(한국어 한 문장, 옵션 이름 포함). 인자가 UTF-16으로 유효하지 않으면(`args_os`) ArgError.
  - `relaunch_args`: `Install`/`Uninstall`/`AuditPolicy`만; 해석한 필드에서 **다시 만듭니다**(원래 문자열을 넘기지 않음), 순서 = 위 문법 순서, `--dry-run`은 절대 넣지 않고 `--interactive`를 항상 끝에 둡니다. 그 밖의 명령은 빈 벡터.
  - `needs_relaunch(cmd, elevated)`: `elevated`면 false; `Install`/`Uninstall`/`AuditPolicy` 중 `interactive && !dry_run`일 때만 true.
  - `winutil`:
    - `harden_dll_search()`: `SetDefaultDllDirectories(LOAD_LIBRARY_SEARCH_SYSTEM32)`(Task 1 스파이크가 DEFAULT_DIRS로 정했으면 그 값) — `main`의 첫 줄.
    - `attach_parent_console()`: 표준 출력 핸들이 없을 때만 `AttachConsole(ATTACH_PARENT_PROCESS)`.
    - `is_elevated() -> bool`(`TokenElevation`), `assert_not_elevated()`(`is_elevated()`면 `panic!("tests must not run elevated: they could change this PC")`).
    - `elevate_and_wait(exe: &Path, args: &[String]) -> Result<i32, String>`: `ShellExecuteExW`(`lpVerb = "runas"`, `fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_NOASYNC | SEE_MASK_FLAG_NO_UI`, `lpParameters = join_command_line(args)`, `nShow = SW_SHOWNORMAL`) → `WaitForSingleObject(INFINITE)` → `GetExitCodeProcess`. UAC 취소(오류 1223) → `Err("관리자 권한 요청이 취소되었습니다.")`.
    - `message_box(text: &str, kind: MsgKind) -> MsgAnswer`(`MsgKind::{Info, Error, YesNo}`, 제목 "MCP Monitor", `MB_SETFOREGROUND | MB_TOPMOST`).
    - `current_user_sid() -> String`(`GetTokenInformation(TokenUser)` → `ConvertSidToStringSidW`), `command_line_to_argv(line) -> Vec<String>`(`CommandLineToArgvW` + `LocalFree`).
  - `main.rs`:
    ```rust
    #![cfg_attr(not(test), windows_subsystem = "windows")]
    fn main() {
        mcp_monitor::winutil::harden_dll_search();
        mcp_monitor::winutil::attach_parent_console();
        std::process::exit(mcp_monitor::run(std::env::args_os().skip(1).collect()));
    }
    ```
    `lib::run(args: Vec<OsString>) -> i32`: 해석 실패 → `eprintln!("오류: {}", e.0)` + 2. `Version` → `version_line(PRODUCT, payload::ARCHIVE_SHA256, payload::KIND, cfg!(feature = "dev"))` 출력 + 0. `needs_relaunch`면 `elevate_and_wait(current_exe, relaunch_args)`의 종료 코드(오류는 메시지 상자 + 1). 그 밖의 모드는 각 과제가 채우고, 이 과제에서는 `오류: 아직 지원하지 않는 명령입니다` + 2. `VerifyPayload(dir)` → 대상이 비어 있지 않으면 `오류: … 비어 있지 않습니다` + 2; `verify_archive` + `extract(…, dir.join("payload"))` → 성공이면 `payload OK: <파일 수> files, <바이트> bytes` + 0, 실패는 `[실패] verify-payload: <오류>` + 1.

- [ ] **Step 1: 실패하는 테스트 작성**

```rust
// desktop/src/cli.rs (tests)
#[cfg(test)]
mod tests {
    use super::*;

    fn s(v: &[&str]) -> Vec<String> {
        v.iter().map(|x| x.to_string()).collect()
    }

    #[test]
    fn no_arguments_is_auto_and_version_is_version() {
        assert_eq!(parse(&[]).unwrap(), Command::Auto);
        assert_eq!(parse(&s(&["--version"])).unwrap(), Command::Version);
    }

    #[test]
    fn install_options_are_parsed() {
        let c = parse(&s(&["install", "--install-dir", r"D:\설치 폴더", "--data-root", r"D:\데이터", "--open-firewall",
                           "--skip-audit-policy", "--local-port", "9700", "--external-port", "9701", "--dry-run"])).unwrap();
        assert_eq!(c, Command::Install(InstallArgs {
            install_dir: Some(r"D:\설치 폴더".into()), data_root: Some(r"D:\데이터".into()), open_firewall: true,
            skip_audit_policy: true, local_port: Some(9700), external_port: Some(9701), dry_run: true, interactive: false }));
        let a = parse(&s(&["agent", "--server", "http://127.0.0.1:8700"])).unwrap();
        assert_eq!(a, Command::Agent(AgentArgs { server: "http://127.0.0.1:8700".into(), dialog: Dialog::Webview, url_file: None, unreachable_exit_sec: 120.0 }));
    }

    #[test]
    fn malformed_arguments_are_errors() {
        let bad: &[&[&str]] = &[
            &["install", "--bogus"], &["install", "--local-port", "0"], &["install", "--local-port", "70000"],
            &["install", "--local-port", "x"], &["install", "--install-dir"], &["install", "--dry-run", "--dry-run"],
            &["agent"], &["agent", "--server", "http://127.0.0.1:8700", "--dialog", "edge"],
            &["agent", "--server", "http://127.0.0.1:8700", "--dialog", "print"], &["audit-policy"],
            &["audit-policy", "--enable", "--restore", "x.csv"], &["autostart", "maybe"], &["frobnicate"],
            &["verify-payload"],
        ];
        for b in bad {
            let e = parse(&s(b)).unwrap_err();
            assert!(!e.0.is_empty(), "{b:?}");
        }
        if !cfg!(feature = "dev") {
            assert!(parse(&s(&["app", "--server-url", "http://127.0.0.1:1"])).is_err());
        }
    }

    #[test]
    fn relaunch_args_carry_only_parsed_options_and_add_interactive() {
        let c = parse(&s(&["install", "--local-port", "9700", "--install-dir", r"C:\Program Files\MCP Monitor", "--open-firewall"])).unwrap();
        assert_eq!(relaunch_args(&c), s(&["install", "--install-dir", r"C:\Program Files\MCP Monitor", "--open-firewall", "--local-port", "9700", "--interactive"]));
        let u = parse(&s(&["uninstall", "--remove-data", "--interactive"])).unwrap();
        assert_eq!(relaunch_args(&u), s(&["uninstall", "--remove-data", "--interactive"]));
        let r = parse(&s(&["audit-policy", "--restore", r"C:\백업\a.csv"])).unwrap();
        assert_eq!(relaunch_args(&r), s(&["audit-policy", "--restore", r"C:\백업\a.csv", "--interactive"]));
        assert!(relaunch_args(&parse(&s(&["agent", "--server", "http://127.0.0.1:8700"])).unwrap()).is_empty());
    }

    #[test]
    fn dry_run_is_never_elevated() {
        let dry = parse(&s(&["install", "--dry-run", "--interactive"])).unwrap();
        assert!(!needs_relaunch(&dry, false));
        assert!(!relaunch_args(&parse(&s(&["install", "--dry-run"])).unwrap()).contains(&"--dry-run".to_string()));
        let real = parse(&s(&["install", "--interactive"])).unwrap();
        assert!(needs_relaunch(&real, false) && !needs_relaunch(&real, true));
        assert!(!needs_relaunch(&parse(&s(&["install"])).unwrap(), false)); // the plan's require_admin answers
        assert!(!needs_relaunch(&Command::Auto, false) && !needs_relaunch(&Command::Version, false));
    }

    #[test]
    fn quoting_survives_command_line_to_argv() {
        let cases = s(&[
            r#""C:\Program Files\MCP Monitor\bin\monitor\mcp-monitor-server.exe" service --root "C:\Data\x y" --local-port 8700"#,
            "name=MCP Monitor (8701)", "", "plain", r"a\\b\", r#"tail\"q"#, r"C:\dir with space\", r"/file:C:\관리 폴더\a.csv",
        ]);
        let line = format!("x.exe {}", join_command_line(&cases));
        assert_eq!(&crate::winutil::command_line_to_argv(&line)[1..], &cases[..]);
    }

    #[test]
    fn tests_are_not_elevated() {
        assert!(!crate::winutil::is_elevated(), "run the tests from a non-elevated shell");
    }
}
```

```rust
// desktop/tests/common/mod.rs
#![allow(dead_code)]
use std::path::{Path, PathBuf};
use std::process::{Command, Output};

pub fn exe() -> Command {
    Command::new(env!("CARGO_BIN_EXE_mcp-monitor"))
}

pub fn run(args: &[&str]) -> Output {
    exe().args(args).output().unwrap()
}

/// %LOCALAPPDATA%\mcp-monitor-install-tests\<random>: parents only this account, SYSTEM and Administrators can change.
pub struct Scratch(pub PathBuf);
impl Scratch {
    pub fn new() -> Scratch {
        let mut b = [0u8; 6];
        getrandom::fill(&mut b).unwrap();
        let p = PathBuf::from(std::env::var("LOCALAPPDATA").unwrap()).join("mcp-monitor-install-tests").join(hex::encode(b));
        std::fs::create_dir_all(&p).unwrap();
        Scratch(p)
    }
    pub fn join(&self, p: &str) -> PathBuf {
        self.0.join(p)
    }
    pub fn path(&self) -> &Path {
        &self.0
    }
}
impl Drop for Scratch {
    fn drop(&mut self) {
        if std::fs::remove_dir_all(&self.0).is_err() {
            let icacls = PathBuf::from(std::env::var("SystemRoot").unwrap()).join(r"System32\icacls.exe");
            let _ = Command::new(icacls).arg(&self.0).args(["/reset", "/T", "/C", "/Q"]).output();
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }
}
```

```rust
// desktop/tests/cli.rs
mod common;
use common::run;

#[test]
fn version_prints_one_line() {
    let o = run(&["--version"]);
    assert!(o.status.success());
    let line = String::from_utf8(o.stdout).unwrap();
    let re = regex::Regex::new(r"^mcp-monitor 1\.1\.0 \(payload [0-9a-f]{12}, (fixture|release)(, dev)?\)\r?\n$").unwrap();
    assert!(re.is_match(&line), "{line:?}");
}

#[test]
fn argument_errors_exit_2_in_korean() {
    for args in [&["install", "--bogus"][..], &["agent", "--server", "http://127.0.0.1:8700", "--dialog", "edge"][..], &["nope"][..]] {
        let o = run(args);
        assert_eq!(o.status.code(), Some(2), "{args:?}");
        assert!(o.stdout.is_empty());
        assert!(String::from_utf8(o.stderr).unwrap().starts_with("오류: "), "{args:?}");
    }
}

#[test]
fn verify_payload_extracts_and_checks_the_embedded_server() {
    let s = common::Scratch::new();
    let o = run(&["verify-payload", s.path().to_str().unwrap()]);
    assert_eq!(o.status.code(), Some(0), "{}", String::from_utf8_lossy(&o.stderr));
    assert!(String::from_utf8(o.stdout).unwrap().starts_with("payload OK: "));
    assert!(s.join("payload/bin/monitor/mcp-monitor-server.exe").is_file());
}
```

- [ ] **Step 2: 실패 확인** — Run: `cargo test --locked` → FAIL

- [ ] **Step 3: 구현** — 위 Interfaces대로.

- [ ] **Step 4: 통과 확인** — Rust 검사 3종 → 통과. 이 과제부터 테스트는 승격된 셸에서 실패합니다(의도, Global Constraints).

- [ ] **Step 5: Commit** — `git commit -m "feat(desktop): command line, elevation relaunch from parsed options only, System32-only DLL search, --version and verify-payload"`

---

### Task 5: 경로 검사와 ACL 규칙 이식(데이터 루트·상위 폴더·설치 폴더)

**Files:**
- Create: `desktop/src/install/mod.rs`, `desktop/src/install/paths.rs`, `desktop/src/install/acl.rs`, `desktop/src/install/testutil.rs`(`#[cfg(test)]`)

**Interfaces:**
- Produces(모두 `install.ps1`의 같은 이름 함수와 **같은 규칙**, 한국어 문구도 같은 뜻으로; 이름 대응은 부록 B):
  - `paths`:
    - `pub struct Env(HashMap<String, String>)`, `Env::from_process()`(키: `SystemRoot`, `SystemDrive`, `ProgramData`, `ProgramFiles`, `ProgramFiles(x86)`, `ProgramW6432`, `PUBLIC`, `USERPROFILE`, `LOCALAPPDATA`, `APPDATA`; 대소문자 무시로 읽음), `Env::get(&self, k) -> Option<String>`.
    - `pub trait Volumes { fn local_fixed_letters(&self) -> Vec<char>; }`, `pub struct SystemVolumes;`(A–Z 중 `GetDriveTypeW == DRIVE_FIXED`이고 `GetVolumeNameForVolumeMountPointW("X:\\")`가 성공하는 글자, 대문자 — subst·네트워크·이동식 드라이브는 빠짐).
    - `full_path(p: &str) -> Result<PathBuf, String>`(`GetFullPathNameW`, 길이가 3보다 길면 끝 `\` 제거) ↔ `Get-FullPath`; `is_inside(child, parent)`(대소문자 무시, `parent\` 접두어) ↔ `Test-Inside`; `path_link_problem(full)` ↔ `Get-PathLinkProblem`; `unsafe_root_reason(root: &str, env: &Env, vols: &dyn Volumes) -> Option<String>` ↔ `Get-UnsafeRootReason`(`\\`·`//` 시작, 드라이브 문자 경로 아님(상대 경로 포함), 로컬 고정 볼륨 아님("로컬 고정 디스크가 아닙니다"), 드라이브 루트, 경로 안의 정션·심볼릭 링크("정션 또는 심볼릭 링크"), 시스템 폴더 목록이거나 그 위, Windows 폴더 안).
    - `data_root_marker(root) -> bool` ↔ `Test-DataRootMarker`(`data\mcp-monitor-data-root.json` 또는 `data\install-state.json`).
  - `acl`:
    - 상수: `SYSTEM = "S-1-5-18"`, `ADMINISTRATORS = "S-1-5-32-544"`, `TRUSTED_INSTALLER = "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464"`, `AUTHENTICATED_USERS = "S-1-5-11"`, `EVERYONE = "S-1-1-0"`; 권한 비트 `DELETE 0x10000`, `WRITE_DAC 0x40000`, `WRITE_OWNER 0x80000`, `FILE_DELETE_CHILD 0x40`, `GENERIC_ALL 0x1000_0000`, `GENERIC_WRITE 0x4000_0000`, `FILE_WRITE_DATA 0x2`, `FILE_APPEND_DATA 0x4`, `READ_EXECUTE 0x0012_00A9`; `ANCESTOR_RIGHTS = DELETE|WRITE_DAC|WRITE_OWNER|FILE_DELETE_CHILD|GENERIC_ALL`, `OPEN_RIGHTS = ANCESTOR_RIGHTS|GENERIC_WRITE|FILE_WRITE_DATA|FILE_APPEND_DATA`; ACE 플래그 `INHERIT_ONLY_ACE 0x8`, `INHERITED_ACE 0x10`.
    - `#[derive(Clone, Debug, PartialEq)] pub struct Ace { pub sid: String, pub allow: bool, pub mask: u32, pub flags: u8 }`, `pub struct SecurityInfo { pub owner: String, pub protected: bool, pub aces: Vec<Ace> }`(상속 ACE 포함), `pub struct Item { pub path: PathBuf, pub is_dir: bool, pub reparse: bool }`.
    - `read_security(path) -> io::Result<SecurityInfo>`(`GetNamedSecurityInfoW(SE_FILE_OBJECT, OWNER|DACL)`; `ACCESS_ALLOWED_ACE_TYPE`·`ACCESS_DENIED_ACE_TYPE` 외의 형식은 안전 쪽으로 `allow: true, mask: GENERIC_ALL`), `sddl_of(path) -> io::Result<String>`(테스트·진단).
    - `untrusted_rule<'a>(aces: &'a [Ace], owners: &[String], rights: u32) -> Option<&'a Ace>` ↔ `Get-UntrustedRule`(허용 ACE만, `INHERIT_ONLY` 제외, `owners` + TrustedInstaller 제외, `S-1-3-*`·`S-1-15-*` 제외, `mask & rights != 0`).
    - `tree_items(root) -> io::Result<Vec<Item>>`(정션·링크 안으로 들어가지 않음) ↔ `Get-TreeItems`.
    - `data_root_problem(root, owners) -> Option<String>` = `data_root_problem_with(root, owners, &mut tree_items)` ↔ `Get-DataRootProblem`(없으면 None; 폴더 아님; 루트가 링크; 각 항목: 링크 / 소유자가 `owners` 밖("소유자") / `OPEN_RIGHTS`의 신뢰하지 않는 ACE("…지우거나 쓰거나 권한·소유자를 바꿀 수 있습니다… 지우고 설치가 새로 만들게 하세요…"); 목록과 읽기 사이 NotFound면 한 번 더, 그래도면 "확인하지 못했습니다"; 비어 있지 않은데 마커 없음 → "…비어 있지 않고 MCP Monitor 데이터 폴더도 아닙니다").
    - `data_root_readable(root) -> bool` ↔ `Test-DataRootReadable`.
    - `ancestor_problem(root, owners, folder_acl: &dyn Fn(&Path) -> io::Result<SecurityInfo>) -> Option<String>` ↔ `Get-AncestorProblem`(드라이브 루트부터 부모까지; 없는 폴더에서 멈춤; 소유자는 owners + TrustedInstaller; 드라이브 루트는 `ANCESTOR_RIGHTS & !DELETE`이고 문구에 "드라이브 루트", 나머지는 `ANCESTOR_RIGHTS`).
    - `RootSecurity::new(owner, sids)` = SDDL `O:<owner>D:P(A;OICI;FA;;;<sid>)…`(`ConvertStringSecurityDescriptorToSecurityDescriptorW`), `create_protected_dirs(path, &RootSecurity)`(없는 상위 폴더부터 `CreateDirectoryW(SECURITY_ATTRIBUTES)`; 이미 있으면 그대로) ↔ `New-ProtectedDirectory`, `set_root_acl(root, &RootSecurity)`(`SetNamedSecurityInfoW` `OWNER | DACL | PROTECTED_DACL`) ↔ `Set-RootAcl`, `reset_item_acl(item, owner)`(링크면 Err; 빈 DACL + `UNPROTECTED_DACL_SECURITY_INFORMATION` + 소유자) ↔ `Reset-ItemAcl`.
    - `acl_problems(root, owner, sids) -> Vec<String>` ↔ `Get-DataRootAclProblems`.
    - `initialize_data_root(root, owner, sids, owners, created_by) -> Result<(), String>` = `initialize_data_root_with(…, create: &dyn Fn(&Path, &RootSecurity) -> io::Result<()>)`(기본 `create_protected_dirs`) ↔ `Initialize-DataRoot`(순서 그대로: 문제 검사 → 상위 검사 → 없으면 만들고 읽어 확인("…다른 계정이 먼저 만들었습니다: …") → 상위 다시 → 문제 다시 → 루트 ACL → 문제 다시 → 아래 항목 초기화 → `logs`·`data`·`scripts` → 마커 `{"product":"mcp-monitor","created_by":…,"created_at":"<KST, 초 단위, +09:00>"}` → `acl_problems`가 비어 있지 않으면 "데이터 폴더 권한 확인 실패: …").
    - **신규** `install_tree_problem(dir, owners) -> Option<String>`: `dir`과 모든 하위 항목에서 링크 또는 `OPEN_RIGHTS`의 신뢰하지 않는 ACE가 있으면 "<항목>을(를) 관리자가 아닌 계정(<SID>)이 바꿀 수 있습니다. 서비스(SYSTEM)가 이 폴더의 프로그램을 실행하므로 설치할 수 없습니다"(Y15: Plan 5는 경고만 했음).
  - `testutil`(`#[cfg(test)]`): `Scratch`(Task 4 `tests/common`과 같은 규칙, 생성 전에 `assert_not_elevated()`, `Drop`에서 `icacls /reset` 후 삭제), `icacls(path, &[..])`, `grant(path, "<권한>")`(= `icacls path /grant *S-1-5-11:<권한>`), `junction(link, target)`(`cmd /d /c mklink /J`), `sddl(path)`, `me()`, `owners() = vec![SYSTEM, ADMINISTRATORS, me()]`, `walk_all(root) -> Vec<PathBuf>`(루트 포함).

- [ ] **Step 1: 실패하는 테스트 작성**

```rust
// desktop/src/install/acl.rs (tests)
#[cfg(test)]
mod tests {
    use super::*;
    use crate::install::paths::{Env, SystemVolumes, Volumes};
    use crate::install::testutil::*;
    use std::{fs, io, path::{Path, PathBuf}};

    fn ace(sid: &str, allow: bool, mask: u32, flags: u8) -> Ace {
        Ace { sid: sid.into(), allow, mask, flags }
    }

    #[test]
    fn untrusted_rule_ignores_deny_inherit_only_placeholders_and_app_containers() {
        let owners = vec![SYSTEM.to_string(), ADMINISTRATORS.to_string()];
        let aces = vec![
            ace(AUTHENTICATED_USERS, false, GENERIC_ALL, 0),
            ace(AUTHENTICATED_USERS, true, FILE_DELETE_CHILD, INHERIT_ONLY_ACE),
            ace("S-1-3-0", true, GENERIC_ALL, 0),
            ace("S-1-15-2-1", true, GENERIC_ALL, 0),
            ace(TRUSTED_INSTALLER, true, GENERIC_ALL, 0),
            ace(ADMINISTRATORS, true, GENERIC_ALL, 0),
            ace(AUTHENTICATED_USERS, true, READ_EXECUTE, 0),
        ];
        assert_eq!(untrusted_rule(&aces, &owners, OPEN_RIGHTS), None);
        let mut inherited = aces.clone();
        inherited.push(ace(AUTHENTICATED_USERS, true, GENERIC_ALL, INHERITED_ACE));
        assert_eq!(untrusted_rule(&inherited, &owners, OPEN_RIGHTS).map(|a| a.sid.as_str()), Some(AUTHENTICATED_USERS));
        let delete_only = vec![ace(AUTHENTICATED_USERS, true, DELETE, 0)];
        assert!(untrusted_rule(&delete_only, &owners, ANCESTOR_RIGHTS).is_some());
        assert!(untrusted_rule(&delete_only, &owners, ANCESTOR_RIGHTS & !DELETE).is_none());
    }

    #[test]
    fn data_root_problem_names_a_foreign_owner() {
        let s = Scratch::new();
        let root = s.path().join("r");
        fs::create_dir_all(root.join("data")).unwrap();
        fs::write(root.join("data/mcp-monitor-data-root.json"), "{}").unwrap();
        assert_eq!(data_root_problem(&root, &owners()), None);
        let p = data_root_problem(&root, &[SYSTEM.to_string(), ADMINISTRATORS.to_string()]).unwrap();
        assert!(p.contains(&me()) && p.contains("소유자"), "{p}");
        assert_eq!(data_root_problem(&s.path().join("missing"), &[]), None);
    }

    #[test]
    fn a_data_root_someone_else_filled_is_refused_and_an_empty_or_earlier_one_accepted() {
        let s = Scratch::new();
        let p = s.path();
        let foreign = p.join("foreign");
        fs::create_dir_all(foreign.join("scripts")).unwrap();
        fs::write(foreign.join("scripts/a.ps1"), "x").unwrap();
        let linked = p.join("linked");
        fs::create_dir_all(linked.join("data")).unwrap();
        fs::write(linked.join("data/install-state.json"), "{}").unwrap();
        junction(&linked.join("scripts"), &p.join("elsewhere"));
        let deep = p.join("deep");
        fs::create_dir_all(deep.join("data")).unwrap();
        fs::write(deep.join("data/mcp-monitor-data-root.json"), "{}").unwrap();
        fs::create_dir_all(deep.join("logs/x")).unwrap();
        junction(&deep.join("logs/x/y"), &p.join("elsewhere2"));
        let root_link = p.join("rootlink");
        junction(&root_link, &p.join("target"));
        let a_file = p.join("file");
        fs::write(&a_file, "x").unwrap();
        for (name, root) in [("not empty", &foreign), ("junction inside", &linked), ("deep junction", &deep),
                             ("root is a junction", &root_link), ("a file", &a_file)] {
            assert!(data_root_problem(root, &owners()).is_some(), "{name}");
        }
        let empty = p.join("empty");
        fs::create_dir(&empty).unwrap();
        let earlier = p.join("earlier");
        fs::create_dir_all(earlier.join("logs")).unwrap();
        fs::write(earlier.join("logs/2026-11-01.jsonl"), "{}\n").unwrap();
        fs::create_dir_all(earlier.join("data")).unwrap();
        fs::write(earlier.join("data/mcp-monitor-data-root.json"), "{}").unwrap();
        for root in [&empty, &earlier, &p.join("missing")] {
            assert_eq!(data_root_problem(root, &owners()), None, "{root:?}");
        }
    }

    #[test]
    fn initialize_data_root_rebuilds_the_acl_from_scratch() {
        let s = Scratch::new();
        let root = s.path().join("MCP Monitor");
        fs::create_dir_all(root.join("data")).unwrap();
        fs::write(root.join("data/install-state.json"), "{}").unwrap();
        let log = root.join("logs/2026-11-01.jsonl");
        fs::create_dir_all(log.parent().unwrap()).unwrap();
        fs::write(&log, "{}\n").unwrap();
        icacls(&root, &["/grant", &format!("*{EVERYONE}:(OI)(CI)RX")]);
        icacls(&log, &["/grant", &format!("*{EVERYONE}:R")]);
        assert!(sddl(&root).contains(";;;WD)") && sddl(&log).contains(";;;WD)"));
        let (me, sids) = (me(), owners());
        initialize_data_root(&root, &me, &sids, &sids, "install").unwrap();
        assert_eq!(acl_problems(&root, &me, &sids), Vec::<String>::new());
        icacls(&log, &["/grant", &format!("*{EVERYONE}:R")]);
        let problems = acl_problems(&root, &me, &sids).join("|");
        assert!(problems.contains(EVERYONE) && problems.contains("2026-11-01.jsonl"), "{problems}");
        icacls(&log, &["/remove", &format!("*{EVERYONE}")]);
        for item in walk_all(&root) {
            let d = sddl(&item);
            assert!(!d.contains("WD)") && d.starts_with(&format!("O:{me}")), "{item:?} {d}");
        }
        assert!(sddl(&root).contains("D:P"));
        for d in ["logs", "data", "scripts"] {
            assert!(root.join(d).is_dir(), "{d}");
        }
        let marker: serde_json::Value = serde_json::from_str(&fs::read_to_string(root.join("data/mcp-monitor-data-root.json")).unwrap()).unwrap();
        assert_eq!((marker["product"].as_str(), marker["created_by"].as_str()), (Some("mcp-monitor"), Some("install")));
    }

    #[test]
    fn initialize_data_root_creates_a_new_root_and_its_missing_parent() {
        let s = Scratch::new();
        let root = s.path().join("new").join("MCP Monitor");
        let (me, sids) = (me(), owners());
        initialize_data_root(&root, &me, &sids, &sids, "audit-policy").unwrap();
        assert!(acl_problems(&root, &me, &sids).is_empty());
        let mut names: Vec<String> = fs::read_dir(&root).unwrap().map(|e| e.unwrap().file_name().into_string().unwrap()).collect();
        names.sort();
        assert_eq!(names, ["data", "logs", "scripts"]);
        for folder in [s.path().join("new"), root.clone()] {
            let d = sddl(&folder);
            assert!(d.starts_with(&format!("O:{me}")) && d.contains("D:P") && !d.contains("WD)") && !d.contains("AU)"), "{folder:?} {d}");
        }
    }

    #[test]
    fn initialize_data_root_refuses_a_foreign_folder_and_changes_nothing() {
        let s = Scratch::new();
        let root = s.path().join("r");
        fs::create_dir_all(root.join("scripts")).unwrap();
        let before = sddl(&root);
        let sids = owners();
        let err = initialize_data_root(&root, &me(), &sids, &sids, "install").unwrap_err();
        assert!(err.contains("MCP Monitor"), "{err}");
        assert_eq!(sddl(&root), before);
        assert!(!root.join("data").exists());
    }

    #[test]
    fn initialize_data_root_refuses_a_root_made_just_before_it() {
        let s = Scratch::new();
        let root = s.path().join("MCP Monitor");
        let sids = owners();
        let attacker = |p: &Path, sd: &RootSecurity| -> io::Result<()> {
            fs::create_dir_all(p)?; // another account wins the race: the folder inherits its parent's ACL
            create_protected_dirs(p, sd)
        };
        let err = initialize_data_root_with(&root, &me(), &sids, &sids, "install", &attacker).unwrap_err();
        assert!(err.contains("먼저 만들었습니다"), "{err}");
        assert!(!sddl(&root).contains("D:P") && !root.join("data").exists());
    }

    #[test]
    fn a_data_root_below_a_folder_others_may_rename_is_refused() {
        let s = Scratch::new();
        let apps = s.path().join("apps");
        fs::create_dir(&apps).unwrap();
        let root = apps.join("MCP Monitor");
        grant(&apps, "(OI)(CI)M");
        let p = ancestor_problem(&root, &owners(), &read_security).unwrap();
        assert!(p.contains(&apps.display().to_string()) && p.contains(AUTHENTICATED_USERS), "{p}");
        icacls(&apps, &["/remove:g", &format!("*{AUTHENTICATED_USERS}")]);
        grant(&apps, "(OI)(CI)(IO)M");
        assert_eq!(ancestor_problem(&root, &owners(), &read_security), None);
    }

    #[test]
    fn ancestor_check_passes_the_default_and_drive_level_roots() {
        let e = Env::from_process();
        let o = vec![SYSTEM.to_string(), ADMINISTRATORS.to_string()];
        assert_eq!(ancestor_problem(&PathBuf::from(e.get("ProgramData").unwrap()).join("MCP Monitor"), &o, &read_security), None);
        for l in SystemVolumes.local_fixed_letters() {
            assert_eq!(ancestor_problem(Path::new(&format!("{l}:\\MCP Monitor")), &o, &read_security), None, "{l}");
        }
    }

    #[test]
    fn ancestor_check_includes_the_drive_root() {
        for (g, refused) in [("(DC)", true), ("(WDAC)", true), ("(WO)", true), ("F", true), ("M", false), ("(AD)", false), ("(OI)(CI)(IO)M", false)] {
            let s = Scratch::new();
            let fake = s.path().join("fake-drive-root");
            fs::create_dir(&fake).unwrap();
            grant(&fake, g);
            let drive = PathBuf::from(&s.path().display().to_string()[..3]);
            let acl = |p: &Path| if p == drive { read_security(&fake) } else { read_security(p) };
            let r = ancestor_problem(&s.path().join("MCP Monitor"), &owners(), &acl);
            if refused {
                let r = r.unwrap_or_else(|| panic!("{g} was accepted"));
                assert!(r.contains(&drive.display().to_string()) && r.contains(AUTHENTICATED_USERS) && r.contains("드라이브"), "{g}: {r}");
            } else {
                assert_eq!(r, None, "{g}");
            }
        }
    }

    #[test]
    fn an_existing_data_root_others_may_delete_or_rechmod_is_refused() {
        for case in ["inherited_modify", "write_dac", "write_owner", "delete_on_a_file", "write_on_a_script"] {
            let s = Scratch::new();
            let root = if case == "inherited_modify" {
                let vol = s.path().join("vol");
                fs::create_dir(&vol).unwrap();
                grant(&vol, "(OI)(CI)(IO)M");
                let r = vol.join("MCP Monitor");
                fs::create_dir(&r).unwrap();
                r
            } else {
                let r = s.path().join("MCP Monitor");
                fs::create_dir_all(r.join("data")).unwrap();
                fs::write(r.join("data/mcp-monitor-data-root.json"), "{}").unwrap();
                fs::write(r.join("data/config.db"), b"").unwrap();
                fs::create_dir(r.join("scripts")).unwrap();
                fs::write(r.join("scripts/a.ps1"), "x").unwrap();
                let (target, g) = match case {
                    "write_dac" => (r.clone(), "(WDAC)"),
                    "write_owner" => (r.clone(), "(WO)"),
                    "delete_on_a_file" => (r.join("data/config.db"), "(D)"),
                    _ => (r.join("scripts/a.ps1"), "(WD)"),
                };
                grant(&target, g);
                r
            };
            let before = sddl(&root);
            let p = data_root_problem(&root, &owners()).unwrap_or_else(|| panic!("{case} was accepted"));
            assert!(p.contains(AUTHENTICATED_USERS) && p.contains("지우고"), "{case}: {p}");
            let sids = owners();
            let err = initialize_data_root(&root, &me(), &sids, &sids, "install").unwrap_err();
            assert!(err.contains(AUTHENTICATED_USERS), "{case}: {err}");
            assert_eq!(sddl(&root), before, "{case}");
            assert!(!before.contains("D:P"));
        }
    }

    #[test]
    fn an_existing_data_root_with_harmless_extra_rights_is_accepted() {
        let s = Scratch::new();
        let root = s.path().join("MCP Monitor");
        fs::create_dir(&root).unwrap();
        grant(&root, "(OI)(CI)RX");
        icacls(&root, &["/grant", &format!("*{EVERYONE}:(OI)(CI)(IO)RX")]);
        assert_eq!(data_root_problem(&root, &owners()), None);
    }

    #[test]
    fn data_root_problem_looks_again_when_a_file_goes_away() {
        let s = Scratch::new();
        let root = s.path().join("r");
        fs::create_dir(&root).unwrap();
        let mut walks = 0;
        let mut first_fails = |_: &Path| -> io::Result<Vec<Item>> {
            walks += 1;
            if walks == 1 { Err(io::Error::from(io::ErrorKind::NotFound)) } else { Ok(vec![]) }
        };
        assert_eq!(data_root_problem_with(&root, &owners(), &mut first_fails), None);
        assert_eq!(walks, 2);
        let mut always = |_: &Path| -> io::Result<Vec<Item>> { Err(io::Error::from(io::ErrorKind::NotFound)) };
        assert!(data_root_problem_with(&root, &owners(), &mut always).unwrap().contains("확인하지 못했습니다"));
    }

    #[test]
    fn a_locked_data_root_is_unreadable_without_admin() {
        let s = Scratch::new();
        let root = s.path().join("MCP Monitor");
        fs::create_dir_all(root.join("data")).unwrap();
        assert!(data_root_readable(&root));
        icacls(&root, &["/inheritance:r", "/grant:r", "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F"]);
        assert!(!data_root_readable(&root));
        icacls(&root, &["/reset", "/T", "/C", "/Q"]);
    }

    #[test]
    fn an_install_tree_others_may_write_is_refused() {
        let s = Scratch::new();
        let i = s.path().join("i");
        fs::create_dir_all(i.join("bin/monitor")).unwrap();
        fs::write(i.join("bin/monitor/mcp-monitor-server.exe"), b"x").unwrap();
        assert_eq!(install_tree_problem(&i, &owners()), None);
        grant(&i.join("bin/monitor/mcp-monitor-server.exe"), "(W)");
        let p = install_tree_problem(&i, &owners()).unwrap();
        assert!(p.contains("mcp-monitor-server.exe") && p.contains(AUTHENTICATED_USERS), "{p}");
    }
}
```

```rust
// desktop/src/install/paths.rs (tests)
#[cfg(test)]
mod tests {
    use super::*;
    use crate::install::testutil::*;

    struct FakeVolumes(Vec<char>);
    impl Volumes for FakeVolumes {
        fn local_fixed_letters(&self) -> Vec<char> {
            self.0.clone()
        }
    }

    fn unc(p: &Path) -> String {
        let s = p.display().to_string();
        format!(r"\\localhost\{}$\{}", &s[..1], &s[3..])
    }

    #[test]
    fn unsafe_roots_are_refused() {
        let s = Scratch::new();
        let e = Env::from_process();
        let d = s.path().join("d");
        let cases = [
            format!("{}\\", e.get("SystemDrive").unwrap()), "Q:\\".to_string(), e.get("ProgramData").unwrap(),
            PathBuf::from(e.get("PUBLIC").unwrap()).parent().unwrap().display().to_string(),
            format!(r"{}\Temp\mcp", e.get("SystemRoot").unwrap()), format!(r"\\?\{}", d.display()),
            format!(r"\\.\{}", d.display()), unc(&d), e.get("LOCALAPPDATA").unwrap(),
        ];
        for c in &cases {
            assert!(unsafe_root_reason(c, &e, &SystemVolumes).is_some(), "{c}");
        }
        assert_eq!(unsafe_root_reason(&d.display().to_string(), &e, &SystemVolumes), None);
    }

    #[test]
    fn unsafe_root_reason_needs_a_local_fixed_volume() {
        let s = Scratch::new();
        let e = Env::from_process();
        let letters = SystemVolumes.local_fixed_letters();
        assert!(letters.contains(&e.get("SystemDrive").unwrap().chars().next().unwrap().to_ascii_uppercase()));
        let d = s.path().join("d").display().to_string();
        assert_eq!(unsafe_root_reason(&d, &e, &SystemVolumes), None);
        assert!(unsafe_root_reason(&d, &e, &FakeVolumes(vec!['Q'])).unwrap().contains("로컬 고정 디스크가 아닙니다"));
    }

    #[test]
    fn a_junction_in_the_path_is_refused() {
        let s = Scratch::new();
        junction(&s.path().join("link"), &s.path().join("real"));
        let r = unsafe_root_reason(&s.path().join("link").join("d").display().to_string(), &Env::from_process(), &SystemVolumes).unwrap();
        assert!(r.contains("정션 또는 심볼릭 링크"), "{r}");
    }

    #[test]
    fn inside_is_case_insensitive_and_needs_a_separator() {
        assert!(is_inside(Path::new(r"C:\Program Files\MCP Monitor\bin"), Path::new(r"c:\program files\mcp monitor")));
        assert!(!is_inside(Path::new(r"C:\Program Files\MCP Monitor2"), Path::new(r"C:\Program Files\MCP Monitor")));
        assert!(!is_inside(Path::new(r"C:\x"), Path::new(r"C:\x")));
    }

    #[test]
    fn only_a_marked_data_root_counts_as_ours() {
        let s = Scratch::new();
        let (bare, marked, legacy) = (s.path().join("bare"), s.path().join("marked"), s.path().join("legacy"));
        for r in [&bare, &marked, &legacy] {
            std::fs::create_dir_all(r.join("data")).unwrap();
        }
        std::fs::write(marked.join("data/mcp-monitor-data-root.json"), "{}").unwrap();
        std::fs::write(legacy.join("data/install-state.json"), "{}").unwrap();
        assert_eq!([data_root_marker(&bare), data_root_marker(&marked), data_root_marker(&legacy)], [false, true, true]);
    }
}
```

- [ ] **Step 2: 실패 확인** — Run: `cargo test --locked install::` → FAIL

- [ ] **Step 3: 구현** — 위 Interfaces대로. Win32 호출은 `acl.rs`·`paths.rs` 안의 작은 함수로 모으고 `unsafe` 블록마다 `// SAFETY:` 주석. SD·문자열은 `LocalFree`로 돌려줍니다. 이 PC의 실제 폴더 ACL은 읽기만 합니다(`ancestor_check_passes_the_default_and_drive_level_roots`).

- [ ] **Step 4: 통과 확인** — Rust 검사 3종 → 통과. 테스트 뒤 `%LOCALAPPDATA%\mcp-monitor-install-tests`가 비어 있음.

- [ ] **Step 5: Commit** — `git commit -m "feat(desktop): port the data root, ancestor and path guards to Rust with the same rules, plus an install tree check"`

---

### Task 6: 설치 계획(`install --dry-run`), 감사 정책(`audit-policy`), 계획 실행기

**Files:**
- Create: `desktop/src/install/plan.rs`, `desktop/src/install/install_plan.rs`, `desktop/src/install/audit.rs`, `desktop/src/install/host.rs`(`Host` 트레이트, `SystemHost`, `#[cfg(test)] FakeHost`), `desktop/src/install/exec.rs`(`RealExecutor`의 이 과제 부분), `desktop/tests/install_cli.rs`
- Modify: `desktop/src/install/mod.rs`, `desktop/src/lib.rs`(`Install`·`AuditPolicy` 연결)

**Interfaces:**
- Produces:
  - `plan`:
    ```rust
    #[derive(Serialize, Clone, Debug, PartialEq)]
    pub struct Step { pub id: String, pub cmd: String, pub args: Vec<String>, pub ok: Vec<i32>, pub when: Option<String> }
    #[derive(Serialize, Debug)]
    pub struct Plan { pub script: String, pub version: Option<String>, pub layout: Option<String>, pub install_dir: Option<String>,
                      pub data_root: Option<String>, pub service_mode: Option<String>, pub steps: Vec<Step>, pub notes: Vec<String> }
    pub enum StepError { NotAdmin, Failed(String) }
    pub trait Executor {
        fn condition(&mut self, when: &str) -> bool;
        fn internal(&mut self, step: &Step) -> Result<i32, StepError>;
        fn native(&mut self, cmd: &str, args: &[String]) -> Result<i32, StepError>;
        fn after(&mut self, id: &str) -> Result<(), StepError>;
    }
    pub const ADMIN_MESSAGE: &str = "관리자 권한으로 다시 실행하세요. (mcp-monitor.exe를 마우스 오른쪽 단추로 눌러 \"관리자 권한으로 실행\" 또는 관리자 PowerShell)";
    pub fn run_plan(plan: &Plan, ex: &mut dyn Executor, out: &mut dyn std::io::Write) -> i32;
    pub fn print_dry_run(plan: &Plan, out: &mut dyn std::io::Write, err: &mut dyn std::io::Write) -> i32;
    ```
    `cmd`가 `(`로 시작하면 `internal`, 아니면 `native`. `run_plan`: 단계마다 `[i/n] <id>`(건너뜀은 `[i/n] <id>: 건너뜀 (<when> 아님)`); `NotAdmin` → `ADMIN_MESSAGE` 한 줄 + 1(`[실패]` 없음); 종료 코드가 `ok`에 없거나 `Failed(m)` → `[실패] <id>: 종료 코드 <c>` 또는 `[실패] <id>: <m>` + 1; `after`(예: `stop_existing` 뒤 정지 대기) 실패도 같은 형식. `print_dry_run`: `serde_json::to_string(plan)` 한 줄 + `\n`을 `out`에, 각 note를 `참고: <note>`로 `err`에, 0.
  - `host`:
    ```rust
    pub struct Installed { pub version: String, pub install_location: PathBuf }
    pub struct PayloadInfo { pub version: String, pub layout: String, pub kind: String, pub size_kb: u32 }
    pub trait Host {
        fn is_admin(&self) -> bool;
        fn service_exists(&self) -> bool;                 // OpenSCManager(SC_MANAGER_CONNECT) + OpenService(SERVICE_QUERY_STATUS)
        fn installed(&self) -> Option<Installed>;          // HKLM\…\Uninstall\MCPMonitor: DisplayVersion, InstallLocation
        fn registry_dword(&self, value: &str) -> Option<u32>; // "<key>\<name>", read only
        fn env(&self) -> &Env;
        fn volumes(&self) -> &dyn Volumes;
        fn user_sid(&self) -> String;
        fn payload(&self) -> PayloadInfo;                  // embedded manifest: bundle.version, bundle.layout, KIND, total size / 1024 + exe size / 1024
    }
    ```
    `SystemHost`는 실제 값(읽기만). 테스트용 `#[cfg(test)] pub struct FakeHost { pub admin: bool, pub service: bool, pub installed: Option<Installed>, pub dwords: HashMap<String, u32>, pub env: Env, pub letters: Vec<char>, pub sid: String, pub payload: PayloadInfo }`(`registry_dword`는 `dwords`에서, `volumes()`는 `letters`를 돌려주는 작은 `Volumes`), `FakeHost::new()`는 관리자 아님·서비스 없음·설치 없음·레지스트리 빈 값·`Env::from_process()`·실제 볼륨·`me()`·payload `{1.1.0, pyinstaller, release, 60000}`.
  - `audit`: `AUDIT_VALUE = r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System\Audit\ProcessCreationIncludeCmdLine_Enabled"`, `PS_VALUE = r"HKLM\SOFTWARE\Policies\Microsoft\Windows\PowerShell\ScriptBlockLogging\EnableScriptBlockLogging"`, `SUCCESS_GUIDS`(Plan 5와 같은 5개, 같은 순서), `FAILURE_GUIDS`(2개), `AUDIT_STEPS = ["audit_backup", "audit_policy_success", "audit_policy_failure", "registry_cmdline", "registry_scriptblock", "security_log_size", "powershell_log_size"]`, `audit_steps(data_root: &str) -> Vec<Step>`(인자는 Plan 5와 같음), `build_audit_plan(a: &AuditArgs, h: &dyn Host) -> Result<Plan, ArgError>`(`--enable`: `require_admin`, `secure_data_root`, `record_registry`(`(write-json)`, `[<D>\data\audit-policy-state.json, {"registry_before":{…},"audit_backup":…,"recorded_at":null}]`, when `no_registry_record_yet`), 그리고 `AUDIT_STEPS`; `--restore <f>`: `require_admin`, `restore_audit_policy`(`auditpol /restore /file:<f>`), `restore_registry`(`(reg-restore)`, 상태 파일의 `registry_before`를 `"<값>=<DWORD|null>"`로)), `validate_registry_restore(entries: &[String]) -> Result<Vec<(String, String, Option<u32>)>, String>`(두 알려진 값과 `null`·`^\d{1,10}$`만, 아니면 `"알 수 없는 레지스트리 값 <entry>"`).
  - `install_plan::build_install_plan(a: &InstallArgs, h: &dyn Host) -> Result<Plan, ArgError>` — 값 정하기(Y15·Y16):
    - `I` = `--install-dir` → `h.installed().install_location` → `%ProgramFiles%\MCP Monitor`; `D` = `--data-root` → `<I>\install.json`의 `data_root` → `%ProgramData%\MCP Monitor`(모두 `full_path`).
    - 이전 상태: `<D>\data\install-state.json`(읽을 수 있을 때), `<I>\install.json`. `LP`/`EP` = 인자 → `install.json` → `install-state.json` → 8700/8701. 방화벽 = `--open-firewall` 또는 이전 상태의 `firewall == true`.
    - 설치된 버전 = `h.installed().version` → `<I>\bundle.json`의 `version`(1.0.0 PowerShell 설치에는 앱 및 기능 항목이 없음). `service_mode` = `h.service_exists()`면 `"update"`, 아니면 `"create"`.
  - 인자 오류(종료 2, 메시지는 문제의 옵션 이름으로 시작 — `--local-port`, `--install-dir`, `--data-root`): 포트가 같음; 다운그레이드(`설치된 버전 1.2.0이 이 실행 파일(1.1.0)보다 새롭습니다…`); `I`가 `unsafe_root_reason`; `I`가 파일; `I`가 비어 있지 않은데 `bundle.json` 없음; `I`의 상위 폴더 `ancestor_problem`(신규, Y15); `D`가 `I`·`<I>.staging`·`<I>.old`와 같거나 겹침; `D`의 `unsafe_root_reason`; `D`의 `data_root_problem`(관리자 아니고 읽을 수 없으면 대신 note "<D> 은(는) 관리자만 읽을 수 있어 안을 확인하지 못했습니다(소유자·내용 검사, 이전 install-state.json). 관리자 권한으로 다시 실행하면 확인합니다."); `D`의 `ancestor_problem`. owners = `[SYSTEM, ADMINISTRATORS, h.user_sid()]`.
  - 단계(이 순서; 방화벽 두 단계는 선택):
    | id | cmd | args | ok | when |
    |---|---|---|---|---|
    | `require_admin` | `(admin)` | | 0 | |
    | `check_os` | `(check-os)` | `[I]` | 0 | |
    | `stage_payload` | `(stage)` | `[I.staging, I]` | 0 | |
    | `stop_existing` | `sc.exe` | `stop mcp-monitor` | 0, 1062 | `service_exists` |
    | `stop_apps` | `(stop-apps)` | `[I]` | 0 | |
    | `swap_install_dir` | `(swap)` | `[I.staging, I, I.old]` | 0 | |
    | `secure_data_root` | `(secure-data-root)` | `[D]` | 0 | |
    | `audit_*`·`registry_*`·`*_log_size` | Plan 5와 같음(`--skip-audit-policy`면 없음) | | | `audit_backup`만 `no_backup_yet` |
    | `service_install` | `sc.exe` | `create|config mcp-monitor binPath= "<I>\bin\monitor\mcp-monitor-server.exe" service --root "<D>" --local-port LP --external-port EP start= delayed-auto DisplayName= MCP Monitor obj= LocalSystem` | 0 | |
    | `service_description` | `sc.exe` | `description mcp-monitor <service_description(LP, EP)>` | 0 | |
    | `service_failure` | `sc.exe` | `failure mcp-monitor reset= 86400 actions= restart/5000/restart/10000/restart/60000` | 0 | |
    | `service_failureflag` | `sc.exe` | `failureflag mcp-monitor 1` | 0 | |
    | `firewall_delete_old` | `netsh` | `advfirewall firewall delete rule name=MCP Monitor (<이전 EP>)` | 0, 1 | (이전 상태 `firewall`이고 이전 EP ≠ EP일 때만 있음) |
    | `firewall` | `netsh` | `advfirewall firewall add rule name=MCP Monitor (EP) dir=in action=allow protocol=TCP localport=EP profile=domain,private` | 0 | `firewall_rule_missing` |
    | `install_state` | `(write-state)` | `[<D>\data\install-state.json, <JSON>]` | 0 | |
    | `install_info` | `(write-json)` | `[<I>\install.json, {"version","local_port","external_port","data_root"}]` | 0 | |
    | `uninstall_entry` | `(registry-set)` | `[UNINSTALL_KEY, "DisplayName=REG_SZ:MCP Monitor", "DisplayVersion=REG_SZ:<ver>", "Publisher=REG_SZ:MCP Monitor", "InstallLocation=REG_SZ:<I>", "DisplayIcon=REG_SZ:\"<I>\mcp-monitor.exe\",0", "UninstallString=REG_SZ:\"<I>\mcp-monitor.exe\" uninstall --interactive", "QuietUninstallString=REG_SZ:\"<I>\mcp-monitor.exe\" uninstall", "NoModify=REG_DWORD:1", "NoRepair=REG_DWORD:1", "EstimatedSize=REG_DWORD:<size_kb>"]` | 0 | |
    | `start_menu_shortcut` | `(shortcut)` | `[<ProgramData>\Microsoft\Windows\Start Menu\Programs\MCP Monitor.lnk, <I>\mcp-monitor.exe, "", "MCP Monitor"]` | 0 | |
    | `service_start` | `sc.exe` | `start mcp-monitor` | 0, 1056 | |
    | `wait_ready` | `(wait)` | `[http://127.0.0.1:LP/api/channel, "30"]` | 0 | |
    | `cleanup_old` | `(remove-old)` | `[I.old]` | 0 | `old_exists` |
    `UNINSTALL_KEY = r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\MCPMonitor"`. `service_description(lp, ep)` = `"MCP 상태 감시와 RDP 접속·행동 감사 (127.0.0.1:{lp} / 0.0.0.0:{ep})"`(`server/app/winsvc/__init__.py`의 `DESCRIPTION`과 같은 문장).
  - `install-state.json`(`install_state`의 JSON; Plan 5 키 + 신규 두 키): `{installed_at: null(실행 때 채움), version, layout, install_dir, data_root, local_port, external_port, firewall, skip_audit_policy, registry_before, audit_backup, installer: "desktop"}`. `registry_before`: 이전 `install-state.json` → `audit-policy-state.json` → (감사 정책을 켤 때만) 지금 레지스트리 값(`h.registry_dword`, 없으면 null). `audit_backup`: 감사 정책을 켜거나 백업 파일이 있으면 `<D>\data\auditpol-backup.csv`, 아니면 이전 값(없으면 null).
  - `exec::RealExecutor`(이 과제 부분): `(admin)`(관리자 아니면 `NotAdmin`), `(secure-data-root)`(`initialize_data_root(D, ADMINISTRATORS, [SYSTEM, ADMINISTRATORS], owners, "install"|"audit-policy")`), `(write-state)`(`installed_at` = 지금 KST 초 `+09:00`, UTF-8 BOM 없음, 들여쓰기 2), `(write-json)`(그대로 씀), `(reg-restore)`(`validate_registry_restore` 뒤 `reg add|delete`), `(wait)`(ureq, 프록시 없음, 2초 시간 제한, 1초 간격, 200이면 성공), 그 밖의 internal은 Task 7·8이 채움(`Failed("아직 구현되지 않았습니다")`). native는 `system_tool(cmd)`를 `std::process::Command`로 실행(인용은 Rust 표준 MSVCRT 규칙 = `quote_arg`와 같음, Task 4 테스트), 콘솔 창 없음(`CREATE_NO_WINDOW`). 조건: `service_exists`, `no_backup_yet`(`<D>\data\auditpol-backup.csv` 없음), `firewall_rule_missing`(`netsh advfirewall firewall show rule name=…`의 종료 코드 ≠ 0), `no_registry_record_yet`. `after("stop_existing")` = 60초 동안 서비스 `STOPPED` 대기.
  - `lib::run`: `Install`/`AuditPolicy` → `build_*_plan(&args, &SystemHost)`(ArgError → `오류: …` + 2) → `dry_run`이면 `print_dry_run`, 아니면 `run_plan(RealExecutor)`; 성공 끝 줄 `설치 완료: http://127.0.0.1:<LP>/admin/setup 에서 첫 Admin 계정을 만드세요.` / `감사 정책을 켰습니다.` / `감사 정책을 되돌렸습니다.`; `--interactive`면 같은 문장을 메시지 상자로도(실패면 오류 상자에 마지막 `[실패]` 줄).

- [ ] **Step 1: 실패하는 테스트 작성**

```rust
// desktop/src/install/install_plan.rs (tests)
#[cfg(test)]
mod tests {
    use super::*;
    use crate::install::audit::{AUDIT_VALUE, PS_VALUE};
    use crate::install::host::{FakeHost, Installed};
    use crate::install::plan::{Plan, Step};
    use crate::install::testutil::*;
    use regex::Regex;
    use serde_json::{json, Value};
    use std::{fs, path::PathBuf};

    const DEFAULT_IDS: [&str; 25] = [
        "require_admin", "check_os", "stage_payload", "stop_existing", "stop_apps", "swap_install_dir", "secure_data_root",
        "audit_backup", "audit_policy_success", "audit_policy_failure", "registry_cmdline", "registry_scriptblock",
        "security_log_size", "powershell_log_size", "service_install", "service_description", "service_failure",
        "service_failureflag", "install_state", "install_info", "uninstall_entry", "start_menu_shortcut", "service_start",
        "wait_ready", "cleanup_old",
    ];

    fn args(s: &Scratch) -> InstallArgs {
        InstallArgs { install_dir: Some(s.path().join("inst")), data_root: Some(s.path().join("data")), ..Default::default() }
    }
    fn dirs(s: &Scratch) -> (String, String) {
        (s.path().join("inst").display().to_string(), s.path().join("data").display().to_string())
    }
    fn ids(p: &Plan) -> Vec<&str> {
        p.steps.iter().map(|x| x.id.as_str()).collect()
    }
    fn step<'a>(p: &'a Plan, id: &str) -> &'a Step {
        p.steps.iter().find(|x| x.id == id).unwrap_or_else(|| panic!("no step {id}"))
    }
    fn after<'a>(s: &'a Step, key: &str) -> &'a str {
        &s.args[s.args.iter().position(|a| a == key).unwrap() + 1]
    }
    fn state(p: &Plan) -> Value {
        serde_json::from_str(&step(p, "install_state").args[1]).unwrap()
    }

    #[test]
    fn install_plan_default() {
        let s = Scratch::new();
        let p = build_install_plan(&args(&s), &FakeHost::new()).unwrap();
        let (inst, data) = dirs(&s);
        assert_eq!(ids(&p), DEFAULT_IDS);
        assert_eq!((p.script.as_str(), p.version.as_deref(), p.layout.as_deref(), p.service_mode.as_deref()),
                   ("install", Some("1.1.0"), Some("pyinstaller"), Some("create")));
        assert_eq!((p.install_dir.as_deref(), p.data_root.as_deref()), (Some(inst.as_str()), Some(data.as_str())));
        let svc = step(&p, "service_install");
        assert_eq!(svc.args[..2], ["create", "mcp-monitor"]);
        assert_eq!((after(svc, "start="), after(svc, "obj="), after(svc, "DisplayName=")), ("delayed-auto", "LocalSystem", "MCP Monitor"));
        assert_eq!(after(svc, "binPath="), format!(r#""{inst}\bin\monitor\mcp-monitor-server.exe" service --root "{data}" --local-port 8700 --external-port 8701"#));
        assert_eq!(step(&p, "service_failure").args, ["failure", "mcp-monitor", "reset=", "86400", "actions=", "restart/5000/restart/10000/restart/60000"]);
        assert_eq!(step(&p, "service_failureflag").args, ["failureflag", "mcp-monitor", "1"]);
        let guid = Regex::new(r"\{0CCE92[0-9A-F]{2}-69AE-11D9-BED3-505054503030\}").unwrap();
        let subs = step(&p, "audit_policy_success").args.iter().find(|a| a.starts_with("/subcategory:")).unwrap();
        assert_eq!(guid.find_iter(subs).count(), 5);
        assert!(p.steps.iter().all(|x| x.cmd != "robocopy" && x.cmd != "icacls"));
        assert!(p.notes.is_empty());
    }

    #[test]
    fn install_plan_details() {
        let s = Scratch::new();
        let p = build_install_plan(&args(&s), &FakeHost::new()).unwrap();
        let (inst, data) = dirs(&s);
        let stop = step(&p, "stop_existing");
        assert_eq!((stop.cmd.as_str(), stop.args.clone(), stop.ok.clone(), stop.when.as_deref()),
                   ("sc.exe", vec!["stop".to_string(), "mcp-monitor".into()], vec![0, 1062], Some("service_exists")));
        assert_eq!((step(&p, "stage_payload").cmd.as_str(), step(&p, "stage_payload").args.clone()), ("(stage)", vec![format!("{inst}.staging"), inst.clone()]));
        assert_eq!(step(&p, "stop_apps").args, [inst.clone()]);
        assert_eq!(step(&p, "swap_install_dir").args, [format!("{inst}.staging"), inst.clone(), format!("{inst}.old")]);
        assert_eq!((step(&p, "secure_data_root").cmd.as_str(), step(&p, "secure_data_root").args.clone()), ("(secure-data-root)", vec![data.clone()]));
        let backup = step(&p, "audit_backup");
        assert_eq!(backup.args, ["/backup".to_string(), format!(r"/file:{data}\data\auditpol-backup.csv")]);
        assert_eq!(backup.when.as_deref(), Some("no_backup_yet"));
        assert_eq!(step(&p, "audit_policy_failure").args, ["/set", "/subcategory:{0CCE9215-69AE-11D9-BED3-505054503030},{0CCE921C-69AE-11D9-BED3-505054503030}", "/failure:enable"]);
        assert_eq!(step(&p, "registry_cmdline").args, ["add", r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System\Audit", "/v", "ProcessCreationIncludeCmdLine_Enabled", "/t", "REG_DWORD", "/d", "1", "/f"]);
        assert_eq!(step(&p, "registry_scriptblock").args, ["add", r"HKLM\SOFTWARE\Policies\Microsoft\Windows\PowerShell\ScriptBlockLogging", "/v", "EnableScriptBlockLogging", "/t", "REG_DWORD", "/d", "1", "/f"]);
        assert_eq!(step(&p, "security_log_size").args, ["sl", "Security", "/ms:268435456"]);
        assert_eq!(step(&p, "powershell_log_size").args, ["sl", "Microsoft-Windows-PowerShell/Operational", "/ms:67108864"]);
        assert!(!ids(&p).contains(&"firewall") && !ids(&p).contains(&"firewall_delete_old"));
        assert_eq!(step(&p, "service_start").ok, [0, 1056]);
        assert_eq!(step(&p, "wait_ready").args, ["http://127.0.0.1:8700/api/channel", "30"]);
        let st = step(&p, "install_state");
        assert_eq!((st.cmd.as_str(), st.args[0].clone()), ("(write-state)", format!(r"{data}\data\install-state.json")));
        let mut v = state(&p);
        assert!(v["installed_at"].is_null());
        let keys: Vec<String> = v["registry_before"].as_object().unwrap().keys().cloned().collect();
        assert_eq!(keys, [AUDIT_VALUE, PS_VALUE]);
        let o = v.as_object_mut().unwrap();
        o.remove("registry_before");
        o.remove("installed_at");
        assert_eq!(v, json!({"version": "1.1.0", "layout": "pyinstaller", "install_dir": &inst, "data_root": &data,
                              "local_port": 8700, "external_port": 8701, "firewall": false, "skip_audit_policy": false,
                              "audit_backup": format!(r"{data}\data\auditpol-backup.csv"), "installer": "desktop"}));
        let info = step(&p, "install_info");
        assert_eq!((info.cmd.as_str(), info.args[0].clone()), ("(write-json)", format!(r"{inst}\install.json")));
        assert_eq!(serde_json::from_str::<Value>(&info.args[1]).unwrap(), json!({"version": "1.1.0", "local_port": 8700, "external_port": 8701, "data_root": &data}));
        let un = step(&p, "uninstall_entry");
        assert_eq!((un.cmd.as_str(), un.args[0].as_str()), ("(registry-set)", UNINSTALL_KEY));
        for want in ["DisplayName=REG_SZ:MCP Monitor".to_string(), "DisplayVersion=REG_SZ:1.1.0".into(), "Publisher=REG_SZ:MCP Monitor".into(),
                     format!("InstallLocation=REG_SZ:{inst}"), format!(r#"DisplayIcon=REG_SZ:"{inst}\mcp-monitor.exe",0"#),
                     format!(r#"UninstallString=REG_SZ:"{inst}\mcp-monitor.exe" uninstall --interactive"#),
                     format!(r#"QuietUninstallString=REG_SZ:"{inst}\mcp-monitor.exe" uninstall"#), "NoModify=REG_DWORD:1".into(),
                     "NoRepair=REG_DWORD:1".into(), "EstimatedSize=REG_DWORD:60000".into()] {
            assert!(un.args.contains(&want), "{want}");
        }
        let programs = format!(r"{}\Microsoft\Windows\Start Menu\Programs", std::env::var("ProgramData").unwrap());
        assert_eq!(step(&p, "start_menu_shortcut").args, [format!(r"{programs}\MCP Monitor.lnk"), format!(r"{inst}\mcp-monitor.exe"), String::new(), "MCP Monitor".into()]);
        let old = step(&p, "cleanup_old");
        assert_eq!((old.cmd.as_str(), old.args.clone(), old.when.as_deref()), ("(remove-old)", vec![format!("{inst}.old")], Some("old_exists")));
    }

    #[test]
    fn description_matches_the_service_host() {
        let src = fs::read_to_string(concat!(env!("CARGO_MANIFEST_DIR"), "/../server/app/winsvc/__init__.py")).unwrap();
        let line = src.lines().find(|l| l.starts_with("DESCRIPTION = ")).unwrap();
        let text = line.trim_start_matches("DESCRIPTION = ").trim_matches('"');
        assert_eq!(service_description(8700, 8701), text);
        assert_eq!(service_description(9700, 9701), text.replace("8700", "9700").replace("8701", "9701"));
    }

    #[test]
    fn install_plan_open_firewall_and_skip_audit() {
        let s = Scratch::new();
        let mut a = args(&s);
        a.open_firewall = true;
        a.skip_audit_policy = true;
        a.external_port = Some(9701);
        let p = build_install_plan(&a, &FakeHost::new()).unwrap();
        let ids = ids(&p);
        for gone in crate::install::audit::AUDIT_STEPS {
            assert!(!ids.contains(&gone), "{gone}");
        }
        let fw = step(&p, "firewall");
        assert_eq!(fw.args, ["advfirewall", "firewall", "add", "rule", "name=MCP Monitor (9701)", "dir=in", "action=allow", "protocol=TCP", "localport=9701", "profile=domain,private"]);
        assert_eq!(fw.when.as_deref(), Some("firewall_rule_missing"));
        assert_eq!(ids.iter().position(|i| *i == "firewall"), ids.iter().position(|i| *i == "service_failureflag").map(|i| i + 1));
        let v = state(&p);
        assert_eq!((v["firewall"].as_bool(), v["external_port"].as_u64(), v["skip_audit_policy"].as_bool()), (Some(true), Some(9701), Some(true)));
        assert_eq!(v["registry_before"], json!({}));
        assert!(v["audit_backup"].is_null());
    }

    #[test]
    fn install_plan_ports_and_korean_paths() {
        let s = Scratch::new();
        let a = InstallArgs { install_dir: Some(s.path().join("설치 폴더")), data_root: Some(s.path().join("데이터")),
                              local_port: Some(9700), external_port: Some(9701), ..Default::default() };
        let p = build_install_plan(&a, &FakeHost::new()).unwrap();
        let (inst, data) = (s.path().join("설치 폴더").display().to_string(), s.path().join("데이터").display().to_string());
        assert_eq!(after(step(&p, "service_install"), "binPath="), format!(r#""{inst}\bin\monitor\mcp-monitor-server.exe" service --root "{data}" --local-port 9700 --external-port 9701"#));
        assert_eq!(step(&p, "service_description").args[2], service_description(9700, 9701));
        assert_eq!(step(&p, "wait_ready").args[0], "http://127.0.0.1:9700/api/channel");
    }

    #[test]
    fn upgrade_plan_stages_before_stopping_and_cleans_up_after_ready() {
        let s = Scratch::new();
        fs::create_dir_all(s.path().join("inst")).unwrap();
        fs::write(s.path().join("inst/bundle.json"), r#"{"layout":"pyinstaller","version":"1.0.9","agent":"desktop"}"#).unwrap();
        let mut h = FakeHost::new();
        h.service = true;
        h.installed = Some(Installed { version: "1.0.9".into(), install_location: s.path().join("inst") });
        let p = build_install_plan(&args(&s), &h).unwrap();
        assert_eq!(p.service_mode.as_deref(), Some("update"));
        assert_eq!(step(&p, "service_install").args[0], "config");
        let all = ids(&p);
        let at = |id: &str| all.iter().position(|x| *x == id).unwrap();
        assert!(at("stage_payload") < at("stop_existing") && at("stop_existing") < at("stop_apps") && at("stop_apps") < at("swap_install_dir"));
        assert!(at("swap_install_dir") < at("service_install") && at("service_start") < at("wait_ready") && at("wait_ready") < at("cleanup_old"));
    }

    #[test]
    fn downgrade_is_refused() {
        let s = Scratch::new();
        let mut h = FakeHost::new();
        h.service = true;
        h.installed = Some(Installed { version: "1.2.0".into(), install_location: s.path().join("inst") });
        let e = build_install_plan(&args(&s), &h).unwrap_err();
        assert!(e.0.contains("1.2.0") && e.0.contains("1.1.0"), "{}", e.0);
        h.installed = Some(Installed { version: "1.1.0".into(), install_location: s.path().join("inst") });
        assert!(build_install_plan(&args(&s), &h).is_ok()); // the same version: a repair
    }

    fn earlier_install(s: &Scratch, state: Value) {
        let (_, data) = dirs(s);
        fs::create_dir_all(s.path().join("inst")).unwrap();
        fs::write(s.path().join("inst/bundle.json"), "{}").unwrap();
        fs::write(s.path().join("inst/install.json"), json!({"version": "1.1.0", "local_port": 9700, "external_port": 9701, "data_root": data}).to_string()).unwrap();
        fs::create_dir_all(s.path().join("data/data")).unwrap();
        fs::write(s.path().join("data/data/mcp-monitor-data-root.json"), "{}").unwrap();
        fs::write(s.path().join("data/data/install-state.json"), state.to_string()).unwrap();
    }

    #[test]
    fn reinstall_reuses_previous_ports_and_firewall() {
        let s = Scratch::new();
        earlier_install(&s, json!({"version": "1.1.0", "local_port": 9700, "external_port": 9701, "firewall": true, "registry_before": {}, "audit_backup": null}));
        let a = InstallArgs { install_dir: Some(s.path().join("inst")), ..Default::default() };
        let p = build_install_plan(&a, &FakeHost::new()).unwrap();
        assert_eq!(p.data_root.as_deref(), Some(dirs(&s).1.as_str()));
        assert!(after(step(&p, "service_install"), "binPath=").ends_with("--local-port 9700 --external-port 9701"));
        assert_eq!(step(&p, "firewall").args[4], "name=MCP Monitor (9701)");
        assert!(!ids(&p).contains(&"firewall_delete_old"));
        let b = InstallArgs { local_port: Some(9800), ..a };
        assert!(after(step(&build_install_plan(&b, &FakeHost::new()).unwrap(), "service_install"), "binPath=").ends_with("--local-port 9800 --external-port 9701"));
    }

    #[test]
    fn reinstall_with_another_external_port_removes_the_old_rule() {
        let s = Scratch::new();
        earlier_install(&s, json!({"version": "1.1.0", "local_port": 9700, "external_port": 9701, "firewall": true, "registry_before": {}, "audit_backup": null}));
        let a = InstallArgs { install_dir: Some(s.path().join("inst")), external_port: Some(9801), ..Default::default() };
        let p = build_install_plan(&a, &FakeHost::new()).unwrap();
        let del = step(&p, "firewall_delete_old");
        assert_eq!((del.cmd.as_str(), del.args.clone(), del.ok.clone()),
                   ("netsh", ["advfirewall", "firewall", "delete", "rule", "name=MCP Monitor (9701)"].map(String::from).to_vec(), vec![0, 1]));
        let all = ids(&p);
        assert_eq!(all.iter().position(|x| *x == "firewall_delete_old").unwrap() + 1, all.iter().position(|x| *x == "firewall").unwrap());
        assert_eq!(step(&p, "firewall").args[4], "name=MCP Monitor (9801)");
    }

    #[test]
    fn reinstall_keeps_the_first_registry_values_and_backup() {
        let s = Scratch::new();
        let data = s.path().join("data");
        fs::create_dir_all(data.join("data")).unwrap();
        fs::write(data.join("data/auditpol-backup.csv"), "x").unwrap();
        fs::write(data.join("data/mcp-monitor-data-root.json"), "{}").unwrap();
        fs::write(data.join("data/install-state.json"), json!({"registry_before": {AUDIT_VALUE: null, PS_VALUE: 0},
            "audit_backup": data.join("data/auditpol-backup.csv"), "version": "1.0.0", "external_port": 8701}).to_string()).unwrap();
        let mut h = FakeHost::new();
        h.dwords.insert(AUDIT_VALUE.into(), 1); // our own values by now
        h.dwords.insert(PS_VALUE.into(), 1);
        let p = build_install_plan(&args(&s), &h).unwrap();
        assert_eq!(state(&p)["registry_before"], json!({AUDIT_VALUE: null, PS_VALUE: 0}));
        assert_eq!(step(&p, "audit_backup").when.as_deref(), Some("no_backup_yet"));
    }

    #[test]
    fn upgrade_from_a_powershell_install_keeps_its_state() {
        let s = Scratch::new();
        let (inst, data) = dirs(&s);
        fs::create_dir_all(s.path().join("inst/bin/agent")).unwrap();
        fs::write(s.path().join("inst/bundle.json"), r#"{"layout":"pyinstaller","version":"1.0.0","python":"3.15.2","built_at":"x","commit":"y"}"#).unwrap();
        fs::create_dir_all(s.path().join("data/data")).unwrap();
        fs::write(s.path().join("data/data/mcp-monitor-data-root.json"), r#"{"product":"mcp-monitor","created_by":"install"}"#).unwrap();
        fs::write(s.path().join("data/data/install-state.json"), json!({"installed_at": "2026-11-07T10:00:00+09:00", "version": "1.0.0",
            "layout": "pyinstaller", "install_dir": &inst, "data_root": &data, "local_port": 8800, "external_port": 8801, "firewall": false,
            "registry_before": {AUDIT_VALUE: null, PS_VALUE: null}, "audit_backup": format!(r"{data}\data\auditpol-backup.csv")}).to_string()).unwrap();
        let mut h = FakeHost::new();
        h.service = true; // 1.0.0 had no Apps & features entry
        let p = build_install_plan(&args(&s), &h).unwrap();
        assert_eq!(p.service_mode.as_deref(), Some("update"));
        assert!(after(step(&p, "service_install"), "binPath=").ends_with("--local-port 8800 --external-port 8801"));
        let v = state(&p);
        assert_eq!(v["registry_before"], json!({AUDIT_VALUE: null, PS_VALUE: null}));
        assert_eq!(v["installer"], "desktop");
    }

    #[test]
    fn install_argument_errors() {
        let cases = ["same_ports", "foreign_install_dir", "install_dir_is_a_file", "data_root_inside_install", "data_root_contains_install",
                     "data_root_is_the_staging_dir", "drive_root_install_dir", "install_dir_below_a_writable_folder", "foreign_data_root"];
        for case in cases {
            let s = Scratch::new();
            let mut a = args(&s);
            let inst = s.path().join("inst");
            match case {
                "same_ports" => { a.local_port = Some(8800); a.external_port = Some(8800); }
                "foreign_install_dir" => { fs::create_dir(&inst).unwrap(); fs::write(inst.join("keep.txt"), "x").unwrap(); }
                "install_dir_is_a_file" => fs::write(&inst, "x").unwrap(),
                "data_root_inside_install" => a.data_root = Some(inst.join("var")),
                "data_root_contains_install" => a.data_root = Some(s.path().to_path_buf()),
                "data_root_is_the_staging_dir" => a.data_root = Some(s.path().join("inst.staging")),
                "drive_root_install_dir" => a.install_dir = Some(PathBuf::from(format!("{}\\", std::env::var("SystemDrive").unwrap()))),
                "install_dir_below_a_writable_folder" => {
                    let w = s.path().join("w");
                    fs::create_dir(&w).unwrap();
                    grant(&w, "(OI)(CI)M");
                    a.install_dir = Some(w.join("MCP Monitor"));
                }
                _ => {
                    let d = s.path().join("data");
                    fs::create_dir_all(d.join("scripts")).unwrap();
                    fs::write(d.join("scripts/a.ps1"), "x").unwrap();
                }
            }
            let e = build_install_plan(&a, &FakeHost::new()).unwrap_err();
            let want = if case.contains("data_root") { "--data-root" } else if case == "same_ports" { "--local-port" } else { "--install-dir" };
            assert!(e.0.starts_with(want), "{case}: {}", e.0);
        }
    }

    #[test]
    fn install_accepts_an_earlier_install_dir() {
        let s = Scratch::new();
        let inst = s.path().join("inst");
        fs::create_dir(&inst).unwrap();
        fs::write(inst.join("bundle.json"), "{}").unwrap();
        fs::write(inst.join("old.txt"), "x").unwrap();
        assert!(!build_install_plan(&args(&s), &FakeHost::new()).unwrap().steps.is_empty());
    }

    #[test]
    fn dry_run_without_admin_plans_over_an_installed_data_root() {
        let s = Scratch::new();
        let root = s.path().join("data");
        fs::create_dir_all(root.join("data")).unwrap();
        fs::write(root.join("data/mcp-monitor-data-root.json"), "{}").unwrap();
        icacls(&root, &["/inheritance:r", "/grant:r", "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F"]);
        let mut a = args(&s);
        a.dry_run = true;
        let p = build_install_plan(&a, &FakeHost::new());
        icacls(&root, &["/reset", "/T", "/C", "/Q"]);
        let p = p.unwrap();
        assert_eq!(p.notes.len(), 1);
        assert!(p.notes[0].contains("관리자 권한으로 다시 실행하면 확인합니다"), "{}", p.notes[0]);
        assert_eq!(step(&p, "secure_data_root").args, [root.display().to_string()]);
    }
}
```

```rust
// desktop/src/install/plan.rs (tests)
#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    fn st(id: &str, cmd: &str, ok: &[i32], when: Option<&str>) -> Step {
        Step { id: id.into(), cmd: cmd.into(), args: vec![], ok: ok.to_vec(), when: when.map(String::from) }
    }
    fn plan(steps: Vec<Step>) -> Plan {
        Plan { script: "install".into(), version: Some("1.1.0".into()), layout: Some("pyinstaller".into()), install_dir: None,
               data_root: None, service_mode: Some("create".into()), steps, notes: vec!["n1".into()] }
    }

    #[derive(Default)]
    struct FakeExec { admin: bool, log: Vec<String>, codes: HashMap<String, i32>, conds: HashMap<String, bool> }
    impl Executor for FakeExec {
        fn condition(&mut self, when: &str) -> bool {
            *self.conds.get(when).unwrap_or(&true)
        }
        fn internal(&mut self, s: &Step) -> Result<i32, StepError> {
            self.log.push(s.id.clone());
            if s.cmd == "(admin)" && !self.admin {
                return Err(StepError::NotAdmin);
            }
            Ok(*self.codes.get(&s.id).unwrap_or(&0))
        }
        fn native(&mut self, cmd: &str, _args: &[String]) -> Result<i32, StepError> {
            self.log.push(cmd.into());
            Ok(*self.codes.get(cmd).unwrap_or(&0))
        }
        fn after(&mut self, id: &str) -> Result<(), StepError> {
            self.log.push(format!("after {id}"));
            Ok(())
        }
    }

    #[test]
    fn require_admin_comes_first_and_stops_without_admin() {
        let p = plan(vec![st("require_admin", "(admin)", &[0], None), st("x", "sc.exe", &[0], None)]);
        let mut ex = FakeExec::default();
        let mut out = Vec::new();
        assert_eq!(run_plan(&p, &mut ex, &mut out), 1);
        assert_eq!(ex.log, ["require_admin"]);
        let text = String::from_utf8(out).unwrap();
        assert!(text.contains(ADMIN_MESSAGE) && !text.contains("[실패]"), "{text}");
    }

    #[test]
    fn run_plan_skips_false_conditions_and_stops_at_the_first_failure() {
        let p = plan(vec![st("a", "(write-json)", &[0], None), st("b", "netsh", &[0], Some("x")), st("c", "sc.exe", &[0, 1062], None),
                          st("d", "auditpol", &[0], None), st("e", "(wait)", &[0], None)]);
        let mut ex = FakeExec { admin: true, ..Default::default() };
        ex.conds.insert("x".into(), false);
        ex.codes.insert("sc.exe".into(), 1062);
        ex.codes.insert("auditpol".into(), 5);
        let mut out = Vec::new();
        assert_eq!(run_plan(&p, &mut ex, &mut out), 1);
        assert_eq!(ex.log, ["a", "sc.exe", "auditpol"]);
        let text = String::from_utf8(out).unwrap();
        let lines: Vec<&str> = text.lines().collect();
        assert_eq!(lines, ["[1/5] a", "[2/5] b: 건너뜀 (x 아님)", "[3/5] c", "[4/5] d", "[실패] d: 종료 코드 5"]);
    }

    #[test]
    fn dry_run_prints_one_compact_json_line_and_notes_on_stderr() {
        let p = plan(vec![st("require_admin", "(admin)", &[0], None)]);
        let (mut out, mut err) = (Vec::new(), Vec::new());
        assert_eq!(print_dry_run(&p, &mut out, &mut err), 0);
        let text = String::from_utf8(out).unwrap();
        assert_eq!(text.matches('\n').count(), 1);
        assert!(text.starts_with(r#"{"script":"install","version":"1.1.0","layout":"pyinstaller","install_dir":null,"data_root":null,"service_mode":"create","steps":[{"id":"require_admin","cmd":"(admin)","args":[],"ok":[0],"when":null}],"notes":["n1"]}"#), "{text}");
        assert_eq!(String::from_utf8(err).unwrap(), "참고: n1\n");
    }
}
```

```rust
// desktop/src/install/audit.rs (tests)
#[cfg(test)]
mod tests {
    use super::*;
    use crate::cli::{AuditArgs, InstallArgs};
    use crate::install::host::FakeHost;
    use crate::install::install_plan::build_install_plan;
    use crate::install::testutil::*;
    use serde_json::{json, Value};
    use std::fs;

    fn ids(p: &Plan) -> Vec<&str> {
        p.steps.iter().map(|x| x.id.as_str()).collect()
    }
    fn step<'a>(p: &'a Plan, id: &str) -> &'a Step {
        p.steps.iter().find(|x| x.id == id).unwrap()
    }

    #[test]
    fn audit_policy_enable_matches_install() {
        let s = Scratch::new();
        let data = s.path().join("d");
        let enable = build_audit_plan(&AuditArgs { enable: true, data_root: Some(data.clone()), ..Default::default() }, &FakeHost::new()).unwrap();
        let install = build_install_plan(&InstallArgs { install_dir: Some(s.path().join("i")), data_root: Some(data), ..Default::default() }, &FakeHost::new()).unwrap();
        let mut want = vec!["require_admin", "secure_data_root", "record_registry"];
        want.extend(AUDIT_STEPS);
        assert_eq!(ids(&enable), want);
        assert_eq!(enable.script, "audit-policy");
        for id in AUDIT_STEPS.iter().chain(["secure_data_root"].iter()) {
            assert_eq!(step(&enable, id), step(&install, id), "{id}");
        }
    }

    #[test]
    fn audit_policy_enable_records_the_registry_before_it_changes() {
        let s = Scratch::new();
        let data = s.path().join("d");
        let p = build_audit_plan(&AuditArgs { enable: true, data_root: Some(data.clone()), ..Default::default() }, &FakeHost::new()).unwrap();
        let rec = step(&p, "record_registry");
        assert_eq!((rec.cmd.as_str(), rec.when.as_deref()), ("(write-json)", Some("no_registry_record_yet")));
        assert_eq!(rec.args[0], format!(r"{}\data\audit-policy-state.json", data.display()));
        let v: Value = serde_json::from_str(&rec.args[1]).unwrap();
        assert_eq!(v["registry_before"].as_object().unwrap().len(), 2);
        assert_eq!(v["audit_backup"], format!(r"{}\data\auditpol-backup.csv", data.display()));
    }

    #[test]
    fn audit_policy_restore_plan_reads_the_recorded_values() {
        let s = Scratch::new();
        let data = s.path().join("d");
        fs::create_dir_all(data.join("data")).unwrap();
        fs::write(data.join("data/audit-policy-state.json"), json!({"registry_before": {AUDIT_VALUE: null, PS_VALUE: 0}}).to_string()).unwrap();
        let backup = s.path().join("백업.csv");
        fs::write(&backup, "x").unwrap();
        let p = build_audit_plan(&AuditArgs { restore: Some(backup.clone()), data_root: Some(data), ..Default::default() }, &FakeHost::new()).unwrap();
        assert_eq!(ids(&p), ["require_admin", "restore_audit_policy", "restore_registry"]);
        assert_eq!(step(&p, "restore_audit_policy").args, ["/restore".to_string(), format!("/file:{}", backup.display())]);
        assert_eq!(step(&p, "restore_registry").args, [format!("{AUDIT_VALUE}=null"), format!("{PS_VALUE}=0")]);
    }

    #[test]
    fn audit_policy_argument_errors() {
        let s = Scratch::new();
        let foreign = s.path().join("foreign");
        fs::create_dir_all(foreign.join("x")).unwrap();
        let bad = [
            AuditArgs::default(),
            AuditArgs { enable: true, restore: Some(s.path().join("x.csv")), ..Default::default() },
            AuditArgs { restore: Some(s.path().join("missing.csv")), ..Default::default() },
            AuditArgs { enable: true, data_root: Some(format!("{}\\", std::env::var("SystemDrive").unwrap()).into()), ..Default::default() },
            AuditArgs { enable: true, data_root: Some(foreign), ..Default::default() },
        ];
        for a in bad {
            assert!(build_audit_plan(&a, &FakeHost::new()).is_err(), "{a:?}");
        }
    }

    #[test]
    fn restore_registry_refuses_values_install_never_set() {
        for bad in [r"HKLM\SOFTWARE\Evil\Run=1".to_string(), format!("{AUDIT_VALUE}=1 /f"), format!("{PS_VALUE}=-1")] {
            assert!(validate_registry_restore(&[bad.clone()]).unwrap_err().starts_with("알 수 없는 레지스트리 값"), "{bad}");
        }
        let ok = validate_registry_restore(&[format!("{AUDIT_VALUE}=null"), format!("{PS_VALUE}=0")]).unwrap();
        assert_eq!(ok[1], (r"HKLM\SOFTWARE\Policies\Microsoft\Windows\PowerShell\ScriptBlockLogging".to_string(), "EnableScriptBlockLogging".to_string(), Some(0)));
        assert_eq!(ok[0].2, None);
    }
}
```

```rust
// desktop/tests/install_cli.rs
mod common;
use common::*;

#[test]
fn install_dry_run_prints_one_json_line() {
    mcp_monitor::winutil::assert_not_elevated();
    let s = Scratch::new();
    let o = exe().args(["install", "--dry-run", "--install-dir"]).arg(s.join("i")).arg("--data-root").arg(s.join("d")).output().unwrap();
    assert_eq!(o.status.code(), Some(0), "{}", String::from_utf8_lossy(&o.stderr));
    let text = String::from_utf8(o.stdout).unwrap();
    assert_eq!(text.lines().count(), 1);
    let plan: serde_json::Value = serde_json::from_str(&text).unwrap();
    assert_eq!((plan["script"].as_str(), plan["steps"][0]["id"].as_str()), (Some("install"), Some("require_admin")));
    assert!(!s.join("i").exists() && !s.join("d").exists());
}

#[test]
fn install_without_admin_exits_1_and_changes_nothing() {
    mcp_monitor::winutil::assert_not_elevated();
    let s = Scratch::new();
    let o = exe().args(["install", "--install-dir"]).arg(s.join("i")).arg("--data-root").arg(s.join("d")).output().unwrap();
    assert_eq!(o.status.code(), Some(1), "{}", String::from_utf8_lossy(&o.stderr));
    assert!(String::from_utf8(o.stdout).unwrap().contains("관리자 권한으로 다시 실행하세요"));
    assert!(!s.join("i").exists() && !s.join("d").exists() && !s.join("i.staging").exists());
}

#[test]
fn audit_policy_without_admin_exits_1_and_changes_nothing() {
    mcp_monitor::winutil::assert_not_elevated();
    let s = Scratch::new();
    let o = exe().args(["audit-policy", "--enable", "--data-root"]).arg(s.join("d")).output().unwrap();
    assert_eq!(o.status.code(), Some(1));
    assert!(!s.join("d").exists());
}

#[test]
fn install_argument_errors_print_nothing_on_stdout() {
    let s = Scratch::new();
    let o = exe().args(["install", "--dry-run", "--local-port", "8800", "--external-port", "8800", "--install-dir"]).arg(s.join("i")).output().unwrap();
    assert_eq!(o.status.code(), Some(2));
    assert!(o.stdout.is_empty() && String::from_utf8(o.stderr).unwrap().starts_with("오류: --local-port"));
}
```

- [ ] **Step 2: 실패 확인** — Run: `cargo test --locked install` → FAIL

- [ ] **Step 3: 구현** — 위 Interfaces대로. `serde_json`의 `Map`은 기본 정렬(BTreeMap)이므로 `registry_before` 키 순서는 사전 순입니다(테스트가 그 순서를 씀). `Plan`·`Step`의 JSON 키 순서는 구조체 필드 순서입니다.

- [ ] **Step 4: 통과 확인** — Rust 검사 3종 → 통과. Run: `target\debug\mcp-monitor.exe install --dry-run | Write-Output` → JSON 한 줄(이 PC의 실제 Program Files·ProgramData 경로, `notes` 비어 있음 또는 읽기 제한 note), 종료 코드 0.

- [ ] **Step 5: Commit** — `git commit -m "feat(desktop): install and audit-policy plans with --dry-run (same steps and arguments as install.ps1, staged upgrade, Apps & features, start menu, firewall cleanup)"`

---

### Task 7: 설치 실행 동작 — 스테이징·교체·업그레이드·앱 정지·앱 및 기능·바로 가기

**Files:**
- Create: `desktop/src/install/stage.rs`, `desktop/src/install/registry.rs`, `desktop/src/install/shortcut.rs`, `desktop/src/install/procs.rs`
- Modify: `desktop/src/install/exec.rs`

**Interfaces:**
- Produces:
  - `stage`:
    - `pub struct PayloadSource { pub archive: Vec<u8>, pub sha256: String, pub manifest: Manifest, pub kind: String }`, `PayloadSource::embedded()`(= `payload::{ARCHIVE, ARCHIVE_SHA256, manifest(), KIND}`).
    - `pub fn stage(staging: &Path, src: &PayloadSource, self_exe: &Path) -> Result<u64, String>`: `src.kind != "release"` → `Err("개발용(fixture) payload로는 설치할 수 없습니다. install\\build-desktop.ps1로 만든 실행 파일을 쓰세요.")`(아무것도 만들지 않음); `verify_archive`; `staging`이 있으면 `STAGING_MARKER`가 있을 때만 지우고, 없으면 `Err("<staging> 이(가) 이미 있고 설치기가 만든 폴더가 아닙니다")`; `extract`; `self_exe`를 `staging\mcp-monitor.exe`로 복사하고 원본과 복사본의 SHA-256이 같은지 확인.
    - `pub trait FsOps { fn rename(&self, from: &Path, to: &Path) -> io::Result<()>; }`, `StdFs`(`MoveFileExW(…, MOVEFILE_WRITE_THROUGH)`).
    - `pub fn swap(staging: &Path, install_dir: &Path, old: &Path, fs: &dyn FsOps, owners: &[String]) -> Result<(), String>`: `staging`에 마커가 없으면 Err; `old`가 있으면 `bundle.json`이 있을 때만 지우고 아니면 Err; `install_dir`이 있으면 `bundle.json`이 있어야 하고 `install_dir → old`; `staging → install_dir`(실패하면 `old → install_dir`로 되돌리고 Err); 마커 삭제; `install_tree_problem(install_dir, owners)`가 있으면 되돌리고(`install_dir → staging`, `old → install_dir`) Err.
    - `pub fn remove_old(old: &Path) -> Result<(), String>`: `bundle.json`이 없으면 Err, 있으면 `remove_dir_all`.
  - `procs`:
    - `pub fn select_app_processes(procs: &[(u32, String)], install_dir: &Path, own_pid: u32) -> Vec<u32>`: 이미지 경로가 `install_dir` 안(대소문자 무시, `is_inside`)이고 자신이 아닌 pid.
    - `pub fn stop_apps(install_dir: &Path) -> Result<(), String>`: Toolhelp 스냅숏 + `QueryFullProcessImageNameW`(열 수 없는 프로세스는 건너뜀) → `select_app_processes` → `TerminateProcess(…, 1)` → 프로세스마다 5초까지 대기; 남으면 `Err("<pid> <경로> 이(가) 끝나지 않았습니다")`. (앱 모드 트레이·남은 에이전트를 끝냄. 서비스는 앞 단계에서 이미 멈춤 — Y15.)
  - `registry`: `pub enum RegValue { Sz(String), Dword(u32) }`, `pub fn parse_reg_value(s: &str) -> Result<(String, RegValue), String>`(`Name=REG_SZ:text` | `Name=REG_DWORD:<u32>`; 그 밖은 Err), `pub trait Registry { fn set_values(&mut self, key: &str, values: &[(String, RegValue)]) -> Result<(), String>; fn delete_key(&mut self, key: &str) -> Result<(), String>; fn delete_value(&mut self, key: &str, name: &str) -> Result<(), String>; fn string(&self, key: &str, name: &str) -> Option<String>; fn subkeys(&self, key: &str) -> Vec<String>; }`, `WinRegistry`(`HKLM\`·`HKU\`·`HKCU\` 접두어, `RegCreateKeyExW`/`RegSetValueExW`/`RegDeleteTreeW`/`RegDeleteKeyValueW`, 64비트 보기), `#[cfg(test)] FakeRegistry(BTreeMap<String, BTreeMap<String, RegValue>>)`.
  - `shortcut::create_shortcut(lnk: &Path, target: &Path, args: &str, description: &str) -> Result<(), String>`(`CoInitializeEx(APARTMENTTHREADED)` + `IShellLinkW` + `IPersistFile::Save`; 작업 폴더 = 대상의 폴더), `shortcut::read_shortcut(lnk) -> Result<(PathBuf, String), String>`(테스트·진단).
  - `exec::check_os_warnings(caption: &str, sku: u32, install_dir: &Path, program_files: &Path, webview2: Option<&str>) -> Vec<String>`: Home(캡션에 `Home` 또는 SKU 98·99·100·101) → `"경고: <caption>은(는) RDP 호스트가 아니어서 세션 수집이 동작하지 않습니다. 설치는 계속합니다."`; `install_dir`이 `program_files` 밖 → `"경고: <I> 은(는) Program Files 밖입니다. …"`; WebView2 런타임 버전 없음(`HKLM\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}`의 `pv`가 없거나 `0.0.0.0`) → `"경고: WebView2 런타임이 없습니다. 관리 화면 창과 고지 창이 열리지 않습니다(https://go.microsoft.com/fwlink/p/?LinkId=2124703 에서 설치)."`.
  - `RealExecutor` 추가: `(check-os)`(경고를 출력하고 0), `(stage)`, `(stop-apps)`, `(swap)`, `(registry-set)`, `(shortcut)`, `(remove-old)`, 조건 `old_exists`(`<I>.old` 있음).

- [ ] **Step 1: 실패하는 테스트 작성**

```rust
// desktop/src/install/stage.rs (tests)
#[cfg(test)]
mod tests {
    use super::*;
    use crate::install::testutil::*;
    use crate::payload::STAGING_MARKER;
    use crate::payload_pack::pack_dir;
    use std::cell::Cell;
    use std::fs;

    fn source(s: &Scratch, kind: &str) -> PayloadSource {
        let src = s.path().join("payload");
        fs::create_dir_all(src.join("bin/monitor")).unwrap();
        fs::write(src.join("bundle.json"), r#"{"layout":"pyinstaller","version":"1.1.0","agent":"desktop"}"#).unwrap();
        fs::write(src.join("bin/monitor/mcp-monitor-server.exe"), b"MZ server").unwrap();
        let p = pack_dir(&src, 3).unwrap();
        PayloadSource { archive: p.archive, sha256: p.sha256, manifest: p.manifest, kind: kind.into() }
    }

    fn self_exe(s: &Scratch) -> PathBuf {
        let p = s.path().join("downloads").join("mcp-monitor-1.1.0.exe");
        fs::create_dir_all(p.parent().unwrap()).unwrap();
        fs::write(&p, b"MZ self").unwrap();
        p
    }

    #[test]
    fn stage_extracts_the_payload_and_copies_this_exe() {
        let s = Scratch::new();
        let staging = s.path().join("i.staging");
        stage(&staging, &source(&s, "release"), &self_exe(&s)).unwrap();
        assert_eq!(fs::read(staging.join("mcp-monitor.exe")).unwrap(), b"MZ self");
        assert!(staging.join("bin/monitor/mcp-monitor-server.exe").is_file() && staging.join(STAGING_MARKER).is_file());
    }

    #[test]
    fn stage_refuses_the_fixture_payload() {
        let s = Scratch::new();
        let staging = s.path().join("i.staging");
        assert!(stage(&staging, &source(&s, "fixture"), &self_exe(&s)).unwrap_err().contains("개발용"));
        assert!(!staging.exists());
    }

    #[test]
    fn stage_refuses_a_staging_folder_it_did_not_make() {
        let s = Scratch::new();
        let staging = s.path().join("i.staging");
        fs::create_dir(&staging).unwrap();
        fs::write(staging.join("keep.txt"), "x").unwrap();
        assert!(stage(&staging, &source(&s, "release"), &self_exe(&s)).is_err());
        assert!(staging.join("keep.txt").is_file());
        fs::remove_file(staging.join("keep.txt")).unwrap();
        fs::write(staging.join(STAGING_MARKER), "{}").unwrap(); // an earlier, unfinished staging of ours
        stage(&staging, &source(&s, "release"), &self_exe(&s)).unwrap();
    }

    fn tree(dir: &Path, version: &str) {
        fs::create_dir_all(dir).unwrap();
        fs::write(dir.join("bundle.json"), version).unwrap();
    }

    #[test]
    fn swap_moves_the_old_install_aside_and_puts_staging_in_place() {
        let s = Scratch::new();
        let (staging, inst, old) = (s.path().join("i.staging"), s.path().join("i"), s.path().join("i.old"));
        tree(&inst, "old");
        tree(&staging, "new");
        fs::write(staging.join(STAGING_MARKER), "{}").unwrap();
        swap(&staging, &inst, &old, &StdFs, &owners()).unwrap();
        assert_eq!(fs::read_to_string(inst.join("bundle.json")).unwrap(), "new");
        assert_eq!(fs::read_to_string(old.join("bundle.json")).unwrap(), "old");
        assert!(!staging.exists() && !inst.join(STAGING_MARKER).exists());
        remove_old(&old).unwrap();
        assert!(!old.exists());
    }

    #[test]
    fn swap_into_a_missing_install_dir() {
        let s = Scratch::new();
        let (staging, inst, old) = (s.path().join("i.staging"), s.path().join("i"), s.path().join("i.old"));
        tree(&staging, "new");
        fs::write(staging.join(STAGING_MARKER), "{}").unwrap();
        swap(&staging, &inst, &old, &StdFs, &owners()).unwrap();
        assert!(inst.join("bundle.json").is_file() && !old.exists());
    }

    struct FailSecond(Cell<u32>);
    impl FsOps for FailSecond {
        fn rename(&self, from: &Path, to: &Path) -> io::Result<()> {
            self.0.set(self.0.get() + 1);
            if self.0.get() == 2 {
                return Err(io::Error::from_raw_os_error(32)); // ERROR_SHARING_VIOLATION: a file is still open
            }
            StdFs.rename(from, to)
        }
    }

    #[test]
    fn swap_rolls_back_when_staging_cannot_be_moved() {
        let s = Scratch::new();
        let (staging, inst, old) = (s.path().join("i.staging"), s.path().join("i"), s.path().join("i.old"));
        tree(&inst, "old");
        tree(&staging, "new");
        fs::write(staging.join(STAGING_MARKER), "{}").unwrap();
        assert!(swap(&staging, &inst, &old, &FailSecond(Cell::new(0)), &owners()).is_err());
        assert_eq!(fs::read_to_string(inst.join("bundle.json")).unwrap(), "old");
        assert!(staging.join("bundle.json").is_file() && !old.exists());
    }

    #[test]
    fn swap_refuses_an_install_tree_others_may_write() {
        let s = Scratch::new();
        let (staging, inst, old) = (s.path().join("i.staging"), s.path().join("i"), s.path().join("i.old"));
        tree(&inst, "old");
        tree(&staging, "new");
        fs::write(staging.join(STAGING_MARKER), "{}").unwrap();
        grant(&staging.join("bundle.json"), "(W)");
        let e = swap(&staging, &inst, &old, &StdFs, &owners()).unwrap_err();
        assert!(e.contains(AUTHENTICATED_USERS), "{e}");
        assert_eq!(fs::read_to_string(inst.join("bundle.json")).unwrap(), "old");
        assert!(!old.exists());
    }

    #[test]
    fn remove_old_refuses_a_folder_without_bundle_json() {
        let s = Scratch::new();
        let old = s.path().join("i.old");
        fs::create_dir(&old).unwrap();
        fs::write(old.join("x"), "x").unwrap();
        assert!(remove_old(&old).is_err());
        assert!(old.join("x").is_file());
    }
}
```

```rust
// desktop/src/install/procs.rs (tests)
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stop_apps_targets_only_processes_inside_the_install_dir() {
        let procs = [
            (10, r"C:\Program Files\MCP Monitor\mcp-monitor.exe".to_string()),
            (11, r"C:\Program Files\MCP Monitor Other\x.exe".to_string()),
            (12, r"c:\program files\mcp monitor\BIN\monitor\mcp-monitor-server.exe".to_string()),
            (13, r"C:\Users\a\Downloads\mcp-monitor.exe".to_string()),
            (14, r"C:\Program Files\MCP Monitor\mcp-monitor.exe".to_string()),
        ];
        assert_eq!(select_app_processes(&procs, Path::new(r"C:\Program Files\MCP Monitor"), 14), [10, 12]);
    }
}
```

```rust
// desktop/src/install/exec.rs (tests, added)
#[cfg(test)]
mod tests {
    use super::*;
    use crate::install::registry::{parse_reg_value, FakeRegistry, RegValue, Registry};
    use crate::install::shortcut::{create_shortcut, read_shortcut};
    use crate::install::testutil::*;
    use std::io::{Read, Write};
    use std::net::TcpListener;

    #[test]
    fn check_os_warnings_cover_home_program_files_and_webview2() {
        let pf = Path::new(r"C:\Program Files");
        let w = check_os_warnings("Microsoft Windows 11 Home", 101, Path::new(r"D:\apps\MCP Monitor"), pf, None);
        assert_eq!(w.len(), 3);
        assert!(w[0].contains("RDP") && w[1].contains("Program Files") && w[2].contains("WebView2"), "{w:?}");
        assert!(check_os_warnings("Microsoft Windows 11 Pro", 48, &pf.join("MCP Monitor"), pf, Some("156.0.0.0")).is_empty());
        assert!(check_os_warnings("Microsoft Windows 11 Pro", 48, &pf.join("MCP Monitor"), pf, Some("0.0.0.0"))[0].contains("WebView2"));
    }

    #[test]
    fn registry_values_are_typed_and_applied() {
        assert_eq!(parse_reg_value("DisplayName=REG_SZ:MCP Monitor").unwrap(), ("DisplayName".into(), RegValue::Sz("MCP Monitor".into())));
        assert_eq!(parse_reg_value(r#"DisplayIcon=REG_SZ:"C:\a b\x.exe",0"#).unwrap().1, RegValue::Sz(r#""C:\a b\x.exe",0"#.into()));
        assert_eq!(parse_reg_value("NoModify=REG_DWORD:1").unwrap(), ("NoModify".into(), RegValue::Dword(1)));
        for bad in ["X=REG_BINARY:1", "X=REG_DWORD:-1", "=REG_SZ:a", "X", "X=REG_DWORD:4294967296"] {
            assert!(parse_reg_value(bad).is_err(), "{bad}");
        }
        let mut r = FakeRegistry::default();
        r.set_values("HKLM\\X", &[("A".into(), RegValue::Dword(1))]).unwrap();
        assert_eq!(r.string("HKLM\\X", "A"), None);
        r.delete_key("HKLM\\X").unwrap();
        assert!(r.subkeys("HKLM").is_empty());
    }

    #[test]
    fn shortcut_points_at_the_target() {
        let s = Scratch::new();
        let target = s.path().join("i").join("mcp-monitor.exe");
        std::fs::create_dir_all(target.parent().unwrap()).unwrap();
        std::fs::write(&target, b"MZ").unwrap();
        let lnk = s.path().join("MCP Monitor.lnk");
        create_shortcut(&lnk, &target, "", "MCP Monitor").unwrap();
        assert_eq!(read_shortcut(&lnk).unwrap(), (target, "MCP Monitor".to_string()));
    }

    #[test]
    fn write_state_stamps_installed_at_and_writes_utf8_without_bom() {
        let s = Scratch::new();
        let path = s.path().join("install-state.json");
        write_state(&path, r#"{"installed_at":null,"version":"1.1.0","registry_before":{}}"#).unwrap();
        let raw = std::fs::read(&path).unwrap();
        assert!(!raw.starts_with(b"\xef\xbb\xbf"));
        let v: serde_json::Value = serde_json::from_slice(&raw).unwrap();
        let at = v["installed_at"].as_str().unwrap();
        assert!(regex::Regex::new(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+09:00$").unwrap().is_match(at), "{at}");
        assert_eq!(v["version"], "1.1.0");
    }

    #[test]
    fn wait_ready_polls_until_200_and_fails_after_the_deadline() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        std::thread::spawn(move || {
            for stream in listener.incoming() {
                let mut stream = stream.unwrap();
                let mut buf = [0u8; 1024];
                let n = stream.read(&mut buf).unwrap();
                let ok = String::from_utf8_lossy(&buf[..n]).starts_with("GET /api/channel ");
                let status = if ok { "200 OK" } else { "404 Not Found" };
                let _ = stream.write_all(format!("HTTP/1.1 {status}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n").as_bytes());
            }
        });
        wait_ready(&format!("http://127.0.0.1:{port}/api/channel"), 5).unwrap();
        let started = std::time::Instant::now();
        assert!(wait_ready(&format!("http://127.0.0.1:{port}/missing"), 1).unwrap_err().contains("응답하지 않았습니다"));
        assert!(started.elapsed().as_secs_f64() < 5.0);
    }
}
```

- [ ] **Step 2: 실패 확인** — Run: `cargo test --locked install` → FAIL

- [ ] **Step 3: 구현** — 위 Interfaces대로. 실제 `WinRegistry`·`stop_apps`·`TerminateProcess`는 이 PC에서 테스트하지 않습니다(관리자·HKLM, Global Constraints) — 실기기 P8-5·P8-11.

- [ ] **Step 4: 통과 확인** — Rust 검사 3종 → 통과.

- [ ] **Step 5: Commit** — `git commit -m "feat(desktop): staged install with hash-checked extraction, rollback-safe folder swap, app shutdown, Apps & features entry and start menu shortcut"`

---

### Task 8: 제거(`uninstall`) — 데이터 안전, 실행 중인 자신, 프로필·Run 값

**Files:**
- Create: `desktop/src/install/uninstall_plan.rs`, `desktop/src/install/remove.rs`, `desktop/tests/uninstall_cli.rs`
- Modify: `desktop/src/install/exec.rs`, `desktop/src/lib.rs`(`Uninstall` 연결)

**Interfaces:**
- Produces:
  - `build_uninstall_plan(a: &UninstallArgs, h: &dyn Host) -> Result<Plan, ArgError>`:
    - `I` = `--install-dir` → `h.installed().install_location` → `<D>\data\install-state.json`의 `install_dir` → `%ProgramFiles%\MCP Monitor`; `D` = `--data-root` → `<I>\install.json`의 `data_root` → `%ProgramData%\MCP Monitor`. 이전 상태(읽을 수 있을 때)에서 `EP`(없으면 8701), `audit_backup`(없으면 `<D>\data\auditpol-backup.csv`), `registry_before`(없으면 `audit-policy-state.json`).
    - 인자 오류(2): `--remove-data`일 때 `D`의 `unsafe_root_reason`(문구 끝 `--remove-data는 이 폴더를 지우지 않습니다.`); `I`의 `unsafe_root_reason`; `--remove-data` 없이 `D`가 `I`와 같거나 그 안(`… -RemoveData로 함께 지우기` 대신 `--remove-data로 함께 지우기`).
    - 단계(이 순서): `require_admin` `(admin)`; `stop_service` `sc.exe stop mcp-monitor` ok `[0, 1060, 1062]`(after: 60초 정지 대기); `delete_service` `sc.exe delete mcp-monitor` ok `[0, 1060]`; `stop_apps` `(stop-apps)` `[I]`; `firewall_delete` `netsh advfirewall firewall delete rule name=MCP Monitor (EP)` ok `[0, 1]`; [`--restore-audit-policy`: `restore_audit_policy` `auditpol /restore /file:<backup>` when `audit_backup_exists`, `restore_registry` `(reg-restore)` `<entries>`]; `remove_uninstall_entry` `(registry-delete)` `[UNINSTALL_KEY]`; `remove_shortcut` `(remove)` `[<ProgramData>\Microsoft\Windows\Start Menu\Programs\MCP Monitor.lnk]`; `remove_run_values` `(run-values-remove)` `[I]`; `remove_install_dir` `(remove-install)` `[I]` when `install_dir_is_bundle`; [`--remove-data`: `remove_data` `(remove)` `[D]` when `data_root_is_ours`, `remove_webview_profiles` `(remove-glob)` `[<Users>\*\AppData\Local\mcp-monitor]`(`<Users>` = `PUBLIC`의 부모)]. `Plan.script = "uninstall"`, `version`·`layout`은 이전 상태의 값(없으면 null), `service_mode` null.
  - `remove`:
    - `pub fn install_dir_is_bundle(dir, env, vols) -> bool`(= `bundle.json` 있음 && `unsafe_root_reason == None`), `pub fn data_root_is_ours(root, env, vols) -> bool`(= `data_root_marker` && 안전).
    - `pub fn remove_install_dir(dir: &Path, self_exe: &Path, schedule: &mut dyn FnMut(&Path)) -> Result<(), String>`: `self_exe`가 `dir` 안이면 `mcp-monitor.exe.uninstalled`(이미 있으면 `.uninstalled-2`, `-3` …)로 이름을 바꾸고 나머지를 모두 지운 뒤 `schedule(바꾼 파일)`, `schedule(dir)`(실제 = `MoveFileExW(path, NULL, MOVEFILE_DELAY_UNTIL_REBOOT)`, Y21); 아니면 `remove_dir_all(dir)`.
    - `pub fn remove_glob(pattern: &Path) -> Result<u32, String>`: `<Users>\*\AppData\Local\mcp-monitor` 형태만(마지막 세 부분 고정, `*`는 정확히 한 단계); 맞는 폴더를 지우고 개수를 돌려줌. 링크인 폴더는 링크만 지움(따라가지 않음).
    - `pub fn select_run_values(values: &[(String, String)], install_dir: &Path) -> Vec<String>`: `(SID, 값 데이터)` 중 데이터의 첫 인자(따옴표 제거)가 `install_dir` 안인 SID. 실제 `(run-values-remove)`는 `HKU`의 `S-1-5-21-*` 하위 키(`_Classes` 제외)에서 `Software\Microsoft\Windows\CurrentVersion\Run\MCPMonitor`를 읽어 고른 것만 지웁니다(로그온하지 않은 사용자의 하이브는 다루지 않음 — 운영 문서, Y20).
  - `RealExecutor` 추가: `(registry-delete)`, `(remove)`, `(remove-install)`, `(remove-glob)`, `(run-values-remove)`, 조건 `audit_backup_exists`, `install_dir_is_bundle`, `data_root_is_ours`. 실행 전 현재 폴더를 System32로 바꿉니다(지울 폴더가 현재 폴더면 지울 수 없음).
  - 끝 줄: `제거 완료(데이터 포함).` / `제거 완료. 데이터는 <D> 에 남아 있습니다(지우려면 --remove-data).` + 실행 중인 자신을 남겼으면 `설치 폴더의 남은 파일은 다시 시작할 때 지워집니다.`

- [ ] **Step 1: 실패하는 테스트 작성**

```rust
// desktop/src/install/uninstall_plan.rs (tests)
#[cfg(test)]
mod tests {
    use super::*;
    use crate::install::audit::{AUDIT_VALUE, PS_VALUE};
    use crate::install::host::{FakeHost, Installed};
    use crate::install::testutil::*;
    use serde_json::json;
    use std::{fs, path::PathBuf};

    fn base(s: &Scratch) -> UninstallArgs {
        UninstallArgs { install_dir: Some(s.path().join("i")), data_root: Some(s.path().join("d")), ..Default::default() }
    }
    fn ids(p: &Plan) -> Vec<&str> {
        p.steps.iter().map(|x| x.id.as_str()).collect()
    }
    fn step<'a>(p: &'a Plan, id: &str) -> &'a Step {
        p.steps.iter().find(|x| x.id == id).unwrap()
    }

    #[test]
    fn uninstall_plan_keeps_data_by_default() {
        let s = Scratch::new();
        assert_eq!(ids(&build_uninstall_plan(&base(&s), &FakeHost::new()).unwrap()), [
            "require_admin", "stop_service", "delete_service", "stop_apps", "firewall_delete", "remove_uninstall_entry",
            "remove_shortcut", "remove_run_values", "remove_install_dir"]);
        let full = UninstallArgs { remove_data: true, restore_audit_policy: true, ..base(&s) };
        assert_eq!(ids(&build_uninstall_plan(&full, &FakeHost::new()).unwrap()), [
            "require_admin", "stop_service", "delete_service", "stop_apps", "firewall_delete", "restore_audit_policy",
            "restore_registry", "remove_uninstall_entry", "remove_shortcut", "remove_run_values", "remove_install_dir",
            "remove_data", "remove_webview_profiles"]);
    }

    #[test]
    fn uninstall_plan_details_without_state() {
        let s = Scratch::new();
        let (inst, data) = (s.path().join("i").display().to_string(), s.path().join("d").display().to_string());
        let p = build_uninstall_plan(&UninstallArgs { remove_data: true, restore_audit_policy: true, ..base(&s) }, &FakeHost::new()).unwrap();
        assert_eq!((p.script.as_str(), p.install_dir.as_deref(), p.data_root.as_deref(), p.version.as_deref()), ("uninstall", Some(inst.as_str()), Some(data.as_str()), None));
        assert_eq!(step(&p, "stop_service").ok, [0, 1060, 1062]);
        assert_eq!((step(&p, "delete_service").args.clone(), step(&p, "delete_service").ok.clone()), (vec!["delete".to_string(), "mcp-monitor".into()], vec![0, 1060]));
        let fw = step(&p, "firewall_delete");
        assert_eq!((fw.args.clone(), fw.ok.clone()), (["advfirewall", "firewall", "delete", "rule", "name=MCP Monitor (8701)"].map(String::from).to_vec(), vec![0, 1]));
        assert_eq!(step(&p, "restore_audit_policy").args, ["/restore".to_string(), format!(r"/file:{data}\data\auditpol-backup.csv")]);
        assert!(step(&p, "restore_registry").args.is_empty());
        assert_eq!((step(&p, "remove_install_dir").cmd.as_str(), step(&p, "remove_install_dir").when.as_deref()), ("(remove-install)", Some("install_dir_is_bundle")));
        assert_eq!(step(&p, "remove_data").args, [data.clone()]);
        assert_eq!(step(&p, "remove_data").when.as_deref(), Some("data_root_is_ours"));
        let profiles = &step(&p, "remove_webview_profiles").args;
        assert!(profiles.len() == 1 && profiles[0].ends_with(r"\*\AppData\Local\mcp-monitor"), "{profiles:?}");
        assert_eq!(step(&p, "remove_uninstall_entry").args, [UNINSTALL_KEY]);
    }

    #[test]
    fn uninstall_plan_reads_the_install_state() {
        let s = Scratch::new();
        let data = s.path().join("d");
        fs::create_dir_all(data.join("data")).unwrap();
        let backup = data.join("data/auditpol-backup.csv").display().to_string().replace('/', "\\");
        fs::write(data.join("data/install-state.json"), json!({"version": "1.1.0", "layout": "pyinstaller", "external_port": 9701, "firewall": true,
            "registry_before": {AUDIT_VALUE: null, PS_VALUE: 0}, "audit_backup": &backup}).to_string()).unwrap();
        let p = build_uninstall_plan(&UninstallArgs { remove_data: true, restore_audit_policy: true, ..base(&s) }, &FakeHost::new()).unwrap();
        assert_eq!((p.version.as_deref(), p.layout.as_deref()), (Some("1.1.0"), Some("pyinstaller")));
        assert_eq!(step(&p, "firewall_delete").args[4], "name=MCP Monitor (9701)");
        assert_eq!(step(&p, "restore_audit_policy").args, ["/restore".to_string(), format!("/file:{backup}")]);
        assert_eq!(step(&p, "restore_registry").args, [format!("{AUDIT_VALUE}=null"), format!("{PS_VALUE}=0")]);
    }

    #[test]
    fn uninstall_reads_the_install_dir_from_apps_and_features() {
        let s = Scratch::new();
        let mut h = FakeHost::new();
        h.installed = Some(Installed { version: "1.1.0".into(), install_location: s.path().join("elsewhere") });
        let p = build_uninstall_plan(&UninstallArgs { data_root: Some(s.path().join("d")), ..Default::default() }, &h).unwrap();
        assert_eq!(p.install_dir.as_deref(), Some(s.path().join("elsewhere").display().to_string().as_str()));
    }

    #[test]
    fn uninstall_refuses_to_remove_unsafe_roots() {
        let s = Scratch::new();
        let e = std::env::var;
        let cases = [
            UninstallArgs { data_root: Some(format!("{}\\", e("SystemDrive").unwrap()).into()), remove_data: true, ..base(&s) },
            UninstallArgs { data_root: Some(e("ProgramData").unwrap().into()), remove_data: true, ..base(&s) },
            UninstallArgs { data_root: Some(PathBuf::from(e("PUBLIC").unwrap()).parent().unwrap().to_path_buf()), remove_data: true, ..base(&s) },
            UninstallArgs { data_root: Some(s.path().join("i").join("var")), ..base(&s) },
        ];
        for a in cases {
            assert!(build_uninstall_plan(&a, &FakeHost::new()).is_err(), "{a:?}");
        }
    }

    #[test]
    fn uninstall_refuses_device_unc_and_linked_paths() {
        let s = Scratch::new();
        let marked = s.path().join("real").join("marked");
        fs::create_dir_all(marked.join("data")).unwrap();
        fs::write(marked.join("data/mcp-monitor-data-root.json"), "{}").unwrap();
        junction(&s.path().join("link"), &s.path().join("real"));
        let m = marked.display().to_string();
        let bad = [format!(r"\\?\{m}"), format!(r"\\localhost\{}$\{}", &m[..1], &m[3..]), s.path().join("link").join("marked").display().to_string()];
        for b in &bad {
            assert!(build_uninstall_plan(&UninstallArgs { data_root: Some(b.into()), remove_data: true, ..base(&s) }, &FakeHost::new()).is_err(), "{b}");
            assert!(build_uninstall_plan(&UninstallArgs { install_dir: Some(b.into()), ..base(&s) }, &FakeHost::new()).is_err(), "{b}");
        }
        assert!(marked.join("data/mcp-monitor-data-root.json").is_file());
    }
}
```

```rust
// desktop/src/install/remove.rs (tests)
#[cfg(test)]
mod tests {
    use super::*;
    use crate::install::paths::{Env, SystemVolumes};
    use crate::install::testutil::*;
    use std::fs;

    #[test]
    fn only_a_marked_data_root_and_a_bundle_install_dir_are_removed() {
        let s = Scratch::new();
        let (bare, marked, inst) = (s.path().join("bare"), s.path().join("marked"), s.path().join("i"));
        for d in [&bare, &marked, &inst] {
            fs::create_dir_all(d.join("data")).unwrap();
        }
        fs::write(marked.join("data/mcp-monitor-data-root.json"), "{}").unwrap();
        fs::write(inst.join("bundle.json"), "{}").unwrap();
        let (e, v) = (Env::from_process(), SystemVolumes);
        assert!(!data_root_is_ours(&bare, &e, &v) && data_root_is_ours(&marked, &e, &v));
        assert!(install_dir_is_bundle(&inst, &e, &v) && !install_dir_is_bundle(&bare, &e, &v));
        let drive = PathBuf::from(format!("{}\\", std::env::var("SystemDrive").unwrap()));
        assert!(!data_root_is_ours(&drive, &e, &v) && !install_dir_is_bundle(&drive, &e, &v));
    }

    #[test]
    fn remove_install_dir_keeps_the_running_exe_for_reboot() {
        let s = Scratch::new();
        let inst = s.path().join("i");
        fs::create_dir_all(inst.join("bin/monitor")).unwrap();
        fs::write(inst.join("bin/monitor/mcp-monitor-server.exe"), b"x").unwrap();
        fs::write(inst.join("mcp-monitor.exe"), b"MZ").unwrap();
        fs::write(inst.join("bundle.json"), "{}").unwrap();
        let mut scheduled = Vec::new();
        remove_install_dir(&inst, &inst.join("mcp-monitor.exe"), &mut |p: &Path| scheduled.push(p.to_path_buf())).unwrap();
        let left: Vec<String> = fs::read_dir(&inst).unwrap().map(|e| e.unwrap().file_name().into_string().unwrap()).collect();
        assert_eq!(left, ["mcp-monitor.exe.uninstalled"]);
        assert_eq!(scheduled, [inst.join("mcp-monitor.exe.uninstalled"), inst.clone()]);
        let other = s.path().join("j");
        fs::create_dir_all(&other).unwrap();
        fs::write(other.join("bundle.json"), "{}").unwrap();
        remove_install_dir(&other, &s.path().join("elsewhere.exe"), &mut |_: &Path| panic!("nothing to schedule")).unwrap();
        assert!(!other.exists());
    }

    #[test]
    fn webview_profiles_are_removed_and_nothing_else() {
        let s = Scratch::new();
        let users = s.path().join("Users");
        for (user, sub) in [("alice", "notice-edge"), ("alice", "webview"), ("bob", "notice-webview")] {
            fs::create_dir_all(users.join(user).join("AppData/Local/mcp-monitor").join(sub)).unwrap();
        }
        fs::create_dir_all(users.join("bob/AppData/Local/other")).unwrap();
        assert_eq!(remove_glob(&users.join("*").join("AppData").join("Local").join("mcp-monitor")).unwrap(), 2);
        assert!(!users.join("alice/AppData/Local/mcp-monitor").exists() && !users.join("bob/AppData/Local/mcp-monitor").exists());
        assert!(users.join("bob/AppData/Local/other").is_dir());
        assert!(remove_glob(&users.join("*").join("AppData")).is_err()); // only the fixed profile pattern
    }

    #[test]
    fn run_values_only_ours() {
        let values = [
            ("S-1-5-21-1-1001".to_string(), r#""C:\Program Files\MCP Monitor\mcp-monitor.exe" app --background"#.to_string()),
            ("S-1-5-21-1-1002".to_string(), r#""C:\Program Files\Other\mcp-monitor.exe" app --background"#.to_string()),
            ("S-1-5-21-1-1003".to_string(), r"c:\program files\mcp monitor\mcp-monitor.exe app --background".to_string()),
        ];
        assert_eq!(select_run_values(&values, Path::new(r"C:\Program Files\MCP Monitor")), ["S-1-5-21-1-1001", "S-1-5-21-1-1003"]);
    }
}
```

```rust
// desktop/tests/uninstall_cli.rs
mod common;
use common::*;

#[test]
fn uninstall_without_admin_exits_1_and_changes_nothing() {
    mcp_monitor::winutil::assert_not_elevated();
    let s = Scratch::new();
    std::fs::create_dir_all(s.join("i")).unwrap();
    std::fs::write(s.join("i/bundle.json"), "{}").unwrap();
    std::fs::create_dir_all(s.join("d/data")).unwrap();
    std::fs::write(s.join("d/data/mcp-monitor-data-root.json"), "{}").unwrap();
    let o = exe().args(["uninstall", "--remove-data", "--restore-audit-policy", "--install-dir"]).arg(s.join("i"))
        .arg("--data-root").arg(s.join("d")).output().unwrap();
    assert_eq!(o.status.code(), Some(1));
    assert!(String::from_utf8(o.stdout).unwrap().contains("관리자 권한으로 다시 실행하세요"));
    assert!(s.join("i/bundle.json").is_file() && s.join("d/data/mcp-monitor-data-root.json").is_file());
}

#[test]
fn uninstall_dry_run_prints_the_plan() {
    let s = Scratch::new();
    let o = exe().args(["uninstall", "--dry-run", "--install-dir"]).arg(s.join("i")).arg("--data-root").arg(s.join("d")).output().unwrap();
    assert_eq!(o.status.code(), Some(0), "{}", String::from_utf8_lossy(&o.stderr));
    let plan: serde_json::Value = serde_json::from_slice(&o.stdout).unwrap();
    assert_eq!(plan["script"], "uninstall");
}
```

- [ ] **Step 2: 실패 확인** — Run: `cargo test --locked` → FAIL

- [ ] **Step 3: 구현** — 위 Interfaces대로.

- [ ] **Step 4: 통과 확인** — Rust 검사 3종 → 통과.

- [ ] **Step 5: Commit** — `git commit -m "feat(desktop): uninstall plan (data kept unless --remove-data on a marked root, running exe removed at reboot, WebView2 profiles and Run values)"`

---

### Task 9: 에이전트 핵심 — 설정, HMAC 서버 증명 클라이언트, 실행기, print 창

**Files:**
- Create: `desktop/src/agent/mod.rs`, `desktop/src/agent/config.rs`, `desktop/src/agent/client.rs`, `desktop/src/agent/runner.rs`, `desktop/src/agent/window.rs`, `desktop/src/agent/testkit.rs`(`#[cfg(test)]`), `desktop/tests/common/agent_server.rs`, `desktop/tests/agent_print.rs`
- Modify: `desktop/src/lib.rs`(`Agent` 연결, 이 과제에서는 `--dialog print`만; `webview`는 Task 11), `desktop/tests/common/mod.rs`(`pub mod agent_server;`)

**Interfaces:**
- Produces(Python `agent/mcp_agent`과 같은 동작·숫자; 이름 대응은 부록 B):
  - `config`: `TOKEN_ENV = "MCPMON_AGENT_TOKEN"`, `SERVER_KEY_ENV = "MCPMON_AGENT_SERVER_KEY"`; `pub trait EnvAccess { fn take(&mut self, name: &str) -> Option<String>; fn names(&self) -> Vec<String>; fn remove(&mut self, name: &str); }`, `ProcessEnv`(`std::env::var`/`remove_var` — 2024 edition에서 `remove_var`는 `unsafe`: 에이전트 모드 진입 직후 **다른 스레드를 만들기 전에만** 부름, `// SAFETY:`에 적음), 테스트용 `impl EnvAccess for HashMap<String, String>`.
    - `take_secrets(env) -> (Option<String>, Option<String>)`: 두 값을 **읽자마자 지웁니다**(무엇이 실패하든 자식 프로세스 — WebView2 — 가 상속하지 않게).
    - `strip_webview2_env(env) -> Vec<String>`: 이름이 `WEBVIEW2_`로 시작하는(대소문자 무시) 변수를 모두 지우고 그 이름들을 돌려줍니다. `dev` 기능 빌드에서는 부르지 않음(Y24).
    - `pub struct AgentConfig { pub server: String, pub token: String, pub server_key: [u8; 32], pub dialog: Dialog, pub url_file: Option<PathBuf>, pub unreachable_exit_sec: f64 }`, `config_from(args: &AgentArgs, token: Option<String>, key: Option<String>) -> Result<AgentConfig, ArgError>`: 토큰이 없거나 빈 값 → `"MCPMON_AGENT_TOKEN이 없습니다"`; 키가 64자 hex(32바이트)가 아니면 `"MCPMON_AGENT_SERVER_KEY는 32바이트 hex여야 합니다"`; `--server`가 `http://`로 시작하지 않으면 ArgError; 끝 `/` 제거.
  - `client`:
    - `TOKEN_HEADER = "X-Agent-Token"`, `NONCE_HEADER = "X-Agent-Nonce"`, `PROOF_HEADER = "X-Server-Proof"`.
    - `#[derive(Debug)] pub enum ClientError { Unavailable(String), Rejected(String), Unverified(String), Unexpected(String) }`, `is_rejected()` = Rejected 또는 Unverified.
    - `pub struct RawResponse { pub status: u16, pub proof: Option<String>, pub body: Vec<u8> }`, `pub trait Transport: Send + Sync { fn send(&self, method: &str, url: &str, headers: &[(&'static str, String)], body: Option<Vec<u8>>, timeout: Duration) -> Result<RawResponse, String>; }`.
    - `UreqTransport`: `ureq::Agent`를 `proxy(None)`(환경 변수 프록시 무시 — 토큰이 PC 밖으로 나가면 안 됨), `http_status_as_error(false)`, `max_redirects(0)`로 만들고 요청마다 `timeout_global(timeout)`. 연결 실패·시간 초과 → `Err(문구)`.
    - `proof_for(key: &[u8], nonce: &str) -> String`(HMAC-SHA256 소문자 hex), `new_nonce() -> String`(`getrandom` 16바이트 → 32자 hex).
    - `ServerClient::new(base, token, key: [u8; 32], transport: Box<dyn Transport>)`, 기본 시간 제한 10초; `verified() -> bool`; `post(path, body: Option<&Value>, verified_only: bool) -> Result<Option<Value>, ClientError>`(`verified_only`이고 검증되지 않았으면 **보내지 않고** `Unavailable`); `next(timeout_sec: f64)` = `GET /api/agent/next?timeout=<%g 형식>`(25.0→`25`, 0.5→`0.5`), 요청 시간 제한 `timeout_sec + 10`.
    - 응답 처리(Python `_request`와 같음): 전송 실패 → 검증 해제 + `Unavailable`; 401·403 → 검증 해제 + `Rejected`(증명 불필요); 5xx → 검증 해제 + `Unavailable`; 그 밖은 증명 확인(헤더 없음·ASCII 아님·hex 해독 실패·`verify_slice` 실패 → 검증 해제 + `Unverified("…: the answer does not prove the server key")`) 뒤 2xx가 아니면 `Unexpected("<METHOD> <path>: unexpected status <n>")`; 204·빈 본문 → `None`; JSON 객체가 아니면 `Unexpected("…: response is not a JSON object")`. 증명 비교는 상수 시간(`hmac::Mac::verify_slice`).
  - `runner`:
    - `EXIT_OK = 0`, `EXIT_REJECTED = 3`, `EXIT_UNREACHABLE = 4`, `EXIT_UNVERIFIED = 5`, `BACKOFF_SEC = [1.0, 2.0, 4.0, 8.0, 10.0]`, `POLL_SEC = 25.0`, `POLL_WHILE_SHOWN_SEC = 2.0`, `DEFAULT_HEARTBEAT_SEC = 5.0`.
    - `pub trait NoticeWindow: Send { fn open(&mut self, url: &str, display_id: i64) -> Result<(), String>; fn close(&mut self); fn closed_by_user(&mut self) -> bool; }`
    - `pub struct Clock { pub monotonic: Arc<dyn Fn() -> f64 + Send + Sync>, pub sleep: Arc<dyn Fn(f64) + Send + Sync> }`(`Clock::real()`), `pub type Log = Arc<dyn Fn(&str) + Send + Sync>`(`log_stderr()` = `eprintln!("mcp-monitor agent: {line}")`).
    - `AgentRunner::new(cfg: &AgentConfig, client: Arc<ServerClient>, window: Box<dyn NoticeWindow>, session_id: u32, pid: u32)` + `with_clock(Clock)`, `with_idle(Arc<dyn Fn() -> f64 + Send + Sync>)`, `with_log(Log)`, `on_hello(Box<dyn FnOnce(&Value) + Send>)`; `run(self) -> i32`.
    - 동작(Python `runner.py`와 같음): hello(`{"session_id", "pid", "version": "1.1.0"}`)를 백오프(1, 2, 4, 8, 10, 10… 초; 첫 실패부터 `unreachable_exit_sec`가 지나면 4)로 재시도, `Unexpected`도 로그 후 백오프; hello 뒤 `on_hello`, 하트비트 스레드(`heartbeat_sec`, 본문 `{"idle_sec": <정수>, "locked": null}`; `Rejected`/`Unverified`면 그 오류를 기록하고 루프에 알림; `Unavailable`은 무시); 명령 루프: 열린 고지가 있고 `closed_by_user()`면 `POST /api/agent/notice/<id>/closed`(실패하면 다음 차례에 다시), `next(열린 고지가 있으면 2초, 아니면 25초)`; `exit` → 0; `show_notice`: `url`이 문자열이고 `<server>/notice#`로 시작할 때만(아니면 로그 `refused notice url "<# 앞>#...": not under <server>/notice#` — 토큰은 절대 출력하지 않음), 열린 것이 있으면 먼저 닫고 `open`; `close_notice`: 같은 id일 때만 닫음; 명령 하나·창 열기 실패는 로그(`command "<type>" failed: …`)만 남기고 계속; `Unverified` → 로그 `…; stopping` + 5, `Rejected` → 3. 끝날 때 항상 창을 닫고 하트비트 스레드를 5초까지 기다립니다.
    - `wants_window_events(hello)`(키 없음 → true), `heartbeat_sec(hello)`(양수 아니거나 숫자 아님 → 5.0).
  - `window::PrintWindow::new(url_file)`: `open` → 파일 끝에 `OPEN <id> <url>\n`, `close` → 열려 있을 때만 `CLOSE <id>\n`, `closed_by_user` → 항상 false(UTF-8, `\n`).
  - `lib::run`의 `Agent`: `take_secrets(&mut ProcessEnv)`를 **가장 먼저**, 그다음(`dev`가 아니면) `strip_webview2_env`, `config_from`(ArgError → 2), `session_id = ProcessIdToSessionId(GetCurrentProcessId())`, `print`면 `PrintWindow`로 `AgentRunner::run`의 종료 코드.
  - `testkit`(`#[cfg(test)]`): `KEY: [u8; 32] = [0x11; 32]`, `FakeServer`(메모리 안 `Transport`: `state()`가 `MutexGuard<FakeState>`를 줌; `FakeState { requests: Vec<Req>, commands: VecDeque<Value>, status_for: HashMap<String, u16>, hello: Value, key: Option<[u8; 32]>, down: bool }`, `Req { method, path, query, body: Option<Value>, token, nonce }`; `next`은 명령이 없으면 5ms 쉬고 204; hello는 200 + `hello`(기본 `{"heartbeat_sec": 5, "events_max": 200, "idle_threshold_sec": 300, "window_events": true}`); 그 밖의 POST는 204; 강제 상태가 400 이상이면 본문 `{"error":"forced"}`; `key`가 있고 401·403이 아니면 `X-Server-Proof`), `fake.on_answer(path, f)`(그 경로의 다음 **성공(2xx)** 답 뒤에 한 번 `f(&mut FakeState)`), `client(&fake) -> Arc<ServerClient>`(base `http://127.0.0.1:8700`, 토큰 `tok`, `KEY`), `wait_until(f)`(5초, 20ms 간격).
  - `tests/common/agent_server.rs`: 실제 TCP 가짜 서버(`127.0.0.1:0`, 연결마다 스레드, 요청 하나 처리 후 `Connection: close`), `AgentServer::start(key: Option<[u8; 32]>)`, `url()`, `queue(Value)`, `requests() -> Vec<Req>`(`path`, `body: Value`), `serve_page(path, html)`(Task 11·12가 씀). 응답 규칙은 `testkit::FakeServer`와 같고 증명은 `mcp_monitor::agent::client::proof_for`로 만듭니다.

- [ ] **Step 1: 실패하는 테스트 작성**

```rust
// desktop/src/agent/config.rs (tests)
#[cfg(test)]
mod tests {
    use super::*;
    use crate::cli::{AgentArgs, Dialog};
    use std::collections::HashMap;

    fn env(pairs: &[(&str, &str)]) -> HashMap<String, String> {
        pairs.iter().map(|(k, v)| (k.to_string(), v.to_string())).collect()
    }
    fn args() -> AgentArgs {
        AgentArgs { server: "http://127.0.0.1:8700/".into(), dialog: Dialog::Webview, url_file: None, unreachable_exit_sec: 120.0 }
    }

    #[test]
    fn secrets_are_taken_out_of_the_environment() {
        let mut e = env(&[(TOKEN_ENV, "tok"), (SERVER_KEY_ENV, &"11".repeat(32)), ("PATH", "x")]);
        let (t, k) = take_secrets(&mut e);
        assert_eq!((t.as_deref(), k.as_deref()), (Some("tok"), Some("11".repeat(32).as_str())));
        assert!(!e.contains_key(TOKEN_ENV) && !e.contains_key(SERVER_KEY_ENV) && e.contains_key("PATH"));
        let cfg = config_from(&args(), t, k).unwrap();
        assert_eq!((cfg.server.as_str(), cfg.server_key), ("http://127.0.0.1:8700", [0x11; 32]));
    }

    #[test]
    fn a_missing_token_or_a_bad_key_is_an_argument_error_and_still_removed() {
        for key in [None, Some(""), Some("zz".repeat(32).leak() as &str), Some("11".repeat(16).leak() as &str)] {
            let mut e = env(&[(TOKEN_ENV, "t")]);
            if let Some(k) = key {
                e.insert(SERVER_KEY_ENV.into(), k.into());
            }
            let (t, k) = take_secrets(&mut e);
            assert!(config_from(&args(), t, k).unwrap_err().0.contains(SERVER_KEY_ENV));
            assert!(e.is_empty());
        }
        assert!(config_from(&args(), None, Some("11".repeat(32))).unwrap_err().0.contains(TOKEN_ENV));
        assert!(config_from(&args(), Some(String::new()), Some("11".repeat(32))).is_err());
        let ftp = AgentArgs { server: "ftp://127.0.0.1:8700".into(), ..args() };
        assert!(config_from(&ftp, Some("t".into()), Some("11".repeat(32))).is_err());
    }

    #[test]
    fn webview2_variables_are_removed() {
        let mut e = env(&[("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "--remote-debugging-port=9222"),
                          ("webview2_browser_executable_folder", r"C:\evil"), ("WEBVIEW2_USER_DATA_FOLDER", r"C:\x"), ("PATH", "x")]);
        let mut gone = strip_webview2_env(&mut e);
        gone.sort();
        assert_eq!(gone, ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "WEBVIEW2_USER_DATA_FOLDER", "webview2_browser_executable_folder"]);
        assert_eq!(e.keys().collect::<Vec<_>>(), ["PATH"]);
    }
}
```

```rust
// desktop/src/agent/client.rs (tests)
#[cfg(test)]
mod tests {
    use super::*;
    use crate::agent::testkit::*;
    use serde_json::json;

    #[test]
    fn proof_matches_the_python_vectors() {
        assert_eq!(proof_for(&[0x11; 32], "abc"), "8094a4aa0311ceadd62bd4b17fa76cb0066cff4f125cbfc64dea5bab2493f2cd");
        assert_eq!(proof_for(&[0x11; 32], "00112233445566778899aabbccddeeff"), "6e954b5b533f380aef1f7121d19df77241bf24c1b258dea69a65d4dbdb0b7e5f");
        let (a, b) = (new_nonce(), new_nonce());
        assert!(a.len() == 32 && a != b && a.chars().all(|c| c.is_ascii_hexdigit()));
    }

    #[test]
    fn sends_the_token_a_fresh_nonce_and_json_and_needs_the_proof() {
        let fake = FakeServer::new();
        let c = client(&fake);
        assert!(!c.verified());
        c.post("/api/agent/heartbeat", Some(&json!({"idle_sec": 1, "locked": null})), false).unwrap();
        c.post("/api/agent/heartbeat", Some(&json!({})), false).unwrap();
        let reqs = fake.state().requests.clone();
        assert_eq!((reqs[0].token.as_str(), reqs[0].body.clone()), ("tok", Some(json!({"idle_sec": 1, "locked": null}))));
        assert!(reqs[0].nonce != reqs[1].nonce && reqs[0].nonce.len() == 32 && c.verified());
    }

    #[test]
    fn refuses_an_answer_without_a_valid_proof() {
        let fake = FakeServer::new();
        let c = client(&fake);
        c.post("/api/agent/heartbeat", Some(&json!({})), false).unwrap();
        for key in [None, Some([0x22; 32])] {
            fake.state().key = key;
            assert!(matches!(c.post("/api/agent/hello", Some(&json!({})), false), Err(ClientError::Unverified(_))));
            assert!(!c.verified());
            assert!(matches!(c.next(0.0), Err(ClientError::Unverified(_))));
        }
        fake.state().status_for.insert("/api/agent/next".into(), 404);
        assert!(matches!(c.next(0.0), Err(ClientError::Unverified(_)))); // an unproven 4xx: not our service either
        assert!(ClientError::Unverified(String::new()).is_rejected());
    }

    #[test]
    fn statuses_map_like_the_python_agent() {
        let fake = FakeServer::new();
        let c = client(&fake);
        fake.state().key = None;
        fake.state().status_for.insert("/api/agent/heartbeat".into(), 401);
        assert!(matches!(c.post("/api/agent/heartbeat", Some(&json!({})), false), Err(ClientError::Rejected(_))));
        fake.state().status_for.insert("/api/agent/heartbeat".into(), 503);
        assert!(matches!(c.post("/api/agent/heartbeat", Some(&json!({})), false), Err(ClientError::Unavailable(_))));
        fake.state().key = Some(KEY);
        fake.state().status_for.insert("/api/agent/heartbeat".into(), 422);
        match c.post("/api/agent/heartbeat", Some(&json!({})), false) {
            Err(ClientError::Unexpected(m)) => assert!(m.contains("unexpected status 422"), "{m}"),
            other => panic!("{other:?}"),
        }
        fake.state().hello = json!([1, 2]);
        assert!(matches!(c.post("/api/agent/hello", Some(&json!({})), false), Err(ClientError::Unexpected(_))));
        fake.state().down = true;
        assert!(matches!(c.next(0.0), Err(ClientError::Unavailable(_))));
    }

    #[test]
    fn sensitive_posts_wait_for_a_proven_answer_after_an_outage() {
        let fake = FakeServer::new();
        let c = client(&fake);
        assert!(matches!(c.post("/api/agent/events", Some(&json!({"events": []})), true), Err(ClientError::Unavailable(_))));
        assert!(fake.state().requests.is_empty());
        c.next(0.0).unwrap();
        assert_eq!(c.post("/api/agent/events", Some(&json!({"events": []})), true).unwrap(), None);
        fake.state().status_for.insert("/api/agent/next".into(), 503);
        assert!(c.next(0.0).is_err());
        assert!(matches!(c.post("/api/agent/events", Some(&json!({"events": []})), true), Err(ClientError::Unavailable(_))));
        assert_eq!(fake.state().requests.iter().filter(|r| r.path == "/api/agent/events").count(), 1);
    }

    #[test]
    fn an_unproven_401_after_a_proven_answer_drops_the_trust() {
        let fake = FakeServer::new();
        let c = client(&fake);
        c.next(0.0).unwrap();
        assert!(c.verified());
        for status in [401, 403] {
            fake.state().key = None;
            fake.state().status_for.insert("/api/agent/heartbeat".into(), status);
            assert!(matches!(c.post("/api/agent/heartbeat", Some(&json!({})), false), Err(ClientError::Rejected(_))));
            assert!(!c.verified());
            assert!(matches!(c.post("/api/agent/events", Some(&json!({"events": []})), true), Err(ClientError::Unavailable(_))));
            fake.state().key = Some(KEY);
            c.next(0.0).unwrap();
        }
        assert!(!fake.state().requests.iter().any(|r| r.path == "/api/agent/events"));
    }

    #[test]
    fn next_sends_the_timeout_like_python() {
        let fake = FakeServer::new();
        let c = client(&fake);
        for t in [25.0, 2.0, 0.5, 0.0] {
            c.next(t).unwrap();
        }
        let q: Vec<String> = fake.state().requests.iter().map(|r| r.query.clone()).collect();
        assert_eq!(q, ["timeout=25", "timeout=2", "timeout=0.5", "timeout=0"]);
    }
}
```

```rust
// desktop/src/agent/runner.rs (tests)
#[cfg(test)]
mod tests {
    use super::*;
    use crate::agent::testkit::*;
    use crate::cli::Dialog;
    use serde_json::{json, Value};
    use std::sync::atomic::{AtomicBool, Ordering::SeqCst};
    use std::sync::{Arc, Mutex};

    const BASE: &str = "http://127.0.0.1:8700";
    fn url(d: i64) -> String {
        format!("{BASE}/notice#d={d}&t=tok_ABCDEFGHIJKLmnop")
    }
    fn show(d: i64) -> Value {
        json!({"type": "show_notice", "display_id": d, "attempt": 1, "url": url(d)})
    }

    type OnOpen = Arc<dyn Fn() + Send + Sync>;
    #[derive(Clone, Default)]
    struct Win { opened: Arc<Mutex<Vec<(i64, String)>>>, closed: Arc<Mutex<u32>>, user_closed: Arc<AtomicBool>, fail_open: bool, on_open: Option<OnOpen> }
    struct FakeWindow(Win);
    impl NoticeWindow for FakeWindow {
        fn open(&mut self, url: &str, id: i64) -> Result<(), String> {
            if self.0.fail_open {
                return Err("no window".into());
            }
            self.0.opened.lock().unwrap().push((id, url.into()));
            self.0.user_closed.store(false, SeqCst);
            if let Some(f) = &self.0.on_open {
                f();
            }
            Ok(())
        }
        fn close(&mut self) {
            *self.0.closed.lock().unwrap() += 1;
        }
        fn closed_by_user(&mut self) -> bool {
            self.0.user_closed.load(SeqCst)
        }
    }

    fn cfg(unreachable: f64) -> AgentConfig {
        AgentConfig { server: BASE.into(), token: "tok".into(), server_key: KEY, dialog: Dialog::Print, url_file: None, unreachable_exit_sec: unreachable }
    }
    fn logs() -> (Log, Arc<Mutex<Vec<String>>>) {
        let lines = Arc::new(Mutex::new(Vec::new()));
        let l = lines.clone();
        (Arc::new(move |s: &str| l.lock().unwrap().push(s.to_string())), lines)
    }
    /// A clock whose sleep advances it; `on_sleep(n)` runs after the n-th sleep.
    fn fake_clock(on_sleep: impl Fn(usize) + Send + Sync + 'static) -> (Clock, Arc<Mutex<Vec<f64>>>) {
        let now = Arc::new(Mutex::new(0.0));
        let sleeps = Arc::new(Mutex::new(Vec::new()));
        let (n, s) = (now.clone(), sleeps.clone());
        let clock = Clock {
            monotonic: Arc::new(move || *n.lock().unwrap()),
            sleep: Arc::new(move |d| {
                *now.lock().unwrap() += d;
                let count = { let mut v = s.lock().unwrap(); v.push(d); v.len() };
                on_sleep(count);
            }),
        };
        (clock, sleeps)
    }
    fn runner(fake: &Arc<FakeServer>, w: &Win, unreachable: f64) -> (AgentRunner, Arc<Mutex<Vec<String>>>) {
        let (log, lines) = logs();
        (AgentRunner::new(&cfg(unreachable), client(fake), Box::new(FakeWindow(w.clone())), 2, 4242).with_idle(Arc::new(|| 12.9)).with_log(log), lines)
    }
    fn paths(fake: &Arc<FakeServer>) -> Vec<String> {
        fake.state().requests.iter().map(|r| r.path.clone()).collect()
    }

    #[test]
    fn shows_and_closes_the_notice() {
        let fake = FakeServer::new();
        fake.state().commands.extend([show(7), json!({"type": "close_notice", "display_id": 7}), json!({"type": "exit"})]);
        let w = Win::default();
        assert_eq!(runner(&fake, &w, 120.0).0.run(), EXIT_OK);
        assert_eq!(*w.opened.lock().unwrap(), [(7, url(7))]);
        assert!(*w.closed.lock().unwrap() >= 1);
        let hello = fake.state().requests.iter().find(|r| r.path == "/api/agent/hello").unwrap().body.clone();
        assert_eq!(hello, Some(json!({"session_id": 2, "pid": 4242, "version": "1.1.0"})));
    }

    #[test]
    fn reports_a_window_the_user_closed() {
        let fake = FakeServer::new();
        fake.state().commands.push_back(show(7));
        let w = Win::default();
        let r = runner(&fake, &w, 120.0).0;
        let t = std::thread::spawn(move || r.run());
        wait_until(|| w.opened.lock().unwrap().len() == 1);
        w.user_closed.store(true, SeqCst);
        wait_until(|| paths(&fake).contains(&"/api/agent/notice/7/closed".to_string()));
        fake.state().commands.push_back(json!({"type": "exit"}));
        assert_eq!(t.join().unwrap(), EXIT_OK);
    }

    #[test]
    fn sends_heartbeats_with_idle() {
        let fake = FakeServer::new();
        fake.state().hello = json!({"heartbeat_sec": 0.05, "events_max": 200, "idle_threshold_sec": 300});
        let r = runner(&fake, &Win::default(), 120.0).0;
        let t = std::thread::spawn(move || r.run());
        wait_until(|| paths(&fake).iter().filter(|p| *p == "/api/agent/heartbeat").count() >= 2);
        fake.state().commands.push_back(json!({"type": "exit"}));
        assert_eq!(t.join().unwrap(), EXIT_OK);
        let hb = fake.state().requests.iter().find(|r| r.path == "/api/agent/heartbeat").unwrap().body.clone();
        assert_eq!(hb, Some(json!({"idle_sec": 12, "locked": null})));
    }

    #[test]
    fn exits_3_when_rejected() {
        let fake = FakeServer::new();
        fake.state().status_for.insert("/api/agent/hello".into(), 401);
        assert_eq!(runner(&fake, &Win::default(), 120.0).0.run(), EXIT_REJECTED);
    }

    #[test]
    fn unreachable_backoff_is_1_2_4_8_then_10_and_exits_4() {
        let fake = FakeServer::new();
        fake.state().down = true;
        let (clock, sleeps) = fake_clock(|_| {});
        assert_eq!(runner(&fake, &Win::default(), 30.0).0.with_clock(clock).run(), EXIT_UNREACHABLE);
        assert_eq!(*sleeps.lock().unwrap(), [1.0, 2.0, 4.0, 8.0, 10.0, 10.0]);
    }

    #[test]
    fn hello_retries_until_the_server_answers() {
        let fake = FakeServer::new();
        fake.state().status_for.insert("/api/agent/hello".into(), 503);
        fake.state().commands.push_back(json!({"type": "exit"}));
        let f2 = fake.clone();
        let (clock, sleeps) = fake_clock(move |n| if n == 2 { f2.state().status_for.remove("/api/agent/hello"); });
        let hellos = Arc::new(Mutex::new(Vec::new()));
        let h = hellos.clone();
        let r = runner(&fake, &Win::default(), 120.0).0.with_clock(clock).on_hello(Box::new(move |v: &Value| h.lock().unwrap().push(v.clone())));
        assert_eq!(r.run(), EXIT_OK);
        assert_eq!(*sleeps.lock().unwrap(), [1.0, 2.0]);
        assert_eq!(hellos.lock().unwrap().len(), 1);
        assert_eq!(paths(&fake).iter().filter(|p| *p == "/api/agent/hello").count(), 3);
    }

    #[test]
    fn window_events_flag_defaults_to_on() {
        assert!(wants_window_events(&json!({"heartbeat_sec": 5})) && wants_window_events(&json!({"window_events": true})));
        assert!(!wants_window_events(&json!({"window_events": false})));
        assert_eq!((heartbeat_sec(&json!({"heartbeat_sec": 0})), heartbeat_sec(&json!({"heartbeat_sec": "x"})), heartbeat_sec(&json!({"heartbeat_sec": 0.5}))), (5.0, 5.0, 0.5));
    }

    #[test]
    fn a_new_notice_replaces_the_open_one_and_exit_closes_it() {
        let fake = FakeServer::new();
        fake.state().commands.extend([show(7), show(8), json!({"type": "exit"})]);
        let w = Win::default();
        assert_eq!(runner(&fake, &w, 120.0).0.run(), EXIT_OK);
        assert_eq!(w.opened.lock().unwrap().iter().map(|x| x.0).collect::<Vec<_>>(), [7, 8]);
        assert!(*w.closed.lock().unwrap() >= 2);
    }

    #[test]
    fn a_rejected_heartbeat_stops_the_loop_with_3() {
        let fake = FakeServer::new();
        fake.state().hello = json!({"heartbeat_sec": 0.05});
        let r = runner(&fake, &Win::default(), 120.0).0;
        let t = std::thread::spawn(move || r.run());
        wait_until(|| paths(&fake).contains(&"/api/agent/heartbeat".to_string()));
        fake.state().status_for.insert("/api/agent/heartbeat".into(), 401);
        assert_eq!(t.join().unwrap(), EXIT_REJECTED);
    }

    #[test]
    fn a_closed_report_lost_to_an_outage_is_sent_again() {
        let fake = FakeServer::new();
        fake.state().commands.push_back(show(7));
        fake.state().status_for.insert("/api/agent/notice/7/closed".into(), 503);
        let f2 = fake.clone();
        let (clock, _) = fake_clock(move |n| if n == 1 { f2.state().status_for.remove("/api/agent/notice/7/closed"); });
        fake.on_answer("/api/agent/notice/7/closed", |s| s.commands.push_back(json!({"type": "exit"})));
        let w = Win { on_open: None, ..Win::default() };
        let r = runner(&fake, &w, 120.0).0.with_clock(clock);
        let w2 = w.clone();
        let t = std::thread::spawn(move || r.run());
        wait_until(|| w2.opened.lock().unwrap().len() == 1);
        w.user_closed.store(true, SeqCst);
        assert_eq!(t.join().unwrap(), EXIT_OK);
        assert_eq!(paths(&fake).iter().filter(|p| *p == "/api/agent/notice/7/closed").count(), 2);
    }

    #[test]
    fn an_unexpected_answer_or_command_is_logged_and_the_agent_keeps_running() {
        let fake = FakeServer::new();
        fake.state().status_for.insert("/api/agent/next".into(), 422);
        let f2 = fake.clone();
        let (clock, _) = fake_clock(move |n| if n == 1 { f2.state().status_for.remove("/api/agent/next"); });
        fake.state().commands.extend([json!({"type": "show_notice", "display_id": "x", "url": url(7)}), json!({"type": "exit"})]);
        let w = Win::default();
        let (r, lines) = runner(&fake, &w, 120.0);
        assert_eq!(r.with_clock(clock).run(), EXIT_OK);
        let all = lines.lock().unwrap().join("\n");
        assert!(all.contains("unexpected status 422") && all.contains(r#"command "show_notice" failed"#), "{all}");
        assert!(w.opened.lock().unwrap().is_empty());
    }

    #[test]
    fn a_failing_window_open_does_not_end_the_agent() {
        let fake = FakeServer::new();
        fake.state().commands.extend([show(7), json!({"type": "exit"})]);
        let w = Win { fail_open: true, ..Win::default() };
        let (r, lines) = runner(&fake, &w, 120.0);
        assert_eq!(r.run(), EXIT_OK);
        assert!(lines.lock().unwrap().iter().any(|l| l.contains("no window")));
    }

    #[test]
    fn a_server_without_the_key_is_dropped_at_once_and_nothing_is_opened() {
        let fake = FakeServer::new();
        fake.state().key = Some([0x22; 32]);
        fake.state().commands.push_back(show(7));
        let (clock, sleeps) = fake_clock(|_| {});
        let w = Win::default();
        assert_eq!(runner(&fake, &w, 120.0).0.with_clock(clock).run(), EXIT_UNVERIFIED);
        assert!(w.opened.lock().unwrap().is_empty() && sleeps.lock().unwrap().is_empty());
        assert_eq!(paths(&fake), ["/api/agent/hello"]);
    }

    #[test]
    fn a_rogue_that_takes_over_mid_run_gets_no_window_opened() {
        let fake = FakeServer::new();
        fake.state().commands.push_back(show(7));
        let f2 = fake.clone();
        let w = Win { on_open: Some(Arc::new(move || {
            let mut s = f2.state();
            s.key = None; // the service is gone; something else answers now
            s.commands.push_back(json!({"type": "show_notice", "display_id": 8, "attempt": 1, "url": "https://evil.example/x"}));
        })), ..Win::default() };
        assert_eq!(runner(&fake, &w, 120.0).0.run(), EXIT_UNVERIFIED);
        assert_eq!(*w.opened.lock().unwrap(), [(7, url(7))]);
        assert!(*w.closed.lock().unwrap() >= 1);
    }

    #[test]
    fn a_rejected_heartbeat_from_an_unproven_server_exits_5() {
        let fake = FakeServer::new();
        fake.state().hello = json!({"heartbeat_sec": 0.05});
        let r = runner(&fake, &Win::default(), 120.0).0;
        let t = std::thread::spawn(move || r.run());
        wait_until(|| paths(&fake).contains(&"/api/agent/heartbeat".to_string()));
        fake.state().key = None;
        assert_eq!(t.join().unwrap(), EXIT_UNVERIFIED);
    }

    #[test]
    fn only_notice_urls_of_the_configured_server_are_opened() {
        let fake = FakeServer::new();
        let bad = [json!("https://evil.example/notice#d=7&t=x"), json!("http://127.0.0.1:1/notice#d=7&t=x"), json!(format!("{BASE}/admin#x")),
                   json!(format!("{BASE}/notice?d=7")), json!(format!("{BASE}@evil.example/notice#d=7")), json!(format!("{BASE}.evil/notice#d=7")), json!(7)];
        for u in &bad {
            fake.state().commands.push_back(json!({"type": "show_notice", "display_id": 7, "attempt": 1, "url": u}));
        }
        fake.state().commands.extend([show(7), json!({"type": "exit"})]);
        let w = Win::default();
        let (r, lines) = runner(&fake, &w, 120.0);
        assert_eq!(r.run(), EXIT_OK);
        assert_eq!(*w.opened.lock().unwrap(), [(7, url(7))]);
        let all = lines.lock().unwrap().join("\n");
        assert_eq!(all.matches("refused notice url").count(), bad.len());
        assert!(!all.contains("t=x") && all.contains("#..."), "{all}");
    }
}
```

```rust
// desktop/tests/agent_print.rs
mod common;
use common::{agent_server::AgentServer, exe, Scratch};
use serde_json::json;
use std::time::Instant;

fn agent(srv: &AgentServer, url_file: &std::path::Path, key: Option<&str>) -> std::process::Command {
    let mut c = exe();
    c.args(["agent", "--server", &srv.url(), "--dialog", "print", "--url-file"]).arg(url_file).env("MCPMON_AGENT_TOKEN", "tok");
    if let Some(k) = key {
        c.env("MCPMON_AGENT_SERVER_KEY", k);
    }
    c
}

#[test]
fn the_print_agent_shows_closes_and_exits_ignoring_proxy_settings() {
    let srv = AgentServer::start(Some([0x11; 32]));
    let s = Scratch::new();
    let url_file = s.join("agent.url");
    let notice = format!("{}/notice#d=7&t=tok_ABCDEFGHIJKLmnop", srv.url());
    srv.queue(json!({"type": "show_notice", "display_id": 7, "attempt": 1, "url": notice}));
    srv.queue(json!({"type": "close_notice", "display_id": 7}));
    srv.queue(json!({"type": "exit"}));
    let child = agent(&srv, &url_file, Some(&"11".repeat(32)))
        .env("HTTP_PROXY", "http://127.0.0.1:9").env("http_proxy", "http://127.0.0.1:9").env("ALL_PROXY", "http://127.0.0.1:9")
        .stdout(std::process::Stdio::piped()).stderr(std::process::Stdio::piped()).spawn().unwrap();
    let pid = child.id();
    let out = child.wait_with_output().unwrap();
    assert_eq!(out.status.code(), Some(0), "{}", String::from_utf8_lossy(&out.stderr));
    let lines: Vec<String> = std::fs::read_to_string(&url_file).unwrap().lines().map(String::from).collect();
    assert_eq!(lines, [format!("OPEN 7 {notice}"), "CLOSE 7".to_string()]);
    let hello = srv.requests().into_iter().find(|r| r.path == "/api/agent/hello").unwrap();
    assert_eq!((hello.body["pid"].as_u64(), hello.body["version"].as_str()), (Some(pid as u64), Some("1.1.0")));
}

#[test]
fn a_rogue_server_is_left_within_seconds_with_exit_5() {
    let srv = AgentServer::start(Some([0x33; 32]));
    let s = Scratch::new();
    let url_file = s.join("agent.url");
    srv.queue(json!({"type": "show_notice", "display_id": 7, "attempt": 1, "url": format!("{}/notice#d=7&t=x", srv.url())}));
    let started = Instant::now();
    let out = agent(&srv, &url_file, Some(&"11".repeat(32))).output().unwrap();
    assert_eq!(out.status.code(), Some(5));
    assert!(started.elapsed().as_secs() < 15 && !url_file.exists());
    assert!(String::from_utf8_lossy(&out.stderr).contains("does not prove the server key"));
}

#[test]
fn an_agent_without_the_server_key_exits_2() {
    let srv = AgentServer::start(Some([0x11; 32]));
    let s = Scratch::new();
    let out = agent(&srv, &s.join("agent.url"), None).output().unwrap();
    assert_eq!(out.status.code(), Some(2));
    assert!(srv.requests().is_empty());
}
```

- [ ] **Step 2: 실패 확인** — Run: `cargo test --locked agent` → FAIL

- [ ] **Step 3: 구현** — 위 Interfaces대로. 하트비트 스레드와 명령 루프 사이의 거절 전달은 `Arc<Mutex<Option<ClientError>>>` + `AtomicBool`(Python의 `_rejection`·`_rejected`). Python 에이전트의 `agent/tests`는 그대로 둡니다(개발 에이전트, Y7).

- [ ] **Step 4: 통과 확인** — Rust 검사 3종 → 통과. Run(agent): `uv run python -m pytest -q` → 통과(변경 없음 확인).

- [ ] **Step 5: Commit** — `git commit -m "feat(desktop): Rust session agent core (per-launch token and key, nonce + HMAC server proof, exit 3/4/5, print window)"`

---

### Task 10: 에이전트 창 이벤트·유휴 — 훅, 합치기, 보내기, 가림

**Files:**
- Create: `desktop/src/agent/time.rs`, `desktop/src/agent/redact.rs`, `desktop/src/agent/coalesce.rs`, `desktop/src/agent/idle.rs`, `desktop/src/agent/sender.rs`, `desktop/src/agent/pump.rs`, `desktop/src/agent/hooks.rs`, `desktop/src/agent/activity.rs`
- Modify: `desktop/src/agent/mod.rs`, `desktop/src/lib.rs`(`on_hello`로 `WindowActivity` 연결, 끝날 때 `stop`)

**Interfaces:**
- Produces(Python `coalesce.py`·`idle.py`·`sender.py`·`pump.py`·`hooks.py`·`__main__.WindowActivity`와 같은 숫자):
  - `time::kst_iso(at_ms: i64) -> String`(예: `1793768397000` → `"2026-11-04T13:59:57.000+09:00"`), `time::now_ms() -> i64`.
  - `redact::redact_notice_tokens(text: &str) -> String`: 서버 `app.activity.redact`와 같은 식 `(/notice#(?:[^\s"'#&]*&)*t=)[^\s"'&#]+` → `$1<redacted>`(`regex`, 한 번만 컴파일).
  - `coalesce`: `#[derive(Clone, Copy, PartialEq, Debug)] pub enum Kind { Foreground, Minimize, Restore, Title }`(`as_str`), `#[derive(Clone, Debug, PartialEq)] pub struct RawWinEvent { pub t: f64, pub kind: Kind, pub hwnd: isize, pub pid: u32, pub exe: Option<String>, pub title: String, pub at_ms: i64 }`, `WindowEventCoalescer::new()`(fg 0.3, title 1.0, dup 0.3, 제목 기억 256) / `with(fg, title, dup)`, `add(e)`, `drain(now) -> Vec<RawWinEvent>` — 규칙은 Python과 같음.
  - `idle::IdleTracker::new(threshold_sec: f64)`, `update(idle_sec: f64, at_ms: i64) -> Option<Value>`(`{"type": "idle"|"active", "at", "idle_sec": <정수>}`).
  - `sender`: `TITLE_MAX = 512`, `EXE_MAX = 260`, `EVENTS_PATH = "/api/agent/events"`; `pub enum Item { Win(RawWinEvent), Idle(Value) }`; `to_event(&RawWinEvent) -> Value`(`type`, `at`, `pid`, `exe`(문자 단위 260자 자름 또는 null), `title`(`redact_notice_tokens` 뒤 문자 단위 512자)), `to_payload(items: &[Item], dropped: u64) -> Value`(`dropped`가 0이면 키 없음); `pub trait Poster: Send + Sync { fn post(&self, path: &str, body: Option<&Value>, verified_only: bool) -> Result<Option<Value>, ClientError>; }`(`ServerClient`가 구현); `EventSender::new(poster: Arc<dyn Poster>, events_max: usize, buffer_max: usize)`(기본 2000), `add(Item)`, `flush() -> Result<(), ClientError>`(`Rejected`/`Unverified`만 위로; `Unavailable` → 남기고 멈춤; `Unexpected` → 그 묶음을 버리고 `dropped += len`, 로그 `dropped <n> events: …`), `pending()`, `dropped()`. 창 이벤트는 항상 `verified_only = true`.
  - `pump`: `STEP_SEC = 0.25`, `FLUSH_SEC = 1.0`; `EventPump::new(coalescer, sender: Arc<Mutex<EventSender>>, idle: IdleTracker, idle_seconds: Arc<dyn Fn() -> Option<f64> + Send + Sync>, idle_every_sec: f64)`; `on_raw(e)`(훅 스레드: 잠금 + push만), `step(mono, wall_ms)`, `run(stop: Arc<AtomicBool>)`(Rejected면 끝, 그 밖의 오류는 로그 후 계속).
  - `hooks`: 상수 `EVENT_SYSTEM_FOREGROUND 0x0003`, `EVENT_SYSTEM_MINIMIZESTART 0x0016`, `EVENT_SYSTEM_MINIMIZEEND 0x0017`, `EVENT_OBJECT_NAMECHANGE 0x800C`, `WINEVENT_OUTOFCONTEXT 0`, `WINEVENT_SKIPOWNPROCESS 2`, `OBJID_WINDOW 0`, `CHILDID_SELF 0`, `IMAGE_CACHE_SEC 30.0`, `IMAGE_CACHE_MAX 512`; `pub trait WinApi: Send + Sync { fn foreground(&self) -> isize; fn text(&self, hwnd: isize) -> String; fn pid_of(&self, hwnd: isize) -> u32; fn image(&self, pid: u32) -> Option<String>; fn monotonic(&self) -> f64; fn now_ms(&self) -> i64; }`, `RealWin`(`GetForegroundWindow`, `GetWindowTextW` → `utf16_lossy_q`, `GetWindowThreadProcessId`, `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)` + `QueryFullProcessImageNameW`); `pub fn utf16_lossy_q(units: &[u16]) -> String`(홀로 있는 서로게이트는 `?` — Python `encode("utf-8", "replace")`와 같음); `HookHandler::new(on_event, win)` + `handle(event, hwnd, id_object, id_child)`(Python `handle`과 같은 규칙, 오류는 `errors += 1`로 삼킴, 패닉도 `catch_unwind`); `HookThread::start(handler) -> HookThread`(전용 스레드: `PeekMessageW(PM_NOREMOVE)`로 큐 생성 → `SetWinEventHook` 세 범위(OUTOFCONTEXT|SKIPOWNPROCESS) → `GetMessageW` 루프), `hook_count()`, `wait_ready(timeout)`, `stop()`(`PostThreadMessageW(WM_QUIT)` + join 2초; 시작 전·두 번 호출해도 안전).
  - `activity::WindowActivity::new(client: Arc<ServerClient>)` + `on_hello(&Value)`(window_events가 false면 아무것도 안 함; `events_max`·`idle_threshold_sec`(양수 아니면 200·300)로 sender·idle을 만들고 훅·펌프 시작), `stop()`(훅 → 펌프 → 남은 것 한 번 flush; 실패는 로그만), 테스트용 `with_hooks(factory)`·`with_idle_source(f)`.

- [ ] **Step 1: 실패하는 테스트 작성**

```rust
// desktop/src/agent/coalesce.rs (tests) — the Python test_events.py cases, same numbers
#[cfg(test)]
mod tests {
    use super::*;

    const AT: i64 = 1_793_768_397_000; // 2026-11-04T04:59:57Z = 13:59:57 KST

    fn raw(t: f64, kind: Kind, hwnd: isize, title: &str) -> RawWinEvent {
        RawWinEvent { t, kind, hwnd, pid: 10, exe: Some("a.exe".into()), title: title.into(), at_ms: AT + (t * 1000.0) as i64 }
    }
    fn fg(t: f64, hwnd: isize, title: &str) -> RawWinEvent {
        raw(t, Kind::Foreground, hwnd, title)
    }
    fn titles(v: &[RawWinEvent]) -> Vec<&str> {
        v.iter().map(|e| e.title.as_str()).collect()
    }

    #[test]
    fn foreground_burst_keeps_the_last() {
        let mut c = WindowEventCoalescer::new();
        c.add(fg(0.0, 1, "A"));
        c.add(fg(0.1, 2, "B"));
        c.add(fg(0.2, 3, "C"));
        assert!(c.drain(0.4).is_empty());
        assert_eq!(titles(&c.drain(0.5)), ["C"]);
    }

    #[test]
    fn refocusing_the_same_window_and_title_is_dropped() {
        let mut c = WindowEventCoalescer::new();
        c.add(fg(0.0, 1, "A"));
        assert_eq!(c.drain(1.0).len(), 1);
        c.add(fg(2.0, 1, "A"));
        assert!(c.drain(3.0).is_empty());
        c.add(fg(4.0, 1, "A2"));
        assert_eq!(titles(&c.drain(5.0)), ["A2"]);
    }

    #[test]
    fn title_changes_merge_for_the_foreground_window_only() {
        let mut c = WindowEventCoalescer::new();
        c.add(fg(0.0, 1, "doc"));
        c.drain(1.0);
        for (i, t) in ["doc*", "doc**", "doc***"].iter().enumerate() {
            c.add(raw(1.0 + i as f64 * 0.2, Kind::Title, 1, t));
        }
        c.add(raw(1.1, Kind::Title, 9, "background"));
        assert!(c.drain(2.3).is_empty());
        let out = c.drain(2.4);
        assert_eq!(out.iter().map(|e| (e.kind, e.title.as_str())).collect::<Vec<_>>(), [(Kind::Title, "doc***")]);
    }

    #[test]
    fn minimize_restore_pass_through_with_dedupe_and_order() {
        let mut c = WindowEventCoalescer::new();
        c.add(fg(0.0, 1, "A"));
        c.add(raw(0.5, Kind::Minimize, 1, "A"));
        c.add(raw(0.6, Kind::Minimize, 1, "A"));
        c.add(raw(0.9, Kind::Restore, 1, "A"));
        assert_eq!(c.drain(1.0).iter().map(|e| e.kind).collect::<Vec<_>>(), [Kind::Foreground, Kind::Minimize, Kind::Restore]);
    }

    #[test]
    fn foreground_switches_further_apart_than_the_merge_window_are_all_kept() {
        let mut c = WindowEventCoalescer::new();
        c.add(fg(0.0, 1, "A"));
        c.add(fg(0.5, 2, "B"));
        assert_eq!(titles(&c.drain(0.6)), ["A"]);
        assert_eq!(titles(&c.drain(0.8)), ["B"]);
    }

    #[test]
    fn a_title_equal_to_the_last_one_sent_for_that_window_is_dropped() {
        let mut c = WindowEventCoalescer::new();
        c.add(fg(0.0, 1, "doc"));
        c.drain(1.0);
        c.add(raw(2.0, Kind::Title, 1, "doc"));
        assert!(c.drain(4.0).is_empty());
        c.add(raw(5.0, Kind::Title, 1, "doc*"));
        c.add(raw(5.5, Kind::Title, 1, "doc"));
        assert!(c.drain(7.0).is_empty());
    }

    #[test]
    fn title_of_a_window_that_lost_the_foreground_is_dropped() {
        let mut c = WindowEventCoalescer::new();
        c.add(fg(0.0, 1, "one"));
        c.add(fg(1.0, 2, "two"));
        c.add(raw(1.1, Kind::Title, 1, "one*"));
        assert_eq!(c.drain(5.0).iter().map(|e| (e.kind, e.title.as_str())).collect::<Vec<_>>(), [(Kind::Foreground, "one"), (Kind::Foreground, "two")]);
    }

    #[test]
    fn minimize_dedupe_is_per_window_and_expires() {
        let mut c = WindowEventCoalescer::new();
        c.add(raw(0.0, Kind::Minimize, 1, ""));
        c.add(raw(0.1, Kind::Minimize, 2, ""));
        c.add(raw(0.2, Kind::Restore, 1, ""));
        c.add(raw(0.4, Kind::Minimize, 1, ""));
        assert_eq!(c.drain(0.4).iter().map(|e| (e.kind, e.hwnd)).collect::<Vec<_>>(),
                   [(Kind::Minimize, 1), (Kind::Minimize, 2), (Kind::Restore, 1), (Kind::Minimize, 1)]);
    }
}
```

```rust
// desktop/src/agent/sender.rs (tests)
#[cfg(test)]
mod tests {
    use super::*;
    use crate::agent::coalesce::{Kind, RawWinEvent};
    use crate::agent::idle::IdleTracker;
    use crate::agent::time::kst_iso;
    use serde_json::{json, Value};
    use std::sync::{Arc, Mutex};

    const AT: i64 = 1_793_768_397_000;

    struct Counting { outcomes: Mutex<Vec<Option<ClientError>>>, bodies: Mutex<Vec<Value>>, verified_only: Mutex<Vec<bool>> }
    impl Counting {
        fn new(outcomes: Vec<Option<ClientError>>) -> Arc<Counting> {
            Arc::new(Counting { outcomes: Mutex::new(outcomes), bodies: Mutex::new(vec![]), verified_only: Mutex::new(vec![]) })
        }
        fn bodies(&self) -> Vec<Value> {
            self.bodies.lock().unwrap().clone()
        }
    }
    impl Poster for Counting {
        fn post(&self, _path: &str, body: Option<&Value>, verified_only: bool) -> Result<Option<Value>, ClientError> {
            self.bodies.lock().unwrap().push(body.cloned().unwrap());
            self.verified_only.lock().unwrap().push(verified_only);
            let mut o = self.outcomes.lock().unwrap();
            match if o.is_empty() { None } else { o.remove(0) } {
                Some(e) => Err(e),
                None => Ok(None),
            }
        }
    }
    fn idle(n: u64) -> Item {
        Item::Idle(json!({"type": "idle", "at": "2026-11-04T14:00:00.000+09:00", "idle_sec": n}))
    }
    fn down() -> Option<ClientError> {
        Some(ClientError::Unavailable("down".into()))
    }
    fn refused() -> Option<ClientError> {
        Some(ClientError::Unexpected("POST /api/agent/events: unexpected status 422".into()))
    }

    #[test]
    fn payload_matches_the_server_fixture() {
        let fixture: Value = serde_json::from_str(&std::fs::read_to_string(concat!(env!("CARGO_MANIFEST_DIR"), "/../server/tests/fixtures/agent-events.json")).unwrap()).unwrap();
        let exe = Some(r"C:\Windows\System32\notepad.exe".to_string());
        let ev = |t: f64, kind, title: &str| Item::Win(RawWinEvent { t, kind, hwnd: 1, pid: 4321, exe: exe.clone(), title: title.into(), at_ms: AT + (t * 1000.0) as i64 });
        let items = [ev(0.0, Kind::Foreground, "메모 - 메모장"), ev(1.5, Kind::Title, "*메모 - 메모장"), ev(2.0, Kind::Minimize, "*메모 - 메모장"),
                     Item::Idle(json!({"type": "idle", "at": "2026-11-04T14:00:00.000+09:00", "idle_sec": 300}))];
        assert_eq!(to_payload(&items, 0), fixture);
    }

    #[test]
    fn to_event_fits_the_server_limits_and_redacts_notice_tokens() {
        let e = RawWinEvent { t: 0.0, kind: Kind::Title, hwnd: 1, pid: 7, exe: Some("x".repeat(300)), title: format!("a?b{}", "t".repeat(600)), at_ms: AT };
        let v = to_event(&e);
        assert_eq!((v["type"].as_str(), v["pid"].as_u64(), v["at"].as_str()), (Some("title"), Some(7), Some("2026-11-04T13:59:57.000+09:00")));
        assert_eq!((v["title"].as_str().unwrap().chars().count(), v["exe"].as_str().unwrap().chars().count()), (512, 260));
        let n = RawWinEvent { title: "MCP Monitor — http://127.0.0.1:8700/notice#d=3&t=Xy-9_aBcDeF".into(), exe: None, ..e };
        let v = to_event(&n);
        assert_eq!(v["title"], "MCP Monitor — http://127.0.0.1:8700/notice#d=3&t=<redacted>");
        assert!(v["exe"].is_null());
        assert_eq!(kst_iso(1_793_804_400_123), "2026-11-05T00:00:00.123+09:00");
    }

    #[test]
    fn idle_transitions_report_ints_in_kst() {
        let mut i = IdleTracker::new(300.0);
        assert!(i.update(10.0, AT).is_none() && i.update(299.0, AT).is_none());
        assert_eq!(i.update(300.9, AT), Some(json!({"type": "idle", "at": "2026-11-04T13:59:57.000+09:00", "idle_sec": 300})));
        assert!(i.update(420.0, AT).is_none());
        assert_eq!(i.update(2.0, AT), Some(json!({"type": "active", "at": "2026-11-04T13:59:57.000+09:00", "idle_sec": 420})));
        assert!(i.update(5.0, AT).is_none());
    }

    #[test]
    fn sender_batches_and_buffers_while_unavailable() {
        let c = Counting::new(vec![down()]);
        let mut s = EventSender::new(c.clone(), 2, 3);
        for n in 0..4 {
            s.add(idle(n));
        }
        s.flush().unwrap();
        assert_eq!((s.pending(), s.dropped()), (3, 1));
        s.flush().unwrap();
        let sent: Vec<Vec<u64>> = c.bodies()[1..].iter().map(|b| b["events"].as_array().unwrap().iter().map(|e| e["idle_sec"].as_u64().unwrap()).collect()).collect();
        assert_eq!(sent, [vec![1, 2], vec![3]]);
        assert_eq!(s.pending(), 0);
        assert!(c.verified_only.lock().unwrap().iter().all(|v| *v)); // window titles only to a proven server
    }

    #[test]
    fn overflow_drops_ride_on_the_next_batch_once() {
        let c = Counting::new(vec![]);
        let mut s = EventSender::new(c.clone(), 2, 2);
        for n in 0..5 {
            s.add(idle(n));
        }
        s.flush().unwrap();
        assert_eq!(c.bodies().iter().map(|b| b.get("dropped").and_then(Value::as_u64)).collect::<Vec<_>>(), [Some(3)]);
        s.add(idle(9));
        s.flush().unwrap();
        assert!(c.bodies()[1].get("dropped").is_none());
    }

    #[test]
    fn a_refused_batch_is_counted_in_the_next_report_and_a_lone_count_is_sent_once() {
        let c = Counting::new(vec![refused()]);
        let mut s = EventSender::new(c.clone(), 5, 2000);
        s.add(idle(0));
        s.flush().unwrap();
        assert_eq!(c.bodies(), [json!({"events": [{"type": "idle", "at": "2026-11-04T14:00:00.000+09:00", "idle_sec": 0}]}), json!({"events": [], "dropped": 1})]);
        s.flush().unwrap();
        assert_eq!(c.bodies().len(), 2);
    }

    #[test]
    fn an_empty_report_waits_while_the_server_is_unavailable() {
        let c = Counting::new(vec![refused(), down()]);
        let mut s = EventSender::new(c.clone(), 5, 2000);
        s.add(idle(0));
        s.flush().unwrap();
        s.flush().unwrap();
        assert_eq!(c.bodies().len(), 3);
        assert_eq!(c.bodies()[2], json!({"events": [], "dropped": 1}));
        s.flush().unwrap();
        assert_eq!(c.bodies().len(), 3);
    }

    #[test]
    fn a_rejected_token_goes_up_and_the_events_stay() {
        let c = Counting::new(vec![Some(ClientError::Rejected("401".into()))]);
        let mut s = EventSender::new(c, 5, 2000);
        s.add(idle(0));
        assert!(s.flush().unwrap_err().is_rejected());
        assert_eq!(s.pending(), 1);
    }
}
```

```rust
// desktop/src/agent/hooks.rs (tests)
#[cfg(test)]
mod tests {
    use super::*;
    use crate::agent::coalesce::Kind;
    use std::sync::{atomic::{AtomicU32, Ordering::SeqCst}, Arc, Mutex};

    struct FakeWin { fg: Mutex<isize>, images: AtomicU32, fail: bool }
    impl WinApi for FakeWin {
        fn foreground(&self) -> isize { *self.fg.lock().unwrap() }
        fn text(&self, hwnd: isize) -> String { if self.fail { panic!("boom") } format!("w{hwnd}") }
        fn pid_of(&self, hwnd: isize) -> u32 { hwnd as u32 + 100 }
        fn image(&self, pid: u32) -> Option<String> { self.images.fetch_add(1, SeqCst); Some(format!(r"C:\p{pid}.exe")) }
        fn monotonic(&self) -> f64 { 1.0 }
        fn now_ms(&self) -> i64 { 1_793_768_397_000 }
    }
    fn handler(fg: isize, fail: bool) -> (HookHandler, Arc<Mutex<Vec<RawWinEvent>>>, Arc<FakeWin>) {
        let got = Arc::new(Mutex::new(Vec::new()));
        let g = got.clone();
        let win = Arc::new(FakeWin { fg: Mutex::new(fg), images: AtomicU32::new(0), fail });
        (HookHandler::new(Arc::new(move |e| g.lock().unwrap().push(e)), win.clone()), got, win)
    }

    #[test]
    fn foreground_and_minimize_events_become_raw_events() {
        let (mut h, got, _) = handler(5, false);
        h.handle(EVENT_SYSTEM_FOREGROUND, 5, 0, 0);
        h.handle(EVENT_SYSTEM_MINIMIZESTART, 5, 0, 0);
        h.handle(EVENT_SYSTEM_MINIMIZEEND, 5, 0, 0);
        h.handle(0x1234, 5, 0, 0);
        h.handle(EVENT_SYSTEM_FOREGROUND, 0, 0, 0);
        let g = got.lock().unwrap();
        assert_eq!(g.iter().map(|e| e.kind).collect::<Vec<_>>(), [Kind::Foreground, Kind::Minimize, Kind::Restore]);
        assert_eq!((g[0].pid, g[0].exe.as_deref(), g[0].title.as_str()), (105, Some(r"C:\p105.exe"), "w5"));
    }

    #[test]
    fn name_changes_count_only_for_the_foreground_window_itself() {
        let (mut h, got, _) = handler(5, false);
        h.handle(EVENT_OBJECT_NAMECHANGE, 5, 0, 0);
        h.handle(EVENT_OBJECT_NAMECHANGE, 6, 0, 0);
        h.handle(EVENT_OBJECT_NAMECHANGE, 5, -4, 0);
        h.handle(EVENT_OBJECT_NAMECHANGE, 5, 0, 3);
        assert_eq!(got.lock().unwrap().len(), 1);
    }

    #[test]
    fn without_a_foreground_window_the_last_foreground_event_counts() {
        let (mut h, got, _) = handler(0, false);
        h.handle(EVENT_SYSTEM_FOREGROUND, 7, 0, 0);
        h.handle(EVENT_OBJECT_NAMECHANGE, 7, 0, 0);
        assert_eq!(got.lock().unwrap().iter().map(|e| e.kind).collect::<Vec<_>>(), [Kind::Foreground, Kind::Title]);
    }

    #[test]
    fn process_image_is_cached_per_pid() {
        let (mut h, _, win) = handler(5, false);
        for _ in 0..3 {
            h.handle(EVENT_SYSTEM_FOREGROUND, 5, 0, 0);
        }
        assert_eq!(win.images.load(SeqCst), 1);
    }

    #[test]
    fn the_callback_never_lets_a_failure_escape() {
        let (mut h, got, _) = handler(5, true);
        h.handle(EVENT_SYSTEM_FOREGROUND, 5, 0, 0);
        assert!(got.lock().unwrap().is_empty());
        assert_eq!(h.errors(), 1);
    }

    #[test]
    fn lone_surrogates_become_question_marks() {
        let units: Vec<u16> = vec![0x61, 0xD800, 0x62, 0xD55C];
        assert_eq!(utf16_lossy_q(&units), "a?b한");
    }

    #[test]
    fn the_hook_thread_installs_three_hooks_and_stops() {
        let (h, _, _) = handler(0, false);
        let t = HookThread::start(h);
        assert!(t.wait_ready(std::time::Duration::from_secs(5)));
        assert_eq!(t.hook_count(), 3);
        t.stop();
        HookThread::not_started().stop(); // stopping something never started is harmless
    }
}
```

```rust
// desktop/src/agent/activity.rs (tests)
#[cfg(test)]
mod tests {
    use super::*;
    use crate::agent::testkit::*;
    use serde_json::json;

    #[test]
    fn activity_skips_hooks_when_the_server_does_not_want_window_events() {
        let fake = FakeServer::new();
        let mut a = WindowActivity::new(client(&fake)).with_idle_source(Arc::new(|| Some(0.0)));
        a.on_hello(&json!({"window_events": false}));
        assert!(!a.running());
        a.stop();
    }

    #[test]
    fn activity_runs_the_pump_and_flushes_what_is_left_on_stop() {
        let fake = FakeServer::new();
        let c = client(&fake);
        c.next(0.0).unwrap(); // a proven answer: window events may go out
        let mut a = WindowActivity::new(c).with_idle_source(Arc::new(|| Some(400.0))).with_no_hooks();
        a.on_hello(&json!({"window_events": true, "events_max": 200, "idle_threshold_sec": 300}));
        assert!(a.running());
        wait_until(|| fake.state().requests.iter().any(|r| r.path == "/api/agent/events"));
        a.stop();
        let body = fake.state().requests.iter().find(|r| r.path == "/api/agent/events").unwrap().body.clone().unwrap();
        assert_eq!(body["events"][0]["type"], "idle");
    }

    #[test]
    fn the_final_flush_sends_nothing_after_an_unproven_401() {
        let fake = FakeServer::new();
        let c = client(&fake);
        fake.state().key = None;
        fake.state().status_for.insert("/api/agent/next".into(), 401);
        assert!(c.next(0.0).is_err());
        let mut a = WindowActivity::new(c).with_idle_source(Arc::new(|| Some(400.0))).with_no_hooks();
        a.on_hello(&json!({"window_events": true}));
        std::thread::sleep(std::time::Duration::from_millis(300));
        a.stop();
        assert!(!fake.state().requests.iter().any(|r| r.path == "/api/agent/events"));
    }
}
```

```rust
// desktop/src/agent/redact.rs (tests) — the server's test_redact_notice_tokens vectors
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn redacts_like_the_server() {
        let cases = [
            ("msedge --app=http://127.0.0.1:8700/notice#d=1&t=abc", "msedge --app=http://127.0.0.1:8700/notice#d=1&t=<redacted>"),
            ("x http://localhost:8700/notice#t=abc&d=1 y", "x http://localhost:8700/notice#t=<redacted>&d=1 y"),
            ("x 'http://[::1]:8700/notice#d=1&t=a%2Fb' y", "x 'http://[::1]:8700/notice#d=1&t=<redacted>' y"),
            ("x https://example.com/watch?v=1&t=30 y", "x https://example.com/watch?v=1&t=30 y"),
            ("notepad.exe a.txt", "notepad.exe a.txt"),
        ];
        for (raw, clean) in cases {
            assert_eq!(redact_notice_tokens(raw), clean, "{raw}");
        }
    }
}
```

- [ ] **Step 2: 실패 확인** — Run: `cargo test --locked agent` → FAIL

- [ ] **Step 3: 구현** — 위 Interfaces대로. `WindowActivity::with_no_hooks()`는 테스트용(훅 스레드를 만들지 않음). 실제 훅 테스트(`the_hook_thread_installs_three_hooks_and_stops`)는 이 PC의 대화형 세션에서 관리자 없이 돌아갑니다(Python `test_hook_thread_installs_three_hooks_and_stops`와 같음).

- [ ] **Step 4: 통과 확인** — Rust 검사 3종 → 통과.

- [ ] **Step 5: Commit** — `git commit -m "feat(desktop): agent window events and idle (WinEvent hooks, coalescing, batched sending with dropped counts, title redaction)"`

---

### Task 11: 에이전트 고지 창 — 최상위 모달 WebView2, 서버 통합 테스트

**Files:**
- Create: `desktop/src/agent/webview.rs`, `desktop/tests/agent_webview.rs`
- Modify: `desktop/src/lib.rs`(`Agent` + `Dialog::Webview`), `server/tests/test_integration_agent.py`(데스크톱 에이전트 매개변수)

**Interfaces:**
- Produces:
  - `pub const NOTICE_TITLE: &str = "MCP Monitor 고지";`
  - `#[derive(Debug, PartialEq)] pub struct NoticeSpec { pub title: &'static str, pub width: f64, pub height: f64, pub always_on_top: bool, pub closable: bool, pub minimizable: bool, pub maximizable: bool, pub resizable: bool, pub skip_taskbar: bool, pub incognito: bool, pub focused: bool, pub decorations: bool, pub context_menu: bool, pub devtools: bool, pub accelerator_keys: bool }`, `notice_spec(work_w: f64, work_h: f64) -> NoticeSpec`: `always_on_top: true, closable: false, minimizable: false, maximizable: false, resizable: false, skip_taskbar: true, incognito: true, focused: true, decorations: true(제목 표시줄은 두고 닫기 단추만 비활성), context_menu: false, devtools: false, accelerator_keys: false`, 크기 = `notice_size(work_w, work_h)`.
  - `notice_size(w, h) -> (f64, f64)` = `((640.0f64).min(w - 32.0).max(320.0), (600.0f64).min(h - 32.0).max(300.0))`.
  - `notice_navigation_allowed(url: &tauri::Url, server: &str) -> bool`: 스킴·호스트·포트가 `server`와 같고, 사용자 정보 없음, 경로가 정확히 `/notice`, 쿼리 없음(조각은 허용).
  - `notice_data_dir(local_app_data: &Path) -> PathBuf` = `<L>\mcp-monitor\notice-webview`(제거의 `remove_webview_profiles`가 지우는 폴더 아래).
  - `pub struct NoticeState`(Arc 공유): `begin_close()`(우리가 닫는 중), `should_prevent_close() -> bool`(우리가 닫는 중이 아니면 true — Alt+F4·`WM_CLOSE` 무시), `on_destroyed()`(우리가 닫는 중이 아니면 사용자 닫음으로 기록), `on_process_failed()`(WebView2 브라우저·렌더러 프로세스가 죽음 → 사용자 닫음으로 기록, 서버가 1초 뒤 다시 보냄), `take_closed_by_user() -> bool`(한 번 읽으면 지움), `reset()`(새 창).
  - `WebViewNotice::new(app: AppHandle, server: String, data_dir: PathBuf, state: Arc<NoticeState>)` impl `NoticeWindow`: `open` = 메인 스레드(`run_on_main_thread`)에서 기존 창이 있으면 닫고 `WebviewWindowBuilder::new(app, "notice", WebviewUrl::External(url))`에 `notice_spec`(모니터 작업 영역 기준) + `.center()` + `.data_directory(data_dir)` + `.on_navigation(|u| notice_navigation_allowed(u, &server))`; 만든 뒤 `with_webview`로 `ICoreWebView2Settings`(`SetAreDevToolsEnabled(false)`, `SetAreDefaultContextMenusEnabled(false)`, `SetAreBrowserAcceleratorKeysEnabled(false)`), `add_NewWindowRequested`(Handled = TRUE, 아무것도 열지 않음), `add_ProcessFailed`(→ `on_process_failed`); `on_window_event`: `CloseRequested` → `should_prevent_close()`면 `api.prevent_close()`, `Destroyed` → `on_destroyed()`; 처음 한 번 `SetForegroundWindow`, 실패(이 프로세스가 전경을 가질 수 없음)면 `FlashWindowEx(FLASHW_ALL | FLASHW_TIMERNOFG)`; 창이 있는 동안 2초마다 `SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)`(초점을 빼앗지 않음). 창 만들기가 실패하면(WebView2 런타임 없음 등) 로그 후 기본 브라우저로 `ShellExecuteW("open", url)`(Python V25와 같음 — 고지는 반드시 보여야 함). `close` = `begin_close()` 후 메인 스레드에서 `destroy()`. `closed_by_user` = `take_closed_by_user()`.
  - `run_webview_agent(cfg: AgentConfig) -> i32`: `tauri::Builder::default()`(플러그인 없음, 단일 인스턴스 없음 — 세션마다·앱 모드와 따로) `.any_thread()` 쓰지 않음(메인 스레드), `setup`에서 러너 스레드를 띄우고, 러너가 끝나면 `app_handle.exit(code)`; `RunEvent::ExitRequested`에서 창이 모두 닫혀도 러너가 끝나기 전에는 `api.prevent_exit()`. 종료 코드는 러너의 값.
  - 서버 통합: `server/tests/test_integration_agent.py`의 `stack` 픽스처에 `params=["python", "desktop"]`. `desktop`은 환경 변수 `MCPMON_DESKTOP_EXE`(빌드한 `mcp-monitor.exe` 경로)가 없으면 `pytest.skip("set MCPMON_DESKTOP_EXE to the built mcp-monitor.exe")`, 있으면 `AgentOptions(command=(exe, "agent"), dialog="print", …)`. `agents_of(root)`는 명령줄에 `mcp_agent` **또는** `mcp-monitor`가 있고 `str(root)`가 있는 프로세스. 기존 네 시나리오가 두 에이전트 모두에서 통과해야 합니다(TCP 피어 pid = hello pid, 토큰 + 서버 키, 고지 표시·확인·재표시·서비스 정지 시 종료).

- [ ] **Step 1: 실패하는 테스트 작성**

```rust
// desktop/src/agent/webview.rs (tests)
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn notice_window_spec_is_a_topmost_modal() {
        let s = notice_spec(1920.0, 1040.0);
        assert_eq!(s, NoticeSpec { title: "MCP Monitor 고지", width: 640.0, height: 600.0, always_on_top: true, closable: false,
            minimizable: false, maximizable: false, resizable: false, skip_taskbar: true, incognito: true, focused: true,
            decorations: true, context_menu: false, devtools: false, accelerator_keys: false });
    }

    #[test]
    fn notice_size_fits_the_work_area() {
        assert_eq!(notice_size(1920.0, 1040.0), (640.0, 600.0));
        assert_eq!(notice_size(800.0, 560.0), (640.0, 528.0));
        assert_eq!(notice_size(500.0, 400.0), (468.0, 368.0));
        assert_eq!(notice_size(300.0, 250.0), (320.0, 300.0));
    }

    #[test]
    fn notice_navigation_allows_only_the_notice_page() {
        let server = "http://127.0.0.1:8700";
        let ok = |u: &str| notice_navigation_allowed(&tauri::Url::parse(u).unwrap(), server);
        assert!(ok("http://127.0.0.1:8700/notice#d=1&t=tok_ABCDEFGHIJKLmnop") && ok("http://127.0.0.1:8700/notice"));
        for bad in ["http://127.0.0.1:8700/admin", "http://127.0.0.1:8701/notice", "http://localhost:8700/notice", "https://127.0.0.1:8700/notice",
                    "http://u@127.0.0.1:8700/notice", "http://127.0.0.1:8700/notice?x=1", "http://127.0.0.1:8700/notice/x", "file:///C:/Windows/win.ini",
                    "https://evil.example/notice"] {
            assert!(!ok(bad), "{bad}");
        }
    }

    #[test]
    fn close_requests_are_refused_unless_we_close() {
        let s = NoticeState::default();
        assert!(s.should_prevent_close());
        s.on_destroyed(); // destroyed without our close (e.g. ended from outside)
        assert!(s.take_closed_by_user() && !s.take_closed_by_user());
        s.reset();
        s.begin_close();
        assert!(!s.should_prevent_close());
        s.on_destroyed();
        assert!(!s.take_closed_by_user());
    }

    #[test]
    fn a_failed_webview_counts_as_closed_by_the_user() {
        let s = NoticeState::default();
        s.on_process_failed();
        assert!(s.take_closed_by_user());
    }

    #[test]
    fn notice_profile_lives_under_the_removed_folder() {
        assert_eq!(notice_data_dir(Path::new(r"C:\Users\hong\AppData\Local")), Path::new(r"C:\Users\hong\AppData\Local\mcp-monitor\notice-webview"));
    }
}
```

```rust
// desktop/tests/agent_webview.rs — a real WebView2 window on this desktop:
//   cargo test --locked --test agent_webview -- --ignored
mod common;
use common::{agent_server::AgentServer, exe};
use serde_json::json;
use std::time::{Duration, Instant};
use windows::core::BOOL;
use windows::Win32::Foundation::{HWND, LPARAM, WPARAM};
use windows::Win32::UI::WindowsAndMessaging::*;

fn windows_of(pid: u32) -> Vec<(HWND, String)> {
    unsafe extern "system" fn each(hwnd: HWND, l: LPARAM) -> BOOL {
        let out = unsafe { &mut *(l.0 as *mut (u32, Vec<(HWND, String)>)) };
        let mut p = 0u32;
        unsafe { GetWindowThreadProcessId(hwnd, Some(&mut p)) };
        if p == out.0 && unsafe { IsWindowVisible(hwnd) }.as_bool() {
            let mut buf = [0u16; 256];
            let n = unsafe { GetWindowTextW(hwnd, &mut buf) } as usize;
            out.1.push((hwnd, String::from_utf16_lossy(&buf[..n])));
        }
        true.into()
    }
    let mut acc: (u32, Vec<(HWND, String)>) = (pid, Vec::new());
    unsafe { EnumWindows(Some(each), LPARAM(&mut acc as *mut _ as isize)).ok() };
    acc.1
}

fn wait_for<T>(secs: u64, mut f: impl FnMut() -> Option<T>) -> T {
    let end = Instant::now() + Duration::from_secs(secs);
    loop {
        if let Some(v) = f() {
            return v;
        }
        assert!(Instant::now() < end, "timed out");
        std::thread::sleep(Duration::from_millis(100));
    }
}

#[test]
#[ignore = "opens a real WebView2 window on this desktop"]
fn webview_notice_is_topmost_ignores_wm_close_and_closes_on_command() {
    let srv = AgentServer::start(Some([0x11; 32]));
    srv.serve_page("/notice", "<!doctype html><title>notice</title><button>확인</button>");
    let notice = format!("{}/notice#d=7&t=tok_ABCDEFGHIJKLmnop", srv.url());
    srv.queue(json!({"type": "show_notice", "display_id": 7, "attempt": 1, "url": notice}));
    let mut child = exe().args(["agent", "--server", &srv.url()]).env("MCPMON_AGENT_TOKEN", "tok")
        .env("MCPMON_AGENT_SERVER_KEY", "11".repeat(32)).spawn().unwrap();
    let hwnd = wait_for(15, || windows_of(child.id()).into_iter().find(|(_, t)| t == "MCP Monitor 고지").map(|(h, _)| h));
    let ex = unsafe { GetWindowLongPtrW(hwnd, GWL_EXSTYLE) } as u32;
    assert!(ex & WS_EX_TOPMOST.0 != 0, "not top-most");
    let state = unsafe { GetMenuState(GetSystemMenu(hwnd, false), SC_CLOSE, MF_BYCOMMAND) };
    assert!(state & (MF_GRAYED.0 | MF_DISABLED.0) != 0, "close is enabled");
    unsafe { PostMessageW(Some(hwnd), WM_CLOSE, WPARAM(0), LPARAM(0)).unwrap() };
    std::thread::sleep(Duration::from_secs(1));
    assert!(unsafe { IsWindow(Some(hwnd)) }.as_bool(), "WM_CLOSE closed the notice");
    srv.queue(json!({"type": "close_notice", "display_id": 7}));
    wait_for(5, || (!unsafe { IsWindow(Some(hwnd)) }.as_bool()).then_some(()));
    srv.queue(json!({"type": "exit"}));
    assert_eq!(child.wait().unwrap().code(), Some(0));
    assert!(!srv.requests().iter().any(|r| r.path == "/api/agent/notice/7/closed"));
}
```

```python
# server/tests/test_integration_agent.py (변경: 두 에이전트로 같은 시나리오)
DESKTOP_EXE = os.environ.get("MCPMON_DESKTOP_EXE")


def agent_options(kind: str, run: Path) -> AgentOptions:
    common = dict(dialog="print", url_dir=run, backoff=(0.5, 1, 2), exit_grace_sec=1.0, tick_sec=0.2)
    if kind == "desktop":
        if not DESKTOP_EXE:
            pytest.skip("set MCPMON_DESKTOP_EXE to the built mcp-monitor.exe")
        return AgentOptions(command=(DESKTOP_EXE, "agent"), agent_dir=Path(DESKTOP_EXE).parent, **common)
    return AgentOptions(agent_dir=REPO / "agent", **common)


def agents_of(root: Path) -> list[psutil.Process]:
    found = []
    for p in psutil.process_iter(["cmdline"]):
        cmd = " ".join(p.info["cmdline"] or [])
        if ("mcp_agent" in cmd or "mcp-monitor" in cmd) and str(root) in cmd:
            found.append(p)
    return found


@pytest.fixture(params=["python", "desktop"])
async def stack(request, tmp_path):
    ...  # unchanged body, except: agent=agent_options(request.param, run)
```

- [ ] **Step 2: 실패 확인** — Run: `cargo test --locked agent::webview` → FAIL

- [ ] **Step 3: 구현** — 위 Interfaces대로. Tauri 2.12.5에 `on_new_window` 빌더 API가 있으면 그것을 써도 됩니다(동작: 모두 거부). `with_webview`에서 쓰는 `webview2-com`은 Task 1에서 tauri와 같은 버전으로 고정한 것.

- [ ] **Step 4: 통과 확인**
  - Rust 검사 3종 → 통과.
  - Run(이 PC 화면에 창이 잠깐 뜸): `cargo test --locked --test agent_webview -- --ignored` → 통과. 실패하면 스크린숏과 `windows_of` 결과를 보고서에 붙입니다. `about:blank` 같은 초기 탐색이 막혀 창이 비면 `notice_navigation_allowed`에 `about:blank` 정확히 하나만 더하고 보고합니다.
  - Run(server): `cargo build --locked`(desktop) 뒤 `$env:MCPMON_DESKTOP_EXE = "<repo>\desktop\target\debug\mcp-monitor.exe"; uv run python -m pytest -m integration tests/test_integration_agent.py -v` → `[python]`·`[desktop]` 8개 모두 통과. `uv run python -m pytest -q` → 통과.

- [ ] **Step 5: Commit** — `git commit -m "feat(desktop): top-most modal WebView2 notice window for the Rust agent; server integration runs both agents"`

---

### Task 12: 앱 모드 — WebView2 창, 탐색 제한, 트레이, 단일 인스턴스, 자동 실행, 설치·업그레이드 안내

**Files:**
- Create: `desktop/src/app/mod.rs`, `desktop/src/app/nav.rs`, `desktop/src/app/detect.rs`, `desktop/src/app/tray.rs`, `desktop/src/app/autostart.rs`, `desktop/tests/app_window.rs`
- Modify: `desktop/src/lib.rs`(`Auto`, `App`, `Autostart`)

**Interfaces:**
- Produces:
  - `nav`: `#[derive(Debug, PartialEq)] pub enum NavDecision { Allow, OpenExternal, Block }`, `classify_navigation(url: &str, local_port: u16) -> NavDecision`: 파싱 실패 → Block; `http`이고 호스트가 정확히 `127.0.0.1`, 포트 = `local_port`, 사용자 정보 없음 → Allow; `http://tauri.localhost/…`(연결 중 페이지) → Allow; 그 밖의 `http`/`https`(사용자 정보 없음) → OpenExternal(기본 브라우저, `ShellExecuteW("open")`); 그 밖(사용자 정보 있음, `file:`, `javascript:`, `data:`, `ms-*:`, `about:` 등) → Block. 새 창 요청도 같은 규칙(Allow면 같은 창에서 열고 새 창은 만들지 않음).
  - `detect`:
    - `pub struct InstallInfo { pub version: String, pub local_port: u16, pub external_port: u16, pub data_root: PathBuf }`, `read_install_info(install_dir: &Path) -> Option<InstallInfo>`(`<I>\install.json`; 사용자도 읽을 수 있음).
    - `installed_version(registry: Option<String>, install_dir: &Path) -> Option<Version>`: 앱 및 기능의 `DisplayVersion` → `<I>\bundle.json`의 `version`(1.0.0 PowerShell 설치).
    - `#[derive(Debug, PartialEq)] pub enum AutoAction { App, Install, Upgrade { installed: Option<Version> }, OlderThanInstalled { installed: Version } }`, `decide(installed: Option<Version>, service_exists: bool, own: Version) -> AutoAction`: 서비스 없음 → Install; 서비스 있음 + 버전 모름 → `Upgrade { installed: None }`; 설치본 < 자신 → Upgrade; 같음 → App; 설치본 > 자신 → OlderThanInstalled.
    - `app_url(info) = format!("http://127.0.0.1:{}/admin", info.local_port)`, `app_data_dir(local_app_data) = <L>\mcp-monitor\webview`.
  - `autostart`: `RUN_KEY = r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run"`, `RUN_VALUE = "MCPMonitor"`, `run_value(install_dir) -> String` = `"\"<I>\mcp-monitor.exe\" app --background"`, `set_autostart(reg: &mut dyn Registry, install_dir, on: bool) -> Result<(), String>`, `autostart_enabled(reg: &dyn Registry, install_dir) -> bool`(값이 정확히 `run_value`일 때만).
  - 문구(한국어, 메시지 상자): 설치 `"MCP Monitor가 이 PC에 설치되어 있지 않습니다.\n\n지금 설치할까요? 관리자 권한이 필요합니다.\n설치 위치: <ProgramFiles>\\MCP Monitor\n데이터: <ProgramData>\\MCP Monitor"`(예/아니요); 업그레이드 `"설치된 MCP Monitor <v | 알 수 없는 버전>을(를) <own>(으)로 업그레이드할까요?\n\n서비스가 잠시 멈추고, 데이터와 설정은 그대로 남습니다. 관리자 권한이 필요합니다."`; 더 새 설치본 `"설치된 MCP Monitor(<v>)가 이 실행 파일(<own>)보다 새롭습니다. 설치된 MCP Monitor의 창을 엽니다."`(정보 → App).
  - `lib::run`의 `Auto`: `decide(...)` → Install/Upgrade는 예이면 `elevate_and_wait(current_exe, ["install", "--interactive"])`(업그레이드면 설치 위치를 `--install-dir <앱 및 기능 위치 또는 기본값>`로 함께), 0이면 이어서 App; 아니요·취소면 0으로 끝. OlderThanInstalled는 정보 상자 뒤 App.
  - `App(args)`(`app/mod.rs`): `InstallInfo`(dev 기능의 `--server-url`이면 그 주소의 포트)가 없으면 오류 상자 "MCP Monitor가 설치되어 있지 않습니다. mcp-monitor.exe를 다시 실행해 설치하세요." + 1. `dev`가 아니면 `strip_webview2_env`. `tauri::Builder::default().plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| { 창을 보이고 앞으로 }))` — **app 모드에서만** 등록. 창 `"main"`: `WebviewUrl::App("index.html")`(연결 중), 제목 "MCP Monitor", `inner_size(1280, 800)`, `min_inner_size(640, 600)`, `data_directory(app_data_dir)`, `visible(!args.background)`, `on_navigation(classify == Allow; OpenExternal은 브라우저로 넘기고 false)`, 새 창은 `classify`로(Allow도 새 창은 만들지 않음), `with_webview`로 개발자 도구·기본 컨텍스트 메뉴의 "검사" 끔(`SetAreDevToolsEnabled(false)`), 닫기 → 숨김(`prevent_close` + `hide`). 준비 스레드: 1초마다 `GET http://127.0.0.1:<LP>/api/channel`(ureq, 프록시 없음) → 200이면 창을 `app_url`로 탐색; 30초 동안 안 되면 `index.html#stopped`로 바꾸고 5초마다 계속 시도, 되면 `app_url`.
  - `tray`: 아이콘 = 앱 아이콘, 툴팁 "MCP Monitor", 메뉴 `창 열기` / `서비스: 실행 중|중지됨|설치 안 됨`(비활성 항목, 5초마다 `QueryServiceStatus`) / `로그인할 때 트레이 시작`(체크 항목 → `set_autostart`) / `트레이 종료`(앱 종료; 서비스는 그대로). 왼쪽 클릭 = 창 열기.
  - `Autostart(on)`: 설치 위치(앱 및 기능)로 `set_autostart(WinRegistry(HKCU))`, 설치 안 됨이면 `오류: …` + 1.
  - `tests/app_window.rs`(`#![cfg(feature = "dev")]`, `#[ignore]`): 작은 HTTP 서버(`/api/channel` → 200 `{"channel":"local"}`, `/admin` → HTML)를 띄우고 `mcp-monitor.exe app --server-url <srv>`를 `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=<p>`, `LOCALAPPDATA=<scratch>`로 실행 → 20초 안에 `http://127.0.0.1:<p>/json/list`에 `url`이 `<srv>/admin`으로 시작하는 페이지가 나타남 → 프로세스 종료.

- [ ] **Step 1: 실패하는 테스트 작성**

```rust
// desktop/src/app/nav.rs (tests)
#[cfg(test)]
mod tests {
    use super::*;
    use NavDecision::*;

    #[test]
    fn classify_navigation_table() {
        let cases = [
            ("http://127.0.0.1:8700/admin", Allow), ("http://127.0.0.1:8700/admin/logs?from=1#x", Allow),
            ("http://127.0.0.1:8700/notice#d=1&t=x", Allow), ("http://tauri.localhost/index.html#stopped", Allow),
            ("http://127.0.0.1:8701/", OpenExternal), ("http://localhost:8700/admin", OpenExternal),
            ("http://127.0.0.1.evil.example:8700/", OpenExternal), ("https://example.com/docs", OpenExternal),
            ("http://[::1]:8700/admin", OpenExternal), ("http://user@127.0.0.1:8700/admin", Block),
            ("file:///C:/Windows/win.ini", Block), ("javascript:alert(1)", Block), ("data:text/html,x", Block),
            ("ms-settings:privacy", Block), ("about:blank", Block), ("not a url", Block),
        ];
        for (url, want) in cases {
            assert_eq!(classify_navigation(url, 8700), want, "{url}");
        }
        assert_eq!(classify_navigation("http://127.0.0.1:9700/admin", 9700), Allow);
        assert_eq!(classify_navigation("http://127.0.0.1:8700/admin", 9700), OpenExternal);
    }
}
```

```rust
// desktop/src/app/detect.rs (tests)
#[cfg(test)]
mod tests {
    use super::*;
    use crate::version::Version;
    use std::fs;

    #[test]
    fn auto_mode_decisions() {
        let own = Version(1, 1, 0);
        assert_eq!(decide(None, false, own), AutoAction::Install);
        assert_eq!(decide(Some(Version(1, 1, 0)), false, own), AutoAction::Install); // entry left, service gone: repair
        assert_eq!(decide(None, true, own), AutoAction::Upgrade { installed: None });
        assert_eq!(decide(Some(Version(1, 0, 0)), true, own), AutoAction::Upgrade { installed: Some(Version(1, 0, 0)) });
        assert_eq!(decide(Some(Version(1, 1, 0)), true, own), AutoAction::App);
        assert_eq!(decide(Some(Version(1, 2, 0)), true, own), AutoAction::OlderThanInstalled { installed: Version(1, 2, 0) });
    }

    #[test]
    fn installed_version_falls_back_to_the_bundle_of_a_powershell_install() {
        let d = tempfile::tempdir().unwrap();
        fs::write(d.path().join("bundle.json"), r#"{"layout":"pyinstaller","version":"1.0.0"}"#).unwrap();
        assert_eq!(installed_version(Some("1.1.0".into()), d.path()), Some(Version(1, 1, 0)));
        assert_eq!(installed_version(None, d.path()), Some(Version(1, 0, 0)));
        assert_eq!(installed_version(None, &d.path().join("missing")), None);
    }

    #[test]
    fn install_info_gives_the_app_url() {
        let d = tempfile::tempdir().unwrap();
        fs::write(d.path().join("install.json"), r#"{"version":"1.1.0","local_port":9700,"external_port":9701,"data_root":"D:\\MCP"}"#).unwrap();
        let info = read_install_info(d.path()).unwrap();
        assert_eq!((app_url(&info), info.external_port), ("http://127.0.0.1:9700/admin".to_string(), 9701));
        fs::write(d.path().join("install.json"), "{").unwrap();
        assert!(read_install_info(d.path()).is_none());
        assert_eq!(app_data_dir(Path::new(r"C:\Users\a\AppData\Local")), Path::new(r"C:\Users\a\AppData\Local\mcp-monitor\webview"));
    }
}
```

```rust
// desktop/src/app/autostart.rs (tests)
#[cfg(test)]
mod tests {
    use super::*;
    use crate::install::registry::FakeRegistry;

    #[test]
    fn autostart_writes_and_removes_the_run_value() {
        let dir = Path::new(r"C:\Program Files\MCP Monitor");
        assert_eq!(run_value(dir), r#""C:\Program Files\MCP Monitor\mcp-monitor.exe" app --background"#);
        let mut r = FakeRegistry::default();
        assert!(!autostart_enabled(&r, dir));
        set_autostart(&mut r, dir, true).unwrap();
        assert!(autostart_enabled(&r, dir) && r.string(RUN_KEY, RUN_VALUE).as_deref() == Some(run_value(dir).as_str()));
        assert!(!autostart_enabled(&r, Path::new(r"D:\Other")));
        set_autostart(&mut r, dir, false).unwrap();
        assert!(!autostart_enabled(&r, dir) && r.string(RUN_KEY, RUN_VALUE).is_none());
    }
}
```

```rust
// desktop/tests/app_window.rs — cargo test --locked --features dev --test app_window -- --ignored
#![cfg(feature = "dev")]
mod common;
use common::{agent_server::AgentServer, exe, Scratch};
use std::time::{Duration, Instant};

#[test]
#[ignore = "opens a real WebView2 window on this desktop"]
fn the_app_window_opens_the_admin_page_of_its_server() {
    let srv = AgentServer::start(None);
    srv.serve_page("/api/channel", r#"{"channel":"local"}"#);
    srv.serve_page("/admin", "<!doctype html><title>admin</title><p>admin</p>");
    let cdp = std::net::TcpListener::bind("127.0.0.1:0").unwrap().local_addr().unwrap().port();
    let s = Scratch::new();
    let mut child = exe().args(["app", "--server-url", &srv.url()])
        .env("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", format!("--remote-debugging-port={cdp}"))
        .env("LOCALAPPDATA", s.path()).spawn().unwrap();
    let want = format!("{}/admin", srv.url());
    let end = Instant::now() + Duration::from_secs(20);
    let found = loop {
        let pages = ureq::get(&format!("http://127.0.0.1:{cdp}/json/list")).call().ok().and_then(|mut r| r.body_mut().read_to_string().ok());
        if pages.as_deref().is_some_and(|p| p.contains(&want)) {
            break true;
        }
        if Instant::now() > end {
            break false;
        }
        std::thread::sleep(Duration::from_millis(250));
    };
    child.kill().unwrap();
    assert!(found, "no WebView2 page at {want}");
}
```

- [ ] **Step 2: 실패 확인** — Run: `cargo test --locked app::` → FAIL

- [ ] **Step 3: 구현** — 위 Interfaces대로. 업그레이드 뒤 다른 세션의 트레이는 설치기가 끝냈으므로(Task 7 `stop_apps`) 다음 로그인 때(`Run` 값이 있으면) 다시 뜹니다 — 운영 문서에 적음(Task 15).

- [ ] **Step 4: 통과 확인**
  - Rust 검사 3종 → 통과. `cargo clippy --locked --all-targets --features dev -- -D warnings` → 0건.
  - Run(이 PC 화면에 창이 잠깐 뜸): `cargo test --locked --features dev --test app_window -- --ignored` → 통과.
  - 손 확인(보고서에 결과): `cargo run --locked --features dev -- app --server-url http://127.0.0.1:<P>`(Task 1 스파이크처럼 띄운 서버) → 연결 중 페이지 → 관리 화면; 창을 640×600까지 줄였을 때 가로 스크롤 없음; 창 닫기 → 트레이에 남음, 트레이 "창 열기"; 같은 명령을 한 번 더 → 새 창 없이 기존 창이 앞으로; 서버를 멈추고 다시 실행 → 30초 뒤 `#stopped` 문구.

- [ ] **Step 5: Commit** — `git commit -m "feat(desktop): app mode (single-instance WebView2 window limited to 127.0.0.1:<port>, tray, login autostart, install and upgrade prompts)"`

---

### Task 13: 릴리스 빌드 `install/build-desktop.ps1` — payload → 선택 서명 → cargo audit → 내장 빌드 → 검사

**Files:**
- Create: `install/build-desktop.ps1`, `server/tests/test_desktop_exe.py`(마커 `desktop`), `server/tests/test_desktop_build.py`
- Modify: `server/pyproject.toml`(pytest 마커 `desktop` 추가, `addopts`에 `and not desktop`)

**Interfaces:**
- Produces:
  - `install/build-desktop.ps1 [-SkipAudit] [-SkipPayload] [-SignThumbprint <SHA1>] [-TimestampUrl <url>] [-Out <폴더, 기본 <repo>\dist>]`(UTF-8 BOM, Windows PowerShell 5.1, `Set-StrictMode -Version Latest`, `$ErrorActionPreference = "Stop"`):
    1. `-SkipPayload`가 아니면 `install\build.ps1 -Out <repo>\dist\payload [-SkipAudit]`.
    2. `-SignThumbprint`면 `-TimestampUrl` 필수, payload의 `bin\monitor\mcp-monitor-server.exe`를 **묶기 전에** 서명(`signtool sign /sha1 <t> /fd SHA256 /tr <url> /td SHA256`, `signtool verify /pa`).
    3. `cargo audit`(`-SkipAudit`면 경고만) — 0이 아니면 실패.
    4. `MCPMON_PAYLOAD_DIR=<payload>`로 `cargo build --release --locked`(**기능 없이**; `dev`를 켜지 않음, Y24).
    5. 검사: `--version`이 정확히 `mcp-monitor <Cargo 버전> (payload <12 hex>, release)`; `dumpbin /loadconfig`에 `800 Dependent Load Flag`; `verify-payload <%LOCALAPPDATA%\mcp-monitor-build\<임의>>`가 `payload OK: …`이고 풀린 `mcp-monitor-server.exe --version`이 `mcp-monitor <버전>`(검사 폴더는 끝에 지움).
    6. `-SignThumbprint`면 `mcp-monitor.exe` 서명, 아니면 `NOTE: not signed (no -SignThumbprint; D5)`.
    7. `<Out>\mcp-monitor-<버전>.exe`와 `<Out>\mcp-monitor-<버전>.exe.sha256`(`<hash>  mcp-monitor-<버전>.exe\n`, BOM 없음). 마지막 줄 `==> done: <경로> (sha256 <hash>)`.

```powershell
<#
.SYNOPSIS
  Build the release mcp-monitor.exe (Plan 6 Task 13): payload (build.ps1) -> optional signing -> cargo audit ->
  cargo build --release with the payload embedded -> checks -> dist\mcp-monitor-<version>.exe + .sha256.
#>
[CmdletBinding()]
param(
    [switch]$SkipAudit,
    [switch]$SkipPayload,
    [string]$SignThumbprint,
    [string]$TimestampUrl,
    [string]$Out
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
$Desktop = Join-Path $Repo "desktop"
$Payload = Join-Path $Repo "dist\payload"
if (-not $Out) { $Out = Join-Path $Repo "dist" }
if ($SignThumbprint -and -not $TimestampUrl) { throw "-SignThumbprint needs -TimestampUrl" }

function Write-Step([string]$Message) { Write-Host "==> $Message" }
function Invoke-Native([string]$What, [scriptblock]$Command) {
    $ErrorActionPreference = "Continue"
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit code $LASTEXITCODE)" }
}
function Find-VsTool([string]$Name) {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
    $vs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    $tool = Get-ChildItem -Path (Join-Path $vs "VC\Tools\MSVC\*\bin\Hostx64\x64\$Name") -ErrorAction SilentlyContinue |
        Sort-Object FullName | Select-Object -Last 1
    if (-not $tool) { throw "$Name was not found under $vs" }
    return $tool.FullName
}
function Invoke-Sign([string]$File) {
    $signtool = Get-ChildItem -Path "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" -ErrorAction SilentlyContinue |
        Sort-Object FullName | Select-Object -Last 1
    if (-not $signtool) { throw "signtool.exe was not found (Windows SDK)" }
    Invoke-Native "signtool sign" { & $signtool.FullName sign /sha1 $SignThumbprint /fd SHA256 /tr $TimestampUrl /td SHA256 $File }
    Invoke-Native "signtool verify" { & $signtool.FullName verify /pa $File }
}

$cargoToml = Get-Content -LiteralPath (Join-Path $Desktop "Cargo.toml") -Raw
if ($cargoToml -notmatch '(?m)^version\s*=\s*"([^"]+)"') { throw "no version in desktop\Cargo.toml" }
$Version = $Matches[1]

if (-not $SkipPayload) {
    Write-Step "payload (install\build.ps1)"
    $buildArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $PSScriptRoot "build.ps1"), "-Out", $Payload)
    if ($SkipAudit) { $buildArgs += "-SkipAudit" }
    Invoke-Native "build.ps1" { & powershell.exe @buildArgs }
}
if (-not (Test-Path -LiteralPath (Join-Path $Payload "bundle.json"))) { throw "$Payload has no bundle.json: run without -SkipPayload" }
if ($SignThumbprint) { Write-Step "sign the embedded server"; Invoke-Sign (Join-Path $Payload "bin\monitor\mcp-monitor-server.exe") }

Push-Location $Desktop
try {
    if ($SkipAudit) { Write-Host "WARNING: -SkipAudit: cargo audit was not run" }
    else { Write-Step "cargo audit"; Invoke-Native "cargo audit" { & cargo audit } }
    Write-Step "cargo build --release --locked (payload embedded, no features)"
    $env:MCPMON_PAYLOAD_DIR = $Payload
    try { Invoke-Native "cargo build" { & cargo build --release --locked } }
    finally { Remove-Item Env:MCPMON_PAYLOAD_DIR -ErrorAction SilentlyContinue }
} finally { Pop-Location }
$Exe = Join-Path $Desktop "target\release\mcp-monitor.exe"

Write-Step "checks"
$line = (& $Exe --version | Out-String).Trim()
if ($line -notmatch "^mcp-monitor $([regex]::Escape($Version)) \(payload [0-9a-f]{12}, release\)$") { throw "unexpected --version: $line" }
$loadConfig = & (Find-VsTool "dumpbin.exe") /loadconfig $Exe | Out-String
if ($loadConfig -notmatch "800 Dependent Load Flag") { throw "DependentLoadFlags is not 0x800 (System32 only)" }
$check = Join-Path $env:LOCALAPPDATA ("mcp-monitor-build\" + [guid]::NewGuid().ToString("N").Substring(0, 12))
try {
    $verify = (& $Exe verify-payload $check | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $verify -notmatch "^payload OK: ") { throw "verify-payload: $verify" }
    $server = (& (Join-Path $check "payload\bin\monitor\mcp-monitor-server.exe") --version | Out-String).Trim()
    if ($server -ne "mcp-monitor $Version") { throw "embedded server --version: $server" }
} finally { Remove-Item -LiteralPath $check -Recurse -Force -ErrorAction SilentlyContinue }

if ($SignThumbprint) { Write-Step "sign mcp-monitor.exe"; Invoke-Sign $Exe }
else { Write-Host "NOTE: not signed (no -SignThumbprint; D5)" }

New-Item -ItemType Directory -Force -Path $Out | Out-Null
$target = Join-Path $Out "mcp-monitor-$Version.exe"
Copy-Item -LiteralPath $Exe -Destination $target -Force
$hash = (Get-FileHash -LiteralPath $target -Algorithm SHA256).Hash.ToLowerInvariant()
[System.IO.File]::WriteAllText("$target.sha256", "$hash  mcp-monitor-$Version.exe`n", (New-Object System.Text.UTF8Encoding $false))
Write-Step "done: $target (sha256 $hash)"
```

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_desktop_build.py
"""install/build.ps1 and install/build-desktop.ps1 (Plan 6 Task 13–14): parse, no dev features in a release build."""
import os
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
INSTALL = REPO / "install"
PS = [str(Path(os.environ["SystemRoot"]) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"),
      "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass"]


@pytest.mark.parametrize("name", ["build.ps1", "build-desktop.ps1"])
def test_build_scripts_parse_and_have_a_bom(name):
    p = subprocess.run([*PS, "-Command", f"$e = $null; [void][System.Management.Automation.Language.Parser]::ParseFile('{INSTALL / name}', [ref]$null, [ref]$e); $e.Count"],
                       capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    assert p.returncode == 0 and p.stdout.strip() == "0", p.stdout + p.stderr
    if name == "build-desktop.ps1":
        assert (INSTALL / name).read_bytes().startswith(b"\xef\xbb\xbf")


def test_a_release_build_never_enables_features():
    text = (INSTALL / "build-desktop.ps1").read_text("utf-8-sig")
    builds = re.findall(r"cargo build[^\r\n}]*", text)
    assert builds == ["cargo build --release --locked "] or builds == ["cargo build --release --locked"], builds
    assert "--features" not in text and "MCPMON_PAYLOAD_DIR" in text
```

```python
# server/tests/test_desktop_exe.py
"""The release mcp-monitor.exe built by install/build-desktop.ps1 (Plan 6 Task 13).

Run with ``$env:MCPMON_DESKTOP_EXE = "<repo>\\dist\\mcp-monitor-1.1.0.exe"; uv run python -m pytest -m desktop -v``.
Nothing here needs admin rights or changes this PC (install without admin stops at require_admin).
"""
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from app import __version__
from tests.live import scratch_path  # noqa: F401 (the tmp_path fixture: a scratch folder a data root may sit in)

pytestmark = pytest.mark.desktop
EXE = Path(os.environ.get("MCPMON_DESKTOP_EXE", "missing"))


def run(*args, timeout=120):
    return subprocess.run([str(EXE), *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, stdin=subprocess.DEVNULL)


def test_version_is_a_release_build_and_the_sha256_file_matches():
    p = run("--version")
    assert p.returncode == 0, p.stderr
    assert re.fullmatch(rf"mcp-monitor {re.escape(__version__)} \(payload [0-9a-f]{{12}}, release\)", p.stdout.strip()), p.stdout
    digest = hashlib.sha256(EXE.read_bytes()).hexdigest()
    assert (EXE.parent / f"{EXE.name}.sha256").read_text("utf-8") == f"{digest}  {EXE.name}\n"


def test_verify_payload_runs_the_embedded_server(tmp_path):
    p = run("verify-payload", str(tmp_path / "v"))
    assert p.returncode == 0 and p.stdout.startswith("payload OK: "), p.stdout + p.stderr
    root = tmp_path / "v" / "payload"
    v = subprocess.run([str(root / "bin" / "monitor" / "mcp-monitor-server.exe"), "--version"], capture_output=True, text=True,
                       timeout=60, stdin=subprocess.DEVNULL)
    assert v.returncode == 0 and v.stdout.strip() == f"mcp-monitor {__version__}"
    meta = json.loads((root / "bundle.json").read_text("utf-8"))
    assert (meta["layout"], meta["agent"], meta["version"]) == ("pyinstaller", "desktop", __version__)
    assert not (root / "install").exists() and not (root / "bin" / "agent").exists()


def test_dry_run_plans_from_the_release_payload(tmp_path):
    p = run("install", "--dry-run", "--install-dir", str(tmp_path / "i"), "--data-root", str(tmp_path / "d"))
    assert p.returncode == 0, p.stderr
    plan = json.loads(p.stdout)
    assert (plan["version"], plan["layout"], plan["steps"][0]["id"]) == (__version__, "pyinstaller", "require_admin")


def test_install_without_admin_changes_nothing(tmp_path):
    p = run("install", "--install-dir", str(tmp_path / "i"), "--data-root", str(tmp_path / "d"))
    assert p.returncode == 1 and "관리자 권한으로 다시 실행하세요" in p.stdout, p.stdout + p.stderr
    assert not any((tmp_path / n).exists() for n in ("i", "d", "i.staging"))
```

- [ ] **Step 2: 실패 확인** — Run(server): `uv run python -m pytest tests/test_desktop_build.py -v` → FAIL(스크립트 없음)

- [ ] **Step 3: 구현** — 위 코드로 `install/build-desktop.ps1`(UTF-8 **BOM 포함**), `server/pyproject.toml`의 마커·`addopts`.

- [ ] **Step 4: 릴리스 빌드와 검증**
  - Run(저장소 루트): `powershell -NoProfile -ExecutionPolicy Bypass -File install\build-desktop.ps1` → `==> done: …\dist\mcp-monitor-1.1.0.exe (sha256 …)`, `NOTE: not signed …`. 실패하면(SAC 차단 포함) 멈추고 보고.
  - Run(server): `uv run python -m pytest tests/test_desktop_build.py -v` → 통과. `$env:MCPMON_DESKTOP_EXE = "<repo>\dist\mcp-monitor-1.1.0.exe"; uv run python -m pytest -m desktop -v` → 통과. 같은 환경 변수로 `uv run python -m pytest -m integration tests/test_integration_agent.py -v` → `[desktop]` 포함 통과(릴리스 exe로도).
  - SAC 확인(보고서에 기록): 새 PowerShell에서 `& "<repo>\dist\mcp-monitor-1.1.0.exe" --version | Write-Output` → 실행됨; `Get-WinEvent -LogName Microsoft-Windows-CodeIntegrity/Operational -MaxEvents 20 | Where-Object Message -match "mcp-monitor"` → 차단 없음. 탐색기에서 더블클릭 → 설치 안내 메시지 상자(아니요를 누름 — 이 PC에 설치하지 않음).

- [ ] **Step 5: Commit** — `git commit -m "build: release mcp-monitor.exe (embedded payload, cargo audit, load-flag and payload checks, optional signing)"`

---

### Task 14: PowerShell 설치 스크립트 은퇴와 Python 에이전트 정리

**Files:**
- Delete: `install/install.ps1`, `install/uninstall.ps1`, `install/audit-policy.ps1`, `install/LAYOUT`, `server/tests/test_install_scripts.py`
- Modify: `install/build.ps1`(설치 스크립트·`LAYOUT`·`mcp-agent` 언급이 남아 있으면 제거), `agent/mcp_agent/__init__.py`(모듈 docstring: "Development and test agent (Plan 6 Y7): the shipped agent is `mcp-monitor.exe agent`. Keep `/api/agent/*` behaviour identical to `desktop/src/agent`."), `agent/pyproject.toml`(`description = "MCP Monitor session agent (development and tests; ships as mcp-monitor.exe agent)"`), `server/tests/test_desktop_build.py`(아래 테스트 추가)

**Interfaces:**
- Produces: 저장소에 PowerShell 설치기가 없음(Y8). `install/`에는 `build.ps1`(payload)·`build-desktop.ps1`(릴리스)·`pyinstaller/`(`mcp-monitor.spec`, `entry_monitor.py`)만. Python 에이전트 코드는 바꾸지 않습니다(테스트 그대로 통과). 서버의 `bundle.py`는 `runtime` 배치와 `python` 에이전트를 계속 지원합니다(개발 경로, 지워도 이득이 없음).

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# server/tests/test_desktop_build.py (추가)
def test_powershell_installer_is_retired():
    for name in ("install.ps1", "uninstall.ps1", "audit-policy.ps1", "LAYOUT", "pyinstaller/mcp-agent.spec", "pyinstaller/entry_agent.py"):
        assert not (INSTALL / name).exists(), name
    assert not (REPO / "server" / "tests" / "test_install_scripts.py").exists()
    for script in ("build.ps1", "build-desktop.ps1"):
        text = (INSTALL / script).read_text("utf-8-sig")
        assert not re.search(r"install\.ps1|uninstall\.ps1|audit-policy\.ps1|mcp-agent|LAYOUT", text), script
```

- [ ] **Step 2: 실패 확인** — Run(server): `uv run python -m pytest tests/test_desktop_build.py -v` → FAIL

- [ ] **Step 3: 구현** — 파일 삭제와 위 수정. `git grep -n "install\.ps1\|uninstall\.ps1\|audit-policy\.ps1\|mcp-agent\.exe" -- server web agent install desktop` → 문서 밖에는 결과 없음(문서는 Task 15가 고침).

- [ ] **Step 4: 통과 확인** — Run(server): `uv run python -m pytest -q`, `uv run python -m ruff check app tests`, `uv run python -m mypy` → 통과/0건. Run(agent): `uv run python -m pytest -q` → 통과.

- [ ] **Step 5: Commit** — `git commit -m "chore: retire the PowerShell installer (replaced by mcp-monitor.exe install/uninstall/audit-policy); the Python agent stays for development and tests"`

---

### Task 15: 문서(운영 v1.1.0, 실기기 점검표 P8, 스펙 v0.9, carry-forward, README), 최종 검증

**Files:**
- Create: `docs/verification/win11-pro-p8.md`
- Modify: `docs/ops/OPERATIONS.md`, `docs/PLAN.md`, `docs/superpowers/plans/carry-forward.md`, `docs/design/desktop-app-rust.md`(상태 줄에 "Plan 6 구현"), `docs/verification/win11-pro-p4-p5.md`·`win11-pro-p6-p7.md`(`audit-policy.ps1 -Enable` → `mcp-monitor.exe audit-policy --enable`, `install.ps1` → `mcp-monitor.exe install`, `mcp-agent.exe` → `mcp-monitor.exe agent` 안내 한 줄씩; 이미 쓴 결과 칸은 그대로), `README.md`, `desktop/src/cli.rs`(아래 테스트)

- [ ] **Step 1: 실패하는 테스트 작성**

```rust
// desktop/src/cli.rs (tests, added)
#[test]
fn operations_guide_documents_every_cli_option() {
    let guide = std::fs::read_to_string(concat!(env!("CARGO_MANIFEST_DIR"), "/../docs/ops/OPERATIONS.md")).unwrap();
    let missing: Vec<&&str> = DOCUMENTED_OPTIONS.iter().filter(|o| !guide.contains(*o)).collect();
    assert!(missing.is_empty(), "not in docs/ops/OPERATIONS.md: {missing:?}");
    for word in ["install", "uninstall", "audit-policy", "agent", "app", "autostart", "verify-payload", "--version"] {
        assert!(DOCUMENTED_OPTIONS.contains(&word), "{word}");
    }
}
```
`DOCUMENTED_OPTIONS`(Task 4에서 만든 상수): `install`, `uninstall`, `audit-policy`, `agent`, `app`, `autostart`, `verify-payload`, `--version`, `--install-dir`, `--data-root`, `--open-firewall`, `--skip-audit-policy`, `--local-port`, `--external-port`, `--dry-run`, `--interactive`, `--remove-data`, `--restore-audit-policy`, `--enable`, `--restore`, `--background`, `--server`, `--dialog`, `--url-file`, `--unreachable-exit-sec`(`--server-url`은 개발 기능이라 제외).

- [ ] **Step 2: 실패 확인** — Run: `cargo test --locked operations_guide` → FAIL

- [ ] **Step 3: 운영 문서 `docs/ops/OPERATIONS.md` → v1.1.0** — 절 구성은 그대로(①–⑩), 내용 변경:
  - ① 구성: 설치 폴더 구성(부록 B 표: `mcp-monitor.exe`, `bin\monitor\mcp-monitor-server.exe`, `web\`, `docs\`, `bundle.json`, `install.json`), 실행 모드 5개(app/install/uninstall/audit-policy/agent), 세션마다 `mcp-monitor.exe agent`(사용자 권한), 사용자별 WebView2 프로필 `%LOCALAPPDATA%\mcp-monitor\{webview,notice-webview}`.
  - ② 설치: 더블클릭 → 안내 → UAC → 설치 → 앱 창. 명령줄 표(모든 옵션 — 위 테스트), PowerShell에서 결과를 기다리는 형태 `& .\mcp-monitor-1.1.0.exe install --dry-run | Write-Output`와 `$LASTEXITCODE`, 서명 없음과 SAC(D5, P8-1), WebView2 런타임 확인.
  - ③ 업그레이드: 새 exe 실행 → 업그레이드 안내(또는 `install --interactive`), 순서(스테이징 → 서비스 정지 → 세션의 앱·에이전트 종료 → 폴더 교체 → 서비스 시작 → `.old` 삭제), 포트·방화벽은 이전 값 유지, 다운그레이드 거부, 서비스 시작 뒤 실패하면 `<I>.old`가 남는 이유(DB가 이미 새 버전일 수 있음)와 복구 절차, 1.0.0(PowerShell 설치)에서 올라오기, 다른 세션 트레이는 다음 로그인 때 다시 뜸.
  - ④ 제거: 앱 및 기능 또는 `uninstall`, `--remove-data`·`--restore-audit-policy`, 실행 중인 exe는 다시 시작할 때 지워짐, 로그온하지 않은 사용자의 HKCU `Run` 값은 남을 수 있음(Y20, 무해: 대상 exe가 없으면 아무것도 실행되지 않음), 1.0.0 설치는 이 exe의 `uninstall`로 지움.
  - ⑤ 서비스 운영: binPath의 새 서버 exe 이름, 나머지 그대로.
  - ⑧ 보안: 앱 창은 `127.0.0.1:<LP>`만, 다른 주소는 기본 브라우저, 개발자 도구 없음, `WEBVIEW2_*` 환경 변수 무시, 고지 토큰은 명령줄에 없음, 승격은 설치·업그레이드·제거·감사 정책 때만, DLL은 System32에서만.
  - ⑨ 알려진 동작: 고지 창은 다른 앱의 입력을 막지 않음(최상위·닫기 없음·작업 표시줄 없음; Windows가 프로세스 사이의 진짜 모달을 허용하지 않음, Y10), WebView2가 없으면 고지는 기본 브라우저로 열림.
  - ⑩ 문제 해결: `[실패] stage_payload`(payload 손상·개발용), `[실패] swap_install_dir`(파일 잠금 — 열린 탐색기 창·바이러스 검사), `[실패] stop_apps`, SAC 차단, WebView2 없음, 트레이가 안 보임, 업그레이드 뒤 서비스가 5로 끝남(더 새 DB).

- [ ] **Step 4: 실기기 점검표 `docs/verification/win11-pro-p8.md`** — 형식은 `win11-pro-p6-p7.md`와 같음(대상·작성·자동 테스트가 확인한 것·결과 채우는 법·준비·항목 표), **모든 결과 칸 `대기`**(Y26). 준비: 깨끗한 Win 11 Pro VM(스냅숏), SAC 상태 기록(가능하면 켜짐), 관리자 1명, RDP용 표준 사용자 `hong`·`kim`, `dist\mcp-monitor-1.1.0.exe`와 `.sha256` 확인, (P8-11용) 1.0.0 묶음 zip(커밋 c9938d1에서 빌드). 항목(절차 / 기대 / 결과 / 비고):
  - P8-1 SAC 켜짐에서 다운로드 폴더의 서명 없는 exe를 `--version`·더블클릭 → 막히지 않음, `CodeIntegrity/Operational`에 차단 없음(막히면 carry-forward: 인증서 또는 1.0.0 방식으로 되돌리기, D5)
  - P8-2 표준 사용자로 더블클릭 → 설치 안내 → UAC(관리자 자격 증명) → 진행 → "설치 완료" → 앱 창이 `/admin/setup`; 첫 Admin 생성
  - P8-3 관리자 PowerShell `install --open-firewall | Write-Output` → 모든 단계, 재부팅 → 로그인 없이 서비스 RUNNING, 다른 PC에서 8701 보드
  - P8-4 `icacls` 데이터 루트(P7-4와 같은 기대), `icacls "C:\Program Files\MCP Monitor" /T`에 사용자 쓰기 권한 없음
  - P8-5 앱 및 기능 항목(이름·버전·게시자·크기·아이콘), 시작 메뉴 "MCP Monitor"(모든 사용자), 앱 및 기능에서 제거 → UAC → 제거
  - P8-6 `hong` RDP 접속 → 2초 안 고지 창: 화면 가운데 640×600, 최상위, 닫기 단추 비활성, Alt+F4 무시, 작업 표시줄에 없음, Tab으로 '확인'에 초점, Enter로 확인 → 창 닫힘, `notice_shown`·`notice_acknowledged`
  - P8-7 `hong`·`kim` 동시 접속 → 각자 자기 고지만, 다른 세션 화면에는 없음; 콘솔 관리자 세션에는 고지 없음; 재연결마다 다시 표시
  - P8-8 고지가 열린 채 작업 관리자에서 `msedgewebview2.exe`(그 세션) 끝내기 → 약 1–2초 뒤 다시 표시; `mcp-monitor.exe agent` 끝내기 → 재시작·다시 표시, `tamper agent_exited`
  - P8-9 서비스를 멈추고 8700을 다른 프로세스가 점유(`127.0.0.1`, `0.0.0.0` 각각) → 에이전트 종료 코드 5, 창 없음(P5-5b와 같음)
  - P8-10 `hong`이 메모장·PowerShell 사용 → `activity.window`(제목에 고지 토큰 없음), 5분 유휴 → `activity.idle`
  - P8-11 1.0.0(PowerShell 설치) PC에서 1.1.0 exe 실행 → 업그레이드 안내 → 데이터·설정·스크립트·감사 백업 유지, `bin\agent` 사라짐, `sc.exe qc`의 새 binPath, 세션 에이전트가 `mcp-monitor.exe agent`; 이어서 버전을 1.1.1로 올려 빌드한 exe로 `hong` 세션에 트레이와 고지가 열린 채 업그레이드 → 성공, `.old` 없음
  - P8-12 1.1.1 설치본에 1.1.0 exe 실행 → "더 새롭습니다" 안내 후 앱 창; `install` 명령 → 종료 2(다운그레이드 거부)
  - P8-13 `uninstall` → 데이터 유지; 재설치 후 `uninstall --remove-data --restore-audit-policy` → 데이터·`C:\Users\*\AppData\Local\mcp-monitor` 삭제, 감사 정책·레지스트리 원복, 재부팅 뒤 설치 폴더 완전히 사라짐
  - P8-14 트레이: 창 닫기 → 트레이, "서비스: 실행 중/중지됨", "로그인할 때 트레이 시작" → `HKCU\…\Run\MCPMonitor`, 로그아웃·로그인 → 창 없이 트레이
  - P8-15 앱 창에서 외부 링크(예: 관리 화면의 문서 링크, 없으면 개발 빌드의 `window.location = "https://example.com"` 대신 `notice` 미리보기의 링크) → 기본 브라우저; F12·Ctrl+Shift+I·오른쪽 클릭 "검사" 없음
  - P8-16 앱 창이 열린 채 시작 메뉴에서 다시 실행 → 새 창 없이 기존 창이 앞으로
  - P8-17 (선택) Process Monitor로 다운로드 폴더에서 승격 실행할 때 그 폴더에서 DLL을 찾지 않음(`NAME NOT FOUND`가 System32 밖에 없음)
  - P8-18 `--external-port 9701`로 다시 설치 → 방화벽 규칙이 `MCP Monitor (9701)` 하나만(이전 8701 규칙 삭제)
  - P8-19 데이터 루트 공격 재현(P7-11·P7-13과 같은 절차를 `mcp-monitor.exe install`로) → 종료 2, 아무것도 바뀌지 않음
  - P8-20 그리고 `win11-pro-p4-p5.md`·`win11-pro-p6-p7.md`를 **데스크톱 설치 상태로** 다시 수행한다는 안내.

- [ ] **Step 5: 스펙·설계·carry-forward·README**
  - `docs/PLAN.md`: 버전 v0.9, 변경 이력 한 행: `v0.9 | Plan 6 데스크톱 앱(설계 docs/design/desktop-app-rust.md, D2–D5): Rust(Tauri 2.12.5) 단일 실행 파일 mcp-monitor.exe — PyInstaller 서버 묶음을 zstd tar로 내장(파일별 SHA-256), 모드 app(127.0.0.1:<LP>만 여는 WebView2 창·트레이·단일 인스턴스·HKCU Run 선택)/install/uninstall/audit-policy(install.ps1·uninstall.ps1·audit-policy.ps1의 규칙을 Rust로 이식, --dry-run, 스테이징 후 폴더 교체 업그레이드, 다운그레이드 거부, 앱 및 기능·시작 메뉴, 설치 폴더 ACL 검사)/agent(Rust 세션 에이전트, 같은 /api/agent/* 규약, 최상위 모달 WebView2 고지 창 — Plan 4 V3 대체 해소), 서버 exe 이름 mcp-monitor-server.exe, bundle.json agent: desktop, --agent-dialog webview, PowerShell 설치기 은퇴, Python 에이전트는 개발·테스트용, 서명은 선택 단계(인증서 없음), 버전 1.1.0`. §5.5 "형태" 문장을 "화면 중앙의 최상위 창(WebView2, 닫기 단추 없음·작업 표시줄 없음·확인 전에는 닫히지 않음)…"으로. §9.2 스택 표에 "데스크톱 셸·설치기·에이전트: Rust 1.99.1 + Tauri 2.12.5(WebView2)" 행. §10 디렉터리 구조에 `desktop/`(src/{cli,payload,install,agent,app}, tests, ui, icons), `install/build-desktop.ps1`. 상태 줄에 "P8(데스크톱) 구현 완료(실기기 확인 대기: win11-pro-p8.md)".
  - `docs/design/desktop-app-rust.md`: 상태 줄 끝에 ` — Plan 6로 구현(2026-11-07, 부록 A Y1–Y34)`. 본문 §3의 "서명됨"을 "서명 선택(D5)"으로, §4.1 패키지 형태 줄의 B를 지움(D2=A).
  - `carry-forward.md`: "True modal notice window" 두 곳(Product 목록, Plan 4 Later)에 체크 + `(Plan 6 Task 11, Y10)`; "A reinstall with a different `-ExternalPort` …"에 체크 + `(Plan 6 Task 6 firewall_delete_old)`; "Code signing" 문구를 `mcp-monitor.exe`와 내장 `mcp-monitor-server.exe`로 고치고 `(Plan 6 Task 13: 선택 단계 -SignThumbprint, 인증서 없음 — 열림)`. 새 절 "After Plan 6 (추후)": 코드 서명 인증서(D5); `win11-pro-p8.md`의 `대기` 전체(P8-1–P8-20); 로그온하지 않은 사용자의 HKCU `Run` 정리(Y20); WebView2 없을 때 고지가 기본 브라우저(토큰이 명령줄에 남음 — 서버 가림으로만 보호, Y33); 실기기 통과 뒤 Python 에이전트 은퇴 검토(Y7); MSI(D2 B — GPO·Intune가 필요할 때); 창 이벤트 같은 연결 증명(R2, Y22).
  - `README.md`: 빠른 시작을 "`install\build-desktop.ps1` → `dist\mcp-monitor-1.1.0.exe` 실행"으로, 구조도·라이브러리 표에 `desktop/`(Rust·Tauri·주요 크레이트), 개발 경로(`uv run python -m app` + Python 에이전트)는 그대로.

- [ ] **Step 6: 전체 검증**

  Run (desktop): `cargo fmt --check` → 0. `cargo clippy --locked --all-targets -- -D warnings` → 0. `cargo clippy --locked --all-targets --features dev -- -D warnings` → 0. `cargo test --locked` → 통과. `cargo test --locked --test agent_webview -- --ignored` → 통과. `cargo test --locked --features dev --test app_window -- --ignored` → 통과. `cargo audit` → 취약점 0. `cargo tree -d -e normal` → `windows`·`webview2-com`·`tauri-utils` 중복 없음.
  Run (release): `powershell -NoProfile -ExecutionPolicy Bypass -File install\build-desktop.ps1` → done.
  Run (server): `uv run python -m pytest -q` → 통과. `-m integration` → 통과(`MCPMON_DESKTOP_EXE` = 릴리스 exe, `[desktop]` 포함). `-m winlive` → 통과. `-m perf` → 통과. `-m bundle`(`MCPMON_BUNDLE=<repo>\dist\payload`) → 통과. `-m desktop`(`MCPMON_DESKTOP_EXE`) → 통과. `uv run python -m ruff check app tests` → 0. `uv run python -m mypy` → 0. `uv run python -m pip_audit` → 0.
  Run (agent): `uv run python -m pytest -q` → 통과. Run (dummy-mcps): `uv run python -m pytest -q` → 통과.
  Run (web): `pnpm typecheck` → 0 errors. `pnpm lint` → 0 problems. `pnpm test` → 통과. `pnpm build` → 성공. `pnpm test:budget` → 통과. `pnpm e2e` → 통과. `pnpm audit` → `No known vulnerabilities found`.
  그 뒤 원장 관리자(controller)가 계획 전체 리뷰 한 번 + 수정 한 번을 합니다(사용자 지시).

- [ ] **Step 7: Commit** — `git commit -m "docs: operations guide 1.1.0 (desktop app), Win 11 Pro P8 checklist, spec v0.9 and carry-forward after Plan 6"`

---

## 부록 A: 결정 사항 (이 계획의 Ruling Y1–Y34)

| # | 결정 | 이유 | 틀렸을 때 비용 |
|---|---|---|---|
| Y1 | `feat/plan6-desktop-app`(main 1ef47f0)에서 작업. 문서와 코드의 이름이 다르면 코드를 따르고 이름 대응을 보고. | Plan 5까지와 같은 규칙. | 이름 맞추기. |
| Y2 | 툴체인: rustup 1.29.3(winget `Rustlang.Rustup`), Rust **1.99.1**(2026-10-13, 2026-11-07 기준 최신 stable — `static.rust-lang.org/dist/channel-rust-stable.toml`로 확인)을 `desktop/rust-toolchain.toml`에 고정, VS Build Tools 2026(`Microsoft.VisualStudio.Workload.VCTools` + 권장 구성 요소 = MSVC x64 + Windows 11 SDK). UAC가 필요하므로 **사용자가** 설치, 구현자는 확인만. tauri-cli는 쓰지 않음(번들러 불필요: MSI 없음 D2, `tauri-build`가 build.rs에서 리소스·매니페스트를 넣음). SAC·앱 제어가 cargo·빌드 스크립트·테스트 exe·cargo-audit를 막으면 멈춤. | 사용자 환경 사실. 1.99.1 이상의 기능은 쓰지 않음. | 막히면 이 계획 전체가 멈춤(Task 1 스파이크에서 가장 먼저 드러남) → 서명·예외 정책 결정 필요. |
| Y3 | 크레이트(정확 고정, 2026-11-07 crates.io 인덱스의 최신 안정판): tauri 2.12.5(`tray-icon`, `image-ico`), tauri-build 2.7.4, tauri-plugin-single-instance 2.5.5, windows 0.62.2, webview2-com 0.39.1, ureq 3.5.1(기본 기능 끔 — TLS 없음), serde 1.0.229, serde_json 1.0.154, sha2 0.11.1, hmac 0.13.0, hex 0.4.3, getrandom 0.4.3, zstd 0.13.4, tar 0.4.46, time 0.3.55, regex 1.13.1, walkdir 2.5.0(빌드), tempfile 3.27.0(테스트). `Cargo.lock` 커밋, 모든 명령 `--locked`. `windows`·`webview2-com`·`tauri-utils`는 tauri가 쓰는 버전 하나로(다르면 tauri 쪽에 맞추고 보고). 기능 추가는 자유, 새 크레이트는 Ruling. 고르지 않은 것: clap(CLI가 작아 손 해석기), reqwest(tokio·TLS 끌고 옴), chrono(time으로 충분), ruzstd(빌드 쪽 압축기 없음), wry/tao 직접(트레이·단일 인스턴스를 다시 만들어야 함), windows-sys(COM `IShellLinkW`·WebView2 설정에 `windows`가 필요). | 공급망 최소화와 재현 가능한 빌드(spec §9.1). | 버전 충돌이면 Task 1에서 tauri에 맞춰 조정(작음). |
| Y4 | 새 개발 도구 cargo-audit **0.22.2**(`cargo install cargo-audit --version 0.22.2 --locked`). `build-desktop.ps1`에서 0이 아니면 실패(취약점), 경고(unmaintained 등)는 보고서에 목록. 권고를 무시하려면 Ruling + `desktop/audit.toml`에 이유. | spec §9.1 "보안 이슈 없는" 의존성; pip-audit·pnpm audit와 같은 위치. | 빌드 때 RustSec DB를 받아야 함(네트워크); SAC가 막으면 멈춤. |
| Y5 | 제품 버전 1.1.0(서버·웹·desktop). Python 에이전트는 1.0.0 그대로. | 새 배포 형태의 첫 릴리스. 개발 에이전트는 배포되지 않음. | 없음. |
| Y6 | 설치 폴더 하나: `mcp-monitor.exe`(설치기가 자신을 복사), `bundle.json`(`agent: "desktop"`), `install.json`(사용자도 읽는 포트·데이터 루트), `bin\monitor\mcp-monitor-server.exe`(이름 변경 — 같은 이름의 exe 두 개를 피함), `web\`, `docs\OPERATIONS.md`. `bin\agent`·`install\` 없음. | 설계 §3. 앱 모드(일반 사용자)가 관리자만 읽는 데이터 루트 없이 포트를 알아야 함. | 이름을 바꾸면 서비스 binPath·테스트를 함께 고침. |
| Y7 | Python 에이전트는 **개발·테스트용으로 유지**(배포하지 않음, 기능 동결, 고칠 때는 Rust와 함께). 서버의 `edge`/`print` 고지와 `runtime` 배치도 유지. | 개발 서버·웹 E2E·서버 통합 테스트가 Rust 툴체인 없이 `python -m mcp_agent --dialog print`로 돎. 규약 일치는 공유 픽스처(`agent-events.json`), HMAC 벡터, 같은 통합 시나리오를 두 에이전트로 돌려 지킴(Task 11). | 두 구현이 어긋날 위험 — 통합 테스트가 잡음. 실기기 P8 통과 뒤 은퇴 검토(carry-forward). |
| Y8 | PowerShell 설치 스크립트(`install.ps1`·`uninstall.ps1`·`audit-policy.ps1`)는 Rust 이식이 초록이 된 뒤 **삭제**(Task 14). `build.ps1`은 payload 빌더로 남고 `build-desktop.ps1`이 릴리스를 만듦. | 보안이 걸린 ACL·경로 규칙을 두 언어로 유지하면 갈라짐. 개발 PC는 설치하지 않음. 실기기에서 Rust exe가 막히면 커밋 c9938d1의 1.0.0 묶음(PowerShell 설치)으로 돌아감. | 되살려야 하면 git 기록에서 복원(코드 작성 없음). |
| Y9 | 고지 토큰 전달: 지금처럼 `/notice#d=<id>&t=<token>`. 호스트가 **WebView2 API로 탐색**(명령줄에 없음), 창 제목은 호스트가 고정(`MCP Monitor 고지`, 페이지 제목을 따르지 않음), InPrivate(`incognito`)라 기록 없음, 에이전트도 창 제목에서 토큰을 가림. 웹은 바꾸지 않음. `window.chrome.webview` 메시지 방식은 채택하지 않음. | 토큰이 새던 두 길(Edge 명령줄, 로딩 중 창 제목)이 WebView2 호스트에서는 구조적으로 없어짐. 메시지 방식은 웹 변경 + 두 경로(개발 에이전트는 여전히 해시) + 페이지 준비 타이밍 처리가 필요. | WebView2가 다른 경로로 URL을 노출한다는 것이 드러나면 메시지 방식으로 전환(웹 `source.ts` + 호스트, 중간 규모). |
| Y10 | 고지 창 = Tauri 창: 최상위, 닫기 단추 비활성, 최소화·최대화·크기 조절 없음, 작업 표시줄 없음, 640×600(작업 영역에 맞춤) 가운데, 컨텍스트 메뉴·개발자 도구·브라우저 단축키 끔, 새 창 거부, `/notice`만 탐색. `CloseRequested`는 우리가 닫을 때만 허용(Alt+F4·`WM_CLOSE` 무시). 2초마다 최상위를 다시 걸되 초점은 빼앗지 않음, 처음에 한 번 전경 시도(실패하면 깜빡임). WebView2 프로세스가 죽으면 "사용자가 닫음"으로 보고해 서버가 다시 보냄. WebView2를 만들 수 없으면 기본 브라우저(V25와 같음). "모달"은 확인 전에는 닫히지 않고 항상 위에 보이는 창을 뜻함(Windows는 다른 프로세스의 입력을 막는 모달을 허용하지 않음). | spec §5.5, 설계 D3=A, carry-forward "true modal". | 실기기에서 다른 최상위 창에 가려지거나 전경을 못 얻으면 타이머·전경 처리 조정(작음). |
| Y11 | 앱 창: `http://127.0.0.1:<LP>`와 연결 중 페이지(`http://tauri.localhost`)만 Allow, 그 밖의 http(s)는 기본 브라우저, 사용자 정보가 있는 URL·다른 스킴은 차단, 새 창도 같은 규칙(새 창은 만들지 않음). 데이터 폴더 `%LOCALAPPDATA%\mcp-monitor\webview`(로그인 쿠키 유지), 개발자 도구 끔, 닫으면 트레이로. 단일 인스턴스는 **app 모드에만**(에이전트·설치기는 여러 개 가능). 원격 주소에 Tauri IPC 권한 없음(capability 없음). | 설계 §6, S3(관리 화면은 로컬 채널만). | 관리 화면이 다른 로컬 주소를 써야 하면 표에 추가. |
| Y12 | 모드 판별: 앱 및 기능 `MCPMonitor`의 `DisplayVersion`(없으면 `<I>\bundle.json` — 1.0.0) + 서비스 존재. 서비스 없음 → 설치 안내, 설치본이 낮음·모름 → 업그레이드 안내, 같음 → 앱, 높음 → 안내 후 앱. 안내는 메시지 상자(설치 전에 웹 UI 없음). | 설계 §3 "실행 방식 판별". | 문구 조정. |
| Y13 | 승격: 매니페스트 `asInvoker`(tauri-build 기본). `--interactive`인 설치·제거·감사 정책만 `ShellExecuteExW("runas")`로 **같은 exe**를 다시 실행하며, 인자는 해석한 옵션에서 다시 만들고 `--dry-run`은 넘기지 않음. 그 밖에 관리자가 아니면 계획의 첫 단계가 안내 후 1. 승격된 프로세스는 검사를 모두 다시 하고, 호출자가 고른 보고 파일 같은 임의 경로에 쓰지 않음(결과는 메시지 상자). 정적 import DLL은 System32에서만(`/DEPENDENTLOADFLAG:0x800`), 시작 직후 `SetDefaultDllDirectories(LOAD_LIBRARY_SEARCH_SYSTEM32)`(스파이크가 실패를 보이면 DEFAULT_DIRS). 정적 CRT. GUI 서브시스템 + 부모 콘솔에 붙기(PowerShell에서는 `| Write-Output`으로 기다림). | 다운로드 폴더에서 승격 실행할 때 DLL 심기를 막고, 표준 사용자가 관리자의 승격을 다른 쓰기에 쓰지 못하게 함. 에이전트는 서비스가 띄우므로 콘솔 창이 뜨면 안 됨. | CLI 사용이 조금 불편(문서화). WebView2가 SYSTEM32 제한에서 실패하면 DEFAULT_DIRS(앱 폴더 포함)로 약해짐 — 스파이크 결과로 결정. |
| Y14 | payload: `build.ps1` 출력 폴더를 build.rs가 결정적 tar(파일만, 정렬, mtime 0, 0o644) + zstd 19로 묶고 파일별 SHA-256 매니페스트와 전체 SHA-256을 함께 내장. 설치는 전체 해시 → 파일마다 크기·해시, 정규 파일만, 매니페스트 밖 이름·`..`·절대·링크·중복 거부, 새 폴더(`<I>.staging`, 마커)에만. `MCPMON_PAYLOAD_DIR` 없이 빌드하면 fixture payload(작은 가짜)이고 실제 설치를 거부. 릴리스 빌드는 배치·버전을 검사. | 설계 §6 "해시 검증, 공유 %TEMP%에 실행 파일을 두지 않음". | exe가 커짐(약 40–60MB, 설계 예상 범위). |
| Y15 | 업그레이드: 스테이징(서비스 동작 중) → 서비스 정지(60초) → 설치 폴더 안 이미지의 프로세스 종료(세션 트레이·남은 에이전트, 5초) → `<I>`→`<I>.old`, 스테이징→`<I>`(실패하면 되돌림) → 설치 폴더 트리 ACL 검사(관리자 아닌 계정의 쓰기·삭제·권한 변경이 있으면 되돌리고 실패 — Plan 5는 경고만, SYSTEM이 실행하는 폴더이므로 강화) → … → 서비스 시작 → 응답 확인 → `.old` 삭제. **서비스 시작 뒤에는 자동으로 되돌리지 않음**(DB가 이미 올라갔을 수 있음, Plan 5 DB 가드). 다운그레이드 거부(같은 버전은 복구). 옵션이 없으면 이전 포트·방화벽을 그대로. 설치 폴더의 상위 폴더에도 데이터 루트와 같은 `ancestor_problem`. | 설계 §4.2. 실행 중인 exe가 폴더 이름 바꾸기를 막으므로 먼저 끝냄. | 실패한 업그레이드가 `<I>.old`를 남김(운영 문서의 복구 절차). |
| Y16 | 서비스 binPath = `"<I>\bin\monitor\mcp-monitor-server.exe" service --root "<D>" --local-port LP --external-port EP`; 나머지(지연 자동, LocalSystem, 실패 동작, failureflag, 설명)는 Plan 5와 같음. 서버는 `bundle.json`의 `agent: "desktop"`을 보고 `<I>\mcp-monitor.exe agent --server … --dialog webview`를 세션마다 띄움(`--agent-dialog` 기본값도 webview). | 서버 코드 변경을 최소로(D4). | 없음. |
| Y17 | 설치 계획 JSON은 Plan 5와 같은 모양, 같은 단계 id·인자(동작이 같은 단계). 바뀐 것: `copy_bundle`(robocopy) → `stage_payload`·`stop_apps`·`swap_install_dir`, 추가 `firewall_delete_old`·`install_info`·`uninstall_entry`·`start_menu_shortcut`·`cleanup_old`; `install-state.json`에 `installer`·`skip_audit_policy` 추가. 1.0.0의 `install-state.json`을 그대로 읽음. | 실기기 점검표와 운영 문서의 연속성, 1.0.0에서의 업그레이드. | 없음. |
| Y18 | ACL·경로 규칙은 PowerShell 함수와 **같은 규칙**을 Win32(`GetNamedSecurityInfoW`/`SetNamedSecurityInfoW`/SDDL로 만든 SD의 `CreateDirectoryW`)로 이식하고 같은 시나리오를 `%LOCALAPPDATA%` 임시 폴더에서 관리자 없이 테스트(현재 사용자가 Administrators 대신 소유자). 규칙 판단(`untrusted_rule`)은 ACE 목록을 받는 순수 함수. | 이식 동등성이 이 계획의 가장 큰 보안 위험(Review Focus 8). | 실기기에서만 드러나는 차이(관리자 소유자, TrustedInstaller) — P8-4·P8-19. |
| Y19 | 앱 및 기능: `HKLM\…\Uninstall\MCPMonitor`(이름·버전·게시자·위치·아이콘·`UninstallString`=`uninstall --interactive`·`QuietUninstallString`=`uninstall`·NoModify·NoRepair·EstimatedSize). 시작 메뉴: 모든 사용자 `%ProgramData%\Microsoft\Windows\Start Menu\Programs\MCP Monitor.lnk`. | 설계 §4.1. | 없음. |
| Y20 | HKCU `Run`(`MCPMonitor` = `"<I>\mcp-monitor.exe" app --background`)은 **앱 모드(그 사용자)만** 씀(트레이 체크·`autostart on|off`). 승격된 설치기는 다른 계정일 수 있어 HKCU를 쓰지 않음. 제거는 로드된 하이브(`HKU\S-1-5-21-*`)에서 우리 exe를 가리키는 값만 지움; 로그온하지 않은 사용자의 값은 남을 수 있음(대상 exe가 없으면 무해, 문서화). | 설계 §4.1 "선택". | 남은 값이 "시작 앱" 목록에 보임(무해). |
| Y21 | 제거는 실행 중인 자신을 `mcp-monitor.exe.uninstalled`로 바꾸고 나머지를 지운 뒤 그 파일과 폴더를 `MOVEFILE_DELAY_UNTIL_REBOOT`로 예약. 공유 %TEMP%로 자신을 복사하지 않음. `--remove-data`면 데이터 루트(마커 확인)와 `<Users>\*\AppData\Local\mcp-monitor`(Edge·WebView2 프로필 모두). | 설계 §6, Plan 5 W31. | 재부팅 전까지 파일 하나가 남음(관리자만 쓰는 위치). |
| Y22 | Rust 에이전트는 Python과 같은 숫자·종료 코드·규칙(백오프, 25/2초 폴링, 하트비트, 합치기 0.3/1.0/0.3초, 제목 기억 256, 버퍼 2000, 묶음 200, 이미지 캐시 30초/512, 512/260자, `dropped`, `verified_only`, 유휴 확인 `IDLE_EVERY_SEC = 5.0`초). 홀로 있는 서로게이트는 `?`(Python과 같음). 창 제목의 고지 토큰을 에이전트에서도 가림(추가 방어). 같은 연결 증명(R2)은 닫지 않음. 의도한 차이(F11): 고지 창이 에이전트 프로세스 안에 있어 `WINEVENT_SKIPOWNPROCESS`로 그 창의 창 이벤트는 남지 않음(Python 때는 `msedge.exe`로 남음) — `notice_shown`·`notice_acknowledged`가 대신하고 운영 문서 ⑨에 적음(Task 15). | 서버 규약 그대로(D3 "서버는 바뀌지 않음"). | 차이가 생기면 통합 테스트·픽스처 테스트가 잡음. |
| Y23 | 테스트: `cargo test`는 관리자 없이, 이 PC의 서비스·HKLM·감사 정책·방화벽·Program Files를 건드리지 않음(가짜 `Host`·`Executor`·`Registry`, 임시 폴더). HKCU도 쓰지 않음(`FakeRegistry`). 실제 WebView2 창 테스트는 `#[ignore]`이고 Task 11·12·15의 지정 단계에서 이 PC 화면으로 실행. 테스트 진입점은 승격된 셸이면 실패. | Global Constraints, Plan 5 W38과 같은 원칙. | 실기기 전용 문제는 P8 점검표에서. |
| Y24 | `dev` 기능: `app --server-url`과 `WEBVIEW2_*` 환경 변수 유지(CDP E2E). 릴리스는 기능 없이 빌드(`build-desktop.ps1` 고정 + `--version`에 `dev` 없음 검사). 그 밖의 빌드에서는 앱·에이전트가 시작할 때 `WEBVIEW2_*`를 지움(사용자 환경 변수로 원격 디버깅·다른 런타임을 켜지 못하게). | E2E는 필요하지만 배포본에 디버깅 경로가 있으면 안 됨. | E2E가 dev 빌드에만 있음. |
| Y25 | 서명은 `build-desktop.ps1 -SignThumbprint <SHA1> -TimestampUrl <url>`일 때만(내장 서버 exe는 묶기 전에, 최종 exe는 마지막에, `signtool verify /pa`). 기본은 꺼짐. | D5(인증서 없음). | 인증서가 생기면 명령 한 줄. |
| Y26 | 실기기 항목은 `docs/verification/win11-pro-p8.md`, 모든 결과 `대기`. P4–P7 점검표는 데스크톱 설치로 다시 수행. | 개발 PC가 Home·비관리자(Plan 5 W38과 같음). | 실기기에서만 드러나는 문제는 그때 고침. |
| Y27 | 웹은 변경 없음(고지 페이지 포함). 웹 검사 7종이 그대로 통과. | Y9. | 없음. |
| Y28 | 문서: PLAN v0.9, OPERATIONS v1.1.0(모든 CLI 옵션 — Rust 테스트로 고정), README, 설계 문서 상태 줄. | 운영자가 exe 하나로 설치·제거·문제 해결. | 없음. |
| Y29 | 종료 코드: 0 성공, 1 실패·관리자 아님·UAC 거절, 2 인자 오류(설치 계열), 에이전트 0/2/3/4/5(Python과 같음), app 모드 0(트레이 종료). | Plan 5 W23·Plan 4 규약과 같음. | 없음. |
| Y30 | 창 크기: 앱 창 기본 1280×800, 최소 640×600; 연결 중 페이지는 640px에서 가로 스크롤 없음; 고지 창 640×600(작업 영역 − 32px, 최소 320×300). | 사용자 지시(640×600까지). | 레이아웃 조정. |
| Y31 | 자동 업데이트 없음, 런타임 외부 네트워크 없음(ureq는 127.0.0.1만, 프록시 무시). WebView2 Evergreen 런타임 자체의 업데이트는 Windows가 관리(우리 범위 밖, 문서화). | 설계 §6, S4. | 없음. |
| Y32 | carry-forward: "true modal"(두 곳)과 "다른 외부 포트로 재설치 시 방화벽 규칙" 닫음, 코드 서명은 부분(단계만), R2·실기기 항목은 유지, "After Plan 6" 절 신설. | 위 표. | 없음. |
| Y33 | `check_os`가 Home·Program Files 밖·WebView2 런타임 없음을 경고(설치는 계속). 앱 모드는 WebView2가 없으면 오류 상자, 에이전트는 기본 브라우저로 고지(토큰이 명령줄에 남음 — 서버 로그 가림으로만 보호, carry-forward). | Win 11에는 Evergreen이 기본이지만 제거될 수 있음. | 드문 PC에서 고지 품질이 낮아짐. |
| Y34 | `verify-payload <빈 폴더>` 명령: 관리자 없이 내장 payload를 검증·추출(빌드 검사와 `-m desktop` 테스트가 씀). 비어 있지 않은 폴더는 거부. | 내장 서버 exe가 실제로 도는지를 설치 없이 확인. | 표면이 하나 늘어남(쓰기는 지정한 빈 폴더에만). |

## 부록 B: 대응표

**CLI (`mcp-monitor.exe`)**
| 명령 | 옵션 | 동작 | 승격 | 종료 코드 |
|---|---|---|---|---|
| (인자 없음) | | 모드 판별(Y12): 설치·업그레이드 안내 → `install --interactive` 승격 → 앱 / 앱 | 안내에서 예일 때 | 0, 1 |
| `app` | `--background`, (dev) `--server-url <url>` | WebView2 창·트레이(단일 인스턴스) | 없음 | 0, 1 |
| `install` | `--install-dir`, `--data-root`, `--open-firewall`, `--skip-audit-policy`, `--local-port`, `--external-port`, `--dry-run`, `--interactive` | 설치·업그레이드 계획 → 출력 또는 실행 | `--interactive`면 재실행, 아니면 관리자 필요 | 0, 1, 2 |
| `uninstall` | `--install-dir`, `--data-root`, `--remove-data`, `--restore-audit-policy`, `--dry-run`, `--interactive` | 제거 계획 | 같음 | 0, 1, 2 |
| `audit-policy` | `--enable` \| `--restore <file>`, `--data-root`, `--dry-run`, `--interactive` | 감사 정책만 켜기·되돌리기 | 같음 | 0, 1, 2 |
| `agent` | `--server <url>`, `--dialog webview|print`, `--url-file`, `--unreachable-exit-sec` | 세션 에이전트(서비스가 띄움; 환경 변수 `MCPMON_AGENT_TOKEN`, `MCPMON_AGENT_SERVER_KEY`) | 없음 | 0, 2, 3, 4, 5 |
| `autostart` | `on` \| `off` | HKCU `Run\MCPMonitor` | 없음 | 0, 1, 2 |
| `verify-payload` | `<빈 폴더>` | 내장 payload 검증·추출 | 없음 | 0, 1, 2 |
| `--version` | | `mcp-monitor <ver> (payload <12 hex>, release|fixture[, dev])` | 없음 | 0 |

**설치 결과물**
| 위치 | 내용 | 권한 |
|---|---|---|
| `%ProgramFiles%\MCP Monitor\` | `mcp-monitor.exe`, `bundle.json` `{layout: "pyinstaller", version, python, built_at, commit, agent: "desktop"}`, `install.json` `{version, local_port, external_port, data_root}`, `bin\monitor\mcp-monitor-server.exe`(+ `_internal\`), `web\`, `docs\OPERATIONS.md` | Program Files 상속(사용자 읽기·실행), 트리 검사(Y15) |
| `%ProgramFiles%\MCP Monitor.staging` / `.old` | 업그레이드 중에만(마커 `.mcp-monitor-staging` / `bundle.json`) | 같음 |
| `%ProgramData%\MCP Monitor\` | `logs\`, `data\`(`config.db`, `index.db`, `install-state.json`, `mcp-monitor-data-root.json`, `auditpol-backup.csv`, `audit-policy-state.json`, `collector-state.json`, `tamper-baseline.json`, `.lock`), `scripts\` | SYSTEM + Administrators만, 상속 없음, 소유자 Administrators |
| `%LOCALAPPDATA%\mcp-monitor\webview` | 앱 창 WebView2 프로필(사용자별) | 사용자 |
| `%LOCALAPPDATA%\mcp-monitor\notice-webview` | 고지 창 WebView2 데이터(InPrivate, 사용자별) | 사용자 |
| `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\MCPMonitor` | 앱 및 기능 | 관리자 |
| `%ProgramData%\Microsoft\Windows\Start Menu\Programs\MCP Monitor.lnk` | 시작 메뉴(모든 사용자) | 관리자 |
| `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\MCPMonitor` | 선택: `"<I>\mcp-monitor.exe" app --background` | 사용자 |
| 서비스 `mcp-monitor` | `"<I>\bin\monitor\mcp-monitor-server.exe" service --root "<D>" --local-port LP --external-port EP`, 지연 자동, LocalSystem | SCM |
| 방화벽 `MCP Monitor (<EP>)` | `--open-firewall`일 때만, domain·private | 관리자 |

**PowerShell → Rust 이름 대응(Task 5–8)**
| PowerShell(Plan 5) | Rust |
|---|---|
| `Get-FullPath`, `Test-Inside`, `Get-LocalDriveLetters`, `Get-PathLinkProblem`, `Get-UnsafeRootReason`, `Test-DataRootMarker` | `paths::{full_path, is_inside, SystemVolumes::local_fixed_letters, path_link_problem, unsafe_root_reason, data_root_marker}` |
| `Get-TreeItems`, `Get-UntrustedRule`, `Get-DataRootProblem`, `Test-DataRootReadable`, `Get-FolderAcl`, `Get-AncestorProblem` | `acl::{tree_items, untrusted_rule, data_root_problem(_with), data_root_readable, read_security, ancestor_problem}` |
| `Reset-ItemAcl`, `New-RootSecurity`, `Set-RootAcl`, `New-ProtectedDirectory`, `Get-DataRootAclProblems`, `Initialize-DataRoot` | `acl::{reset_item_acl, RootSecurity::new, set_root_acl, create_protected_dirs, acl_problems, initialize_data_root(_with)}` |
| `ConvertTo-CommandLineArg`, `Invoke-Native`, `Test-Admin` | `cli::quote_arg`, `exec::RealExecutor::native`(`std::process::Command` + `system_tool`), `winutil::is_elevated` |
| `Restore-RegistryValues` | `audit::validate_registry_restore` + `(reg-restore)` |
| `$Internal`, `$Conditions`, `$AfterStep`, `Invoke-Plan`, `-DryRun` | `plan::Executor`(`internal`, `condition`, `after`), `plan::run_plan`, `plan::print_dry_run` |
| (신규) | `acl::install_tree_problem`, `stage::{stage, swap, remove_old}`, `procs::stop_apps`, `remove::{remove_install_dir, remove_glob, select_run_values}` |

**Python 에이전트 → Rust 에이전트(Task 9–11)**
| Python `agent/mcp_agent` | Rust `desktop/src/agent` |
|---|---|
| `config.parse_args`(토큰·키 pop) | `config::{take_secrets, config_from, strip_webview2_env}` + `cli::AgentArgs` |
| `client.ServerClient`, `proof_for`, `ServerUnavailable`/`AgentRejected`/`ServerUnverified` | `client::{ServerClient, proof_for, ClientError::{Unavailable, Rejected, Unverified, Unexpected}}` |
| `runner.AgentRunner`, `_Backoff`, `wants_window_events`, `_heartbeat_sec` | `runner::{AgentRunner, BACKOFF_SEC, wants_window_events, heartbeat_sec}` |
| `coalesce`, `idle`, `sender`, `pump`, `hooks`, `__main__.WindowActivity` | `coalesce`, `idle`, `sender`, `pump`, `hooks`, `activity::WindowActivity` |
| `dialog.PrintWindow` / `EdgeWindow` | `window::PrintWindow` / `webview::WebViewNotice` |
| (서버) `app.activity.redact.redact_notice_tokens` | `redact::redact_notice_tokens`(같은 식) |

**에이전트 규약(변경 없음; 서버 `app/web/agent_api.py`, `app/activity/agent_hub.py`)**
| 요청 | 본문 | 응답 | 비고 |
|---|---|---|---|
| 모든 요청 | 헤더 `X-Agent-Token`(실행마다), `X-Agent-Nonce`(요청마다 32 hex) | 401·403 외에는 `X-Server-Proof` = HMAC-SHA256(서버 키, nonce) hex | 증명 실패 → 종료 5 |
| `POST /api/agent/hello` | `{session_id, pid, version}`(pid = TCP 피어 pid여야 함) | `{heartbeat_sec: 5, events_max: 200, idle_threshold_sec: 300, window_events}` | 다른 세션·pid → 403 `agent_impersonation` |
| `GET /api/agent/next?timeout=0..30` | | 204 또는 `{type: "show_notice", display_id, attempt, url: "<Local>/notice#d=<id>&t=<token>"}` / `{type: "close_notice", display_id}` / `{type: "exit"}` | 고지 URL은 `<server>/notice#`로 시작할 때만 엶 |
| `POST /api/agent/heartbeat` | `{idle_sec, locked: null}` | 204 | |
| `POST /api/agent/events` | `{events: [≤200], dropped?: int}` — 창 `{type: foreground|minimize|restore|title, at, pid, exe(≤260)|null, title(≤512)}`, 유휴 `{type: idle|active, at, idle_sec}` | 204 | 증명된 서버에만(`verified_only`) |
| `POST /api/agent/notice/{id}/closed` | | 204 | 사용자가 닫음·WebView2 프로세스 실패 |
| 실행 | `<I>\mcp-monitor.exe agent --server http://127.0.0.1:<LP> --dialog webview`, 환경 `MCPMON_AGENT_TOKEN`, `MCPMON_AGENT_SERVER_KEY`(64 hex) | | `WtsLauncher`(서비스) / `LocalLauncher`(개발) |
