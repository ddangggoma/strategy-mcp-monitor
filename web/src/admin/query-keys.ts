// React Query keys (plan Appendix B). Everything about one MCP sits under ["mcp", id], so
// invalidating qk.mcp(id) also refreshes its history, actions and scripts.
import type { ScriptKind } from "@/lib/api-types";

/** Recent tamper events kept in the cache (the dashboard card shows the newest 10). */
export const TAMPER_LIMIT = 50;

export const qk = {
  me: ["me"],
  bootstrap: ["bootstrap"],
  mcps: ["mcps"],
  mcp: (id: number) => ["mcp", id] as const,
  /** Prefix of every history window of one MCP (for invalidation). */
  histories: (id: number) => ["mcp", id, "history"] as const,
  history: (id: number, hours: number) => ["mcp", id, "history", hours] as const,
  action: (id: number, aid: number) => ["mcp", id, "action", aid] as const,
  activity: ["mcp-activity"],
  scripts: (id: number) => ["mcp", id, "scripts"] as const,
  script: (id: number, kind: ScriptKind) => ["mcp", id, "script", kind] as const,
  scriptVersions: (id: number, kind: ScriptKind) => ["mcp", id, "script", kind, "versions"] as const,
  scriptVersion: (id: number, kind: ScriptKind, v: number) => ["mcp", id, "script", kind, "version", v] as const,
  users: ["users"],
  settings: ["settings"],
  retention: (days: number) => ["retention-preview", days] as const,
  notice: ["notice"],
  noticeVersions: ["notice", "versions"],
  noticeVersion: (v: number) => ["notice", "version", v] as const,
  sessionsCurrent: ["sessions", "current"],
  sessionsHistory: (days: number) => ["sessions", "history", days] as const,
  collectors: ["sessions", "collectors"],
  tamper: ["tamper"],
} as const;
