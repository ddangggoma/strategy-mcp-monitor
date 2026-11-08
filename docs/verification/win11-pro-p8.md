# Win 11 Pro 실기기 점검표 — P8(데스크톱 앱: 단일 실행 파일 mcp-monitor.exe)

- **대상:**
  - `docs/PLAN.md` v0.9(P8 데스크톱 앱), 설계 `docs/design/desktop-app-rust.md`(D2–D5)
  - Plan 6(`docs/superpowers/plans/2026-11-07-plan6-desktop-app.md`) 부록 A Y1–Y34, Review Focus 1–8
  - 운영 문서 `docs/ops/OPERATIONS.md` v1.0.0
- **작성:** Plan 6 Task 15 (2026-11-08).
  - 개발 PC는 **Windows 11 Home, 관리자 아님, Smart App Control 켜짐**입니다. 그래서 UAC 승격, 서비스 설치, SYSTEM 실행, RDP 세션, Program Files·ProgramData ACL, HKLM 레지스트리, 감사 정책, 방화벽을 실제로 바꾸거나 실행할 수 없습니다.
  - Rust 테스트는 GitHub Actions의 Windows 러너(승격된 관리자, SAC 없음)에서 돕니다. 러너는 실제 서비스·다른 사용자 세션이 없습니다. 관리자 아님을 전제로 한 테스트는 승격된 실행에서는 이유를 출력하고 건너뛰고, 같은 잡에서 **임시 표준 사용자(Users 그룹만)로 다시** 돌아 통과해야 합니다(Plan 6 리뷰 I1).
  - 그래서 **모든 결과 칸은 `대기`**입니다(Y26).
- **자동 테스트가 이미 확인한 것:**
  - 명령줄 해석, 승격 재실행 인자(해석한 옵션만, `--dry-run`은 승격하지 않음), 명령줄 인용(`desktop/src/cli.rs`, `tests/cli.rs`)
  - 설치·업그레이드·제거·감사 정책 계획 전체(`--dry-run` JSON, 단계 id·조건·인자, 이전 포트·방화벽 유지, 다운그레이드 거부, 이전 PowerShell 설치에서의 업그레이드), 관리자가 아니면 아무것도 바꾸지 않고 종료 1(`tests/install_cli.rs`, `tests/uninstall_cli.rs`), 데이터 루트·설치 폴더 ACL 규칙(현재 사용자 소유의 `%LOCALAPPDATA%` 임시 폴더)
  - 내장 묶음 무결성(잘린 exe, 바뀐 파일, 매니페스트 밖 항목, `..`·절대 경로·링크), 개발용 묶음으로 설치 거부, 릴리스 빌드의 `--version`·`DependentLoadFlags 0x800`·`verify-payload`(`install\build-desktop.ps1`, 서버 `-m desktop`)
  - Rust 에이전트: Python과 같은 HMAC 벡터·이벤트 픽스처, 가짜 서버로 사칭·증명 실패·종료 코드, 서버 통합 9개 시나리오를 Python·Rust 에이전트 둘 다로(`server/tests/test_integration_agent.py`)
  - 실제 WebView2 창: 고지 창(최상위, 닫기 회색, 최소화·최대화·크기 조절 없음, 640×600, `WM_CLOSE` 무시, 다른 곳으로 이동·`window.open` 막힘, 명령으로 닫힘, **브라우저 프로세스를 끝내면 "닫힘"을 한 번 보고하고 빈 창을 닫은 뒤 다음 `show_notice`에 새 창**)과 앱 창(연결 중 → 관리 화면, 단일 인스턴스, 닫으면 트레이, 서비스 없음 → 안내) — 러너 데스크톱과 이 PC 화면에서. 작업 표시줄에 없는 것(`skip_taskbar`)은 창 스타일로 보이지 않아(ITaskbarList) P8-6에서 봅니다
  - 이 점검표는 그 밖에 남은 것입니다. 곧 **깨끗한 Win 11 Pro에 실제로 설치하고 사람이 눌러 봐야 하는 확인**입니다.
- **결과를 채우는 법:**
  - `결과` 칸에 `통과` / `실패` / `해당 없음`과 날짜를 적습니다.
  - 실패면 `비고`에 출력(명령은 `| Write-Output` 형태로 실행), 메시지 상자 문구, 이벤트 뷰어 항목, `C:\ProgramData\MCP Monitor\logs\<날짜>.jsonl`의 해당 줄을 남깁니다.
  - 실패 항목은 `docs/superpowers/plans/carry-forward.md`의 "After Plan 6"에 새 항목으로 옮깁니다.

## 1. 준비

1. **기기:** **깨끗한** Windows 11 Pro VM(Hyper-V 등, **설치 전 스냅숏**을 만들어 둠) 또는 실기기.
   - Smart App Control 상태를 기록합니다: `(Get-MpComputerStatus).SmartAppControlState`(`On` / `Evaluation` / `Off`). 가능하면 **켜진 상태**로 점검합니다(P8-1).
   - WebView2 런타임 버전을 기록합니다: `Get-ItemProperty 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}' -Name pv`.
   - 같은 네트워크에 RDP 클라이언트와 브라우저로 쓸 다른 PC 1대를 둡니다.
2. **계정:**
   - 관리자 1개(점검 진행, 설치).
   - RDP용 **표준 사용자** `hong`, `kim`(Administrators에 넣지 않음).
   - 설정 → 시스템 → 원격 데스크톱을 켜고, 두 사용자를 "원격 데스크톱 사용자"에 추가합니다.
3. **실행 파일:**
   - `dist\mcp-monitor-1.0.0.exe`와 `mcp-monitor-1.0.0.exe.sha256`(GitHub Actions `desktop` 워크플로의 release 산출물 `mcp-monitor-release-<커밋>`, 또는 `install\build-desktop.ps1`)을 VM의 **다운로드 폴더**(`C:\Users\<관리자>\Downloads`)에 복사합니다.
   - `Get-FileHash -Algorithm SHA256 .\mcp-monitor-1.0.0.exe`의 값과 `.sha256`의 값이 같은지 확인합니다.
   - 서명이 없는 것이 맞습니다(D5): 파일 속성 → 디지털 서명 탭이 없음.
   - P8-11·P8-12용: (a) **이전 PowerShell 설치 묶음 zip**(커밋 c9938d1에서 `server\app\__init__.py`의 `__version__`을 `0.9.0`으로 바꾼 뒤 `install\build.ps1`로 빌드한 `mcp-monitor-0.9.0.zip`. 그 커밋 그대로 빌드하면 버전이 `1.0.0`이라 이 exe와 같은 버전으로 보여 업그레이드 안내가 나오지 않습니다), (b) `desktop/Cargo.toml`·`tauri.conf.json`·서버·웹 버전을 **1.0.1로 올려 빌드한 exe**(같은 소스, 버전만 다름).
4. **설치 전 기록**(P8-13에서 되돌림 확인용):
   - `auditpol /backup /file:C:\Temp\before.csv`
   - `reg query HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System\Audit /v ProcessCreationIncludeCmdLine_Enabled`(없을 수 있음)
   - `reg query HKLM\SOFTWARE\Policies\Microsoft\Windows\PowerShell\ScriptBlockLogging /v EnableScriptBlockLogging`
   - `wevtutil gl Security`
5. 이하 `<I>` = `C:\Program Files\MCP Monitor`, `<D>` = `C:\ProgramData\MCP Monitor`, `<exe>` = `<I>\mcp-monitor.exe`. 명령은 따로 적지 않으면 **관리자 PowerShell**에서 `| Write-Output`을 붙여 실행합니다(GUI 실행 파일이라 붙이지 않으면 기다리지 않음).

## 2. 항목

각 행은 절차 / 기대 / 결과 / 비고입니다.

### 2.1 P8 — 설치·업그레이드·제거·앱·에이전트

| # | 절차 | 기대 | 결과 | 비고 |
|---|---|---|---|---|
| P8-1 | SAC가 켜진 상태에서 다운로드 폴더의 서명 없는 exe로 `& .\mcp-monitor-1.0.0.exe --version \| Write-Output`, 이어서 탐색기에서 **더블클릭** → 설치 안내 상자에서 **아니요** | `mcp-monitor 1.0.0 (payload <12 hex>, release)`, 종료 코드 0. 더블클릭하면 "MCP Monitor가 이 PC에 설치되어 있지 않습니다. 지금 설치할까요? …"(설치 위치·데이터 표시), 아니요 → 아무것도 바뀌지 않음(`sc.exe query mcp-monitor` = 1060). `CodeIntegrity/Operational`에 `mcp-monitor.exe` 차단(3076/3077) 없음. 설치 뒤(P8-2) 서비스의 `mcp-monitor-server.exe`와 세션의 `mcp-monitor.exe agent`도 막히지 않음 | 대기 | D5, Y2. SAC는 파일마다 평판으로 판단(개발 PC에서는 통과). **막히면** carry-forward로: 코드 서명 인증서(`build-desktop.ps1 -SignThumbprint`) 또는 이전 PowerShell 설치 방식(커밋 c9938d1)으로 되돌리기(Y8). Task 13: 탐색기 더블클릭은 이 점검에서 처음 |
| P8-2 | **표준 사용자**로 콘솔 로그인 → 다운로드 폴더의 exe 더블클릭 → 안내 **예** → UAC에 관리자 자격 증명 → 진행 | 결과 상자 "설치 완료: http://127.0.0.1:8700/admin/setup 에서 첫 Admin 계정을 만드세요." → **설치된** `<exe>`의 앱 창이 첫 Admin 만들기 화면(`/admin/setup`). 첫 Admin을 만들고 로그인(코드는 관리자로 `<D>\data\dev\otp-outbox.log`). 다운로드 폴더의 exe는 끝나 있어 지울 수 있음(작업 관리자에 그 경로의 프로세스 없음) | 대기 | Review Focus 1, Y12–Y13, F27. Task 4: 실제 UAC 재실행은 이 점검에서 처음. UAC에서 **아니요**를 누른 경우도 한 번: 오류 상자, 아무것도 바뀌지 않음 |
| P8-3 | (P8-2 대신, 스냅숏에서 다시) 관리자 PowerShell: `& .\mcp-monitor-1.0.0.exe install --dry-run \| Write-Output` → `& .\mcp-monitor-1.0.0.exe install --open-firewall \| Write-Output; $LASTEXITCODE` → 재부팅 → **아무도 로그인하지 않은 채** 2분 → 다른 PC에서 `http://<VM>:8701/` | DryRun은 26단계 JSON. 실행은 `[1/26] require_admin` … `[26/26] cleanup_old: 건너뜀 (old_exists 아님)`까지 `[실패]` 없이, 마지막 줄 `설치 완료: …`, 종료 코드 0. `check_os`가 경고를 내지 않음(Pro, Program Files, WebView2 있음). 재부팅 뒤 `sc.exe query mcp-monitor` = `RUNNING`, 다른 PC에서 보드 표시. `sc.exe qc mcp-monitor`의 `BINARY_PATH_NAME` = `"<I>\bin\monitor\mcp-monitor-server.exe" service --root "<D>" --local-port 8700 --external-port 8701` | 대기 | **P7-1·P7-2의 데스크톱판.** Task 6: 부모 콘솔에 붙은 출력은 파이프에서만 확인했음. **cmd.exe**에서 `mcp-monitor-1.0.0.exe install --dry-run`(파이프 없이)도 한 번: 출력이 그 콘솔에 보이는지(프롬프트가 먼저 돌아와도 됨), `sc.exe`·`auditpol` 출력이 새 콘솔 창을 띄우지 않는지 기록 |
| P8-4 | `icacls "<D>"`, `icacls "<D>\logs"`, `icacls "C:\Program Files\MCP Monitor" /T`. `hong`으로 RDP 접속해 `<D>\logs`·`<D>\data` 열기, `<I>`에 파일 만들기 | `<D>`: P7-4와 같음(`NT AUTHORITY\SYSTEM:(OI)(CI)(F)`, `BUILTIN\Administrators:(OI)(CI)(F)`만, 상속 없음, 소유자 Administrators), `hong`은 액세스 거부. `<I>` 트리: 사용자(`BUILTIN\Users`, `Authenticated Users`)에게 쓰기·삭제·권한 변경 없음(읽기·실행만), `hong`은 `<I>`에 쓸 수 없음 | 대기 | Y15, Y18, E1. Task 5·7: 소유자가 실제 Administrators·TrustedInstaller이고 Program Files 상속(CREATOR OWNER, ALL APPLICATION PACKAGES)이 있는 트리에서 `install_tree_problem`이 통과하는지는 여기서 처음. 승격된 토큰의 `SetNamedSecurityInfoW` 전파도 |
| P8-5 | 설정 → 앱 → 설치된 앱에서 **MCP Monitor** 확인, 시작 메뉴(다른 사용자 `hong`으로도) 확인. 이어서 앱 및 기능에서 **제거** → UAC | 항목: 이름 `MCP Monitor`, 버전 `1.0.0`, 게시자 `MCP Monitor`, 크기(약 수십 MB), 아이콘. 수정·복구 단추 없음. 시작 메뉴 "MCP Monitor"가 모든 사용자에게 보이고 앱 창을 엶. 제거 → UAC → 결과 상자 "제거 완료. 데이터는 C:\ProgramData\MCP Monitor 에 남아 있습니다(지우려면 --remove-data)." + "설치 폴더의 남은 파일은 다시 시작할 때 지워집니다." → 앱 및 기능·시작 메뉴 항목 사라짐, 서비스 없음 | 대기 | Y19, Task 7·8: 실제 HKLM 쓰기·`%ProgramData%` 바로 가기, `uninstall --interactive`(승격 전 부모는 남고 자식이 끝낸 뒤 상자) 처음. 끝나면 다시 설치(P8-3) |
| P8-6 | 다른 PC에서 보드를 연 채 `hong`으로 RDP 접속 | **2초 안에** 보드 `● 접속 중`, `hong` 세션에 `<exe> agent`(사용자 `hong`)와 고지 창: 화면 가운데 640×600, 항상 위, 닫기 단추 비활성(회색), Alt+F4·Esc 무시, 작업 표시줄에 없음, 최소화·최대화·크기 조절 없음, 창 제목 `MCP Monitor 고지`. Tab으로 '확인'에 초점, Enter → 창 닫힘. `notice` `notice_shown`·`notice_acknowledged` | 대기 | Review Focus 6, Y10, D3. 내용이 뜨기까지 < 300ms(§15)인지 체감 기록. 작업 표시줄 오른쪽 아래 깜빡임 여부도 |
| P8-7 | `hong`·`kim` 두 사람이 동시에 RDP 접속, 관리자는 콘솔 세션 | 각자 **자기 고지만** 보이고 다른 세션 화면에는 없음. 콘솔 관리자 세션에는 고지 없음(`--collect-console` 아님). 끊고 다시 연결할 때마다 다시 표시 | 대기 | 세션마다 에이전트 하나(작업 관리자 → 사용자 탭) |
| P8-8 | ① 고지가 열린 채 `hong` 세션의 작업 관리자에서 그 세션의 `msedgewebview2.exe`(맨 위 브라우저 프로세스) 작업 끝내기. ② 고지가 열린 채 `<exe> agent`(사용자 `hong`) 작업 끝내기 | ①: 약 1–3초 뒤 고지가 다시 뜸(`notice_unacknowledged` 뒤 새 `notice_shown`, `attempt` 증가). ②: 서비스가 에이전트를 다시 띄우고 고지 다시 표시, `tamper` `agent_exited` | 대기 | 리뷰 I3: `ProcessFailed`·`BrowserProcessExited`·브라우저 프로세스 감시 셋 중 하나로 알아차림. CI에서는 에이전트가 기록한 브라우저 프로세스(`BrowserProcessId`)를 끝내자 `ProcessFailed (kind 0)`가 왔고 새 창이 떴음(Task 11 때는 다른 `msedgewebview2.exe`를 끝냈던 것으로 보임). ①에서 빈 창이 남지 않는지, 에이전트 표준 오류의 `notice window: …` 줄은 이 점검에서 볼 수 없으니 결과만 기록 |
| P8-9 | 서비스를 멈추고(`sc.exe stop mcp-monitor`) ① `127.0.0.1:8700`, ② `0.0.0.0:8700`을 다른 프로세스가 점유(예: `python -m http.server 8700 --bind …`) → `hong` 세션에서 `& "<I>\mcp-monitor.exe" agent --server http://127.0.0.1:8700 --dialog webview \| Write-Output; $LASTEXITCODE`(환경 변수 `MCPMON_AGENT_TOKEN`=아무 값, `MCPMON_AGENT_SERVER_KEY`=64자리 hex) | 둘 다 수 초 안에 종료 코드 **5**, 창이 열리지 않음, 창 제목 이벤트를 보내지 않음 | 대기 | P5-5b와 같음(Review Focus 5). 끝나면 점유 프로세스 종료, 서비스 시작 |
| P8-10 | `hong`이 메모장·PowerShell을 쓰고 창 제목을 몇 번 바꿈 → 5분 넘게 입력 없음 → 다시 입력 | 관리 화면 **로그**에 `activity.window`(포그라운드·제목, `exe` 경로) 줄, 제목에 고지 토큰(`t=`) 원문 없음. 5분 뒤 `activity.idle` `idle`, 입력 뒤 `active`. 고지 창 자체의 창 이벤트는 없음(⑨, F11) | 대기 | Y22. `Select-String -Pattern 't=[A-Za-z0-9_-]{20,}' "<D>\logs\*.jsonl"` 결과 없음 |
| P8-11 | 스냅숏(설치 전)으로 되돌려 **이전 PowerShell 설치 묶음(0.9.0, 준비 3)**을 PowerShell로 설치(`install.ps1 -OpenFirewall`, 그 버전의 P7-1) → MCP 1개·스크립트·사용자·로그를 만듦 → 1.0.0 exe 더블클릭 → 업그레이드 안내 **예**. 이어서 `hong` 세션에 트레이와 고지 창이 열린 채 **1.0.1** exe로 다시 업그레이드 | 0.9.0 → 1.0.0: 안내 "설치된 MCP Monitor 0.9.0을(를) 1.0.0(으)로 업그레이드할까요? …", 성공. 데이터·설정·스크립트·`auditpol-backup.csv`(수정 시각 그대로)·`install-state.json`의 `registry_before` 유지, `<I>\bin\agent`·`<I>\install` 사라짐, `sc.exe qc`의 binPath가 `mcp-monitor-server.exe`, 세션 에이전트가 `mcp-monitor.exe agent`, 앱 및 기능 항목 생김. 1.0.0 → 1.0.1: `hong`의 트레이·고지 창이 닫히고(`stop_apps`) 성공, `<I>.old`·`<I>.staging` 없음, 방화벽 규칙 하나, `hong`의 고지는 서비스가 다시 띄운 에이전트가 다시 표시 | 대기 | Review Focus 3, Y15–Y17. Task 7: 다른 세션 프로세스의 `TerminateProcess`(`SeDebugPrivilege`)와 Program Files 아래 폴더 교체는 여기서 처음. `hong`의 트레이는 다음 로그인 때 다시 뜨는지(자동 시작을 켰다면) |
| P8-12 | 1.0.1 설치본에서 1.0.0 exe를 ① 더블클릭, ② `& .\mcp-monitor-1.0.0.exe install \| Write-Output; $LASTEXITCODE` | ①: "설치된 MCP Monitor(1.0.1)가 이 실행 파일(1.0.0)보다 새롭습니다. …" 안내 뒤 **설치된** 앱 창. ②: `오류: --install-dir: 설치된 버전 1.0.1이 이 실행 파일(1.0.0)보다 새롭습니다 …`, 종료 코드 2, 아무것도 바뀌지 않음 | 대기 | 다운그레이드 거부(Y15). 같은 버전 1.0.1 exe의 `install`은 복구 설치로 성공하는지도 한 번 |
| P8-13 | ① `& "<I>\mcp-monitor.exe" uninstall \| Write-Output` → 재부팅 → ② 다시 설치(P8-3) → `hong`·`kim`이 각각 한 번 로그인해 둠 → `& "<I>\mcp-monitor.exe" uninstall --remove-data --restore-audit-policy \| Write-Output` → 재부팅 | ①: 서비스·방화벽 규칙·앱 및 기능·시작 메뉴 삭제, `<D>` 그대로, `<I>`에 `mcp-monitor.exe.uninstalled`만 남고 재부팅 뒤 `<I>` 전체가 사라짐. 재부팅 **전에** 같은 폴더로 다시 설치하면 종료 코드 2(`… 비어 있지 않고 MCP Monitor 설치 폴더(bundle.json)도 아닙니다.`). ②: `<D>`와 `C:\Users\*\AppData\Local\mcp-monitor`(`hong`·`kim`·관리자 모두) 삭제, `auditpol /get`·레지스트리·로그 크기가 1.4의 기록과 같음, 재부팅 뒤 `<I>`가 완전히 사라짐 | 대기 | Review Focus 4, Y21. Task 8: `MoveFileExW` 재부팅 삭제, 다른 세션의 `msedgewebview2.exe`가 끝나는 중일 때의 재시도(F26) 처음. `[실패] remove_*`가 나오면 비고에 기록하고 다시 실행 |
| P8-14 | 앱 창 오른쪽 위 닫기 → 트레이 아이콘 오른쪽 클릭 → 메뉴 확인 → `로그인할 때 트레이 시작` 체크 → `reg query HKCU\Software\Microsoft\Windows\CurrentVersion\Run /v MCPMonitor` → 로그아웃·로그인 → 서비스를 멈췄다 켜며 메뉴 첫 줄 보기 → `트레이 종료` | 창이 사라지고 트레이에 남음. 메뉴: `서비스: 실행 중`(멈추면 `서비스: 중지됨`, 그 사이 `멈추는 중`·`시작하는 중`), `창 열기`, `로그인할 때 트레이 시작`, `트레이 종료`. Run 값 = `"C:\Program Files\MCP Monitor\mcp-monitor.exe" app --background`. 다시 로그인하면 **창 없이** 트레이만, 트레이 아이콘 클릭·`창 열기`로 창. `트레이 종료` 뒤에도 서비스는 `RUNNING` | 대기 | Y20, Task 12: 트레이 클릭은 개발 PC에서 입력을 넣을 수 없어 처음. 체크를 끄면 Run 값이 사라지는지도. 다른 사용자(`hong`)의 HKCU는 그대로인지 |
| P8-15 | 앱 창에서 외부 링크 열기(관리 화면의 외부 문서 링크, 없으면 **고지 편집**의 미리보기 문구에 `https://example.com` 링크를 넣고 미리보기에서 클릭). 앱 창에서 F12, Ctrl+Shift+I, 오른쪽 클릭 | 링크는 **기본 브라우저**에서 열리고 앱 창은 그대로. 개발자 도구가 열리지 않고, 오른쪽 클릭 메뉴에 "검사" 없음 | 대기 | Review Focus 7, Y11, Y24. Task 12: `OpenExternal` 경로는 분류 단위 테스트로만 확인 |
| P8-16 | 앱 창이 열린 채(다른 창 뒤에 있게 둠) 시작 메뉴에서 **MCP Monitor**를 다시 실행. 창을 오른쪽 아래 모서리로 끌어 줄이기 | 새 창 없이 기존 창이 앞으로 옴(작업 관리자에 이 사용자의 `mcp-monitor.exe app` 하나). 640×600에서 더 줄어들지 않고, 그 크기에서 관리 화면에 가로 스크롤 없음 | 대기 | Y11, Y30. Task 12: 끌어서 크기 조절은 개발 PC에서 입력을 넣을 수 없어 처음 |
| P8-17 | (선택) Process Monitor(Sysinternals)에 필터 `Process Name is mcp-monitor-1.0.0.exe`, `Path ends with .dll` → 다운로드 폴더에서 exe를 **관리자 권한으로 실행**(오른쪽 클릭) → 안내에서 아니요 | 다운로드 폴더에서 DLL을 찾는 줄(`NAME NOT FOUND`가 `C:\Users\…\Downloads\*.dll`)이 없음. DLL은 `C:\Windows\System32`(와 WebView2 런타임 폴더)에서만 | 대기 | Review Focus 1, Y13(`/DEPENDENTLOADFLAG:0x800`, `SetDefaultDllDirectories`) |
| P8-18 | P8-3 설치(`--open-firewall`, 8701) 상태에서 `& "<I>\mcp-monitor.exe" install --external-port 9701 \| Write-Output` → `netsh advfirewall firewall show rule name=all \| findstr "MCP Monitor"` → 다른 PC에서 `http://<VM>:9701/` | 단계 `firewall_delete_old`가 `MCP Monitor (8701)`을 지우고 `firewall`이 `MCP Monitor (9701)`을 만듦 — 규칙이 **하나만**. 보드는 9701로 열림. 8701로 되돌린 뒤 다시 하나만 | 대기 | Y32, X7-8의 데스크톱판(이제 옛 규칙이 남지 않음). PowerShell 설치 때 남은 옛 규칙은 지우지 않음(알려진 동작) |
| P8-19 | 제거된 상태에서 P7-11·P7-13의 데이터 루트 공격을 `mcp-monitor.exe install`로 재현: ① `hong`이 미리 만든 `C:\ProgramData\MCP Monitor`(Everyone F) ② `hong`의 정션 ③ `--data-root "D:\apps\MCP Monitor"`(Authenticated Users M 상속) ④ `--data-root "\\localhost\C$\ProgramData\MCP Monitor"`와 subst 드라이브. 같은 방식으로 `--install-dir`(예: `hong`이 만든 `C:\Tools\MCP`), `audit-policy --enable --data-root …`도 | 모두 종료 코드 **2**, 표준 오류 `오류: --data-root: …`(또는 `--install-dir`) 한 줄, 표준 출력 없음, 아무 단계도 실행되지 않음(서비스·ACL·레지스트리 그대로). 폴더를 지우고 다시 설치하면 정상 설치되고 P8-4와 같은 ACL | 대기 | Review Focus 8, Y18. Task 5: 실제 Administrators 소유자·TrustedInstaller 소유 상위 폴더에서의 판단은 여기서 처음 |
| P8-20 | `win11-pro-p4-p5.md`(P4-1–P4-13, P5-1–P5-14, X-1–X-10)와 `win11-pro-p6-p7.md`(P7-1–P7-13, P6-1–P6-3, X7-1–X7-10)를 **데스크톱 설치 상태(P8-3)로 다시 수행** | 각 문서의 기대대로. 바꿔 읽기는 아래 §3 | 대기 | 결과는 그 문서의 `결과` 칸에 날짜와 "데스크톱 설치 상태(1.0.0)"라고 적음 |

### 2.2 추가 점검 (Plan 6 과제 노트에서 모음)

| # | 절차 | 기대 | 결과 | 비고 |
|---|---|---|---|---|
| X8-1 | 관리자가 아닌 PowerShell에서 `& .\mcp-monitor-1.0.0.exe install --interactive \| Write-Output` → UAC 승인 | UAC 창이 뜨고(같은 exe, 인자에 `--interactive`, `--dry-run` 없음), 승격된 쪽이 설치하고 결과를 메시지 상자로 보여 줌. 부모는 승격된 쪽이 끝날 때까지 기다렸다가 그 종료 코드로 끝남 | 대기 | Y13, Task 4. 작업 관리자 세부 정보의 "명령줄" 열로 승격된 쪽의 인자 확인 |
| X8-2 | 앱 및 기능에서 제거할 때 다른 세션(`hong`)에 앱 창·트레이와 고지 창이 열려 있음 | `stop_apps`가 그 세션의 `mcp-monitor.exe`를 끝내고(`SeDebugPrivilege`), 제거 성공. `hong`의 `%LOCALAPPDATA%\mcp-monitor`는 `--remove-data`가 아니면 그대로 | 대기 | Task 7·8(F07) |
| X8-3 | 설치된 서비스의 로그 시각과 보존 정리 시각 | `<D>\logs\<오늘>.jsonl`의 `at`이 `+09:00`(KST)이고, 날짜 파일 전환이 KST 자정. 서비스 시작 로그에 `zoneinfo`·`tzdata` 오류 없음 | 대기 | Task 2: PyInstaller 빌드에서 "Hidden import tzdata not found" 경고 — 얼린 서버에서 KST 처리가 맞는지 실기기에서 확인 |
| X8-4 | WebView2 런타임이 없는 VM(가능하면 별도 VM, 또는 런타임 제거 후) | 설치 `check_os`가 `경고: 이 PC에 설치된 WebView2 런타임을 확인하지 못했습니다 …`를 내고 설치는 끝까지. 앱 창 실행 → "MCP Monitor 창을 열 수 없습니다 …" 상자. `hong` 접속 → 고지가 기본 브라우저 탭으로 열림(최상위 아님), 로그의 고지 URL은 `t=<redacted>`. 그 탭을 닫아도 고지는 다시 뜨지 않음(이 방식에서는 닫힘을 알 수 없음, OPERATIONS ⑨) | 대기 | Y33. 토큰이 브라우저 명령줄에 남는 것은 알려진 한계(carry-forward) |
| X8-5 | `check_os` 경고 문구: Windows 11 Home VM이 있으면 `install --dry-run`이 아니라 실제 설치 단계에서, 또는 `--install-dir "D:\MCP Monitor"`(Program Files 밖) | Home: `경고: … RDP 호스트가 아니어서 세션 수집이 동작하지 않습니다. 설치는 계속합니다.` / Program Files 밖: 그 경고. 설치는 계속 | 대기 | Task 7: 에디션 이름은 WMI가 아니라 레지스트리에서 읽음(표시용) |
| X8-6 | `hong` 세션의 고지 창을 다른 최상위 창(작업 관리자 "항상 위", 다른 앱의 전체 화면) 뒤로 보내 봄 | 2초 안에 고지가 다시 맨 위로 옴. 초점은 빼앗지 않음(입력 중인 창에 계속 입력됨) | 대기 | Y10 "실기기에서 가려지면 타이머·전경 처리 조정" |
| X8-7 | 업그레이드 중 설치 폴더를 탐색기로 열어 둠(`<I>\bin` 폴더) | `[실패] swap_install_dir: …` 다음 줄 `[복구] 이전 버전의 서비스를 다시 시작했습니다(sc.exe start mcp-monitor).`(더블클릭이면 결과 상자에 두 줄), `sc.exe query mcp-monitor` = `RUNNING`(이전 버전), 이전 폴더로 되돌려져 있음(`<I>`에 이전 버전, `<I>.staging` 남을 수 있음). 탐색기를 닫고 다시 실행하면 성공 | 대기 | Y15, 리뷰 4, OPERATIONS ③ 2·⑩. 결과를 운영 문서의 문구와 비교 |
| X8-8 | (선택, 재현할 수 있을 때) PowerShell 설치(0.9.0) → 1.0.0 업그레이드에서 폴더 교체 **뒤**의 단계(`secure_data_root`, 감사 단계, `service_install` …)가 실패한 경우 | `[실패] <id>: …` 다음 줄 `[복구] 서비스가 멈춰 있습니다. … 이전 설치는 <I>.old 에 있습니다.`. 이때 `sc.exe start mcp-monitor`는 실패(PowerShell 설치의 binPath가 `<I>.old`로 옮겨진 파일을 가리킴). 원인을 지우고 같은 1.0.0 exe로 다시 설치하면 성공하고 binPath가 `mcp-monitor-server.exe` | 대기 | 리뷰 4 |
| X8-9 | 실패한 업그레이드 뒤 `<I>.old`(이전 설치)와 `<I>.staging`이 남은 상태에서 `& "<I>\mcp-monitor.exe" uninstall \| Write-Output` | 단계 `remove_old_install`·`remove_staging`이 둘을 지움. 표시가 없는 폴더(손으로 만든 `<I>.old`)는 `건너뜀 (old_is_ours 아님)`으로 남김 | 대기 | 리뷰 8 |
| X8-10 | 다운로드한 exe를 **관리자 권한으로 실행**(설치된 상태), 관리자 PowerShell에서 `& "<I>\mcp-monitor.exe" app` | 둘 다 앱 창·트레이가 뜨지 않고 "관리자 권한으로 실행 중이라 MCP Monitor 창을 열지 않습니다 …" 상자, 종료 코드 1. 관리자의 `HKCU\…\Run`에 아무것도 생기지 않음. 설치되지 않은 PC에서 다운로드한 exe를 **관리자 권한으로 실행**해 설치(예)하면 설치기의 결과 상자 다음에 "설치를 마쳤습니다. …" 안내 상자(오류 상자 아님), 종료 코드 0, 창·트레이 없음 | 대기 | 리뷰 18, 재리뷰 Minor 2 |
| X8-11 | 서비스를 지운 뒤(`sc.exe delete mcp-monitor`, 앱 및 기능·`<I>`는 그대로) 시작 메뉴 **MCP Monitor** 실행 | 설치 안내·UAC 없이 "… 다운로드한 mcp-monitor-1.0.0.exe로 실행하세요" 상자. 받은 exe로 실행하면 복구 설치 | 대기 | 리뷰 17(F06) |

## 3. P4–P7 점검표를 데스크톱 설치 상태로 다시 수행 (P8-20)

`docs/verification/win11-pro-p4-p5.md`와 `docs/verification/win11-pro-p6-p7.md`를 **P8-3 설치 상태에서 다시 수행**합니다. 두 문서는 데스크톱 exe 이전(PowerShell 설치·Python 에이전트·Edge 고지)에 쓰였으므로 다음을 바꿔 읽습니다.

- **설치·제거·감사 정책:**
  - `install\install.ps1 [-OpenFirewall] [-DataRoot …]` → `mcp-monitor.exe install [--open-firewall] [--data-root …] | Write-Output`. 단계 수는 19/20이 아니라 25/26이고, `copy_bundle` 대신 `stage_payload`·`stop_apps`·`swap_install_dir`.
  - `<I>\install\uninstall.ps1 [-RemoveData] [-RestoreAuditPolicy]` → `<I>\mcp-monitor.exe uninstall [--remove-data] [--restore-audit-policy]`(또는 앱 및 기능).
  - `install\audit-policy.ps1 -Enable` / `-Restore <csv>` → `mcp-monitor.exe audit-policy --enable` / `--restore <csv>`.
  - 매개변수 이름: `-DryRun` → `--dry-run`, `-ExternalPort` → `--external-port` 등(OPERATIONS ②).
  - 묶음 zip과 `Get-FileHash`의 대상은 `mcp-monitor-1.0.0.exe`.
- **서버 exe:** `<I>\bin\monitor\mcp-monitor.exe` → `<I>\bin\monitor\mcp-monitor-server.exe`(서비스 binPath, 작업 관리자에서 끝낼 서비스 프로세스(P7-6), `reindex`(X7-4), 콘솔 실행(X7-9)). `<I>\mcp-monitor.exe`는 데스크톱 앱이라 `reindex`가 없습니다.
- **에이전트:** `<I>\bin\agent\mcp-agent.exe`(또는 `python … mcp_agent`) → `<I>\mcp-monitor.exe agent`(사용자 권한). P5-4·X-2에서 끝낼 대상도 이것입니다.
- **고지 창:** Edge `--app` 창 → WebView2 창(P8-6). 바뀐 기대:
  - P5-3 "X로 닫기 → 1초 뒤 다시 뜸": 닫기 단추가 비활성이고 Alt+F4도 무시되므로 닫히지 않는 것이 기대입니다. "다시 뜸"은 P8-8로 확인합니다.
  - P5-1 "Edge 첫 실행 화면 없음", X-3·X-4(Edge 프로필·백그라운드 Edge): 해당 없음(Edge를 쓰지 않음). 대신 고지가 뜨는 동안 그 세션에 `msedgewebview2.exe`가 에이전트의 자식으로 뜨는지 기록합니다.
  - P5-6b: `activity.process`에 고지용 `msedge.exe` 줄이 없고 `msedgewebview2.exe` 줄이 생김. 고지 창 자체의 `activity.window` 줄은 없음(OPERATIONS ⑨). 토큰 원문이 로그 어디에도 없어야 하는 것은 같음.
  - X-5(Edge가 없는 경우) → X8-4(WebView2가 없는 경우).
- **P7-8(SAC):** PowerShell 설치 묶음 zip의 `--version` 대신 P8-1.
- **P7-10·P7-11·P7-13:** P8-13·P8-19와 겹칩니다. 두 쪽에 같은 결과를 적어도 됩니다.
- **X7-8(옛 방화벽 규칙이 남음):** 데스크톱 설치에서는 P8-18의 기대(규칙 하나)로 바뀝니다.
- 데이터 폴더(`C:\ProgramData\MCP Monitor`), 서비스 이름(`mcp-monitor`), 포트, 웹 화면, 로그 카테고리는 같습니다.
