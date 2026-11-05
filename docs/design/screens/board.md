# 화면 설계 — 상태 보드 (`board` 번들)

Task 8 산출물. `frontend-design` 스킬로 `docs/design/direction.md`(고성능 HMI 관제 콘솔)를 보드 화면에 적용했고, 차트 모양은 `dataviz` 스킬을 먼저 읽고 정했습니다. 모션은 audit-suite `web-animation-design`·`emil-design-engineering`, React 구조는 `vercel-react-best-practices`를 따릅니다. 토큰·컴포넌트 규칙은 `docs/design/design-system.md`.

## 1. 일과 시선 순서

보드는 로그인하지 않은 동료도 보는 첫 화면이고, 벽면 모니터에 띄워 방 건너편에서 읽힙니다. 답할 질문은 두 개입니다: **"누가 접속해 있나"**, **"망가진 MCP가 있나"**.

시선 순서(위 → 아래, 왼쪽 → 오른쪽):

1. **접속 배너** — `● 접속 중`(펄스) / `○ 접속자 없음` / 수집 전 안내(중립). 접속자가 있으면 바로 아래에 접속자 카드.
2. **판정 문장** — `text-display`, 가장 나쁜 상태의 `-fg` 색 + 그 상태 아이콘. "MCP 2개에 문제가 있어요" / "모든 MCP가 정상이에요" / "MCP 1개가 점검 중이에요". 이 화면의 유일한 대담한 요소입니다. `aria-live="polite"`라 상태가 바뀌면 화면 낭독기가 읽습니다.
3. **문제 MCP** — 심각도순(FAILED → ACTION → SUSPECT → RECOVERING, U17). 상단 3px 상태 띠 + soft 채움 + 상태 색 스파크라인.
4. **정상 MCP** — MAINTENANCE, HEALTHY. 중립 패널, 작은 초록 아이콘, 회색 스파크라인. 조용합니다.

로컬 채널에서 초기 설정이 필요하면(`GET /api/bootstrap` → `needed`) 1번 위에 안내 한 줄과 `/admin/setup` 링크가 붙습니다. 원격 채널에서는 그 API를 부르지 않습니다.

## 2. 배치

### 2.1 1920×1080 벽면

```
┌ 상단 바 56px(sticky) ───────────────────────────────────────────────────────────┐
│ MCP Monitor  [▣ 로컬 관리 모드]         (재연결 3초+: ⟳ 실시간 연결 다시 시도 중) ◐ [로그인] │
└──────────────────────────────────────────────────────────────────────────────────┘
 32px 여백
 ● 접속 중                                                       ← 배너(text-lg)
 ┌ hong (CORP) ───────────────────────────────┐                   ← 접속자 카드 그리드
 │ 클라이언트 PC HONG-PC   IP 10.0.3.21         │                     (minmax(24rem,1fr))
 │ 역방향 DNS —   접속 14:03:22   경과 1분 12초 │
 │ 상태 Active   유휴 0초   해상도 1920x1080   │
 │ 고지 확인 확인함                             │
 └─────────────────────────────────────────────┘
 ⊗ MCP 2개에 문제가 있어요                                        ← 판정(display 56px)
 ┌━━━━━━━━━━━━━━━━━━┐┌━━━━━━━━━━━━━━━━━━┐┌──────────────────┐┌──────────────────┐┌──…
 │ seoul-weather [⊗실패]││ calc   [⚠이상 감지]││ files    [✓정상]  ││ notes   [✓정상]  ││
 │ 프로세스 중지          ││ 응답 없음           ││                  ││                  ││
 │ 지연 —   가동률 91.2% ││ 지연 842 가동 99.1% ││ 지연 12  가동 100%││ …                ││
 │ ╱╲╱┄┄┄┄ (상태 색)     ││ ╱╲╱╲╱ (상태 색)    ││ ╱╲╱╲ (회색)       ││                  ││
 │                       ││ ▓▓▓▓▓▓░░ 23초 뒤 자동 조치││                  ││                  ││
 │ 마지막 점검 3초 전     ││ 마지막 점검 1초 전   ││ …                ││                  ││
 └───────────────────────┘└────────────────────┘└──────────────────┘└──────────────────┘
```

- 본문 폭 제한 없음(벽면은 넓게 씀), 좌우 여백 32px. 카드 그리드 `repeat(auto-fill, minmax(var(--size-board-card) /*19rem*/, 1fr))` → 1920px에서 5열.
- 카드 행은 **subgrid** 5줄(머리 · 이슈 · 지표 · 차트/게이지 · 바닥). 같은 줄의 카드끼리 이름이 두 줄이 되어도 지표·스파크라인이 같은 높이에 섭니다. 미지원 브라우저는 일반 grid(카드마다 자기 높이).
- 지표 숫자는 `text-metric`(40px까지 유동), 라벨은 `text-xs fg-muted`. 숫자는 `tabular-nums`.

### 2.2 1366×768 노트북

- 같은 구조, 여백 24px, 카드 3–4열. 판정 문장은 유동 크기로 약 40px.
- 첫 화면에 배너 + 판정 + 카드 첫 줄이 들어옵니다(문제 MCP가 첫 줄에 오므로 스크롤 없이 문제를 봄).

### 2.3 360px 휴대폰

- 여백 16px, 카드 1열(`minmax(min(19rem, 100%), 1fr)`), 접속자 카드도 1열.
- 상단 바: 제품명 · 채널 배지(아이콘만, 글자는 `sr-only`) · 테마 · 로그인. 재연결 안내는 아이콘 + 짧은 글자로 줄바꿈 없이.
- 카드 내부는 **컨테이너 쿼리**: 카드 폭 < 22rem이면 지표(지연·가동률)를 2열 그대로 두되 숫자 크기를 `text-2xl`로 낮춤. 정의 목록(`dl`)은 라벨 위·값 아래.
- 터치 기기에서 버튼·메뉴 항목 44px(tokens.css `pointer: coarse`).

## 3. 카드 모습 (상태별)

공통: 이름(`text-lg semibold`, 줄바꿈 허용), 오른쪽 위 `StatusBadge`(아이콘 + 글자, soft 채움), 지연(`RollingNumber`, ms), 24시간 가동률(`UptimeMeter`, 소수 1자리 %), 스파크라인(최근 60점), 마지막 점검(상대 시간, `title`·`dateTime`에 KST). **호스트·포트·소유자는 보드에 표시하지 않습니다**(익명 화면, carry-forward). direction.md §5 와이어프레임의 `127.0.0.1:9101` 줄은 이 결정으로 빠집니다.

| 상태 | 띠·채움 | 스파크라인 | 추가 표시 |
|---|---|---|---|
| HEALTHY | 없음(중립 패널, 헤어라인) | `fg-muted` | — |
| SUSPECT | 3px amber 띠 + amber soft | amber | 이슈 글자. `action_in_sec`이 있으면 카운트다운 게이지 + "N초 뒤 자동 조치" |
| ACTION | 3px orange 띠 + soft | orange | 이슈, "스크립트 실행 중: 다시 시작"(`running`) |
| RECOVERING | 3px cyan 띠 + soft + **회전 테두리** | cyan | 이슈(있으면) |
| FAILED | 3px red 띠 + soft | red | 이슈 |
| MAINTENANCE | 없음, 배지만 slate | `fg-muted` | "점검 모드라 자동 복구를 하지 않아요" |

- 카운트다운은 **상태가 아니라 `action_in_sec != null`로** 그립니다(preflight F23): 서버는 SUSPECT + 자동 복구 가능 이슈 + 자동 복구 켜짐일 때만 값을 줍니다. ACTION이나 알림 전용 SUSPECT에는 게이지가 없습니다.
- 지연이 `null`이면 `—`, 가동률이 `null`이면 "기록 없음", 마지막 점검이 `null`이면 "—".
- 스파크라인의 `null` 점(점검 실패)은 선을 끊고, 끊긴 구간 바닥에 같은 색 점선을 그어 "값이 없음"을 보이게 합니다(빈칸이 정상처럼 읽히지 않게).

### 차트 형태 (dataviz)

- **스파크라인:** 시간 변화 1계열 → 선. 축·격자·범례 없음(1계열이라 제목이 이름 역할 — `aria-label` "calc 최근 지연 추이: 평균 12ms, 최대 15ms"). 2px 선, 둥근 끝, 세로 축은 **0부터** 최댓값의 110%까지(작은 흔들림이 급등처럼 보이지 않게). 색은 글자 토큰이 아니라 상태 색(선은 마크)이고, 정상은 무채색(de-emphasis). `vector-effect: non-scaling-stroke`로 카드 폭이 바뀌어도 선 두께 유지.
- **가동률:** 하나의 비율 → 차트가 아니라 **숫자**(stat). 99.x%대가 대부분이라 미터 막대는 거의 꽉 차 정보가 없으므로 그리지 않습니다.
- **카운트다운:** 남은 시간 → 한 줄 게이지(막대). 채움은 상태 색, 트랙은 같은 색 soft. 숫자는 옆에 글자로.
- hover 툴팁(dataviz 기본)은 이번에는 넣지 않습니다: 보드는 멀리서 보는 화면이고 정확한 값은 admin 상세 차트(Recharts, Task 11)가 맡습니다. 요약값은 `aria-label`로 제공합니다.

## 4. 빈·로딩·끊김 상태

| 상태 | 판단 | 모습 |
|---|---|---|
| 로딩 | 첫 `board` 이벤트 전(`BoardState.now === null`) | 판정 자리에 "상태 보드"(muted), 카드 자리에 스켈레톤 카드 6개(`Skeleton`, `aria-hidden`) + `role="status"` "불러오는 중…"(sr-only). 배너 자리도 스켈레톤 한 줄 |
| MCP 없음 | 첫 이벤트 후 항목 0개 | 판정 문장 "등록된 MCP가 없어요" + 안내 한 줄(`noMcpHint`), 회색 아이콘. 접속 배너는 그대로 |
| 접속 정보 수집 전 | `sessions === undefined`(Plan 4 이전) | 배너가 `copy.board.sessionsNotReady`, 정보 아이콘, 펄스 없음 |
| 재연결 중 | 스트림 상태 `reconnecting`이 3초 이상 | 상단 바에 "⟳ 실시간 연결 다시 시도 중"(`role="status"`). 3초 미만의 짧은 끊김은 표시하지 않습니다(깜빡임 방지) |
| 멈춤 | 상태 `stopped` | 상단 바에 `copy.stream.offline` |

마지막으로 받은 카드 값은 끊긴 동안에도 그대로 둡니다(지우면 화면이 비어 더 혼란스러움). 다시 연결되면 서버가 `board` 스냅샷을 보내 전체를 바꿉니다.

## 5. 모션 목록

모든 움직임은 `transform`/`opacity`만(U25). 움직이는 요소에는 `data-anim`, 매번 바뀌는 요소에는 `data-volatile`(E2E 스크린샷 마스크).

| 모션 | 구현 | 시간·이징 | reduced-motion |
|---|---|---|---|
| 접속 중 펄스 | 점 뒤의 가상 고리 `scale(1→2.4)` + `opacity(.6→0)` 무한 반복 | 2s `ease-out` | 정지(고리 숨김, 점만) |
| 상태 배지 크로스페이드 | Motion `AnimatePresence`, 옛 배지 out / 새 배지 in(같은 칸에 겹침) | 120ms `ease-out`(`--motion-fast`) | `MotionConfig reducedMotion="user"` → 즉시 교체 |
| 카운트다운 게이지 | `scaleX(var(--gauge-from)) → scaleX(0)`, CSS `@keyframes`, 길이 = 남은 초, `transform-origin: left` | 남은 초, `linear`(시간을 그리는 막대라 linear가 맞는 드문 경우) | 애니메이션 끔, 시작 비율로 고정. 숫자는 1초마다 계속 갱신 |
| 복구 중 회전 테두리 | 카드 `::before`의 conic-gradient를 `rotate(0→360deg)`, `::after`가 안쪽을 덮어 2px 고리만 보임 | 2.4s `linear` 무한 | 회전 끔, 정적 cyan 테두리 |
| 지연 롤링 | `RollingNumber`: 자리마다 0–9 세로 열을 `translateY(-n×10%)` | 200ms `ease-out`(`--motion-base`; 5초마다 바뀌는 값이라 짧게) | 즉시(전환 끔) |
| 카드 재정렬 | Motion `layout`(LazyMotion `domMax`) | 360ms `--ease-in-out`(이미 화면에 있는 것이 움직임) | 즉시 |
| 상단 바 그림자 | base.css(스크롤 타임라인) | — | 끔 |

움직임이 없는 것: 카드 hover(보드는 읽기 전용), 카드 진입 페이드업, 스켈레톤 외 로딩 효과. 스켈레톤 펄스는 shadcn 기본(`data-anim="pulse"`), reduced-motion에서 끔.

## 6. 접근성 메모

- 상태 = 아이콘(Lucide, `aria-hidden`) + 글자(WCAG 1.4.1). 배지에 `data-state`.
- 카드는 `<article aria-labelledby=이름>`, 지표는 `<dl>`. 지연 숫자는 롤링 열을 `aria-hidden`으로 두고 실제 값 "42 ms"를 `sr-only`로.
- 카운트다운 숫자는 `role="timer"` + `aria-live="off"`(1초마다 읽히지 않게). 판정 문장만 `aria-live="polite"`.
- 접속자 카드의 IP는 전체 표시(사양), 모노 글꼴(복사·대조하는 기계 값).
- 계정 메뉴·테마 메뉴는 Radix 메뉴(키보드 화살표·Esc), 트리거에 이름.
- 비활성 컨트롤은 `WithReason`: `aria-disabled` + `aria-describedby` + 포커스 시 툴팁(U26).

## 7. 검증 체크 (Playwright 플러그인, Step 6)

서버: `uv run python -m app --root <scratch>/ui-root --external-host 127.0.0.1 --dev-otp-code 246810 --static-dir ../web/dist`(계획의 명령에 `--external-host 127.0.0.1`을 더함: F36 이후 dev OTP는 외부 채널이 loopback일 때만 허용). 브라우저 콘솔 `fetch`로 초기 Admin 생성·로그인 후 MCP 5개 등록(tcp 8700/8701 정상, 닫힌 포트 9301 자동 복구·9302 점검 모드·9303 자동 복구 꺼짐). 스크린샷은 검토용이며 커밋하지 않았습니다(U30).

dark ✓ light ✓ reduced-motion ✓ 360px ✓ 1920px ✓ (1366px ✓)

확인한 것:
- 빈 상태(MCP 0개, 로컬 + 초기 설정 안내), 접속 정보 수집 전 배너, SUSPECT 카운트다운(45초 → 줄어듦), ACTION, FAILED(최대 자동 조치 후), MAINTENANCE, 자동 복구 꺼진 SUSPECT(게이지 없음), RECOVERING 회전 테두리, 정상 카드 회색 스파크라인, 문제 카드가 앞으로 재정렬.
- 로그인 상태의 계정 메뉴(이름·이메일·역할·관리 화면·로그아웃), 로그아웃 → 로그인 링크로 바뀌고 스트림 재시작 후에도 카드 유지. 콘솔 오류 0건.
- reduced-motion: 게이지 `animation-name: none`(시작 비율에 고정), 회전 테두리 `::before` 애니메이션 없음(정적 cyan 고리).

고친 점:
1. **subgrid가 꺼져 있었음** — 카드에 `container-type: inline-size`를 주면 layout containment 때문에 `grid-template-rows: subgrid`가 `none`이 되어 카드 행이 어긋났습니다. 컨테이너를 지표 `dl`로 옮겨 행 정렬을 되살렸습니다.
2. **문제 카드 테두리가 초록빛** — amber와 강철 파랑을 `color-mix(in oklch)`로 섞으면 색상환이 초록을 지납니다. `in oklab`으로 바꿨습니다.
3. **CSP가 글꼴을 막음** — 4KB 미만 Pretendard 조각이 `data:` URI로 인라인돼 `font-src 'self'`에 막혔습니다. `vite.config.ts`에서 글꼴은 인라인하지 않게 했습니다.
4. **가동률 값 단위** — 서버 `uptime_24h`는 0–1 비율인데 테스트 픽스처는 퍼센트(100, 92.5)였습니다. 픽스처와 타입 주석을 비율로 고쳤습니다.
5. **"기록 없음"이 지표 크기로 커서** 숫자처럼 보임 → `text-base`로 낮춤.
6. **다크 테마 muted 글자가 amber soft 카드 위에서 4.48:1** — 대비 테스트를 문제 카드(soft 채움)까지 넓혔고 `--steel-400`을 L 0.72 → 0.735로 올려 4.5:1을 맞췄습니다.
7. 감사 결과로 건너뛰기 링크(`copy.common.skipToContent`) 추가, 로그인·계정 버튼을 기본 크기(터치 44px)로, 지연 롤링을 360 → 200ms로 줄임.

관찰(고치지 않음): Playwright로 color scheme을 실시간으로 바꾼 직후의 전체 페이지 스크린샷 한 장에서 카드 이름이 이전 테마 색으로 남아 보였습니다. 새로 고친 뒤와 이후의 실시간 전환에서는 재현되지 않아 캡처 시점의 그리기 문제로 보고 기록만 합니다.
