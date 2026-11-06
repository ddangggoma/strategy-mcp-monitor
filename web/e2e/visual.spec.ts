// Visual baselines, run in both the chromium-dark and chromium-light projects. Values that change
// from run to run (times, latency, sparklines, countdowns, uptime, activity rows) carry
// data-volatile and are masked (F32: earlier specs leave history behind).
// A mask hides values but not how many rows there are, so the reads whose length depends on what
// earlier specs (or this PC) did (recent activity, notice versions, tamper events) are answered with
// fixed data here: the baselines are the same whether this spec runs alone or after the whole
// suite. The MCP's port is fixed too (backend.ts MCP_PORT).
import type { Page, Route } from "@playwright/test";
import type {
  LogHistogram, LogIndexStatus, LogItem, LogPage, LogUserCount, McpActivity, Notice, NoticeVersionSummary, TamperEvent,
} from "../src/lib/api-types";
import { MCP_NAME, copy, expect, test, type BackendState, type Who } from "./fixtures";

const AT = "2026-11-06T09:00:00.000+09:00";

function activity(s: BackendState): McpActivity {
  return {
    transitions: [{ at: AT, from: "HEALTHY", to: "SUSPECT", issue: "UNRESPONSIVE", mcp_id: s.mcpId, name: MCP_NAME }],
    actions: [
      {
        id: 1, run_id: "visual", at: AT, requested: "start", kind: "start", trigger: "manual", reason: "manual",
        actor_id: 1, actor: { id: 1, email: s.adminEmail, name: "E2E Admin" }, status: "ok", exit_code: 0,
        duration_ms: 1200, killed: 0, error: null, mcp_id: s.mcpId, name: MCP_NAME,
      },
    ],
  };
}

/** A fresh backend's notice: the built-in text, no saved versions. */
const NOTICE: Notice = { ...copy.notice.builtIn, version: 0, created_at: null, author: null, reverted_from: null };
const NOTICE_VERSIONS: NoticeVersionSummary[] = [];
/** Tamper events depend on what this PC and earlier specs did (log files, agents): fixed here. */
const TAMPER: TamperEvent[] = [
  { at: AT, event: "agent_exited", session_id: 3, user: "CORP\\kim", pid: 4100, exit_code: 1, restarts: 0 },
  { at: AT, event: "log_file_truncated", file: "2026-11-06.jsonl", before: 4096, after: 0 },
];

async function fixHistoryReads(page: Page, s: BackendState): Promise<void> {
  // matched on the path alone: the activity read carries ?limit=
  const fixed = (path: string, body: unknown) =>
    page.route(
      (url) => url.pathname === path,
      (route: Route) => (route.request().method() === "GET" ? route.fulfill({ json: body }) : route.fallback()),
    );
  await fixed("/api/mcp-activity", activity(s));
  await fixed("/api/notice", NOTICE);
  await fixed("/api/notice/versions", NOTICE_VERSIONS);
  await fixed("/api/tamper/recent", TAMPER);
  await fixLogReads(page);
}

// The log and audit screens read the index, whose rows depend on everything earlier specs did:
// their reads are answered with fixed lines, and the screens open on a fixed custom range (the
// range inputs show it). The histogram is data-volatile (masked); its bars follow the request.
const LOG_FROM = "2026-11-06T09:00:00.000+09:00";
const LOG_TO = "2026-11-06T10:00:00.000+09:00";
const LOG_RANGE = `from=${encodeURIComponent(LOG_FROM)}&to=${encodeURIComponent(LOG_TO)}`;

function line(id: number, at: string, item: Omit<LogItem, "id" | "ts" | "data"> & { data?: Record<string, unknown> }): LogItem {
  const ts = `2026-11-06T09:${at}.000+09:00`;
  return { id, ts, ...item, data: { ts, cat: item.cat, ...(item.event ? { event: item.event } : {}), ...item.data } };
}

const LOG_LINES: LogItem[] = [
  line(8, "58:12", { cat: "activity.command", event: null, user: "CORP\\kim", session_id: 3, client_ip: "10.0.3.22", outcome: null, data: { text: "Get-Process -Name python" } }),
  line(7, "57:40", { cat: "activity.process", event: "start", user: "CORP\\kim", session_id: 3, client_ip: "10.0.3.22", outcome: null, data: { name: "notepad.exe", pid: 5120 } }),
  line(6, "55:03", { cat: "session", event: "logon", user: "CORP\\kim", session_id: 3, client_ip: "10.0.3.22", outcome: null }),
  line(5, "41:27", { cat: "mcp.action", event: null, user: "admin@e2e.test", session_id: null, client_ip: null, outcome: "ok", data: { name: MCP_NAME, kind: "restart", status: "ok" } }),
  line(4, "41:20", { cat: "mcp.health", event: null, user: null, session_id: null, client_ip: null, outcome: null, data: { name: MCP_NAME, issue: "UNRESPONSIVE" } }),
  line(3, "30:00", { cat: "auth", event: "login", user: "admin@e2e.test", session_id: null, client_ip: "127.0.0.1", outcome: "ok", data: { channel: "local", windows_user: "CORP\\admin", user_agent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0 Safari/537.36" } }),
  line(2, "12:45", { cat: "admin.audit", event: "user_create", user: "admin@e2e.test", session_id: null, client_ip: "127.0.0.1", outcome: "ok", data: { channel: "local", target: { email: "dev@e2e.test", role: "developer" } } }),
  line(1, "05:00", { cat: "system", event: "logindex.ready", user: null, session_id: null, client_ip: null, outcome: null, data: { rows: 1204, duration_ms: 310 } }),
];
const AUDIT_LINES: LogItem[] = [
  line(12, "50:31", { cat: "admin.audit", event: "settings_update", user: "admin@e2e.test", session_id: null, client_ip: "127.0.0.1", outcome: "ok", data: { channel: "local", target: { keys: ["log_retention_days"] } } }),
  line(11, "44:02", { cat: "admin.audit", event: "mcp_action", user: "dev@e2e.test", session_id: null, client_ip: "10.0.3.40", outcome: "denied", data: { channel: "external", target: { id: 1, name: MCP_NAME, kind: "stop" } } }),
  line(10, "21:15", { cat: "admin.audit", event: "logs_export", user: "admin@e2e.test", session_id: null, client_ip: "127.0.0.1", outcome: "ok", data: { channel: "local", target: { format: "csv", limit: 100000 } } }),
  line(2, "12:45", { cat: "admin.audit", event: "user_create", user: "admin@e2e.test", session_id: null, client_ip: "127.0.0.1", outcome: "ok", data: { channel: "local", target: { email: "dev@e2e.test", role: "developer" } } }),
];
const LOG_USERS: LogUserCount[] = [
  { user: "CORP\\kim", count: 3 },
  { user: "admin@e2e.test", count: 3 },
];
const LOG_STATUS: LogIndexStatus = {
  ready: true, rebuilding: false, files: 3, pending_files: 0, pending_bytes: 0, rows: 1204, bad_lines: 0,
  oldest_day: "2026-11-04", newest_day: "2026-11-06", last_indexed_at: "2026-11-06T09:58:13.000+09:00",
};

/** Bars for exactly the requested window and bucket count (the grouping key is the category). */
function histogram(url: URL): LogHistogram {
  const from = url.searchParams.get("from") ?? LOG_FROM;
  const to = url.searchParams.get("to") ?? LOG_TO;
  const buckets = Number(url.searchParams.get("buckets") ?? "60");
  const start = Date.parse(from);
  const bucketSec = Math.max(60, Math.ceil((Date.parse(to) - start) / 1000 / buckets / 60) * 60);
  const starts = Array.from({ length: buckets }, (_, i) => new Date(start + i * bucketSec * 1000).toISOString());
  const counts = (k: number) => starts.map((_, i) => (i * k) % 7);
  // the series the request filters to (the dashboard card asks for auth + session), else three
  const asked = url.searchParams.getAll("cat");
  const keys = asked.length > 0 ? asked : ["activity.command", "session", "admin.audit"];
  const series = keys.map((key, k) => ({ key, counts: counts(k + 1) }));
  const total = series.reduce((n, s) => n + s.counts.reduce((a, b) => a + b, 0), 0);
  return { from, to, bucket_sec: bucketSec, starts, series, total, source: "rollup" };
}

async function fixLogReads(page: Page): Promise<void> {
  const page1 = (items: LogItem[]): LogPage => ({ items, next_cursor: null, index: { ready: true } });
  const routes: Record<string, (url: URL) => unknown> = {
    "/api/logs": () => page1(LOG_LINES),
    "/api/logs/histogram": histogram,
    "/api/logs/users": () => LOG_USERS,
    "/api/logs/status": () => LOG_STATUS,
    "/api/audit": () => page1(AUDIT_LINES),
  };
  await page.route(
    (url) => url.pathname in routes,
    (route: Route) => {
      const url = new URL(route.request().url());
      return route.request().method() === "GET" ? route.fulfill({ json: routes[url.pathname]!(url) }) : route.fallback();
    },
  );
}

interface Screen {
  name: string;
  path: string;
  who: Who | null;
  ready(page: Page): Promise<void>;
}

const SCREENS: Screen[] = [
  {
    name: "board",
    path: "/",
    who: null,
    ready: (page) => expect(page.getByTestId("mcp-card").getByText(copy.states.HEALTHY)).toBeVisible(),
  },
  {
    name: "login",
    path: "/admin/login",
    who: null,
    ready: (page) => expect(page.getByText(copy.login.devBadge)).toBeVisible(),
  },
  {
    name: "dashboard",
    path: "/admin",
    who: "admin",
    ready: (page) => expect(page.getByRole("heading", { name: copy.dashboard.recentActivity })).toBeVisible(),
  },
  {
    name: "mcp-list",
    path: "/admin/mcps",
    who: "admin",
    ready: (page) => expect(page.getByRole("table", { name: copy.mcp.listLabel }).getByRole("row", { name: new RegExp(MCP_NAME) }).getByText(copy.states.HEALTHY)).toBeVisible(),
  },
  {
    name: "mcp-detail",
    path: "/admin/mcps/{id}",
    who: "admin",
    ready: (page) => expect(page.getByLabel(copy.mcp.fields.name, { exact: true })).toHaveValue(MCP_NAME),
  },
  {
    name: "notice-editor",
    path: "/admin/notice",
    who: "admin",
    ready: (page) => expect(page.getByRole("list", { name: copy.notice.versions })).toBeVisible(),
  },
  {
    name: "logs",
    path: `/admin/logs?${LOG_RANGE}`,
    who: "admin",
    ready: async (page) => {
      await expect(page.getByRole("table", { name: copy.logs.title }).getByRole("row").filter({ hasText: "logindex.ready" })).toBeVisible();
      await expect(page.getByTestId("log-histogram")).toBeVisible();
    },
  },
  {
    name: "audit",
    path: `/admin/audit?${LOG_RANGE}`,
    who: "admin",
    ready: (page) => expect(page.getByRole("table", { name: copy.audit.title }).getByRole("row").filter({ hasText: "user_create" })).toBeVisible(),
  },
  {
    name: "notice",
    path: "/notice",
    who: "admin",
    ready: (page) => expect(page.getByRole("dialog").getByRole("heading", { name: copy.notice.builtIn.title })).toBeVisible(),
  },
];

for (const screen of SCREENS) {
  test(`screenshot ${screen.name}`, async ({ page, state, loginAs }) => {
    await fixHistoryReads(page, state);
    if (screen.who) await loginAs(page, screen.who, "local");
    await page.goto(`${state.localUrl}${screen.path.replace("{id}", String(state.mcpId))}`);
    await screen.ready(page);
    await page.evaluate(() => document.fonts.ready);
    await expect(page).toHaveScreenshot(`${screen.name}.png`, { fullPage: true, mask: [page.locator("[data-volatile]")] });
  });
}
