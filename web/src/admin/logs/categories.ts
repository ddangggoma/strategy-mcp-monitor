// The 12 log categories (spec §5.6) and the five colour groups the log screens draw them in (W32):
// twelve hues cannot be told apart, five can.
import type { LogCategory } from "@/lib/api-types";

/** In the server's order (app/logstore/normalize.py CATEGORIES). */
export const LOG_CATEGORIES: readonly LogCategory[] = [
  "session", "notice", "activity.process", "activity.command", "activity.window", "activity.idle",
  "tamper", "mcp.health", "mcp.action", "auth", "admin.audit", "system",
];

export type LogGroup = "session" | "activity" | "mcp" | "security" | "system";

export const LOG_GROUPS: readonly LogGroup[] = ["session", "activity", "mcp", "security", "system"];

export const CATEGORY_GROUP: Readonly<Record<LogCategory, LogGroup>> = {
  session: "session",
  notice: "session",
  "activity.process": "activity",
  "activity.command": "activity",
  "activity.window": "activity",
  "activity.idle": "activity",
  tamper: "security",
  "mcp.health": "mcp",
  "mcp.action": "mcp",
  auth: "security",
  "admin.audit": "security",
  system: "system",
};

/** Fill/stroke of a group (tokens.css `--color-cat-*`, light and dark). */
export const GROUP_COLOR_VAR: Readonly<Record<LogGroup, string>> = {
  session: "var(--color-cat-session)",
  activity: "var(--color-cat-activity)",
  mcp: "var(--color-cat-mcp)",
  security: "var(--color-cat-security)",
  system: "var(--color-cat-system)",
};
