// Client function per server route: plan Appendix B, names and return types as listed there.
// Local-only routes (marked) must not be called on the external channel (Global Constraints).
import { api } from "./api";
import type {
  ActionDetail, AdminUser, Board, CollectorStatus, CurrentSession, McpActivity, McpConfig, McpCreate, McpDetail, McpHistory, Me, Notice,
  NoticeContent, NoticeVersionSummary, RetentionPreview, ScriptContent, ScriptKind, ScriptListItem,
  ScriptSummary, ScriptUpload, ScriptVersion, ScriptVersionContent, SessionsHistory, SessionUser, Settings, TamperEvent,
  UserCreate, UserPatch,
} from "./api-types";

// ---- auth (both channels) ------------------------------------------------------------

export const me = () => api<Me>("/api/auth/me");
export const otpRequest = (email: string) =>
  api<Record<string, never>>("/api/auth/otp/request", { method: "POST", body: { email } });
export const otpVerify = (email: string, code: string) =>
  api<{ user: SessionUser; csrf_token: string }>("/api/auth/otp/verify", { method: "POST", body: { email, code } });
export const logout = () => api<void>("/api/auth/logout", { method: "POST" });

// ---- bootstrap (Local) ---------------------------------------------------------------

export const bootstrapStatus = () => api<{ needed: boolean }>("/api/bootstrap");
export const bootstrap = (b: { email: string; name: string }) =>
  api<SessionUser>("/api/bootstrap", { method: "POST", body: b });

// ---- board, MCPs (both channels) -----------------------------------------------------

export const board = () => api<Board>("/api/board");
export const mcps = () => api<McpDetail[]>("/api/mcps");
export const mcp = (id: number) => api<McpDetail>(`/api/mcps/${id}`);
export const mcpHistory = (id: number, hours: number) =>
  api<McpHistory>(`/api/mcps/${id}/history`, { query: { hours } });
export const actionDetail = (id: number, aid: number) => api<ActionDetail>(`/api/mcps/${id}/actions/${aid}`);
export const mcpActivity = (limit: number) => api<McpActivity>("/api/mcp-activity", { query: { limit } });
/** Send only the changed fields (U27). */
export const updateMcp = (id: number, patch: Partial<McpConfig>) =>
  api<McpDetail>(`/api/mcps/${id}`, { method: "PUT", body: patch });
export const manualAction = (id: number, kind: ScriptKind) =>
  api<{ run_id: string }>(`/api/mcps/${id}/actions/${kind}`, { method: "POST" });

// ---- remote desktop sessions, tamper events (both channels) ---------------------------

export const sessionsCurrent = () => api<{ ready: boolean; sessions: CurrentSession[] }>("/api/sessions/current");
/** Connections newest first; `beforeId` (the previous page's `next_before_id`) pages on. */
export const sessionsHistory = (days: number, beforeId?: number) =>
  api<SessionsHistory>("/api/sessions/history", { query: beforeId === undefined ? { days } : { days, before_id: beforeId } });
export const collectorsStatus = () => api<CollectorStatus[]>("/api/sessions/collectors");
export const tamperRecent = (limit?: number) =>
  api<TamperEvent[]>("/api/tamper/recent", limit === undefined ? {} : { query: { limit } });

// ---- MCP registration, ownership, scripts (Local) ------------------------------------

export const createMcp = (body: McpCreate) => api<McpDetail>("/api/mcps", { method: "POST", body });
export const deleteMcp = (id: number) => api<void>(`/api/mcps/${id}`, { method: "DELETE" });
export const transferOwner = (id: number, userId: number) =>
  api<McpDetail>(`/api/mcps/${id}/owner`, { method: "POST", body: { user_id: userId } });
export const scripts = (id: number) => api<ScriptListItem[]>(`/api/mcps/${id}/scripts`);
export const script = (id: number, kind: ScriptKind) => api<ScriptContent>(`/api/mcps/${id}/scripts/${kind}`);
export const scriptVersions = (id: number, kind: ScriptKind) =>
  api<ScriptVersion[]>(`/api/mcps/${id}/scripts/${kind}/versions`);
export const scriptVersion = (id: number, kind: ScriptKind, v: number) =>
  api<ScriptVersionContent>(`/api/mcps/${id}/scripts/${kind}/versions/${v}`);
export const putScript = (id: number, kind: ScriptKind, b: ScriptUpload) =>
  api<ScriptSummary>(`/api/mcps/${id}/scripts/${kind}`, { method: "PUT", body: b });
export const deleteScript = (id: number, kind: ScriptKind) =>
  api<void>(`/api/mcps/${id}/scripts/${kind}`, { method: "DELETE" });
export const revertScript = (id: number, kind: ScriptKind, v: number) =>
  api<ScriptSummary>(`/api/mcps/${id}/scripts/${kind}/versions/${v}/revert`, { method: "POST" });

// ---- users, settings, notice (Local, admin) ------------------------------------------

export const users = () => api<AdminUser[]>("/api/users");
export const createUser = (b: UserCreate) => api<AdminUser>("/api/users", { method: "POST", body: b });
export const updateUser = (id: number, patch: UserPatch) =>
  api<AdminUser>(`/api/users/${id}`, { method: "PATCH", body: patch });
export const settings = () => api<Settings>("/api/settings");
/** Send only the changed fields (U27). */
export const updateSettings = (patch: Partial<Settings>) => api<Settings>("/api/settings", { method: "PUT", body: patch });
export const retentionPreview = (days: number) =>
  api<RetentionPreview>("/api/settings/retention/preview", { query: { days } });
export const notice = () => api<Notice>("/api/notice");
export const putNotice = (c: NoticeContent) => api<Notice>("/api/notice", { method: "PUT", body: c });
export const noticeVersions = () => api<NoticeVersionSummary[]>("/api/notice/versions");
export const noticeVersion = (v: number) => api<Notice>(`/api/notice/versions/${v}`);
export const revertNotice = (v: number) => api<Notice>(`/api/notice/versions/${v}/revert`, { method: "POST" });
