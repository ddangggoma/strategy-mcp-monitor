# MCP Monitor 운영 문서 (v1.1.0)

이 문서는 설치 폴더의 `docs\OPERATIONS.md`로도 함께 나갑니다. 기준 스펙은 `docs/PLAN.md` v0.9입니다(설치 폴더에는 없음). 1.1.0부터 MCP Monitor는 **실행 파일 하나**(`mcp-monitor-1.1.0.exe`)로 설치·업그레이드·제거·실행합니다. 1.0.0의 PowerShell 스크립트(`install.ps1` 등)는 없습니다.

따로 적지 않으면 경로는 기본값입니다.

| 기호 | 기본값 |
|---|---|
| `<I>` 설치 폴더 | `C:\Program Files\MCP Monitor` |
| `<D>` 데이터 루트 | `C:\ProgramData\MCP Monitor` |
| `<exe>` 설치된 실행 파일 | `<I>\mcp-monitor.exe` |
| `<server>` 서버 실행 파일 | `<I>\bin\monitor\mcp-monitor-server.exe` |

**명령줄에서 결과를 기다리는 법.** `mcp-monitor.exe`는 창 프로그램(GUI 서브시스템)이라, PowerShell은 그냥 실행하면 기다리지 않고 다음 프롬프트로 돌아갑니다. 출력과 종료 코드를 받으려면 **파이프라인 안에서** 실행합니다.

```powershell
& .\mcp-monitor-1.1.0.exe install --dry-run | Write-Output
$LASTEXITCODE
```

`$out = & .\mcp-monitor-1.1.0.exe …`처럼 변수에만 받으면 출력이 비고 `$LASTEXITCODE`도 바뀌지 않습니다. 이 문서의 명령은 모두 `| Write-Output` 형태로 적습니다.

## ① 구성 요약

- **실행 파일 `mcp-monitor.exe`**(Rust, Tauri 2, WebView2, **코드 서명 없음**): 서버 묶음(`bin\monitor\`, `web\`, `docs\`, `bundle.json`)을 압축해 안에 품고, 파일마다 SHA-256을 함께 담습니다. 하는 일은 실행 방식(모드)으로 나뉩니다.

  | 모드 | 누가 | 하는 일 |
  |---|---|---|
  | (인자 없음) | 사람이 더블클릭 | 설치 여부와 버전을 보고 설치·업그레이드 안내 → 승격해 `install --interactive` → 앱 창. 이미 설치돼 있으면 곧바로 앱 창 |
  | `app` | 로그인한 사용자(관리자 아님) | 상태 보드 창(WebView2, 위쪽 **관리 화면** 버튼으로 관리 화면) + 알림 영역 트레이. 시작 메뉴 **MCP Monitor**가 이것 |
  | `install` | 관리자 | 설치·업그레이드·복구 설치(②, ③) |
  | `uninstall` | 관리자 | 제거(④) |
  | `audit-policy` | 관리자 | 감사 정책만 켜기·되돌리기(②) |
  | `agent` | 서비스가 세션마다 실행(사용자 권한) | 고지 창(WebView2)과 창 이벤트·유휴 상태 전송 |

  보조 명령: `autostart on|off`(로그인할 때 트레이 시작), `verify-payload <빈 폴더>`(내장 묶음 검사), `--version`.
- **서비스:** 이름 `mcp-monitor`, 표시 이름 `MCP Monitor`, 계정 `LocalSystem`, 시작 유형 `delayed-auto`.
  - Windows에 원래 있는 Microsoft 서비스 `McpManagementService`와는 **다른 서비스**입니다. 그 서비스는 건드리지 않습니다.
  - 서비스는 `"<server>" service --root "<D>" --local-port 8700 --external-port 8701`로 실행됩니다. 1.0.0의 `bin\monitor\mcp-monitor.exe`는 1.1.0에서 `mcp-monitor-server.exe`로 이름이 바뀌었습니다(같은 이름의 exe가 둘이 되지 않게).
- **두 포트:**

  | 채널 | 주소 | 쓰임 |
  |---|---|---|
  | Local | `127.0.0.1:8700` | 이 PC 안에서만. 전체 관리 기능, 첫 Admin 만들기, 앱 창, 에이전트 통신 |
  | External | `0.0.0.0:8701` | 다른 PC에서. 익명 상태 보드(`/`), 로그인 뒤 운영 기능(로그 조회 포함) |

- **세션 에이전트:** 서비스가 RDP 세션마다 `"<exe>" agent --server http://127.0.0.1:8700 --dialog webview`를 그 사용자 권한으로 띄웁니다(작업 관리자에서 사용자 이름으로 보이는 `mcp-monitor.exe`). 토큰과 서버 키는 명령줄이 아니라 환경 변수로 받습니다.
- **설치 폴더 `<I>`:**

  | 항목 | 내용 |
  |---|---|
  | `mcp-monitor.exe` | 설치기가 자기 자신을 복사한 것. 앱·에이전트·제거에 씁니다 |
  | `bin\monitor\mcp-monitor-server.exe`(+ `_internal\`) | 서버와 Windows 서비스 호스트, `reindex` 명령 |
  | `web\` | 화면(보드·관리·고지) |
  | `docs\OPERATIONS.md` | 이 문서 |
  | `bundle.json` | 버전·빌드 정보, `agent: "desktop"`(서버가 세션 에이전트로 `mcp-monitor.exe agent`를 띄움) |
  | `install.json` | 버전, 포트, 데이터 루트. 관리자가 아닌 앱 모드가 포트를 알려고 읽습니다 |

  Program Files의 기본 권한을 그대로 씁니다. 사용자는 읽고 실행만 할 수 있습니다. 업그레이드는 새 폴더를 통째로 바꿔 끼우므로, 1.0.0의 `bin\agent\`와 `install\`은 사라집니다.
- **그 밖에 설치가 만드는 것:**

  | 위치 | 내용 |
  |---|---|
  | `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\MCPMonitor` | **앱 및 기능** 항목(이름, 버전, 게시자, 크기, 아이콘, 제거 명령) |
  | `%ProgramData%\Microsoft\Windows\Start Menu\Programs\MCP Monitor.lnk` | 시작 메뉴(모든 사용자) → `<exe>`(앱 창) |
  | `%LOCALAPPDATA%\mcp-monitor\webview` | 사용자마다의 앱 창 WebView2 프로필(로그인 쿠키 유지) |
  | `%LOCALAPPDATA%\mcp-monitor\notice-webview` | 사용자마다의 고지 창 WebView2 데이터(InPrivate, 방문 기록 없음) |
  | `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\MCPMonitor` | 선택: 사용자가 트레이에서 켜면 `"<exe>" app --background` |
  | 방화벽 규칙 `MCP Monitor (8701)` | `--open-firewall`일 때만 |

- **데이터 루트 `<D>`**: SYSTEM과 Administrators만 접근합니다.

  | 경로 | 내용 | 백업 |
  |---|---|---|
  | `logs\YYYY-MM-DD.jsonl`, `.jsonl.gz` | 원본 로그. 날짜는 KST 기준이고 하루에 파일 하나입니다 | 필요 |
  | `data\config.db` | 설정, 사용자, MCP, 이력 (SQLite WAL) | 필요 |
  | `scripts\<mcp id>\` | MCP 조치 스크립트 | 필요 |
  | `data\index.db` | 로그 조회 색인. JSONL에서 다시 만들 수 있습니다 | 불필요 |
  | `data\install-state.json`, `data\auditpol-backup.csv`, `data\audit-policy-state.json` | 설치 전 감사 정책·레지스트리 값과 설치 기록. 제거할 때 되돌리는 데 씁니다 | 권장 |
  | `data\collector-state.json`, `data\tamper-baseline.json` | 이벤트 로그 북마크와 우회 탐지 기준값 | 선택 |
  | `data\dev\otp-outbox.log` | 로그인 코드(Dummy OTP 공급자, ⑨) | 불필요 |
  | `data\.lock` | 같은 데이터 루트를 두 프로세스가 함께 쓰지 못하게 막는 잠금 | — |

## ② 설치

**준비**

1. 받은 파일을 확인합니다. `Get-FileHash -Algorithm SHA256 .\mcp-monitor-1.1.0.exe`의 값이 `mcp-monitor-1.1.0.exe.sha256`의 값과 같아야 합니다.
2. **Smart App Control(SAC)과 서명.** 이 exe와 안의 서버 exe에는 **코드 서명이 없습니다**(인증서 없음, D5).
   - 대상 PC의 SAC 상태: `(Get-MpComputerStatus).SmartAppControlState`(`On` / `Evaluation` / `Off`).
   - SAC는 파일마다 평판으로 판단합니다. 개발 PC(SAC 켜짐)에서는 릴리스 exe와 서버 exe가 막히지 않았지만, 다른 PC에서는 다를 수 있습니다. 설치 전에 `& .\mcp-monitor-1.1.0.exe --version | Write-Output`이 `mcp-monitor 1.1.0 (payload <12자리>, release)`를 출력하는지 봅니다.
   - 막히면: "이 앱의 일부가 차단되었습니다" 알림, 아무 반응 없음, 또는 설치 중 `[실패] service_start`. 이벤트 뷰어 `응용 프로그램 및 서비스 로그 → Microsoft → Windows → CodeIntegrity → Operational`에 차단 기록(3076/3077)이 남습니다.
   - 막혔을 때: SAC를 끄지 말고 개발팀에 알립니다. 정해 둔 대안은 (a) 코드 서명 인증서로 서명한 빌드(`install\build-desktop.ps1 -SignThumbprint …`), (b) 1.0.0 방식(PowerShell 설치 묶음, 커밋 c9938d1)입니다. SAC를 끄는 것은 기기 소유자의 보안 결정입니다.
3. **WebView2 런타임.** Windows 11에는 기본으로 있습니다(Evergreen, 업데이트는 Windows가 함). 확인: `Get-ItemProperty 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}' -Name pv`(없으면 `WOW6432Node` 없는 같은 키). 두 키 모두에 버전이 없으면 설치의 `check_os`가 `경고: 이 PC에 설치된 WebView2 런타임을 확인하지 못했습니다 …`를 내고 설치는 계속합니다. 사용자별로만 설치된 런타임은 이 검사가 보지 못하므로, 그때는 경고가 나와도 창이 열립니다. 런타임이 정말 없으면 앱 창이 열리지 않고(오류 상자), 고지는 기본 브라우저로 엽니다(⑨).

**방법 A — 더블클릭(보통은 이것)**

1. 관리자 계정이든 표준 사용자든 `mcp-monitor-1.1.0.exe`를 더블클릭합니다.
2. "MCP Monitor가 이 PC에 설치되어 있지 않습니다. 지금 설치할까요?" 상자에 설치 위치와 데이터 위치가 보입니다. **예**를 누릅니다.
3. UAC 창에서 승인합니다(표준 사용자면 관리자 자격 증명). 아니요를 누르면 아무것도 바뀌지 않습니다.
4. 설치가 끝나면 "설치 완료: http://127.0.0.1:8700/admin/setup 에서 첫 Admin 계정을 만드세요." 상자가 뜨고, **설치된** `<exe>`가 앱 창을 엽니다. 창은 상태 보드를 보여 주고, Admin이 아직 없으면 보드 위의 **초기 설정 시작** 링크로 첫 Admin 만들기 화면에 갑니다. 받은 exe는 그 뒤 끝나므로 지워도 됩니다.
5. 실패하면 상자에 `[실패] <id>: …` 한 줄이 보입니다. ⑩을 봅니다.

**방법 B — 명령줄**

관리자 PowerShell에서:

```powershell
& .\mcp-monitor-1.1.0.exe install --dry-run | Write-Output    # 단계 목록(JSON)만, 관리자 불필요
& .\mcp-monitor-1.1.0.exe install --open-firewall | Write-Output
$LASTEXITCODE
```

- 진행은 `[i/n] <id>` 줄로, 조건이 맞지 않아 건너뛴 단계는 `[i/n] <id>: 건너뜀 (<조건> 아님)`으로 나옵니다. 끝나면 `설치 완료: http://127.0.0.1:8700/admin/setup …`.
- 종료 코드: **0** 성공, **1** 실패·관리자 아님·UAC 거절, **2** 인자 오류(`오류: <옵션>: <이유>`, 아무것도 바꾸지 않음).
- 관리자가 아니면 첫 단계 `require_admin`이 `관리자 권한으로 다시 실행하세요. …`을 출력하고 아무것도 바꾸지 않은 채 1로 끝납니다.
- 관리자가 아닌 PowerShell에서는 `--interactive`를 붙이면 같은 exe가 UAC로 승격해 다시 실행되고, 결과는 메시지 상자로 봅니다. 다시 실행할 때는 해석한 옵션만 넘기고 `--dry-run`은 넘기지 않습니다(승격된 프로세스는 모든 검사를 다시 합니다).

**명령과 옵션**

| 명령 | 옵션 | 동작 | 관리자 | 종료 코드 |
|---|---|---|---|---|
| (인자 없음) | — | 모드 판별 → 설치·업그레이드 안내 → 앱 창. 설치 폴더 안의 exe로는 설치·업그레이드를 안내하지 않고 "다운로드한 mcp-monitor-<버전>.exe로 실행하세요" 상자를 띄웁니다 | 안내에서 예일 때 UAC | 0, 1 |
| `app` | `--background` | 앱 창과 트레이. `--background`면 창 없이 트레이만(로그인할 때 시작). 로그인 세션마다 하나만 뜨고, 두 번째 실행은 기존 창을 앞으로 가져옵니다. **관리자 권한으로 실행 중이면 창을 열지 않고**(인자 없는 실행 포함) `관리자 권한으로 실행 중이라 MCP Monitor 창을 열지 않습니다 …` 상자와 1로 끝납니다: 창·트레이·로그인 시작 항목은 사용자 권한으로만 돕니다. 단, 관리자 권한으로 실행한 인자 없는 실행에서 설치·업그레이드가 성공했으면 창은 열지 않되 `설치를 마쳤습니다. …` 안내 상자와 0으로 끝납니다 | 아니요 | 0, 1 |
| `install` | `--install-dir`, `--data-root`, `--open-firewall`, `--skip-audit-policy`, `--local-port`, `--external-port`, `--dry-run`, `--interactive` | 설치·업그레이드·복구 설치 | 예(`--dry-run` 제외) | 0, 1, 2 |
| `uninstall` | `--install-dir`, `--data-root`, `--remove-data`, `--restore-audit-policy`, `--dry-run`, `--interactive` | 제거(④) | 예(`--dry-run` 제외) | 0, 1, 2 |
| `audit-policy` | `--enable` 또는 `--restore <백업 csv>`, `--data-root`, `--dry-run`, `--interactive` | 감사 정책만 켜기·되돌리기 | 예(`--dry-run` 제외) | 0, 1, 2 |
| `agent` | `--server <url>`, `--dialog webview\|print`, `--url-file <파일>`, `--unreachable-exit-sec <초>` | 세션 에이전트. 서비스가 띄우며, 손으로 쓸 일은 없습니다. `--server`는 `http://` 주소만 받고(서비스는 늘 `http://127.0.0.1:<Local 포트>`를 줌), 호스트는 따로 막지 않습니다 | 아니요 | 0, 1(자기 세션 번호를 알 수 없음, `--dialog webview`), 2, 3, 4, 5 |
| `autostart` | `on` 또는 `off` | `HKCU\…\Run\MCPMonitor`(이 사용자) 켜기·끄기. 설치돼 있어야 합니다 | 아니요 | 0, 1, 2 |
| `verify-payload` | `<빈 폴더>` | 내장 묶음의 해시를 검사하고 그 폴더에 풉니다(설치 없이 서버 exe를 시험할 때). 비어 있지 않은 폴더는 거부 | 아니요 | 0, 1, 2 |
| `--version` | — | `mcp-monitor <버전> (payload <해시 12자리>, release)` | 아니요 | 0 |

**`install` 옵션**

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--install-dir <폴더>` | 앱 및 기능의 설치 위치 → 서비스 binPath → `%ProgramFiles%\MCP Monitor` | 설치 폴더. 비어 있거나 이전 설치 폴더(`bundle.json`)여야 하고, 안에 `logs`·`data`·`scripts` 폴더가 있으면 거부합니다(업그레이드 때 이전 폴더와 함께 지워지므로). Program Files 밖이면 경고합니다(SYSTEM이 실행하는 파일을 사용자가 고칠 수 없어야 함). 로컬 고정 디스크의 경로(`C:\...`)만 받습니다: `\\?\`·`\\.\` 장치 경로, UNC·관리 공유(`\\host\C$`), subst·네트워크·이동식 드라이브, 경로 안의 정션·심볼릭 링크, 드라이브 루트·시스템 폴더는 거부합니다(종료 코드 2). 관리자가 아닌 계정이 지우거나 이름·권한을 바꿀 수 있는 상위 폴더 아래도 거부합니다. 경로 비교는 대소문자를 가리지 않습니다 |
| `--data-root <폴더>` | `<I>\install.json`의 값 → 서비스 binPath → `%ProgramData%\MCP Monitor` | 데이터 루트(로그, DB, 스크립트). 없는 폴더, 빈 폴더, 이전 데이터 루트(`data\mcp-monitor-data-root.json` 또는 `install-state.json`)만 받습니다. 드라이브 루트·시스템 폴더, 설치 폴더(`<I>`, `<I>.staging`, `<I>.old`)와 겹치는 폴더, 정션·심볼릭 링크가 든 폴더, SYSTEM·Administrators·설치하는 계정이 아닌 사용자가 소유한 파일이 든 폴더는 거부합니다(종료 코드 2). 경로 규칙은 `--install-dir`와 같습니다. **데이터 루트 폴더는 미리 만들지 말고 설치가 만들게 합니다**: 이미 있는 데이터 루트나 그 안의 항목을 관리자가 아닌 계정이 지우거나 쓰거나 권한·소유자를 바꿀 수 있으면(예: 관리자가 미리 만든 `D:\MCP Monitor`가 드라이브 루트의 `Authenticated Users:(M)`을 물려받은 경우) 거부합니다. 그 권한으로 설치 전에 열어 둔 핸들은 설치가 ACL을 바꾼 뒤에도 남아, 데이터 루트를 다른 이름으로 옮기고 자기 폴더(`config.db`, 스크립트)를 그 자리에 둘 수 있기 때문입니다. 이 오류가 나면 그 폴더를 지우고 다시 설치합니다(이전 데이터를 지켜야 하면 그 권한을 없애고 PC를 다시 시작한 뒤 설치합니다). **기본값이 아닌 데이터 루트는 관리자만 바꿀 수 있는 폴더 아래나 드라이브 바로 아래(예: `D:\MCP Monitor`)에 둡니다**: 드라이브 루트와 데이터 루트 사이의 폴더를 관리자가 아닌 계정이 지우거나 이름·권한을 바꿀 수 있으면(예: 데이터 드라이브 루트의 `Authenticated Users:(M)`을 물려받은 `D:\apps`) 거부합니다. 드라이브 루트도 확인합니다: 관리자가 아닌 계정에 하위 항목 삭제(`DC`)·권한 변경(`WDAC`)·소유자 변경(`WO`)·모든 권한을 주는 드라이브는 거부합니다(Windows 기본 `C:\`와 데이터 드라이브 루트의 권한은 통과합니다). 없는 상위 폴더는 데이터 루트와 같은 ACL(SYSTEM·Administrators만)로 만듭니다 |
| `--open-firewall` | 꺼짐(이전 설치가 열었으면 유지) | External 포트의 인바운드 방화벽 규칙 `MCP Monitor (<포트>)`를 만듭니다. 도메인·개인 프로필만이고, 공용 프로필은 열지 않습니다 |
| `--skip-audit-policy` | 꺼짐 | 감사 정책, 레지스트리, 이벤트 로그 크기 단계를 건너뜁니다. 이 경우 세션·명령 수집이 줄어듭니다 |
| `--local-port <포트>` | `install.json` → `install-state.json` → binPath → `8700` | Local 채널 포트 |
| `--external-port <포트>` | 같은 순서 → `8701` | External 채널 포트. `--local-port`와 달라야 합니다. 이전 설치가 방화벽을 열었고 포트가 바뀌면 옛 규칙을 지우고(`firewall_delete_old`) 새 규칙을 만듭니다 |
| `--dry-run` | 꺼짐 | 실행할 단계를 JSON으로 출력만 합니다. 관리자가 아니어도 되고 승격하지 않습니다. 이미 설치된 PC에서 관리자 권한 없이 실행하면 데이터 루트 안을 읽을 수 없어, 그 검사를 건너뛰었다는 참고(`notes`, 표준 오류의 `참고:`)와 함께 계획을 출력합니다. 실제 실행 때 `secure_data_root`가 다시 검사합니다 |
| `--interactive` | 꺼짐 | 관리자가 아니면 UAC로 승격해 다시 실행하고, 결과를 메시지 상자로 보여 줍니다(더블클릭 안내와 앱 및 기능이 씁니다) |

**설치 단계**(`--dry-run` 출력의 `id`. 기본 25단계, `--open-firewall`이면 26단계, 방화벽 포트를 바꾸면 27단계, `--skip-audit-policy`면 7단계 적음)

| 단계 | id |
|---|---|
| 확인. `check_os`는 Home 에디션(RDP 호스트 아님), Program Files 밖의 설치 폴더, WebView2 런타임 없음을 **경고만** 하고 계속합니다 | `require_admin`, `check_os` |
| 내장 묶음 풀기. 전체 해시 → 파일마다 크기·SHA-256, 매니페스트 밖 이름·`..`·절대 경로·링크 거부, 새 폴더 `<I>.staging`에만. 서비스는 아직 동작 중입니다 | `stage_payload` |
| 기존 서비스 정지(멈출 때까지 최대 60초) | `stop_existing`(서비스가 있을 때) |
| 설치 폴더 안의 exe로 도는 프로세스 종료(모든 세션의 앱·트레이, 남은 에이전트). 끝낸 프로세스마다 `  끝냄: <pid> <경로>` 줄 | `stop_apps` |
| 폴더 교체. `<I>` → `<I>.old`, `<I>.staging` → `<I>`. 새 폴더 트리를 관리자가 아닌 계정이 쓰거나 지우거나 권한을 바꿀 수 있으면 되돌리고 실패합니다 | `swap_install_dir` |
| 데이터 폴더와 ACL. 루트의 ACL을 처음부터 새로 만들고(소유자 Administrators, 상속 끊음, SYSTEM·Administrators 모든 권한만), 그 아래는 모두 자기 ACE를 지우고 루트에서 상속만 받게 한 뒤, 다시 읽어 다른 ACE·소유자·정션이 하나라도 있으면 설치를 멈춥니다. SID로 지정하므로 한국어 Windows에서도 같습니다 | `secure_data_root` |
| 감사 정책. 처음 한 번 백업한 뒤 하위 범주 GUID로 켭니다 | `audit_backup`(백업이 없을 때), `audit_policy_success`, `audit_policy_failure` |
| 레지스트리 | `registry_cmdline`, `registry_scriptblock` |
| 이벤트 로그 크기. Security 256 MB, PowerShell/Operational 64 MB | `security_log_size`, `powershell_log_size` |
| 서비스 등록(`create`, 업그레이드면 `config`) | `service_install`(`delayed-auto`), `service_description`, `service_failure`, `service_failureflag` |
| 방화벽(`--open-firewall`이거나 이전 설치가 열었을 때) | `firewall_delete_old`(포트가 바뀌었을 때), `firewall`(규칙이 없을 때) |
| 설치 기록 | `install_state`(`<D>\data\install-state.json`), `install_info`(`<I>\install.json`) |
| 앱 및 기능·시작 메뉴 | `uninstall_entry`, `start_menu_shortcut` |
| 시작과 준비 확인 | `service_start`, `wait_ready`(30초 동안 `/api/channel`) |
| 이전 설치 폴더 삭제 | `cleanup_old`(`<I>.old`가 있을 때) |

**감사 정책만 따로**

```powershell
& "C:\Program Files\MCP Monitor\mcp-monitor.exe" audit-policy --enable --dry-run | Write-Output
& "C:\Program Files\MCP Monitor\mcp-monitor.exe" audit-policy --restore "C:\ProgramData\MCP Monitor\data\auditpol-backup.csv" | Write-Output
```

- `--enable`과 `--restore <파일>` 중 하나만 줍니다. 공통으로 `--data-root`, `--dry-run`, `--interactive`를 받습니다.
- 설치 전에 `--enable`을 쓰면 데이터 루트를 설치와 같은 ACL로 먼저 만들고(`secure_data_root`), 바꾸기 전 레지스트리 값을 `<D>\data\audit-policy-state.json`에 처음 한 번 기록합니다(`record_registry`). 이어서 설치와 같은 감사 단계 7개를 실행합니다.
- 나중의 설치는 그 값을 `install-state.json`의 `registry_before`로 이어받습니다. `--restore`와 제거(`--restore-audit-policy`)는 `install-state.json`, 없으면 `audit-policy-state.json`의 값으로 되돌립니다(`restore_audit_policy`, `restore_registry`). 되돌리는 값은 설치가 바꾸는 두 레지스트리 값(DWORD)뿐입니다.

**첫 Admin 만들기**

1. 설치가 연 앱 창(또는 그 PC의 브라우저)에서 `http://127.0.0.1:8700/admin/setup`을 엽니다. External 채널에서는 할 수 없습니다.
2. 이메일과 이름을 넣어 Admin을 만듭니다.
3. 같은 이메일로 로그인합니다. 로그인 코드는 `<D>\data\dev\otp-outbox.log`의 마지막 줄에 있습니다(⑨ Dummy OTP). 관리자만 읽을 수 있습니다.
4. **사용자** 화면에서 로그인할 MCP 개발자와 Admin의 이메일을 등록합니다.
5. 나중에는 시작 메뉴 **MCP Monitor**로 앱 창을 엽니다. 창은 상태 보드(`http://127.0.0.1:8700/`, 8701의 보드와 같은 화면)로 열리고, 위쪽 **관리 화면** 버튼이 관리 화면(로그인 전이면 로그인 화면)으로, 관리 화면 위쪽 **상태 보드** 버튼이 보드로 돌아갑니다. 창을 닫아도 서비스는 계속 돌고, 트레이 아이콘이 남습니다(⑨).

## ③ 업그레이드

1. 새 버전의 `mcp-monitor-<버전>.exe`를 더블클릭합니다. "설치된 MCP Monitor 1.1.0을(를) 1.1.1(으)로 업그레이드할까요?" 상자에서 **예** → UAC → 진행 → 결과 상자 → 앱 창.
   - 명령줄: 관리자 PowerShell에서 `& .\mcp-monitor-1.1.1.exe install | Write-Output`(또는 관리자 아닌 셸에서 `install --interactive`). 옵션을 주지 않으면 이전 설치 폴더·데이터 루트·포트·방화벽을 그대로 씁니다.
2. 설치기가 하는 일(②의 단계표 순서):
   1. 새 묶음을 `<I>.staging`에 풀고 검사합니다. 이때까지 서비스는 그대로 동작합니다.
   2. 서비스를 멈춥니다(최대 60초). 정지 순서는 ⑤와 같습니다(에이전트는 `exit`를 받고 고지 창을 닫음).
   3. 설치 폴더의 exe로 도는 프로세스를 끝냅니다: 모든 세션의 앱 창·트레이, 남은 에이전트. 실행 중인 exe는 폴더 이름 바꾸기를 막기 때문입니다.
   4. `<I>`를 `<I>.old`로, `<I>.staging`을 `<I>`로 바꿉니다. 실패하면 이전 폴더를 되돌리고 `[실패] swap_install_dir`로 끝납니다.
   5. 데이터 루트·감사 정책·서비스 설정을 다시 맞추고, 서비스를 시작해 `/api/channel` 응답을 확인한 뒤 `<I>.old`를 지웁니다.
   - **서비스를 멈춘 뒤, 다시 시작하기 전에 실패하면** 설치기가 `[실패]` 줄 다음에 `[복구] …` 한 줄을 냅니다(더블클릭이면 결과 상자에도 보임).
     - 폴더를 바꾸기 전(`stop_existing`이 서비스 정지를 요청했지만 60초 안에 멈추지 않은 경우, `stop_apps`, `swap_install_dir`)이면 이전 설치가 그대로이므로 이전 버전의 서비스를 다시 시작합니다: `[복구] 이전 버전의 서비스를 다시 시작했습니다(sc.exe start mcp-monitor).` 다시 시작하지 못하면 `[복구] 이전 버전의 서비스를 다시 시작하지 못했습니다(종료 코드 N). …`이 나오고, 원인을 고친 뒤 `sc.exe start mcp-monitor` 또는 같은 exe로 다시 설치합니다.
     - 폴더를 바꾼 뒤(`secure_data_root`, 감사 단계, `service_install` … `start_menu_shortcut`)면 `[복구] 서비스가 멈춰 있습니다. 원인을 고친 뒤 같은 mcp-monitor.exe를 관리자 권한으로 다시 실행하세요(복구 설치). 이전 설치는 <I>.old 에 있습니다.` 이때는 `sc.exe start mcp-monitor`로 켜지 않습니다: **1.0.0에서 올라오는 중이면 서비스 binPath가 아직 `<I>\bin\monitor\mcp-monitor.exe`(이제 `<I>.old` 안)를 가리켜 시작이 실패합니다**(1053/2). 같은 새 exe로 다시 설치하면 binPath를 고치고 서비스를 시작합니다. 1.0.0으로 돌아가야 하면 5의 3을 따릅니다.
3. 그대로 남는 것: 데이터 루트(로그, 설정, 사용자, 스크립트), 감사 정책 백업(`auditpol-backup.csv`)과 바꾸기 전 레지스트리 값(`registry_before`)은 **첫 설치 때 것**, 포트와 방화벽 규칙.
4. **낮은 버전으로는 설치하지 않습니다**(다운그레이드 거부). `install`은 `오류: --install-dir: 설치된 버전 …이 이 실행 파일(…)보다 새롭습니다 …`와 종료 코드 2. 더블클릭하면 "설치된 MCP Monitor(…)가 이 실행 파일(…)보다 새롭습니다" 안내 뒤 설치된 쪽의 앱 창을 엽니다. 같은 버전의 `install`은 **복구 설치**입니다(파일을 다시 풀고 설정을 다시 맞춤).
5. **서비스 시작 뒤에 실패하면**(`[실패] service_start` 또는 `wait_ready`) `<I>.old`가 남고, 설치기는 자동으로 되돌리지 않습니다. 새 버전이 이미 `config.db`를 마이그레이션했을 수 있어서, 옛 버전으로 바꿔 끼우면 그 버전이 DB를 열지 못하기 때문입니다(종료 코드 5). 복구:
   1. 원인을 봅니다: ⑤ 오류를 보는 곳, `sc.exe query mcp-monitor`.
   2. 원인을 고칠 수 있으면 고친 뒤 **같은 새 exe로 다시 설치**합니다(복구 설치). 이때 남은 `<I>.old`는 지워지므로, 보관하려면 먼저 다른 이름으로 옮겨 둡니다.
   3. 이전 버전으로 돌아가야 하면: `sc.exe stop mcp-monitor` → `<I>`를 `<I>.failed`로, `<I>.old`를 `<I>`로 이름 바꾸기 → 서비스가 종료 코드 5로 끝나면 업그레이드 전 ⑦ 백업을 복원 → `sc.exe start mcp-monitor`. 1.0.0으로 돌아갈 때는 서버 exe 이름이 달라 binPath도 고칩니다: `sc.exe config mcp-monitor binPath= "\"C:\Program Files\MCP Monitor\bin\monitor\mcp-monitor.exe\" service --root \"C:\ProgramData\MCP Monitor\" --local-port 8700 --external-port 8701"`.
6. **1.0.0(PowerShell 설치)에서 올라오기:** 1.0.0에는 앱 및 기능 항목이 없지만, 설치기가 서비스 binPath와 `<I>\bundle.json`으로 찾아 업그레이드로 다룹니다. 데이터·설정·스크립트·감사 백업은 그대로이고, `<I>\bin\agent`와 `<I>\install`은 사라지며, binPath는 `mcp-monitor-server.exe`로, 세션 에이전트는 `mcp-monitor.exe agent`로 바뀝니다. 그 뒤에는 앱 및 기능과 시작 메뉴 항목이 생깁니다.
7. 업그레이드가 끝낸 **다른 사용자 세션의 트레이**는 그 사용자가 다음에 로그인할 때(로그인할 때 시작을 켰다면) 또는 시작 메뉴로 다시 뜹니다. 고지 창은 서비스가 다시 띄운 에이전트가 다시 보여 줍니다.
8. 업그레이드한 뒤 처음 시작할 때:
   - 새 버전이 `config.db` 마이그레이션을 적용합니다.
   - `index.db`의 스키마가 바뀌었으면 지우고 다시 색인합니다. 그동안 로그 화면에 "색인 중"이 보입니다.
   - 시작 유형은 설치가 `delayed-auto`로 되돌리고, 서비스가 시작하면서 웹 설정값으로 다시 맞춥니다(W25).
9. **업그레이드 전에 ⑦ 백업을 해 둡니다.** 새 버전이 마이그레이션한 `config.db`는 옛 버전이 열지 않습니다(종료 코드 5).

## ④ 제거

- **앱 및 기능**(설정 → 앱 → 설치된 앱) → **MCP Monitor** → 제거 → UAC. 데이터를 남기는 기본 제거를 하고, 결과를 상자로 보여 줍니다(`uninstall --interactive`).
- 명령줄(관리자 PowerShell):

  ```powershell
  & "C:\Program Files\MCP Monitor\mcp-monitor.exe" uninstall --dry-run | Write-Output
  & "C:\Program Files\MCP Monitor\mcp-monitor.exe" uninstall | Write-Output
  & "C:\Program Files\MCP Monitor\mcp-monitor.exe" uninstall --remove-data --restore-audit-policy | Write-Output
  ```

  설치 폴더 안의 exe로 실행해도 되고, 받은 `mcp-monitor-1.1.0.exe`로 실행해도 됩니다.

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--install-dir <폴더>` | 앱 및 기능의 설치 위치 → 서비스 binPath → `%ProgramFiles%\MCP Monitor` | 지울 설치 폴더. `bundle.json`이 있을 때만 지웁니다. 경로 규칙은 `install`의 `--install-dir`와 같습니다(어긋나면 종료 코드 2) |
| `--data-root <폴더>` | `<I>\install.json` → 서비스 binPath → `%ProgramData%\MCP Monitor` | 데이터 루트. `--remove-data`는 우리 표시(`data\mcp-monitor-data-root.json` 또는 `install-state.json`)가 있을 때만 지우고, 드라이브 루트·시스템 폴더와 경로 규칙에 어긋나는 경로(장치·UNC·subst 경로, 경로 안의 정션·심볼릭 링크)는 거부합니다(종료 코드 2). 데이터 루트가 설치 폴더 안이면 `--remove-data` 없이는 거부합니다 |
| `--remove-data` | 꺼짐 | 데이터 루트 전체(로그, `config.db`, 스크립트, `collector-state.json`, `tamper-baseline.json`)와 모든 사용자의 `C:\Users\*\AppData\Local\mcp-monitor`(앱 창·고지 창 WebView2 프로필, 1.0.0의 Edge 고지 프로필)를 지웁니다. **되살릴 수 없습니다** |
| `--restore-audit-policy` | 꺼짐 | 첫 설치 때의 `auditpol` 백업과 레지스트리 값으로 되돌립니다 |
| `--dry-run` | 꺼짐 | 단계만 출력합니다(관리자 불필요) |
| `--interactive` | 꺼짐 | 관리자가 아니면 UAC로 승격하고, 결과를 상자로 보여 줍니다 |

**제거 단계**(기본 11단계, `--restore-audit-policy` +2, `--remove-data` +2): `require_admin`, `stop_service`, `delete_service`, `stop_apps`, `firewall_delete`, (`restore_audit_policy`, `restore_registry`), `remove_uninstall_entry`, `remove_shortcut`, `remove_run_values`, `remove_install_dir`, `remove_old_install`, `remove_staging`, (`remove_data`, `remove_webview_profiles`).

- `remove_old_install`과 `remove_staging`은 실패한 업그레이드가 남긴 `<I>.old`(이전 설치, `bundle.json`이 있을 때만)와 `<I>.staging`(설치기의 표시 파일이 있을 때만)을 지웁니다. 링크이거나 표시가 없으면 `건너뜀`으로 남겨 둡니다.
- `remove_webview_profiles`는 사용자마다 `<사용자>`, `AppData`, `Local` 폴더를 지우는 동안 열어 두어(삭제 공유 없음), 그 사이에 사용자가 그 폴더를 다른 이름으로 바꾸고 정션을 놓을 수 없게 합니다.

- **기본 동작은 데이터를 남깁니다**(W31). 서비스, 방화벽 규칙(설치 때의 포트), 앱 및 기능 항목, 시작 메뉴, 설치 폴더만 지웁니다. 감사 기록은 쉽게 지우지 않는다는 원칙입니다. 끝나면 `제거 완료. 데이터는 <D> 에 남아 있습니다(지우려면 --remove-data).`
- 감사 정책을 되돌릴지는 기기 소유자가 정합니다. 되돌리면 그 뒤로 RDP 로그온 실패와 명령줄이 Windows에 남지 않습니다.
- **실행 중인 자신:** 제거를 실행한 exe가 설치 폴더 안에 있으면 지울 수 없으므로 `mcp-monitor.exe.uninstalled`로 이름을 바꾸고, 그 파일과 설치 폴더는 **다음에 PC를 다시 시작할 때** 지워지도록 예약합니다("설치 폴더의 남은 파일은 다시 시작할 때 지워집니다."). 공유 `%TEMP%`로 자신을 복사하지 않습니다.
- **다시 시작하기 전에 같은 폴더로 다시 설치하면 거부됩니다**: 남은 `mcp-monitor.exe.uninstalled` 때문에 `오류: --install-dir: … 이(가) 비어 있지 않고 MCP Monitor 설치 폴더(bundle.json)도 아닙니다.`(종료 코드 2). PC를 다시 시작한 뒤 설치합니다.
- **로그인 때 트레이 시작(`HKCU\…\Run\MCPMonitor`):** 제거는 지금 로그인해 있는 사용자의 값만 지웁니다. 로그온하지 않은 사용자의 값은 남을 수 있습니다(무해: 가리키는 exe가 없으면 아무것도 실행되지 않고, "시작 앱" 목록에 이름만 보입니다). 그 사용자가 설정 → 앱 → 시작 프로그램에서 지울 수 있습니다.
- **1.0.0(PowerShell 설치)의 제거**도 이 exe의 `uninstall`로 합니다(binPath로 찾음).
- **방화벽:** 1.1.0부터는 다른 `--external-port`로 다시 설치하면 옛 규칙을 지웁니다(이전 설치가 방화벽을 열었을 때). 1.0.0 시절 다른 포트로 다시 설치하며 남은 옛 규칙은 그대로 남으므로 `netsh advfirewall firewall show rule name=all | findstr "MCP Monitor"`로 확인하고 지웁니다.

## ⑤ 서비스 운영

- **시작 유형은 웹 설정이 기준입니다**(W25).
  - **설정 → 부팅 시작 유형**에서 `자동`, `자동(지연된 시작)`, `수동` 중에서 고릅니다. Local 채널의 Admin만 바꿀 수 있습니다.
  - 저장하면 곧바로 SCM에 적용하고, `admin.audit` `service_start_type_apply`로 남깁니다.
  - 서비스가 시작할 때마다 다시 맞춥니다. 그래서 `sc.exe config`나 서비스 관리자에서 손으로 바꾼 값은 다음 시작 때 웹 설정값으로 돌아갑니다.
  - 설정 화면의 **Windows 서비스** 줄에서 지금 SCM 값과 일치 여부를 볼 수 있습니다.
  - 예외: 관리자가 `services.msc`에서 **사용 안 함**으로 바꾼 서비스는 그대로 둡니다(사고 대응). 설정 화면에 `사용 안 함`과 안내가 보이고, 설정을 저장해도 다시 켜지 않습니다(`service.start_type` `disabled`, 감사 결과 `error`). 다시 쓰려면 `services.msc`에서 시작 유형을 바꿉니다.
- **binPath:** `sc.exe qc mcp-monitor`의 `BINARY_PATH_NAME`은 `"<I>\bin\monitor\mcp-monitor-server.exe" service --root "<D>" --local-port 8700 --external-port 8701`입니다. 작업 관리자에서 서비스 프로세스는 `mcp-monitor-server.exe`(SYSTEM)로 보입니다. 사용자 이름으로 도는 `mcp-monitor.exe`는 세션 에이전트와 앱 창입니다.
- **시작과 정지:** `sc.exe start mcp-monitor`, `sc.exe stop mcp-monitor`(또는 `services.msc`). 트레이 메뉴의 첫 줄이 서비스 상태(`서비스: 실행 중` / `중지됨` / `시작하는 중` / `멈추는 중` / `설치 안 됨`)를 보여 줍니다.
  - 정지 순서는 다음과 같습니다.
    1. 그때까지 쌓인 로그를 먼저 디스크에 씁니다.
    2. 수집기가 멈춥니다. 에이전트가 종료 신호를 받고 고지 창을 닫습니다.
    3. 실행 중인 MCP 스크립트는 10초 기다린 뒤 프로세스 트리째 종료합니다(W21). 그 기록도 곧바로 디스크에 씁니다.
    4. 마지막으로 웹 서버, 보존 정리, 색인, 로그가 멈춥니다.
  - 정지하는 동안 2초마다 SCM에 진행(`STOP_PENDING`, 체크포인트 증가, 다음 보고까지 10초)을 알립니다. 전체 정지는 **최대 50초**이고, 넘으면 그 자리에서 `STOPPED`를 보고하고 끝냅니다(이벤트 로그에 "did not stop within 50 s").
  - Windows 종료·재시작 때는 PRESHUTDOWN 알림을 받아 같은 순서로 멈춥니다. 서비스가 시작할 때 자기 PRESHUTDOWN 시간 제한을 60초로 정합니다(보통의 종료 알림은 약 5초뿐).
  - SCM이 요청한 정지는 중간에 오류가 나도 `STOPPED`로 끝납니다. 오류는 응용 프로그램 이벤트 로그에 남고, SCM이 충돌로 보고 다시 시작하지 않습니다. `failureflag 1`에서는 0이 아닌 종료 코드도 복구 동작을 부르므로, 이때의 종료 코드는 0입니다.
  - 서비스가 멈춘 채로 앱 창을 열면 연결 중 페이지가 뜨고, 30초 넘게 응답이 없으면 "서비스가 응답하지 않습니다 …" 안내로 바꾼 뒤 5초마다 다시 연결합니다. 서비스가 응답하면 상태 보드로 넘어갑니다.
- **복구 동작**(설치가 설정합니다):
  - 예기치 않게 끝나면 5초, 10초, 60초 뒤에 다시 시작합니다. 실패 횟수는 하루(86,400초) 뒤 초기화됩니다.
  - `failureflag 1`은 서비스가 0이 아닌 종료 코드로 `STOPPED`를 보고했을 때도 복구 동작을 돌게 하는 설정입니다. 지금 서비스에는 그렇게 끝나는 길이 없습니다: SCM이 요청한 정지는 언제나 종료 코드 0으로 `STOPPED`를 보고하고(복구 없음), 그 밖의 종료(아래 종료 코드 3·4·5 포함)는 `STOPPED` 없이 프로세스가 끝나 충돌로 처리되므로 이 설정과 상관없이 복구 동작이 돕니다.
  - 확인: `sc.exe qfailure mcp-monitor`.
- **종료 코드와 조치:**

  | 코드 | 뜻 | 조치 |
  |---|---|---|
  | 3 | 포트 사용 중(8700 또는 8701) | `Get-NetTCPConnection -LocalPort 8700,8701 -State Listen \| Select LocalAddress,LocalPort,OwningProcess`로 점유한 프로세스를 찾아 끝냅니다. 다른 포트를 쓰려면 `mcp-monitor.exe install --local-port <포트> --external-port <포트>`로 다시 설치합니다 |
  | 4 | 데이터 루트 사용 중(`data\.lock`) | 같은 `<D>`를 쓰는 다른 MCP Monitor(손으로 띄운 콘솔 서버, 진행 중인 `reindex`)를 끝냅니다 |
  | 5 | `config.db`가 이 프로그램보다 새 버전 | 더 새 버전을 설치하거나, 이 버전 때의 백업을 복원합니다(③ 5, ⑦) |
  | 1 | 예기치 않은 오류 | 아래 이벤트 뷰어와 `logs\<오늘>.jsonl`의 `system` 줄을 봅니다 |

- **오류를 보는 곳.** 서비스로 실행되면 콘솔 출력이 없습니다. 다음 세 곳을 봅니다.
  - 이벤트 뷰어 → `Windows 로그 → 응용 프로그램`, 원본 `mcp-monitor`: "mcp-monitor exited with code N"과 예기치 않은 예외의 트레이스백이 남습니다. 메시지 설명을 찾을 수 없다는 문구가 붙어도 본문은 그대로 읽힙니다.
  - 이벤트 뷰어 → `Windows 로그 → 시스템`, 원본 `Service Control Manager`:
    - 7031, 7034: 예기치 않은 종료와 복구 동작
    - 7000, 7009: 시작 실패와 시간 초과
  - `<D>\logs\<오늘>.jsonl`의 `"cat":"system"` 줄(`collector.status`, `agent.launched`, `agent.launch_failed`, `logindex.*`, `retention.*`, `service.start_type` 등).
    - 관리 화면 **로그**에서 카테고리 `시스템`으로도 볼 수 있습니다.
  - 같은 오류를 콘솔에서 재현하려면 서비스를 멈춘 뒤 관리자 PowerShell에서 `& "C:\Program Files\MCP Monitor\bin\monitor\mcp-monitor-server.exe" --root "C:\ProgramData\MCP Monitor"`로 실행합니다. 한 줄 오류와 종료 코드가 나옵니다. Ctrl+C로 끝냅니다.

## ⑥ 로그

- **파일 구조:**
  - `<D>\logs\YYYY-MM-DD.jsonl`에 한 줄에 이벤트 하나가 기록됩니다. UTF-8, 시각은 KST(+09:00), 자정에 새 파일로 넘어갑니다.
  - 카테고리는 12개입니다: `session`, `notice`, `activity.process`, `activity.command`, `activity.window`, `activity.idle`, `tamper`, `mcp.health`, `mcp.action`, `auth`, `admin.audit`, `system`.
- **압축:**
  - 압축 대상은 `max(압축 시작 일수, 2)`일보다 오래되고 **색인이 끝난** `.jsonl`입니다. gzip(`.jsonl.gz`)으로 압축하고, 같은 날짜의 `.gz`가 이미 있으면 합칩니다.
  - 어제와 오늘 파일은 압축하지 않습니다. 수집기가 늦게 쓰는 이벤트가 있기 때문입니다.
- **보존 정리:**
  - 매일 **03:30 KST**에 보존 기간을 넘긴 날짜의 파일, 색인 행, DB 표를 지웁니다. DB 표는 `auth_sessions`, OTP 표, `mcp_actions`, `mcp_transitions`, `rdp_*`, `notice_displays`입니다.
  - 그 시각에 서비스가 꺼져 있었으면 시작 60초 뒤에 돕니다.
  - 기준일은 설정 화면 미리보기와 같은 `retention_cutoff`입니다.
  - 지운 내역은 `system` `retention.run`과 `admin.audit` `retention_purge`(삭제한 날짜 범위, 파일 수, 용량, 행 수)로 남습니다.
  - 정리는 우회 탐지에 미리 알리고 지우므로, `tamper` `log_file_removed`가 생기지 않습니다. **로그 파일을 손으로 지우면** 우회 탐지로 남습니다.
- **보존 기간을 줄이면:**
  - 설정 화면이 삭제될 기간, 파일 수, 용량, 기록 건수를 먼저 보여 줍니다.
  - 확인하면 **몇 초(약 5초) 안에** 정리가 시작됩니다(W14).
  - 보존 기간은 7–3,650일(기본 180일), 압축 시작 일수는 1일 이상이고 보존 기간 이하입니다(기본 30일).
- **로그 조회와 감사:**
  - **로그**와 **감사 로그** 화면은 로그인한 MCP 개발자 이상이 두 채널 모두에서 씁니다.
  - 내보내기는 매번 `logs_export`/`audit_export`로 기록됩니다.
  - 목록 조회는 같은 사람, 채널, 조건마다 60초에 한 번 `logs_view`/`audit_view`로 기록됩니다.
  - 키워드는 낱말 앞부분 검색입니다. 전체의 수십 %에 맞는 넓은 낱말(예: `chrome`, `focus`)은 목록은 빠르지만 히스토그램·사용자 건수가 300ms를 넘을 수 있습니다. 사용자나 카테고리를 먼저 고르면 빨라집니다(`docs/verification/perf-p6.md` 3.3·4절).
  - 색인 읽기 하나는 **5초**가 지나면 중단되고 "입력값을 확인하세요" 오류(응답 헤더 `X-Error-Reason: query_timeout`)가 납니다. 기간·사용자·카테고리를 좁혀 다시 찾습니다. 화면을 떠나면 진행 중이던 읽기도 곧바로 멈춥니다.
- **색인 다시 만들기.** `index.db`가 깨졌거나 원본 JSONL을 복원한 뒤에 합니다. 서비스를 먼저 멈춰야 합니다. 서비스가 떠 있으면 종료 코드 4로 거절됩니다. `reindex`는 **서버 exe**의 명령입니다(`mcp-monitor.exe`에는 없음).

  ```powershell
  sc.exe stop mcp-monitor
  & "C:\Program Files\MCP Monitor\bin\monitor\mcp-monitor-server.exe" reindex --root "C:\ProgramData\MCP Monitor"
  sc.exe start mcp-monitor
  ```

  - 끝나면 `indexed N rows from M files`가 출력됩니다. 180일 분량이면 몇 분 걸립니다(약 1만 6천 줄/초).
  - 개발 체크아웃에서는 `server\`에서 `uv run python -m app reindex --root <루트>`를 씁니다.
  - 색인 스키마가 바뀐 업그레이드 뒤에는 서비스가 스스로 다시 만듭니다. 그동안 최근 날짜부터 보입니다.

## ⑦ 백업·복원

- **백업:**
  1. `sc.exe stop mcp-monitor`로 서비스를 멈춥니다. 쓰는 중인 SQLite를 복사하면 깨진 사본이 생길 수 있습니다.
  2. 다음을 복사합니다.
     - `<D>\data\config.db`(같은 폴더에 `config.db-wal`이 있으면 함께)
     - `<D>\scripts\`
     - `<D>\logs\`
     - 권장: `<D>\data\install-state.json`, `<D>\data\auditpol-backup.csv`, `<D>\data\audit-policy-state.json`
  3. `index.db`는 **백업하지 않습니다**. 원본 로그로 다시 만들 수 있습니다.
  4. `sc.exe start mcp-monitor`로 다시 시작합니다.
  - 예: `robocopy "C:\ProgramData\MCP Monitor" D:\backup\mcpmon /E /XF index.db index.db-wal index.db-shm .lock`
  - 백업본에는 로그 원문(명령줄, 창 제목, IP)이 들어 있습니다. 백업 위치도 데이터 루트처럼 관리자만 읽게 둡니다.
- **복원:**
  1. 서비스를 멈춥니다.
  2. 같은 경로로 되돌려 복사하고, `<D>\data\index.db*`를 지웁니다.
  3. 권한을 데이터 루트 상속으로 맞춥니다: `icacls "C:\ProgramData\MCP Monitor\*" /reset /T /C /Q`.
  4. 서비스를 시작합니다. 시작하면 색인을 처음부터 다시 만듭니다.
  - 복원한 스크립트와 로그 파일은 우회 탐지 기준값과 다르므로, 첫 점검에서 `tamper` 줄(`while_stopped: true`)이 남을 수 있습니다. 복원 직후의 그 줄은 예상된 것입니다.

## ⑧ 보안

- **8700 앞에 리버스 프록시를 두지 않습니다**(§4.4).
  - 채널은 들어온 포트로만 판별합니다. 같은 PC의 프록시가 외부 요청을 8700으로 넘기면, 외부 사용자가 Local 권한(스크립트 편집, 사용자 관리, 첫 Admin 만들기)을 얻습니다.
  - 8700은 `127.0.0.1`에만 열립니다. 포트 전달이나 프록시로 밖에 내보내지 않습니다.
- **8701은 HTTP 평문입니다**(§2 #5).
  - 로그인 코드와 세션 쿠키가 암호화되지 않고 오갑니다. 믿을 수 있는 사내망에서만 열고, 방화벽은 필요한 프로필에만 엽니다(`--open-firewall`은 도메인·개인).
  - HTTPS 옵션은 추후입니다.
- **RDP 계정은 Windows 표준 사용자로 운영합니다**(§14, §2 #4).
  - 관리자 권한 사용자는 에이전트, 감사 정책, 이벤트 로그를 끄거나 지울 수 있습니다.
  - MCP Monitor는 그것을 **막지 못하고 우회 탐지로만 남깁니다**. 남는 곳은 `tamper` 줄, 대시보드의 **우회 탐지 이벤트** 카드, 로그인한 화면의 실시간 알림입니다.
  - 외부 알림(메일, 웹훅)은 추후입니다.
- **앱 창과 고지 창(WebView2):**
  - 앱 창은 상태 보드(`http://127.0.0.1:<Local 포트>/`)로 열리고, 그 출처(보드와 관리 화면)와 자기 연결 중 페이지만 엽니다. 그 밖의 `http(s)` 주소는 **기본 브라우저**로 넘기고, 사용자 정보가 든 주소(`http://a@…`)와 다른 스킴(`file:` 등)은 막습니다. 새 창은 만들지 않습니다. 이 규칙은 창 전체의 이동(최상위 탐색)에 적용되고, 페이지 안의 프레임(iframe) 이동과 다운로드는 따로 분류하지 않습니다. 관리 화면은 우리 페이지이고 CSP로 다른 출처의 프레임을 넣지 않으므로 그 경로는 쓰이지 않습니다.
  - 고지 창은 서비스가 보낸 `<서버>/notice#…` 주소만 엽니다. 페이지가 다른 곳으로 이동하려 하면 막고 고지 페이지가 그대로 남습니다(WebView2가 막기 전에 그 주소로 요청을 이미 보냈을 수는 있지만, 그 페이지는 보이지 않습니다). 새 창(`window.open`)은 열지 않습니다.
  - 개발자 도구(F12, Ctrl+Shift+I), 오른쪽 클릭 메뉴의 "검사", 브라우저 단축키가 없습니다.
  - `WEBVIEW2_*` 환경 변수(원격 디버깅, 다른 런타임 지정)는 시작할 때 지워 무시합니다.
  - 고지 토큰은 명령줄에 없습니다: 에이전트가 WebView2 API로 탐색하고, 창 제목은 `MCP Monitor 고지`로 고정이며, 에이전트 로그와 창 제목 이벤트에서도 토큰을 가립니다. 에이전트의 토큰·서버 키는 환경 변수로 받아 곧바로 지우므로 자식 프로세스(WebView2)에 넘어가지 않습니다.
- **승격은 설치·업그레이드·제거·감사 정책 때만입니다.** exe의 매니페스트는 `asInvoker`이고, `--interactive`일 때만 UAC로 **같은 exe**를 다시 실행합니다. 다시 실행할 인자는 해석한 옵션에서 새로 만들고, 승격된 프로세스는 호출자가 고른 파일에 결과를 쓰지 않습니다(결과는 메시지 상자). 반대로 앱 창·트레이는 관리자 권한으로 실행하면 열지 않습니다(②의 `app`): 관리자 토큰의 WebView2 창과 관리자의 `HKCU`에 쓰는 로그인 시작 항목을 만들지 않기 위해서입니다.
- **DLL은 System32에서만 찾습니다.** 다운로드 폴더에서 승격 실행할 때 그 폴더에 심어 둔 DLL을 읽지 않도록, 정적 import는 System32에서만(`DependentLoadFlags 0x800`), 시작 직후 `SetDefaultDllDirectories(LOAD_LIBRARY_SEARCH_SYSTEM32)`입니다.
- **내장 묶음:** 설치는 exe에 든 해시로 묶음 전체와 파일 하나하나를 검사하고, 관리자만 쓸 수 있는 `<I>.staging`에만 풉니다. 공유 `%TEMP%`에 실행 파일을 두지 않습니다. 개발용 묶음으로 만든 exe는 설치를 거부합니다.
- **데이터 루트 ACL:**
  - `<D>`는 상속을 끊고 SYSTEM(`S-1-5-18`)과 Administrators(`S-1-5-32-544`)만 모든 권한을 가집니다. 소유자는 Administrators입니다.
  - 그래서 표준 사용자는 로그, 설정, 스크립트, 로그인 코드를 읽을 수 없습니다.
  - 확인: `icacls "C:\ProgramData\MCP Monitor"`.
- **설치 폴더 ACL:** `<I>`는 Program Files 권한 그대로 둡니다. 사용자는 읽고 실행만 하고, 쓸 수 없습니다. 설치·업그레이드는 폴더를 바꿔 끼운 뒤 트리 전체를 검사해, 관리자가 아닌 계정이 쓰거나 지우거나 권한을 바꿀 수 있는 항목이 있으면 되돌리고 실패합니다(SYSTEM이 실행하는 폴더이므로). 확인: `icacls "C:\Program Files\MCP Monitor" /T`.
- **런타임 외부 네트워크 없음.** 앱·에이전트는 `127.0.0.1`의 서비스에만 연결하고(프록시 무시), 자동 업데이트도 없습니다. 업그레이드는 새 exe를 실행합니다.
- **스크립트는 SYSTEM으로 실행됩니다.**
  - 스크립트 편집은 Local 채널에서 MCP 소유자 또는 Admin만 할 수 있습니다.
  - 실행 직전에 저장된 해시와 비교합니다. 파일을 손으로 고치면 실행이 막히고 우회 탐지로 남습니다.

## ⑨ 알려진 동작

- **고지 창**은 화면 가운데의 WebView2 창입니다: 640×600(작업 영역에 맞춰 줄임), 항상 위, 닫기 단추 비활성, 최소화·최대화·크기 조절 없음, 작업 표시줄에 없음, Alt+F4·닫기 요청 무시, '확인'에만 반응합니다. 확인하면 닫히고 `notice_acknowledged`가 남습니다.
  - **다른 앱의 입력을 막지는 않습니다.** Windows는 다른 프로세스의 입력을 막는 모달 창을 허용하지 않으므로, 여기서 "모달"은 "확인 전에는 닫히지 않고 항상 위에 보이는 창"을 뜻합니다(Y10). 2초마다 다시 맨 위로 올리지만 초점을 빼앗지는 않고, 처음 한 번 앞으로 가져오기를 시도합니다(Windows가 허락하지 않으면 창을 깜빡여 알림).
  - 고지 창의 WebView2 프로세스가 죽으면(사용자가 작업 관리자에서 `msedgewebview2.exe`를 끝낸 경우 포함) "사용자가 닫음"으로 한 번 보고하고, 빈 창이 된 고지 창을 닫습니다. 서버가 곧 다시 보내면 새 창이 뜹니다(`notice_unacknowledged`). 알아차리는 길은 셋입니다: WebView2의 `ProcessFailed`, `BrowserProcessExited`, 그리고 에이전트가 2초 안팎마다 브라우저 프로세스가 살아 있는지 직접 보는 것(앞의 둘이 오지 않을 때). 에이전트 로그(표준 오류)에 `notice window: …` 줄로 어느 쪽이 알렸는지 남습니다.
  - **고지 창 자체의 창 이벤트는 `activity.window`에 남지 않습니다.** 에이전트는 자기 프로세스의 창 이벤트를 받지 않는데(`WINEVENT_SKIPOWNPROCESS`), 1.1.0부터 고지 창이 에이전트 프로세스 안에 있기 때문입니다(1.0.0에서는 `msedge.exe`의 창으로 남았음). 고지가 보이고 확인된 사실은 `notice` `notice_shown`·`notice_acknowledged`가 대신 남깁니다.
  - **WebView2 런타임이 없으면** 고지를 기본 브라우저 탭으로 엽니다(최상위가 아님). 이때 고지 주소(토큰 포함)가 브라우저 명령줄에 남고, 서버 로그의 `<redacted>` 가림으로만 보호됩니다. 이 방식에서는 **탭을 닫아도 알 수 없어 다시 보여 주지 않습니다**: 고지는 확인될 때까지 "보임, 미확인"으로 남습니다. WebView2 런타임을 다시 설치하는 것이 조치입니다.
  - 에이전트(`agent --dialog webview`)가 자기 세션 번호를 알 수 없으면 창을 열지 않고 종료 코드 1로 끝납니다(서비스가 다시 띄움). 다른 종료 코드는 0(`exit` 받음), 2(인자·비밀 값 오류), 3(토큰 거부), 4(서버 응답 없음), 5(서버 증명 실패)입니다.
- **세션 에이전트의 유휴 상태:** 5초마다 마지막 입력 시각(`GetLastInputInfo`)을 읽어 300초(서버가 정함) 넘게 입력이 없으면 `activity.idle` `idle`, 입력이 돌아오면 `active`를 보냅니다. 창 이벤트는 0.3초/1초 단위로 합쳐 묶음(최대 200개)으로 보내고, 서비스가 응답하지 않는 동안 최대 2,000개를 버퍼에 두며 넘친 수를 `dropped`로 알립니다. 창 제목은 서비스의 증명(HMAC)을 확인한 연결로만 보냅니다.
- **앱 창과 트레이:**
  - 창을 닫으면 트레이로 숨습니다. 서비스와 감시는 그대로 돕니다. 트레이 메뉴: 서비스 상태 줄, `창 열기`, `로그인할 때 트레이 시작`(체크), `트레이 종료`. `트레이 종료`는 이 사용자의 앱만 끝내고 서비스는 끄지 않습니다.
  - 앱은 로그인 세션마다 하나만 뜹니다(같은 사용자가 두 세션에 로그인하면 세션마다 하나). 다시 실행하면(시작 메뉴 등) 새 창 없이 기존 창이 앞으로 옵니다.
  - 창의 최소 크기는 640×600입니다. 열 때 서비스가 응답하지 않으면 연결 중 페이지를 보여 주고, 30초 넘게 응답이 없으면 서비스 시작 안내로 바꿉니다(⑤).
  - 업그레이드·제거는 모든 세션의 앱을 끝냅니다. 다시 띄우는 것은 사용자 몫입니다(③ 7).
- **WebView2 런타임 업데이트**는 Windows(Edge 업데이트)가 관리합니다. MCP Monitor는 런타임을 받거나 고정하지 않습니다.
- **서비스가 다시 시작하면 MCP의 `FAILED` 상태와 자동 조치 횟수가 초기화됩니다**(W17).
  - 재부팅 뒤에는 감시를 새로 시작합니다.
  - 서비스가 반복해서 재시작되면 그만큼 자동 조치가 다시 돕니다. 이 경우 이벤트 뷰어와 `mcp.action` 로그를 봅니다.
- **우회 탐지 기준값(`<D>\data\tamper-baseline.json`)이 손상됐거나, 로그가 있는데 없으면** 처음부터 다시 만들고 `tamper` `baseline_reset`(`reason`: `corrupt`/`missing`)을 남깁니다. 서비스가 멈춘 동안의 변경은 비교할 수 없다는 뜻입니다. 이 기능이 없던 버전에서 업그레이드한 첫 시작에도 한 번 남을 수 있습니다.
- **보존 기간을 줄여 저장하면** 약 5초 뒤의 정리는 **저장한 날짜** 기준으로 지웁니다. 자정 직전에 저장해도 미리보기보다 하루 더 지우지 않습니다. 하루 더 지난 몫은 다음 03:30 정리가 지웁니다.
- 지우지 못한 만료 로그 파일(다른 프로그램이 열고 있음)은 색인하지 않습니다. 다음 정리가 지웁니다.
- **서비스 정지 중 쓰던 로그 묶음**: 정지가 시간 제한으로 끊기면 그 순간 디스크에 쓰던 묶음은 대개 그대로 쓰이지만, 확실하지 않아 `logstore.dropped` 수에는 들어가지 않습니다.
- **스크립트 저장 중 디스크 오류가 나면**, 그 뒤 첫 실행이 해시 불일치(`hash_mismatch`)로 막힐 수 있습니다(W19). 소유자가 스크립트를 **한 번 다시 저장**하면 풀립니다.
- **cmd 내부 명령(`dir`, `cd`, `del` …)은 수집하지 않습니다**(§2 #7).
  - 남는 것: `cmd.exe` 실행과 인자, `cmd /c …`, 배치 파일 실행, cmd에서 실행한 외부 프로그램.
  - PowerShell 명령은 스크립트 블록 로깅(4104)으로 남습니다.
- **로그인 코드(Dummy OTP):**
  - 1.1.0에도 실제 메일·문자 발송 공급자가 없습니다.
  - 로그인 코드는 `<D>\data\dev\otp-outbox.log`에 `<시각> <이메일> <코드>` 줄로 쌓이고, PC 관리자만 읽을 수 있습니다.
  - 다른 PC에서 로그인하는 사람에게는 관리자가 코드를 전달해야 합니다. 실제 공급자는 추후입니다.
- **데모 데이터(테스트·시연 전용, 운영 PC에서 쓰지 않습니다):** 저장소 체크아웃의 `tools\seed-demo.ps1`이 이 PC의 설치에 시험용 사용자와 실제로 도는 더미 MCP를 넣습니다.
  - 실행: 일반 PowerShell에서 `powershell -ExecutionPolicy Bypass -File tools\seed-demo.ps1`. `dummy-mcps\.venv`가 없으면 먼저 현재 사용자로 `uv sync`를 돌리고, UAC로 한 번 권한을 올립니다.
  - `dummy-mcps\.venv`의 Python이 사용자 프로필 안(예: `%APPDATA%\uv\python`)에 있으면, 권한을 올리기 전에 그 Python을 `dummy-mcps\.python`으로 복사하고 venv를 다시 만듭니다. 서비스(LocalSystem)는 패키지 앱(MSIX) 안에서 설치된 Python의 비공개 AppData 복사본을 볼 수 없어서, MCP 시작 스크립트가 `did not find executable`로 실패합니다.
  - 하는 일: 서비스를 멈추고 `<server> seed-demo --root <D> --dummy-mcps-dir <체크아웃>\dummy-mcps`를 실행합니다. 사용자 `dev1@example.com`·`dev2@example.com`(Developer), `ops@example.com`(Admin)과 MCP `seoul-weather`(9101)·`calculator`(9102)·`seoul-clock`(9103)를 만들고(`admin.audit`, `actor` `seed-demo`), 이미 있는 것은 건드리지 않습니다. MCP의 시작·정지·재시작 스크립트는 `dummy-mcps\examples\*.ps1`을 부르고, 실행 기록은 `<D>\data\demo-run`에 둡니다.
  - 기본으로 서비스 binPath 끝에 `--external-host 127.0.0.1 --dev-otp-code 123456`을 붙여 모든 사용자가 고정 코드로 로그인합니다(외부 채널은 이 PC에서만 열림). `-NoDevOtp`는 binPath를 그대로 두고, `-DevOtpCode <6자리>`로 코드를 바꿉니다. 그 뒤 서비스를 시작하고 `http://127.0.0.1:8700/api/channel` 응답을 기다립니다.
  - 되돌리기: `-Revert`가 붙인 인자를 빼고 서비스를 다시 시작합니다. 데모 사용자·MCP는 관리 화면에서 비활성화·삭제합니다. 진행 기록은 `%LOCALAPPDATA%\mcp-monitor-demo\`에 남습니다.
- 수집 큐가 넘치면 오래된 이벤트부터 버리고, 버린 수를 `system` `collector.dropped`/`logstore.dropped`로 남깁니다.
- 로그 화면에서 넓은 키워드는 느릴 수 있습니다(⑥).

## ⑩ 문제 해결

| 증상 | 확인 | 조치 |
|---|---|---|
| `관리자 권한으로 다시 실행하세요. …` | — | 관리자 PowerShell에서 다시 실행하거나 `--interactive`를 붙입니다. 아무것도 바뀌지 않았습니다 |
| 명령을 실행했는데 아무 출력 없이 프롬프트가 돌아옴 | 명령 형태 | 창 프로그램이라 기다리지 않은 것입니다. `\| Write-Output`을 붙여 다시 실행합니다(이 문서 첫머리) |
| `오류: …` 출력, 종료 코드 2 | 메시지의 옵션 | 겹치는 폴더, 비어 있지 않은 설치 폴더, 같은 포트 값, 다운그레이드 등을 고칩니다. 아무것도 바뀌지 않았습니다 |
| `[실패] <id>: …` | ②의 단계표 | 그 단계만 고친 뒤 다시 실행합니다. 같은 명령을 여러 번 실행해도 안전합니다 |
| `[실패] stage_payload: 개발용(fixture) payload로는 설치할 수 없습니다 …` | `--version`의 `fixture` | 개발 빌드입니다. `install\build-desktop.ps1`로 만든 릴리스 exe를 씁니다 |
| `[실패] stage_payload: …`(해시가 다름, 매니페스트에 없음 등) | `Get-FileHash`와 `.sha256` | exe가 손상되었습니다(받다가 잘림 등). 다시 받아 해시를 확인합니다 |
| `[실패] stop_apps: …` | 작업 관리자 세부 정보의 `mcp-monitor.exe`, `msedgewebview2.exe` | 설치 폴더의 exe로 도는 프로세스를 끝내지 못했습니다. 그 프로세스를 끝내거나 사용자를 로그아웃시킨 뒤 다시 실행합니다 |
| `[실패] swap_install_dir: …` | 설치 폴더를 연 탐색기 창, 명령 프롬프트의 현재 폴더, 바이러스 검사 | 파일 잠금으로 폴더를 바꾸지 못했습니다. 이전 설치로 되돌렸고, 다음 줄 `[복구] …`가 이전 버전의 서비스를 다시 시작했는지 알려 줍니다. 잠근 것을 닫고 다시 실행합니다. 트리 권한 오류면 메시지의 항목 권한을 Program Files 기본으로 되돌립니다 |
| `[복구] 서비스가 멈춰 있습니다 …` | 바로 위의 `[실패]` 줄 | 폴더를 바꾼 뒤의 단계가 실패했습니다. 원인을 고친 뒤 같은 exe로 다시 설치합니다. `sc.exe start`는 1.0.0에서 올라오는 중이면 실패합니다(③ 2) |
| "관리자 권한으로 실행 중이라 MCP Monitor 창을 열지 않습니다 …" | 실행 방법 | "관리자 권한으로 실행"이나 관리자 셸로 연 것입니다. 시작 메뉴의 **MCP Monitor**로 엽니다 |
| 설치 폴더의 `mcp-monitor.exe`가 "… 다운로드한 mcp-monitor-<버전>.exe로 실행하세요" | 서비스 상태(`sc.exe query mcp-monitor`) | 서비스가 없어 설치가 필요한데, 설치된 exe로는 설치 폴더를 바꿀 수 없습니다. 받은 exe로 실행합니다(복구 설치) |
| `[실패] service_start`, 또는 `wait_ready` 30초 초과 | `sc.exe query mcp-monitor`, ⑤ 오류를 보는 곳, CodeIntegrity 로그 | 종료 코드 3/4/5는 ⑤ 표를 봅니다. SAC 차단은 ②를 봅니다. 업그레이드였다면 `<I>.old`가 남아 있습니다(③ 5) |
| 업그레이드 뒤 서비스가 종료 코드 5로 끝남 | 응용 프로그램 로그 `mcp-monitor exited with code 5` | `config.db`가 이 서버보다 새 버전입니다. 더 새 버전을 다시 설치하거나 ⑦ 백업을 복원합니다(③ 5) |
| 더블클릭해도 아무것도 뜨지 않음, 또는 "이 앱의 일부가 차단되었습니다" | `CodeIntegrity/Operational` 3076/3077, `(Get-MpComputerStatus).SmartAppControlState` | SAC 차단입니다. ② 준비 2를 봅니다 |
| "MCP Monitor 창을 열 수 없습니다. Microsoft Edge WebView2 런타임이 …" | ② 준비 3의 레지스트리 값 | WebView2 런타임을 설치합니다. 서비스와 다른 PC의 브라우저는 그대로 씁니다 |
| 설치 중 `경고: 이 PC에 설치된 WebView2 런타임을 확인하지 못했습니다 …` | ② 준비 3의 두 레지스트리 키 | 런타임이 사용자별로만 설치된 PC면 창은 열리므로 무시해도 됩니다. 창이 열리지 않으면 런타임을 설치합니다 |
| 트레이 아이콘이 안 보임 | 작업 표시줄 모서리의 숨겨진 아이콘(^) | 설정 → 개인 설정 → 작업 표시줄 → 기타 시스템 트레이 아이콘에서 **MCP Monitor**를 켭니다. 앱이 끝났으면 시작 메뉴로 다시 엽니다 |
| 같은 폴더로 다시 설치가 `비어 있지 않고 … 설치 폴더(bundle.json)도 아닙니다`로 거부됨 | `<I>\mcp-monitor.exe.uninstalled` | 제거 뒤 다시 시작하지 않았습니다. PC를 다시 시작한 뒤 설치합니다(④) |
| `autostart`가 `오류: MCP Monitor가 설치되어 있지 않습니다 …` | 앱 및 기능 | 먼저 설치합니다 |
| 다른 PC에서 `http://<PC>:8701`이 안 열림 | `Get-NetFirewallRule -DisplayName "MCP Monitor*"`, 네트워크 프로필 | `--open-firewall`로 다시 설치하거나 규칙을 직접 만듭니다. 공용 프로필 네트워크면 열리지 않습니다 |
| 로그인 코드가 오지 않음 | `<D>\data\dev\otp-outbox.log` | ⑨ Dummy OTP. 등록되지 않은 이메일에는 코드를 보내지 않습니다. Admin이 **사용자** 화면에서 등록합니다 |
| `/admin/setup`이 "이 PC에서만" 안내를 보여 줌 | 주소 | 그 PC의 앱 창이나 `http://127.0.0.1:8700/admin/setup`으로 엽니다 |
| 로그 화면에 "색인 중" | **로그** 화면 상단 배너 | 업그레이드나 재색인 직후에는 정상입니다. 오래 남으면 `system` `logindex.cycle_failed`를 확인하고 ⑥ 재색인을 합니다 |
| `reindex`가 `오류: …`와 종료 코드 2 | 실행한 exe | `mcp-monitor.exe`가 아니라 `bin\monitor\mcp-monitor-server.exe`로 실행합니다(⑥) |
| `reindex`가 종료 코드 4 | 서비스 상태 | 서비스를 멈춘 뒤 다시 실행합니다 |
| 로그 검색이 느림 | 키워드가 흔한 낱말인지 | 사용자, 카테고리, 기간을 먼저 좁힙니다 |
| 오래된 로그가 지워지지 않음 | `system` `retention.run`의 `errors`, `skipped_compress` | 다른 프로그램이 파일을 열고 있으면(WinError 32) 다음 날 다시 시도합니다. 바로 하려면 그 프로그램을 닫고 서비스를 재시작합니다(시작 60초 뒤 실행) |
| `tamper` `log_file_removed` / `log_file_truncated` | 누가 `<D>\logs`를 건드렸는지 | 정리 작업이 지운 경우에는 생기지 않습니다. 손으로 지웠거나 다른 도구가 지운 것입니다 |
| 설정 화면 "서비스의 시작 유형이 이 설정과 달라요" | `sc.exe qc mcp-monitor` | 서비스가 다시 시작할 때 맞춥니다. 바로 맞추려면 설정을 다시 저장합니다(Local Admin) |
| 서비스가 몇 번 재시작한 뒤 멈춤 | 시스템 로그 7031/7034, 응용 프로그램 로그 `mcp-monitor` | 복구는 3번까지입니다(5s/10s/60s, 하루 뒤 초기화). 원인을 고친 뒤 `sc.exe start mcp-monitor`로 시작합니다 |
| 고지 창이 뜨지 않음 | `system` `agent.launch_failed`, `agent.launched`, **세션 → 수집 상태**, 그 세션의 `mcp-monitor.exe`(사용자 권한) | 서비스로 실행 중인지 확인합니다. WebView2 런타임이 없으면 기본 브라우저 탭으로 열립니다(⑨). SAC가 에이전트를 막았는지 CodeIntegrity 로그를 봅니다 |
| 제거 중 `[실패] remove_install_dir` / `remove_data` / `remove_webview_profiles` | 열린 파일 | 다른 세션의 고지 창·앱(`msedgewebview2.exe`)이 아직 끝나는 중일 수 있습니다. 잠시 뒤 같은 명령을 다시 실행합니다 |
