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
