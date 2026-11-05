# 접근성 리뷰 — MCP Monitor 웹 UI (Plan 3 Task 16)

**기준:** WCAG 2.1 AA (+ 2.2 AA의 2.5.8 터치 대상 24px) · **날짜:** 2026-11-06 · **스킬:** `design:accessibility-review`, `audit-suite:audit-as-a11y-eng`

**입력:** Task 15 기준 이미지 14장(dark/light 7화면), 실제 백엔드에서 돌린 axe(WCAG 2.0/2.1/2.2 A·AA + best-practice), 화면마다 Tab 40–30번을 눌러 본 포커스 순서와 포커스 표시 확인, 대화형 요소 크기 측정, `aria-live`/`role=status` 목록, 640×400(1280px의 200%)·320×200(400%) 재배치, Task 6 대비 테스트(`tokens.contrast.test.ts`), `aria-disabled` 요소마다 설명(`aria-describedby`)이 있는지 확인. 측정은 모두 Playwright Chromium(실제 백엔드, `pnpm e2e`와 같은 시드)에서 했습니다.

**한계:** 실제 스크린 리더(NVDA·내레이터)로 듣지 않았습니다. "읽히는 것"은 접근성 트리(이름·역할·설명·live 영역)로 판단했습니다. 남은 위험 §6에 적었습니다.

## 1. 요약

| 구분 | 건수 |
|---|---|
| 점검 항목 | 32 |
| 통과(손대지 않음) | 23 |
| 고침 | 9 (Critical 0 · Major 3 · Minor 6) |
| 남은 위험 | 5 (모두 Minor, §6) |

자동 검사(axe)는 처음부터 위반 0건이었습니다. 고친 것은 모두 자동 검사가 못 잡는 종류였습니다: 포커스가 `<body>`로 떨어짐(2곳), 이유 없이 흐려진 버튼(4개 화면), 흐린 글자(팔레트), 셸 밖의 404, 400% 재배치, 24px 미만 대상.

## 2. 항목별 결과

### 인지 가능 (Perceivable)

| # | 항목 | WCAG | 결과 | 내용 |
|---|---|---|---|---|
| P1 | 상태를 색만으로 구분하지 않음 | 1.4.1 | 통과 | 배지·카드·요약 타일·필터 모두 아이콘 + 글자(`STATE_ICONS`). 스파크라인 색은 장식이고 값은 글자로 함께 있음 |
| P2 | 본문 대비 4.5:1, 큰 글자·UI 3:1 (두 테마) | 1.4.3, 1.4.11 | 통과 | Task 6 테스트가 모든 글자 토큰 쌍을 두 테마에서 검사(§3 표). 이번에 늘어난 쌍도 같은 토큰만 씀 |
| P3 | 명령 팔레트의 비활성 항목 | 1.4.3 | **고침 (Major)** | shadcn 기본 `opacity-50`이 이유 문장까지 흐리게 해 2.2–2.7:1이었습니다. 비활성은 글자를 `fg-muted`로, 아이콘만 60%로 바꿔 이유 문장이 6.3:1(강조 행 5.2:1)이 됩니다. 비활성 컨트롤 자체는 1.4.3 예외지만, 이유 문장은 읽어야 하는 정보입니다. `command.tsx` |
| P4 | 의미 구조(제목·랜드마크·목록·표) | 1.3.1 | **고침 (Minor)** | 모든 화면이 h1 하나 + h2/h3 순서, `header`·`nav[aria-label]`·`main` 랜드마크. 예외였던 404는 h1이 없고 셸 밖이었습니다 → 셸 안의 h1 "화면을 찾을 수 없어요" + 관리 화면 링크(P/O 공통, `router.tsx`) |
| P5 | 비텍스트 대체 | 1.1.1 | 통과 | 아이콘은 모두 `aria-hidden`, 아이콘만 있는 버튼은 `aria-label`. 차트는 제목·축 글자 + 같은 데이터의 표(상태 전이·조치 기록) |
| P6 | 확대 200% (1280px → 640 CSS px) | 1.4.4, 1.4.10 | 통과 | 13개 화면 모두 가로 페이지 스크롤 0, 사이드바는 아이콘 레일, 표는 자기 상자에서 스크롤. `layout.spec.ts` 640px 케이스가 고정 |
| P7 | 확대 400% (320 CSS px) | 1.4.10 | **고침 (Minor)** | MCP 상세 머리의 조치 버튼 묶음이 줄바꿈하지 않아 18px 가로 스크롤이 생겼습니다 → 머리(`md`) 크기에서 `flex-wrap`. 표 행(`sm`)은 그대로(표는 2차원 데이터라 1.4.10 예외, 자기 상자에서 스크롤). 새 E2E "reflows at 400% zoom" |
| P8 | 줄 간격·글자 간격 덮어쓰기 | 1.4.12 | 통과(코드 검토, 측정 안 함) | 여러 줄 글자를 담는 고정 높이 상자가 없습니다. 고정 높이는 한 줄짜리 컨트롤(버튼·입력 칸·내비 항목)뿐이고, 긴 이름은 줄바꿈(`break-all`)하거나 `truncate` + 전체 이름을 다른 곳(제목·툴팁)에 둡니다 |
| P9 | 움직임 줄이기 | 2.3.3(AAA, 참고) | 통과 | `prefers-reduced-motion`에서 CSS 전환·애니메이션·View Transition 꺼짐, Motion `reducedMotion="user"`. `motion.spec.ts`가 켜진 경우와 비교해 확인 |

### 조작 가능 (Operable)

| # | 항목 | WCAG | 결과 | 내용 |
|---|---|---|---|---|
| O1 | 로그인을 키보드로 | 2.1.1 | 통과 | 이메일 → Enter → 코드 칸이 스스로 포커스 → 6자리 입력 → 자동 제출. `a11y.spec.ts` "keyboard-only: login and run an action" |
| O2 | 수동 조치를 키보드로 | 2.1.1 | 통과 | 표 행 아이콘 버튼까지 Tab → Enter → 토스트. 같은 테스트 |
| O3 | 스크립트 저장을 키보드로 | 2.1.1, 2.1.2 | 통과 (테스트 추가) | 편집기는 Tab으로 들어가고 Tab으로 나옴(Tab 미바인딩, 키보드 함정 없음), Ctrl+S 저장. 새 E2E `scripts.spec.ts` "keyboard-only: … save with Ctrl+S" |
| O4 | 고지 저장을 키보드로 | 2.1.1 | 통과 (테스트 추가) | 제목 칸까지 Tab → 고치기 → 저장까지 Tab → Enter, Shift+Tab으로 되돌아가 한 번 더. 새 E2E `notice.spec.ts` "keyboard-only: edit the notice title and save it" |
| O5 | 명령 팔레트를 키보드로 | 2.1.1 | 통과 (테스트 추가) | Ctrl+K(한글 입력 상태에서도 `KeyK`) → 입력 → Enter. 막힌 화면은 열리지 않음. 새 E2E "keyboard-only: command palette …" |
| O6 | 단축키로 연 팔레트를 닫으면 포커스가 `<body>`로 | 2.4.3 | **고침 (Major)** | Task 9 이월. 아무것도 포커스가 없을 때 Ctrl+K로 열고 닫으면 Radix가 `<body>`로 돌려줘 다음 Tab이 페이지 맨 앞에서 시작했습니다. 이제 열 때 포커스가 있던 요소를 기억해 닫을 때 돌려주고, 없거나(또는 이동으로 사라졌으면) `#main`으로 보냅니다. `AppShell.tsx`, Vitest 2개 + E2E |
| O7 | 이유가 생기거나 사라질 때 컨트롤이 다시 마운트돼 포커스를 잃음 | 2.4.3 | **고침 (Major)** | `WithReason`이 이유 없을 때와 있을 때 다른 요소 트리를 돌려줘서, 저장 직후(저장 버튼에 "바뀐 내용 없음" 이유가 생김)나 조치가 시작될 때(버튼에 `running` 이유) 포커스된 버튼이 다시 만들어지고 포커스가 `<body>`로 떨어졌습니다. 키보드 고지 저장 E2E가 이것을 잡았습니다. 이제 트리가 항상 같아 같은 DOM 요소가 남습니다. 표 행 조치 버튼도 같은 컴포넌트 하나로 합쳤습니다. `WithReason.tsx`, `McpActions.tsx`, Vitest 2개 |
| O8 | 건너뛰기 링크 | 2.4.1 | 통과 | 보드·관리 셸 첫 Tab = "본문으로 건너뛰기" → `#main`(tabIndex −1). 로그인 화면은 머리에 링크 2개뿐이라 없음 |
| O9 | 포커스 표시 | 2.4.7 | 통과 | 전역 `:focus-visible` 2px 윤곽. Tab으로 지나간 모든 요소에서 윤곽 확인. 예외처럼 보인 CodeMirror 본문(`.cm-content`)은 바깥 상자가 `focus-within` 윤곽을 그림 |
| O10 | 대화상자 포커스 | 2.4.3 | 통과 | Radix가 가둠·Esc·복귀. 상태로 연 대화상자(종료 확인, 사용자 역할 변경, 보존 확인)는 `onCloseAutoFocus`로 직접 돌려줌. 고지 standalone은 네이티브 `showModal`(닫을 수 없음, 버튼에 포커스) |
| O11 | 터치 대상 24px 이상 | 2.5.8(2.2) | **고침 (Minor)** | 표 머리 정렬 버튼(22px)과 조치 기록의 "출력 보기" 버튼(18px)을 `min-h-6`(24px)으로. 스위치(36×20)와 문장 속 링크(대시보드 활동의 MCP 이름)는 간격·인라인 예외로 통과(axe `target-size` 통과). 영구 검사: a11y.spec의 axe에 `wcag22aa` 태그를 더함 |
| O12 | 404에서 돌아갈 길 | 2.4.5 | **고침 (Minor)** | 로그인한 사용자가 모르는 `/admin/*`로 오면 셸(내비게이션)이 그대로 있고 본문에 h1 + 버튼 모양 링크. 익명이면 로그인 뒤 같은 주소로. 새 Vitest 2개 + E2E |
| O13 | 시간 제한 | 2.2.1 | 통과 | 로그인 코드 재발송 대기(원형 타이머)는 사용자가 아닌 서버 제한을 보여줄 뿐이고, 코드 입력에는 시간 제한 화면이 없음(만료되면 다시 받기). 세션 만료는 초안을 지키고 돌아올 주소를 기억 |

### 이해 가능 (Understandable)

| # | 항목 | WCAG | 결과 | 내용 |
|---|---|---|---|---|
| U1 | 언어 | 3.1.1 | 통과 | 세 HTML 모두 `lang="ko"` |
| U2 | 라벨·안내 | 3.3.2 | 통과 | 모든 칸에 `<label for>`, 허용 범위·이름 규칙은 `aria-describedby`로 칸에 연결, 글자 수 카운터도 설명 |
| U3 | 오류 식별 | 3.3.1, 3.3.3 | 통과 | 칸 오류 = `aria-invalid` + 칸 아래 문장(무엇 + 어떻게). 서버 422는 폼 아래 `role=alert`. 409 `name_taken`/`endpoint_taken`은 해당 칸에 |
| U4 | 흐려진 버튼에 이유 | 3.3.2, 4.1.2 | **고침 (Minor)** | 저장·변경 취소는 바뀐 내용이 없으면 `aria-disabled`였지만 이유가 없었습니다(MCP 설정, 전역 설정, 스크립트, 고지 4곳). 새 이유 `deny.unchanged` "아직 바뀐 내용이 없어요."를 툴팁 + 설명으로. 권한 이유가 있으면 그쪽이 먼저. Vitest 4개 화면에 단언 추가 |
| U5 | 예측 가능 | 3.2.1, 3.2.2 | 통과 | 포커스·입력만으로 이동하지 않음. 실시간 값은 사용자가 고치지 않은 칸만 바꾸고 화면 위 문장으로 알림 |
| U6 | 일관된 식별 | 3.2.4 | 통과 | 같은 동작은 같은 이름(시작·다시 시작·종료, 저장·변경 취소), 같은 이유 문장(`copy.deny.*`) |

### 견고함 (Robust)

| # | 항목 | WCAG | 결과 | 내용 |
|---|---|---|---|---|
| R1 | 이름·역할·값 | 4.1.2 | 통과 | 토글 묶음 `aria-pressed`, 탭 `role=tab`, 표 `aria-sort`, 스위치 `role=switch`, 비활성 `aria-disabled` |
| R2 | 이유가 두 번 읽힘 | 4.1.2 | **고침 (Minor)** | Task 9 이월. 툴팁이 열려 있으면 Radix가 트리거의 설명에 툴팁 내용을 덧붙여 이유가 두 번 읽혔습니다. 툴팁 글자를 `aria-hidden`으로 바꾸고 이유는 늘 있는 숨긴 설명에서만 읽힙니다 |
| R3 | 상태 메시지 | 4.1.3 | 통과 | §4 표 |
| R4 | 이름에 보이는 글자 포함 | 2.5.3 | 통과 | Task 15가 계정 버튼을 고친 뒤 위반 없음 |

## 3. 대비 (Task 6 테스트 + 이번에 잰 쌍)

`tokens.contrast.test.ts`가 두 테마의 모든 글자 토큰 쌍, 상태 배지(soft 채움 위 글자, bg 위에 놓인 경우까지), diff 행, 포커스 링을 검사합니다. 아래는 이번 변경과 관련된 쌍을 같은 도구(culori, 반투명 토큰은 실제 배경에 합성)로 잰 값입니다.

| 요소 | 글자 | 배경 | dark | light | 기준 | 결과 |
|---|---|---|---|---|---|---|
| 본문 | `fg` | `bg` | 16.5 | 16.5 | 4.5 | 통과 |
| 팔레트 비활성 항목·이유(고친 뒤) | `fg-muted` | `surface-raised` | 6.4 | 6.3 | 4.5 | 통과 |
| 같은 항목, 키보드 강조 행 | `fg-muted` | `hover` / `surface-raised` | 5.2 | 5.4 | 4.5 | 통과 |
| 팔레트 이유(고치기 전, 50% 불투명) | `fg-muted` 50% | `surface-raised` | 2.7 | 2.2 | 4.5 | 실패 → 고침 |
| 주 버튼 | `accent-fg` | `accent` | 15.3 | 16.4 | 4.5 | 통과 |
| 포커스 링 | `focus` | `bg` | 13.3 | 12.1 | 3 | 통과 |
| 입력 칸 테두리 | `border-strong` | `surface` | 4.2 | 3.9 | 3 | 통과 |

흐려진(`aria-disabled`) 버튼의 글자는 50% 불투명이라 4.5:1이 안 되지만, 비활성 컨트롤은 1.4.3 예외이고 이유는 툴팁(반전 채움, 고대비)과 설명으로 따로 읽힙니다.

## 4. 스크린 리더로 읽히는 상태 변화 (접근성 트리 기준)

| 요소 | 읽히는 방식 | 판단 |
|---|---|---|
| 조치 토스트(Sonner) | `section[aria-live=polite]`(`aria-relevant="additions text"`)에 진행 → 완료/실패 문장이 들어감. 이 탭이 보낸 `run_id`만 | 통과 |
| 저장·되돌리기 토스트 | 같은 live 영역 | 통과 |
| 보드 판정 문장(h1) | `aria-live=polite` 안. "모든 MCP가 정상이에요" ↔ "n개 MCP에 문제가 있어요" | 통과 |
| SUSPECT 카운트다운 | `role=timer` + `aria-live=off`: 1초마다 읽지 않음(읽으면 다른 내용을 덮음). 카드에 포커스하면 남은 초를 읽음 | 통과 |
| 상태 배지 크로스페이드 | 120ms 동안 옛 배지와 새 배지가 한 칸에 겹침. live 영역이 아니므로 알리지 않음(보드는 판정 문장이 알림). 겹친 120ms에 읽으면 두 단어가 들림 | 남은 위험 §6-3 |
| 스트림 끊김·재연결 | 상단 바 `role=status` "다시 시도 중" | 통과 |
| 로딩 | 스켈레톤은 `aria-hidden`, 옆에 `role=status` + 숨긴 "불러오는 중" | 통과 |
| 초안 복원 띠 | `role=status` | 통과 |
| 폼 오류 | `role=alert` + 칸 `aria-invalid`/설명 | 통과 |

## 5. 키보드 경로

| 경로 | Tab 순서 | Enter/Space | Esc | 화살표 | 테스트 |
|---|---|---|---|---|---|
| 보드 | 건너뛰기 → 브랜드 → 테마 → 로그인 | 링크·버튼 | — | 테마 메뉴 | axe + layout |
| 로그인 | 브랜드 → 테마 → 이메일 → 코드 받기 → (코드 칸 자동 포커스) | 제출 | — | 코드 칸 좌우 | a11y.spec |
| 관리 셸 | 건너뛰기 → 브랜드 → 테마 → 계정 → 빠른 이동 → 내비 8개(막힌 것도 포커스, 이유 툴팁) → 본문 | 이동 | 메뉴 닫기 | 메뉴 | a11y.spec |
| MCP 목록 | 등록 → 상태 필터 7개 → 정렬 머리 4개 → 행: 이름 링크 → 시작·다시 시작·종료 | 정렬·조치(종료는 확인) | 확인 닫기 → 종료 버튼 | — | a11y.spec |
| MCP 상세 | 조치 → 소유권 이전 → 삭제 → 탭(화살표) → 탭 패널 → 칸들 → 저장·변경 취소 | | 대화상자 | 탭 목록 | detail.test |
| 스크립트 | 종류 토글 → 확장자 → 편집기(Tab으로 나감) → 저장 → 버전 목록 | Ctrl+S 저장 | — | — | scripts.spec(새) |
| 고지 | 제목 → 굵게·목록 → 본문 → 버튼 문구 → 저장 → 전체 화면 미리보기 → 버전 목록 | 저장 | — | — | notice.spec(새) |
| 명령 팔레트 | Ctrl+K → 입력 → 결과 | 이동(막힌 화면은 무시) | 닫기 → 연 요소 또는 `#main` | 결과 이동 | a11y.spec(새) |

## 6. 남은 위험

1. **실제 스크린 리더 미확인** — 접근성 트리로 판단했습니다. Plan 4 WebView2 고지와 함께 NVDA·내레이터로 한 번 들어 보는 것을 권합니다(특히 토스트 진행 → 완료가 한 번씩만 읽히는지).
2. **스위치 20px 높이** — 2.5.8 간격 예외로 통과하고 라벨 행 전체가 누름 영역이지만, 스위치 자체는 24px보다 작습니다. 크기를 바꾸면 모든 폼의 리듬이 바뀌어 이번에는 두었습니다.
3. **배지 크로스페이드 120ms 겹침** — 그 순간 가상 커서로 읽으면 두 상태 단어가 들립니다. 알림이 아니므로 영향은 작습니다.
4. **400%(320px)는 가로 스크롤만 검사** — 사용자 결정(2026-11-05)으로 640px 아래는 전용 레이아웃이 없습니다. 내용은 모두 닿지만 촘촘합니다(표는 자기 상자에서 스크롤).
5. **고지 standalone의 Tab** — 네이티브 `showModal`은 Tab이 브라우저 UI(주소창)로 나갈 수 있습니다(명세 동작, 뒤 페이지는 inert). Plan 4 WebView2 호스트에는 브라우저 UI가 없습니다(Task 14 보고).

## 7. 고친 파일과 테스트

- `web/src/components/ui/command.tsx` — 비활성 항목 스타일, `onCloseAutoFocus` 전달.
- `web/src/admin/shell/AppShell.tsx`, `CommandPalette.tsx` — 팔레트 포커스 복귀.
- `web/src/components/app/WithReason.tsx` — 같은 요소 트리, `label`만 있는 툴팁, 툴팁 글자 `aria-hidden`.
- `web/src/admin/mcps/McpActions.tsx` — `WithReason` 하나로, 머리 크기에서 줄바꿈.
- `web/src/admin/router.tsx` — 셸 안 404(`authedRoute.notFoundComponent`), h1.
- `web/src/admin/mcps/SettingsTab.tsx`, `settings/SettingsPage.tsx`, `scripts/ScriptEditor.tsx`, `notice/NoticeEditorPage.tsx` — `unchanged` 이유.
- `web/src/admin/mcps/McpListPage.tsx`, `HistoryTab.tsx` — 24px 대상.
- `web/src/copy/ko.ts` — `deny.unchanged`, `common.notFoundTitle`, `common.notFound` 문장 다듬기.
- Vitest: `shell.test.tsx`(+3), `status.test.tsx`(+2, 1개 보강), `detail.test.tsx`·`settings.test.tsx`·`scripts.test.tsx`·`notice-editor.test.tsx`(이유 단언), `ko.test.ts`.
- E2E: `a11y.spec.ts`(axe `wcag22aa`, 404 화면 axe, 팔레트 키보드, 404), `layout.spec.ts`(400%), `scripts.spec.ts`·`notice.spec.ts`(키보드 저장), `fixtures.ts`(`tabTo` 공유, Shift+Tab).
