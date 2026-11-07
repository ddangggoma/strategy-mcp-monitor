// One hook per GET (plan Appendix B) plus the shared mutations. Local-only reads run only when the
// policy mirror allows them (`can(me, action)`): on the external channel they are never requested,
// so a 404 there is never mistaken for "nothing here" (Global Constraints).
import { keepPreviousData, useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { AuditQuery, LogQuery, McpConfig, McpDetail, ScriptKind } from "@/lib/api-types";
import * as ep from "@/lib/endpoints";
import { can, type Action } from "@/lib/permissions";
import { useSession } from "@/lib/session";
import { TAMPER_LIMIT, qk, type HistogramGroup } from "./query-keys";

export interface QueryGate {
  /** Extra condition from the caller (a dialog is open, a tab is selected…); default true. */
  enabled?: boolean;
}

/** Recent transitions and actions across all MCPs (U11); the dashboard shows the newest 10. */
export const ACTIVITY_LIMIT = 50;

function useAllowed(action: Action, gate: QueryGate): boolean {
  const me = useSession();
  return (gate.enabled ?? true) && can(me, action);
}

// ---- both channels -------------------------------------------------------------------

export function useMcps(gate: QueryGate = {}) {
  return useQuery({ queryKey: qk.mcps, queryFn: ep.mcps, enabled: useAllowed("view_mcp_history", gate) });
}

export function useMcp(id: number, gate: QueryGate = {}) {
  return useQuery({ queryKey: qk.mcp(id), queryFn: () => ep.mcp(id), enabled: useAllowed("view_mcp_history", gate) });
}

/** Switching the period keeps the previous window on screen until the new one arrives (no flash). */
export function useMcpHistory(id: number, hours: number, gate: QueryGate = {}) {
  return useQuery({
    queryKey: qk.history(id, hours),
    queryFn: () => ep.mcpHistory(id, hours),
    enabled: useAllowed("view_mcp_history", gate),
    placeholderData: keepPreviousData,
  });
}

export function useActionDetail(id: number, aid: number, gate: QueryGate = {}) {
  return useQuery({
    queryKey: qk.action(id, aid),
    queryFn: () => ep.actionDetail(id, aid),
    enabled: useAllowed("view_mcp_history", gate),
  });
}

export function useMcpActivity(gate: QueryGate = {}) {
  return useQuery({
    queryKey: qk.activity,
    queryFn: () => ep.mcpActivity(ACTIVITY_LIMIT),
    enabled: useAllowed("view_mcp_history", gate),
  });
}

/** Remote desktop sessions now, disconnected ones included (the sessions screen). */
export function useSessionsCurrent(gate: QueryGate = {}) {
  return useQuery({
    queryKey: qk.sessionsCurrent,
    queryFn: ep.sessionsCurrent,
    enabled: useAllowed("view_session_history", gate),
  });
}

/**
 * Connection history of the last `days`, one page per "더 보기" (cursor `before_id`); the logon
 * failures come with the first page. Switching the period keeps the previous one on screen until
 * the new one arrives.
 */
export function useSessionsHistory(days: number, gate: QueryGate = {}) {
  return useInfiniteQuery({
    queryKey: qk.sessionsHistory(days),
    queryFn: ({ pageParam }) => ep.sessionsHistory(days, pageParam),
    initialPageParam: undefined as number | undefined,
    getNextPageParam: (p) => p.next_before_id ?? undefined,
    enabled: useAllowed("view_session_history", gate),
    placeholderData: keepPreviousData,
  });
}

export function useCollectors(gate: QueryGate = {}) {
  return useQuery({ queryKey: qk.collectors, queryFn: ep.collectorsStatus, enabled: useAllowed("view_session_history", gate) });
}

/** Newest first; SSE `tamper` events are put in front by connectLive (at most TAMPER_LIMIT). */
export function useTamperRecent(gate: QueryGate = {}) {
  return useQuery({
    queryKey: qk.tamper,
    queryFn: () => ep.tamperRecent(TAMPER_LIMIT),
    enabled: useAllowed("view_logs", gate),
  });
}

// ---- logs and audit (both channels, any signed-in user) -------------------------------

/** How often the index status is re-read while the index is still being built. */
export const LOG_STATUS_POLL_MS = 5000;

/**
 * Log lines newest first, one page per "더 보기" (cursor `next_cursor`). A new filter set keeps the
 * previous lines on screen until its first page arrives (no empty flash between filters).
 */
export function useLogPages(q: LogQuery, gate: QueryGate = {}) {
  return useInfiniteQuery({
    queryKey: qk.logs(q),
    queryFn: ({ pageParam }) => ep.logs(q, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (p) => p.next_cursor ?? undefined,
    enabled: useAllowed("view_logs", gate),
    placeholderData: keepPreviousData,
  });
}

/** `buckets` 10–200 (the server rejects fewer). */
export function useLogHistogram(q: LogQuery, group: HistogramGroup, buckets: number, gate: QueryGate = {}) {
  return useQuery({
    queryKey: qk.logHistogram(q, group, buckets),
    queryFn: () => ep.logHistogram(q, { buckets, group }),
    enabled: useAllowed("view_logs", gate),
    placeholderData: keepPreviousData,
  });
}

export function useLogUsers(q: LogQuery, gate: QueryGate = {}) {
  return useQuery({
    queryKey: qk.logUsers(q),
    queryFn: () => ep.logUsers(q),
    enabled: useAllowed("view_logs", gate),
    placeholderData: keepPreviousData,
  });
}

/** Re-read every 5 s while the index is not ready (results may be partial); stops once it is. */
export function useLogStatus(gate: QueryGate = {}) {
  return useQuery({
    queryKey: qk.logStatus,
    queryFn: ep.logStatus,
    enabled: useAllowed("view_logs", gate),
    refetchInterval: (query) => (query.state.data?.ready === false ? LOG_STATUS_POLL_MS : false),
  });
}

/** Admin actions and/or login attempts (`q.kind`), paged like useLogPages. */
export function useAuditPages(q: AuditQuery, gate: QueryGate = {}) {
  return useInfiniteQuery({
    queryKey: qk.audit(q),
    queryFn: ({ pageParam }) => ep.audit(q, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (p) => p.next_cursor ?? undefined,
    enabled: useAllowed("view_audit", gate),
    placeholderData: keepPreviousData,
  });
}

// ---- Local only ----------------------------------------------------------------------

/** The Windows service's start type next to the setting (never asked on the external channel). */
export function useServiceStatus(gate: QueryGate = {}) {
  return useQuery({ queryKey: qk.service, queryFn: ep.serviceStatus, enabled: useAllowed("edit_global_settings", gate) });
}

export function useScripts(id: number, gate: QueryGate = {}) {
  return useQuery({ queryKey: qk.scripts(id), queryFn: () => ep.scripts(id), enabled: useAllowed("view_scripts", gate) });
}

export function useScript(id: number, kind: ScriptKind, gate: QueryGate = {}) {
  return useQuery({
    queryKey: qk.script(id, kind),
    queryFn: () => ep.script(id, kind),
    enabled: useAllowed("view_scripts", gate),
  });
}

export function useScriptVersions(id: number, kind: ScriptKind, gate: QueryGate = {}) {
  return useQuery({
    queryKey: qk.scriptVersions(id, kind),
    queryFn: () => ep.scriptVersions(id, kind),
    enabled: useAllowed("view_scripts", gate),
  });
}

export function useScriptVersion(id: number, kind: ScriptKind, v: number, gate: QueryGate = {}) {
  return useQuery({
    queryKey: qk.scriptVersion(id, kind, v),
    queryFn: () => ep.scriptVersion(id, kind, v),
    enabled: useAllowed("view_scripts", gate),
  });
}

export function useUsers(gate: QueryGate = {}) {
  return useQuery({ queryKey: qk.users, queryFn: ep.users, enabled: useAllowed("manage_users", gate) });
}

export function useSettings(gate: QueryGate = {}) {
  return useQuery({ queryKey: qk.settings, queryFn: ep.settings, enabled: useAllowed("edit_global_settings", gate) });
}

export function useRetentionPreview(days: number, gate: QueryGate = {}) {
  return useQuery({
    queryKey: qk.retention(days),
    queryFn: () => ep.retentionPreview(days),
    enabled: useAllowed("edit_retention", gate),
  });
}

export function useNotice(gate: QueryGate = {}) {
  return useQuery({ queryKey: qk.notice, queryFn: ep.notice, enabled: useAllowed("edit_notice", gate) });
}

export function useNoticeVersions(gate: QueryGate = {}) {
  return useQuery({ queryKey: qk.noticeVersions, queryFn: ep.noticeVersions, enabled: useAllowed("edit_notice", gate) });
}

export function useNoticeVersion(v: number, gate: QueryGate = {}) {
  return useQuery({
    queryKey: qk.noticeVersion(v),
    queryFn: () => ep.noticeVersion(v),
    enabled: useAllowed("edit_notice", gate),
  });
}

// ---- mutations -----------------------------------------------------------------------

/** Writes a fresh McpDetail into the detail cache and its row in the list. */
export function storeMcp(qc: ReturnType<typeof useQueryClient>, detail: McpDetail): void {
  qc.setQueryData<McpDetail>(qk.mcp(detail.id), detail);
  qc.setQueryData<McpDetail[]>(qk.mcps, (list) => list?.map((m) => (m.id === detail.id ? detail : m)));
}

/** PUT /api/mcps/{id} with only the changed fields (U27). */
export function useUpdateMcp(id: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: Partial<McpConfig>) => ep.updateMcp(id, patch),
    onSuccess: (detail) => storeMcp(qc, detail),
  });
}

export interface ManualActionRequest {
  mcp: Pick<McpDetail, "id" | "name" | "script_timeout_sec">;
  kind: ScriptKind;
}

export interface ManualActionHandlers {
  /** The 202: hand the run to the tab's tracker. */
  onAccepted(req: ManualActionRequest, runId: string): void;
  onFailed(err: unknown): void;
}

/**
 * POST /api/mcps/{id}/actions/{kind} → `{run_id}` (the result arrives later as an SSE `action`).
 * The handlers are mutation-level callbacks, not per-`mutate` ones: TanStack Query skips the latter
 * once the calling component unmounts (a click, then a move to another page before the 202), and
 * the run would never get its toast.
 */
export function useManualAction(handlers: ManualActionHandlers) {
  return useMutation({
    mutationFn: ({ mcp, kind }: ManualActionRequest) => ep.manualAction(mcp.id, kind),
    onSuccess: ({ run_id }, req) => handlers.onAccepted(req, run_id),
    onError: (err) => handlers.onFailed(err),
  });
}
