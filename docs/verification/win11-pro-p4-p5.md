# Win 11 Pro 실기기 점검표 — P4(세션 수집)·P5(행동 로그 + 고지)

- 대상: `docs/PLAN.md` v0.7 §11 P4·P5 완료 기준, Plan 4(`docs/superpowers/plans/2026-11-07-plan4-windows-collection.md`) 부록 A V1–V33
- 작성: Plan 4 Task 20 (2026-11-06). 개발 PC는 **Windows 11 Home, 관리자 아님**이라 RDP 접속, Security 로그, `CreateProcessAsUser`, 감사 정책 변경을 실행할 수 없습니다. 그래서 **모든 결과 칸은 `대기`**입니다.
- 자동 테스트가 이미 확인한 것: 가짜·녹화 픽스처로 같은 코드 경로 전체(트래커·표시·감독·실제 에이전트·실제 TCP 피어 검증), 이 PC에서 관리자 없이 부를 수 있는 Windows API(`winlive`), 실제 프로세스 통합(`integration`), 웹 E2E(`--session-source json:`). 이 점검표는 그 밖에 남은 것, 곧 **실제 RDP·관리자·SYSTEM이 있어야 하는 확인**입니다.
- 결과를 채우는 법: `결과` 칸에 `통과` / `실패` / `해당 없음`과 날짜를 적고, 실패면 `비고`에 서버 로그(`C:\mcpmon\logs\<날짜>.jsonl`의 해당 줄)와 화면을 남깁니다. 실패 항목은 `docs/superpowers/plans/carry-forward.md`에 새 항목으로 옮깁니다.

## 1. 준비

1. **기기:** Windows 11 **Pro** 실기기 또는 VM(Hyper-V 등). 같은 네트워크에 RDP 클라이언트로 쓸 다른 PC 1대(가능하면 IPv6도 되는 곳).
2. **계정 2개:**
   - 관리자 1개(점검 진행, 서버 실행).
   - RDP용 **표준 사용자** `hong`(Administrators 그룹에 넣지 않습니다. §2 #4: RDP 계정은 표준 사용자로 운영).
   - 설정 → 시스템 → 원격 데스크톱 켜기, `hong`을 "원격 데스크톱 사용자"에 추가.
3. **감사 정책**(관리자 PowerShell; Plan 5 `install.ps1`이 같은 일을 하게 됩니다):

   ```powershell
   auditpol /set /subcategory:"Process Creation" /success:enable
   auditpol /set /subcategory:"Logon" /success:enable /failure:enable
   auditpol /set /subcategory:"Logoff" /success:enable
   auditpol /set /subcategory:"Other Logon/Logoff Events" /success:enable
   auditpol /set /subcategory:"Audit Policy Change" /success:enable
   reg add HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System\Audit /v ProcessCreationIncludeCmdLine_Enabled /t REG_DWORD /d 1 /f
   reg add HKLM\SOFTWARE\Policies\Microsoft\Windows\PowerShell\ScriptBlockLogging /v EnableScriptBlockLogging /t REG_DWORD /d 1 /f
   ```

   확인: `auditpol /get /category:*`에서 위 하위 범주가 "성공"(Logon은 "성공 및 실패")인지 봅니다.
4. **설치:**
   - 저장소를 사용자 프로필 밖으로 복사합니다(예: `C:\src\strategy-mcp-monitor`, 이하 `<repo>`). 실행 방식 B에서 `hong`의 세션이 에이전트 폴더(`<repo>\agent`)를 읽어야 하기 때문입니다.
   - 실행 방식 B를 할 거라면 **Python도 프로필 밖에** 둡니다: `uv sync` 전에 `$env:UV_PYTHON_INSTALL_DIR = "C:\uv-python"`. 에이전트는 서버 venv의 **기본 인터프리터**(`sys._base_executable`)로 뜨는데, 기본값(`%APPDATA%\uv\python\…`)은 관리자 프로필 안이라 `hong`이 읽을 수 없습니다(Plan 5 패키징 carry).
   - `cd <repo>\server; uv sync`, `cd <repo>\agent; uv sync`, `cd <repo>\web; pnpm install --frozen-lockfile; pnpm build`.
5. **데이터 폴더:** `C:\mcpmon`(서버가 만듭니다). 처음 실행 뒤 `http://127.0.0.1:8700`에서 첫 Admin을 만들고(Dummy OTP), 점검에 쓸 MCP 개발자 계정을 하나 등록합니다.

## 2. 실행 방식

| 방식 | 언제 | 명령 | 에이전트가 뜨는 곳 |
|---|---|---|---|
| **A (간단)** | P4 전체, P5 중 관리자 세션으로 충분한 항목 | `hong`이 **아닌 관리자 계정으로 RDP 접속**해 관리자 PowerShell에서 `cd <repo>\server; uv run python -m app --root C:\mcpmon --agent-launcher local` | 그 RDP 세션에만(`LocalLauncher`). 다른 세션의 연결은 `agent.launch_failed`(`session_mismatch`) 한 줄만 남깁니다(F22) |
| **B (서비스와 같은 권한)** | P5 전체, 특히 `hong` 세션의 고지·창 이벤트·사칭 차단, WMI trace 모드 | 관리자 PowerShell: `schtasks /create /tn mcpmon-p4 /ru SYSTEM /sc onstart /tr "<repo>\server\.venv\Scripts\python.exe -m app --root C:\mcpmon --static-dir <repo>\web\dist"` 후 `schtasks /run /tn mcpmon-p4` | SYSTEM → `WtsLauncher`(`WTSQueryUserToken` → `CreateProcessAsUser`, `winsta0\default`)로 표준 사용자 `hong`의 세션에 |

- 방식 B의 서버 출력은 화면에 없으므로 `C:\mcpmon\logs\<날짜>.jsonl`의 `system` 줄(`collector.status`, `collector.mode`, `agent.launched`, `agent.launch_failed`)로 상태를 봅니다. 수집기 상태는 관리 화면 **세션 → 수집 상태** 표에도 나옵니다.
- 멈추기: 방식 A는 Ctrl+C(에이전트에 `exit` 전달 → 고지 창 닫힘 → 서버 종료). 방식 B는 `schtasks /end /tn mcpmon-p4`(작업 종료는 프로세스 강제 종료라 `exit`가 전달되지 않을 수 있음 → P5-14 비고 참고).
- **점검 후 정리:** `schtasks /delete /tn mcpmon-p4 /f`. 감사 정책을 원래대로 되돌릴지는 기기 소유자가 정합니다.
- 로그 확인 예(PowerShell): `Get-Content C:\mcpmon\logs\$(Get-Date -Format yyyy-MM-dd).jsonl -Wait | Select-String '"cat":"session"'`.

## 3. 항목

각 행: 절차 / 기대 / 결과 / 비고. "보드" = `http://<host>:8701/`(익명), "세션 화면" = 관리 화면 `/admin/sessions`(MCP 개발자 이상, 두 채널).

### 3.1 P4 — 세션 수집 (§11 P4)

| # | 절차 | 기대 | 결과 | 비고 |
|---|---|---|---|---|
| P4-1 | 다른 PC에서 `hong`으로 RDP 접속. 그 PC의 브라우저에 보드를 미리 열어 둡니다 | **2초 안에** 보드 `● 접속 중`과 카드: 사용자·도메인·클라이언트 PC명·IP 전체·PTR(조회되면 몇 초 뒤)·접속 시각·해상도(`1920×1080, 32비트` 꼴)·고지 상태. 세션 화면 이력에 `logon` 행 | 대기 | **§11 P4 완료 기준.** 2초를 넘기면 V6 비용(LSM 이벤트에서 `nudge()`) |
| P4-2 | RDP 창에서 연결 끊기(로그오프 아님) | 보드 `○ 접속자 없음`(끊긴 세션은 보드에 안 나옴, V7). 세션 화면 이력 종료 = `disconnect`, **현재 세션**에는 "연결 끊긴 시각"과 함께 남음 | 대기 | |
| P4-3 | 같은 계정으로 다시 연결 | 보드 다시 `● 접속 중`, 이력에 새 `reconnect` 행, 고지 다시 표시(P5-1) | 대기 | |
| P4-4 | 시작 → 로그아웃 | 보드 `○ 접속자 없음`, 이력 종료 = `logoff`, `session` `agent_stopped`(에이전트 정상 종료, `tamper` 아님) | 대기 | |
| P4-5 | 잘못된 암호로 RDP 시도 2번 | 세션 화면 **로그인 실패** 표에 2행(4625: 사용자·IP·워크스테이션·로그온 유형·상태 코드), `session` `logon_failed` 2줄(같은 `record_id`는 1줄, F19) | 대기 | Security 로그 = SYSTEM/관리자만(방식 A·B 모두 가능) |
| P4-6 | P4-1–P4-4 동안의 `session` 로그를 확인 | 1149(`rdp_auth_ok`)·21(`lsm_logon`)·24(`lsm_disconnect`)·25(`lsm_reconnect`)·4624 유형 10(`logon`)·4778(`session_reconnect`)·4779(`session_disconnect`) 줄이 **이벤트 시각**(`ts`)으로 남음. 23(`lsm_logoff`)·4634/4647(`logoff`/`user_logoff`)도 | 대기 | Task 8: LSM·RCM·Security 매핑은 녹화 XML로만 확인 |
| P4-7 | IPv6로 접속(가능하면: `mstsc /v:[<IPv6 주소>]`) | 카드·이력의 `client_ip`가 올바른 IPv6 전체(V9: `WTSClientAddress.Address[2:18]`) | 대기 | Task 3: IPv6 오프셋과 RDP 전용 필드(PC명·빌드·해상도)는 합성 바이트로만 확인 |
| P4-8 | 처음 쓰는 PC·IP에서 첫 접속 → 끊고 같은 PC에서 다시 접속 | 첫 접속 카드에만 `처음 보는 IP`·`처음 보는 기기` 배지, 두 번째는 없음 | 대기 | |
| P4-9 | 관리자 계정으로 **콘솔에 로그온해 둔 상태**에서 같은 계정으로 RDP 접속(콘솔 세션을 RDP가 가져감) | 이력 종류가 무엇으로 남는지 기록(설계상 `--collect-console` 없이 처음 보이는 세션이라 `logon`). 실제로는 기존 로그온의 재연결이므로 `reconnect`가 맞는지 판단 | 대기 | Task 4 노트. 잘못이면 트래커 규칙 1 보정 |
| P4-10 | P4-1 세션에서 2분 가만히 둔 뒤 보드 카드 확인 | 유휴 시간 `2분`(분 단위, V10). 입력하면 `—`로 돌아옴 | 대기 | Task 5: 이 PC의 콘솔은 WTS `LastInputTime`이 없어 `idle_sec` = null. RDP 세션에서 값이 나오는지 |
| P4-11 | 접속 중 잠금(Win+L) → 해제 | 카드 상태 `잠김` → `사용 중`. `session` `lock`/`unlock`이 `source: "wts"`와 `source: "eventlog:4800"`/`"eventlog:4801"` 둘 다(V21) | 대기 | 4800/4801은 "Other Logon/Logoff Events" 감사가 켜져 있어야 함 |
| P4-12 | 서버를 내렸다가 다시 올림(이 사이 Security 이벤트 몇 개 발생) | 재개 뒤 놓친 이벤트가 북마크(`C:\mcpmon\data\collector-state.json`)부터 이어 기록되고, 24시간보다 오래된 것은 버림(V12) | 대기 | Task 7: Security 채널 재개는 관리자·SYSTEM에서만 확인 가능 |
| P4-13 | 역방향 DNS가 없는 IP(또는 DNS 서버 차단)에서 접속 → 서버 종료 | 카드에 PTR 없이 표시, 서버 종료가 DNS 대기로 수 초 넘게 늦어지지 않음 | 대기 | Task 5: DNS 제한 시간(2초) 때문에 종료가 몇 초 늦을 수 있음 |

### 3.2 P5 — 행동 로그 + 고지 (§11 P5)

| # | 절차 | 기대 | 결과 | 비고 |
|---|---|---|---|---|
| P5-1 | (방식 B) `hong`으로 로그온, 끊고 재연결 | 로그온·재연결마다 고지 창이 **화면 중앙 최상위**로 뜸, Edge 첫 실행 화면 없음, 창이 뜨고 내용 표시까지 **< 300ms**(§15). `notice` `notice_shown`(`kind`, `version`, `attempt` = 1) | 대기 | **§11 P5 완료 기준.** Task 15: 서비스가 띄운 에이전트의 `SetForegroundWindow`가 포그라운드 잠금으로 거부될 수 있음(최상위는 적용) |
| P5-2 | 고지 창에서 **확인** | `notice_acknowledged`(`elapsed_ms`), 창 닫힘, 보드 카드·세션 화면 사전 고지 = `확인함`(이력은 "N초 만에 확인") | 대기 | |
| P5-3 | 확인 전에 창의 X로 닫기 | **1초 뒤 다시 뜸**, `notice_unacknowledged`(`reason: "window_closed"`), 다시 뜬 창의 `attempt` = 2 | 대기 | C1: 창은 Edge 프로세스 전체에서 제목으로 찾음 |
| P5-4 | 확인 전에 작업 관리자에서 에이전트(`python.exe … mcp_agent`) 종료 | `tamper` `agent_exited`, 수 초 안에 재기동(`agent.launched`), 고지 재표시(`notice_unacknowledged` `agent_exited` 뒤 새 `notice_shown`). 대시보드 **우회 탐지 이벤트** 카드에 한 줄 | 대기 | **§11 P5 완료 기준.** 표준 사용자 `hong`이 자기 세션의 에이전트를 끌 수 있는지도 기록 |
| P5-5 | 에이전트 사칭: `hong`이 자기 세션의 에이전트 토큰을 얻었다고 가정합니다(토큰은 환경 변수로 넘어가 에이전트가 읽자마자 지우므로, 같은 사용자가 자기 에이전트 프로세스 메모리를 덤프해 43자 토큰을 찾는 정도의 공격). 그 토큰을 다른 세션(콘솔 관리자)의 PowerShell로 옮겨 `Invoke-WebRequest -Method Post http://127.0.0.1:8700/api/agent/heartbeat -Headers @{"X-Agent-Token"="<토큰>"} -Body '{"idle_sec":0,"locked":false}' -ContentType application/json` | **403**, `tamper` `agent_impersonation`(요청 피어의 세션 ≠ 토큰의 세션). `hong`의 진짜 에이전트는 계속 정상 | 대기 | V4. Task 12: 피어를 못 찾는 경우(연결 표 경합)도 403 + `agent_impersonation`이므로, 정상 사용 중 **오탐이 없는지** 하루 정도 로그를 봄 |
| P5-6 | (방식 B) `hong` 세션에서 메모장 실행·종료 | `activity.process` `start`/`stop`, `source: "wmi:trace"`, 명령줄·`exit_code` 포함, 세션 맥락(`user`, `client_ip`) | 대기 | Task 9: trace 모드는 관리자·SYSTEM. 방식 A(관리자 PowerShell)에서도 trace인지 `system` `collector.mode` 줄로 확인 |
| P5-7 | `cmd /c dir`, `cmd /c deploy.bat`(빈 배치 파일), cmd 창에서 `ping 127.0.0.1 -n 1` | `activity.command` `process_cmdline`(4688): `cmd.exe /c dir`, `cmd.exe /c deploy.bat`, `PING.EXE`(부모 셸 cmd). `dir` 내부 명령 자체는 없음(§2 #7) | 대기 | Task 10: 실제 4688 + "명령줄 포함" 정책 |
| P5-8 | PowerShell에서 `Get-Process \| Select -First 1` | `activity.command` `script_block`(4104), `text`에 원문 | 대기 | Task 10 |
| P5-9 | 창 전환·최소화·복원·제목 바뀌는 앱(브라우저 탭 전환) | `activity.window` `foreground`/`minimize`/`restore`/`title`, 병합되어 과도하지 않음(전경 300ms·제목 1초) | 대기 | Task 16: 실제 RDP에서 `GetForegroundWindow`가 0이 아닌지, 제목이 엉뚱한 창에 붙지 않는지 |
| P5-10 | 5분 동안 입력 없음 → 마우스 움직임 | `activity.idle` `idle` → `active` | 대기 | V26 |
| P5-11 | 관리자 PowerShell: `auditpol /set /subcategory:"Process Creation" /success:disable`, `wevtutil cl Application`, 레지스트리 `ProcessCreationIncludeCmdLine_Enabled`를 0으로 | `tamper` `audit_policy_changed`(4719), `log_cleared`(System 104), 60초 안에 `audit_config_changed`. 끝나면 셋 다 되돌림 | 대기 | Task 14: 실제 4719/1102/104와 `install.ps1` 뒤 레지스트리 값. 그룹 정책 새로 고침(`gpupdate`) 때 4719가 잡음처럼 뜨는지도 기록 |
| P5-12 | `C:\mcpmon\scripts\<id>\start.ps1` 직접 수정, `C:\mcpmon\logs\<어제>.jsonl` 뒷부분 잘라내기 | 60초 안에 `script_file_changed`, `log_file_truncated` | 대기 | 우회 탐지 기준값은 메모리에만 있음 → 서버가 꺼진 동안의 변경은 잡지 못함(Plan 5 carry) |
| P5-13 | 성능: 접속 1명, 유휴 60초 평균 `Get-Counter '\Process(python*)\% Processor Time' -SampleInterval 1 -MaxSamples 60`. 창을 빠르게 30번 전환 | 서비스 CPU < 2%, 에이전트 CPU < 1%. `activity.window` 줄이 병합됨(30줄보다 훨씬 적음) | 대기 | `% Processor Time`은 코어 합산이라 논리 코어 수로 나눔 |
| P5-14 | 서비스(방식 B는 `schtasks /end` 후 `/run`) 재시작, `hong`은 접속 중 | 재시작 뒤 `existing` 연결과 고지(V8), 이전 미확인 고지는 `notice_unacknowledged` `service_restart`, 이전 연결은 `service_stop`으로 닫힘 | 대기 | 강제 종료면 에이전트가 `exit`를 못 받아 이전 Edge 고지 창이 남을 수 있음(아래 X-3) |

### 3.3 추가 점검 (구현 과제 노트에서 모음)

| # | 절차 | 기대 | 결과 | 비고 |
|---|---|---|---|---|
| X-1 | 정상 종료: 고지 창이 떠 있는 동안 (방식 A) 서버를 Ctrl+C로 멈춤. `WtsLauncher` 경로는 Plan 5 서비스 호스트가 생긴 뒤 서비스 정지로 같은 확인 | 에이전트가 `exit`를 받아 고지 창을 닫고 끝남(창이 남지 않음), 서버가 2초 유예 안에 끝남 | 대기 | Task 19: `WtsLauncher` 경로의 창 닫기는 이 PC에서 확인 못 함. Plan 5: 서비스 정지는 `ShutdownSequence.request`로 |
| X-2 | 응답 없는 에이전트: 작업 관리자에서 에이전트 **일시 중단**(리소스 모니터 → 프로세스 일시 중단) 30초 이상 | `agent_unresponsive` 한 번 후 강제 종료·재기동(우리가 죽인 것은 `agent_exited` 아님, V18) | 대기 | |
| X-3 | X-2 뒤 화면 확인 | 죽은 에이전트가 띄운 Edge 고지 창이 남는지 기록(남으면 다음 고지와 겹침) | 대기 | Task 13/15: `TerminateProcess`는 Edge 트리에 닿지 않음. 남으면 Edge를 kill-on-close Job Object에 넣는 방안 |
| X-4 | 새 Windows 사용자로 첫 로그온(Edge를 한 번도 연 적 없는 프로필) | 고지 창에 Edge 첫 실행·로그인 권유 화면 없음, 창을 닫은 뒤 Edge가 백그라운드에 남아 다음 표시를 방해하지 않음 | 대기 | Task 15: "백그라운드에서 계속 실행" 코너 케이스 |
| X-5 | Edge가 없는 경우(가능하면 별도 VM) | 기본 브라우저 탭으로 고지가 열림(V25, 최상위 아님) | 대기 | |
| X-6 | `pwsh`(PowerShell 7)을 설치하고 P5-8 반복 | `PowerShellCore/Operational` 채널의 4104도 `script_block`. 설치 전에는 수집 상태에 채널 없음으로 남고 60초마다 재시도 | 대기 | Task 10, V12 |
| X-7 | 32K자보다 긴 스크립트 블록 실행(긴 문자열 변수를 담은 스크립트 파일) | 여러 조각 4104가 하나의 `script_block`(`parts` > 1)으로 합쳐짐, 65,536자에서 `truncated` | 대기 | Task 10 |
| X-8 | 도메인 가입 PC(가능하면)에서 도메인 계정으로 4688·4104 발생 | 첫 도메인 SID 조회 때 서버 응답이 멈추지 않음(보드 갱신 지연 없음) | 대기 | Task 10: `sid_to_account`가 루프 스레드에서 실행됨 |
| X-9 | localhost 로그인: `hong` 세션의 브라우저로 `http://127.0.0.1:8700` 로그인·로그아웃 | `auth` 줄에 `windows_user` = `<PC>\hong`(V20) | 대기 | |
| X-10 | (방식 A) `--agent-launcher local`에서 `hong`이 따로 접속 | `agent.launch_failed`(`session_mismatch`) **한 줄**, 백오프 재시도 없음(F22) | 대기 | |

## 4. 알려진 한계 (V3·V4, §2 #4)

- 고지 창은 **Edge 앱 창**(`--app`, WebView2와 같은 Chromium 엔진)이라 다른 앱 위에 떠 있어도 **진짜 모달은 아닙니다**. 사용자가 닫으면 1초 뒤 다시 뜨고 그 사실이 남습니다(`window_closed`). 진짜 모달이 필요하면 `NoticeWindow` 구현만 pywebview(WebView2 호스트)로 바꿉니다(V3).
- 에이전트↔서비스는 Named Pipe가 아니라 **Local 채널(127.0.0.1:8700) HTTP**입니다. 인증은 실행마다 새 토큰 + 요청 TCP 피어 → 프로세스 → 세션 ID 검증입니다(V4). 연결 표 조회가 실기기에서 불안정하면(P5-5 오탐) 전송만 Named Pipe로 바꿉니다.
- **관리자 권한 사용자**는 에이전트·감사 정책·이벤트 로그를 끌 수 있습니다. 우리는 그 사실을 기록하고 화면(대시보드 우회 탐지 카드, SSE `tamper`)에 알릴 뿐 막지 못합니다(§2 #4). 외부 알림(토스트·메일·웹훅)은 추후입니다.
- cmd 내부 명령(`dir`, `cd`, `del` …)은 수집하지 않습니다(§2 #7). WMI poll 모드(관리자 아님)에서는 1초 안에 끝난 프로세스가 `activity.process`에 없고 4688에만 남습니다(V13).
- 이벤트가 쏟아지면 수집 큐(소스별 1만 개)는 오래된 것부터 버리고 그 수를 `collector.dropped`로 남깁니다(V11). §7 "이벤트 유실 0"은 이 상한 안에서의 목표입니다.
