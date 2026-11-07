# 화면 설계 — 로그인·초기 설정·관리 셸 (`admin` 번들 기반)

Task 9 산출물. `frontend-design` 스킬로 `docs/design/direction.md`(고성능 HMI 관제 콘솔)를 로그인과 관리 셸에 적용했습니다. 문구는 `design:ux-copy`(해요체, `web/src/copy/ko.ts`), 움직임은 audit-suite `web-animation-design`, React 구조는 `vercel-react-best-practices`를 따릅니다. 토큰·컴포넌트 규칙은 `docs/design/design-system.md`.

## 1. 일

- **로그인:** 등록된 이메일 → 6자리 코드 → 원래 가려던 화면. 비밀번호가 없으니 이 화면에서 헤매는 일은 "코드가 안 왔다 / 틀렸다 / 잠겼다" 세 가지뿐이고, 화면은 그 셋을 숫자로 말해 줍니다(5번 틀리면 코드 무효, 1시간에 10번 틀리면 잠금, 남은 분).
- **초기 설정:** Local 채널에서 사용자가 하나도 없을 때 한 번만. 첫 Admin의 이메일·이름 → 로그인 화면(이메일 미리 채움).
- **관리 셸:** 어떤 관리 화면에서도 "어디에 있나, 무엇을 할 수 있나, 무엇을 왜 못 하나"가 보이게. 못 쓰는 메뉴도 숨기지 않고 비활성 + 이유(§4.4, U26).

## 2. 이 화면의 한 가지 대담함

로그인의 **6칸 코드 입력**이 이 화면의 얼굴입니다. 칸은 넓고(48px) 숫자는 `text-2xl` `tabular-nums`, 그 밖의 요소(제목, 안내, 링크)는 `text-sm`으로 조용합니다. 틀리면 칸 묶음이 좌우로 짧게 흔들리고(translateX, 360ms) 칸 테두리가 `danger`로 바뀝니다. 색만이 아니라 글자("인증 코드가 맞지 않아요…", 실패 횟수)가 함께 나옵니다.

관리 셸은 의도적으로 조용합니다. 색은 상태에만 쓰므로(방향 §2.1) 내비의 현재 위치는 색이 아니라 **명도**(`selected` 채움 + `fg` 글자 + 굵기 유지)로 표시합니다.

## 3. 로그인 (`/admin/login?redirect=&email=`)

```
┌ 머리 56px ─────────────────────────────────────────────────────────┐
│ MCP Monitor   [▣ 로컬 관리 모드]                              ◐    │
└────────────────────────────────────────────────────────────────────┘
          ┌ 24rem 열(가운데 놓되 내용은 왼쪽 정렬) ─────┐
          │ 로그인                     [⚗ 개발용 OTP 모드] │  ← text-xl + 배지(otp_provider=dummy)
          │ 등록된 이메일로 받은 인증 코드로 로그인해요.  │  ← fg-muted
          │                                              │
          │ 1단계  이메일 [name@example.com        ]     │
          │        [ 인증 코드 받기 ]  (주 버튼, 전체 폭) │
          │                                              │
          │ 2단계  등록된 이메일이면 a@x.com(으)로 …     │  ← role=status
          │        ┌──┐┌──┐┌──┐┌──┐┌──┐┌──┐             │  ← OtpInput(role=group)
          │        │ 2││ 4││ 6││  ││  ││  │             │
          │        └──┘└──┘└──┘└──┘└──┘└──┘             │
          │        [ 로그인 ]                            │
          │        ◔ 42초 뒤에 다시 받을 수 있어요 [코드 다시 받기] │ ← ResendRing + aria-disabled 버튼
          │        다른 이메일로 로그인                   │  ← 링크 모양 버튼
          │        개발용 OTP: 서비스 콘솔을 확인하세요.  │  ← dummy일 때만
          └──────────────────────────────────────────────┘
```

- 한 열, 왼쪽 정렬(방향 §2 "가운데 정렬 대화상자 없음"). 열 자체만 화면 가운데에 놓습니다.
- 머리: 제품명(보드로 가는 링크), 채널 배지, 테마. 스트림 표시는 없습니다(로그인 화면은 실시간 데이터를 보여 주지 않음).
- 이메일은 `type=email` + `autocomplete=username`, 코드 첫 칸은 `autocomplete=one-time-code`(Windows·Android 자동 채움이 6자리를 한 번에 넣음 → F19 붙여넣기 경로).
- 6칸이 다 차면 바로 확인 요청(`onComplete`). "로그인" 버튼은 Enter·마우스 사용자를 위해 남깁니다.

### 3.1 상태

| 상태 | 표시 | 문구 키 |
|---|---|---|
| 개발 배지 | 제목 옆 outline 배지 + 2단계 안내 한 줄 | `login.devBadge`, `login.devHint` |
| 이메일 형식 오류(422 `invalid_email`, 빈 값) | 입력칸 `aria-invalid` + 바로 아래 오류 글자(`danger`) | `errors.invalid_email` |
| 코드 보냄 | 2단계, 상태 문장(`role=status`) | `login.codeSent(email)` |
| 다시 받기 대기 | 24px 원형 타이머(U25 `@property --progress` + `conic-gradient`) + "N초 뒤에…" 글자. 버튼은 `aria-disabled` + `aria-describedby`(남은 시간) | `login.resendIn(n)`, `login.resend` |
| 틀린 코드(401) | 칸 흔들림 + 비우고 첫 칸 포커스, 오류 문장 + 이 코드 실패 횟수 + 10회 규칙 안내 | `login.wrongCode`, `login.failedCount(n)`, `login.failureHint` |
| 코드 소진(5회) | 칸 비활성, "새 코드를 받으세요" + 10회 규칙 | `login.codeExhausted` |
| 요청 제한(429, Retry-After ≤ 60) | 2단계로 넘어가고 타이머를 Retry-After에 맞춤(F05: 코드는 이미 있음) | — |
| 잠김(429, Retry-After > 60) | `role=alert` 오류 상자, 남은 분(올림) | `login.lockedFor(min)` |
| 그 밖의 오류 | `role=alert` 오류 상자 | `errors.<code>` |
| 초기 설정 직후(`?email=`) | 이메일 미리 채움 + 완료 안내 | `setup.done` |

이메일 잠금과 IP 제한은 서버가 구분하지 않으므로 같은 문장입니다(U7). 등록되지 않은 이메일도 같은 "보냈어요" 응답이라 문장은 등록 여부를 단정하지 않습니다.

### 3.2 이동 규칙

- 로그인 성공 → `setSessionFromLogin` → 스트림 `restart()`(연결 시점 인증 수준 유지) → `safeRedirect(redirect)`.
  - 대상이 `/admin` 아래면 라우터 이동(전체 새로 고침 없음).
  - 아니면(예: 보드의 `?redirect=/`) `window.location.assign` — `/`는 다른 HTML 엔트리라 라우터가 모릅니다(F11).
  - `//evil.com`, `/\evil.com`, `https://…`, `/api/…`는 `/admin`으로 바꿉니다(`lib/redirect.ts`).
- Local + 익명 + `GET /api/bootstrap` `needed` → 로그인 대신 `/admin/setup`. 원격 채널은 그 API를 부르지 않습니다.

## 4. 초기 설정 (`/admin/setup`)

로그인과 같은 머리·열. 제목 "처음 사용할 Admin 만들기", 안내 한 문단, 이메일·이름(필수, 최대 320·100자), 주 버튼 "Admin 만들기". 성공 → `/admin/login?email=…`. 409 `bootstrap_done`(다른 탭이 먼저 만듦) → 로그인. 원격 채널이거나 이미 끝났으면 화면 대신 로그인으로 보냅니다.

## 5. 관리 셸

```
1366×768
┌ TopBar 56px(sticky, Task 8) ──────────────────────────────────────────────────────────┐
│ MCP Monitor  [▣ 로컬 관리 모드]                       ● 실시간  ◐  [👤 홍길동 ▾]      │
├───────────────┬───────────────────────────────────────────────────────────────────────┤
│ [⌕ 빠른 이동 Ctrl K] │ (본문: 각 화면, 좌우 24px, 위 24px)                                │
│               │                                                                        │
│ ▦ 대시보드     │                                                                        │
│ ⬡ MCP         │                                                                        │
│ ▢ 세션   준비 중 │ ← aria-disabled, fg-muted, 툴팁 + 숨은 설명 = copy.deny.planned_sessions │
│ ≡ 로그   준비 중 │                                                                        │
│ ⛨ 감사 로그 준비 중│                                                                     │
│ ── (구분선)    │                                                                        │
│ 👥 사용자      │ ← manage_users 게이트(원격: local_only 이유, 개발자: admin_only 이유)   │
│ 📣 사전 고지   │ ← edit_notice                                                          │
│ ⚙ 설정        │ ← edit_global_settings                                                 │
└───────────────┴───────────────────────────────────────────────────────────────────────┘
```

- 사이드바 `--size-sidebar`(15rem), `surface` 면 + 오른쪽 헤어라인. 항목 높이 36px(터치 44px), 아이콘 16px + 글자 `text-sm`.
- 현재 위치: `aria-current="page"` + `bg-selected` + `text-fg`. 나머지 `text-fg-muted`, hover `bg-hover`(120ms 색 전환만).
- 막힌 항목: 링크 모양 그대로(`role=link`, 포커스 받음) `aria-disabled="true"`, 글자 `fg-muted` 50% 아님 — 읽혀야 하므로 대비 4.5:1 유지, 대신 아이콘을 흐리게 하고 오른쪽에 "준비 중"/자물쇠 아이콘. 누르거나 Enter를 눌러도 이동하지 않고, 툴팁(호버·포커스)과 숨은 설명(`aria-describedby`)으로 이유를 말합니다.
- 채널 배지와 역할 배지: 채널은 TopBar(Task 8 `ChannelBadge`), 역할은 계정 메뉴 안(`AccountMenu`)과 사이드바 아래 사용자 줄("홍길동 · Admin" 대신 이름 줄 + 역할 배지 두 줄).
- 본문: `main#main`, 건너뛰기 링크가 맨 앞. 라우트가 바뀌면 View Transition(200ms 크로스페이드, `defaultViewTransition`), reduced-motion이면 즉시.
- 토스트: Sonner, 오른쪽 아래.

### 5.1 화면 폭

휴대폰·터치 전용 배치는 범위 밖이지만(사용자 지시, 2026-11-05), 브라우저 창은 작아질 수 있으므로 **640×600까지 유동적**이어야 합니다.

- 창 폭 1024px 이상: 15rem 사이드바(글자 + "준비 중"/자물쇠 + 아래 사용자 줄).
- 1024px 미만: 사이드바가 **아이콘 레일**(`--size-rail` 3.5rem)로 접힘. 글자·사용자 줄은 `sr-only`로 남아 이름은 그대로이고, 보이는 글자는 오른쪽 툴팁으로(열린 항목: 이름, 막힌 항목: 이름 + 이유). "빠른 이동" 버튼은 돋보기 아이콘만.
- 가로 페이지 스크롤 없음. 본문은 `minmax(0,1fr)`라 내용이 넓어도 셸을 밀지 않습니다(표는 각 Task가 자기 상자 안에서 가로 스크롤).
- 로그인·초기 설정 열(24rem)은 640px에서도 그대로 들어갑니다. 600px 높이에서는 세로 스크롤만 생깁니다.
- 명령 팔레트는 Dialog의 `max-w-[calc(100%-2rem)]`·`max-h-[calc(100dvh-2rem)]`로 창 안에 맞습니다.

처음에는 휴대폰용 가로 스크롤 내비를 만들었으나, 지시에 따라 걷어내고 레일로 바꿨습니다.

### 5.2 명령 팔레트

- `Ctrl+K`(Windows) / `⌘K`(macOS)로 열고, 사이드바 맨 위 "빠른 이동" 버튼으로도 엽니다(마우스 사용자, 단축키 발견). 버튼에 마우스를 올리거나 포커스하면 청크를 미리 받습니다.
- cmdk는 별도 청크(`React.lazy`), 처음 열 때 로드.
- 묶음 "화면": 내비 항목 전부. 막힌 항목은 비활성(`aria-disabled`, 키보드 선택에서 건너뜀) + 이유를 보조 글자로.
- 묶음 "MCP": `qk.mcps` 캐시(없으면 그때 요청)의 이름 → 상세. 호스트:포트는 보조 글자(mono).
- 움직임: 공용 Dialog의 200ms fade + scale(0.95→1). 키보드로 자주 여는 창이라 더 짧게 할 수도 있으나, 막(scrim)과 같은 시간·이징을 지키는 쪽을 택했습니다(쌍 요소 규칙).

## 6. 예정 기능 빈 상태 (`PlannedFeature`)

헤어라인 테두리 카드, 왼쪽 정렬: 회색 모래시계 아이콘(장식) + `copy.deny[reason]` 한 문장. 가짜 숫자·차트·스켈레톤 없음(U13). 대시보드의 "로그인 실패 추이"·"우회 탐지 이벤트"(Task 10)와 설정의 알림 채널(Task 13)이 씁니다.

## 7. 움직임

| 요소 | 방식 | 시간·이징 | reduced-motion |
|---|---|---|---|
| OTP 흔들림 | `@keyframes` translateX(±6px → 0), `[data-invalid]`가 다시 붙을 때마다 재시작 | 360ms ease-in-out(화면 위 이동) | 없음(테두리·글자만) |
| 재발송 원형 타이머 | `@property --progress` + `conic-gradient`, 한 번의 CSS 애니메이션(U25 유일한 예외) | 남은 초, linear(시계) | 정지(시작 비율 유지), 숫자는 계속 |
| 라우트 전환 | View Transition 크로스페이드 | 200ms ease-out | 즉시 |
| 명령 팔레트 | Dialog 공용 | 200ms ease-out | 즉시 |
| 내비 hover | 배경색 | 120ms ease | 즉시 |

움직이는 요소는 `data-anim`을 답니다(`shake`, `ring`).

## 8. 접근성

- 코드 칸: `role=group` + `aria-label="인증 코드 6자리"`, 각 칸 `aria-label="N번째 자리"`, `inputMode=numeric`. 틀리면 모든 칸 `aria-invalid`, 오류 문장은 `role=alert`.
- 타이머 글자는 `role=timer` + `aria-live=off`(매초 읽지 않음). 버튼은 `aria-describedby`로 남은 시간을 가리킴.
- 막힌 내비: U26(`aria-disabled`, 포커스 유지, 이유 두 번 — 툴팁과 설명).
- 내비 `nav aria-label="관리 메뉴"`, 현재 위치 `aria-current=page`.
- 401로 로그인에 돌아오면 원래 경로를 `redirect`로 들고 가며, 이동은 `useBlocker`를 건너뜁니다(F12, 초안은 각 편집기가 이미 저장).

## 9. Step 6 확인 목록 (Playwright 플러그인, 2026-11-05)

실제 백엔드: `python -m app --root <임시> --external-host 127.0.0.1 --dev-otp-code 246810 --static-dir web/dist`(F36), 빌드한 `web/dist`. 스크린샷은 검토 자료라 커밋하지 않았습니다(U30).

- [x] 로컬(8700), 사용자 없음: `/admin` → 로그인 → `/admin/setup`으로 넘어감. 설정 화면 다크 1366px.
- [x] 초기 설정 → `/admin/login?email=…` 이메일 미리 채움 → 코드 단계. 개발 배지(제목 옆)와 개발 안내(코드 단계 아래) 표시.
- [x] 원형 타이머가 줄어들고 "N초 뒤에…"가 매초 바뀜, "코드 다시 받기"는 대기 중 `aria-disabled`.
- [x] 틀린 코드(`fill` 6자리 한 번에, F19 경로): 칸 비움 + 첫 칸 포커스 + 테두리 `danger` + `otp-shake` 애니메이션, 오류 문장 + "1번 틀렸어요" + 10회 규칙.
- [x] reduced-motion: 두 번째 실패에서 `animation-name: none`(흔들림 없음), 타이머 링도 `none`(정지), 글자·테두리 피드백은 그대로.
- [x] 맞는 코드 → `/admin` 셸(다크 1366px): 사이드바, 현재 위치 `selected` 채움, "준비 중" 3개, 아래 사용자 줄 + Admin 배지.
- [x] `Ctrl+K` → 팔레트(별도 청크 로드), "사"로 거르면 감사 로그(비활성 + 이유)·사용자·사전 고지, Enter → `/admin/users`.
- [x] 창 폭 1920·1280·1024 → 사이드바 240px, 800·640(높이 600) → 레일 56px. 다섯 폭 모두 `scrollWidth ≤ clientWidth`(가로 스크롤 없음). 640×600: 로그인 열과 코드 칸이 들어감, 레일 항목 hover → 툴팁 "세션 / 세션 화면은 아직 준비 중이에요."(레일 오른쪽), 명령 팔레트 512×350이 창 안(위 125px).
- [x] 원격(8701) 라이트: `/admin/mcps` → `/admin/login?redirect=%2Fadmin%2Fmcps`, 채널 배지 지구본 아이콘, 로그인 후 `/admin/mcps`로 돌아감.
- [x] 원격, Admin이라도 사용자·사전 고지·설정은 자물쇠 + 툴팁 "로컬 관리 모드(이 PC의 http://127.0.0.1:8700)에서만…". 처음에는 툴팁이 위쪽에 떠 화면 왼쪽 끝에 붙고 위 항목을 가림 → 내비 항목은 `side="right"`로 고침(`WithReason`에 `side` 선택 속성 추가).
- [x] `/admin/login?redirect=/`(보드의 로그인 링크) → 로그인 후 전체 페이지 이동으로 보드 `/`, 계정 메뉴 표시(F11).
- [x] 콘솔 오류: 일부러 틀린 코드의 `401 /api/auth/otp/verify` 두 줄뿐.

관찰(앱 문제 아님): 이 Playwright 창은 가려져 있어 rAF가 초당 약 1회로 묶였고, 그래서 View Transition이 1–2초 걸리거나 한 번은 "DOM update timed out"으로 건너뛰어졌습니다(전환 없이 바로 새 화면). 같은 시점 DOM은 이미 새 화면이었습니다. 보통 탭에서는 200ms입니다.

## 10. 자체 점검 뒤 고친 것 (audit-as-a11y-eng, audit-as-ux-eng)

- 세션이 끊겨(401) 로그인으로 오면 이유가 없었음 → 기록 상태 `flash: "expired"`로 `errors.login_required` 표시.
- 이메일 오류(빈 값·422) 때 포커스가 버튼에 남아 오류가 읽히지 않았음 → 입력칸으로 포커스(오류는 그 칸의 설명).
- 코드 5회 소진으로 칸이 비활성되면 포커스가 `<body>`로 떨어졌음 → "코드 다시 받기"로 포커스.
- 코드 칸 묶음이 어디로 보냈는지 말하지 않았음 → 묶음 `aria-describedby` = "…(으)로 인증 코드를 보냈어요" 문장.
