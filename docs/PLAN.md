# Strategy MCP Monitor — 하이레벨 개발 계획서

- 버전: **v0.4** (2026-11-04)
- 상태: 요구사항 확정. 구현 착수 전입니다.
- 대상: **Windows 11 Pro**에서 실행되는 MCP 관리 + RDP 접속·행동 감사 웹 애플리케이션

### 변경 이력
| 버전 | 내용 |
|---|---|
| v0.1 | 최초 작성 (아키텍처, MCP 모니터, 세션·행동 로그, UI 디자인 시스템) |
| v0.2 | Win 11 Pro 확정, 이메일 + OTP 로그인(Dummy), 역할·소유자 기반 권한, 사전 고지 다이얼로그, 부팅 자동 실행, 로그 필터, 성능 설계, 버전 정책, 디자인 스킬 |
| v0.3 | **역할 명칭 변경**: Admin → **MCP 개발자**, Super Admin → **Admin**. **User 역할 삭제**(로그인은 MCP 개발자·Admin만). Admin이 다른 Admin을 지정할 수 있음. 로그인 가능 이메일은 Admin이 등록. **cmd 내부 명령 수집(Clink) 제외**. 고지 다이얼로그는 **연결될 때마다** 표시. 로그 보존 기간 설정 UI 추가 |
| v0.4 | 스크립트 예외 격리 추가: 별도 프로세스 실행, **120초 타임아웃**, 결과 분류(ok/failed/timeout/error), 출력·동시 실행 제한 (R20) |

---

## 1. 요구사항

| # | 요구사항 | 반영 위치 |
|---|---|---|
| R1 | localhost 접속 = 세부 설정이 가능한 관리 화면, 0.0.0.0 접속 = 일반 화면 | §4, §5.2 |
| R2 | RDP 접속자의 도메인, IP 등 수집 가능한 접속 정보 전부 수집 | §5.3 |
| R3 | **누구나(익명)** MCP 현재 상태와 RDP 접속 중 여부·접속자 정보를 볼 수 있음. **IP는 가리지 않음** | §4.3, §6.2 |
| R4 | 이메일 + **OTP 로그인**. 현재는 **Dummy OTP**. **로그인은 MCP 개발자와 Admin만** 가능 | §4.1 |
| R5 | **사용자 관리는 Admin**이 함. 로그인 가능 이메일을 Admin이 등록하고, Admin이 다른 Admin을 지정할 수 있음 | §4.2, §4.3 |
| R6 | MCP 설정 변경은 **MCP 개발자 이상** | §4.3 |
| R7 | **MCP 시작·재실행·종료는 MCP 개발자 이상이면 모든 MCP에 대해** 가능 | §4.3 |
| R8 | **스크립트 추가·수정·삭제는 localhost에서, 해당 MCP를 등록한 사용자(소유자)만** 가능. 외부 브라우저에서는 불가 | §4.3, §5.8 |
| R9 | **소유권 이전은 localhost의 Admin만** 가능 | §4.3 |
| R10 | 전역 설정·고지 메시지·부팅 옵션·로그 보존 기간은 **localhost Admin만** 변경 | §4.3, §6.4 |
| R11 | 날짜별 일일 로그(`logs/`). 실행 프로그램, 명령 프롬프트(프로세스 명령줄과 PowerShell), 창 조작 기록. **cmd 내부 명령은 수집하지 않음** | §5.4, §5.6 |
| R12 | **부팅 시 자동 실행** 옵션 | §5.9 |
| R13 | RDP **연결될 때마다** 행동 감사 사전 고지 다이얼로그('확인' 버튼만). 메시지는 Admin UI에서 편집 | §5.5 |
| R14 | 로그 조회에서 **시간대별·사용자별 필터** | §6.4 |
| R15 | **로그 보존 기간 기본 180일, UI에서 설정** | §5.6, §6.4 |
| R16 | MCP 하나씩 등록(URL·포트), 전역 ping 주기, 포트 점유 프로세스 감시, 10초 점검 → 1초 재측정 → 설정 시간 경과 시 조치, 시작·종료 스크립트 필수 | §5.7, §5.8 |
| R17 | Dummy MCP(서울 날씨, 계산기, 서울 시계) | §5.10 |
| R18 | 최신 CSS 디자인, 라이브러리·컴포넌트, 애니메이션. **디자인과 성능을 모두 고려** | §6, §7, §12 |
| R19 | Python·Node는 **보안 이슈 없는 최신 안정 버전** | §9.1 |
| R20 | MCP 시작·재실행·종료 스크립트에서 **오류가 나거나 2분 이상 지연되면 예외 처리**하고, 메인 프로세스에는 지장이 없어야 함 | §5.8 |

---

## 2. 핵심 검토 결과

| # | 내용 | 대응 |
|---|---|---|
| 1 | Windows 11 Pro는 **동시에 RDP 세션 1개**만 허용합니다. 원격 접속 중에는 콘솔 세션이 잠기거나 끊깁니다. | UI는 다중 세션도 표시할 수 있게 만들되, 기본 레이아웃은 1명 기준으로 설계합니다. |
| 2 | 개발 PC(Windows 11 Home)는 RDP 접속을 받을 수 없습니다. | 개발 중에는 가짜(Mock) 세션 공급자를 쓰고, P4·P5 통합 테스트는 **Win 11 Pro 실기기나 VM**에서 진행합니다. |
| 3 | RDP 접속자(MCP 개발자·Admin)는 그 PC의 localhost에도 접근할 수 있습니다. | localhost 접속에도 **OTP 로그인이 필수**입니다. localhost라는 조건은 권한을 넓혀줄 뿐 본인 확인을 대신하지 않습니다. |
| 4 | RDP 사용자가 Windows 관리자 권한을 가지면 에이전트나 감사 정책을 끄거나 로그를 지울 수 있습니다. | 완전히 막을 수 없으므로 **우회 탐지 이벤트**(에이전트 종료, 감사 정책 변경, 로그·스크립트 파일 변경)를 기록하고 알립니다. RDP 계정은 Windows 표준 사용자로 운영하길 권장합니다. |
| 5 | 외부 접속 포트(8701)는 HTTP라서 OTP와 세션 쿠키가 평문으로 오갑니다. | 기본은 HTTP로 두고, **HTTPS 옵션**을 제공합니다 (§14). |
| 6 | Windows 방화벽은 기본적으로 외부에서 8701로 들어오는 연결을 막습니다. | 방화벽은 사용자가 필요할 때 직접 설정합니다. 설치 스크립트의 `-OpenFirewall` 옵션은 기본으로 꺼 둡니다. |
| 7 | **cmd 내부 명령(`dir`, `cd`, `del` 등)은 수집하지 않습니다** (결정). | cmd 관련 기록은 `cmd.exe` 실행과 인자, cmd에서 실행한 외부 프로그램, `cmd /c ...`, 배치 파일 실행까지입니다. 이 한계를 Admin 로그 화면 도움말에도 적어 둡니다. |
| 8 | 지금 PC의 런타임(Python 3.14.3, Node 24.14.0)은 최신 보안 패치보다 뒤처져 있습니다. | §9.1 정책대로 업그레이드합니다. |

---

## 3. 시스템 아키텍처

```
┌─────────────────────────── Windows 11 Pro Host ──────────────────────────────┐
│                                                                              │
│  ┌──────────── mcp-monitor (Windows Service, LocalSystem, 자동 시작) ─────┐   │
│  │                                                                        │   │
│  │  [Local 채널]    127.0.0.1:8700 ── 전체 기능 (OTP 로그인 + 역할 검사)   │   │
│  │  [External 채널] 0.0.0.0:8701   ── 익명 상태 보드 + 로그인 후 운영 기능 │   │
│  │                                    (스크립트·전역 설정·사용자 관리      │   │
│  │                                     라우트는 등록하지 않음)            │   │
│  │                                                                        │   │
│  │  Auth (이메일 + OTP, OtpProvider: Dummy → 추후 SMTP/TOTP) · 사용자·역할 │   │
│  │  MCP Monitor Engine ─ Probe(MCP ping/TCP/ICMP) ─ Port→PID ─ 상태 머신   │   │
│  │  Script Runner (소유자 스크립트, timeout, 출력 캡처, 해시 검증)         │   │
│  │  Session Collector (WTS API + TerminalServices/Security 이벤트)         │   │
│  │  Activity Collector (WMI 프로세스 · 4688 명령줄 · PowerShell 4104)      │   │
│  │  Agent Supervisor (세션별 에이전트 기동·감시, 우회 탐지)               │   │
│  │  Log Writer (logs/YYYY-MM-DD.jsonl + data/index.db, 배치 기록, 보존)    │   │
│  └───────────────▲────────────────────────────────────────────────────────┘   │
│                  │ Named Pipe (세션 ID 검증)                                  │
│  ┌───────────────┴──────────────┐                                            │
│  │ mcp-agent (RDP 사용자 세션)  │                                            │
│  │ · 연결마다 사전 고지 다이얼로그│                                            │
│  │   (WebView2, 같은 디자인)    │                                            │
│  │ · 포그라운드 창/최소화/제목  │                                            │
│  │ · 유휴 상태                  │                                            │
│  └──────────────────────────────┘                                            │
│  Dummy MCPs:  seoul-weather :9101   calculator :9102   seoul-clock :9103     │
└──────────────────────────────────────────────────────────────────────────────┘
      ▲ RDP 3389 (MCP 개발자·Admin)           ▲ http(s)://<host>:8701 (누구나)
```

---

## 4. 인증·권한 설계

### 4.1 로그인: 이메일 + OTP
1. **이메일 입력:** Admin이 사용자 관리에 등록한 활성 이메일만 로그인할 수 있습니다. 가입 기능은 없고, 도메인 제한도 두지 않습니다. 등록되지 않은 이메일이어도 화면 응답은 동일하게 보여서, 등록 여부를 알아낼 수 없게 합니다.
2. **OTP 발급:** 서버가 6자리 OTP를 만들어 `OtpProvider.send(email, code)`를 호출합니다.
   - 유효 시간 5분, 1회용입니다.
   - 5회 틀리면 무효가 됩니다.
   - 재발송은 60초 뒤부터 가능합니다.
   - 이메일·IP 단위로 요청 횟수를 제한합니다.
3. **세션 발급:** 인증에 성공하면 세션 쿠키를 발급합니다.
   - 쿠키 속성은 `HttpOnly`, `SameSite=Strict`이고, HTTPS일 때는 `Secure`도 붙습니다.
   - 세션은 최대 8시간이며, 30분 동안 사용이 없으면 만료됩니다.
   - 변경 요청은 CSRF 토큰을 검사합니다.
4. **채널별 세션:** 8700과 8701은 쿠키를 공유하지 않으므로 각각 로그인합니다.
5. **감사 기록:** 모든 로그인 시도를 남깁니다(성공·실패, 채널, IP, User-Agent). localhost에서는 브라우저를 연 Windows 계정도 함께 기록합니다.

**OtpProvider (교체 가능)**
| 구현 | 단계 | 동작 |
|---|---|---|
| `DummyOtpProvider` | **현재** | 코드를 서비스 콘솔과 `data/dev/otp-outbox.log`에 출력합니다. 개발 모드에서는 고정 코드도 허용하고, 로그인 화면에 "개발용 OTP 모드" 배지를 표시합니다. |
| `SmtpOtpProvider` | 추후 | 사내 SMTP로 메일을 발송합니다. |
| `TotpProvider` | 추후 | TOTP 앱을 사용합니다 (RFC 6238). |

**최초 실행:** 등록된 사용자가 없으면 **localhost 채널에서만** 초기 설정 화면이 열리고, 여기서 첫 계정을 **Admin**으로 만듭니다.

### 4.2 역할
| 역할 | 로그인 | 설명 |
|---|:-:|---|
| **익명** | — | 로그인하지 않은 모든 사람. 상태 보드만 볼 수 있습니다. |
| **MCP 개발자** | ✓ | MCP를 등록하고 운영합니다. 자신이 등록한 MCP의 스크립트를 관리합니다. |
| **Admin** | ✓ | 최상위 관리자입니다. MCP 개발자의 모든 권한에 더해 사용자 관리, 소유권 이전, 전역 설정을 담당합니다. **다른 사용자를 Admin으로 지정할 수 있습니다.** |

- RDP로 접속하는 사람은 MCP 개발자 또는 Admin 계정을 가진 사람입니다.
- **Admin은 항상 한 명 이상 남아 있어야 합니다.** 마지막 Admin은 삭제·비활성화·강등할 수 없습니다.
- 역할 변경, 사용자 추가·비활성화는 모두 감사 로그에 남습니다.

### 4.3 권한 매트릭스

✓ = 허용, ✗ = 불가, (L) = **localhost 채널에서만** 허용

| 기능 | 익명 | MCP 개발자 | Admin |
|---|:-:|:-:|:-:|
| MCP 현재 상태 조회 | ✓ | ✓ | ✓ |
| RDP 접속 중 여부·접속자 정보(IP 포함) 조회 | ✓ | ✓ | ✓ |
| MCP 상태 이력·지연 그래프 상세 | ✗ | ✓ | ✓ |
| 세션(접속) 이력 조회 | ✗ | ✓ | ✓ |
| 행동 로그 조회·내보내기 | ✗ | ✓ | ✓ |
| MCP 설정 변경 (이름, 호스트·포트, 프로브, 임계값, 자동 복구, 점검 모드) | ✗ | ✓ | ✓ |
| **MCP 시작 / 재실행 / 종료 (모든 MCP)** | ✗ | ✓ | ✓ |
| MCP 신규 등록 (start·stop 스크립트를 함께 작성해야 하므로) | ✗ | (L) | (L) |
| MCP 삭제 | ✗ | (L) 소유자만 | (L) |
| **스크립트 추가·수정·삭제** | ✗ | **(L) 소유자만** | **(L) 소유자만** |
| **소유권 이전** | ✗ | ✗ | **(L)** |
| **사용자 관리** (로그인 이메일 등록, 역할 지정, Admin 지정, 비활성화) | ✗ | ✗ | **(L)** |
| 전역 설정 (ping·점검 주기, 부팅 시작 유형, OTP 공급자) | ✗ | ✗ | **(L)** |
| **로그 보존 기간 설정** | ✗ | ✗ | **(L)** |
| 사전 고지 메시지 편집 | ✗ | ✗ | **(L)** |
| 관리자 감사 로그 조회 | ✗ | ✓ | ✓ |

- **스크립트 권한은 Admin도 예외가 아닙니다.** 다른 사람의 MCP 스크립트를 고쳐야 하면, Admin이 localhost에서 소유권을 이전한 다음 수정합니다.
- 소유자 계정이 비활성화되면 그 MCP는 "소유자 없음"으로 표시됩니다. 스크립트는 계속 동작하지만, 소유권을 이전하기 전에는 수정할 수 없습니다.
- 스크립트를 **실행**하는 것(자동 조치, 수동 시작·재실행·종료)에는 소유자 제한이 없습니다. 제한은 스크립트 **내용을 바꾸는 행위**에만 적용됩니다.

### 4.4 채널 분리 구현 원칙
- **서버 2개:** 8700은 `127.0.0.1`에만 바인딩합니다. 스크립트, 전역 설정, 사용자 관리, 소유권 이전, 고지 편집 라우트는 **8700 라우터에만 등록**합니다.
- 같은 PC에서 8701로 들어온 요청도 **외부 채널로 취급**합니다. 채널은 들어온 포트로만 판별합니다.
- 8700 앞에 같은 PC의 리버스 프록시를 두지 않습니다. 이 제약은 운영 문서에 명시합니다.
- **권한 검사 단일화:** 모든 판단은 정책 함수 하나 `can(user, action, resource, channel)`에서 합니다. 매트릭스(§4.3) 전체를 자동 테스트로 만듭니다.
- **UI 표시:** 권한이 없는 기능도 숨기지 않고, 비활성 상태로 두면서 이유를 함께 보여줍니다.

---

## 5. 컴포넌트 상세

### 5.1 Core Service (`mcp-monitor.exe`)
- Windows 서비스(LocalSystem)로 동작하며, 실패하면 자동으로 재시작되도록 복구 옵션을 설정합니다.
- 하나의 asyncio 루프에서 웹 서버 2개, 모니터 엔진, 수집기를 함께 돌립니다. 블로킹이 생기는 Windows API 호출은 전용 스레드로 분리합니다.
- 설정은 `data/config.db`(SQLite, WAL)에 저장합니다.

### 5.2 Web 계층
| 채널 | 바인딩 | 제공 |
|---|---|---|
| Local | `127.0.0.1:8700` | 로그인 + 전체 기능 (역할·소유자 검사) |
| External | `0.0.0.0:8701` | 익명 상태 보드, 로그인, 운영 기능 (MCP 설정 변경·수동 조치·로그 조회) |

- 실시간 갱신은 SSE 하나로 변경분만 보냅니다.
- 정적 파일은 미리 압축해 두고, 해시 파일명과 장기 캐시를 씁니다.

### 5.3 RDP 세션 수집기
| 소스 | 얻는 정보 |
|---|---|
| WTS API (세션 변경 알림 + 2초 폴링 보정) | 세션 ID, 상태, 사용자명, **로그온 도메인**, **클라이언트 컴퓨터명**, **클라이언트 IP**, 클라이언트 빌드, 해상도·색 깊이, 프로토콜, 로그온/연결/해제 시각, 유휴 시간 |
| RemoteConnectionManager 1149 | 인증 성공 (사용자, 도메인, 출발지 IP) |
| LocalSessionManager 21/22/23/24/25 | 로그온, 셸 시작, 로그오프, 연결 해제, 재연결 |
| Security 4624(Type 10/7)/4625/4634/4647/4778/4779 | 로그온 성공·실패, 로그오프, 재연결·해제 |
| 파생 정보 | IP 역방향 DNS(PTR), 처음 보는 IP·기기 여부, (선택) GeoIP |

수집할 수 없는 정보: 클라이언트 MAC 주소, NAT·VPN 뒤의 실제 IP.

### 5.4 행동 로그 — 프로세스·명령 (서비스 측)
| 대상 | 방법 |
|---|---|
| 프로그램 실행·종료 | WMI `Win32_ProcessStartTrace`/`StopTrace`. 이벤트를 받는 즉시 명령줄·경로·사용자를 조회합니다. |
| 짧게 끝나는 프로세스의 명령줄 | Security **4688** + "명령줄 포함" 정책 (설치 시 활성화) |
| cmd 사용 | `cmd.exe` 실행과 인자, cmd에서 실행한 외부 프로그램, `cmd /c ...`, 배치 파일 실행. **내부 명령은 수집하지 않습니다.** |
| PowerShell 입력 명령 | **Script Block Logging (4104)** |
| 잠금·해제 | 4800/4801, 세션 알림 |

### 5.5 행동 감사 사전 고지 다이얼로그
- **표시 시점:** RDP **연결될 때마다** 표시합니다. 새 로그온과 재연결 모두 해당합니다. 에이전트가 세션 연결 이벤트를 받는 즉시 띄웁니다.
- **형태:** 화면 중앙의 최상위 모달 창이며, '확인' 버튼 하나만 있는 안내형입니다. WebView2로 렌더링해서 웹앱과 같은 디자인 토큰과 애니메이션을 씁니다.
- **기록:**
  - `notice_shown`: 표시 시각, 연결 종류(로그온/재연결), 문구 버전
  - `notice_acknowledged`: 확인 시각, 확인까지 걸린 시간
  - 확인하기 전에 에이전트가 종료되면 `notice_unacknowledged`를 기록하고, 에이전트가 다시 뜰 때 다이얼로그를 다시 표시합니다.
- **편집 UI (localhost Admin):** 제목, 본문(간단한 서식), 버튼 문구를 편집합니다. 실제 다이얼로그와 똑같이 보이는 실시간 미리보기를 제공합니다. 저장할 때마다 버전과 변경 이력이 남고, 이전 버전으로 되돌릴 수 있습니다.
- (선택) 같은 문구를 Windows 로그인 전 법적 고지(`legalnoticecaption`/`legalnoticetext`)에도 반영할 수 있습니다.

### 5.6 로그 저장소
- **원본:** `logs/YYYY-MM-DD.jsonl` (UTF-8, KST +09:00, 자정에 새 파일로 전환)
- **조회용:** `data/index.db` (SQLite WAL + FTS5). JSONL에서 언제든 다시 만들 수 있습니다.
- **카테고리:** `session`, `notice`, `activity.process`, `activity.command`(프로세스 명령줄·PowerShell), `activity.window`, `activity.idle`, `tamper`, `mcp.health`, `mcp.action`, `auth`, `admin.audit`, `system`
- **보존 정책 (localhost Admin이 UI에서 설정):**
  - 보존 기간: 기본 **180일**, 7–3650일 범위에서 설정
  - 압축 시작 시점: 기본 30일
  - 매일 새벽 정리 작업이 보존 기간을 넘긴 일일 파일과 인덱스 행을 삭제합니다.
  - 보존 기간 변경과 삭제 내역(삭제된 날짜 범위, 건수)은 `admin.audit`·`system`에 기록합니다.
  - 보존 기간을 줄일 때는 삭제될 기간과 용량을 미리 보여주고 확인을 받습니다.
- **무결성:** `logs/`·`data/` ACL, (선택) 해시 체인

```json
{"ts":"2026-11-04T14:03:22.418+09:00","cat":"activity.command","shell":"powershell","session_id":2,
 "user":"CORP\\hong","client_ip":"10.0.3.21","client_name":"HONG-LAPTOP",
 "text":"Get-Process | Stop-Process -Name notepad","pid":8812,"source":"eventlog:4104"}
```

### 5.7 MCP 모니터 엔진
- **프로브:** `mcp_ping`(기본), `tcp`, `icmp`, 포트 → PID 검사, `expected_process_name` 검증
- **이슈 분류와 기본 조치:**
  - `PROCESS_DOWN` → start
  - `UNRESPONSIVE` → restart (restart 스크립트가 없으면 stop → start)
  - `NETWORK_DOWN` → 알림만
  - `WRONG_PROCESS` → 알림만
- **상태 머신:**
  1. `HEALTHY`: 10초 점검에서 이슈가 감지되면 `SUSPECT`로 갑니다.
  2. `SUSPECT`: 1초마다 다시 측정하며 연속 실패 시간을 누적합니다. 누적이 `action_delay_sec` 이상이 되면 `ACTION`으로 갑니다.
  3. `ACTION`: 조치 스크립트를 실행하고, `startup_grace_sec` 동안 기다린 뒤 `RECOVERING`으로 갑니다.
  4. `RECOVERING`: 정상이면 `HEALTHY`로 돌아갑니다. 재시도 한도를 넘기면 stop을 실행하고 `FAILED`가 됩니다.
  5. `MAINTENANCE`: 수동으로 종료했거나 점검 모드로 바꾼 상태입니다.
- **전역 설정:** `ping_interval_sec`(5), `issue_check_interval_sec`(10), `confirm_interval_sec`(1)
- **MCP별 설정:** `action_delay_sec`(30), `startup_grace_sec`(30), `max_auto_actions`/`window_sec`(3회/600초), `auto_recovery`, `autostart_on_boot`
- **수동 조치(MCP 개발자 이상, 모든 MCP):** 수동으로 종료하면 `MAINTENANCE`로 전환합니다. 자동 복구가 다시 켜는 일을 막기 위해서입니다.

### 5.8 스크립트 실행기와 스크립트 관리
- **종류:** `start`(필수), `stop`(필수), `restart`(선택). 형식은 `.ps1`, `.bat`, `.cmd`입니다.
- **저장:** `scripts/<mcp-id>/`에 둡니다. SYSTEM과 Administrators만 쓸 수 있도록 ACL을 겁니다.
- **편집:** localhost 채널에서 MCP 소유자만 할 수 있고, CodeMirror 편집기를 씁니다. 저장할 때마다 버전 이력(작성자, 시각, diff)이 남고 되돌릴 수 있습니다.
- **무결성 검사:** 실행 직전에 파일 해시를 DB와 비교합니다. 앱 밖에서 바뀐 파일이면 실행을 막고 `tamper` 이벤트를 남깁니다.
- **실행:**
  - 환경변수: `MCP_ID`, `MCP_NAME`, `MCP_HOST`, `MCP_PORT`, `MCP_PID`, `MCP_REASON`, `MCP_TRIGGER`, `MCP_ACTOR`
  - stdout/stderr를 캡처합니다. MCP마다 잠금을 걸어 동시에 두 번 실행되지 않게 합니다.
- **예외 격리 — 스크립트 문제가 메인 프로세스에 영향을 주지 않도록 (R20):**
  - **별도 프로세스로만 실행:** 스크립트는 항상 자식 프로세스(asyncio subprocess)로 돌립니다. 서비스 프로세스 안에서 코드를 직접 실행하지 않습니다. 실행을 기다리는 동안에도 이벤트 루프를 막지 않으므로, 다른 MCP 감시와 웹 응답은 계속 동작합니다.
  - **2분 타임아웃:** 실행 시간이 **120초**를 넘으면 `timeout`으로 처리합니다. 스크립트 프로세스와 그 하위 프로세스 트리를 강제 종료합니다. MCP별로 더 짧게(10–120초) 설정할 수는 있지만, 120초보다 길게는 설정할 수 없습니다.
  - **결과 분류:** 실행기는 예외를 위로 던지지 않고, 항상 결과 객체를 돌려줍니다.
    - `ok`: 종료 코드 0
    - `failed`: 0이 아닌 종료 코드
    - `timeout`: 120초 초과
    - `error`: 실행 자체가 실패(파일 없음, 해시 불일치, 실행 권한 오류, 실행기 내부 예외)
  - **상태 머신 연동:** `ok`가 아닌 결과는 자동 조치의 "실패 1회"로 집계합니다. 백오프와 재시도 한도(§5.7)를 그대로 적용하고, 한도를 넘으면 `FAILED`로 전환한 뒤 알림을 보냅니다. 수동 조치였다면 결과를 화면에 토스트로 알리고 이력에 남깁니다.
  - **출력 제한:** stdout/stderr는 각 1MB까지만 저장하고 나머지는 잘라냅니다. 스크립트가 출력을 쏟아내도 메모리가 넘치지 않게 하기 위해서입니다.
  - **동시 실행 제한:** 전체 동시 실행 수를 세마포어로 제한합니다(기본 4개). 스크립트가 많이 멈춰 있어도 시스템 자원이 고갈되지 않습니다.
  - **하위 프로세스 처리:** 정상 종료한 start 스크립트가 띄운 MCP 프로세스는 건드리지 않습니다. 강제 종료는 `timeout`일 때만 하고, 그때 멈춘 스크립트가 띄우던 하위 프로세스도 함께 정리합니다.
  - **기록:** 결과, 종료 코드, 소요 시간, 출력 일부, 정리한 프로세스 수를 `mcp.action` 로그에 남깁니다.

### 5.9 부팅 시 자동 실행
- 서비스 시작 유형의 기본값은 **자동(지연된 시작)**입니다. 로그인하지 않아도 부팅 후 감시가 시작됩니다.
- localhost Admin 설정에서 `자동` / `자동(지연)` / `수동` 중에서 바꿀 수 있습니다.
- MCP별 `autostart_on_boot` 옵션을 켜면, 부팅 후 그 MCP가 꺼져 있을 때 start 스크립트를 실행합니다.
- 세션 에이전트는 서비스가 RDP 세션 생성을 감지해서 그 세션에 직접 띄웁니다.

### 5.10 Dummy MCP 3종
| 이름 | 포트 | 도구 |
|---|---|---|
| `seoul-weather` | 9101 | `get_current_weather(district)`, `get_forecast(days)` (더미 데이터. 옵션으로 Open-Meteo 실데이터) |
| `calculator` | 9102 | `add`, `subtract`, `multiply`, `divide`, `evaluate(expression)` (AST 기반 안전 파서) |
| `seoul-clock` | 9103 | `now_kst()`, `convert_timezone(time, tz)` |

- **chaos 엔드포인트:** `--chaos` 옵션을 켰을 때만 동작합니다. `/chaos/crash`, `/chaos/hang?sec=N`, `/chaos/slow?ms=N`
- **예시 스크립트:** 각 MCP에 `start.ps1` / `stop.ps1` / `restart.ps1` 예시와 PID 파일 관리를 넣습니다.

---

## 6. 화면 구성

### 6.1 공통
- **채널 배지:** 상단 바에 `로컬 관리 모드` 또는 `원격 모드`를 표시합니다.
- **계정 영역:** 로그인 버튼, 또는 로그인한 계정·역할(MCP 개발자 / Admin)과 로그아웃을 표시합니다.

### 6.2 상태 보드 (익명 포함, 첫 화면)
- **접속 상태 배너:** `● 접속 중` (펄스 애니메이션) / `○ 접속자 없음`
- **접속자 카드:** 사용자, 로그온 도메인, 클라이언트 PC명, **IP(전체 표시)**, 역방향 DNS, 접속 시각, 경과 시간, 상태, 유휴 시간, 해상도, 이번 연결의 고지 확인 여부
- **MCP 상태 카드:** 상태 배지, 지연 스파크라인, 24시간 가동률, 마지막 점검 시각. `SUSPECT` 상태에서는 조치까지 남은 시간을 카운트다운 게이지로 보여줍니다.

### 6.3 로그인
- **1단계:** 이메일을 입력합니다.
- **2단계:** 6칸 OTP를 입력합니다. 자동 포커스 이동과 붙여넣기를 지원하고, 재발송까지 남은 시간을 원형 타이머로 표시합니다. 틀리면 입력칸이 흔들리는 애니메이션이 나옵니다.
- **Dummy 모드:** "개발용 OTP: 서비스 콘솔을 확인하세요" 안내를 표시합니다.

### 6.4 관리 화면 (로그인 후)
1. **대시보드:** MCP 요약, 현재 세션, 최근 이슈와 조치, 로그인 실패 추이, 우회 탐지 이벤트
2. **MCP 관리:**
   - 목록: 상태, 호스트:포트, 지연, 가동률, 소유자, 시작·재실행·종료 버튼
   - 상세: 설정 / 스크립트(localhost 소유자만 편집, 그 외에는 읽기 전용) / 이력 / 지연 차트
   - 소유권 이전 대화상자 (localhost Admin)
3. **세션:** 현재 세션, 과거 접속 이력, 로그인 실패, 고지 확인 이력
4. **로그 조회:**
   - **시간대 필터:** 빠른 선택(최근 1시간 / 오늘 / 어제 / 최근 7일)과 날짜·시각 범위 직접 입력
   - **시간대 히스토그램:** 막대 그래프 위를 드래그하면 그 구간으로 바로 필터됩니다.
   - **사용자 필터:** 여러 명을 선택할 수 있고, 사용자별 이벤트 수를 함께 보여줍니다.
   - **추가 필터:** 카테고리, 세션, 클라이언트 IP, 키워드
   - **보기 방식:** 표(가상 스크롤) 또는 사용자별 타임라인
   - 필터 상태가 URL에 유지되므로 링크로 공유할 수 있습니다. CSV·JSONL로 내보낼 수 있습니다.
5. **사용자 관리 (localhost Admin):**
   - 목록: 이메일, 이름, 역할, 활성 여부, 마지막 로그인, 소유한 MCP 수
   - 동작: 로그인 가능 이메일 추가, 역할 지정(MCP 개발자 ↔ Admin), 비활성화
   - 마지막 Admin 보호 규칙을 안내합니다.
6. **사전 고지 메시지 (localhost Admin):** 편집기, 실시간 미리보기, 버전 이력
7. **설정 (localhost Admin):**
   - 전역 ping·점검 주기
   - **로그 보존:** 보존 기간과 압축 시작 일수를 입력합니다. 현재 로그 용량, 가장 오래된 로그 날짜, 변경 시 삭제될 기간·용량 미리보기를 보여줍니다.
   - 부팅 시작 유형
   - OTP 공급자(현재 Dummy)
   - 알림 채널
8. **감사 로그:** 누가, 언제, 어느 채널에서, 무엇을 했는지

### 6.5 디자인 시스템
- **콘셉트:** 다크 우선(라이트 지원) "운영 관제 콘솔"입니다. 상태 보드는 멀리서도 읽히게, 관리 화면은 정보 밀도를 높게 만듭니다.
- **최신 CSS:** OKLCH + `color-mix()`, `light-dark()`, Cascade Layers, Nesting, Container Queries, `:has()`, Subgrid, View Transitions, Scroll-driven Animations, `@starting-style`, `@property`, Popover·Anchor Positioning(지원 브라우저에서 점진 적용), `text-wrap: balance`, `prefers-reduced-motion`
- **라이브러리:** React 19 + TypeScript + Vite, Tailwind CSS v4, shadcn/ui (Radix), Motion, Lucide, Recharts, TanStack Table·Virtual·Query·Router, react-hook-form + zod, CodeMirror 6, Sonner, cmdk, date-fns
- **글꼴:** Pretendard Variable + JetBrains Mono. 번들에 포함하고 CDN은 쓰지 않습니다.
- **애니메이션:**
  - 상태: 접속 중 펄스, 상태 배지 크로스페이드, SUSPECT 카운트다운 게이지, 복구 중 회전 테두리
  - 데이터: 지연 수치 롤링, 카드 재정렬 애니메이션
  - 전환: View Transitions, 다이얼로그·토스트 진입과 퇴장, OTP 입력 피드백, 고지 다이얼로그 진입
  - 로그 테이블에는 애니메이션을 넣지 않습니다.
- **번들 분리:** `board`(익명 상태 보드), `admin`(관리), `notice`(고지 다이얼로그) 세 엔트리로 나눕니다.

---

## 7. 성능 설계

| 영역 | 설계 | 목표 |
|---|---|---|
| 프로브 | asyncio 동시 실행, MCP별 타임아웃, 연결 재사용 | MCP 50개를 1초 주기로 측정 |
| 이벤트 수집 | 전용 스레드 → 큐 → asyncio | 이벤트 유실 0, 유휴 시 서비스 CPU < 2% |
| 로그 기록 | 큐 기반 배치 기록(200ms 또는 500건마다), SQLite WAL, 일괄 삽입 | 초당 2,000건 |
| 로그 조회 | 인덱스 `(ts)`, `(user, ts)`, `(cat, ts)`, FTS5, 커서 페이지네이션, 히스토그램 집계 쿼리 | 100만 건 기준 필터 < 300ms |
| 보존 정리 | 일 단위 파일 삭제 + 인덱스는 날짜 범위 일괄 삭제(새벽 시간대 배치) | 서비스 응답에 영향 없음 |
| 실시간 | SSE 변경분만 전송, 1초 단위로 묶음 | 화면 갱신 최대 1회/초 |
| 창 이벤트 | 에이전트에서 디바운스·병합 | 에이전트 CPU < 1% |
| 프런트 | 엔트리·라우트 단위 코드 분할, 가상 스크롤, `transform`/`opacity` 애니메이션만 사용 | 상태 보드 JS < 200KB(gzip), LAN에서 LCP < 1.5초, 스크롤 60fps |
| 정적 자원 | 사전 압축, 해시 파일명, `immutable` 캐시 | 재방문 시 다운로드 0 |

---

## 8. API 개요

| 엔드포인트 (예) | 익명 | MCP 개발자 | Admin | 채널 |
|---|:-:|:-:|:-:|---|
| `GET /api/board`, `GET /api/stream` | ✓ | ✓ | ✓ | 둘 다 |
| `POST /api/auth/otp/request`, `POST /api/auth/otp/verify`, `POST /api/auth/logout` | ✓ | ✓ | ✓ | 둘 다 |
| `GET /api/mcps/{id}/history`, `GET /api/sessions/history` | ✗ | ✓ | ✓ | 둘 다 |
| `GET /api/logs?from&to&users&cat&q&cursor`, `GET /api/logs/histogram`, `GET /api/logs/export` | ✗ | ✓ | ✓ | 둘 다 |
| `PUT /api/mcps/{id}`, `POST /api/mcps/{id}/actions/{start\|restart\|stop}` | ✗ | ✓ | ✓ | 둘 다 |
| `POST /api/mcps`, `DELETE /api/mcps/{id}`, `GET/PUT/DELETE /api/mcps/{id}/scripts/{kind}` | ✗ | 소유자 | 소유자 | **Local만** |
| `POST /api/mcps/{id}/owner` | ✗ | ✗ | ✓ | **Local만** |
| `GET/POST/PUT /api/users` | ✗ | ✗ | ✓ | **Local만** |
| `GET/PUT /api/settings` (보존 기간 포함), `GET /api/settings/retention/preview`, `GET/PUT /api/notice` | ✗ | ✗ | ✓ | **Local만** |

`DELETE /api/mcps/{id}`는 MCP 개발자는 소유자일 때만, Admin은 모든 MCP에 대해 허용합니다. 스크립트 라우트는 역할과 관계없이 소유자만 허용합니다.

---

## 9. 기술 스택과 버전 정책

### 9.1 런타임 버전 (2026-11-04 기준 조사)
| 런타임 | 선택 | 근거 |
|---|---|---|
| **Node.js** | **26 LTS 최신 패치 (26.13.0 이상)** | 2026-10-28에 LTS로 전환됐고 2029-04까지 지원됩니다. 2026-10-21 보안 릴리스(CVE 10건)가 반영돼 있습니다. |
| **Python** | **3.15 최신 패치(3.15.2 이상)를 우선 사용. 의존성 휠이 없으면 3.14 최신 패치(3.14.10 이상)** | 3.15는 2026-10-09에 출시됐습니다. pywin32, PyInstaller, pydantic-core, psutil이 3.15 Windows 휠을 제공하는지 **P0 첫 단계에서 확인**합니다. 3.14는 2030-10까지 지원됩니다. |

- **버전 고정:** `uv` + `uv.lock`, `pnpm` + `pnpm-lock.yaml`, `.python-version`, `.nvmrc`
- **보안 점검:** 빌드할 때마다 `pip-audit`과 `pnpm audit`을 실행하고, 취약점이 있으면 빌드를 실패시킵니다.

### 9.2 스택
| 영역 | 선택 |
|---|---|
| 웹 서버 | FastAPI + Uvicorn (서버 2개), SSE |
| Windows 연동 | pywin32, WMI(comtypes), ctypes(SetWinEventHook), WebView2(`pywebview`) |
| 모니터링 | psutil, httpx, icmplib |
| 인증 | 자체 OTP 구현 (`secrets` 모듈, 상수 시간 비교), SQLite 세션 저장소 |
| 저장 | SQLite(WAL, FTS5), JSONL |
| 프런트 | §6.5 |
| Dummy MCP | 공식 `mcp` Python SDK (FastMCP) |
| 패키징 | PyInstaller → `mcp-monitor.exe`, `mcp-agent.exe` / `install.ps1` |

---

## 10. 디렉터리 구조

```
strategy-mcp-monitor/
├─ docs/
├─ server/app/
│  ├─ main.py                  # 서비스 진입점, 채널 2개 기동
│  ├─ web/local_api.py         # Local 전용 라우트
│  ├─ web/shared_api.py        # 두 채널 공통 라우트
│  ├─ auth/{otp,policy,sessions}.py
│  ├─ users/
│  ├─ monitor/{engine,probes,scripts}.py
│  ├─ sessions/collector.py
│  ├─ activity/{process,powershell,agent_hub,tamper}.py
│  ├─ notice/
│  ├─ logstore/{writer,query,retention}.py
│  └─ settings/
├─ server/tests/
├─ agent/                      # 세션 에이전트 (창 이벤트, 고지 다이얼로그)
├─ web/src/{board,admin,notice}/
├─ web/src/components/{ui,status}/
├─ web/src/styles/tokens.css
├─ dummy-mcps/{seoul_weather,calculator,seoul_clock,common}/
├─ install/{install.ps1,uninstall.ps1,audit-policy.ps1}
├─ scripts/                    # 런타임: MCP별 스크립트
├─ logs/                       # 런타임: YYYY-MM-DD.jsonl
└─ data/                       # 런타임: config.db, index.db, dev/
```

---

## 11. 개발 단계

| Phase | 내용 | 완료 기준 |
|---|---|---|
| **P0 기반** | 런타임 버전 확정, 프로젝트 골격, 설정 저장소, 로그 Writer, 채널 2개 서버, 디자인 시스템 기반 | 8701에서 Local 전용 라우트 404, 자정 로그 전환, 다크·라이트·reduced-motion 확인, 보안 점검 통과 |
| **P1 인증·권한** | 최초 Admin 생성, 이메일 + Dummy OTP, 사용자 관리(이메일 등록, Admin 지정, 마지막 Admin 보호), `can()` 정책, 감사 로그 | 권한 매트릭스(§4.3) 전체 자동 테스트 통과 |
| **P2 Dummy MCP + 모니터 엔진** | Dummy 3종 + chaos, 프로브, 상태 머신, 스크립트 실행기 | crash → 자동 start, hang → restart, 한도 초과 → FAILED |
| **P3 상태 보드 + MCP 관리 UI** | 익명 상태 보드, MCP 등록·설정, 수동 조치, 스크립트 편집(소유자 + Local), 버전 이력, 소유권 이전, 부팅 옵션 | 외부 채널·비소유자의 스크립트 편집 불가 시연 |
| **P4 세션 수집** | WTS·이벤트 로그 수집, 세션 이력, 상태 보드 실시간 표시 | Win 11 Pro에 RDP 접속 후 2초 안에 "접속 중"과 정보 카드 표시 |
| **P5 행동 로그 + 고지** | 프로세스 명령줄·PowerShell 수집, 에이전트(창 이벤트), **연결마다 고지 다이얼로그**와 편집 UI, 우회 탐지 | 재연결 때도 고지가 표시되고 확인이 기록됨, 에이전트를 종료하면 재기동되고 그 사실이 기록됨 |
| **P6 로그 조회 + 보존** | 시간대·사용자 필터, 히스토그램 드래그 필터, 사용자 타임라인, FTS, 내보내기, **보존 기간 설정 UI와 정리 작업** | 100만 건 기준 필터 < 300ms, 보존 기간 변경 시 미리보기 후 정리 동작 |
| **P7 배포·하드닝** | PyInstaller, `install.ps1`(서비스, 감사 정책, ACL, `-OpenFirewall` 옵션), 운영 문서 | 깨끗한 Win 11 Pro에서 설치 스크립트 한 번으로 전체 동작 |

---

## 12. 개발 방식 — 디자인·컴포넌트 스킬 활용

| 시점 | 스킬 | 용도 |
|---|---|---|
| 화면 설계를 시작할 때 | frontend-design | 미적 방향, 타이포그래피, 레이아웃 |
| 디자인 기반을 만들 때 | design:design-system | 토큰과 컴포넌트 문서화, 하드코딩 값 점검 |
| 문구를 쓸 때 | design:ux-copy | 한국어 마이크로카피, 권한 제한 안내, 고지 기본 문구 |
| 화면을 완성한 뒤 | design:design-critique | 스크린샷 기반 리뷰 |
| 각 Phase를 마칠 때 | design:accessibility-review | WCAG 2.1 AA 점검 |
| 개발 전반 (설치한 경우) | audit-suite: web-animation-design, web-design-guidelines, vercel-react-best-practices, make-interfaces-feel-better | 애니메이션, 디자인 가이드, React 성능, 마감 품질 |
| 검증 | Playwright 플러그인 | E2E, 스크린샷 비교, 권한별 시나리오 |
| 공통 | superpowers: TDD, 코드 리뷰, 완료 전 검증 | 테스트 우선, 단계별 리뷰 |

---

## 13. 테스트 전략
- **단위:** 상태 머신(가짜 시계), 이슈 분류, `can()` 정책(매트릭스 전체), OTP, 마지막 Admin 보호, 로그 전환, 보존 정리, 스크립트 해시 검사
- **통합:** Dummy MCP + chaos 장애 시나리오, 스크립트 버전 이력, 소유권 이전, Admin 지정
- **스크립트 예외 격리:** 0이 아닌 종료 코드, 120초를 넘겨 멈추는 스크립트, 존재하지 않는 파일, 출력 폭주(수십 MB), 하위 프로세스를 띄우고 멈추는 스크립트. 이 경우에도 다른 MCP의 ping 측정과 웹 응답 시간이 정상 범위를 유지해야 합니다.
- **보안:** 8701에서 Local 전용 API 호출 시 404, 비소유자 스크립트 수정 거부, CSRF, OTP 무차별 대입 제한, 에이전트 사칭 차단
- **Win 11 Pro 실기기·VM:** RDP 접속·해제·**재연결 시 고지 재표시**, 로그인 실패, 프로세스·PowerShell 수집, 에이전트 종료 탐지
- **성능:** 로그 100만 건 조회, 초당 2,000건 기록, 보존 정리 중 응답 시간
- **UI:** Playwright E2E와 스크린샷 비교, axe 접근성 검사, reduced-motion

---

## 14. 추가 제안

| 구분 | 제안 |
|---|---|
| 권장 | 외부 채널 HTTPS 옵션 |
| 권장 | 알림: MCP FAILED, 자동 복구, 로그인 실패 다발, 처음 보는 IP, 우회 탐지 (Windows 토스트 / 이메일 / Slack·Teams 웹훅) |
| 권장 | RDP 계정을 Windows 표준 사용자로 운영 |
| 권장 | 설정 백업: MCP 설정과 스크립트 내보내기·가져오기 (가져오기는 localhost Admin) |
| 권장 | 자가 감시(heartbeat), NTP 동기화 상태 표시 |
| 선택 | 외부 syslog/SIEM 전송, GeoIP |
| 제외 | cmd 내부 명령 수집, 키 입력, 클립보드, 화면 녹화 |

---

## 15. 리스크

| 리스크 | 대응 |
|---|---|
| 개발 PC가 Home이라 RDP 테스트 불가 | Mock 공급자 + Win 11 Pro 테스트 환경 |
| Python 3.15 의존성 휠 미지원 | P0에서 확인 후 3.14로 결정 |
| RDP 사용자의 Windows 관리자 권한 | 우회 탐지 + 표준 사용자 운영 권장 |
| 외부 채널 HTTP 평문 | HTTPS 옵션 |
| 창 제목·명령줄의 민감 정보 | 보존 기간 설정, 로그인 사용자만 조회, 조회 행위도 감사 기록 |
| 재연결마다 고지가 떠서 번거로움 | 다이얼로그를 가볍고 빠르게(표시 < 300ms), '확인' 한 번으로 닫히게 |

---

## 16. 결정 사항 (확정)

| 항목 | 결정 |
|---|---|
| 운영 OS | Windows 11 Pro |
| 기술 스택 | Python + React (버전은 §9.1) |
| 채널 | Local `127.0.0.1:8700` / External `0.0.0.0:8701` |
| 역할 | 익명 / **MCP 개발자** / **Admin** (User 역할 없음) |
| 로그인 | 이메일 + OTP, 두 채널 모두 필수, 현재 Dummy. MCP 개발자와 Admin만 로그인 |
| 로그인 가능 이메일 | Admin이 등록 (도메인 제한 없음) |
| 사용자 관리·Admin 지정 | localhost Admin |
| 익명 조회 | MCP 상태 + RDP 접속자 정보 (IP 전체 표시) |
| MCP 설정 변경·수동 조치 | MCP 개발자 이상, 모든 MCP, 두 채널 모두 |
| 스크립트 추가·수정·삭제 | localhost + 해당 MCP 소유자만 |
| 소유권 이전 | localhost Admin |
| 전역 설정·고지 메시지·부팅 옵션·보존 기간 | localhost Admin |
| 사전 고지 | 연결될 때마다 표시, '확인' 버튼만, 확인 기록 |
| cmd 내부 명령 | 수집하지 않음 (Clink 제외) |
| 로그 보존 | 기본 180일, UI에서 설정 |
| 방화벽 | 사용자가 필요할 때 직접 설정 |
| Dummy MCP | 날씨 / 계산기 / 시계 3종 |
