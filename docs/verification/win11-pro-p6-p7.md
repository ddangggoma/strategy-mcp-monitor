# Win 11 Pro 실기기 점검표 — P6(로그 조회·보존)·P7(배포·하드닝)

- **대상:**
  - `docs/PLAN.md` v0.8 §11 P6·P7 완료 기준
  - Plan 5(`docs/superpowers/plans/2026-11-08-plan5-logs-retention-packaging.md`) 부록 A W1–W41
  - 운영 문서 `docs/ops/OPERATIONS.md`
- **작성:** Plan 5 Task 16 (2026-11-07).
  - 개발 PC는 **Windows 11 Home, 관리자 아님, Smart App Control 켜짐**입니다. 그래서 서비스 설치, SCM, SYSTEM 실행, ACL, 감사 정책, 방화벽을 실제로 바꾸거나 실행할 수 없습니다.
  - 그래서 **모든 결과 칸은 `대기`**입니다(W38).
- **자동 테스트가 이미 확인한 것:**
  - 설치·제거 스크립트: `-DryRun` 계획 전체, 관리자가 아니면 아무것도 바꾸지 않고 종료, 명령줄 인용(`tests/test_install_scripts.py`)
  - 배포 묶음: 관리자 없이 실행, `--version`, 보드 제공, `PYTHONPATH` 무시, SCM 밖 `service` 종료 코드 2(`-m bundle`)
  - 서비스 호스트: 가짜 SCM, 다른 스레드의 정지, 종료 코드 3/4/5
  - 100만 건 성능(`docs/verification/perf-p6.md`), 웹 E2E
  - 이 점검표는 그 밖에 남은 것입니다. 곧 **깨끗한 Win 11 Pro에 실제로 설치해야 하는 확인**입니다.
- **Plan 6 이후(1.0.0, 2026-11-08):** 이 점검표는 데스크톱 설치 상태(`docs/verification/win11-pro-p8.md` P8-3)로 다시 수행합니다. 바꿔 읽기(그 문서 §3): `install.ps1` → `mcp-monitor.exe install`, `uninstall.ps1` → `mcp-monitor.exe uninstall`, `audit-policy.ps1 -Enable` → `mcp-monitor.exe audit-policy --enable`, `mcp-agent.exe` → `mcp-monitor.exe agent`, 서버 exe `bin\monitor\mcp-monitor.exe` → `bin\monitor\mcp-monitor-server.exe`. 이미 적은 결과 칸은 그대로 둡니다.
- **결과를 채우는 법:**
  - `결과` 칸에 `통과` / `실패` / `해당 없음`과 날짜를 적습니다.
  - 실패면 `비고`에 출력, 이벤트 뷰어 항목, `C:\ProgramData\MCP Monitor\logs\<날짜>.jsonl`의 해당 줄을 남깁니다.
  - 실패 항목은 `docs/superpowers/plans/carry-forward.md`의 "After Plan 5"에 새 항목으로 옮깁니다.

## 1. 준비

1. **기기:** **깨끗한** Windows 11 Pro VM(Hyper-V 등, 스냅숏 권장) 또는 실기기.
   - Smart App Control 상태를 기록합니다. `HKLM\SYSTEM\CurrentControlSet\Control\CI\Policy\VerifiedAndReputablePolicyState`의 값이 1이면 켜짐, 2면 평가, 0이면 꺼짐입니다.
   - 가능하면 **켜진 상태**로 점검합니다(P7-8).
   - 같은 네트워크에 RDP 클라이언트와 브라우저로 쓸 다른 PC 1대를 둡니다.
2. **계정:**
   - 관리자 1개(점검 진행, 설치).
   - RDP용 **표준 사용자** `hong`(Administrators에 넣지 않음).
   - 설정 → 시스템 → 원격 데스크톱을 켜고, `hong`을 "원격 데스크톱 사용자"에 추가합니다.
3. **묶음:**
   - `mcp-monitor-1.0.0.zip`과 `mcp-monitor-1.0.0.zip.sha256`을 VM에 복사합니다.
   - `Get-FileHash -Algorithm SHA256 .\mcp-monitor-1.0.0.zip`의 값과 `.sha256`의 값이 같은지 확인하고, `C:\Temp\mcp-monitor-1.0.0`에 풉니다.
   - 업그레이드 점검(P7-9)용으로 **다시 빌드한 두 번째 묶음**이 있으면 좋습니다. 같은 버전을 다시 빌드한 것이어도 됩니다.
4. **설치 전 기록**(P7-10에서 되돌림 확인용):
   - `auditpol /backup /file:C:\Temp\before.csv`
   - `reg query HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System\Audit /v ProcessCreationIncludeCmdLine_Enabled`(없을 수 있음)
   - `reg query HKLM\SOFTWARE\Policies\Microsoft\Windows\PowerShell\ScriptBlockLogging /v EnableScriptBlockLogging`
   - `wevtutil gl Security`
5. 이하 `<I>` = `C:\Program Files\MCP Monitor`, `<D>` = `C:\ProgramData\MCP Monitor`.

## 2. 항목

각 행은 절차 / 기대 / 결과 / 비고입니다. 명령은 따로 적지 않으면 관리자 PowerShell에서 실행합니다.

### 2.1 P7 — 배포·하드닝 (§11 P7)

| # | 절차 | 기대 | 결과 | 비고 |
|---|---|---|---|---|
| P7-1 | 관리자 PowerShell에서 `powershell -NoProfile -ExecutionPolicy Bypass -File C:\Temp\mcp-monitor-1.0.0\install\install.ps1 -OpenFirewall`을 **한 번** 실행 | 20단계(`-OpenFirewall` 포함, 기본은 19단계)가 모두 `[실패]` 없이 끝나고, 마지막 줄이 `설치 완료: http://127.0.0.1:8700/admin/setup …`, 종료 코드 0. 그 주소가 열리고 첫 Admin을 만들 수 있음. 로그인 코드는 `<D>\data\dev\otp-outbox.log` | 대기 | **§11 P7 완료 기준.** 먼저 `-DryRun`으로 같은 단계 목록이 나오는지 보고 출력을 첨부합니다 |
| P7-2 | 재부팅 → **아무도 로그인하지 않은 채** 2분 대기 → 다른 PC에서 `http://<VM>:8701/` | 지연 자동 시작으로 서비스가 실행 중(`sc.exe query mcp-monitor` = `RUNNING`), 보드 표시. `-OpenFirewall` 없이 설치했다면 다른 PC에서는 열리지 않음 | 대기 | 방화벽 규칙은 도메인·개인 프로필만. VM 네트워크가 "공용"이면 열리지 않는 것이 맞음 |
| P7-3 | `sc.exe qc mcp-monitor`, `sc.exe qfailure mcp-monitor`. 웹(Local Admin) **설정 → 부팅 시작 유형**을 `수동`으로 저장 → `sc.exe qc` | qc: `START_TYPE 2 AUTO_START (DELAYED)`, `BINARY_PATH_NAME` = `"<I>\bin\monitor\mcp-monitor-server.exe" service --root "<D>" --local-port 8700 --external-port 8701`(PowerShell 설치 묶음은 `mcp-monitor.exe`), `SERVICE_START_NAME LocalSystem`. qfailure: `RESET_PERIOD 86400`, 재시작 5000/10000/60000ms. 저장 뒤 `DEMAND_START`, 설정 화면 **Windows 서비스** 줄이 `수동`이고 불일치 안내 없음, `admin.audit` `service_start_type_apply`, `system` `service.start_type` `applied` | 대기 | Task 8·12: 실제 SCM 적용은 단위 테스트로만 확인했음. 다시 `자동(지연된 시작)`으로 되돌림 |
| P7-4 | `icacls "<D>"`, `icacls "<D>\logs"`. `hong`으로 RDP 접속해 탐색기에서 `<D>\logs`와 `<D>\data` 열기, `type "<D>\data\dev\otp-outbox.log"` | `NT AUTHORITY\SYSTEM:(OI)(CI)(F)`, `BUILTIN\Administrators:(OI)(CI)(F)`만, 상속 없음, 소유자 Administrators. `hong`은 모두 **액세스 거부** | 대기 | W30: 한국어 Windows에서도 SID로 지정되어 같은지(`NT AUTHORITY\SYSTEM` 대신 한국어 이름이 보여도 됨) |
| P7-5 | `auditpol /get /category:*`, 레지스트리 두 값(`reg query …`), `wevtutil gl Security`, `wevtutil gl Microsoft-Windows-PowerShell/Operational` | 프로세스 만들기 = 성공, 로그온 = 성공 및 실패, 로그오프 = 성공, 기타 로그온/로그오프 이벤트 = 성공 및 실패, 감사 정책 변경 = 성공. `ProcessCreationIncludeCmdLine_Enabled = 1`, `EnableScriptBlockLogging = 1`. `maxSize: 268435456` / `67108864`. `<D>\data\auditpol-backup.csv`와 `install-state.json`(`registry_before`가 1.4의 값)이 있음 | 대기 | GUID로 켜므로 한국어 범주 이름으로 보임. Task 14: 실제 `auditpol`·`wevtutil` 실행은 여기서 처음 |
| P7-6 | 작업 관리자 → 세부 정보에서 `mcp-monitor-server.exe`(SYSTEM; PowerShell 설치 묶음은 `mcp-monitor.exe`) **작업 끝내기** | 약 5초 뒤 새 PID로 다시 실행. 시스템 로그 `Service Control Manager` 7031(복구 동작 수행). 보드가 다시 응답 | 대기 | 하루 안에 세 번 넘게 죽이면 세 번째(60초) 뒤 멈춤 → 기록. W17: MCP `FAILED`·자동 조치 횟수가 초기화되는지도 확인 |
| P7-7 | 다른 PC에서 보드를 열어 둔 채 `hong`으로 RDP 접속 | **2초 안에** 보드 `● 접속 중`과 카드. `hong` 세션에 `<I>\bin\agent\mcp-agent.exe`(사용자 `hong`)가 뜨고 고지 창 표시 | 대기 | Plan 4 V6 + Task 8 `SESSIONCHANGE → nudge`. 작업 관리자에서 에이전트 경로가 Program Files인지(Task 9·13: 사용자가 읽을 수 있는 위치) |
| P7-8 | SAC가 켜진 상태에서: 설치 전 `C:\Temp\mcp-monitor-1.0.0\bin\monitor\mcp-monitor.exe --version`, 설치 후 서비스 시작, P7-7의 에이전트 실행 | 셋 다 막히지 않음(`mcp-monitor 1.0.0`). `CodeIntegrity/Operational`에 `mcp-monitor.exe`·`mcp-agent.exe` 차단 기록 없음 | 대기 | W26: 개발 PC에서는 서명 없는 PyInstaller exe가 SAC를 통과했음(Task 13 스파이크). 막히면 묶음 방식 B(python.org embeddable, PSF 서명)로 다시 만들어야 함 → carry-forward |
| P7-9 | 데이터를 조금 만든 뒤(MCP 1개 등록, 스크립트 저장, 로그 몇 줄) 새 묶음의 `install.ps1`을 같은 매개변수로 다시 실행 | 단계 `stop_existing` 실행, `service_install`이 `config`(DryRun `service_mode: "update"`). 끝난 뒤 MCP·스크립트·사용자·로그 유지, `auditpol-backup.csv`는 처음 파일 그대로(수정 시각), `install-state.json`의 `registry_before`도 처음 값. 방화벽 규칙이 둘로 늘지 않음 | 대기 | Task 14: 재설치 보존 로직은 DryRun 테스트로만 확인 |
| P7-10 | ① `& "<I>\install\uninstall.ps1"` → ② 다시 설치 → `& "<I>\install\uninstall.ps1" -RemoveData -RestoreAuditPolicy` | ①: 서비스·방화벽 규칙·`<I>` 삭제, `<D>` 그대로. ②: `<D>`와 `C:\Users\*\AppData\Local\mcp-monitor` 삭제, `auditpol /get`·레지스트리·로그 크기가 1.4의 기록과 같음(레지스트리 값이 없던 것은 다시 없음) | 대기 | Task 14 concern 3: `hong`의 고지 창(Edge)·에이전트가 아직 파일을 잡고 있으면 `[실패] remove_*` → 비고에 기록하고 다시 실행해 끝나는지 |
| P7-11 | 제거된 상태에서 `hong`(표준 사용자)으로 로그인해 `mkdir "C:\ProgramData\MCP Monitor"` → `icacls "C:\ProgramData\MCP Monitor" /grant "*S-1-1-0:(OI)(CI)F"` → `mkdir "C:\ProgramData\MCP Monitor\scripts"`. 관리자로 `install.ps1` 실행. 이어서 그 폴더를 지우고 `hong`이 `mklink /J "C:\ProgramData\MCP Monitor" C:\Users\hong\x`로 정션을 만든 뒤 다시 설치 | 두 번 다 종료 코드 2, `오류: -DataRoot: …`(소유자 `hong` / 정션) 한 줄, 아무 단계도 실행되지 않음(서비스·ACL 그대로). 폴더를 지우고 다시 설치하면 정상 설치되고 P7-4와 같은 ACL | 대기 | 플랜 리뷰 C1: 미리 만든 데이터 루트의 추가 ACE·정션이 SYSTEM 권한 상승으로 이어지지 않는지. DryRun·임시 폴더 테스트로만 확인했음 |
| P7-12 | `hong` 세션에서 30초 넘게 도는 스크립트(MCP 조치)를 실행시킨 채 ① `sc.exe stop mcp-monitor`, 다시 시작 후 ② Windows **다시 시작** | ①: `sc.exe query`가 `STOP_PENDING`의 `CHECKPOINT`가 늘다가 `STOPPED`, "제때 응답하지 않음" 없음, 그 뒤 SCM이 다시 시작하지 않음(시스템 로그 7036 중지, 7031 없음). ②: 재부팅 뒤 로그에 `monitor.stop`(`killed`)과 그 전 줄들이 남아 있음 | 대기 | 플랜 리뷰 I4·I5: 정지 중 오류에도 `STOPPED` 보고, `STOP_PENDING` 체크포인트, PRESHUTDOWN(시간 제한 60초)으로 종료 순서가 끝까지 실행되는지 |
| P7-13 | 제거된 상태에서 관리자로 ① `install.ps1 -DataRoot "D:\apps\MCP Monitor"`(`D:\apps`는 데이터 드라이브 기본 ACL, `Authenticated Users:(M)` 상속), ② 같은 명령에 `D:\apps`가 없을 때, ③ `-DataRoot "\\localhost\C$\ProgramData\MCP Monitor"`와 `subst S: C:\ProgramData` 뒤 `-DataRoot "S:\MCP Monitor"`. 이어서 정상 설치한 PC에서 **관리자 아닌** PowerShell로 `install.ps1 -DryRun` | ①③: 종료 코드 2, `오류: -DataRoot: …`(①은 `D:\apps`와 `S-1-5-11`, ③은 로컬 드라이브 경로 아님 / 로컬 고정 디스크 아님), 아무 단계도 실행되지 않음. ②: 설치되고 `icacls D:\apps`가 SYSTEM·Administrators만(상속 없음), `icacls "D:\apps\MCP Monitor"`가 P7-4와 같은 ACL. DryRun: 종료 코드 0, 계획 JSON의 `notes`와 표준 오류 `참고:` 한 줄 | 대기 | 재검토 1–4: 데이터 루트를 처음부터 최종 ACL로 만들기, 상위 폴더 검사, 장치·UNC·subst 경로 거부, 관리자 아닌 DryRun. 임시 폴더·가짜 볼륨 목록 테스트로만 확인했음(subst 드라이브는 만들지 않음) |

### 2.2 P6 — 로그 조회·보존 (§11 P6)

| # | 절차 | 기대 | 결과 | 비고 |
|---|---|---|---|---|
| P6-1 | P7-7 뒤 `hong` 세션에서 메모장·PowerShell 명령 몇 개, 잘못된 암호로 RDP 2번, 웹 로그인 실패 1번. 관리 화면 **로그**: 사용자 `hong` 필터, 카테고리 칩, 키워드(`Get-Process`), 히스토그램 드래그로 범위 선택, 행 상세, 타임라인 보기, CSV·JSONL 내보내기. **감사 로그**(관리 작업/로그인 탭). **대시보드 → 로그인 실패 추이** | 실제 수집 로그가 1–2초 안에 보이고 필터·드래그가 URL에 남음(링크 복사 → 다른 PC 브라우저에서 같은 결과). CSV는 Excel에서 한글이 깨지지 않음. 감사 로그에 `logs_view`·`logs_export`. 카드에 원격 데스크톱 2건 + 웹 1건 | 대기 | External 채널(다른 PC, MCP 개발자)과 Local 채널 둘 다. 640×600 창에서도 가로 스크롤 없이(W41) |
| P6-2 | 설정에서 압축 시작을 7일, 보존 기간을 7일로 낮춤(그 전에 `<D>\logs`에 8일 이상 된 날짜 파일을 관리자 PowerShell로 복사해 둠: 예 `Copy-Item <오늘>.jsonl <10일 전>.jsonl`) → 미리보기 확인 → **줄이고 삭제** | 대화 상자에 삭제될 기간·파일·용량·기록 건수. 확인 뒤 **몇 초 안에** 그 파일 삭제, 로그 화면에서 그 날짜가 사라짐. `system` `retention.run`·`admin.audit` `retention_purge`(날짜 범위·건수). `tamper` `log_file_removed` **없음** | 대기 | 손으로 만든 파일은 처음엔 우회 탐지 기준값에 없어 `log_file_*` 줄이 생길 수 있음 — 정리로 인한 것이 아닌지 시각으로 구분. 끝나면 180일로 되돌림 |
| P6-3 | (선택) 저장소 체크아웃이 있으면 `server\`에서 `uv run python -m pytest -m perf -q` | 통과, 값을 `docs/verification/perf-p6.md` 옆에 기록 | 대기 | 개발 PC 값과 비교. 설치 묶음에는 테스트가 없음 |

### 2.3 추가 점검 (Plan 5 과제 노트에서 모음)

| # | 절차 | 기대 | 결과 | 비고 |
|---|---|---|---|---|
| X7-1 | `hong`의 고지 창이 떠 있는 동안 `sc.exe stop mcp-monitor` | 30초 안에 `STOPPED`. 에이전트가 `exit`를 받아 고지 창이 닫힘(창이 남지 않음). 이전 연결은 `service_stop`으로 닫힘 | 대기 | Plan 4 X-1(`WtsLauncher` 경로), F01: 서비스 정지는 `ShutdownSequence.request`(수집기 → 서버 순) |
| X7-2 | 스크립트가 `Start-Sleep 120`인 MCP의 수동 조치 실행 직후 서비스 정지 | 10초 유예 뒤 스크립트 프로세스 트리(`powershell.exe`와 자식, SYSTEM)가 남지 않음(작업 관리자 세부 정보), `system` `monitor.stop`에 `killed` | 대기 | W21, Task 7 |
| X7-3 | 서비스를 멈추고 관리자 PowerShell에서 `python -m http.server 8700 --bind 127.0.0.1`(또는 아무 프로그램으로 8700 점유) → `sc.exe start mcp-monitor` | 서비스가 곧 끝나고, 응용 프로그램 로그(원본 `mcp-monitor`)에 `mcp-monitor exited with code 3`, 트레이스백 없음. 복구 동작으로 재시작을 시도함(시스템 로그 7031/7034) | 대기 | W23. Task 13 concern 3: SCM 아래에서 `sys.stderr`가 None이어도 죽지 않는지. 끝나면 점유 프로세스를 끝내고 서비스 시작 |
| X7-4 | 서비스가 실행 중일 때 `& "<I>\bin\monitor\mcp-monitor-server.exe" reindex --root "<D>"`(PowerShell 설치 묶음은 `mcp-monitor.exe`) → 서비스 정지 → 다시 실행 → 서비스 시작 | 처음은 종료 코드 4(`data root … is already in use`). 두 번째는 `indexed N rows from M files`, 시작 뒤 로그 화면 정상 | 대기 | W24, 운영 문서 ⑥ |
| X7-5 | 서비스 정지 → `<D>\scripts\<id>\start.ps1` 한 줄 수정, `reg add …\Audit /v ProcessCreationIncludeCmdLine_Enabled /t REG_DWORD /d 0 /f` → 서비스 시작 | 60초 안에 `tamper` `script_file_changed`와 `audit_config_changed`가 `while_stopped: true`로 남음, 대시보드 우회 탐지 카드에 표시. 끝나면 레지스트리 1로, 스크립트는 웹에서 다시 저장 | 대기 | Task 7(F07): 기준값이 `data\tamper-baseline.json`에 남음. Plan 4 P5-12 비고("메모리에만")는 이제 해당 없음 |
| X7-6 | 웹 설정은 `자동(지연된 시작)`인 채 `sc.exe config mcp-monitor start= demand` → 설정 화면 새로 고침 → 서비스 재시작 → 다시 새로 고침 | 처음엔 **Windows 서비스** 줄에 불일치 안내, 재시작 뒤 `sc.exe qc`가 다시 `AUTO_START (DELAYED)`이고 안내 사라짐 | 대기 | W25, Task 12. `disabled`는 `수동`으로 읽힘(Task 8 노트) — `start= disabled`로도 한 번 확인 |
| X7-7 | `audit-policy.ps1 -DryRun -Enable`, 그 뒤 `-Restore "<D>\data\auditpol-backup.csv"` | DryRun 단계가 설치 9–15단계와 같음. Restore 뒤 `auditpol /get`이 1.4의 기록과 같음 | 대기 | Task 14 concern 2: `-Enable` 단독은 바꾸기 전 레지스트리 값을 기록하지 않음(설치 상태 파일이 있을 때만 레지스트리 복원) |
| X7-8 | `-ExternalPort 8711`로 다시 설치 → `netsh advfirewall firewall show rule name=all \| findstr "MCP Monitor"` → 제거 | 규칙 `MCP Monitor (8711)` 추가. 옛 `MCP Monitor (8701)`은 남음(알려진 동작, 운영 문서 ④) — 제거 뒤에도 8701 규칙이 남는지 기록 | 대기 | Task 14 concern 4 |
| X7-9 | 서비스 실행 중 `hong` 세션에서 `& "<I>\bin\monitor\mcp-monitor-server.exe" --root C:\Users\hong\x`(PowerShell 설치 묶음은 `mcp-monitor.exe`) 실행, `<I>`에 파일 만들기 | 콘솔 서버는 실행될 수 있지만(포트가 이미 잡혀 종료 코드 3), `<I>`에는 쓸 수 없음(액세스 거부) | 대기 | W30: SYSTEM이 실행하는 파일을 표준 사용자가 고칠 수 없어야 함 |
| X7-10 | (개발용 주의) 서비스가 설치된 PC에서 서버 테스트를 **관리자 권한으로** 돌리지 않음 | — | 대기 | Task 8 노트: `test_service_host_runs_until_stop`이 실제 SCM을 읽고, 관리자면 테스트 루트의 기본값(`delayed-auto`)을 설치된 서비스에 적용할 수 있음. 실기기에서 테스트를 돌린다면 표준 사용자로 |

## 3. Plan 4 점검표를 서비스 설치 상태로 다시 수행

`docs/verification/win11-pro-p4-p5.md`(P4-1–P4-13, P5-1–P5-14, X-1–X-10)를 **이 점검표의 P7-1 설치 상태에서 다시 수행**합니다. 그 문서는 서비스가 없던 Plan 4 때 쓰였으므로 다음을 바꿔 읽습니다.

- **§1 준비 3. 감사 정책:** 손으로 `auditpol`을 실행하지 않습니다. `install.ps1`이 이미 켰습니다(P7-5). 따로 켜려면 `install\audit-policy.ps1 -Enable`.
- **§1 준비 4–5, §2 실행 방식:**
  - 저장소 체크아웃, `uv sync`, `schtasks` 실행 방식 A·B 대신 설치된 서비스 `mcp-monitor`(SYSTEM, `WtsLauncher`)를 씁니다. 방식 B와 같은 경로입니다.
  - 데이터 폴더는 `C:\mcpmon`이 아니라 `C:\ProgramData\MCP Monitor`입니다.
  - 멈추기와 다시 시작은 `sc.exe stop|start mcp-monitor`입니다(P5-14, X-1).
- **에이전트:** `python.exe … mcp_agent`가 아니라 `<I>\bin\agent\mcp-agent.exe`입니다(P5-4에서 작업 관리자로 끌 대상).
- **P5-12:** 우회 탐지 기준값은 이제 저장됩니다(X7-5). "서버가 꺼진 동안의 변경은 잡지 못함" 비고는 해당 없음.
- **P5-5b:** "서비스 강제 종료"는 작업 관리자의 `mcp-monitor-server.exe`(SYSTEM; PowerShell 설치 묶음은 `mcp-monitor.exe`) 작업 끝내기입니다. 복구 동작이 5초 뒤 다시 띄우므로, ①은 그 5초 안에 점유해야 시작 실패(X7-3과 같음)를 볼 수 있습니다.
- 결과는 그 문서의 `결과` 칸에 날짜와 함께 "서비스 설치 상태"라고 적습니다.
