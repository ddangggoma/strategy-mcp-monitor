// Every Korean string on screen lives here (Global Constraints). Voice: docs/design/design-system.md
// "Copy". UI text is 해요체: short, active, no apologies, no exclamation marks; errors say what
// happened and what to do next. The audit notice is a formal notice and uses 합니다체.
// Fixed terms (roles, channel, states, issues) are pinned by ko.test.ts; do not reword them.

export const API_ERROR_CODES = [
  "validation", "invalid_email", "rate_limited", "login_required", "forbidden", "csrf", "not_found",
  "bootstrap_done", "user_exists", "last_admin", "name_taken", "endpoint_taken", "action_in_progress",
  "script_required", "scripts_required", "script_too_large", "script_encoding", "script_empty",
  "invalid_owner", "too_many_streams", "body_too_large", "bad_host", "internal", "unavailable",
  "method_not_allowed", "network", "session_changed",
] as const;
/**
 * Server `{"error": code}` values, plus two the client makes itself: `network` for a fetch that
 * never reached the server, `session_changed` when a CSRF refresh finds another user's session.
 */
export type ApiErrorCode = (typeof API_ERROR_CODES)[number];

export const DISABLED_REASONS = [
  "login", "local_only", "admin_only", "owner_only", "no_owner", "running", "config_error",
  "planned_sessions", "planned_logs", "planned_audit", "planned_alerts", "unchanged",
] as const;
/** Why a visible control is unavailable (shown next to it, never hidden: spec §4.4). */
export type DisabledReason = (typeof DISABLED_REASONS)[number];

export type ActionKind = "start" | "restart" | "stop";

const actionKind: Record<ActionKind, string> = { start: "시작", restart: "다시 시작", stop: "종료" };

const LOCAL_ADDRESS = "http://127.0.0.1:8700";

type StartType = "auto" | "delayed-auto" | "manual";
const START_TYPES: Readonly<Record<StartType, string>> = { auto: "자동", "delayed-auto": "자동(지연된 시작)", manual: "수동" };
/** What the SCM can report besides the settings' choices (Windows' own name for it). */
const SERVICE_START_TYPES: Readonly<Record<StartType | "disabled", string>> = { ...START_TYPES, disabled: "사용 안 함" };

const STATE_NAMES = {
  HEALTHY: "정상",
  SUSPECT: "이상 감지",
  ACTION: "조치 중",
  RECOVERING: "복구 중",
  FAILED: "실패",
  MAINTENANCE: "점검 중",
} as const;

const ISSUE_NAMES = {
  PROCESS_DOWN: "프로세스 중지",
  UNRESPONSIVE: "응답 없음",
  NETWORK_DOWN: "네트워크 연결 안 됨",
  WRONG_PROCESS: "다른 프로세스가 포트 사용",
} as const;

/** What each MCP state means (server/app/monitor/engine.py), for the state legends and the detail header. */
const STATE_HELP = {
  HEALTHY: "마지막 점검에서 문제가 없었어요.",
  SUSPECT: "점검에서 문제가 보여 재확인 주기마다 다시 확인하는 중이에요. 조치 대기 시간이 지나도 이어지면 자동 조치를 해요.",
  ACTION: "시작·다시 시작 스크립트를 실행하고 있거나, 실행이 끝나 시작 유예 시간을 기다리고 있어요.",
  RECOVERING: "조치를 마치고 다시 확인하는 중이에요. 다음 점검이 정상이면 정상으로 돌아가요.",
  FAILED: "자동 조치를 최대 횟수만큼 해도 문제가 남아 종료 스크립트를 실행하고 자동 조치를 멈췄어요. 시작·다시 시작을 직접 누르거나 점검 모드를 켰다 끄면 다시 감시해요.",
  MAINTENANCE: "점검 모드라 상태를 판단하지 않고 자동 복구도 하지 않아요. 이 시간은 가동률에서 빠져요.",
} as const;

/** What each issue means (server/app/monitor/probes.py classify). */
const ISSUE_HELP = {
  PROCESS_DOWN: "이 PC에서 포트를 여는 프로세스가 없고 점검도 실패했어요. 자동 복구는 시작 스크립트를 실행해요.",
  UNRESPONSIVE: "점검 요청에 응답하지 않아요. 자동 복구는 다시 시작 스크립트를 실행해요.",
  NETWORK_DOWN: "다른 PC의 MCP가 응답하지 않고 ICMP ping도 닿지 않아요. 스크립트로 고칠 수 없어 알리기만 해요.",
  WRONG_PROCESS: "포트를 연 프로세스의 이름이 예상 프로세스 이름과 달라요. 알리기만 하고 스크립트는 실행하지 않아요.",
} as const;

type Pairs = readonly (readonly [string, string])[];
const pairs = <K extends string>(names: Readonly<Record<K, string>>, help: Readonly<Record<K, string>>): Pairs =>
  (Object.keys(names) as K[]).map((k) => [names[k], help[k]] as const);

const ENV_VARS = "스크립트에는 MCP_ID, MCP_NAME, MCP_HOST, MCP_PORT, MCP_PID, MCP_REASON, MCP_TRIGGER, MCP_ACTOR 환경 변수가 전달돼요.";

/** Log screens: thousands with separators ("1,234건"). */
const count = (n: number | string) => (typeof n === "number" ? n.toLocaleString("ko-KR") : n);

/** Windows logon types as the Korean Windows event viewer names them. */
const LOGON_TYPES: Readonly<Record<number, string>> = {
  2: "대화형",
  3: "네트워크",
  4: "일괄 작업",
  5: "서비스",
  7: "잠금 해제",
  8: "네트워크 일반 텍스트",
  9: "새 자격 증명",
  10: "원격 대화형",
  11: "캐시된 대화형",
};

export const copy = {
  common: {
    productName: "MCP Monitor",
    save: "저장",
    saving: "저장하는 중…",
    saved: "저장했어요",
    cancel: "취소",
    close: "닫기",
    confirm: "확인",
    delete: "삭제",
    edit: "편집",
    retry: "다시 시도",
    back: "뒤로",
    loading: "불러오는 중…",
    copyText: "복사",
    copied: "복사했어요",
    copyFailed: "복사하지 못했어요. 내용을 직접 선택해 복사하세요.",
    search: "검색",
    help: "도움말",
    searchPlaceholder: "이름이나 주소로 검색…",
    noResults: "검색 결과가 없어요.",
    none: "없음",
    unknown: "알 수 없음",
    required: "필수",
    optional: "선택",
    login: "로그인",
    logout: "로그아웃",
    adminHome: "관리 화면",
    boardHome: "상태 보드",
    // starts with the visible name (WCAG 2.5.3 Label in Name)
    accountMenu: (name: string) => `${name} 계정 메뉴`,
    skipToContent: "본문으로 건너뛰기",
    commandTitle: "빠른 이동",
    commandHint: "이동할 화면이나 MCP 이름을 입력하세요.",
    commandShortcut: (mac: boolean) => (mac ? "⌘K" : "Ctrl K"),
    commandScreens: "화면",
    commandMcps: "MCP",
    notFoundTitle: "화면을 찾을 수 없어요",
    notFound: "주소가 틀렸거나 없어진 화면이에요. 주소를 확인하거나 관리 화면 처음으로 가세요.",
    unsavedTitle: "저장하지 않은 변경 사항이 있어요",
    unsavedBody: "이 페이지를 떠나면 지금 고친 내용이 사라져요.",
    leave: "떠나기",
    stay: "계속 편집",
    theme: {
      label: "화면 테마",
      triggerLabel: (current: string) => `화면 테마(지금: ${current})`,
      system: "시스템 설정",
      dark: "어둡게",
      light: "밝게",
    },
    units: {
      ms: (n: number | string) => `${n}ms`,
      seconds: (n: number | string) => `${n}초`,
      minutes: (n: number | string) => `${n}분`,
      hours: (n: number | string) => `${n}시간`,
      days: (n: number | string) => `${n}일`,
      percent: (n: number | string) => `${n}%`,
    },
  },

  channel: {
    label: "접속 채널",
    local: "로컬 관리 모드",
    external: "원격 모드",
    localHint: `이 PC(${LOCAL_ADDRESS})로 접속했어요. 권한에 맞는 모든 관리 기능을 쓸 수 있어요.`,
    externalHint: `다른 PC에서 접속했어요. 사용자·설정·고지 관리, MCP 등록·삭제, 스크립트 보기·편집은 이 PC의 ${LOCAL_ADDRESS}에서만 할 수 있어요.`,
  },

  roles: {
    developer: "MCP 개발자",
    admin: "Admin",
  },

  states: STATE_NAMES,

  issues: ISSUE_NAMES,

  nav: {
    label: "관리 메뉴",
    dashboard: "대시보드",
    mcps: "MCP",
    sessions: "세션",
    logs: "로그",
    audit: "감사 로그",
    users: "사용자",
    notice: "사전 고지",
    settings: "설정",
    planned: "준비 중",
  },

  board: {
    title: "상태 보드",
    allHealthy: "모든 MCP가 정상이에요",
    problems: (n: number) => `MCP ${n}개에 문제가 있어요`,
    maintenanceOnly: (n: number) => `MCP ${n}개가 점검 중이에요`,
    noMcp: "등록된 MCP가 없어요",
    noMcpHint: "로컬 관리 모드에서 Admin이 MCP를 등록하면 여기에 바로 나타나요.",
    connected: "접속 중",
    noSession: "접속자 없음",
    sessionsNotReady: "원격 접속 정보를 아직 받지 못했어요.",
    latency: "지연",
    uptime24h: "24시간 가동률",
    lastCheck: "마지막 점검",
    noData: "아직 측정값이 없어요",
    noRecord: "기록 없음",
    actionIn: (sec: number | string) => `${sec}초 뒤 자동 조치`,
    autoActionOff: "자동 조치 꺼짐",
    autoAction: "자동 조치",
    sparklineLabel: (name: string) => `${name} 최근 지연 추이`,
    sparklineSummary: (label: string, avg: number | string, max: number | string) => `${label}: 평균 ${avg}ms, 최대 ${max}ms`,
    running: (kind: ActionKind) => `스크립트 실행 중: ${actionKind[kind]}`,
    maintenanceOn: "점검 모드라 자동 복구를 하지 않아요",
    sessionsTitle: "원격 접속",
    setupHint: "아직 Admin이 없어요. 이 PC에서 첫 Admin을 만들면 관리 기능을 쓸 수 있어요.",
    setupLink: "초기 설정 시작",
    /** The overview tiles between the verdict and the cards (numbers from the live board only). */
    overview: {
      title: "한눈에 보기",
      live: "실시간",
      waiting: "연결 대기 중",
      lastCheck: (ago: string) => `마지막 점검 ${ago}`,
      distribution: "상태 분포",
      healthyOf: (ok: number | string, total: number | string) => `${total}개 중 ${ok}개 정상`,
      donutLabel: (parts: string) => `MCP 상태 분포: ${parts}`,
      donutPart: (state: string, n: number | string) => `${state} ${n}개`,
      avgLatency: "평균 응답 지연",
      slowest: (name: string, ms: number | string) => `가장 느림 ${name} ${ms}ms`,
      checkRate: "최근 점검 성공률",
      checkSummary: (ok: number | string, total: number | string) => `점검 ${count(total)}회 중 ${count(ok)}회 응답`,
      checkStripLabel: (steps: number | string, failed: number | string) => `최근 점검 ${steps}회, 응답 없는 점검 ${failed}회`,
      checkStep: (ago: number | string, ok: number | string, total: number | string) =>
        Number(ago) === 0 ? `가장 최근 점검: ${total}개 중 ${ok}개 응답` : `${ago}회 전 점검: ${total}개 중 ${ok}개 응답`,
      older: "이전",
      newer: "최근",
      avgUptime: "24시간 평균 가동률",
      lowest: (name: string, pct: number | string) => `가장 낮음 ${name} ${pct}%`,
      uptimeLabel: (pct: number | string) => `24시간 평균 가동률 ${pct}%`,
      noValue: "아직 측정값이 없어요",
      excludesMaintenance: "점검 중인 MCP는 지표에서 빠져요",
    },
    /** This PC's resources (server app/monitor/system.py), below the MCP cards. */
    system: {
      title: "서버 PC 리소스",
      uptime: (d: string) => `부팅 후 ${d}`,
      every: (sec: number | string) => `${sec}초마다 갱신`,
      waiting: "리소스 정보를 아직 받지 못했어요.",
      cpu: "CPU",
      cores: (n: number | string) => `논리 프로세서 ${n}개`,
      memory: "메모리",
      memoryUsed: (used: string, total: string) => `${total} 중 ${used} 사용`,
      gpu: "GPU",
      gpuMemory: "GPU 전용 메모리",
      gpuMemoryUsed: (used: string, total: string) => `${total} 중 ${used} 사용`,
      gpuMemoryOnly: (used: string) => `${used} 사용`,
      gpuNoMemory: "전용 메모리 정보 없음",
      disk: "디스크",
      diskUsed: (used: string, total: string) => `${total} 중 ${used} 사용`,
      noDisk: "읽을 수 있는 고정 디스크가 없어요.",
      network: "네트워크",
      received: "받기",
      sent: "보내기",
      networkFirst: "다음 측정부터 속도가 보여요.",
      gaugeLabel: (name: string, pct: number | string) => `${name} 사용률 ${pct}%`,
      trendLabel: (name: string) => `${name} 사용률 최근 추이`,
      trendSummary: (label: string, avg: number | string, max: number | string) => `${label}: 평균 ${avg}%, 최대 ${max}%`,
      recent: (min: number | string) => `최근 ${min}분`,
    },
  },

  /** Remote desktop sessions: the board's session card and the sessions screen (one namespace, F16). */
  sessions: {
    title: "세션",
    current: "현재 세션",
    history: "접속 이력",
    failures: "로그인 실패",
    collectors: "수집 상태",
    fields: {
      user: "사용자",
      domain: "로그온 도메인",
      clientName: "클라이언트 PC",
      clientIp: "IP 주소",
      reverseDns: "역방향 DNS",
      connectedAt: "접속 시각",
      elapsed: "경과 시간",
      state: "상태",
      idle: "유휴 시간",
      resolution: "해상도",
      notice: "사전 고지",
    },
    /** WTS session states: `connected` is a client at the logon screen, not yet signed in. */
    state: {
      active: "사용 중",
      locked: "잠김",
      disconnected: "연결 끊김",
      connected: "로그온 전",
    },
    firstSeenIp: "처음 보는 IP",
    firstSeenDevice: "처음 보는 기기",
    noticeAcked: "확인함",
    noticePending: "확인 전",
    noticeUnknown: "알 수 없음",
    /** Whole minutes (the server resends idle time when the minute changes, V10). */
    idle: (min: number) => {
      const h = Math.floor(min / 60);
      const m = min % 60;
      if (h === 0) return `${m}분`;
      return m === 0 ? `${h}시간` : `${h}시간 ${m}분`;
    },
    /** "1920x1080@32" from the server; the colour depth may be missing. */
    resolution: (w: number, h: number, bits: number | null) => (bits ? `${w}×${h}, ${bits}비트` : `${w}×${h}`),
    kinds: {
      logon: "새 로그온",
      reconnect: "다시 연결",
      existing: "서비스 시작 때 접속 중",
    },
    endReasons: {
      disconnect: "연결 끊김",
      logoff: "로그오프",
      reconnected: "다시 연결됨",
      service_stop: "서비스 중지",
    },
    ongoing: "접속 중",
    /** Time from the notice's last showing to the button. */
    ackIn: (ms: number) => {
      const s = Math.round(ms / 1000);
      if (s < 1) return "1초 안에 확인";
      return s < 60 ? `${s}초 만에 확인` : `${Math.floor(s / 60)}분 ${s % 60}초 만에 확인`;
    },
    unacked: "확인 안 함",
    more: "더 보기",
    days: (n: number) => `최근 ${n}일`,
    empty: "이 기간에는 접속 기록이 없어요.",
    failuresEmpty: "이 기간에는 로그인 실패가 없어요.",
    collectorOk: "수집 중",
    collectorDown: (error: string) => `수집 중단: ${error}`,
    /** Stopped without an error text from the collector. */
    collectorStopped: "수집 중단",
    collectorsEmpty: "켜진 수집기가 없어요.",
    /** The period buttons govern the history and the failures, not the current sessions. */
    periodLabel: "기록 기간",
    currentEmpty: "지금 접속한 세션이 없어요.",
    disconnectedAt: "연결 끊긴 시각",
    loadError: "불러오지 못했어요. 새로 고친 뒤 다시 시도하세요.",
    moreError: "다음 기록을 불러오지 못했어요. 더 보기를 다시 누르세요.",
    columns: {
      kind: "종류",
      end: "종료",
      at: "시각",
      workstation: "워크스테이션",
      logonType: "로그온 유형",
      status: "상태 코드",
      collector: "수집기",
      collectorState: "상태",
      since: "바뀐 시각",
    },
    /** Windows logon type (event 4625) in words, with the number an operator looks up. */
    logonType: (n: number) => {
      const name = LOGON_TYPES[n];
      return name ? `${name}(${n})` : String(n);
    },
  },

  /** Bypass detection (Global Constraints `tamper` events); the dashboard card is `dashboard.bypassEvents`. */
  tamper: {
    empty: "최근 우회 탐지 이벤트가 없어요.",
    /** The Windows session an event is about. */
    session: (id: number) => `세션 ${id}`,
    events: {
      agent_exited: "세션 에이전트 종료",
      agent_unresponsive: "세션 에이전트 응답 없음",
      agent_restart_storm: "세션 에이전트 반복 종료",
      agent_impersonation: "세션 에이전트 사칭 시도",
      notice_token_misuse: "다른 세션에서 고지 토큰 사용",
      script_hash_mismatch: "스크립트 해시 불일치",
      script_file_changed: "스크립트 파일 변경",
      script_file_missing: "스크립트 파일 없음",
      log_file_removed: "로그 파일 삭제",
      log_file_truncated: "로그 파일 내용 잘림",
      audit_policy_changed: "감사 정책 변경",
      log_cleared: "Windows 이벤트 로그 지움",
      audit_config_changed: "감사 설정 레지스트리 변경",
      baseline_reset: "우회 탐지 기준값 없음·손상(정지 중 변경 비교 불가)",
    },
  },

  /** Log search (view_logs, both channels). Category and group names are chip labels: all distinct. */
  logs: {
    title: "로그",
    quick: { "1h": "최근 1시간", today: "오늘", yesterday: "어제", "7d": "최근 7일" },
    from: "시작 시각",
    to: "끝 시각",
    apply: "적용",
    users: "사용자",
    usersCount: (n: number) => `${n}명 선택`,
    categories: "카테고리",
    cats: {
      session: "원격 접속",
      notice: "사전 고지",
      "activity.process": "프로세스",
      "activity.command": "명령",
      "activity.window": "창 전환",
      "activity.idle": "유휴",
      tamper: "우회 탐지",
      "mcp.health": "MCP 상태",
      "mcp.action": "MCP 조치",
      auth: "웹 로그인",
      "admin.audit": "관리 작업",
      system: "시스템 이벤트",
    },
    groups: { session: "접속", activity: "활동", mcp: "MCP", security: "보안", system: "시스템" },
    session: "세션 번호",
    ip: "클라이언트 IP",
    keyword: "키워드",
    keywordHint: "낱말의 앞부분으로 찾아요. 여러 낱말을 쓰면 모두 들어 있는 기록만 나와요(최대 10개).",
    moreConditions: "추가 조건",
    clear: "조건 지우기",
    view: { table: "표", timeline: "타임라인" },
    export: { menu: "내보내기", csv: "CSV로 내보내기", jsonl: "JSONL(원문)로 내보내기" },
    empty: "이 조건에 맞는 로그가 없어요. 기간을 넓히거나 조건을 줄여 보세요.",
    indexing: (files: number) => `로그 색인을 만드는 중이에요. 파일 ${count(files)}개가 남아 있어 결과에 빠진 기록이 있을 수 있어요.`,
    detail: "로그 상세",
    // spec §2 #7: what the command log can and cannot see
    cmdLimitHelp:
      "cmd.exe 실행과 인자, cmd가 실행한 외부 프로그램, cmd /c 명령, 배치 파일은 기록해요. " +
      "dir·cd·del 같은 cmd 내부 명령은 기록하지 않아요. 키 입력·클립보드·화면 내용도 수집하지 않아요.",
    histogramLabel: (from: string, to: string, total: number | string) =>
      `시간대별 로그 건수(${from}–${to}, 모두 ${count(total)}건). Shift+화살표로 구간을 고르고 Enter로 적용해요.`,
    selection: (from: string, to: string, n: number | string) => `${from}–${to} 선택, ${count(n)}건`,
    columns: { ts: "시각", cat: "카테고리", user: "사용자", session: "세션", ip: "IP", event: "이벤트", summary: "내용" },
    loadMore: "더 보기",
    // beyond the Global Constraints list (Task 11)
    quickLabel: "기간",
    viewLabel: "보기",
    legend: "카테고리 묶음",
    count: (n: number | string) => `${count(n)}건`,
    total: (n: number | string) => `모두 ${count(n)}건`,
    invertedRange: "끝 시각이 시작 시각보다 늦어야 해요. 두 시각을 확인하세요.",
    incompleteRange: "시작 시각과 끝 시각을 모두 넣으세요.",
    removeCondition: (label: string) => `${label} 조건 빼기`,
    usersSearch: "사용자 이름으로 찾기",
    usersEmpty: "이 기간에 기록된 사용자가 없어요.",
    picked: "선택됨",
    byUser: "이 사용자로 거르기",
    bySession: "이 세션으로 거르기",
    raw: "원문",
    loadError: "로그를 불러오지 못했어요. 잠시 뒤 다시 시도하세요.",
    loadMoreError: "다음 기록을 불러오지 못했어요.",
    timelineLane: (user: string, total: number | string) =>
      `${user}, ${count(total)}건. 화살표로 칸을 고르고 Enter로 그 시간의 표를 열어요.`,
    otherUsers: "그 밖의 사용자",
    noUser: "사용자 없음",
    sessionInvalid: "세션 번호는 숫자로 넣으세요.",
    dragHint: "막대를 끌어 구간을 고르면 그 시간으로 좁혀요.",
  },

  /** Admin actions and login attempts (view_audit, both channels). */
  audit: {
    title: "감사 로그",
    kinds: { admin: "관리 작업", auth: "로그인", all: "전체" },
    columns: { ts: "시각", actor: "행위자", channel: "채널", ip: "IP", action: "작업", target: "대상", result: "결과" },
    results: { ok: "성공", fail: "실패", denied: "거부", error: "오류" },
    empty: "이 조건에 맞는 감사 기록이 없어요. 기간을 넓히거나 조건을 줄여 보세요.",
    // beyond the Global Constraints list (Task 12)
    tabsLabel: "감사 기록 종류",
    channels: { all: "모든 채널", local: "로컬", external: "원격" },
    /** The Windows account behind a local-channel login (Plan 4). */
    windowsUser: (name: string) => `Windows 계정 ${name}`,
    loadError: "감사 기록을 불러오지 못했어요. 잠시 뒤 다시 시도하세요.",
  },

  stream: {
    live: "실시간 연결됨",
    reconnecting: "실시간 연결 다시 시도 중",
    offline: "실시간 연결이 끊겼어요. 화면이 최신이 아닐 수 있어요.",
  },

  login: {
    title: "로그인",
    lead: "등록된 이메일로 받은 인증 코드로 로그인해요.",
    email: "이메일",
    emailPlaceholder: "name@example.com",
    sendCode: "인증 코드 받기",
    sendingCode: "코드를 보내는 중…",
    // the server answers the same for unknown emails, so this must not claim the email is registered
    codeSent: (email: string) => `등록된 이메일이면 ${email}(으)로 인증 코드를 보냈어요. 코드는 5분 동안 쓸 수 있어요.`,
    codeGroup: "인증 코드 6자리",
    codeDigit: (n: number) => `${n}번째 자리`,
    verify: "로그인",
    verifying: "확인하는 중…",
    wrongCode: "인증 코드가 맞지 않아요. 다시 입력하세요.",
    failedCount: (n: number) => `이 코드로 ${n}번 틀렸어요. 5번 틀리면 새 코드를 받아야 해요.`,
    codeExhausted: "이 코드는 5번 틀려서 더 쓸 수 없어요. 새 코드를 받으세요.",
    failureHint: "1시간 안에 10번 틀리면 이 이메일은 최대 1시간 동안 로그인할 수 없어요.",
    lockedFor: (minutes: number) => `로그인 시도가 너무 많아 잠겼어요. ${minutes}분 뒤에 다시 시도하세요.`,
    resend: "코드 다시 받기",
    resendIn: (sec: number) => `${sec}초 뒤에 다시 받을 수 있어요`,
    changeEmail: "다른 이메일로 로그인",
    devBadge: "개발용 OTP 모드",
    // a service has no console: the Dummy provider appends every code to <root>/data/dev/otp-outbox.log
    devHint: "개발용 OTP: 코드는 서버 PC의 data\\dev\\otp-outbox.log 파일(콘솔로 실행했다면 콘솔)에 남아요.",
    unknownEmailNote: "코드가 오지 않으면 Admin에게 이메일 등록을 요청하세요.",
  },

  setup: {
    title: "처음 사용할 Admin 만들기",
    lead: "이 PC에서 처음 접속했어요. 관리를 맡을 Admin의 이메일과 이름을 입력하세요.",
    email: "이메일",
    name: "이름",
    submit: "Admin 만들기",
    submitting: "만드는 중…",
    nameRequired: "이름을 입력하세요.",
    done: "Admin을 만들었어요. 이 이메일로 로그인하세요.",
    externalOnly: `초기 설정은 이 PC의 ${LOCAL_ADDRESS}에서만 할 수 있어요.`,
  },

  dashboard: {
    title: "대시보드",
    mcpSummary: "MCP 요약",
    currentSessions: "현재 세션",
    recentActivity: "최근 이슈와 조치",
    noActivity: "최근 이슈나 조치가 없어요.",
    /** Last 24 h of failed web logins (`auth`) and remote desktop logons (`session`). */
    loginFailures: {
      title: "로그인 실패 추이",
      web: "웹 로그인",
      rdp: "원격 데스크톱",
      openLogs: "로그에서 보기",
      empty: "최근 24시간 동안 로그인 실패가 없어요.",
      // beyond the Global Constraints list (Task 12)
      chartLabel: (total: number | string) => `최근 24시간 시간대별 로그인 실패, 모두 ${count(total)}건`,
      error: "로그인 실패 추이를 불러오지 못했어요. 새로 고친 뒤 다시 시도하세요.",
    },
    bypassEvents: "우회 탐지 이벤트",
    viewAll: "모두 보기",
    summaryAll: "전체",
    noMcp: "등록된 MCP가 없어요.",
    activityError: "최근 기록을 불러오지 못했어요. 새로 고친 뒤 다시 시도하세요.",
    columns: { at: "시각", mcp: "MCP", event: "내용" },
    /** "자동 다시 시작": who started it, then what ran. */
    actionLine: (trigger: string, kind: ActionKind) => `${trigger} ${actionKind[kind]}`,
  },

  mcp: {
    title: "MCP",
    create: "MCP 등록",
    createLead: "감시할 MCP의 주소와 시작·종료 스크립트를 등록해요. 스크립트는 이 PC에서 서비스 권한(SYSTEM)으로 실행돼요.",
    scriptsLegend: "스크립트",
    scriptRequired: (kind: string) => `${kind}를 입력하세요.`,
    createSubmit: "등록",
    creating: "등록하는 중…",
    created: (name: string) => `${name}을(를) 등록했어요.`,
    createCancel: "취소",
    detail: "MCP 상세",
    start: actionKind.start,
    restart: actionKind.restart,
    stop: actionKind.stop,
    stopConfirmTitle: (name: string) => `${name}을(를) 종료할까요?`,
    stopConfirm: "종료하면 점검 모드로 바뀌고 자동 복구가 멈춰요. 다시 시작하면 점검 모드가 풀려요.",
    noOwner: "소유자 없음",
    owner: "소유자",
    transferOwner: "소유권 이전",
    transferOwnerLead: "새 소유자는 이 MCP의 설정과 스크립트를 관리하게 돼요.",
    newOwner: "새 소유자",
    chooseOwner: "사용자를 고르세요",
    currentOwner: "지금 소유자",
    transferSubmit: "이전",
    transferring: "이전하는 중…",
    transferred: (name: string, user: string) => `${name}의 소유자를 ${user}(으)로 바꿨어요.`,
    usersError: "사용자 목록을 불러오지 못했어요. 대화상자를 닫았다가 다시 여세요.",
    notFound: "이 MCP를 찾을 수 없어요. 이미 삭제됐거나 주소가 틀렸을 수 있어요.",
    backToList: "MCP 목록으로",
    loadError: "MCP 정보를 불러오지 못했어요. 새로 고친 뒤 다시 시도하세요.",
    configError: "저장된 설정에 오류가 있어 이 MCP를 감시하지 않고 있어요. 설정을 고쳐 저장하거나 MCP를 삭제하세요.",
    nameRule: "글자, 숫자, 공백, 마침표(.), 밑줄(_), 하이픈(-)만 쓸 수 있어요. 최대 64자예요.",
    truncated: "출력이 너무 길어 앞부분만 저장했어요.",
    deleteTitle: (name: string) => `${name} 삭제`,
    deleteConfirm: "삭제하면 설정, 스크립트, 이력이 모두 지워져요. 종료 스크립트는 실행하지 않으니 필요하면 먼저 종료하세요. 확인하려면 MCP 이름을 그대로 입력하세요.",
    deleteAction: "MCP 삭제",
    deleteNameLabel: "MCP 이름",
    deleting: "삭제하는 중…",
    deleted: (name: string) => `${name}을(를) 삭제했어요.`,
    tabs: { settings: "설정", scripts: "스크립트", history: "이력", latency: "지연 차트" },
    noHistory: "선택한 기간에 기록된 이슈나 조치가 없어요.",
    // settings form
    nameRequired: "이름을 입력하세요.",
    hostRule: "호스트 이름이나 IP 주소를 입력하세요. 하이픈(-)으로 시작할 수 없고 최대 253자예요.",
    pathRule: "/로 시작하고 공백 없이 최대 200자로 입력하세요.",
    processNameRule: "제어 문자 없이 최대 260자로 입력하세요.",
    processNameHint: "비워 두면 포트를 쓰는 프로세스의 이름을 확인하지 않아요.",
    rangeHint: (min: number | string, max: number | string) => `허용 범위 ${min}–${max}`,
    rangeError: (min: number | string, max: number | string) => `${min}–${max} 사이의 정수를 입력하세요.`,
    groups: { connection: "연결과 점검", recovery: "자동 복구", operation: "운영" },
    hints: {
      auto_recovery: "끄면 이상을 감지해도 스크립트를 실행하지 않고 알리기만 해요.",
      autostart_on_boot: "서비스가 시작될 때 이 MCP의 시작 스크립트를 실행해요.",
      maintenance: "켜면 점검 중으로 표시하고 자동 복구를 멈춰요.",
      max_auto_actions: "집계 구간 안에서 이 횟수를 넘으면 자동 조치를 멈춰요.",
    },
    liveNote: "다른 사람이 바꾼 값은 지금 고치고 있지 않은 칸에 바로 반영돼요.",
    discard: "변경 취소",
    // history
    periodLabel: "기간",
    periods: { 1: "1시간", 6: "6시간", 24: "24시간", 168: "7일" } as Record<1 | 6 | 24 | 168, string>,
    transitionsTitle: "상태 전이",
    actionsTitle: "조치 기록",
    historyError: "이력을 불러오지 못했어요. 새로 고친 뒤 다시 시도하세요.",
    historyColumns: {
      at: "시각",
      change: "변경",
      issue: "이슈",
      kind: "종류",
      trigger: "계기",
      reason: "사유",
      actor: "실행자",
      result: "결과",
      exitCode: "종료 코드",
      duration: "소요 시간",
    },
    /** A restart without a restart script runs stop, then start: "다시 시작(종료 단계)". */
    requestedStep: (requested: ActionKind, kind: ActionKind) => `${actionKind[requested]}(${actionKind[kind]} 단계)`,
    systemActor: "시스템",
    /** Action `reason` values that are not an issue code (issues use `issues.*`). */
    reasons: { manual: "직접 요청", action_in_progress: "다른 조치가 진행 중이라 건너뜀" } as Record<string, string>,
    viewOutput: "출력 보기",
    chartTitle: "지연과 가동률",
    chartAvg: "평균 지연",
    chartMax: "최대 지연",
    chartUptime: "가동률",
    chartTransition: "상태 전이",
    chartSummary: (period: string, avg: string, max: string, uptime: string) =>
      `${period} 동안 평균 지연 ${avg}, 최대 지연 ${max}, 가동률 ${uptime}`,
    noChartData: "이 기간에 측정값이 없어요.",
    // action output
    outputTitle: (kind: string, at: string) => `${kind} 실행 결과(${at})`,
    stdout: "표준 출력",
    stderr: "표준 오류",
    noOutput: "출력 없음",
    outputError: "실행 결과를 불러오지 못했어요. 다시 열어 보세요.",
    runErrorLabel: "실행 오류",
    hostPort: "호스트:포트",
    listLabel: "MCP 목록",
    listEmpty: "등록된 MCP가 없어요. MCP를 등록하면 여기서 상태를 보고 직접 시작하거나 종료할 수 있어요.",
    listError: "MCP 목록을 불러오지 못했어요. 새로 고친 뒤 다시 시도하세요.",
    filterLabel: "상태로 거르기",
    filterAll: "전체",
    filterEmpty: (state: string) => `지금 ${state} 상태인 MCP가 없어요.`,
    clearFilter: "모든 MCP 보기",
    configErrorBadge: "설정 오류",
    noLive: "상태 기록 없음",
    columns: {
      state: "상태",
      name: "이름",
      hostPort: "호스트:포트",
      latency: "지연(ms)",
      uptime: "24시간 가동률",
      owner: "소유자",
      actions: "조치",
    },
    actionsLabel: (name: string) => `${name} 조치`,
    triggers: { auto: "자동", manual: "수동", boot: "부팅 시" },
    scriptStatus: { ok: "성공", failed: "실패", timeout: "시간 초과", error: "실행 오류" },
    probes: { mcp_ping: "MCP ping", tcp: "TCP 연결", icmp: "ICMP ping" },
    fields: {
      name: "이름",
      host: "호스트",
      port: "포트",
      path: "경로",
      probe: "점검 방식",
      expected_process_name: "예상 프로세스 이름",
      action_delay_sec: "조치 대기 시간(초)",
      startup_grace_sec: "시작 유예 시간(초)",
      max_auto_actions: "최대 자동 조치 횟수",
      window_sec: "자동 조치 집계 구간(초)",
      auto_recovery: "자동 복구",
      autostart_on_boot: "부팅 시 자동 시작",
      maintenance: "점검 모드",
      script_timeout_sec: "스크립트 제한 시간(초)",
    },
  },

  scripts: {
    title: "스크립트",
    kinds: { start: "시작 스크립트", stop: "종료 스크립트", restart: "다시 시작 스크립트" },
    edit: "편집",
    view: "보기",
    readOnly: "읽기 전용",
    draftRestored: "저장하지 않은 초안을 되살렸어요.",
    discardDraft: "초안 버리기",
    /** The script was saved again (another tab) after the draft was made. */
    draftStale: (v: number) => `초안을 만든 뒤에 새 버전(버전 ${v})이 저장됐어요. 버전 이력에서 비교한 뒤 저장하세요.`,
    /** The same, while the edits are on screen: Save would overwrite that version. */
    newerWhileEditing: (v: number) => `편집하는 동안 새 버전(버전 ${v})이 저장됐어요. 지금 저장하면 그 버전을 덮어써요. 버전 이력에서 비교한 뒤 저장하세요.`,
    versions: "버전 이력",
    revert: "이 버전으로 되돌리기",
    noVersions: "아직 저장된 버전이 없어요.",
    optionalRestart: "다시 시작 스크립트가 없으면 종료한 뒤 시작해요.",
    encodingNote: ".ps1은 UTF-8로, .bat와 .cmd는 이 PC의 코드 페이지로 저장돼요.",
    kindsLabel: "스크립트 종류",
    missing: "(없음)",
    loadError: "스크립트를 불러오지 못했어요. 새로 고친 뒤 다시 시도하세요.",
    versionsError: "버전 이력을 불러오지 못했어요. 새로 고친 뒤 다시 시도하세요.",
    lastSaved: "마지막 저장",
    ext: "확장자",
    editorLabel: (kind: string) => `${kind} 내용`,
    count: (used: number, max: number) => `${used.toLocaleString("ko-KR")}/${max.toLocaleString("ko-KR")}자`,
    tooLong: "65,536자를 넘었어요. 내용을 줄여야 저장할 수 있어요.",
    saveHint: "편집기 안에서 Ctrl+S를 눌러도 저장돼요. Tab 키는 다음 칸으로 이동해요.",
    savedVersion: (v: number) => `저장했어요(버전 ${v}).`,
    noRestart: "다시 시작 스크립트가 없어요.",
    addRestart: "다시 시작 스크립트 추가",
    deleteRestart: "다시 시작 스크립트 삭제",
    deleteRestartTitle: "다시 시작 스크립트를 삭제할까요?",
    deleteRestartBody: "삭제하면 다시 시작할 때 종료 스크립트를 실행한 뒤 시작 스크립트를 실행해요. 지금 내용은 버전 이력에 남아 되돌릴 수 있어요.",
    restartDeleted: "다시 시작 스크립트를 삭제했어요.",
    versionLabel: (v: number) => `버전 ${v}`,
    current: "현재",
    deletedTag: "삭제됨",
    deletedNote: "이 버전에서 스크립트를 삭제했어요. 삭제된 버전으로는 되돌릴 수 없어요.",
    currentNote: "지금 쓰고 있는 버전이에요.",
    pickVersion: "버전을 고르면 현재 내용과 비교해요.",
    versionError: "이 버전을 불러오지 못했어요. 다시 골라 보세요.",
    revertTitle: (v: number) => `버전 ${v}의 내용으로 되돌릴까요?`,
    revertBody: "이 버전의 내용을 새 버전으로 저장해요. 지금 내용도 버전 이력에 남아요.",
    revertAction: "되돌리기",
    reverting: "되돌리는 중…",
    reverted: (from: number, to: number) => `버전 ${from}의 내용으로 되돌렸어요(버전 ${to}).`,
    byAuthor: (name: string) => `${name} 저장`,
    systemAuthor: "알 수 없는 사용자",
  },

  diff: {
    caption: (before: string, after: string) => `${before} → ${after} 비교`,
    added: "추가된 줄",
    removed: "삭제된 줄",
    change: "변경",
    content: "내용",
    same: "두 내용이 같아요.",
    summary: (removed: number, added: number) => `${removed}줄 삭제, ${added}줄 추가`,
  },

  users: {
    title: "사용자",
    add: "사용자 추가",
    email: "이메일",
    name: "이름",
    role: "역할",
    active: "활성",
    lastLogin: "마지막 로그인",
    ownedMcps: "소유 MCP",
    neverLoggedIn: "로그인 기록 없음",
    lastAdmin: "현재 활성 Admin이 이 사용자 1명뿐이에요. 다른 사용자를 먼저 Admin으로 지정하면 바꿀 수 있어요.",
    activeAdmins: (n: number | string) => `Admin ${n}명`,
    activeAdminsLabel: "활성 Admin",
    revokeNotice: "역할을 바꾸거나 비활성화하면 그 사용자는 바로 로그아웃돼요.",
    revokeSelf: "내 계정이라 저장하면 나도 로그아웃돼요. 다시 로그인해야 해요.",
    empty: "등록된 사용자가 없어요.",
    listLabel: "사용자 목록",
    loadError: "사용자 목록을 불러오지 못했어요. 새로 고친 뒤 다시 시도하세요.",
    inactive: "비활성",
    addTitle: "사용자 추가",
    addLead: "추가한 사람은 이 이메일로 받은 인증 코드로 로그인해요.",
    addSubmit: "추가",
    adding: "추가하는 중…",
    added: (name: string) => `${name}을(를) 추가했어요. 이 이메일로 로그인할 수 있어요.`,
    emailRequired: "이메일을 입력하세요.",
    nameRequired: "이름을 입력하세요.",
    nameTooLong: "이름은 100자까지 쓸 수 있어요.",
    actions: "동작",
    editNameShort: "이름 편집",
    editName: (name: string) => `${name} 이름 편집`,
    editNameTitle: "이름 바꾸기",
    nameSaved: "이름을 바꿨어요.",
    roleTitle: (name: string, role: string) => `${name}의 역할을 ${role}(으)로 바꿀까요?`,
    roleConfirm: "역할 바꾸기",
    roleChanged: (name: string, role: string) => `${name}의 역할을 ${role}(으)로 바꿨어요.`,
    deactivateTitle: (name: string) => `${name}을(를) 비활성화할까요?`,
    deactivateConfirm: "비활성화",
    deactivated: (name: string) => `${name}을(를) 비활성화했어요.`,
    activated: (name: string) => `${name}을(를) 다시 활성화했어요.`,
  },

  settings: {
    title: "설정",
    monitoring: "감시 주기",
    retention: "로그 보존",
    startType: "부팅 시작 유형",
    otp: "OTP 공급자",
    alerts: "알림 채널",
    retentionRange: "보존 기간은 7–3,650일 사이로 정해요.",
    retentionBelowCompress: "압축 시작 일수는 보존 기간보다 길 수 없어요. 두 값을 함께 고치세요.",
    compressHint: "1일 이상, 보존 기간 이하로 정해요.",
    loadError: "설정을 불러오지 못했어요. 새로 고친 뒤 다시 시도하세요.",
    discard: "변경 취소",
    checking: "삭제될 로그를 확인하는 중…",
    currentLogs: "지금 로그",
    currentUsage: (files: number | string, size: string) => `${files}개 파일, ${size}`,
    oldest: "가장 오래된 날짜",
    noLogs: "아직 저장된 로그 파일이 없어요.",
    usageError: "로그 용량을 불러오지 못했어요.",
    previewError: "삭제될 로그를 확인하지 못했어요. 저장하지 않았어요. 잠시 뒤에 다시 시도하세요.",
    confirmDeleteTitle: "오래된 로그를 삭제할까요?",
    confirmBody: (from: number | string, to: number | string) =>
      `보존 기간을 ${from}일에서 ${to}일로 줄이면 아래 로그가 삭제 대상이 돼요. 삭제한 로그는 되살릴 수 없어요.`,
    confirmReduceTitle: "보존 기간을 줄일까요?",
    confirmBodyNone: (from: number | string, to: number | string) =>
      `보존 기간을 ${from}일에서 ${to}일로 줄여요. 지금 기준으로는 삭제될 로그가 없어요.`,
    deleteRange: "삭제될 기간",
    deleteFiles: "파일",
    deleteSize: "용량",
    filesCount: (n: number | string) => `${n}개`,
    noDelete: "삭제될 로그 없음",
    confirmDelete: "줄이고 삭제",
    confirmReduce: "보존 기간 줄이기",
    startTypes: START_TYPES,
    /** The confirm dialog of a shorter retention: indexed lines in the days to delete. */
    retentionDeleteEvents: (n: number) => `로그 기록 ${n.toLocaleString("ko-KR")}건이 함께 삭제돼요.`,
    retentionRunsSoon: "저장하면 몇 초 안에 정리를 시작해요.",
    /** The Windows service next to the boot start type (GET /api/service). */
    service: {
      title: "Windows 서비스",
      notInstalled: "Windows 서비스로 설치되어 있지 않아요. 설치하면 이 시작 유형이 적용돼요.",
      current: (type: StartType | "disabled") => `지금 서비스 시작 유형: ${SERVICE_START_TYPES[type] ?? type}`,
      // the server applies the setting when it is changed and when the service starts (W25), not on
      // a save that leaves it as it is
      mismatch: "서비스의 시작 유형이 이 설정과 달라요. 서비스가 다시 시작할 때 이 설정으로 맞춰요.",
      devMode: "개발용으로 실행 중이라 서비스가 없어요. 시작 유형은 저장만 돼요.",
      disabled: "Windows에서 서비스가 사용 안 함으로 되어 있어 이 설정을 적용하지 않아요. 다시 쓰려면 서비스 관리자에서 바꾸세요.",
      loadError: "서비스 상태를 확인하지 못했어요. 새로 고친 뒤 다시 시도하세요.",
    },
    otpDummy: "Dummy(개발용)",
    fields: {
      ping_interval_sec: "ping 주기(초)",
      issue_check_interval_sec: "이슈 점검 주기(초)",
      confirm_interval_sec: "재확인 주기(초)",
      log_retention_days: "로그 보존 기간(일)",
      log_compress_after_days: "압축 시작(일)",
      service_start_type: "부팅 시작 유형",
      otp_provider: "OTP 공급자",
    },
  },

  notice: {
    title: "사전 고지",
    lead: "원격 데스크톱으로 연결할 때마다 보여 줄 안내예요. 버튼은 하나만 표시돼요.",
    fields: {
      title: "제목",
      body: "본문",
      button_text: "버튼 문구",
    },
    count: (used: number, max: number) => `${used.toLocaleString("ko-KR")}/${max.toLocaleString("ko-KR")}자`,
    tooLong: (max: number) => `${max.toLocaleString("ko-KR")}자를 넘었어요. 줄여야 저장할 수 있어요.`,
    required: {
      title: "제목을 입력하세요.",
      body: "본문을 입력하세요.",
      button_text: "버튼 문구를 입력하세요.",
    },
    insertBold: "굵게",
    insertList: "목록",
    formatLabel: "본문 서식",
    markupHelp: "빈 줄로 문단을 나누고, 줄을 “- ”로 시작하면 목록, **글자**는 굵게 표시돼요.",
    previewLabel: "고지 미리보기",
    previewNote: "입력하는 대로 바로 바뀌어요.",
    fullPreview: "전체 화면 미리보기",
    fullPreviewNote: "저장된 내용을 실제 고지와 똑같이 이 화면 위에 띄워요.",
    /** The full-screen preview's own line: what it shows and that its button records nothing. */
    fullPreviewDescription: "저장된 내용이에요. 고지의 버튼을 눌러도 기록되지 않고 미리보기만 닫혀요.",
    fullPreviewClose: "미리보기 닫기",
    /** `/notice` opened directly (preview mode only): the way back to the editor. */
    backToAdmin: "관리 화면으로 돌아가기",
    savedVersion: (v: number) => `저장했어요(버전 ${v}).`,
    loadError: "사전 고지를 불러오지 못했어요. 새로 고친 뒤 다시 시도하세요.",
    draftRestored: "저장하지 않은 초안을 되살렸어요.",
    discardDraft: "초안 버리기",
    /** The notice was saved again (another tab, a revert) after the draft was made. */
    draftStale: (v: number) => `초안을 만든 뒤에 새 버전(버전 ${v})이 저장됐어요. 버전 이력에서 비교한 뒤 저장하세요.`,
    /** The same, while the edits are on screen: Save would overwrite that version. */
    newerWhileEditing: (v: number) => `편집하는 동안 새 버전(버전 ${v})이 저장됐어요. 지금 저장하면 그 버전을 덮어써요. 버전 이력에서 비교한 뒤 저장하세요.`,
    versions: "버전 이력",
    versionsError: "버전 이력을 불러오지 못했어요. 새로 고친 뒤 다시 시도하세요.",
    versionLabel: (v: number) => (v === 0 ? "기본 문구" : `버전 ${v}`),
    defaultVersion: "기본 문구",
    defaultNote: "저장한 적이 없으면 기본 문구가 표시돼요. 언제든 기본 문구로 되돌릴 수 있어요.",
    builtInMeta: "처음부터 들어 있는 문구",
    systemAuthor: "알 수 없는 사용자",
    current: "현재",
    /** The compare view's table of the short fields that differ. */
    fieldChanges: "제목·버튼 문구 비교",
    fieldHeader: "항목",
    /** The body diff's summary when only the title or button text differ. */
    bodySame: "본문은 같아요.",
    currentNote: "지금 표시되는 버전이에요.",
    pickVersion: "버전을 고르면 저장된 내용과 비교해요.",
    versionError: "이 버전을 불러오지 못했어요. 다시 골라 보세요.",
    revert: "이 버전으로 되돌리기",
    reverted: (v: number) => (v === 0 ? "기본 문구에서 되돌림" : `버전 ${v}에서 되돌림`),
    revertTitle: (v: number) => (v === 0 ? "기본 문구로 되돌릴까요?" : `버전 ${v}의 내용으로 되돌릴까요?`),
    revertBody: "이 버전의 내용을 새 버전으로 저장해요. 지금 내용도 버전 이력에 남아요.",
    revertKeepsEdits: "편집 중인 내용은 저장하지 않은 채로 그대로 남아요.",
    revertAction: "되돌리기",
    reverting: "되돌리는 중…",
    revertedTo: (from: number, to: number) =>
      from === 0 ? `기본 문구로 되돌렸어요(버전 ${to}).` : `버전 ${from}의 내용으로 되돌렸어요(버전 ${to}).`,
    unchanged: "바뀐 내용이 없어 새 버전을 만들지 않았어요.",
    acknowledged: "확인했어요. 이 창을 닫아도 돼요.",
    loadFailed: "고지 내용을 불러오지 못했어요. 새로 고친 뒤 다시 시도하세요.",
    /** The notice window (display mode): the token left the address bar, so a reload cannot help. */
    loadFailedRetry: "고지 내용을 불러오지 못했어요. 다시 시도하세요.",
    displayExpired: "이 고지는 이미 확인했거나 새 고지로 바뀌었어요. 이 창을 닫아도 돼요.",
    ackFailed: "확인한 사실을 서버에 남기지 못했어요. 다시 시도하세요.",
    retry: "다시 시도",
    /** Version 0: must equal server/app/notice/defaults.py DEFAULT_NOTICE (ko.test.ts checks). */
    builtIn: {
      title: "원격 접속 행동 감사 안내",
      body:
        "**이 원격 데스크톱 연결에서 하는 작업은 보안 감사를 위해 기록됩니다.**\n" +
        "\n" +
        "기록하는 내용은 다음과 같습니다.\n" +
        "\n" +
        "- 접속 정보: 사용자, 접속한 PC 이름과 IP 주소, 연결 시각\n" +
        "- 실행한 프로그램과 명령\n" +
        "- 창 전환 기록\n" +
        "\n" +
        "이 안내는 연결할 때마다 표시됩니다. 확인을 누르면 작업을 계속할 수 있습니다.",
      button_text: "확인",
    },
  },

  /**
   * Contextual help behind the “i” buttons (InfoTip; docs/design/help-tips.md lists where each one
   * is shown). One or two sentences, defaults where they help; the allowed ranges are already on
   * screen under the fields. Never the same string as a visible one: tests find texts by content.
   */
  help: {
    /** The button's name: starts with the visible label (WCAG 2.5.3 Label in Name). */
    label: (label: string) => `${label} 설명`,
    states: STATE_HELP,
    issues: ISSUE_HELP,
    stateLegend: { lead: "MCP는 감시 결과에 따라 아래 여섯 상태 중 하나예요.", items: pairs(STATE_NAMES, STATE_HELP) },
    issueLegend: { lead: "상태 옆에 이슈가 붙으면 무엇이 문제인지 알려 줘요.", items: pairs(ISSUE_NAMES, ISSUE_HELP) },
    stateLabel: "MCP 상태",
    latency:
      "마지막 점검에서 응답이 오기까지 걸린 시간이에요. ping 주기마다 새로 재고, 점검 방식에 따라 MCP ping·TCP 연결·ICMP 응답 시간이에요.",
    uptime: "최근 24시간 동안 성공한 점검의 비율이에요. 점검 모드였던 시간은 빼고 계산해요.",
    countdown: "조치 대기 시간이 끝나면 자동 조치를 해요. 그 전에 점검이 정상으로 돌아오면 조치하지 않아요.",
    devOtp:
      "실제 메일·문자를 보내지 않는 개발용 공급자(Dummy)예요. 인증 코드는 서버 PC의 data\\dev\\otp-outbox.log에 쌓여요. 다른 PC에서 로그인하는 사람에게는 관리자가 코드를 전해 줘야 해요.",
    gpu:
      "작업 관리자의 GPU 사용률과 같은 값이에요. 3D·복사·비디오 디코드 같은 GPU 엔진 가운데 가장 바쁜 엔진이 측정 간격 동안 일한 비율이고, GPU가 여러 개면 가장 바쁜 GPU를 보여 줘요. 전용 메모리는 GPU에 달린 메모리 사용량이에요(내장 GPU는 공유 메모리를 써서 거의 0이에요). 70% 이상은 주의, 90% 이상은 위험 색이에요.",
    setupAdmin:
      "Admin은 사용자·전역 설정·사전 고지 관리와 MCP 소유권 이전까지 모든 기능을 써요. 다른 Admin은 나중에 사용자 화면에서 더 만들 수 있어요.",
    session: {
      state: {
        lead: "Windows가 알려 주는 원격 데스크톱 세션 상태예요.",
        items: [
          ["사용 중", "로그온해 화면을 쓰고 있어요."],
          ["잠김", "로그온은 유지한 채 화면을 잠갔어요."],
          ["연결 끊김", "로그온은 남아 있지만 원격 연결이 끊겼어요."],
          ["로그온 전", "연결은 됐지만 아직 로그인 화면이에요."],
        ],
      },
      idle: "이 세션에서 마지막으로 키보드나 마우스를 쓴 뒤 지난 시간이에요. 1분 단위로 바뀌어요.",
      reverseDns: "클라이언트 IP 주소를 DNS에 거꾸로 물어 얻은 컴퓨터 이름이에요. 2초 안에 답이 없거나 이름이 없으면 비워 둬요.",
      notice: "이번 연결에서 사전 고지 창의 확인 버튼을 눌렀는지 보여 줘요. 확인 전이면 고지 창이 아직 떠 있어요.",
    },
    dashboard: {
      recent: "정상이 아닌 상태로 바뀐 기록과 스크립트 실행 기록 중 최근 10건이에요. 자동은 자동 복구, 수동은 사람이 누른 조치, 부팅 시는 부팅 자동 시작이에요.",
      loginFailures: "최근 24시간 동안 시간대별 로그인 실패 건수예요. 웹 로그인은 관리 화면의 인증 코드 실패, 원격 데스크톱은 Windows 로그온 실패(이벤트 4625)예요.",
      tamper:
        "감시를 피하거나 기록을 지우려는 시도로 보이는 일이에요. 세션 에이전트 종료, 스크립트·로그 파일 변경이나 삭제, Windows 이벤트 로그 지움, 감사 정책 변경 같은 일을 잡아요.",
    },
    mcp: {
      actions: {
        lead: "스크립트는 이 PC에서 서비스 권한(SYSTEM)으로 실행되고, 한 MCP에는 한 번에 하나만 실행돼요. 결과는 이력 탭에 남아요.",
        items: [
          ["시작", "시작 스크립트를 실행해요. 점검 모드였다면 풀려요."],
          ["다시 시작", "다시 시작 스크립트를 실행해요. 없으면 종료 스크립트 뒤에 시작 스크립트를 실행해요. 점검 모드였다면 풀려요."],
          ["종료", "종료 스크립트를 실행하고 점검 모드로 바꿔 자동 복구를 멈춰요."],
        ],
      },
      owner:
        "소유자만 이 MCP의 스크립트를 편집할 수 있고, MCP 개발자는 자기가 소유한 MCP만 삭제할 수 있어요. 설정 변경과 직접 조치는 로그인한 사용자 누구나 할 수 있고, 소유권은 Admin이 이전해요.",
      recoveryGroupLabel: "자동 복구 동작",
      recoveryGroup:
        "이상이 조치 대기 시간보다 오래 이어지면 스크립트를 실행하고, 시작 유예 시간이 지나면 다시 확인해요. 집계 구간 안에서 최대 횟수를 넘기면 종료 스크립트를 실행하고 실패 상태로 멈춰요.",
      fields: {
        host: "이 PC의 주소(localhost, 127.0.0.1, 이 PC의 IP나 이름)면 포트를 연 프로세스까지 확인해 프로세스 중지를 가려내요. 다른 PC면 응답만 보고, 실패하면 ICMP ping으로 네트워크를 확인해요.",
        path: "MCP ping 점검이 요청을 보내는 HTTP 경로예요. 기본값은 /mcp이고, TCP 연결과 ICMP ping은 경로를 쓰지 않아요.",
        probe: {
          lead: "응답을 확인하는 방법이에요. 한 번의 점검은 3초 안에 답이 와야 성공이에요.",
          items: [
            ["MCP ping", "MCP 프로토콜의 ping을 HTTP로 보내요. MCP가 실제로 요청을 처리하는지까지 봐서 가장 정확해요(기본값)."],
            ["TCP 연결", "포트에 연결만 해 봐요. MCP ping을 지원하지 않는 서버에 써요."],
            ["ICMP ping", "PC가 ping에 답하는지만 봐요. 포트와 경로는 확인하지 않아요."],
          ],
        },
        expected_process_name:
          "이 PC의 MCP일 때 포트를 연 프로세스 이름(예: python.exe)과 비교해요. 다르면 다른 프로세스가 포트 사용으로 알려요. 대소문자는 가리지 않아요.",
        action_delay_sec:
          "이상을 처음 감지한 뒤 자동 조치까지 기다리는 시간이에요. 그 사이 정상으로 돌아오면 조치하지 않고, 보드의 카운트다운이 이 시간이에요. 기본 30초.",
        startup_grace_sec:
          "시작·다시 시작 스크립트가 성공한 뒤 MCP가 뜰 때까지 기다렸다가 다시 점검해요. 0이면 바로 확인해요. 기본 30초.",
        max_auto_actions:
          "집계 구간 안에서 자동 조치를 할 수 있는 횟수예요. 다 쓰고도 문제가 남으면 종료 스크립트를 실행하고 실패 상태가 돼요. 직접 조치와 부팅 시 시작은 세지 않아요. 기본 3회.",
        window_sec: "최대 자동 조치 횟수를 세는 기간이에요. 지금부터 이 시간 전까지의 자동 조치만 세요. 기본 600초(10분).",
        script_timeout_sec:
          "스크립트가 이 시간 안에 끝나지 않으면 프로세스 트리째 강제로 끝내고 시간 초과로 기록해요. 스크립트가 띄운 MCP 프로세스는 기다리지 않아요. 기본 120초.",
        auto_recovery:
          "켜면 이상이 조치 대기 시간보다 오래 이어질 때 프로세스 중지는 시작 스크립트, 응답 없음은 다시 시작 스크립트를 자동으로 실행해요. 네트워크 문제와 다른 프로세스 이슈는 켜져 있어도 알리기만 해요.",
        maintenance:
          "켜 두는 동안 상태 판단과 자동 복구를 멈추고 그 시간을 가동률에서 빼요. 끄면 정상 상태에서 다시 감시해요. 종료 버튼도 점검 모드를 켜고, 시작·다시 시작은 풀어요.",
        autostart_on_boot:
          "서비스가 시작한 뒤 첫 점검에서 프로세스 중지면 시작 스크립트를 한 번 실행해요. 자동 조치 횟수에는 세지 않고, 점검 모드면 실행하지 않아요.",
      },
      chart: {
        lead: "고른 기간의 점검 기록을 시간대별로 묶었어요.",
        items: [
          ["평균·최대 지연", "성공한 점검의 응답 시간 평균과 가장 긴 값이에요."],
          ["가동률", "성공한 점검의 비율이에요. 점검 모드였던 시간은 빼요."],
          ["상태 전이", "세로선은 상태가 바뀐 시각이에요."],
        ],
      },
      actionLog: {
        lead: "시간을 누르면 스크립트의 출력을 볼 수 있어요.",
        items: [
          ["계기", "자동은 자동 복구, 수동은 사람이 누른 조치, 부팅 시는 부팅 자동 시작이에요."],
          ["결과", "실패는 종료 코드가 0이 아님, 시간 초과는 제한 시간을 넘겨 강제 종료, 실행 오류는 스크립트를 실행하지 못한 경우예요."],
          ["종료 코드", "스크립트가 끝나며 돌려준 값이에요. 0이면 성공이에요."],
        ],
      },
    },
    scripts: {
      kinds: {
        start: `시작 버튼, 프로세스 중지 자동 복구, 부팅 시 자동 시작이 이 스크립트를 실행해요. ${ENV_VARS}`,
        stop: `종료 버튼, 그리고 자동 조치를 다 쓰고도 실패했을 때 실행해요. MCP를 삭제할 때는 실행하지 않아요. ${ENV_VARS}`,
        restart: `다시 시작 버튼과 응답 없음 자동 복구가 실행해요. 없으면 종료 스크립트 뒤에 시작 스크립트를 실행해요. ${ENV_VARS}`,
      },
      ext: ".ps1은 PowerShell로, .bat와 .cmd는 cmd로 실행해요. 종료 코드 0을 성공으로 봐요.",
      versions: "저장할 때마다 버전이 하나씩 쌓여요. 되돌리기는 고른 버전의 내용을 새 버전으로 저장하므로 지금 내용도 그대로 남아요.",
    },
    sessions: {
      kind: {
        lead: "연결이 어떻게 시작됐는지예요.",
        items: [
          ["새 로그온", "새로 로그인해 세션을 열었어요."],
          ["다시 연결", "연결이 끊긴 채 남아 있던 세션에 다시 연결했어요."],
          ["서비스 시작 때 접속 중", "MCP Monitor 서비스가 시작할 때 이미 접속해 있던 세션이에요."],
        ],
      },
      notice: "고지 창이 마지막으로 뜬 뒤 확인 버튼을 누르기까지 걸린 시간이에요. 확인 안 함은 누르지 않고 연결이 끝났거나 창이 아직 떠 있는 경우예요.",
      logonType: "Windows 로그온 실패 이벤트(4625)의 로그온 유형이에요. 원격 데스크톱은 보통 원격 대화형(10)이나 네트워크(3)로 남아요.",
      status: "Windows가 알려 준 실패 원인 코드예요. 예: 0xC000006D 이름이나 암호 오류, 0xC000006A 잘못된 암호, 0xC0000234 계정 잠김.",
      collectors:
        "로그와 세션 정보를 모으는 서비스 안의 수집기예요. eventlog는 Windows 이벤트 로그를, wts는 원격 데스크톱 세션 목록을 읽어요. 수집 중단이면 그동안의 기록이 빠질 수 있어요.",
    },
    logs: {
      session: "Windows가 원격 데스크톱 세션마다 붙이는 번호예요. 표의 세션 열과 같은 값이고, 세션이 끝나면 같은 번호를 다른 접속이 다시 쓸 수 있어요.",
      view: {
        items: [
          ["표", "기록을 시간순으로 한 줄씩 보여 줘요."],
          ["타임라인", "사용자마다 시간대별 기록 수를 칸으로 보여 줘요. 칸을 누르면 그 사용자와 시간의 표를 열어요."],
        ],
      },
    },
    audit: {
      kinds: {
        items: [
          ["관리 작업", "관리 화면에서 한 변경과 권한이 없어 거부된 요청이에요."],
          ["로그인", "관리 화면의 인증 코드 요청과 로그인 시도예요."],
          ["전체", "두 가지를 함께 보여 줘요."],
        ],
      },
      channel: `요청이 들어온 길이에요. 로컬은 이 PC의 ${LOCAL_ADDRESS}, 원격은 다른 PC에서 8701 포트로 들어온 요청이에요.`,
      result: {
        items: [
          ["성공", "요청대로 처리했어요."],
          ["실패", "로그인 코드가 틀렸거나 로그인이 잠겼어요."],
          ["거부", "권한이 없거나 보안 확인이 맞지 않아 서버가 막았어요."],
          ["오류", "처리하는 중에 서버에서 오류가 났어요."],
        ],
      },
    },
    users: {
      role: {
        items: [
          ["Admin", "사용자·전역 설정·사전 고지 관리와 MCP 소유권 이전을 포함해 모든 기능을 써요."],
          ["MCP 개발자", "MCP 등록·설정·조치와 로그 조회를 하고, 자기가 소유한 MCP의 스크립트를 편집하고 삭제해요."],
        ],
      },
      active: "끄면 그 사용자는 로그인할 수 없고 지금 로그인한 세션도 바로 끝나요. 남긴 기록은 지워지지 않아요.",
      ownedMcps: "이 사용자가 소유자인 MCP 수예요. 소유자만 그 MCP의 스크립트를 편집할 수 있어요.",
      activeAdmins:
        "지금 활성 상태인 Admin 수예요. Admin이 한 명도 없으면 아무도 사용자와 설정을 관리할 수 없어서, 마지막 활성 Admin은 역할을 바꾸거나 비활성화할 수 없어요. 그 사람을 바꾸려면 먼저 다른 사용자를 Admin으로 지정하세요.",
    },
    settings: {
      ping_interval_sec: "지연과 가동률을 재려고 모든 MCP에 점검 요청을 보내는 주기예요. 이 점검으로는 상태를 바꾸지 않아요. 기본 5초.",
      issue_check_interval_sec: "정상인 MCP에 문제가 생겼는지 점검하는 주기예요. 짧을수록 이상을 빨리 알아채요. 기본 10초.",
      confirm_interval_sec: "이상 감지나 복구 중인 MCP를 다시 확인하는 주기예요. 조치 대기와 복구 확인이 이 간격으로 진행돼요. 기본 1초.",
      log_retention_days:
        "이 기간이 지난 날짜의 로그 파일과 색인, 세션·조치 이력을 매일 03:30에 지워요. 줄여서 저장하면 지울 양을 먼저 보여 주고 몇 초 안에 정리해요. 기본 180일.",
      log_compress_after_days:
        "이 일수가 지난 로그 파일을 gzip으로 압축해 디스크를 아껴요. 압축한 로그도 그대로 조회돼요. 어제와 오늘 파일은 압축하지 않아요. 기본 30일.",
      service_start_type: {
        lead: "Windows가 켜질 때 MCP Monitor 서비스를 시작하는 방법이에요. 바꾸면 서비스에 바로 적용해요.",
        items: [
          ["자동", "부팅하자마자 시작해요."],
          ["자동(지연된 시작)", "다른 자동 서비스가 뜬 뒤 잠시 있다가 시작해요. 기본값이에요."],
          ["수동", "누군가 서비스를 직접 시작할 때만 돌아요. 그동안은 감시하지 않아요."],
        ],
      },
      otp_provider: "로그인 인증 코드를 보내는 방법이에요. 지금은 Dummy(개발용)뿐이라 코드가 서버 PC의 data\\dev\\otp-outbox.log에 남아요.",
    },
    notice: {
      what: "원격 데스크톱으로 연결할 때마다 그 세션 화면 가운데에 항상 위에 뜨는 창으로 보여 줘요. 표시와 확인은 로그의 사전 고지 카테고리와 세션 화면에 남아요.",
      button: "고지 창의 하나뿐인 버튼에 쓰여요. 이 버튼을 눌러야 창이 닫히고, 누른 사실과 걸린 시간이 기록돼요.",
    },
  },

  deny: {
    login: "로그인하면 쓸 수 있어요.",
    local_only: `로컬 관리 모드(이 PC의 ${LOCAL_ADDRESS})에서만 쓸 수 있어요.`,
    admin_only: "Admin만 쓸 수 있어요.",
    owner_only: "이 MCP의 소유자만 쓸 수 있어요.",
    no_owner: "소유자가 없는 MCP예요. Admin이 소유자를 지정하면 쓸 수 있어요.",
    running: "조치가 진행 중이에요. 끝나면 다시 쓸 수 있어요.",
    config_error: "저장된 설정에 오류가 있어 실행할 수 없어요. 설정을 먼저 고치세요.",
    planned_sessions: "세션 화면은 아직 준비 중이에요.",
    planned_logs: "로그 조회는 아직 준비 중이에요.",
    planned_audit: "감사 로그는 아직 준비 중이에요.",
    planned_alerts: "알림 채널은 아직 준비 중이에요.",
    unchanged: "아직 바뀐 내용이 없어요.",
  } satisfies Record<DisabledReason, string>,

  errors: {
    validation: "입력값을 확인하세요. 허용 범위를 벗어난 값이 있어요.",
    invalid_email: "이메일 주소를 name@example.com 형식으로 입력하세요.",
    rate_limited: "요청이 너무 잦아요. 잠시 뒤에 다시 시도하세요.",
    login_required: "로그인이 필요해요. 다시 로그인하세요.",
    forbidden: "이 작업을 할 권한이 없어요.",
    csrf: "보안 확인이 만료됐어요. 페이지를 새로 고친 뒤 다시 시도하세요.",
    not_found: "찾는 항목이 없어요. 이미 삭제됐을 수 있어요.",
    bootstrap_done: "초기 설정은 이미 끝났어요. 로그인하세요.",
    user_exists: "이미 등록된 이메일이에요.",
    last_admin: "마지막 Admin은 역할을 바꾸거나 비활성화할 수 없어요. 다른 사용자를 먼저 Admin으로 지정하세요.",
    name_taken: "같은 이름의 MCP가 이미 있어요. 다른 이름을 쓰세요.",
    endpoint_taken: "다른 MCP가 이미 이 호스트와 포트를 쓰고 있어요.",
    action_in_progress: "이 MCP에 다른 조치가 진행 중이에요. 끝난 뒤에 다시 시도하세요.",
    script_required: "시작 스크립트와 종료 스크립트는 지울 수 없어요.",
    scripts_required: "MCP를 등록하려면 시작 스크립트와 종료 스크립트가 모두 필요해요.",
    script_too_large: "스크립트가 64KB를 넘어요. 내용을 줄이세요.",
    script_encoding: ".bat·.cmd에 이 PC의 코드 페이지로 저장할 수 없는 글자가 있어요. 그 글자를 빼거나 .ps1로 저장하세요.",
    script_empty: "스크립트 내용이 비어 있어요.",
    invalid_owner: "이 사용자는 소유자로 지정할 수 없어요. 활성 사용자를 고르세요.",
    too_many_streams: "실시간 연결이 너무 많아요. 다른 탭을 닫으면 다시 연결돼요.",
    body_too_large: "보낸 내용이 너무 커요. 512KB 이하로 줄이세요.",
    bad_host: "허용되지 않은 주소로 접속했어요. 서버 주소를 확인하세요.",
    internal: "서버에서 오류가 났어요. 잠시 뒤에 다시 시도하세요.",
    unavailable: "잠시 연결을 확인하지 못했어요. 다시 시도하세요.",
    method_not_allowed: "지원하지 않는 요청이에요. 페이지를 새로 고친 뒤 다시 시도하세요.",
    network: "서버에 연결할 수 없어요. 네트워크와 서비스 상태를 확인하세요.",
    session_changed: "다른 탭에서 다른 계정으로 로그인해 요청을 보내지 않았어요. 지금 로그인한 계정을 확인한 뒤 다시 시도하세요.",
  } satisfies Record<ApiErrorCode, string>,

  toasts: {
    pending: (name: string, kind: ActionKind) => `${name} ${actionKind[kind]} 중…`,
    ok: (name: string, kind: ActionKind) => `${name} ${actionKind[kind]} 완료`,
    failed: (name: string, kind: ActionKind) => `${name} ${actionKind[kind]} 실패`,
    unknown: (name: string) => `${name} 조치 결과를 확인하지 못했어요. 이력에서 확인하세요.`,
    viewHistory: "이력 보기",
    restartStep: "종료 단계를 마쳤어요. 이어서 시작하는 중이에요.",
    exitAndDuration: (code: number | string, duration: string) => `종료 코드 ${code}, ${duration} 걸렸어요.`,
    duration: (duration: string) => `${duration} 걸렸어요.`,
    timedOut: (duration: string) => `제한 시간을 넘겨 중단했어요. ${duration} 걸렸어요.`,
    runError: "스크립트를 실행하지 못했어요. 이력에서 원인을 확인하세요.",
  },
} as const;

/** Korean message for a server error code; unknown codes read as `internal`. */
export function messageForError(code: string): string {
  return Object.hasOwn(copy.errors, code) ? copy.errors[code as ApiErrorCode] : copy.errors.internal;
}
