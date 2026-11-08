<img src="docs/assets/brand/icon.svg" width="96" alt="MCP Monitor 아이콘. 짙은 청록 유리 타일 위의 흰 에이전트 로봇 얼굴로, AI를 뜻하는 금색 반짝이 안테나와 MCP 커넥터 핀 귀가 있고, 화면에는 위로 솟는 초록 실시간 심박이 흐릅니다.">

# 🛰️ MCP Monitor

![Python 3.15](https://img.shields.io/badge/Python-3.15.2-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.162-009688?logo=fastapi&logoColor=white)
![Node 26](https://img.shields.io/badge/Node.js-26%20LTS-5FA04E?logo=nodedotjs&logoColor=white)
![React 19](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-6.0-3178C6?logo=typescript&logoColor=white)
![Vite](https://img.shields.io/badge/Vite-8-646CFF?logo=vite&logoColor=white)
![Tailwind CSS v4](https://img.shields.io/badge/Tailwind_CSS-v4-06B6D4?logo=tailwindcss&logoColor=white)
![SQLite FTS5](https://img.shields.io/badge/SQLite-FTS5-003B57?logo=sqlite&logoColor=white)
![Windows 11](https://img.shields.io/badge/Windows-11_Pro-0078D4?logo=windows11&logoColor=white)
![Rust 1.99](https://img.shields.io/badge/Rust-1.99.1-000000?logo=rust&logoColor=white)
![Tauri 2](https://img.shields.io/badge/Tauri-2.12-24C8D8?logo=tauri&logoColor=white)
![WebView2](https://img.shields.io/badge/WebView2-Evergreen-0078D4?logo=microsoftedge&logoColor=white)
![Playwright](https://img.shields.io/badge/E2E-Playwright-2EAD33?logo=playwright&logoColor=white)

**Windows 11 Pro PC 한 대를 지키는 관제탑입니다.** 그 PC에서 도는 MCP 서버가 쓰러지면 일으켜 세우고, RDP로 들어온 사람이 무엇을 했는지 날짜별 로그로 남깁니다.

- **누구를 위한 것인가:** MCP 서버를 여러 개 띄워 둔 공용 Windows PC를 운영하는 팀. 원격 데스크톱으로 그 PC에 들어가는 MCP 개발자와 관리자.
- **왜 필요한가:** "MCP가 죽었는데 아무도 몰랐다", "새벽 3시에 누가 접속해서 뭘 했지?" 이 두 질문에 웹 화면 하나로 답합니다.
- **무엇을 하나:** MCP 상태 감시·자동 복구 · RDP 세션 수집 · 행동 감사(프로세스·명령·창) · 연결마다 사전 고지 · 로그 조회·보존 · Windows 서비스로 부팅 시 자동 실행.
- **어떻게 받나:** `mcp-monitor-1.1.0.exe` **파일 하나.** 더블클릭하면 설치되고, 그 뒤로는 시작 메뉴의 앱 창과 트레이 아이콘으로 씁니다. 안에 서버가 통째로 들어 있습니다(마트료시카 방식 🪆).

> 현재 버전 **1.1.0**. 기준 스펙은 [`docs/PLAN.md`](docs/PLAN.md) v0.9, 운영 방법은 [`docs/ops/OPERATIONS.md`](docs/ops/OPERATIONS.md), 데스크톱 앱 설계는 [`docs/design/desktop-app-rust.md`](docs/design/desktop-app-rust.md)입니다.

## 📑 목차

- [⚡ 빠른 시작](#-빠른-시작)
- [💻 지원 플랫폼과 준비물](#-지원-플랫폼과-준비물)
- [✨ 주요 기능](#-주요-기능)
- [🔌 포트와 채널](#-포트와-채널)
- [🎨 화면 구성](#-화면-구성)
- [🧱 아키텍처](#-아키텍처)
- [🧰 사용 라이브러리](#-사용-라이브러리)
- [📁 디렉터리 구조](#-디렉터리-구조)
- [📦 설치와 운영](#-설치와-운영)
- [🔧 개발 환경](#-개발-환경)
- [🧪 테스트와 품질](#-테스트와-품질)
- [🔒 보안 참고](#-보안-참고)
- [❓ FAQ와 문제 해결](#-faq와-문제-해결)
- [🚧 현재 상태와 한계](#-현재-상태와-한계)
- [🔭 로드맵](#-로드맵)
- [🤝 기여와 커밋 규칙](#-기여와-커밋-규칙)
- [📜 라이선스](#-라이선스)
- [📚 문서](#-문서)

---

## ⚡ 빠른 시작

**TL;DR (개발용, 체크아웃에서 바로).** `uv`, Node 26 + `pnpm`이 있는 Windows에서 저장소 루트 기준으로 실행합니다.

```powershell
cd web
pnpm install
pnpm build
cd ..\server
uv sync
uv run python -m app --root "$env:TEMP\mcpmon-dev" --external-host 127.0.0.1 --dev-otp-code 123456 --session-source none
```

1. 브라우저로 `http://127.0.0.1:8700/admin/setup`을 열어 첫 Admin을 만듭니다.
2. 같은 이메일로 로그인하고, 코드에 `123456`을 넣습니다(개발 전용 고정 코드).
3. 익명 상태 보드는 `http://127.0.0.1:8701/`에 있습니다. 끝낼 때는 콘솔에서 Ctrl+C.

**TL;DR (운영 PC).** 개발 PC에서 실행 파일 하나를 만들고, 운영 PC에서 그 파일을 더블클릭합니다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File install\build-desktop.ps1   # → dist\mcp-monitor-1.1.0.exe (+ .sha256)
```

1. `dist\mcp-monitor-1.1.0.exe`를 운영 PC로 옮겨 더블클릭 → "지금 설치할까요?" **예** → UAC.
2. 설치가 끝나면 앱 창이 상태 보드를 엽니다. 보드의 **초기 설정 시작** 링크(또는 위쪽 **관리 화면** 버튼)로 `/admin/setup`에 갑니다. 서비스는 이미 돌고 있습니다.

명령줄을 좋아한다면 관리자 PowerShell에서 `& .\mcp-monitor-1.1.0.exe install --open-firewall | Write-Output`. 자세한 순서는 [📦 설치와 운영](#-설치와-운영)에 있습니다.

---

## 💻 지원 플랫폼과 준비물

| 용도 | 플랫폼 | 준비물 |
|---|---|---|
| **운영** | Windows 11 **Pro**(RDP 접속을 받는 PC) | 설치할 때 관리자 계정(UAC), 앱 창과 고지 창용 **WebView2 런타임**(Windows 11에 기본으로 있음, 없으면 고지는 기본 브라우저 탭) |
| **개발** | Windows(개발 PC는 Windows 11 Home에서 확인) | Python 3.15.2 + [`uv`](https://docs.astral.sh/uv/), Node.js 26.13.0 LTS + `pnpm` 12.16.1, `git`. 데스크톱 exe를 만들려면 Rust 1.99.1(rustup) + Visual Studio Build Tools(MSVC, Windows SDK) |
| **화면** | 데스크톱 브라우저(Chromium 123+, Firefox 128+, Safari 17.5+ 빌드 대상)와 앱 창(WebView2) | 휴대폰 화면은 지원하지 않고, 640×600 창까지 맞춥니다 |

- Windows 11 Home은 RDP 접속을 받을 수 없습니다. 개발 PC에서는 세션 수집을 가짜 공급자(`--session-source none` 또는 `json:<path>`)로 대신합니다.
- 서버(pywin32·ctypes)와 데스크톱 exe(`windows` 크레이트·WebView2)는 Windows API를 직접 부르므로 **Windows 전용**입니다.

---

## ✨ 주요 기능

- 📺 **상태 보드(익명):** 로그인 없이 MCP 상태 배지, 지연 스파크라인, 24시간 가동률, 조치까지 남은 시간, RDP 접속 여부와 접속자 정보(**IP 전체 표시**)를 봅니다. SSE로 변경분만 받습니다.
- 🩺 **MCP 감시·자동 조치:** 프로브 `mcp_ping`/`tcp`/`icmp`와 포트 점유 프로세스 검사. `HEALTHY → SUSPECT → ACTION → RECOVERING`, 한도를 넘기면 `FAILED`, 수동 종료는 `MAINTENANCE`. 프로세스가 없으면 start, 응답이 없으면 restart.
- 📜 **스크립트:** `start`·`stop`(필수)과 `restart`(선택), `.ps1`/`.bat`/`.cmd`. 항상 자식 프로세스로 돌리고 **120초 타임아웃**, 결과 `ok`/`failed`/`timeout`/`error`, 출력 각 1 MB, 동시 4개, 실행 직전 해시 검사. 편집기(CodeMirror)와 버전 이력·diff·되돌리기.
- 🔑 **인증·권한:** 이메일 + 6자리 OTP(5분, 1회용). 역할은 **익명 / MCP 개발자 / Admin**. Local·External 두 채널로 기능을 나누고, 모든 판단은 `can(user, action, channel, owner_id)` 하나에서 합니다([권한 매트릭스](docs/PLAN.md#43-권한-매트릭스)).
- 🖥️ **RDP 세션 수집:** WTS API 0.5초 폴링(+ 세션 변경 알림 때 즉시)과 이벤트 로그(1149, 21–25, 4624/4625/4634/4647/4778/4779, 4800/4801). 도메인, 클라이언트 이름·IP·빌드, 해상도, 유휴 시간까지.
- 👣 **행동 로그:** WMI 프로세스 시작·종료, 4688 명령줄, PowerShell 4104 스크립트 블록, 에이전트가 보내는 포그라운드 창·제목·유휴 상태. **cmd 내부 명령(`dir`, `cd` …)은 수집하지 않습니다**(의도된 결정).
- 📢 **사전 고지:** RDP **연결될 때마다** 화면 가운데 맨 위에 '확인' 버튼 하나뿐인 WebView2 창. 닫기 단추도, 작업 표시줄 자리도, Alt+F4도 통하지 않습니다(그래도 다른 앱의 입력까지 막지는 않습니다 — Windows가 허락하지 않아서요). 표시·확인을 기록하고, 문구는 Local Admin이 미리보기와 버전 이력으로 편집합니다.
- 🕵️ **우회 탐지:** 에이전트 종료, 감사 정책 변경, 이벤트 로그 삭제, 감사 레지스트리 변경, 스크립트·로그 파일 변경을 `tamper`로 남기고 대시보드와 실시간 알림에 띄웁니다. 막지는 못하고, 대신 **절대 모른 척하지 않습니다.**
- 🔎 **로그 조회·감사·보존:** JSONL 원본 + SQLite FTS5 색인. 히스토그램 드래그 필터, 여러 사용자 선택, 키워드, 가상 스크롤 표·사용자 타임라인, CSV·JSONL 내보내기. 조회·내보내기도 감사로 남습니다. 보존 기본 180일, 매일 03:30 KST 정리.
- 🚀 **배포·서비스:** Rust(Tauri 2)로 만든 `mcp-monitor.exe` 하나가 설치기·업그레이드·제거·앱 창·트레이·세션 에이전트를 모두 맡고, PyInstaller 서버 묶음을 해시째 품고 다닙니다. 앱 및 기능·시작 메뉴에 등록되고, 서비스 시작 유형은 웹 설정이 기준입니다.

---

## 🔌 포트와 채널

| 이름 | 기본 주소 | 누가 | 무엇을 |
|---|---|---|---|
| **Local** 채널 | `127.0.0.1:8700` | 그 PC 안의 앱 창·브라우저, 세션 에이전트 | 전체 관리 기능, 첫 Admin 만들기, 에이전트·고지 API |
| **External** 채널 | `0.0.0.0:8701` | 다른 PC의 브라우저 | 익명 상태 보드, 로그인 뒤 운영 기능(MCP 설정·수동 조치·로그 조회) |
| Dummy MCP | `127.0.0.1:9101` · `9102` · `9103` | 모니터 엔진 | `seoul-weather` · `calculator` · `seoul-clock` (개발·시험용) |

- 채널은 **들어온 포트로만** 판별합니다. 같은 PC에서 8701로 들어와도 External입니다.
- Local 전용 기능: 스크립트 조회·편집, MCP 등록·삭제, 소유권 이전, 사용자 관리, 전역 설정, 보존 기간, 고지 편집. External에서는 라우트 자체가 없어 **404**입니다.
- 두 채널은 쿠키 이름이 달라(`mcpmon_sid_local`, `mcpmon_sid_ext`) 각각 로그인합니다.
- 방화벽은 기본으로 닫혀 있습니다. 8701을 열려면 설치 때 `--open-firewall`(도메인·개인 프로필만).

---

## 🎨 화면 구성

웹은 세 번들로 나뉩니다: `board`(익명 보드), `admin`(관리 화면), `notice`(고지 창).

| 경로 | 화면 | 누가 |
|---|---|---|
| `/` | 상태 보드 | 누구나 |
| `/admin/setup` | 첫 Admin 만들기 | Local, 사용자가 없을 때만 |
| `/admin/login` | 이메일 → 6칸 OTP | 등록된 이메일 |
| `/admin` | 대시보드(MCP 요약, 현재 세션, 최근 조치, 로그인 실패, 우회 탐지) | MCP 개발자 이상 |
| `/admin/mcps`, `/admin/mcps/new`, `/admin/mcps/{id}` | MCP 목록·등록·상세(설정·스크립트·이력·지연 차트) | MCP 개발자 이상(등록·스크립트는 Local) |
| `/admin/sessions` | 현재 세션, 접속 이력, 로그인 실패, 수집기 상태 | MCP 개발자 이상 |
| `/admin/logs` | 로그 조회 | MCP 개발자 이상 |
| `/admin/audit` | 감사 로그(관리 작업·로그인) | MCP 개발자 이상 |
| `/admin/users`, `/admin/settings`, `/admin/notice` | 사용자 관리, 설정(주기·보존·시작 유형), 고지 문구 | Local Admin |
| `/notice` | 고지 창 | 세션 에이전트가 연 창만(토큰) |

그 PC에서는 시작 메뉴의 **MCP Monitor**(앱 창)가 Local 채널의 상태 보드(`/`, 8701의 보드와 같은 화면)를 엽니다. 보드 위쪽의 **관리 화면** 버튼이 `/admin`(로그인 전이면 로그인 화면)으로, 관리 화면 위쪽의 **상태 보드** 버튼이 보드로 돌아갑니다. 앱 창은 `127.0.0.1:<Local 포트>` 밖으로 나가지 않고, 다른 주소는 기본 브라우저로 넘깁니다. 창을 닫으면 트레이로 숨고, 서비스는 계속 돕니다.

권한이 없는 기능은 숨기지 않고 비활성으로 두며 이유를 함께 보여 줍니다. 화면별 명세는 [`docs/design/screens/`](docs/design/screens/)에 있습니다.

---

## 🧱 아키텍처

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/architecture-dark.svg">
  <img alt="MCP Monitor 구성도. 실행 파일 mcp-monitor.exe(Rust, Tauri 2)가 서버 묶음을 품고 app, install, uninstall, audit-policy, agent 모드로 동작합니다. 다른 PC의 브라우저는 External 채널 0.0.0.0:8701로, 이 PC의 앱 창(WebView2)과 브라우저는 Local 채널 127.0.0.1:8700으로 Windows 서비스 mcp-monitor(mcp-monitor-server.exe)의 FastAPI 라우터에 닿습니다. 모니터 엔진과 스크립트 실행기가 MCP 서버(dummy 9101–9103)를 프로브하고 조치하며, 수집기와 우회 탐지의 이벤트는 LogWriter가 logs/ JSONL로 기록하고 LogIndex가 index.db에 색인합니다. 에이전트 감독이 사용자 세션마다 mcp-monitor.exe agent를 띄우고, 에이전트는 토큰과 HMAC 증명으로 Local 채널과 통신하며 최상위 WebView2 고지 창을 엽니다." src="docs/assets/architecture-light.svg" width="1200">
</picture>

**요청과 데이터의 흐름**

1. **설치:** `mcp-monitor.exe install`(더블클릭 안내 포함)이 내장 묶음을 해시로 검사해 `Program Files\MCP Monitor`에 풀고, 데이터 루트 ACL·감사 정책·서비스·앱 및 기능·시작 메뉴를 맞춥니다. 업그레이드는 새 폴더를 옆에 풀어 두었다가 서비스를 멈추고 통째로 바꿔 끼웁니다.
2. **웹 요청:** 앱 창·브라우저 → 채널(포트로 Local/External 결정) → 세션 쿠키·CSRF → `can()` → 라우트. 설정·사용자·MCP는 `data/config.db`에 저장합니다.
3. **감시:** 엔진이 MCP를 주기적으로 프로브하고, 이슈가 `action_delay_sec` 동안 이어지면 실행기가 스크립트를 자식 프로세스로 돌립니다. 결과는 `mcp.health`·`mcp.action` 로그와 SSE로 나갑니다.
4. **수집:** WTS·이벤트 로그·WMI는 전용 스레드에서 읽어 큐로 루프에 넘기고, LogWriter가 `logs/YYYY-MM-DD.jsonl`에 묶어서 씁니다. LogIndex가 그 파일을 `data/index.db`에 색인하고, 로그 화면은 색인만 읽습니다.
5. **세션 에이전트:** RDP 연결이 열리면 감독이 그 세션에 `mcp-monitor.exe agent`를 사용자 권한으로 띄웁니다. 에이전트는 Local 채널로 서비스와 대화하며(요청마다 서비스의 HMAC 증명 확인) 창 이벤트를 보내고, `show_notice`를 받으면 WebView2 고지 창으로 `/notice`를 엽니다.

<details>
<summary>구성 요소별 코드 위치</summary>

| 구성 요소 | 위치 | 역할 |
|---|---|---|
| 서버 진입점 | `server/app/__main__.py`, `server/app/main.py` | CLI(콘솔 서버, `service`, `reindex` — 설치본에서는 `mcp-monitor-server.exe`)와 `serve()`. 두 포트를 수집기·에이전트보다 먼저 `SO_EXCLUSIVEADDRUSE`로 엶. 데이터 루트당 프로세스 하나(`data/.lock`) |
| 웹 계층 | `server/app/web/` | `local_api.py`(Local 전용), `shared_api.py`·`mcp_shared.py`(두 채널), `logs_api.py`, `agent_api.py`, `static.py`(정적 파일·CSP) |
| 인증·권한 | `server/app/auth/` | `otp.py`(`DummyOtpProvider`), `sessions.py`, `policy.py`(`can()`) |
| 모니터 엔진 | `server/app/monitor/` | 프로브, 상태 머신, 이력, 스크립트 저장소(해시)와 실행기(`runner.py`) |
| 수집기 | `server/app/collect/`, `sessions/`, `activity/`, `win/` | WTS·이벤트 로그·WMI. 소스별 큐 상한 1만 개(넘치면 `collector.dropped`) |
| 우회 탐지 | `server/app/activity/tamper.py` | 이벤트 로그 탐지기 + 60초 스캐너, 기준값 `data/tamper-baseline.json` |
| 에이전트 감독 | `server/app/activity/agent_supervisor.py`, `server/app/win/launch.py` | `WTSQueryUserToken` + `CreateProcessAsUser`, 실행마다 새 토큰·서버 키, 비정상 종료 시 재기동 + `tamper` |
| 세션 에이전트 | `desktop/src/agent/` (배포), `agent/mcp_agent/` (Python, 개발·테스트용) | `SetWinEventHook` 창 이벤트, 유휴 상태, 고지 창(WebView2 / 개발용 Edge·print), `X-Server-Proof` 검증. 두 구현이 같은 픽스처·HMAC 벡터·통합 시나리오를 통과 |
| 데스크톱 앱 | `desktop/src/app/`, `desktop/ui/` | 앱 창(탐색 제한), 트레이, 단일 인스턴스, 로그인 때 시작, 연결 중 페이지 |
| 설치기 | `desktop/src/install/` | 설치·업그레이드·제거·감사 정책 계획(`--dry-run`), ACL·경로 규칙, 폴더 교체, 앱 및 기능·시작 메뉴 |
| 내장 묶음 | `desktop/build.rs`, `desktop/src/payload*.rs` | 서버 묶음을 결정적 tar + zstd로 내장, 파일별 SHA-256 매니페스트로 검증 |
| 명령줄 | `desktop/src/cli.rs`, `desktop/src/lib.rs` | 손으로 짠 해석기, 승격 재실행(해석한 옵션만), 모드 판별 |
| 로그 저장소 | `server/app/logstore/` | `writer.py`, `indexer.py`·`index_db.py`·`fts.py`·`query.py`, `retention.py` |
| 설정 저장소 | `server/app/db.py`, `settings/`, `users/`, `notice/` | `data/config.db`(SQLite WAL, 마이그레이션) |
| 서비스 호스트 | `server/app/winsvc/` | SCM 정지·PRESHUTDOWN·세션 변경 알림, 시작 유형 동기화 |
| 웹 | `web/src/{board,admin,notice}/` | 세 엔트리와 공용 컴포넌트(`web/src/components/`), 디자인 토큰(`web/src/styles/`) |

</details>

더 깊은 설계는 [`docs/PLAN.md` §3](docs/PLAN.md#3-시스템-아키텍처)과 §5를 봅니다.

---

## 🧰 사용 라이브러리

한 줄 요약: **Python 3.15.2 + FastAPI + SQLite**(서버), **React 19 + Vite + Tailwind v4**(웹), **Rust 1.99.1 + Tauri 2 + WebView2**(데스크톱 exe·설치기·세션 에이전트), **PyInstaller**(내장 서버). 웹은 `package.json`에, Rust는 `Cargo.toml`에(`=x.y.z`) 정확한 버전을 고정하고, Python은 `uv.lock`이 버전을 고정합니다(아래 Python 버전은 lock 기준).

<details>
<summary>🐍 서버 런타임 (<code>server/pyproject.toml</code>, <code>server/uv.lock</code>)</summary>

| 패키지 | 버전 | 왜 썼나 |
|---|---|---|
| fastapi | 0.162.0 | 두 채널 라우터, 의존성 주입으로 권한 검사 |
| uvicorn | 0.54.0 | ASGI 서버 두 개(Local·External)를 한 루프에서 |
| httptools · websockets · watchfiles · python-dotenv | 0.9.0 · 17.4 · 1.3.0 · 1.2.4 | `uvicorn[standard]`과 같은 구성(cp315 휠이 없는 pyyaml만 뺌) |
| pydantic | 2.14.2 | 요청·응답 검증 |
| httpx | 0.28.1 | MCP `mcp_ping` 프로브 |
| psutil | 7.2.2 | 포트 → PID, 프로세스 트리 정리 |
| pywin32 | 312 (Windows만) | 이벤트 로그, WMI, `CreateProcessAsUser`, Windows 서비스 |
| (내장) sqlite3 | SQLite 3.53 | `config.db`(WAL), `index.db`(FTS5 `contentless_delete`) |

</details>

<details>
<summary>🧪 서버 개발·테스트 (<code>dev</code> 그룹)</summary>

| 패키지 | 버전 | 왜 썼나 |
|---|---|---|
| pytest | 9.2.0 | 테스트 러너(표지: `integration`, `winlive`, `perf`, `bundle`) |
| pytest-asyncio | 1.4.1.post1 | asyncio 테스트(`asyncio_mode = "auto"`) |
| pytest-timeout | 2.4.0 | 멈춘 실제 프로세스 테스트가 전체를 붙잡지 않게(테스트당 120초) |
| ruff | 0.17.3 | 린트(규칙 집합을 고정) |
| mypy | 2.4.1 | 타입 검사(`packages = ["app"]`) |
| types-psutil | 7.2.2.20260906 | psutil 타입 |
| pip-audit | 2.10.1 | 빌드 보안 관문 |

</details>

<details>
<summary>⚛️ 웹 런타임 (<code>web/package.json</code> <code>dependencies</code>)</summary>

| 패키지 | 버전 | 왜 썼나 |
|---|---|---|
| react · react-dom | 19.3.1 | UI |
| @tanstack/react-router | 1.170.46 | `/admin/*` 라우팅, 필터 상태를 URL에 유지 |
| @tanstack/react-query | 5.105.3 | 서버 상태 캐시, SSE 뒤 무효화 |
| @tanstack/react-table | 9.3.1 | 로그·감사·MCP 표 |
| @tanstack/react-virtual | 3.14.26 | 로그 표 가상 스크롤 |
| recharts | 3.10.1 | 지연 차트, 로그 히스토그램 |
| @codemirror/state · view · commands · language · legacy-modes, @lezer/highlight | 6.7.6 · 6.43.15 · 6.11.1 · 6.13.1 · 6.5.5, 1.2.5 | 스크립트 편집기(PowerShell 강조) |
| diff (jsdiff) | 9.0.0 | 스크립트·고지 버전 비교 |
| motion | 14.9.1 | 상태 배지 전환, 다이얼로그·토스트 애니메이션 |
| sonner | 2.0.8 | 토스트(수동 조치 결과 등) |
| cmdk | 1.1.1 | 명령 팔레트·검색 목록 |
| radix-ui | 1.8.1 | shadcn/ui 컴포넌트의 접근성 기반 |
| class-variance-authority · clsx · tailwind-merge | 0.7.1 · 2.1.1 · 3.7.0 | shadcn/ui 변형·클래스 합치기 |
| lucide-react | 1.64.0 | 아이콘 |
| date-fns | 4.4.0 | KST 시각 표시·기간 계산 |
| react-hook-form · @hookform/resolvers · zod | 7.91.0 · 7.0.2 · 4.6.7 | 폼과 스키마 검증 |
| pretendard · @fontsource-variable/jetbrains-mono | 1.3.9 · 5.3.0 | 글꼴을 번들에 포함(CDN 없음, CSP `font-src 'self'`) |

</details>

<details>
<summary>🛠 웹 개발·테스트 (<code>devDependencies</code>)</summary>

| 패키지 | 버전 | 왜 썼나 |
|---|---|---|
| typescript | 6.0.3 | 타입 |
| vite · @vitejs/plugin-react | 8.3.5 · 6.2.1 | 빌드·개발 서버(세 엔트리, `/api` 프록시) |
| tailwindcss · @tailwindcss/vite · tw-animate-css | 4.3.4 · 4.3.4 · 1.4.0 | 스타일과 애니메이션 유틸리티 |
| vitest | 5.1.0 | 단위 테스트, 번들 예산 테스트 |
| @testing-library/react · dom · user-event · jest-dom | 16.3.3 · 10.4.2 · 14.6.8 · 7.0.1 | 컴포넌트 테스트 |
| jsdom | 30.1.3 | 테스트용 DOM |
| msw | 3.0.3 | API 모킹 |
| @playwright/test | 1.64.1 | E2E, 스크린샷 비교(다크·라이트) |
| @axe-core/playwright | 4.14.0 | 접근성 자동 검사 |
| eslint · @eslint/js · typescript-eslint · eslint-plugin-react-hooks · eslint-plugin-jsx-a11y · globals | 9.39.5 · 9.39.5 · 8.72.1 · 7.1.1 · 6.10.2 · 17.14.0 | 린트(훅 규칙, 접근성 규칙) |
| culori · @types/culori | 4.0.2 · 4.0.1 | 디자인 토큰 색 대비 테스트 |
| @types/node · @types/react · @types/react-dom | 26.6.6 · 19.3.0 · 19.3.0 | 타입 정의 |

</details>

<details>
<summary>🦀 데스크톱 exe (<code>desktop/Cargo.toml</code>, <code>desktop/Cargo.lock</code>)</summary>

| 크레이트 | 버전 | 왜 썼나 |
|---|---|---|
| tauri (`tray-icon`, `image-ico`, `custom-protocol`) · tauri-build | 2.12.5 · 2.7.4 | WebView2 창, 트레이, 리소스·매니페스트. 번들러(tauri-cli)는 쓰지 않음 |
| tauri-plugin-single-instance | 2.5.5 | 앱 모드는 사용자당 하나, 두 번째 실행은 기존 창을 앞으로 |
| windows · webview2-com | 0.62.2 · 0.39.1 | SCM, ACL(`GetNamedSecurityInfoW`…), 레지스트리, WTS, 훅, `IShellLinkW`, WebView2 설정. tauri와 같은 버전 하나로 |
| ureq (기본 기능 끔) | 3.5.1 | `127.0.0.1`의 서비스와만 HTTP. TLS·tokio 없음 |
| sha2 · hmac · hex · getrandom | 0.11.1 · 0.13.0 · 0.4.3 · 0.4.3 | 내장 묶음 해시, 서버 증명(HMAC-SHA256), nonce |
| zstd · tar · walkdir | 0.13.4 · 0.4.46 · 2.5.0 | 서버 묶음을 결정적 tar + zstd 19로 내장하고 풀기 |
| serde · serde_json · time · regex | 1.0.229 · 1.0.154 · 0.3.55 · 1.13.1 | 계획 JSON, 설치 기록, KST 시각, 토큰 가리기 |
| tempfile (테스트) | 3.27.0 | `%LOCALAPPDATA%` 임시 폴더 테스트 |
| cargo-audit (도구) | 0.22.2 | 릴리스 빌드의 보안 관문(RustSec) |

clap·reqwest·chrono는 일부러 뺐습니다. 명령줄이 작고, TLS가 필요 없고, `time`으로 충분해서입니다.

</details>

<details>
<summary>🤖 Python 에이전트와 📦 패키징</summary>

| 대상 | 패키지 | 버전 | 왜 썼나 |
|---|---|---|---|
| Python 에이전트 런타임 | (없음) 표준 라이브러리 + ctypes | Python 3.15.2 | 개발·테스트용(배포본은 Rust 에이전트). Rust 툴체인 없이 개발 서버·E2E·통합 테스트를 돌리려고 남김. `dependencies = []` |
| Python 에이전트 테스트 | pytest · pytest-timeout | 9.2.0 · 2.4.0 | 가짜 서버로 클라이언트·고지·이벤트 시험 |
| 서버 패키징 | pyinstaller (`build` 그룹) | 6.22.3 | onedir `mcp-monitor-server.exe`. 서명 없는 exe가 개발 PC의 Smart App Control을 통과해 채택 |
| Dummy MCP | mcp(공식 Python SDK) | 2.3.0 | FastMCP로 시험용 MCP 3종 |

</details>

---

## 📁 디렉터리 구조

<details>
<summary>최상위 트리 펼치기</summary>

```text
strategy-mcp-monitor/
├─ server/        # 서비스 백엔드 (FastAPI, 모니터 엔진, 수집기, 로그 저장소) — python -m app
│  ├─ app/        #   auth, monitor, sessions, activity, collect, logstore, web, win, winsvc, ...
│  └─ tests/      #   pytest (perf/ 는 100만 건 성능)
├─ desktop/       # Rust(Tauri 2) mcp-monitor.exe — src/{cli,payload,install,agent,app}, tests/, ui/(연결 중 페이지), icons/(icon.ico — make-icon.py로 생성)
├─ agent/         # Python 세션 에이전트 (개발·테스트용) — python -m mcp_agent
├─ web/           # 프런트엔드: board.html · admin.html · notice.html, src/, e2e/, tests/
├─ dummy-mcps/    # 시험용 MCP 3종 (seoul_weather, calculator, seoul_clock) + examples/ 조치 스크립트
├─ install/       # build.ps1(서버 payload), build-desktop.ps1(릴리스 exe), pyinstaller/
├─ .github/       # workflows/desktop.yml — Rust 테스트·릴리스 빌드(Windows 러너)
├─ docs/          # PLAN.md, ops/, verification/, design/, assets/(구성도 SVG, brand/ 에이전트 펄스 봇 아이콘 원본), superpowers/plans/
├─ build/         # (git 제외) PyInstaller 작업 폴더
└─ dist/          # (git 제외) payload/, mcp-monitor-<버전>.exe, .exe.sha256
```

`desktop/target/`(cargo 출력)과 `desktop/gen/`(tauri-build가 만듦)도 git에서 제외됩니다.

데이터 루트(`--root`) 아래에는 런타임 폴더 `logs/`, `data/`, `scripts/`가 생깁니다. 저장소 루트를 데이터 루트로 쓰면 이 폴더들은 git에서 제외됩니다.

</details>

---

## 📦 설치와 운영

전체 절차와 표는 [`docs/ops/OPERATIONS.md`](docs/ops/OPERATIONS.md)가 기준입니다. 여기에는 순서만 적습니다.

> 🪟 **`mcp-monitor.exe`는 창 프로그램(GUI 서브시스템)입니다.** PowerShell에서 결과를 기다리려면 꼭 파이프라인 안에서 부릅니다: `& .\mcp-monitor-1.1.0.exe install --dry-run | Write-Output`, 그다음 `$LASTEXITCODE`. 파이프 없이 부르면 PowerShell은 기다리지 않고 프롬프트를 돌려줍니다(출력도 종료 코드도 놓침).

### 1. 실행 파일 만들기 (개발 PC)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File install\build-desktop.ps1
```

- 순서: `install\build.ps1`(`pip-audit`·`pnpm audit` 관문 → `pnpm build` → PyInstaller 서버 → `dist\payload\`) → `cargo audit` → `cargo build --release --locked`(payload를 zstd로 내장, `dev` 기능 없음) → 검사(`--version`, `DependentLoadFlags`가 정확히 `0x800`, VC++ 재배포 패키지 DLL(`vcruntime*`·`msvcp*`·`concrt*`·`vccorlib*`) import 없음(`+crt-static`; Windows 10/11에 들어 있는 유니버설 CRT `api-ms-win-crt-*.dll`은 허용하고 목록만 출력), `verify-payload`로 풀어 내장 서버의 `--version`) → `dist\mcp-monitor-1.1.0.exe` + `.sha256`.
- `RUSTFLAGS`·`CARGO_ENCODED_RUSTFLAGS`·`CARGO_BUILD_RUSTFLAGS`·`CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_RUSTFLAGS`가 설정돼 있으면 시작하지 않습니다(`desktop\.cargo\config.toml`의 `+crt-static`·`/DEPENDENTLOADFLAG:0x800`을 덮어쓰므로). payload 파일 이름에 Windows 장치 이름(`CON`, `NUL`, `AUX`, `COM1` …, 확장자가 붙어도)이 있으면 묶지 않습니다.
- 매개변수: `-SkipAudit`(경고만 남기고 관문 생략), `-SkipPayload`(이미 만든 `-Payload` 폴더를 그대로), `-Payload <폴더>`, `-Out <폴더>`, `-SignThumbprint <SHA1> -TimestampUrl <url>`(인증서가 있을 때만 서명; 없으면 `NOTE: not signed`). `uv`가 PATH에 없으면 `UV_EXE`에 경로를 줍니다.
- 🧱 **Smart App Control이 켜진 PC에서는** 새로 빌드한 서명 없는 exe가 그때그때 막힐 수 있습니다(SAC는 파일 해시마다 평판으로 판단). 그래서 Rust 테스트와 릴리스 빌드의 정본은 **GitHub Actions**(`.github/workflows/desktop.yml`)입니다:
  - `fmt · clippy · test` 잡과 `release build · audit` 잡. 릴리스 잡은 `install\build-desktop.ps1`을 실제 payload로 끝까지 돌리고, 산출물 `mcp-monitor-release-<커밋>`(`mcp-monitor-1.1.0.exe` + `.sha256`, **서명 없음**)을 올립니다.
  - 러너의 사용자는 관리자라 "관리자 없이는 아무것도 바꾸지 않음"을 증명하는 테스트가 그대로는 `SKIPPED`로 건너뛰어집니다. 그래서 테스트 잡은 그 테스트들을 **임시 표준 사용자**(Users 그룹만, 무작위 비밀번호는 로그에서 가림, 끝나면 삭제)로 다시 돌리고, 하나라도 실패하거나 `SKIPPED`를 찍으면 실패합니다(`.github/scripts/standard-user-tests.ps1`). 릴리스 잡도 같은 스크립트(`-ReleaseExe`)로 릴리스 exe의 "관리자 없이 install → 종료 코드 1, 폴더 안 만듦"을 임시 표준 사용자로 확인합니다.
  - 워크플로는 데스크톱 테스트와 릴리스 payload가 읽는 모든 입력이 바뀐 push·PR에서 돕니다: `desktop/`, `server/app/`, 서버의 데스크톱·에이전트 테스트와 그 픽스처, `agent/`, `web/`, `install/`, `docs/ops/OPERATIONS.md`, 워크플로와 `.github/scripts/`. 그 밖의 것(다른 문서, `dummy-mcps/`)만 바뀐 커밋을 릴리스할 때는, 그 커밋의 `desktop` 실행이 없으므로 Actions 탭에서 손으로 실행(`workflow_dispatch`)해 그 커밋의 payload로 다시 만듭니다. 릴리스 파일 이름의 버전은 `desktop/Cargo.toml`에서 읽습니다.

### 2. 설치 (운영 PC)

1. 해시를 확인합니다: `Get-FileHash -Algorithm SHA256 .\mcp-monitor-1.1.0.exe`가 `.sha256`의 값과 같은지.
2. 서명이 없으니 SAC 상태부터 봅니다: `(Get-MpComputerStatus).SmartAppControlState`. `On`이면 `& .\mcp-monitor-1.1.0.exe --version | Write-Output`이 막히지 않는지 먼저 확인합니다(막히면 OPERATIONS ② 준비 2).
3. **더블클릭** → "지금 설치할까요?" **예** → UAC → "설치 완료" → 앱 창이 상태 보드를 열고, 보드의 **초기 설정 시작** 링크로 `/admin/setup`에 갑니다. 받은 exe는 지워도 됩니다.
4. 또는 관리자 PowerShell:

   ```powershell
   & .\mcp-monitor-1.1.0.exe install --dry-run | Write-Output   # 25단계 JSON, 관리자 불필요, 아무것도 바꾸지 않음
   & .\mcp-monitor-1.1.0.exe install --open-firewall | Write-Output; $LASTEXITCODE
   ```

   서비스 `mcp-monitor`(LocalSystem, `delayed-auto`, 실패 시 5/10/60초 뒤 재시작)를 등록·시작하고 `/api/channel`로 준비를 확인합니다. 종료 코드 0 성공, 1 실패(관리자가 아니면 아무것도 바꾸지 않음), 2 인자 오류.

> ⚠ **데이터 루트 폴더는 미리 만들지 마세요.** 설치가 SYSTEM·Administrators만 접근하는 ACL로 직접 만듭니다. 이미 있는 폴더는 비어 있거나 이전 설치의 데이터 루트일 때만 받고, 관리자가 아닌 계정이 그 폴더·상위 폴더·드라이브 루트를 지우거나 권한을 바꿀 수 있으면 거부합니다(종료 코드 2).

<details>
<summary><code>mcp-monitor.exe</code> 명령과 옵션</summary>

| 명령 | 옵션 | 하는 일 |
|---|---|---|
| (인자 없음) | — | 설치·업그레이드 안내 → UAC → 앱 창. 설치돼 있으면 곧바로 앱 창 |
| `install` | `--install-dir`, `--data-root`, `--open-firewall`, `--skip-audit-policy`, `--local-port`, `--external-port`, `--dry-run`, `--interactive` | 설치·업그레이드·복구 설치. 옵션을 빼면 이전 설치의 폴더·포트·방화벽을 그대로 |
| `uninstall` | `--install-dir`, `--data-root`, `--remove-data`, `--restore-audit-policy`, `--dry-run`, `--interactive` | 제거. 기본은 데이터를 남김 |
| `audit-policy` | `--enable` \| `--restore <csv>`, `--data-root`, `--dry-run`, `--interactive` | 감사 정책만 켜기·되돌리기 |
| `app` | `--background` | 앱 창 + 트레이(로그인 세션마다 하나, 관리자 권한으로는 열지 않음) |
| `autostart` | `on` \| `off` | 로그인할 때 트레이 시작(HKCU `Run`) |
| `agent` | `--server`, `--dialog webview\|print`, `--url-file`, `--unreachable-exit-sec` | 세션 에이전트(서비스가 띄움) |
| `verify-payload` | `<빈 폴더>` | 내장 서버 묶음을 검사하고 풀기 |
| `--version` | — | `mcp-monitor 1.1.0 (payload <12 hex>, release)` |

`--interactive`는 관리자가 아니면 같은 exe를 UAC로 다시 실행하고(해석한 옵션만 넘기고, `--dry-run`은 넘기지 않음) 결과를 메시지 상자로 보여 줍니다. 경로 규칙(UNC·subst·정션 거부 등)과 단계표 전체는 OPERATIONS의 ② 설치 절에 있습니다.

</details>

### 3. 확인과 첫 Admin

1. `sc.exe query mcp-monitor`로 실행 중인지 봅니다.
2. **그 PC에서** 앱 창(시작 메뉴 **MCP Monitor**)이나 `http://127.0.0.1:8700/admin/setup`에서 첫 Admin을 만듭니다.
3. 로그인 코드는 `C:\ProgramData\MCP Monitor\data\dev\otp-outbox.log`의 마지막 줄에 있습니다(Dummy OTP, 관리자만 읽기 가능).
4. **사용자** 화면에서 로그인할 MCP 개발자·Admin의 이메일을 등록합니다.

### 업그레이드, 제거, 감사 정책

```powershell
& "C:\Program Files\MCP Monitor\mcp-monitor.exe" uninstall --dry-run | Write-Output
& "C:\Program Files\MCP Monitor\mcp-monitor.exe" uninstall | Write-Output
```

- **업그레이드:** 새 버전의 exe를 더블클릭(또는 `install`). 새 폴더를 `<I>.staging`에 풀어 둔 뒤 서비스를 멈추고, 모든 세션의 앱·에이전트를 끝내고, 폴더를 통째로 바꿔 끼웁니다. 데이터·포트·방화벽·첫 설치 때의 감사 정책 백업은 그대로입니다. **낮은 버전으로는 설치하지 않습니다**(같은 버전은 복구 설치). 1.0.0(PowerShell 설치)도 이 방식으로 올라옵니다. 새 버전이 마이그레이션한 `config.db`는 옛 버전이 열지 않으니(종료 코드 5) 먼저 백업합니다.
- **제거:** 앱 및 기능의 **MCP Monitor → 제거**, 또는 위 명령. 기본은 서비스, 방화벽 규칙, 앱 및 기능·시작 메뉴, 설치 폴더만 지우고 **데이터는 남깁니다.** `--remove-data`는 데이터 루트와 모든 사용자의 `%LOCALAPPDATA%\mcp-monitor`(WebView2 프로필)까지 지우며 **되살릴 수 없습니다.** `--restore-audit-policy`는 첫 설치 전의 감사 정책·레지스트리 값으로 되돌립니다. 실행 중인 자신은 다음 재부팅 때 지워지므로, 그 전에는 같은 폴더로 다시 설치할 수 없습니다.
- **감사 정책만:** `mcp-monitor.exe audit-policy --enable`(켜기, 처음 한 번 백업) / `--restore <백업 csv>`(되돌리기), 공통으로 `--data-root`, `--dry-run`.

서비스 시작·정지, 종료 코드, 로그 재색인, 백업·복원은 OPERATIONS의 ⑤–⑦ 절을 봅니다.

---

## 🔧 개발 환경

> 🧯 **`uv run python -m …` 형태로만 부릅니다.** `uv run pytest`가 아니라 `uv run python -m pytest`입니다. Smart App Control이 `.venv\Scripts\*.exe` 콘솔 런처를 막기 때문입니다. `uv`가 PATH에 없으면 전체 경로로 부르고, 빌드·E2E에는 `UV_EXE` 환경 변수를 줍니다.

- Python 프로젝트(`server/`, `agent/`, `dummy-mcps/`)는 각 폴더에서 `uv sync`로 준비합니다.
- 웹은 `web/`에서 `pnpm install` 뒤 `pnpm <script>`. Node·pnpm 준비(nvm-windows, corepack)는 [`web/README.md`](web/README.md)에 있습니다.
- 서버는 기본으로 `web/dist`를 제공하므로 먼저 `pnpm build`를 한 번 합니다. 화면만 고칠 때는 `pnpm dev`(Vite)를 쓰면 `/api`가 `127.0.0.1:8700`으로 프록시됩니다.

### 서버 콘솔 실행

```powershell
cd server
uv run python -m app --root "$env:TEMP\mcpmon-dev" --external-host 127.0.0.1 --dev-otp-code 123456 --session-source none
```

- `--dev-otp-code`는 **개발 전용**입니다. 모든 사용자의 로그인 코드로 그 6자리를 받으므로, External 채널이 loopback이 아니면 거부합니다(`--allow-lan-dev`로만 허용).
- 하위 명령: `uv run python -m app reindex --root <루트>`(색인 다시 만들기, 그 루트를 서버가 쓰는 중이면 종료 코드 4), `python -m app service …`(SCM이 시작할 때만, 직접 실행하면 종료 코드 2).
- 종료 코드: 0 정상, 1 예기치 않은 오류, 2 인자, 3 포트 사용 중, 4 데이터 루트 사용 중, 5 `config.db`가 더 새 버전.

<details>
<summary>서버 CLI 옵션 전체</summary>

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--root` | 묶음에서는 `%ProgramData%\MCP Monitor`, 아니면 현재 폴더 | 데이터 루트 |
| `--local-port` / `--external-port` | `8700` / `8701` | 채널 포트 |
| `--external-host` | `0.0.0.0` | External 채널 주소 |
| `--static-dir` | 묶음의 `web\`, 아니면 `web/dist` | 빌드된 웹 |
| `--dev-otp-code` | 없음 | 개발용 고정 로그인 코드(6자리) |
| `--allow-lan-dev` | 꺼짐 | External이 loopback이 아니어도 `--dev-otp-code` 허용 |
| `--session-source` | `wts` | `wts`, `none`, `json:<path>`(개발: 파일의 세션) |
| `--collect-console` | 꺼짐 | 콘솔 세션도 추적(RDP가 없는 PC) |
| `--activity` | `on` | 프로세스 이벤트 수집 `on`/`off` |
| `--agent-launcher` | `auto` | `auto`, `wts`, `local`(이 세션만), `none` |
| `--agent-dialog` | 데스크톱 묶음은 `webview`, 체크아웃은 `edge` | `webview`(Rust 에이전트의 WebView2 창), `edge`(Python 에이전트의 Edge `--app` 창), `print`(고지 URL을 `<root>/run/agent-<session>.url`에 씀). 에이전트가 못 여는 조합은 종료 코드 2로 거부 |
| `--agent-dir` | 묶음 루트, 아니면 `<repo>/agent` | 에이전트 작업 폴더 |
| `--version` | — | `mcp-monitor 1.1.0` |

</details>

### 데스크톱 exe (Rust) 🦀

```powershell
cd desktop
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
cargo clippy --locked --all-targets --features dev -- -D warnings
cargo build --locked                      # 개발용 exe (fixture payload: 설치는 거부, 나머지는 됨)
```

- 툴체인: Rust 1.99.1(`rustup`, `%USERPROFILE%\.cargo\bin`) + Visual Studio Build Tools(MSVC x64, Windows SDK). `Cargo.lock`을 커밋하고 모든 명령에 `--locked`를 붙입니다.
- 🧯 **`cargo test`는 GitHub Actions가 정본입니다.** 개발 PC의 Smart App Control이 새로 빌드한 서명 없는 테스트 exe를 막을 때가 있어서입니다(파일마다 평판이라 빌드할 때마다 결과가 다름). 막히면 우회하지 말고 push해서 `desktop` 워크플로의 결과를 봅니다. 러너는 승격된 관리자라, "관리자 아님"을 전제로 한 테스트는 이유를 출력하고 건너뜁니다.
- 테스트는 관리자 없이, 이 PC의 서비스·HKLM·감사 정책·방화벽·Program Files를 건드리지 않습니다(가짜 `Host`·`Executor`·`Registry`, `%LOCALAPPDATA%` 임시 폴더). 실제 WebView2 창을 띄우는 테스트는 `#[ignore]`: `cargo test --locked --test agent_webview -- --ignored`, `cargo test --locked --features dev --test app_window -- --ignored`.
- `dev` 기능은 `app --server-url http://127.0.0.1:<port>`(개발 서버에 앱 창 붙이기)와 `WEBVIEW2_*` 환경 변수(CDP E2E)를 켭니다. 릴리스 빌드에는 절대 들어가지 않습니다(`build-desktop.ps1`이 검사).
- 내장할 payload를 바꾸려면 `MCPMON_PAYLOAD_DIR=<payload 폴더>`를 주고 빌드합니다. 없으면 `desktop/tests/fixtures/payload`(작은 가짜)를 품습니다.
- 개발 서버 + Python 에이전트 경로(`uv run python -m app` → `python -m mcp_agent`)는 Rust 없이 그대로 돕니다.

### Dummy MCP 🌦️ 🧮 🕰️

```powershell
cd dummy-mcps
uv sync
uv run python -m seoul_weather --chaos
```

| 모듈 | 기본 포트 | 도구 |
|---|---|---|
| `seoul_weather` | 9101 | `get_current_weather(district)`, `get_forecast(days)` (`--open-meteo`: 실데이터) |
| `calculator` | 9102 | `add`, `subtract`, `multiply`, `divide`, `evaluate(expression)` (AST 기반 안전 파서) |
| `seoul_clock` | 9103 | `now_kst()`, `convert_timezone(time, tz)` |

- 공통 옵션: `--host`(기본 `127.0.0.1`), `--port`, `--pid-file`, `--chaos`(`/chaos/crash`, `/chaos/hang?sec=N`, `/chaos/slow?ms=N`로 일부러 넘어뜨리기 — 자동 복구 시연용).
- `dummy-mcps/examples/{start,stop,restart}.ps1`은 모니터에 그대로 등록할 수 있는 조치 스크립트 예시입니다(`MCP_ID`, `MCP_NAME`, `MCP_HOST`, `MCP_PORT`, `DUMMY_MCPS_DIR`, 선택 `DUMMY_MCP_CHAOS`).

---

## 🧪 테스트와 품질

| 대상 | 폴더 | 명령 |
|---|---|---|
| 서버 | `server/` | `uv run python -m pytest -q` |
| 서버 정적 검사 | `server/` | `uv run python -m ruff check app tests` · `uv run python -m mypy` · `uv run python -m pip_audit` |
| Python 에이전트 | `agent/` | `uv run python -m pytest -q` · `uv run --project ../server python -m ruff check mcp_agent tests` |
| Dummy MCP | `dummy-mcps/` | `uv run python -m pytest -q` |
| 웹 단위·정적 검사 | `web/` | `pnpm test` · `pnpm lint` · `pnpm typecheck` · `pnpm audit` |
| 웹 번들 예산 | `web/` | `pnpm build` 뒤 `pnpm test:budget` (보드 초기 JS < 200 KB gzip, 고지 < 100 KB) |
| 웹 E2E | `web/` | `pnpm build` 뒤 `pnpm e2e` (실제 백엔드를 임시 루트로 띄움, `dummy-mcps/`에서 `uv sync` 필요, 스크린샷 비교·axe) |
| 데스크톱 exe | `desktop/` | 로컬: `cargo fmt --check` · `cargo clippy --locked --all-targets -- -D warnings`(+ `--features dev`). `cargo test --locked`와 `cargo audit`는 GitHub Actions `desktop` 워크플로가 정본 |

서버 pytest의 기본 실행은 아래 표지를 뺍니다(`server/pyproject.toml`의 `addopts`).

| 표지 | 켜는 법 | 내용 |
|---|---|---|
| `integration` | `-m integration` | 실제 하위 프로세스 시나리오(Windows, `dummy-mcps/.venv` 필요). 에이전트 통합은 Python·Rust 에이전트 둘 다로(Rust는 `MCPMON_DESKTOP_EXE`가 있을 때) |
| `winlive` | `-m winlive` | 이 PC의 실제 Windows API, 관리자 불필요(에이전트에도 있음) |
| `perf` | `-m perf` | 로그 100만 건 조회·보존 정리 성능(`server/.cache/`에 캐시, 첫 실행은 수 분) |
| `bundle` | 환경 변수 `MCPMON_BUNDLE=<repo>\dist\payload` + `-m bundle` | 빌드한 서버 payload 실행 |
| `desktop` | 환경 변수 `MCPMON_DESKTOP_EXE=<repo>\dist\mcp-monitor-1.1.0.exe` + `-m desktop` | 릴리스 exe: `--version`, `verify-payload`로 푼 내장 서버, 관리자 없는 `install` |

📈 **성능:** 목표는 "로그 100만 건 기준 필터 < 300 ms"이고, 시나리오 S1–S15가 모두 통과했습니다(함수 단위 중앙값). 흔한 낱말 키워드의 히스토그램·사용자 건수는 300 ms를 넘을 수 있고, 색인 읽기 하나는 5초에서 끊깁니다(`X-Error-Reason: query_timeout`). 수치는 [`docs/verification/perf-p6.md`](docs/verification/perf-p6.md), 나머지 목표는 [`docs/PLAN.md` §7](docs/PLAN.md#7-성능-설계).

---

## 🔒 보안 참고

- **채널 분리:** 8700은 `127.0.0.1`에만 열고, Local 전용 라우트는 8701에 등록하지 않습니다. **8700 앞에 리버스 프록시나 포트 전달을 두지 마세요.** 외부 요청이 Local 권한을 얻게 됩니다.
- **localhost도 로그인 필수:** RDP 접속자도 그 PC의 localhost에 닿습니다. Local은 권한을 넓혀 줄 뿐 본인 확인을 대신하지 않습니다. 쿠키는 `HttpOnly`·`SameSite=Strict`, 변경 요청은 CSRF 토큰 검사.
- **8701은 HTTP 평문입니다.** 로그인 코드와 쿠키가 암호화되지 않으므로 믿을 수 있는 사내망에서만 엽니다.
- **CSP:** HTML 응답에 `default-src 'self'; script-src 'self'; … object-src 'none'; frame-ancestors 'none'`. 글꼴·스크립트는 번들에 포함하고 CDN을 쓰지 않습니다.
- **에이전트 인증(양방향):** `/api/agent/*`와 `/api/notice/display/*`는 Local에만 있고, 실행마다 바뀌는 토큰 + **요청 TCP 피어의 세션 ID**를 검사합니다. 에이전트도 요청마다 새 nonce에 대한 `X-Server-Proof`(HMAC-SHA256)로 서비스를 검증하고, 증명하지 못하는 상대면 창을 열지 않고 종료합니다. 고지 토큰은 로그에서 `<redacted>`로 가리고, WebView2 고지 창은 토큰을 명령줄이 아니라 API로 넘깁니다.
- **승격은 필요할 때만:** exe는 `asInvoker`이고, 설치·업그레이드·제거·감사 정책의 `--interactive`만 UAC로 **같은 exe**를 다시 실행합니다(해석한 옵션만 넘기고 `--dry-run`은 넘기지 않음). DLL은 System32에서만 찾아(`DependentLoadFlags 0x800`), 다운로드 폴더에 심은 DLL을 승격된 프로세스가 읽지 않습니다.
- **내장 묶음:** 전체 해시와 파일별 SHA-256을 확인하고, 관리자만 쓸 수 있는 `<I>.staging`에만 풉니다. 공유 `%TEMP%`에 실행 파일을 두지 않고, 개발용 묶음으로는 설치하지 않습니다.
- **앱 창(WebView2):** `127.0.0.1:<Local 포트>`만 열고 다른 주소는 기본 브라우저로, 개발자 도구·브라우저 단축키 없음, `WEBVIEW2_*` 환경 변수 무시.
- **데이터 루트 ACL:** 상속을 끊고 SYSTEM(`S-1-5-18`)과 Administrators(`S-1-5-32-544`)만. 표준 사용자는 로그·설정·스크립트·로그인 코드를 읽지 못합니다. 설치 폴더는 바꿔 끼운 뒤 트리 전체를 검사해, 관리자가 아닌 계정이 쓸 수 있으면 되돌립니다.
- **스크립트는 SYSTEM으로 실행됩니다.** 편집은 Local의 MCP 소유자만(Admin도 예외 아님), 실행 직전 해시가 다르면 막고 `tamper`로 남깁니다.
- **RDP 계정은 Windows 표준 사용자로.** 관리자 권한이 있으면 에이전트·감사 정책·이벤트 로그를 끌 수 있고, MCP Monitor는 그것을 기록할 뿐 막지 못합니다.

자세한 내용은 OPERATIONS의 ⑧ 보안 절과 [`docs/PLAN.md` §4](docs/PLAN.md)를 봅니다.

---

## ❓ FAQ와 문제 해결

<details>
<summary>exe를 더블클릭했는데 아무 일도 없거나 "차단되었습니다"가 떠요.</summary>

Smart App Control(SAC)일 가능성이 큽니다. 이 exe에는 **코드 서명이 없고**(인증서 없음), SAC는 파일마다 평판으로 판단합니다. `(Get-MpComputerStatus).SmartAppControlState`로 상태를, 이벤트 뷰어 `Microsoft → Windows → CodeIntegrity → Operational`의 3076/3077로 차단 기록을 봅니다. SAC를 끄는 것은 기기 소유자의 결정이고, 정해 둔 대안은 서명한 빌드(`build-desktop.ps1 -SignThumbprint`) 또는 1.0.0 PowerShell 설치 묶음입니다(OPERATIONS ②).

</details>

<details>
<summary>PowerShell에서 <code>mcp-monitor.exe install</code>을 쳤는데 아무 출력 없이 끝났어요.</summary>

창 프로그램이라 PowerShell이 기다리지 않은 겁니다. `& .\mcp-monitor-1.1.0.exe install | Write-Output`처럼 파이프를 붙이면 끝날 때까지 기다리고 출력과 `$LASTEXITCODE`를 받습니다. `$out = & .\mcp-monitor-1.1.0.exe …`도 같은 이유로 비어 있습니다.

</details>

<details>
<summary>로그인 코드가 메일로 안 와요.</summary>

1.1.0의 OTP도 Dummy 공급자라 메일을 보내지 않습니다. 코드는 `<데이터 루트>\data\dev\otp-outbox.log`에 `<시각> <이메일> <코드>` 줄로 쌓이고, 관리자만 읽을 수 있습니다. 등록되지 않은 이메일에는 코드를 보내지 않습니다. 다른 PC의 사용자에게는 관리자가 코드를 전달합니다.

</details>

<details>
<summary>다른 PC에서 <code>http://&lt;PC&gt;:8701</code>이 안 열려요.</summary>

방화벽이 기본으로 닫혀 있습니다. `mcp-monitor.exe install --open-firewall`로 다시 설치하거나 규칙을 직접 만듭니다. `--open-firewall`은 도메인·개인 프로필만 열기 때문에 공용 프로필 네트워크에서는 열리지 않습니다. 확인: `Get-NetFirewallRule -DisplayName "MCP Monitor*"`.

</details>

<details>
<summary>서비스가 시작하자마자 멈춰요 (종료 코드 3 / 4 / 5).</summary>

| 코드 | 뜻 | 조치 |
|---|---|---|
| 3 | 8700 또는 8701을 다른 프로세스가 사용 중 | `Get-NetTCPConnection -LocalPort 8700,8701 -State Listen`으로 찾아 끝내거나 `--local-port`·`--external-port`로 재설치 |
| 4 | 같은 데이터 루트를 다른 MCP Monitor가 사용 중(`data\.lock`) | 손으로 띄운 콘솔 서버나 진행 중인 `reindex`를 끝냄 |
| 5 | `config.db`가 이 프로그램보다 새 버전 | 더 새 버전을 설치하거나 백업을 복원 |

오류는 이벤트 뷰어(응용 프로그램, 원본 `mcp-monitor`)와 `logs\<오늘>.jsonl`의 `"cat":"system"` 줄에 남습니다.

</details>

<details>
<summary>로그 화면에 "색인 중"이 계속 보여요.</summary>

업그레이드나 재색인 직후에는 정상입니다(최근 날짜부터 보입니다). 오래 남으면 `system` `logindex.cycle_failed`를 확인하고, 서비스를 멈춘 뒤 **서버 exe**로 다시 만듭니다: `& "C:\Program Files\MCP Monitor\bin\monitor\mcp-monitor-server.exe" reindex --root "<데이터 루트>"`. 바깥의 `mcp-monitor.exe`에는 `reindex`가 없습니다(그건 데스크톱 앱이니까요).

</details>

<details>
<summary>고지 창이 뜨지 않아요.</summary>

`system` 로그의 `agent.launch_failed`·`agent.launched`와 **세션 → 수집 상태**를 봅니다. 그 세션에 사용자 권한의 `mcp-monitor.exe`(에이전트)가 떠 있는지도 봅니다. WebView2 런타임이 없으면 기본 브라우저 탭으로 엽니다. 개발 체크아웃의 콘솔 서버는 기본으로 `auto` 런처가 `local`, 곧 그 세션에만 Python 에이전트를 띄웁니다.

</details>

<details>
<summary>고지 창을 닫을 수가 없어요. 버그인가요?</summary>

의도된 동작입니다. 닫기 단추는 회색이고 Alt+F4도 무시합니다. '확인'을 누르면 닫히고, 그 사실이 `notice_acknowledged`로 남습니다. 그래도 다른 앱은 그대로 쓸 수 있습니다 — 고지는 맨 위에 떠 있을 뿐 입력을 가로채지 않습니다.

</details>

<details>
<summary>cmd에서 <code>dir</code>, <code>del</code> 친 건 왜 안 남나요?</summary>

의도된 결정입니다(스펙 §2 #7). cmd 내부 명령은 프로세스를 만들지 않아 4688에 남지 않고, 수집하려면 cmd에 훅을 걸어야 하기 때문에 범위에서 뺐습니다. `cmd.exe` 실행과 인자, `cmd /c …`, 배치 파일, cmd에서 띄운 외부 프로그램은 남고, PowerShell은 4104로 남습니다.

</details>

<details>
<summary>Windows에 원래 있는 <code>McpManagementService</code>와 같은 건가요?</summary>

아닙니다. 이 프로젝트의 서비스 이름은 `mcp-monitor`(표시 이름 `MCP Monitor`)이고, Microsoft의 `McpManagementService`는 건드리지 않습니다. 이름이 닮은 건 순전히 우연입니다.

</details>

더 많은 증상과 조치는 OPERATIONS의 ⑨ 알려진 동작과 ⑩ 문제 해결 절에 있습니다.

---

## 🚧 현재 상태와 한계

- ✅ **구현 완료:** Plan 1–6, 곧 스펙의 P0–P8(기반, 인증·권한, Dummy MCP·모니터 엔진, 상태 보드·MCP 관리 UI, 세션 수집, 행동 로그·고지, 로그 조회·보존, 배포·하드닝, 데스크톱 앱). 버전 1.1.0.
- ⏳ **실기기 확인 대기:** 개발 PC가 Windows 11 Home(관리자 아님, SAC 켜짐)이라 실제 UAC, RDP, SYSTEM 서비스, ACL, 감사 정책, 방화벽, 다른 세션의 고지 창은 자동 테스트로 확인하지 못했습니다. 점검표의 결과 칸은 모두 `대기`입니다.
  - [`docs/verification/win11-pro-p8.md`](docs/verification/win11-pro-p8.md): 데스크톱 exe(설치·업그레이드·제거·앱 창·트레이·WebView2 고지·SAC)
  - [`docs/verification/win11-pro-p4-p5.md`](docs/verification/win11-pro-p4-p5.md): 세션 수집, 행동 로그, 고지
  - [`docs/verification/win11-pro-p6-p7.md`](docs/verification/win11-pro-p6-p7.md): 로그 조회·보존, 설치·서비스
- 🔀 **스펙과 달라진 점:**
  - 고지 창의 "모달"은 **맨 위에 떠서 확인 전에는 닫히지 않는 창**입니다. Windows가 다른 프로세스의 입력을 막는 모달을 허용하지 않기 때문입니다.
  - 에이전트 ↔ 서비스는 Named Pipe 대신 **Local 채널 loopback HTTP**(토큰 + 피어 세션 검사 + 서버 HMAC 증명)입니다.
- 🎭 **OTP는 Dummy 공급자입니다.** 실제 메일·문자 발송은 없습니다.
- ✍️ **코드 서명 없음.** 서명 단계는 준비돼 있지만 인증서가 없습니다. 대상 PC의 SAC가 막는지는 실기기 P8-1에서 봅니다.
- 그 밖에: External 채널 HTTPS 없음, 외부 알림(메일·웹훅) 없음, MSI 없음(exe 하나), cmd 내부 명령 미수집, 흔한 키워드의 건수 집계는 느릴 수 있음.

---

## 🔭 로드맵

남은 일은 [`docs/superpowers/plans/carry-forward.md`](docs/superpowers/plans/carry-forward.md)의 **"After Plan 5 (추후)"**와 **"After Plan 6 (추후)"**에 이유와 함께 모여 있습니다. 주요 항목:

- **제품:** 알림 채널(토스트·메일·웹훅), 실제 OTP 공급자, External HTTPS, 설정 백업·가져오기, 로그 해시 체인, syslog/SIEM·GeoIP, 로그온 전 법적 고지, 코드 서명 인증서, (필요해지면) MSI.
- **데스크톱:** 실기기 P8 점검, 그 뒤 Python 에이전트 은퇴 검토, 로그온하지 않은 사용자의 `Run` 값 정리, WebView2가 없을 때의 고지 경로.
- **엔지니어링:** 넓은 키워드 건수 근사, 5초 제한 오류 문구 개선, 서비스 종료 코드 3/4/5의 SCM 재시작 루프 정리 등.
- **웹 UI:** 640×600에서 필터 접기, 키워드 도움말 노출, 실제 화면 낭독기 점검, 설정 화면 시각 기준선.

---

## 🤝 기여와 커밋 규칙

- **브랜치:** `main`에서 작업 브랜치를 땁니다(예: `feat/plan6-desktop-app`). `feat/**`로 push하면 데스크톱 관련 변경에서 `desktop` 워크플로가 돕니다.
- **커밋 메시지:** Conventional Commits 접두어 `feat:`, `fix:`, `docs:`, `test:`, `build:`, `chore:`에 영어 요약. 계획 단위 작업은 `fix: Plan 5 review — …`처럼 계획 이름을 붙입니다.
- **테스트 먼저:** 실패하는 테스트 → 구현 → 전체 통과의 순서(스펙 §12). 권한 매트릭스(§4.3)는 전체가 자동 테스트로 묶여 있으니 권한을 바꾸면 테스트도 함께 바꿉니다. CLI 옵션을 더하면 운영 문서에도 적어야 테스트(`operations_guide_documents_every_cli_option`)가 통과합니다.
- **푸시 전 확인:** 서버 `pytest`·`ruff`·`mypy`, 에이전트 `pytest`·`ruff`, 웹 `test`·`lint`·`typecheck`, 화면을 바꿨다면 `pnpm build` + `pnpm e2e`, Rust를 바꿨다면 `cargo fmt --check`·`clippy -D warnings` 뒤 CI의 `cargo test`가 초록인지. 테스트는 전체 통과, 린트·타입 오류는 0건이어야 합니다.
- **의존성:** 웹은 정확한 버전으로 고정하고 `pnpm audit`이 깨끗해야 합니다. Python은 `uv.lock`을 커밋하고 `pip-audit`을 통과해야 합니다. Rust는 `Cargo.toml`에 `=x.y.z`, `Cargo.lock` 커밋, `cargo audit` 통과, `windows`·`webview2-com`·`tauri-utils`는 한 버전만(빌드 관문과 같음).
- **포매터:** `ruff format`은 아직 쓰지 않습니다(일괄 줄바꿈이 다른 작업과 충돌, carry-forward의 Engineering 항목). Rust는 `cargo fmt`.
- **시각 기준선:** 스크린샷을 바꿀 때는 `pnpm e2e e2e/visual.spec.ts --update-snapshots=all` 뒤 PNG를 하나씩 열어 본 다음 커밋합니다.
- **문서:** 동작이 스펙과 달라지면 [`docs/PLAN.md`](docs/PLAN.md) 변경 이력에, 운영 절차가 바뀌면 [`docs/ops/OPERATIONS.md`](docs/ops/OPERATIONS.md)에 적습니다.

---

## 📜 라이선스

저장소에 라이선스 파일이 **아직 없습니다.** 라이선스가 정해지기 전까지는 별도 허락 없이 복제·배포·수정할 권리가 주어지지 않습니다.

---

## 📚 문서

| 문서 | 내용 |
|---|---|
| [`docs/PLAN.md`](docs/PLAN.md) | 기준 스펙 v0.9: 요구사항, 아키텍처, 권한 매트릭스, 컴포넌트, 화면, 성능, API, 기술 스택, 변경 이력 |
| [`docs/ops/OPERATIONS.md`](docs/ops/OPERATIONS.md) | 운영 문서 v1.1.0: 설치·업그레이드·제거(모든 CLI 옵션), 서비스 운영, 로그, 백업·복원, 보안, 문제 해결(설치 폴더에도 포함) |
| [`docs/design/desktop-app-rust.md`](docs/design/desktop-app-rust.md) | 데스크톱 앱(Rust 단일 exe) 설계와 결정 D2–D5 |
| [`docs/verification/perf-p6.md`](docs/verification/perf-p6.md) | 로그 조회·색인·보존 정리 성능 기록 |
| [`docs/verification/win11-pro-p8.md`](docs/verification/win11-pro-p8.md) | 실기기 점검표: 데스크톱 exe, P4–P7 다시 수행 안내 |
| [`docs/verification/win11-pro-p4-p5.md`](docs/verification/win11-pro-p4-p5.md) | 실기기 점검표: 세션 수집, 행동 로그, 고지 |
| [`docs/verification/win11-pro-p6-p7.md`](docs/verification/win11-pro-p6-p7.md) | 실기기 점검표: 로그 조회·보존, 배포·하드닝 |
| [`docs/design/`](docs/design/) | 디자인 방향(`direction.md`), 디자인 시스템(`design-system.md`), 화면별 명세(`screens/`), 디자인·접근성 리뷰 |
| [`docs/superpowers/plans/`](docs/superpowers/plans/) | Plan 1–6 구현 계획과 결정 기록, 이월 항목(`carry-forward.md`) |
| [`web/README.md`](web/README.md) | 웹 툴체인, pnpm 스크립트, E2E 실행 방법 |
