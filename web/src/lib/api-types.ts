// JSON shapes of the server API (server code is the source: plan Appendix B). Times are KST ISO
// strings with offset ("2026-11-04T14:03:22.418+09:00"); retention dates are "YYYY-MM-DD".

export type Channel = "local" | "external";
export type Role = "developer" | "admin";
export type McpState = "HEALTHY" | "SUSPECT" | "ACTION" | "RECOVERING" | "FAILED" | "MAINTENANCE";
export type Issue = "PROCESS_DOWN" | "UNRESPONSIVE" | "NETWORK_DOWN" | "WRONG_PROCESS";
export type ScriptKind = "start" | "stop" | "restart";
export type ScriptExt = ".ps1" | ".bat" | ".cmd";
export type ScriptStatus = "ok" | "failed" | "timeout" | "error";
export type Trigger = "auto" | "manual" | "boot";

export interface UserSummary {
  id: number;
  email: string;
  name: string;
}
export interface SessionUser extends UserSummary {
  role: Role;
}
export interface Me {
  user: SessionUser | null;
  channel: Channel;
  csrf_token: string | null;
  otp_provider: "dummy";
}

export interface BoardItem {
  id: number;
  name: string;
  state: McpState;
  issue: Issue | null;
  latency_ms: number | null;
  sparkline: (number | null)[];
  /** Share of ok checks in the last 24 h, 0–1 (not a percent); null without checks. */
  uptime_24h: number | null;
  last_check_at: string | null;
  action_due_at: string | null;
  action_in_sec: number | null;
  /** Countdown length; non-null only while a countdown runs (U8). */
  action_delay_sec: number | null;
  maintenance: boolean;
  running: ScriptKind | null;
}

/** Plan 4 contract: GET /api/board `sessions`, SSE `board` snapshot `sessions`, SSE `sessions` event `{sessions}`. Absent = not collected yet. */
export interface RdpSession {
  session_id: number;
  user: string;
  domain: string | null;
  client_name: string | null;
  client_ip: string | null;
  reverse_dns: string | null;
  logon_at: string | null;
  connected_at: string | null;
  /** Board sessions are active ones only (locked included, V7). */
  state: "active" | "locked";
  /** Server-computed from WTS LastInputTime; resent only when the whole minute changes (V10). */
  idle_sec: number | null;
  /** "1920x1080@32" (width x height @ colour depth). */
  resolution: string | null;
  /** null: no notice display for this connection. */
  notice_acknowledged: boolean | null;
  connection_id: number;
  client_build: number | null;
  protocol: "rdp" | "console" | "other";
  first_seen_ip: boolean;
  first_seen_device: boolean;
}
export interface Board {
  now: string;
  mcps: BoardItem[];
  sessions?: RdpSession[];
}

// ---- sessions screen (both channels, view_session_history) and tamper events --------

/** GET /api/sessions/current: every watched session, disconnected ones included (`user` without the domain). */
export interface CurrentSession {
  session_id: number;
  user: string;
  domain: string | null;
  /** `connected`: a client at the logon screen, not yet signed in. */
  state: "active" | "locked" | "disconnected" | "connected";
  client_name: string | null;
  client_ip: string | null;
  protocol: "rdp" | "console" | "other";
  logon_at: string | null;
  connected_at: string | null;
  disconnected_at: string | null;
  idle_sec: number | null;
  connection_id: number | null;
}
/** The latest notice display of one connection. `ack_ms`: last showing to the button. */
export interface ConnectionNotice {
  version: number;
  attempts: number;
  first_shown_at: string | null;
  acknowledged_at: string | null;
  ack_ms: number | null;
  /** null: still open. */
  closed_reason: "acknowledged" | "superseded" | "logoff" | "service_restart" | null;
}
export interface SessionConnection {
  id: number;
  session_id: number;
  user: string;
  domain: string | null;
  client_name: string | null;
  client_ip: string | null;
  reverse_dns: string | null;
  client_build: number | null;
  protocol: "rdp" | "console" | "other";
  resolution: string | null;
  kind: "logon" | "reconnect" | "existing";
  logon_at: string | null;
  connected_at: string;
  /** null: still connected. */
  ended_at: string | null;
  end_reason: "disconnect" | "logoff" | "reconnected" | "service_stop" | null;
  first_seen_ip: boolean;
  first_seen_device: boolean;
  notice: ConnectionNotice | null;
}
export interface LogonFailure {
  id: number;
  at: string;
  user: string | null;
  domain: string | null;
  client_ip: string | null;
  workstation: string | null;
  logon_type: number | null;
  /** NTSTATUS as the event log writes it ("0xc000006d"). */
  status: string | null;
  sub_status: string | null;
  source: string;
}
/** One page of GET /api/sessions/history; `failures` come with the first page only. */
export interface SessionsHistory {
  connections: SessionConnection[];
  failures: LogonFailure[];
  next_before_id: number | null;
}
export interface CollectorStatus {
  name: string;
  ok: boolean;
  error: string | null;
  /** When `ok`/`error` last changed. */
  since: string;
}
export type TamperEventName =
  | "agent_exited" | "agent_unresponsive" | "agent_restart_storm" | "agent_impersonation" | "notice_token_misuse"
  | "script_hash_mismatch" | "script_file_changed" | "script_file_missing" | "log_file_removed" | "log_file_truncated"
  | "audit_policy_changed" | "log_cleared" | "audit_config_changed" | "baseline_reset";
/** GET /api/tamper/recent row and SSE `tamper` (authenticated streams only); other fields depend on the event. */
export interface TamperEvent {
  at: string;
  event: TamperEventName;
  [field: string]: unknown;
}

export interface McpConfig {
  name: string;
  host: string;
  port: number;
  path: string;
  probe: "mcp_ping" | "tcp" | "icmp";
  expected_process_name: string | null;
  action_delay_sec: number;
  startup_grace_sec: number;
  max_auto_actions: number;
  window_sec: number;
  auto_recovery: boolean;
  autostart_on_boot: boolean;
  maintenance: boolean;
  script_timeout_sec: number;
}
export interface McpDetail extends McpConfig {
  id: number;
  config_error: boolean;
  owner: UserSummary | null;
  created_at: string;
  live: BoardItem | null;
}

export interface ActionRecord {
  id: number;
  run_id: string;
  at: string;
  requested: ScriptKind;
  kind: ScriptKind;
  trigger: Trigger;
  reason: string;
  actor_id: number | null;
  actor: UserSummary | null;
  status: ScriptStatus;
  exit_code: number | null;
  duration_ms: number | null;
  killed: number;
  error: string | null;
}
export interface ActionDetail extends ActionRecord {
  stdout: string;
  stderr: string;
  stdout_truncated: boolean;
  stderr_truncated: boolean;
}

export interface MinuteBucket {
  minute: string;
  ok: number;
  total: number;
  avg_latency_ms: number | null;
  max_latency_ms: number | null;
}
export interface Transition {
  at: string;
  from: McpState;
  to: McpState;
  issue: Issue | null;
}
export interface McpHistory {
  buckets: MinuteBucket[];
  transitions: Transition[];
  actions: ActionRecord[];
}
export interface McpActivity {
  transitions: (Transition & { mcp_id: number; name: string })[];
  actions: (ActionRecord & { mcp_id: number; name: string })[];
}

/** SSE `action` event (authenticated streams only). `requested` tells a restart fallback's stop step apart (U9). */
export interface ActionEvent {
  run_id: string;
  mcp_id: number;
  kind: ScriptKind;
  requested: ScriptKind;
  trigger: Trigger;
  status: ScriptStatus;
  exit_code: number | null;
  duration_ms: number | null;
}

export interface ScriptSummary {
  kind: ScriptKind;
  ext: ScriptExt;
  version: number;
  sha256: string;
}
export interface ScriptListItem extends ScriptSummary {
  updated_at: string;
  updated_by: number | null;
  updated_by_user: UserSummary | null;
}
export interface ScriptContent extends ScriptSummary {
  content: string;
  editable: boolean;
}
export interface ScriptVersion {
  version: number;
  ext: ScriptExt | null;
  sha256: string | null;
  author_id: number | null;
  author: UserSummary | null;
  created_at: string;
  deleted: boolean;
}
export interface ScriptVersionContent extends ScriptVersion {
  content: string | null;
}

export interface AdminUser extends SessionUser {
  active: boolean;
  created_at: string;
  last_login_at: string | null;
  owned_mcps: number;
}

export interface Settings {
  ping_interval_sec: number;
  issue_check_interval_sec: number;
  confirm_interval_sec: number;
  log_retention_days: number;
  log_compress_after_days: number;
  service_start_type: "auto" | "delayed-auto" | "manual";
  otp_provider: "dummy";
}
export interface RetentionPreview {
  days: number;
  cutoff: string;
  total_files: number;
  total_bytes: number;
  oldest_date: string | null;
  delete_files: number;
  delete_bytes: number;
  delete_from: string | null;
  delete_to: string | null;
  /** Indexed log lines in the deleted days; null while the index cannot tell. */
  delete_events: number | null;
}

// ---- logs and audit (both channels, view_logs / view_audit / export_logs) ------------

/** The 12 fixed categories (spec §5.6). */
export type LogCategory = "session" | "notice" | "activity.process" | "activity.command" | "activity.window" | "activity.idle"
  | "tamper" | "mcp.health" | "mcp.action" | "auth" | "admin.audit" | "system";
export type LogOutcome = "ok" | "fail" | "denied" | "error" | "failed" | "timeout";
/** One indexed line; `data` is the whole original event. */
export interface LogItem {
  id: number;
  ts: string;
  cat: LogCategory;
  event: string | null;
  user: string | null;
  session_id: number | null;
  client_ip: string | null;
  outcome: LogOutcome | null;
  data: Record<string, unknown>;
}
/** Newest first; `next_cursor` null on the last page. */
export interface LogPage {
  items: LogItem[];
  next_cursor: string | null;
  index: { ready: boolean };
}
/** Bars from `starts[i]` for `bucket_sec`; one series per group key (`null` key: no grouping). */
export interface LogHistogram {
  from: string;
  to: string;
  bucket_sec: number;
  starts: string[];
  series: { key: string | null; counts: number[] }[];
  total: number;
  source: "rollup" | "scan";
}
export interface LogUserCount {
  user: string;
  count: number;
}
export interface LogIndexStatus {
  ready: boolean;
  rebuilding: boolean;
  files: number;
  pending_files: number;
  pending_bytes: number;
  rows: number;
  bad_lines: number;
  oldest_day: string | null;
  newest_day: string | null;
  last_indexed_at: string | null;
}
/** Filters of /api/logs and its histogram, users and export routes (array fields repeat the parameter). */
export interface LogQuery {
  from: string;
  to: string;
  users?: string[];
  cat?: LogCategory[];
  event?: string[];
  outcome?: LogOutcome[];
  session?: number;
  ip?: string;
  q?: string;
}
export interface AuditQuery extends Omit<LogQuery, "cat" | "event" | "outcome" | "session" | "ip"> {
  kind?: "admin" | "auth" | "all";
  result?: LogOutcome[];
  channel?: Channel;
}

/** GET /api/service (Local, edit_global_settings): the Windows service's start type vs the setting. */
export interface ServiceStatus {
  installed: boolean;
  running_as_service: boolean;
  /** "disabled": an admin disabled the service in the SCM; never a setting, never re-enabled by the server. */
  start_type: Settings["service_start_type"] | "disabled" | null;
  desired: Settings["service_start_type"];
  in_sync: boolean;
  /** Running from a deployment bundle, which can be installed as the service; false in a development run (F20). */
  bundle: boolean;
}

export interface NoticeContent {
  title: string;
  body: string;
  button_text: string;
}
/** POST /api/notice/display/open (Local only, X-Notice-Token header): the version pinned when the display was made (V15). */
export interface NoticeDisplayContent extends NoticeContent {
  display_id: number;
  version: number;
}
/** Version 0 is the built-in text: `created_at` and `author` are null. */
export interface Notice extends NoticeContent {
  version: number;
  created_at: string | null;
  author: UserSummary | null;
  reverted_from: number | null;
}
export interface NoticeVersionSummary {
  version: number;
  title: string;
  created_at: string;
  author: UserSummary | null;
  reverted_from: number | null;
}

// ---- request bodies ------------------------------------------------------------------

export interface ScriptUpload {
  ext: ScriptExt;
  content: string;
}
/** POST /api/mcps: name/host/port plus any other config field (server defaults the rest) and the scripts. */
export type McpCreate = Pick<McpConfig, "name" | "host" | "port"> &
  Partial<McpConfig> & { scripts: Partial<Record<ScriptKind, ScriptUpload>> };
export interface UserCreate {
  email: string;
  name: string;
  role: Role;
}
export interface UserPatch {
  name?: string;
  role?: Role;
  active?: boolean;
}
