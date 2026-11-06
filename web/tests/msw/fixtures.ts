// Typed response builders shared by every component test. Values follow web/src/lib/api-types.ts
// (server code is the source); later tasks override per test with server.use(...).
import type {
  ActionDetail, ActionRecord, AdminUser, Board, BoardItem, Channel, CollectorStatus, CurrentSession, LogonFailure, McpActivity, McpDetail, McpHistory, McpState,
  Me, Notice, NoticeDisplayContent, NoticeVersionSummary, RdpSession, RetentionPreview, Role, ScriptContent, ScriptKind, ScriptListItem,
  ScriptVersion, SessionConnection, SessionsHistory, Settings, TamperEvent, UserSummary,
} from "@/lib/api-types";
import type { SseEvent } from "@/lib/sse";

export const NOW = "2026-11-04T14:03:22.418+09:00";

export function userSummary(id = 1): UserSummary {
  return { id, email: `user${id}@example.com`, name: `user${id}` };
}

export function meFixture(role: Role | null, channel: Channel, id = 1): Me {
  return {
    user: role === null ? null : { ...userSummary(id), role },
    channel,
    csrf_token: role === null ? null : `csrf-${id}`,
    otp_provider: "dummy",
  };
}

export function item(id: number, state: McpState, name = "mcp" + id): BoardItem {
  const healthy = state === "HEALTHY" || state === "MAINTENANCE";
  return {
    id,
    name,
    state,
    issue: healthy ? null : "PROCESS_DOWN",
    latency_ms: healthy ? 12 : null,
    sparkline: healthy ? [10, 12, 11, 13, 12] : [10, 12, null, null, null],
    uptime_24h: healthy ? 1 : 0.925, // a ratio (server History.uptime: ok / total), not a percent
    last_check_at: NOW,
    action_due_at: null,
    action_in_sec: null,
    action_delay_sec: null,
    maintenance: state === "MAINTENANCE",
    running: state === "ACTION" ? "restart" : null,
  };
}

export function boardFixture(b: Partial<Board> = {}): Board {
  return { now: NOW, mcps: [item(1, "HEALTHY", "calculator"), item(2, "FAILED", "seoul-weather")], ...b };
}

/** SSE `board` event; mcps default to empty so a test lists exactly the items it cares about. */
export function boardEvent(b: Partial<Board>): SseEvent {
  return { event: "board", data: JSON.stringify({ now: NOW, mcps: [], ...b }) };
}

/**
 * RDP session row (Plan 4 contract). Named rdpSession to stay clear of the `session` store (F17).
 * notice_acknowledged defaults to true (preflight F03): a quiet card unless a test asks otherwise.
 */
export function rdpSession(p: Partial<RdpSession> = {}): RdpSession {
  return {
    session_id: 2,
    user: "hong",
    domain: "CORP",
    client_name: "HONG-PC",
    client_ip: "10.0.3.21",
    reverse_dns: null,
    logon_at: NOW,
    connected_at: NOW,
    state: "active",
    idle_sec: 0,
    resolution: "1920x1080@32",
    notice_acknowledged: true,
    connection_id: 1,
    client_build: 26100,
    protocol: "rdp",
    first_seen_ip: false,
    first_seen_device: false,
    ...p,
  };
}

/** GET /api/sessions/current row: an active RDP session (matches rdpSession's defaults). */
export function currentSessionFixture(p: Partial<CurrentSession> = {}): CurrentSession {
  return {
    session_id: 2,
    user: "hong",
    domain: "CORP",
    state: "active",
    client_name: "HONG-PC",
    client_ip: "10.0.3.21",
    protocol: "rdp",
    logon_at: NOW,
    connected_at: NOW,
    disconnected_at: null,
    idle_sec: 0,
    connection_id: 1,
    ...p,
  };
}

/** One connection of the history: still connected, nothing first-seen, no notice display. */
export function connectionFixture(p: Partial<SessionConnection> = {}): SessionConnection {
  return {
    id: 1,
    session_id: 2,
    user: "hong",
    domain: "CORP",
    client_name: "HONG-PC",
    client_ip: "10.0.3.21",
    reverse_dns: null,
    client_build: 26100,
    protocol: "rdp",
    resolution: "1920x1080@32",
    kind: "logon",
    logon_at: NOW,
    connected_at: NOW,
    ended_at: null,
    end_reason: null,
    first_seen_ip: false,
    first_seen_device: false,
    notice: null,
    ...p,
  };
}

export function failureFixture(p: Partial<LogonFailure> = {}): LogonFailure {
  return {
    id: 1,
    at: NOW,
    user: "hong",
    domain: "CORP",
    client_ip: "192.0.2.10",
    workstation: "HONG-PC",
    logon_type: 10,
    status: "0xc000006d",
    sub_status: "0xc000006a",
    source: "eventlog:4625",
    ...p,
  };
}

/** One page: a single connection, no failures, no next page. */
export function sessionsHistoryFixture(p: Partial<SessionsHistory> = {}): SessionsHistory {
  return { connections: [connectionFixture()], failures: [], next_before_id: null, ...p };
}

export function collectorFixture(p: Partial<CollectorStatus> = {}): CollectorStatus {
  return { name: "wts", ok: true, error: null, since: NOW, ...p };
}

/** A tamper record as TamperMonitor.report() writes it (KST time, event, the event's own fields). */
export function tamperFixture(p: Partial<TamperEvent> = {}): TamperEvent {
  return { at: NOW, event: "agent_exited", session_id: 2, user: "CORP\\hong", pid: 4100, exit_code: 1, restarts: 0, ...p };
}

export function mcpDetailFixture(p: Partial<McpDetail> = {}): McpDetail {
  const id = p.id ?? 1;
  const name = p.name ?? "mcp" + id;
  return {
    name,
    host: "127.0.0.1",
    port: 9000 + id,
    path: "/mcp",
    probe: "mcp_ping",
    expected_process_name: null,
    action_delay_sec: 30,
    startup_grace_sec: 30,
    max_auto_actions: 3,
    window_sec: 600,
    auto_recovery: true,
    autostart_on_boot: false,
    maintenance: false,
    script_timeout_sec: 120,
    id,
    config_error: false,
    owner: userSummary(1),
    created_at: "2026-11-01T09:00:00.000+09:00",
    live: item(id, "HEALTHY", name),
    ...p,
  };
}

export function record(p: Partial<ActionRecord> = {}): ActionRecord {
  return {
    id: 1,
    run_id: "run-1",
    at: NOW,
    requested: "restart",
    kind: "restart",
    trigger: "manual",
    reason: "manual",
    actor_id: 1,
    actor: userSummary(1),
    status: "ok",
    exit_code: 0,
    duration_ms: 1234,
    killed: 0,
    error: null,
    ...p,
  };
}

export function actionDetailFixture(p: Partial<ActionDetail> = {}): ActionDetail {
  return { ...record(p), stdout: "started\n", stderr: "", stdout_truncated: false, stderr_truncated: false, ...p };
}

export function historyFixture(): McpHistory {
  return {
    buckets: [
      { minute: "2026-11-04T14:01:00.000+09:00", ok: 12, total: 12, avg_latency_ms: 11.5, max_latency_ms: 15 },
      { minute: "2026-11-04T14:02:00.000+09:00", ok: 10, total: 12, avg_latency_ms: 30, max_latency_ms: 80 },
      { minute: "2026-11-04T14:03:00.000+09:00", ok: 0, total: 12, avg_latency_ms: null, max_latency_ms: null },
    ],
    transitions: [
      { at: "2026-11-04T14:02:30.000+09:00", from: "HEALTHY", to: "SUSPECT", issue: "UNRESPONSIVE" },
      { at: "2026-11-04T14:03:00.000+09:00", from: "SUSPECT", to: "ACTION", issue: "UNRESPONSIVE" },
    ],
    actions: [record()],
  };
}

export function activityFixture(): McpActivity {
  return {
    transitions: [{ at: NOW, from: "HEALTHY", to: "FAILED", issue: "PROCESS_DOWN", mcp_id: 2, name: "seoul-weather" }],
    actions: [{ ...record({ id: 7, run_id: "run-7", trigger: "auto", actor_id: null, actor: null }), mcp_id: 2, name: "seoul-weather" }],
  };
}

export function scriptFixture(p: Partial<ScriptContent> = {}): ScriptContent {
  return {
    kind: "start",
    ext: ".ps1",
    version: 1,
    sha256: "a".repeat(64),
    content: "Write-Host start",
    editable: false,
    ...p,
  };
}

export function scriptListFixture(kinds: ScriptKind[] = ["start", "stop"]): ScriptListItem[] {
  return kinds.map((kind) => ({
    kind,
    ext: ".ps1",
    version: 1,
    sha256: "a".repeat(64),
    updated_at: NOW,
    updated_by: 1,
    updated_by_user: userSummary(1),
  }));
}

export function scriptVersionFixture(p: Partial<ScriptVersion> = {}): ScriptVersion {
  return {
    version: 1,
    ext: ".ps1",
    sha256: "a".repeat(64),
    author_id: 1,
    author: userSummary(1),
    created_at: NOW,
    deleted: false,
    ...p,
  };
}

export function adminUser(p: Partial<AdminUser> = {}): AdminUser {
  const id = p.id ?? 1;
  return {
    ...userSummary(id),
    role: "admin",
    active: true,
    created_at: "2026-11-01T09:00:00.000+09:00",
    last_login_at: NOW,
    owned_mcps: 0,
    ...p,
  };
}

export function settingsFixture(p: Partial<Settings> = {}): Settings {
  return {
    ping_interval_sec: 5,
    issue_check_interval_sec: 10,
    confirm_interval_sec: 1,
    log_retention_days: 180,
    log_compress_after_days: 30,
    service_start_type: "delayed-auto",
    otp_provider: "dummy",
    ...p,
  };
}

export function previewFixture(p: Partial<RetentionPreview> = {}): RetentionPreview {
  return {
    days: 180,
    cutoff: "2026-05-09",
    total_files: 12,
    total_bytes: 12_900_000,
    oldest_date: "2026-04-01",
    delete_files: 1,
    delete_bytes: 1_048_576,
    delete_from: "2026-04-01",
    delete_to: "2026-05-08",
    ...p,
  };
}

/** POST /api/notice/display/open: the notice page in display mode. */
export function noticeDisplayFixture(p: Partial<NoticeDisplayContent> = {}): NoticeDisplayContent {
  return { display_id: 12, version: 3, title: "원격 접속 안내", body: "이 연결의 작업은 기록됩니다.", button_text: "확인", ...p };
}

export function noticeFixture(p: Partial<Notice> = {}): Notice {
  return {
    version: 1,
    title: "접속 안내",
    body: "이 PC의 접속 기록은 보안 감사를 위해 저장합니다.",
    button_text: "확인",
    created_at: NOW,
    author: userSummary(1),
    reverted_from: null,
    ...p,
  };
}

export function noticeVersionFixture(p: Partial<NoticeVersionSummary> = {}): NoticeVersionSummary {
  return { version: 1, title: "접속 안내", created_at: NOW, author: userSummary(1), reverted_from: null, ...p };
}
