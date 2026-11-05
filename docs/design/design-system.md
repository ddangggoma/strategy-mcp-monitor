# 디자인 시스템 — MCP Monitor 웹 UI

Task 6 산출물(`design:design-system` 스킬). 방향과 근거는 `docs/design/direction.md`. 이 문서는 **무엇을 어떻게 쓰는지**의 기준입니다.

파일:
- `web/src/styles/tokens.css` — 원색(OKLCH)과 역할 토큰(`light-dark()`). **색 값을 쓸 수 있는 유일한 파일.**
- `web/src/styles/base.css` — 요소 기본값, 포커스, 글꼴 import, 테마 전환 가드, View Transition, 상단 바 그림자, reduced motion.
- `web/src/styles/app.css` — 세 번들의 엔트리 CSS. 레이어 순서, Tailwind import, `@theme inline reference` 매핑.
- `web/src/components/ui/*` — shadcn 기반 컴포넌트(우리 토큰으로 다시 씀).
- `web/src/copy/ko.ts` — 모든 화면 문구.

## 1. 토큰

### 1.1 규칙

- 컴포넌트는 역할 토큰만 씁니다(`bg-surface`, `text-fg-muted`, `border-border-strong`, `bg-state-failed-soft` …). 원색(`--steel-*`, `--green-*` …)은 `tokens.css` 안에서만.
- Tailwind 기본 팔레트·글꼴·글자 크기·반경·그림자·이징은 `app.css`에서 비웁니다. `bg-red-500`, `text-white`, `rounded-xl` 같은 클래스는 **아무 CSS도 만들지 않습니다.**
- `dark:` 변형을 쓰지 않습니다. 모든 역할 토큰은 `light-dark()`라서 테마가 바뀌면 스스로 바뀝니다.
- 테마: `:root { color-scheme: light dark }`(OS 따르기), `<html data-theme="dark|light">`로 고정(`lib/theme.ts`, localStorage `mcpmon.theme`).
- 새 토큰을 더하면 `app.css`의 `@theme inline reference`에도 같은 이름으로 한 줄 더합니다.

### 1.2 색 (light / dark)

| 토큰 | Light | Dark | 용도 |
|---|---|---|---|
| `--color-bg` | steel-50 `oklch(0.972 0.004 255)` | steel-950 `oklch(0.205 0.012 255)` | 페이지 배경 |
| `--color-surface` | steel-0 `oklch(0.995 0.002 255)` | steel-900 `oklch(0.235 0.013 255)` | 패널·카드·입력칸 |
| `--color-surface-raised` | `oklch(1 0 0)` | steel-850 `oklch(0.27 0.014 255)` | 메뉴·팝오버·대화상자·토스트 |
| `--color-sunken` | steel-100 `oklch(0.945 0.006 255)` | steel-1000 `oklch(0.18 0.011 255)` | 읽기 전용 입력, 코드 뷰어, 탭 목록 바탕 |
| `--color-border` | steel-200 `oklch(0.9 0.009 255)` | steel-800 `oklch(0.31 0.015 255)` | 장식 헤어라인(묶기). 3:1 대상 아님 |
| `--color-border-strong` | steel-500 `oklch(0.6 0.018 255)` | steel-500 | 입력칸·outline 버튼·스위치 트랙(3:1) |
| `--color-fg` | steel-950 | steel-50 | 본문 |
| `--color-fg-muted` | steel-600 `oklch(0.49 0.018 255)` | steel-400 `oklch(0.735 0.016 255)` | 보조 글자, placeholder, 표 머리. 보드 문제 카드(soft 채움) 위에서도 4.5:1 (Task 8에서 0.72 → 0.735) |
| `--color-accent` | steel-900 | steel-100 `oklch(0.945 0.006 255)` | 주 버튼·켜진 스위치(반전 채움) |
| `--color-accent-fg` | steel-0 | steel-950 | accent 위 글자 |
| `--color-hover` | `color-mix(in oklch, fg 7%, transparent)` | 같음 | hover 채움 |
| `--color-selected` | `color-mix(in oklch, fg 11%, transparent)` | 같음 | 선택·보조 채움, `::selection` |
| `--color-focus` | steel-800 `oklch(0.31 0.015 255)` | steel-200 `oklch(0.9 0.009 255)` | 포커스 링 |
| `--color-danger` | red-600 `oklch(0.55 0.2 25)` | red-400 `oklch(0.71 0.17 22)` | 파괴적 버튼 채움, 필드 오류 글자 |
| `--color-danger-fg` | steel-0 | steel-1000 | danger 위 글자 |
| `--color-scrim` | `oklch(0.2 0.012 255 / 0.4)` | `oklch(0.12 0.01 255 / 0.6)` | 모달 뒤 막 |
| `--color-state-healthy` | green-600 `oklch(0.55 0.14 152)` | green-400 `oklch(0.76 0.15 152)` | 정상 아이콘·선 |
| `--color-state-healthy-fg` | green-800 `oklch(0.37 0.09 152)` | green-200 `oklch(0.9 0.08 152)` | 정상 배지 글자 |
| `--color-state-suspect` | amber-600 `oklch(0.6 0.124 75)` | amber-400 `oklch(0.83 0.15 85)` | 이상 감지 |
| `--color-state-suspect-fg` | amber-800 `oklch(0.4 0.08 70)` | amber-200 `oklch(0.92 0.09 88)` | |
| `--color-state-action` | orange-600 `oklch(0.58 0.16 45)` | orange-400 `oklch(0.75 0.16 52)` | 조치 중 |
| `--color-state-action-fg` | orange-800 `oklch(0.4 0.11 45)` | orange-200 `oklch(0.9 0.058 55)` | |
| `--color-state-recovering` | cyan-600 `oklch(0.56 0.1 220)` | cyan-400 `oklch(0.79 0.12 212)` | 복구 중 |
| `--color-state-recovering-fg` | cyan-800 `oklch(0.38 0.07 225)` | cyan-200 `oklch(0.91 0.06 210)` | |
| `--color-state-failed` | red-600 `oklch(0.55 0.2 25)` | red-400 `oklch(0.71 0.17 22)` | 실패 |
| `--color-state-failed-fg` | red-800 `oklch(0.4 0.14 25)` | red-200 `oklch(0.9 0.048 22)` | |
| `--color-state-maintenance` | slate-600 `oklch(0.53 0.04 255)` | slate-400 `oklch(0.73 0.04 255)` | 점검 중 |
| `--color-state-maintenance-fg` | slate-800 `oklch(0.37 0.035 255)` | slate-200 `oklch(0.89 0.025 255)` | |
| `--color-state-*-soft` | `color-mix(in oklch, var(--color-state-*) 18%, transparent)` | 같음 | 배지·비정상 카드 채움 |

**검증(`tokens.contrast.test.ts`, 두 테마):**
- 텍스트 4.5:1 — `fg`·`fg-muted`를 `bg`/`surface`/`surface-raised` 위에, `accent-fg`/`accent`, `danger-fg`/`danger`, `danger`를 세 면 위에, `state-*-fg`를 `state-*-soft`(surface와 bg 위에 합성) 위에.
- UI 3:1(WCAG 1.4.11) — `border-strong`, `focus`, `state-*`를 세 면 위에. `border`는 장식이라 제외하고, `border-strong`보다 약하되 보이는지(>1.1:1)만 검사합니다(preflight F27).
- 모든 색 토큰이 sRGB 안(브라우저마다 같은 색).
- 측정치(최저): 라이트 `fg-muted`/bg 5.77, `state-suspect`/bg 3.72, 배지 글자 6.89; 다크 `fg-muted`/raised 6.08, `border-strong`/surface 4.23, 배지 글자 8.76.

### 1.3 글자

| 토큰 | 값 |
|---|---|
| `--font-sans` | "Pretendard Variable", Pretendard, "Segoe UI Variable Text", "Segoe UI", "Malgun Gothic", "Apple SD Gothic Neo", system-ui, sans-serif |
| `--font-mono` | "JetBrains Mono Variable", "Cascadia Mono", Consolas, "D2Coding", ui-monospace, monospace |
| `--font-weight-{normal,medium,semibold,bold}` | 400 / 500 / 600 / 700 |
| `--text-xs` … `--text-2xl` | 12/18, 14/22, 16/26, 18/28, 22/30, 28/36 (px, 크기/행간) |
| `--text-metric` | `clamp(1.75rem, 1.2rem + 1.4vw, 2.5rem)` / 1.05 / -0.02em |
| `--text-display` | `clamp(2rem, 1.2rem + 2.6vw, 3.5rem)` / 1.12 / -0.025em |

글꼴은 npm(`pretendard` 1.3.9의 dynamic-subset CSS, `@fontsource-variable/jetbrains-mono` 5.3.0의 `wght.css`)에서 번들, 둘 다 SIL OFL 1.1.

### 1.4 간격·크기·반경·그림자·층·모션

| 토큰 | 값 | 용도 |
|---|---|---|
| `--spacing` | 0.25rem | Tailwind `p-4` = 16px 등 |
| `--size-control` / `-sm` | 36px / 28px (터치: 44 / 36) | 버튼·입력 높이 |
| `--size-topbar` / `--size-sidebar` / `--size-rail` | 3.5rem / 15rem / 3.5rem | 셸(레일 = 창 폭 1024px 미만에서 접힌 사이드바) |
| `--size-board-card` | 19rem | 보드 카드 최소 폭 |
| `--size-prose` | 40rem | 폼·고지 본문 폭 |
| `--radius-xs/sm/md/lg/full` | 3 / 4 / 6 / 10px / 9999px | kbd / 배지·입력 / 버튼·카드·메뉴 / 대화상자·고지 / 점·스위치 |
| `--shadow-xs…lg` | `--shadow-color` 기반 | 떠 있는 층만(md = 메뉴, lg = 대화상자) |
| `--z-sticky/modal/popover/toast/tooltip` | 10 / 50 / 60 / 70 / 80 | 고정 척도(임의 z-index 금지). 팝오버(Select·메뉴)는 대화상자 안에서도 열리므로 modal 위(Task 11) |
| `--focus-ring-width/offset` | 2px / 2px | 전역 `:focus-visible` |
| `--motion-fast/base/slow` | 120 / 200 / 360ms | direction.md §6 |
| `--ease-out` / `--ease-in-out` / `--ease-hover` | `cubic-bezier(.23,1,.32,1)` / `cubic-bezier(.77,0,.175,1)` / `ease` | 들고 남 / 화면 위 이동 / 색 피드백 |

Tailwind 기본 전환(`transition-colors` 등)도 `--motion-fast` + `--ease-hover`를 씁니다.

## 2. 컴포넌트

공통 규칙:
- **포커스:** 컴포넌트가 따로 링을 그리지 않습니다. 전역 `:focus-visible { outline: 2px solid var(--color-focus); outline-offset: 2px }` 하나. 메뉴 항목·cmdk 항목만 강조 채움(`bg-hover`)이 포커스 표시입니다(`outline-hidden`).
- **비활성:** 권한 때문에 못 쓰는 컨트롤은 `disabled`가 아니라 `aria-disabled="true"` + 클릭 무시 + 이유 툴팁(U26). Button·Switch는 `aria-disabled:` 스타일을 갖고 포커스를 받습니다.
- **전환 속성은 이름으로**(`transition-all` 금지). 움직이는 요소는 `data-anim`을 답니다.
- **아이콘**은 `aria-hidden="true"`, 아이콘만 있는 버튼은 `aria-label`(문구는 `ko.ts`).
- **문구**는 컴포넌트에 직접 쓰지 않고 `copy.*`에서 가져옵니다.

### 2.1 shadcn 기반 (`web/src/components/ui`)

| 컴포넌트 | 변형·크기 | 상태 | 접근성 메모 |
|---|---|---|---|
| `Button` | `default`(반전 채움), `outline`(border-strong), `secondary`(hover 채움), `ghost`, `destructive`(danger), `link` · `default` 36px, `xs`, `sm` 28px, `lg` 44px, `icon*` | hover(채움 85%/hover 토큰), press `scale(.98)`, `disabled`, `aria-disabled`(포커스 유지) | 기본 `type="button"`(폼 실수 제출 방지). `asChild`로 링크 |
| `Badge` | `default`, `secondary`, `outline`, `destructive`, `ghost`, `link` | — | 중립 정보(역할·채널·개수)용. 상태에는 `StatusBadge` |
| `Card` | Header / Title / Description / Action / Content / Footer | — | 그림자 없음, 헤어라인, 16px 안쪽 여백 |
| `Dialog` | 닫기 버튼 선택(`showCloseButton`) | 진입 fade + zoom-in-95, 200ms ease-out(막과 같음) | Radix 포커스 가둠·Esc, 닫기 `aria-label=copy.common.close`, 왼쪽 정렬, 긴 내용 스크롤(`overscroll-contain`) |
| `AlertDialog` | `size` default/sm, `AlertDialogMedia` | Dialog와 같은 클래스(`dialogPanelClass`) | 파괴적 확인은 동작 이름 버튼(“MCP 삭제”) + 취소 |
| `DropdownMenu` | Item(`variant=destructive`), Checkbox/Radio Item, Sub | 120ms 진입, 항목 강조 `bg-hover` | 키보드 화살표·타입어헤드(Radix) |
| `Tooltip` | — | 400ms 지연, 열린 뒤 300ms 동안 즉시(warm) | 반전 채움(fg 위 bg 글자), 이유 안내용 |
| `Popover` | Header / Title / Description | 120ms | |
| `Tabs` | `default`(분절), `line`(밑줄) | 선택 = raised 채움 / 밑줄 | 관리 상세 탭은 `line` 권장 |
| `Input` / `Textarea` | — | hover border fg-muted, `aria-invalid` → border danger, read-only → sunken | 터치 기기에서 16px 이상(iOS 확대 방지, base.css) |
| `Label` | — | peer/group disabled | `htmlFor` 필수 |
| `Select` | trigger `default`/`sm` | Input과 같은 경계 | Radix listbox |
| `Switch` | `default`, `sm` | 꺼짐 border-strong, 켜짐 accent, 썸 surface | 라벨 행 전체가 누름 영역 |
| `Table` | Header/Body/Row/Head/Cell/Caption | 행 hover 채움, **전환 없음** | `tabular-nums`, 머리 12px muted |
| `Separator` | 가로/세로 | — | 기본 장식(`decorative`) |
| `Skeleton` | — | `animate-pulse`, `data-anim="pulse"` | `aria-hidden` |
| `Sonner`(`Toaster`) | success/info/warning/error/loading 아이콘 | raised 면, 아이콘이 상태 색 | 결과는 아이콘 + 글자. `aria-live`는 Sonner 기본 |
| `Command` / `CommandDialog` | Input/List/Empty/Group/Item/Shortcut | 선택 항목 `bg-hover` | 제목·설명(`copy.common.commandTitle/Hint`)이 Content 안에 있어 대화상자 이름이 됨. admin 지연 청크 전용 |
| `Form` | Item/Label/Control/Description/Message | 오류 → label·message danger | react-hook-form 연결, `aria-describedby`·`aria-invalid` 자동 |

### 2.2 이 계획의 앱 컴포넌트

| 컴포넌트 | 과제 | 메모 |
|---|---|---|
| `app/ThemeToggle` | **6(완료)** | 상단 바 고스트 아이콘 버튼 + 라디오 메뉴(시스템 설정/어둡게/밝게). 트리거 이름에 현재 값(“화면 테마(지금: 시스템 설정)”) |
| `status/StatusBadge` | 8 | 아이콘 + `copy.states` 글자, `bg-state-*-soft text-state-*-fg`, 크로스페이드 120ms |
| `status/CountdownBar` | 8 | `transform: scaleX()` + `--gauge-from`, `ease-linear`(시간 표시), `data-anim`·`data-volatile` |
| `status/Sparkline` | 8 | 직접 그린 SVG(U18), HEALTHY는 `fg-muted`, 비정상은 상태 색, `data-volatile` |
| `board/McpCard` | 8 | subgrid 4행, 컨테이너 쿼리, 비정상만 상단 3px 띠 + soft 채움, `data-testid="mcp-card"` |
| `app/TopBar`, `ChannelBadge`, `StreamIndicator`, `AccountMenu` | 8·9 | `data-topbar`(스크롤 그림자는 base.css) |
| `admin/shell/AppShell`, `Nav`, `CommandPalette`, `PlannedFeature`, `app/WithReason`(`side` 선택) | 9 | 비활성 + 이유(U26). `LocalOnlyPage`는 Task 13 행 |
| `admin/auth/OtpInput`, `ResendRing` | 9 | 6칸, 흔들림 피드백, 원형 타이머(U25 예외). docs/design/screens/auth-shell.md |
| `admin/mcps/McpActions` | **10(완료)** | md = 아이콘 + 글자 버튼, sm(표 행) = 28px 아이콘 버튼 + `aria-label`·툴팁. 비활성 순서 권한 → running → config_error. 종료는 AlertDialog. docs/design/screens/mcp.md |
| `admin/mcps/McpListPage` 표, `dashboard/DashboardPage` | **10(완료)** | TanStack Table v9, `aria-sort`, 이름 칸 `th scope=row`, 조치 열 sticky, 포인터가 본문에 있으면 행 순서 고정. 표에는 애니메이션 없음 |
| `admin/mcps/McpDetailPage`, `SettingsTab`, `HistoryTab`, `LatencyChart`, `ActionOutputDialog`, `OwnerTransferDialog`, `DeleteMcpDialog`, `ConfigErrorBadge`, `shell/LeaveGuard` | **11(완료)** | 폼 = shadcn Form + zod(`mcp-schema.ts`), 숫자 칸은 숫자 또는 빈 문자열. 차트 = 두 플롯(지연 ms / 가동률 %) + 공유 시간축, 중립 선 + 상태 색 전이선, 애니메이션 없음, 별도 청크. 대화상자는 자기 트리거를 가짐(Radix가 포커스 복귀). docs/design/screens/mcp.md §6·§10 |
| `scripts/ScriptsTab`, `ScriptEditor`(+`ScriptField`), `ScriptViewer`, `VersionList`, `app/TextDiff`, `mcps/McpCreatePage`, `McpConfigFields` | **12(완료)** | CodeMirror 6 = 지연 청크 하나(스크립트 탭과 등록 폼이 공유), 테마는 토큰 변수, 문법 강조에 hue 없음, Tab 미바인딩. 읽기 전용은 `<pre>`(sunken) + 복사. diff = 표, +/− 기호 + `diff-add`/`diff-del` 틴트(surface 위), 애니메이션 없음. 초안 `lib/draft.ts`(sessionStorage, 로그아웃 때 모두 지움). docs/design/screens/mcp.md §6·§11 |
| `users/UsersPage`, `settings/SettingsPage`, `RetentionSection`(+`RetentionConfirm`), `NumberField`, `shell/LocalOnlyPage` | **13(완료)** | 사용자 표: 행 머리 = 이름만, 역할 Select·활성 Switch는 행 안에서 바로, 바꾸면 AlertDialog(결과를 말하는 제목, 로그아웃 안내), 활성화만 확인 없음. 마지막 활성 Admin = `aria-disabled` + 역할 칸 아래 보이는 이유(두 컨트롤의 설명). 설정 = MCP 설정과 같은 fieldset 묶음 한 폼, 바뀐 칸만 PUT(보존 두 값은 함께). 보존을 줄이면 미리보기 AlertDialog(기간·파일 수·용량을 `text-lg` 숫자로, 이 화면군의 한 가지 대담함). 공유 오류 = 두 칸 `aria-invalid` + 한 번만 보이는 문장. `LocalOnlyPage` = 제목 + 자물쇠 한 문장, 자식(쿼리) 렌더링 안 함. 상태로 연 대화상자는 닫힐 때 포커스를 직접 돌려줌. docs/design/screens/admin-settings.md |
| `notice/NoticeDialog` | 14 | `@starting-style` 진입(360ms), standalone/preview 같은 클래스 |

## 3. 문구 (`web/src/copy/ko.ts`, `design:ux-copy`)

- **목소리:** 해요체. 짧고 능동형. 사과("죄송합니다")·느낌표 없음. 오류는 무슨 일 + 다음 행동("…요청이 너무 잦아요. 잠시 뒤에 다시 시도하세요.").
- **버튼:** 동작 이름. "확인"은 고지 버튼(사양 고정)과 정보성 대화상자에만. 파괴적 확인은 결과를 말하는 이름("MCP 삭제", "줄이고 삭제").
- **토스트:** 진행 `… 중…`, 끝 `… 완료` / `… 실패` — 이름 뒤에 조사를 붙이지 않아 영문 MCP 이름에도 어색하지 않습니다.
- **권한 이유:** "…만 쓸 수 있어요" 꼴로 끝나고, Local 전용은 주소(`http://127.0.0.1:8700`)를 함께 줍니다. 예정 기능은 "아직 준비 중이에요".
- **로그인:** 등록 여부를 드러내지 않습니다("등록된 이메일이면 … 보냈어요"). 잠금 규칙(1시간에 10번, 최대 1시간), 코드 5번 오류 무효를 숫자로 말합니다.
- **사전 고지 기본 문구:** 공식 안내문이라 합니다체. `server/app/notice/defaults.py`와 `ko.ts`의 `notice.builtIn`이 같아야 하며 `ko.test.ts`가 비교합니다.
- **타이포:** 말줄임표는 `…`, 따옴표는 “ ”, 범위는 en dash(7–3,650일). `ko.test.ts`가 `...`, 곧은 따옴표, `!`, 사과 표현을 막습니다.
- **고정 용어**(테스트가 씀): 역할, 채널, 상태 6종, 이슈 4종 — 바꾸지 않습니다.

## 4. 하드코딩 값 점검 (2026-11-05)

`rg`가 없어(preflight F22) git grep으로 같은 패턴을 돌렸습니다(추적되지 않은 새 파일 포함):

```
git grep --untracked -nE "#[0-9a-fA-F]{3,8}\b|rgb\(|oklch\(" -- web/src ':!web/src/styles/tokens.css'
```

결과 3줄, **색 값 0건**:
- `web/src/styles/contrast-helpers.ts:146,147` — 함수 이름 `toRgb(`(culori 변환기, 색 값 아님).
- `web/src/styles/hardcoded-values.test.ts:53` — 검사기가 잡아야 하는 나쁜 예(테스트 데이터).

같은 점검을 테스트로 고정했습니다: `web/src/styles/hardcoded-values.test.ts`가 `web/src`의 모든 `.ts/.tsx/.css`(테스트 제외)에서 ① `tokens.css` 밖의 색 리터럴(hex, rgb/hsl, oklch/oklab/lab/lch), ② shadcn 기본 이름(`bg-background`, `text-muted-foreground` …)·Tailwind 팔레트 클래스·`dark:` 변형을 막습니다. 패턴이 실제로 잡는지도 같은 파일에서 확인합니다.

| 범주 | 정의된 토큰 | 하드코딩 발견 |
|---|---|---|
| 색 | 원색 38개, 역할 34개 | 0 |
| 간격·크기 | `--spacing` + 크기 7개 | 0 (shadcn 내부의 `h-6`, `px-2.5` 등은 4px 격자 배수) |
| 글자 | 글꼴 2, 굵기 4, 크기 8 | 0 (Tailwind 기본 크기 비움) |
| 반경·그림자·층·모션 | 5 / 4 / 5 / 6 | 0 (임의 z-index 없음) |
