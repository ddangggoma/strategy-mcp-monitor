// One hook per GET (plan Appendix B) plus the shared mutations. Local-only reads run only when the
// policy mirror allows them (`can(me, action)`): on the external channel they are never requested,
// so a 404 there is never mistaken for "nothing here" (Global Constraints).
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { McpConfig, McpDetail, ScriptKind } from "@/lib/api-types";
import * as ep from "@/lib/endpoints";
import { can, type Action } from "@/lib/permissions";
import { useSession } from "@/lib/session";
import { qk } from "./query-keys";

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

export function useMcpHistory(id: number, hours: number, gate: QueryGate = {}) {
  return useQuery({
    queryKey: qk.history(id, hours),
    queryFn: () => ep.mcpHistory(id, hours),
    enabled: useAllowed("view_mcp_history", gate),
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

// ---- Local only ----------------------------------------------------------------------

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

/** POST /api/mcps/{id}/actions/{kind} → `{run_id}` (the result arrives later as an SSE `action`). */
export function useManualAction() {
  return useMutation({
    mutationFn: ({ id, kind }: { id: number; kind: ScriptKind }) => ep.manualAction(id, kind),
  });
}
