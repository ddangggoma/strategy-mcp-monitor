// Every Korean string on screen lives here (Global Constraints). Voice: docs/design/design-system.md
// "Copy". UI text is 해요체: short, active, no apologies, no exclamation marks; errors say what
// happened and what to do next. The audit notice is a formal notice and uses 합니다체.
// Fixed terms (roles, channel, states, issues) are pinned by ko.test.ts; do not reword them.

export const API_ERROR_CODES = [
  "validation", "invalid_email", "rate_limited", "login_required", "forbidden", "csrf", "not_found",
  "bootstrap_done", "user_exists", "last_admin", "name_taken", "endpoint_taken", "action_in_progress",
  "script_required", "scripts_required", "script_too_large", "script_encoding", "script_empty",
  "invalid_owner", "too_many_streams", "body_too_large", "bad_host", "internal", "method_not_allowed",
  "network",
] as const;
/** Server `{"error": code}` values, plus `network` for a fetch that never reached the server. */
export type ApiErrorCode = (typeof API_ERROR_CODES)[number];

export const DISABLED_REASONS = [
  "login", "local_only", "admin_only", "owner_only", "no_owner", "running", "config_error",
  "planned_sessions", "planned_logs", "planned_audit", "planned_alerts",
] as const;
/** Why a visible control is unavailable (shown next to it, never hidden: spec §4.4). */
export type DisabledReason = (typeof DISABLED_REASONS)[number];

export type ActionKind = "start" | "restart" | "stop";

const actionKind: Record<ActionKind, string> = { start: "시작", restart: "다시 시작", stop: "종료" };

const LOCAL_ADDRESS = "http://127.0.0.1:8700";

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
    search: "검색",
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
    accountMenu: (name: string) => `계정 메뉴(${name})`,
    skipToContent: "본문으로 건너뛰기",
    commandTitle: "빠른 이동",
    commandHint: "이동할 화면이나 MCP 이름을 입력하세요.",
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
    localHint: "이 PC에서 접속했어요. 모든 관리 기능을 쓸 수 있어요.",
    externalHint: `다른 PC에서 접속했어요. 사용자·설정·고지 관리와 MCP 등록·삭제는 이 PC의 ${LOCAL_ADDRESS}에서 할 수 있어요.`,
  },

  roles: {
    developer: "MCP 개발자",
    admin: "Admin",
  },

  states: {
    HEALTHY: "정상",
    SUSPECT: "이상 감지",
    ACTION: "조치 중",
    RECOVERING: "복구 중",
    FAILED: "실패",
    MAINTENANCE: "점검 중",
  },

  issues: {
    PROCESS_DOWN: "프로세스 중지",
    UNRESPONSIVE: "응답 없음",
    NETWORK_DOWN: "네트워크 연결 안 됨",
    WRONG_PROCESS: "다른 프로세스가 포트 사용",
  },

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
    sessionsNotReady: "원격 접속 정보는 다음 업데이트부터 표시돼요.",
    latency: "지연",
    uptime24h: "24시간 가동률",
    lastCheck: "마지막 점검",
    noData: "아직 측정값이 없어요",
    noRecord: "기록 없음",
    actionIn: (sec: number | string) => `${sec}초 뒤 자동 조치`,
    autoActionOff: "자동 조치 꺼짐",
    sparklineLabel: (name: string) => `${name} 최근 지연 추이`,
    sparklineSummary: (label: string, avg: number | string, max: number | string) => `${label}: 평균 ${avg}ms, 최대 ${max}ms`,
    running: (kind: ActionKind) => `스크립트 실행 중: ${actionKind[kind]}`,
    maintenanceOn: "점검 모드라 자동 복구를 하지 않아요",
    sessionsTitle: "원격 접속",
    setupHint: "아직 Admin이 없어요. 이 PC에서 첫 Admin을 만들면 관리 기능을 쓸 수 있어요.",
    setupLink: "초기 설정 시작",
    session: {
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
        notice: "고지 확인",
      },
      noticeYes: "확인함",
      noticeNo: "확인 안 함",
    },
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
    codeExhausted: "이 코드는 5번 틀려서 더 쓸 수 없어요. 새 코드를 받으세요.",
    failureHint: "1시간 안에 10번 틀리면 이 이메일은 최대 1시간 동안 로그인할 수 없어요.",
    lockedFor: (minutes: number) => `로그인 시도가 너무 많아 잠겼어요. ${minutes}분 뒤에 다시 시도하세요.`,
    resend: "코드 다시 받기",
    resendIn: (sec: number) => `${sec}초 뒤에 다시 받을 수 있어요`,
    changeEmail: "다른 이메일로 로그인",
    devBadge: "개발용 OTP 모드",
    devHint: "개발용 OTP: 서비스 콘솔을 확인하세요.",
    unknownEmailNote: "코드가 오지 않으면 Admin에게 이메일 등록을 요청하세요.",
  },

  setup: {
    title: "처음 사용할 Admin 만들기",
    lead: "이 PC에서 처음 접속했어요. 관리를 맡을 Admin의 이메일과 이름을 입력하세요.",
    email: "이메일",
    name: "이름",
    submit: "Admin 만들기",
    done: "Admin을 만들었어요. 이 이메일로 로그인하세요.",
    externalOnly: `초기 설정은 이 PC의 ${LOCAL_ADDRESS}에서만 할 수 있어요.`,
  },

  dashboard: {
    title: "대시보드",
    mcpSummary: "MCP 요약",
    currentSessions: "현재 세션",
    recentActivity: "최근 이슈와 조치",
    noActivity: "최근 이슈나 조치가 없어요.",
    loginFailures: "로그인 실패 추이",
    bypassEvents: "우회 탐지 이벤트",
    viewAll: "모두 보기",
  },

  mcp: {
    title: "MCP",
    create: "MCP 등록",
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
    configError: "저장된 설정에 오류가 있어 이 MCP를 감시하지 않고 있어요. 설정을 고쳐 저장하거나 MCP를 삭제하세요.",
    nameRule: "글자, 숫자, 공백, 마침표(.), 밑줄(_), 하이픈(-)만 쓸 수 있어요. 최대 64자예요.",
    truncated: "출력이 너무 길어 앞부분만 저장했어요.",
    deleteTitle: (name: string) => `${name} 삭제`,
    deleteConfirm: "삭제하면 설정, 스크립트, 이력이 모두 지워져요. 종료 스크립트는 실행하지 않으니 필요하면 먼저 종료하세요. 확인하려면 MCP 이름을 그대로 입력하세요.",
    deleteAction: "MCP 삭제",
    tabs: { settings: "설정", scripts: "스크립트", history: "이력", latency: "지연 차트" },
    noHistory: "선택한 기간에 기록된 이슈나 조치가 없어요.",
    hostPort: "호스트:포트",
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
    versions: "버전 이력",
    revert: "이 버전으로 되돌리기",
    noVersions: "아직 저장된 버전이 없어요.",
    optionalRestart: "다시 시작 스크립트가 없으면 종료한 뒤 시작해요.",
    encodingNote: ".ps1은 UTF-8로, .bat와 .cmd는 이 PC의 코드 페이지로 저장돼요.",
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
    lastAdmin: "마지막 Admin이라 역할을 바꾸거나 비활성화할 수 없어요.",
    revokeNotice: "역할을 바꾸거나 비활성화하면 그 사용자는 바로 로그아웃돼요.",
    empty: "등록된 사용자가 없어요.",
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
    retentionPreview: (days: number | string, size: string) => `저장하면 ${days}일 치 로그(${size})가 삭제돼요.`,
    confirmDeleteTitle: "오래된 로그를 삭제할까요?",
    confirmDelete: "줄이고 삭제",
    startTypeNote: "지금은 값만 저장돼요. 서비스를 설치할 때 이 값이 적용돼요.",
    startTypes: { auto: "자동", "delayed-auto": "자동(지연된 시작)", manual: "수동" },
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
    count: (used: number, max: number) => `${used}/${max}자`,
    insertBold: "굵게",
    insertList: "목록",
    markupHelp: "빈 줄로 문단을 나누고, 줄을 “- ”로 시작하면 목록, **글자**는 굵게 표시돼요.",
    previewLabel: "고지 미리보기",
    fullPreview: "전체 화면 미리보기",
    fullPreviewNote: "저장된 내용으로 열려요.",
    versions: "버전 이력",
    defaultVersion: "기본 문구",
    defaultNote: "저장한 적이 없으면 기본 문구가 표시돼요. 언제든 기본 문구로 되돌릴 수 있어요.",
    revert: "이 버전으로 되돌리기",
    reverted: (v: number) => `버전 ${v}에서 되돌림`,
    unchanged: "바뀐 내용이 없어 새 버전을 만들지 않았어요.",
    acknowledged: "확인했어요. 이 창을 닫아도 돼요.",
    loadFailed: "고지 내용을 불러오지 못했어요. 새로 고친 뒤 다시 시도하세요.",
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
    method_not_allowed: "지원하지 않는 요청이에요. 페이지를 새로 고친 뒤 다시 시도하세요.",
    network: "서버에 연결할 수 없어요. 네트워크와 서비스 상태를 확인하세요.",
  } satisfies Record<ApiErrorCode, string>,

  toasts: {
    pending: (name: string, kind: ActionKind) => `${name} ${actionKind[kind]} 중…`,
    ok: (name: string, kind: ActionKind) => `${name} ${actionKind[kind]} 완료`,
    failed: (name: string, kind: ActionKind) => `${name} ${actionKind[kind]} 실패`,
    unknown: (name: string) => `${name} 조치 결과를 확인하지 못했어요. 이력에서 확인하세요.`,
    viewHistory: "이력 보기",
  },
} as const;

/** Korean message for a server error code; unknown codes read as `internal`. */
export function messageForError(code: string): string {
  return Object.hasOwn(copy.errors, code) ? copy.errors[code as ApiErrorCode] : copy.errors.internal;
}
