// One-line summary of a log line for the table and the timeline. Identifiers and data only, never
// Korean words: the summary is what an operator copies and greps for.
import type { LogItem } from "@/lib/api-types";

export const SUMMARY_MAX = 300;

/** A value worth printing: non-empty text or a finite number. */
function piece(v: unknown): string | undefined {
  if (typeof v === "number" && Number.isFinite(v)) return String(v);
  return typeof v === "string" && v.trim() !== "" ? v : undefined;
}

/** The first of email → name → path → id an admin action's `target` has. */
function targetSummary(target: unknown): string | undefined {
  if (!target || typeof target !== "object") return undefined;
  const t = target as Record<string, unknown>;
  return piece(t.email) ?? piece(t.name) ?? piece(t.path) ?? piece(t.id);
}

function pieces(item: LogItem): (string | undefined)[] {
  const d = item.data;
  switch (item.cat) {
    case "activity.command":
      return [piece(d.text) ?? piece(d.cmdline)];
    case "activity.process": {
      const pid = piece(d.pid);
      return [piece(item.event), piece(d.name), pid === undefined ? undefined : `(${pid})`];
    }
    case "activity.window":
      return [piece(d.title) ?? piece(d.exe)];
    case "session":
      return [piece(item.event), piece(item.client_ip)];
    case "notice": {
      const version = piece(d.version);
      return [piece(item.event), version === undefined ? undefined : `v${version}`];
    }
    case "auth":
      return [piece(item.event), piece(item.user)];
    case "admin.audit":
      return [piece(item.event), targetSummary(d.target)];
    case "mcp.action":
      return [piece(d.name), piece(d.kind), piece(item.outcome)];
    case "mcp.health":
      return [piece(d.name), piece(d.issue) ?? (d.alert ? "alert" : undefined)];
    default: // activity.idle, tamper, system (and a category this build does not know yet)
      return [piece(item.event)];
  }
}

/** Missing pieces are left out, whitespace runs become one space, at most SUMMARY_MAX characters. */
export function summarize(item: LogItem): string {
  const line = pieces(item).filter((p) => p !== undefined).join(" ").replace(/\s+/g, " ").trim();
  if (line.length <= SUMMARY_MAX) return line;
  const cut = line.slice(0, SUMMARY_MAX);
  // never end on half of a surrogate pair
  return /[\uD800-\uDBFF]$/.test(cut) ? cut.slice(0, -1) : cut;
}
