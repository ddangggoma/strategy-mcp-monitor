# 디자인 크리틱 — Plan 5 화면 (Task 16)

**스킬:** `design:design-critique`, `audit-suite:make-interfaces-feel-better`, `audit-suite:vercel-react-best-practices`, `audit-suite:web-design-guidelines`(W40) · **날짜:** 2026-11-07

**입력:**
- Task 15 기준 이미지: `web/e2e/visual.spec.ts-snapshots/{logs,audit,dashboard}-chromium-{dark,light}-win32.png`, 1280px.
- 실제 백엔드(4만 줄 생성 데이터, 사용자 25명)에서 찍은 1920×1080, 1280×800, 800×600(다크), 640×600, 320×300 화면.
- 대상 코드: `web/src/admin/{logs,audit}/*`, `dashboard/LoginFailuresCard.tsx`, `settings/ServiceSection.tsx`.
- 단계: 마무리(final polish). 사용자는 운영자(Admin·MCP 개발자)이고, "그때 무슨 일이 있었나"를 좁혀 가는 것이 첫째 일입니다(`docs/design/screens/logs.md`).

## 전체 인상

- 로그 화면은 히스토그램 하나에 힘을 주고 나머지를 중립 잉크로 둔 방향(`screens/logs.md` §2)이 실제 데이터에서도 잘 읽힙니다. 시간 띠를 끌어 좁히는 흐름은 바로 알 수 있습니다.
- 가장 큰 문제는 **1280px 창에서 표의 핵심 열이 틀 밖에 있던 것**이었습니다. 로그는 "내용", 감사는 "결과"입니다. 이번에 고쳤습니다.

## 사용성

| 발견 | 심각도 | 조치 |
|---|---|---|
| **로그 표:** 1280×800(가장 흔한 노트북 폭)에서 표 틀 976px 안에 시각·카테고리·사용자·세션·IP·이벤트만 보였습니다. "내용" 열(명령 원문, 창 제목, MCP 이슈)은 48px만 보여, 줄마다 가로로 밀어야 했습니다. 세션·IP는 사용자 열과 상세에 이미 있는 보조 정보입니다 | 🟡 Moderate | **고침.** 열 순서를 시각 · 카테고리 · 사용자 · 이벤트 · **내용** · 세션 · IP로 바꿨습니다. 1280에서 내용이 약 260px 보이고, 세션·IP가 틀 안 가로 스크롤 쪽으로 갑니다. 열 폭과 표 최소 폭(76rem)은 그대로입니다. `LogTable.tsx`. 단위 테스트 "puts the summary before session and IP …" |
| **감사 표:** 화면의 "대담함"이라고 정한 **결과 열**(`screens/audit.md` §2)이 1280에서 맨 오른쪽 밖에 있었습니다. 거부·오류 행을 훑어보려면 가로로 밀어야 했습니다. 문서의 남은 것에도 적혀 있던 항목입니다 | 🟡 Moderate | **고침.** 결과를 작업 바로 뒤(대상 앞)로 옮겼습니다. 행위자 13 → 11rem, 채널 8 → 7rem("로컬 관리 모드"가 들어감), 작업 14.5 → 13.5rem(`service_start_type_apply` 24자가 들어감)로 줄였습니다. 1280에서 결과 열 끝이 틀 안(1233 < 1241px)에 들어옵니다. `AuditPage.tsx`. 단위 테스트 "puts the result right after the action …" |
| 사용자 지정 기간이 잘못됐을 때 포커스가 "적용"에 남음 | 🟢 Minor | **고침.** 고칠 칸으로 포커스를 옮깁니다(web-design-guidelines "오류 시 첫 오류로 포커스"). a11y 리뷰 U1 |
| 타임라인에서 Enter로 표를 열면 포커스를 잃음 | 🟡 Moderate | **고침.** a11y 리뷰 O6 |
| **로그인 화면의 개발용 OTP 안내**가 "서비스 콘솔을 확인하세요"였습니다. 설치된 서비스에는 콘솔이 없습니다. 1.0.0의 공급자는 Dummy뿐이라 실제 운영에서도 이 안내가 보입니다 | 🟢 Minor | **고침(문구).** "코드는 서버 PC의 data\dev\otp-outbox.log 파일(콘솔로 실행했다면 콘솔)에 남아요." 운영 문서 ⑨와 같은 내용입니다. `copy/ko.ts` `login.devHint` |
| 640×600에서는 필터 막대가 첫 화면을 다 차지해, 히스토그램과 표가 스크롤 아래에 있습니다 | 🟢 Minor | 남김. 필터는 줄바꿈으로 모두 쓸 수 있고, 표는 창 높이의 절반을 받습니다(W41의 기준은 충족). "조건 더 보기"로 접는 방식은 다음 후보입니다 |
| 관리 작업·시스템 줄의 "내용"이 이벤트 이름을 되풀이합니다(`logs_view logs_view`) | 🟢 Minor | 남김. `summarize`는 식별자만 내는 규칙(복사·grep용, `log-format.ts`)이고, `target`이 없는 작업은 이름뿐입니다. 상세의 원문에 모두 있습니다 |

## 시각 위계

- **처음 눈이 가는 곳:** 히스토그램입니다. 맞습니다. 색은 막대, 칩 점, 표 카테고리 점에만 있고, 글자는 늘 글자 색입니다.
- **읽는 순서:** 제목 → 기간 → 카테고리 칩 → 사람·조건 → 히스토그램 → 보기 토글 → 표. 필터 상자 하나로 묶여 "조건"과 "결과"가 나뉩니다.
- **강조:**
  - 감사 화면은 실패·거부·오류만 진한 글자 + 위험 색 아이콘이고, 성공은 흐린 잉크라 예외가 먼저 보입니다.
  - 대시보드 카드는 계열별 건수(굵게)가 막대보다 먼저 읽힙니다. 숫자가 주인공인 카드라 맞습니다.

## 일관성

| 요소 | 상태 | 비고 |
|---|---|---|
| 토글·칩 | 일치 | 기간·보기·채널 토글은 세션 화면 기간 단추와 같은 모양(`ToggleGroup`). 결과 칩과 카테고리 칩은 같은 pill + `aria-pressed` |
| 표 | 일치 | 두 화면 모두 `VirtualTable`, 행 32px, 같은 빈 값 표기(— + "없음"), 같은 상세 대화상자 |
| 둥근 모서리 | 일치 | 토글 묶음 바깥 6px(`md`) = 안쪽 4px(`sm`) + 2px 여백(동심원). 대화상자 10px 안의 원문 상자 4px |
| 숫자 | 일치 | 시각, 건수, 축 글자, 범례가 모두 `tabular-nums`. `time` 요소는 기본 규칙으로 적용 |
| 움직임 | 일치 | 로그 영역 무애니메이션(W32). 전환은 `transition-[border-color]`처럼 속성을 지정하고, `transition: all`은 없음 |

## make-interfaces-feel-better 점검표

- 동심원 모서리 ✓
- 아이콘 광학 정렬: 내보내기의 다운로드와 꺾쇠, 결과 아이콘 ✓
- 그림자 대신 헤어라인: 관제 콘솔 방향에서 의도한 것(`direction.md`), 그대로 둠
- 들어오고 나가는 애니메이션: 로그 영역은 없음(의도). 대화상자는 기존 확대·축소이고 reduced-motion에서 꺼짐 ✓
- tabular-nums ✓
- 글꼴 다듬기(`antialiased`): `base.css` ✓
- 제목 `text-wrap: balance`, 본문 `pretty`: `base.css` ✓
- 누름 시 축소: 로그 영역에서는 쓰지 않음(움직임 없음 규칙)
- `transition: all` 없음 ✓
- `will-change` 없음 ✓
- 대상 40×40: 밀도 높은 관리 화면은 디자인 시스템이 정한 24px 최소(조잡한 포인터 36px)를 따름. 조건 빼기 X(24px)는 칩 안에 있어 넓히면 이웃과 겹침 → 그대로

## vercel-react-best-practices (로그·감사 코드)

변경할 것은 없었습니다. 확인한 것:
- 열 정의는 모듈 수준에 올려 두었습니다(rendering-hoist).
- 히스토그램 계열 접기는 `useMemo`이고, 포인터 이동은 칸이 바뀔 때만 상태를 바꿉니다(rerender-derived-state).
- SVG 좌표를 소수 둘째 자리로 줄였습니다(rendering-svg-precision).
- 사용자 목록은 팝오버가 열릴 때만 읽습니다(client/bundle-conditional).
- 로그·감사 라우트는 지연 로드입니다(W33).
- 질의는 탐색마다 한 번 계산합니다(`useMemo` + 시계).
- 조건부 렌더는 삼항입니다.
- 타임라인은 키 입력마다 모든 칸(최대 50 × 60)을 다시 그립니다. 측정상 문제없는 규모라 그대로 둡니다.

## web-design-guidelines (로그·감사 코드)

- `TimeRangePicker.tsx`: 제출이 막혔을 때 첫 오류 칸으로 포커스 → **고침**.
- `UserTimeline.tsx`: 칸 `div`의 `onClick` → 줄의 키보드 경로(←/→/Enter)가 대안이고, 이유를 주석으로 남김. 통과.
- `FilterBar.tsx`: 입력 칸에 `autocomplete=off`, `spellcheck=false`, 세션 `inputmode=numeric`. 통과.
- `LogTable.tsx`, `AuditPage.tsx`: 가상화, 렌더 중 레이아웃 읽기 없음(`useLayoutEffect` + `ResizeObserver`), 말줄임 "…", 빈 상태 문구. 통과.
- `LogHistogram.tsx`: 끌기에 키보드 대안, `touch-action: none`은 SVG에만. 통과.
- `ExportMenu.tsx`: 진짜 링크(`<a download>`). 통과.

## 잘된 점

- 히스토그램 선택이 마우스와 키보드에서 같은 결과(분 단위 KST 경계)를 내고, URL 하나에 모든 상태가 남습니다. 링크를 보내면 같은 화면이 열립니다.
- 다크 테마에서도 카테고리 다섯 색이 구분되고, 달력 아이콘 같은 기본 컨트롤도 `color-scheme`을 따라 밝게 바뀝니다.
- 320px(400%)까지 페이지 가로 스크롤이 없습니다.

## 우선순위 권고(남은 것)

1. 640×600에서 필터 막대 접기("조건 더 보기"): 히스토그램을 첫 화면으로 올립니다.
2. 키워드 도움말을 보이는 위치로 옮기기(a11y 리뷰 §5-2).
3. 시스템·관리 작업 줄의 내용에 대표 필드 하나 더하기(예: `retention.run`의 삭제 파일 수).
