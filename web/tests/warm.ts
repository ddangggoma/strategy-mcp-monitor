// Route-level tests mount lazy chunks (pages, Recharts, CodeMirror). The first test of a file to
// reach one paid for its cold transform and import inside its own timeout (up to ~6 s under the
// parallel suite), which is why testTimeout once had to be 15 s. Loading the chunks a file needs in
// beforeAll moves that one-time cost into the hook (hookTimeout) and keeps the per-test limit tight.
import { beforeAll } from "vitest";

const chunks = {
  login: () => import("@/admin/auth/LoginPage"),
  setup: () => import("@/admin/auth/SetupPage"),
  dashboard: () => import("@/admin/dashboard/DashboardPage"),
  mcpList: () => import("@/admin/mcps/McpListPage"),
  mcpCreate: () => import("@/admin/mcps/McpCreatePage"),
  mcpDetail: () => import("@/admin/mcps/McpDetailPage"),
  chart: () => import("@/admin/mcps/LatencyChart"),
  scriptEditor: () => import("@/admin/scripts/ScriptEditor"),
  users: () => import("@/admin/users/UsersPage"),
  settings: () => import("@/admin/settings/SettingsPage"),
  notice: () => import("@/admin/notice/NoticeEditorPage"),
  palette: () => import("@/admin/shell/CommandPalette"),
} as const;

export type Chunk = keyof typeof chunks;

/** Imports the named lazy chunks once, before the first test of the calling file. */
export function warmChunks(...names: Chunk[]): void {
  beforeAll(async () => {
    await Promise.all(names.map((n) => chunks[n]()));
  }, 60_000);
}
