# MCP Monitor 운영 문서 (v1.0.0)

이 문서는 배포 묶음의 `docs\OPERATIONS.md`로도 함께 나갑니다. 기준 스펙은 `docs/PLAN.md` v0.8입니다(묶음에는 없음). 명령은 모두 **관리자 PowerShell**에서 실행합니다. 따로 적지 않으면 경로는 기본값입니다.

| 기호 | 기본값 |
|---|---|
| `<I>` 설치 폴더 | `C:\Program Files\MCP Monitor` |
| `<D>` 데이터 루트 | `C:\ProgramData\MCP Monitor` |
| `<exe>` | `<I>\bin\monitor\mcp-monitor.exe` |

## ① 구성 요약

- **서비스:** 이름 `mcp-monitor`, 표시 이름 `MCP Monitor`, 계정 `LocalSystem`.
  - Windows에 원래 있는 Microsoft 서비스 `McpManagementService`와는 **다른 서비스**입니다. 그 서비스는 건드리지 않습니다.
  - 서비스는 `<exe> service --root "<D>" --local-port 8700 --external-port 8701`로 실행됩니다.
- **두 포트:**

  | 채널 | 주소 | 쓰임 |
  |---|---|---|
  | Local | `127.0.0.1:8700` | 이 PC 안에서만. 전체 관리 기능, 첫 Admin 만들기, 에이전트 통신 |
  | External | `0.0.0.0:8701` | 다른 PC에서. 익명 상태 보드(`/`), 로그인 뒤 운영 기능(로그 조회 포함) |

- **설치 폴더 `<I>`**(묶음 그대로):
  - `bin\monitor\mcp-monitor.exe`: 서비스와 명령줄
  - `bin\agent\mcp-agent.exe`: 사용자 세션마다 서비스가 띄우는 에이전트. 고지 창과 창 이벤트를 맡습니다.
  - `web\`: 화면, `install\`: 스크립트, `docs\`: 이 문서, `bundle.json`: 버전과 빌드 정보
  - Program Files의 기본 권한을 그대로 씁니다. 사용자는 읽고 실행만 할 수 있습니다. 에이전트가 사용자 세션에서 실행되기 때문입니다.
- **데이터 루트 `<D>`**: SYSTEM과 Administrators만 접근합니다.

  | 경로 | 내용 | 백업 |
  |---|---|---|
  | `logs\YYYY-MM-DD.jsonl`, `.jsonl.gz` | 원본 로그. 날짜는 KST 기준이고 하루에 파일 하나입니다 | 필요 |
  | `data\config.db` | 설정, 사용자, MCP, 이력 (SQLite WAL) | 필요 |
  | `scripts\<mcp id>\` | MCP 조치 스크립트 | 필요 |
  | `data\index.db` | 로그 조회 색인. JSONL에서 다시 만들 수 있습니다 | 불필요 |
  | `data\install-state.json`, `data\auditpol-backup.csv` | 설치 전 감사 정책·레지스트리 값. 제거할 때 되돌리는 데 씁니다 | 권장 |
  | `data\collector-state.json`, `data\tamper-baseline.json` | 이벤트 로그 북마크와 우회 탐지 기준값 | 선택 |
  | `data\dev\otp-outbox.log` | 로그인 코드(Dummy OTP 공급자, ⑨) | 불필요 |
  | `data\.lock` | 같은 데이터 루트를 두 프로세스가 함께 쓰지 못하게 막는 잠금 | — |

## ② 설치

1. 묶음 zip을 확인합니다.
   - `Get-FileHash -Algorithm SHA256 mcp-monitor-1.0.0.zip`의 값이 `mcp-monitor-1.0.0.zip.sha256`의 값과 같은지 봅니다.
   - 같으면 원하는 곳에 압축을 풉니다(예: `C:\Temp\mcp-monitor-1.0.0`).
2. 무엇이 바뀌는지 먼저 봅니다(선택). DryRun은 관리자 권한이 필요 없고, 아무것도 바꾸지 않습니다. 실행할 단계 목록을 JSON으로 출력합니다.

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File C:\Temp\mcp-monitor-1.0.0\install\install.ps1 -DryRun
   ```

3. 관리자 PowerShell에서 `-DryRun` 없이 **한 번** 실행합니다.
   - 끝나면 `설치 완료: http://127.0.0.1:8700/admin/setup …`이 출력됩니다.
   - 종료 코드: 0 성공, 1 실패(관리자가 아닐 때 포함), 2 인자 오류.
   - 관리자가 아니면 아무것도 바꾸지 않고 종료합니다.

**`install.ps1` 매개변수**

| 매개변수 | 기본값 | 설명 |
|---|---|---|
| `-Source` | 스크립트가 든 묶음 폴더 | `bundle.json`이 있는 묶음 폴더 |
| `-InstallDir` | `%ProgramFiles%\MCP Monitor` | 설치 폴더. Program Files 밖이면 경고합니다. SYSTEM이 실행하는 파일을 사용자가 고칠 수 없어야 합니다. 비어 있거나 이전 설치 폴더여야 합니다 |
| `-DataRoot` | `%ProgramData%\MCP Monitor` | 데이터 루트(로그, DB, 스크립트). 없는 폴더, 빈 폴더, 이전 데이터 루트(`data\mcp-monitor-data-root.json` 또는 `install-state.json`)만 받습니다. 드라이브 루트·시스템 폴더, 설치 폴더·묶음과 겹치는 폴더, 정션·심볼릭 링크가 든 폴더, SYSTEM·Administrators·설치하는 계정이 아닌 사용자가 소유한 파일이 든 폴더는 거부합니다(종료 코드 2) |
| `-OpenFirewall` | 꺼짐 | 8701 인바운드 방화벽 규칙 `MCP Monitor (8701)`을 만듭니다. 도메인·개인 프로필만이고, 공용 프로필은 열지 않습니다. **기본은 꺼짐**입니다(§2 #6) |
| `-SkipAuditPolicy` | 꺼짐 | 감사 정책, 레지스트리, 이벤트 로그 크기 단계를 건너뜁니다. 이 경우 세션·명령 수집이 줄어듭니다 |
| `-LocalPort` | `8700` | Local 채널 포트 |
| `-ExternalPort` | `8701` | External 채널 포트. `-LocalPort`와 달라야 합니다 |
| `-DryRun` | 꺼짐 | 실행할 단계를 JSON으로 출력만 합니다 |

**설치 단계**(`-DryRun` 출력의 `id`. 기본 19단계, `-OpenFirewall`이면 20단계)

| 단계 | id |
|---|---|
| 확인 | `require_admin`, `check_os` |
| 기존 서비스 정지 | `stop_existing` |
| 묶음 복사(`robocopy /MIR`) | `copy_bundle` |
| 데이터 폴더와 ACL. 루트의 ACL을 처음부터 새로 만들고(소유자 Administrators, 상속 끊음, SYSTEM·Administrators 모든 권한만), 그 아래는 모두 자기 ACE를 지우고 루트에서 상속만 받게 한 뒤, 다시 읽어 다른 ACE·소유자·정션이 하나라도 있으면 설치를 멈춥니다. SID로 지정하므로 한국어 Windows에서도 같습니다 | `secure_data_root` |
| 감사 정책. 처음 한 번 백업한 뒤 하위 범주 GUID로 켭니다 | `audit_backup`, `audit_policy_success`, `audit_policy_failure` |
| 레지스트리 | `registry_cmdline`, `registry_scriptblock` |
| 이벤트 로그 크기. Security 256 MB, PowerShell/Operational 64 MB | `security_log_size`, `powershell_log_size` |
| 서비스 등록 | `service_install`(`delayed-auto`), `service_description`, `service_failure`, `service_failureflag` |
| 방화벽(`-OpenFirewall`일 때만) | `firewall` |
| 설치 상태 기록 | `install_state` |
| 시작과 준비 확인 | `service_start`, `wait_ready`(30초 동안 `/api/channel`) |

- 감사 정책만 따로 켜거나 되돌릴 때는 `install\audit-policy.ps1 -Enable` / `-Restore <백업 csv>`를 씁니다(`-DryRun` 가능).
  - 설치 전에 `-Enable`을 쓰면 데이터 루트를 설치와 같은 ACL로 먼저 만들고(`secure_data_root`), 바꾸기 전 레지스트리 값을 `<D>\data\audit-policy-state.json`에 처음 한 번 기록합니다(`record_registry`).
  - 나중의 설치는 그 값을 `install-state.json`의 `registry_before`로 이어받습니다. `-Restore`와 제거(`-RestoreAuditPolicy`)는 `install-state.json`, 없으면 `audit-policy-state.json`의 값으로 되돌립니다. 되돌리는 값은 설치가 바꾸는 두 레지스트리 값(DWORD)뿐입니다.

**첫 Admin 만들기**

1. 그 PC에서 브라우저로 `http://127.0.0.1:8700/admin/setup`을 엽니다. External 채널에서는 할 수 없습니다.
2. 이메일과 이름을 넣어 Admin을 만듭니다.
3. 같은 이메일로 로그인합니다. 로그인 코드는 `<D>\data\dev\otp-outbox.log`의 마지막 줄에 있습니다(⑨ Dummy OTP). 관리자만 읽을 수 있습니다.
4. **사용자** 화면에서 로그인할 MCP 개발자와 Admin의 이메일을 등록합니다.

**Smart App Control(SAC)이 켜진 PC (W26)**

- 묶음의 실행 파일은 PyInstaller로 만들었고 **코드 서명이 없습니다**.
- 개발 PC(SAC 켜짐)에서는 막히지 않았습니다. 그러나 SAC는 파일마다 평판으로 판단하므로, 다른 PC에서는 결과가 다를 수 있습니다.
- 설치 전에 막히는지 확인합니다. `C:\Temp\mcp-monitor-1.0.0\bin\monitor\mcp-monitor.exe --version`이 `mcp-monitor 1.0.0`을 출력하면 됩니다.
- 막히면 증상은 다음과 같습니다.
  - "이 앱의 일부가 차단되었습니다" 같은 알림이 뜹니다.
  - 설치 중 `[실패] service_start`가 나옵니다.
  - 이벤트 뷰어 `응용 프로그램 및 서비스 로그 → Microsoft → Windows → CodeIntegrity → Operational`에 `mcp-monitor.exe` 차단 기록이 남습니다.
- 막혔을 때의 조치:
  - SAC를 끄지 말고 개발팀에 알립니다. 서명된 python.org 런타임을 쓰는 묶음 방식 B로 다시 빌드하는 것이 정해 둔 대안입니다.
  - SAC를 끄는 것은 기기 소유자의 보안 결정입니다.

## ③ 업그레이드

1. 새 묶음을 풀고, 그 묶음의 `install\install.ps1`을 **같은 매개변수로** 다시 실행합니다.
2. 스크립트가 하는 일:
   - 서비스를 멈추고 설치 폴더를 새 묶음으로 바꿉니다.
   - 서비스 설정은 `sc config`로 갱신합니다.
3. 그대로 남는 것:
   - 데이터 루트(로그, 설정, 사용자, 스크립트)는 그대로입니다.
   - 감사 정책 백업(`auditpol-backup.csv`)과 바꾸기 전 레지스트리 값(`install-state.json`의 `registry_before`)은 **첫 설치 때 것**을 유지합니다. 그래서 나중에 제거하면 설치 전 상태로 돌아갑니다.
4. 업그레이드한 뒤 처음 시작할 때:
   - 새 버전이 `config.db` 마이그레이션을 적용합니다.
   - `index.db`의 스키마가 바뀌었으면 지우고 다시 색인합니다. 그동안 로그 화면에 "색인 중"이 보입니다.
5. 시작 유형은 설치가 `delayed-auto`로 되돌립니다. 서비스가 시작하면서 웹 설정값으로 다시 맞춥니다(W25).
6. **이전 버전으로 되돌리기:**
   - 새 버전이 마이그레이션한 `config.db`는 옛 버전이 열지 않습니다(종료 코드 5).
   - 업그레이드 전에 ⑦ 백업을 해 두고, 되돌릴 때는 옛 묶음을 설치한 뒤 백업을 복원합니다.

## ④ 제거

```powershell
& "C:\Program Files\MCP Monitor\install\uninstall.ps1" [-RemoveData] [-RestoreAuditPolicy] [-DryRun]
```

- 설치 폴더 안의 스크립트를 실행해도 됩니다. 제거 전에 System32로 옮겨 실행합니다.

| 매개변수 | 기본값 | 설명 |
|---|---|---|
| `-InstallDir` | `install-state.json`의 값, 없으면 `%ProgramFiles%\MCP Monitor` | 지울 설치 폴더. `bundle.json`이 있을 때만 지웁니다 |
| `-DataRoot` | `%ProgramData%\MCP Monitor` | 데이터 루트. `-RemoveData`는 우리 표시(`data\mcp-monitor-data-root.json` 또는 `install-state.json`)가 있을 때만 지우고, 드라이브 루트·시스템 폴더는 거부합니다(종료 코드 2). 데이터 루트가 설치 폴더 안이면 `-RemoveData` 없이는 거부합니다 |
| `-RemoveData` | 꺼짐 | 데이터 루트 전체(로그, `config.db`, 스크립트, `collector-state.json`, `tamper-baseline.json`)와 사용자마다의 Edge 고지 프로필(`%LOCALAPPDATA%\mcp-monitor`)을 지웁니다. **되살릴 수 없습니다** |
| `-RestoreAuditPolicy` | 꺼짐 | 첫 설치 때의 `auditpol` 백업과 레지스트리 값으로 되돌립니다 |
| `-DryRun` | 꺼짐 | 단계만 출력합니다 |

- **기본 동작은 데이터를 남깁니다**(W31). 서비스, 방화벽 규칙(설치 때의 포트), 설치 폴더만 지웁니다. 감사 기록은 쉽게 지우지 않는다는 원칙입니다.
- 감사 정책을 되돌릴지는 기기 소유자가 정합니다. 되돌리면 그 뒤로 RDP 로그온 실패와 명령줄이 Windows에 남지 않습니다.
- 다른 `-ExternalPort`로 다시 설치한 적이 있다면, 옛 포트의 방화벽 규칙은 남습니다. `netsh advfirewall firewall show rule name=all | findstr "MCP Monitor"`로 확인합니다.

## ⑤ 서비스 운영

- **시작 유형은 웹 설정이 기준입니다**(W25).
  - **설정 → 부팅 시작 유형**에서 `자동`, `자동(지연된 시작)`, `수동` 중에서 고릅니다. Local 채널의 Admin만 바꿀 수 있습니다.
  - 저장하면 곧바로 SCM에 적용하고, `admin.audit` `service_start_type_apply`로 남깁니다.
  - 서비스가 시작할 때마다 다시 맞춥니다. 그래서 `sc.exe config`나 서비스 관리자에서 손으로 바꾼 값은 다음 시작 때 웹 설정값으로 돌아갑니다.
  - 설정 화면의 **Windows 서비스** 줄에서 지금 SCM 값과 일치 여부를 볼 수 있습니다.
  - 예외: 관리자가 `services.msc`에서 **사용 안 함**으로 바꾼 서비스는 그대로 둡니다(사고 대응). 설정 화면에 `사용 안 함`과 안내가 보이고, 설정을 저장해도 다시 켜지 않습니다(`service.start_type` `disabled`, 감사 결과 `error`). 다시 쓰려면 `services.msc`에서 시작 유형을 바꿉니다.
- **시작과 정지:** `sc.exe start mcp-monitor`, `sc.exe stop mcp-monitor`(또는 `services.msc`).
  - 정지 순서는 다음과 같습니다.
    1. 그때까지 쌓인 로그를 먼저 디스크에 씁니다.
    2. 수집기가 멈춥니다. 에이전트가 종료 신호를 받고 고지 창을 닫습니다.
    3. 실행 중인 MCP 스크립트는 10초 기다린 뒤 프로세스 트리째 종료합니다(W21). 그 기록도 곧바로 디스크에 씁니다.
    4. 마지막으로 웹 서버, 보존 정리, 색인, 로그가 멈춥니다.
  - 정지하는 동안 2초마다 SCM에 진행(`STOP_PENDING`, 체크포인트 증가, 다음 보고까지 10초)을 알립니다. 전체 정지는 **최대 50초**이고, 넘으면 그 자리에서 `STOPPED`를 보고하고 끝냅니다(이벤트 로그에 "did not stop within 50 s").
  - Windows 종료·재시작 때는 PRESHUTDOWN 알림을 받아 같은 순서로 멈춥니다. 서비스가 시작할 때 자기 PRESHUTDOWN 시간 제한을 60초로 정합니다(보통의 종료 알림은 약 5초뿐).
  - SCM이 요청한 정지는 중간에 오류가 나도 `STOPPED`로 끝납니다. 오류는 응용 프로그램 이벤트 로그에 남고, SCM이 충돌로 보고 다시 시작하지 않습니다. `failureflag 1`에서는 0이 아닌 종료 코드도 복구 동작을 부르므로, 이때의 종료 코드는 0입니다.
- **복구 동작**(설치가 설정합니다):
  - 예기치 않게 끝나면 5초, 10초, 60초 뒤에 다시 시작합니다. 실패 횟수는 하루(86,400초) 뒤 초기화됩니다.
  - `failureflag 1`이라서, 오류 코드로 끝난 경우에도 복구 동작이 돕니다.
  - 확인: `sc.exe qfailure mcp-monitor`.
- **종료 코드와 조치:**

  | 코드 | 뜻 | 조치 |
  |---|---|---|
  | 3 | 포트 사용 중(8700 또는 8701) | `Get-NetTCPConnection -LocalPort 8700,8701 -State Listen \| Select LocalAddress,LocalPort,OwningProcess`로 점유한 프로세스를 찾아 끝냅니다. 다른 포트를 쓰려면 같은 묶음으로 `-LocalPort`/`-ExternalPort`를 바꿔 다시 설치합니다 |
  | 4 | 데이터 루트 사용 중(`data\.lock`) | 같은 `<D>`를 쓰는 다른 MCP Monitor(손으로 띄운 콘솔 서버, 진행 중인 `reindex`)를 끝냅니다 |
  | 5 | `config.db`가 이 프로그램보다 새 버전 | 더 새 버전을 설치하거나, 이 버전 때의 백업을 복원합니다(③ 6, ⑦) |
  | 1 | 예기치 않은 오류 | 아래 이벤트 뷰어와 `logs\<오늘>.jsonl`의 `system` 줄을 봅니다 |

- **오류를 보는 곳.** 서비스로 실행되면 콘솔 출력이 없습니다. 다음 세 곳을 봅니다.
  - 이벤트 뷰어 → `Windows 로그 → 응용 프로그램`, 원본 `mcp-monitor`: "mcp-monitor exited with code N"과 예기치 않은 예외의 트레이스백이 남습니다. 메시지 설명을 찾을 수 없다는 문구가 붙어도 본문은 그대로 읽힙니다.
  - 이벤트 뷰어 → `Windows 로그 → 시스템`, 원본 `Service Control Manager`:
    - 7031, 7034: 예기치 않은 종료와 복구 동작
    - 7000, 7009: 시작 실패와 시간 초과
  - `<D>\logs\<오늘>.jsonl`의 `"cat":"system"` 줄(`collector.status`, `agent.launch_failed`, `logindex.*`, `retention.*`, `service.start_type` 등).
    - 관리 화면 **로그**에서 카테고리 `시스템`으로도 볼 수 있습니다.
  - 같은 오류를 콘솔에서 재현하려면 서비스를 멈춘 뒤 `& "<exe>" --root "<D>"`로 실행합니다. 한 줄 오류와 종료 코드가 나옵니다. Ctrl+C로 끝냅니다.

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
  - 키워드는 낱말 앞부분 검색입니다. 전체의 수십 %에 맞는 넓은 낱말(예: `chrome`, `focus`)은 300ms를 넘을 수 있습니다. 사용자나 카테고리를 먼저 고르면 빨라집니다(`docs/verification/perf-p6.md` 4절).
- **색인 다시 만들기.** `index.db`가 깨졌거나 원본 JSONL을 복원한 뒤에 합니다. 서비스를 먼저 멈춰야 합니다. 서비스가 떠 있으면 종료 코드 4로 거절됩니다.

  ```powershell
  sc.exe stop mcp-monitor
  & "C:\Program Files\MCP Monitor\bin\monitor\mcp-monitor.exe" reindex --root "C:\ProgramData\MCP Monitor"
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
     - 권장: `<D>\data\install-state.json`, `<D>\data\auditpol-backup.csv`
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
  - 로그인 코드와 세션 쿠키가 암호화되지 않고 오갑니다. 믿을 수 있는 사내망에서만 열고, 방화벽은 필요한 프로필에만 엽니다(`-OpenFirewall`은 도메인·개인).
  - HTTPS 옵션은 추후입니다.
- **RDP 계정은 Windows 표준 사용자로 운영합니다**(§14, §2 #4).
  - 관리자 권한 사용자는 에이전트, 감사 정책, 이벤트 로그를 끄거나 지울 수 있습니다.
  - MCP Monitor는 그것을 **막지 못하고 우회 탐지로만 남깁니다**. 남는 곳은 `tamper` 줄, 대시보드의 **우회 탐지 이벤트** 카드, 로그인한 화면의 실시간 알림입니다.
  - 외부 알림(메일, 웹훅)은 추후입니다.
- **데이터 루트 ACL:**
  - `<D>`는 상속을 끊고 SYSTEM(`S-1-5-18`)과 Administrators(`S-1-5-32-544`)만 모든 권한을 가집니다. 소유자는 Administrators입니다.
  - 그래서 표준 사용자는 로그, 설정, 스크립트, 로그인 코드를 읽을 수 없습니다.
  - 확인: `icacls "C:\ProgramData\MCP Monitor"`.
  - 설치 폴더 `<I>`는 Program Files 권한 그대로 둡니다. 사용자는 읽고 실행만 하고, 쓸 수 없습니다.
- **스크립트는 SYSTEM으로 실행됩니다.**
  - 스크립트 편집은 Local 채널에서 MCP 소유자 또는 Admin만 할 수 있습니다.
  - 실행 직전에 저장된 해시와 비교합니다. 파일을 손으로 고치면 실행이 막히고 우회 탐지로 남습니다.

## ⑨ 알려진 동작

- **서비스가 다시 시작하면 MCP의 `FAILED` 상태와 자동 조치 횟수가 초기화됩니다**(W17).
  - 재부팅 뒤에는 감시를 새로 시작합니다.
  - 서비스가 반복해서 재시작되면 그만큼 자동 조치가 다시 돕니다. 이 경우 이벤트 뷰어와 `mcp.action` 로그를 봅니다.
- **스크립트 저장 중 디스크 오류가 나면**, 그 뒤 첫 실행이 해시 불일치(`hash_mismatch`)로 막힐 수 있습니다(W19). 소유자가 스크립트를 **한 번 다시 저장**하면 풀립니다.
- **cmd 내부 명령(`dir`, `cd`, `del` …)은 수집하지 않습니다**(§2 #7).
  - 남는 것: `cmd.exe` 실행과 인자, `cmd /c …`, 배치 파일 실행, cmd에서 실행한 외부 프로그램.
  - PowerShell 명령은 스크립트 블록 로깅(4104)으로 남습니다.
- **로그인 코드(Dummy OTP):**
  - 1.0.0에는 실제 메일·문자 발송 공급자가 없습니다.
  - 로그인 코드는 `<D>\data\dev\otp-outbox.log`에 `<시각> <이메일> <코드>` 줄로 쌓이고, PC 관리자만 읽을 수 있습니다.
  - 다른 PC에서 로그인하는 사람에게는 관리자가 코드를 전달해야 합니다. 실제 공급자는 추후입니다.
- **고지 창**은 Edge `--app` 창입니다(진짜 모달은 아님). 확인 전에 닫으면 1초 뒤 다시 뜨고, 닫은 사실이 남습니다.
- 수집 큐가 넘치면 오래된 이벤트부터 버리고, 버린 수를 `system` `collector.dropped`/`logstore.dropped`로 남깁니다.
- 로그 화면에서 넓은 키워드는 느릴 수 있습니다(⑥).

## ⑩ 문제 해결

| 증상 | 확인 | 조치 |
|---|---|---|
| `관리자 권한(Administrator)으로 PowerShell을 열고 다시 실행하세요.` | — | 관리자 PowerShell에서 다시 실행합니다. 아무것도 바뀌지 않았습니다 |
| `오류: …` 출력, 종료 코드 2 | 메시지의 매개변수 | 묶음 폴더(`bundle.json`), 겹치는 폴더, 비어 있지 않은 설치 폴더, 같은 포트 값을 고칩니다 |
| `[실패] <id>: …` | ②의 단계표 | 그 단계만 고친 뒤 다시 실행합니다. 같은 스크립트를 여러 번 실행해도 안전합니다 |
| `[실패] service_start`, 또는 `wait_ready` 30초 초과 | `sc.exe query mcp-monitor`, ⑤ 오류를 보는 곳, CodeIntegrity 로그 | 종료 코드 3/4/5는 ⑤ 표를 봅니다. SAC 차단은 ②를 봅니다 |
| 다른 PC에서 `http://<PC>:8701`이 안 열림 | `Get-NetFirewallRule -DisplayName "MCP Monitor*"`, 네트워크 프로필 | `-OpenFirewall`로 다시 설치하거나 규칙을 직접 만듭니다. 공용 프로필 네트워크면 열리지 않습니다 |
| 로그인 코드가 오지 않음 | `<D>\data\dev\otp-outbox.log` | ⑨ Dummy OTP. 등록되지 않은 이메일에는 코드를 보내지 않습니다. Admin이 **사용자** 화면에서 등록합니다 |
| `/admin/setup`이 "이 PC에서만" 안내를 보여 줌 | 주소 | 그 PC의 `http://127.0.0.1:8700/admin/setup`으로 엽니다 |
| 로그 화면에 "색인 중" | **로그** 화면 상단 배너 | 업그레이드나 재색인 직후에는 정상입니다. 오래 남으면 `system` `logindex.cycle_failed`를 확인하고 ⑥ 재색인을 합니다 |
| `reindex`가 종료 코드 4 | 서비스 상태 | 서비스를 멈춘 뒤 다시 실행합니다 |
| 로그 검색이 느림 | 키워드가 흔한 낱말인지 | 사용자, 카테고리, 기간을 먼저 좁힙니다 |
| 오래된 로그가 지워지지 않음 | `system` `retention.run`의 `errors`, `skipped_compress` | 다른 프로그램이 파일을 열고 있으면(WinError 32) 다음 날 다시 시도합니다. 바로 하려면 그 프로그램을 닫고 서비스를 재시작합니다(시작 60초 뒤 실행) |
| `tamper` `log_file_removed` / `log_file_truncated` | 누가 `<D>\logs`를 건드렸는지 | 정리 작업이 지운 경우에는 생기지 않습니다. 손으로 지웠거나 다른 도구가 지운 것입니다 |
| 설정 화면 "서비스의 시작 유형이 이 설정과 달라요" | `sc.exe qc mcp-monitor` | 서비스가 다시 시작할 때 맞춥니다. 바로 맞추려면 설정을 다시 저장합니다(Local Admin) |
| 서비스가 몇 번 재시작한 뒤 멈춤 | 시스템 로그 7031/7034, 응용 프로그램 로그 `mcp-monitor` | 복구는 3번까지입니다(5s/10s/60s, 하루 뒤 초기화). 원인을 고친 뒤 `sc.exe start mcp-monitor`로 시작합니다 |
| 고지 창이 뜨지 않음 | `system` `agent.launch_failed`, `agent.launched`, **세션 → 수집 상태** | Edge 설치 여부를 확인합니다(없으면 기본 브라우저 탭으로 엽니다). 서비스로 실행 중인지 확인합니다 |
| 제거 중 `[실패] remove_install_dir` / `remove_data` | 열린 파일 | 사용자 세션의 고지 창(Edge)과 `mcp-agent.exe`가 끝났는지 보고 다시 실행합니다 |
