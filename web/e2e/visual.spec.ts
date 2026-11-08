// Visual baselines, run in both the chromium-dark and chromium-light projects. Values that change
// from run to run (times, latency, sparklines, countdowns, uptime, activity rows) carry
// data-volatile and are masked (F32: earlier specs leave history behind).
// A mask hides values but not how many rows there are, so the reads whose length depends on what
// earlier specs (or this PC) did (recent activity, notice versions, tamper events) are answered with
// fixed data here: the baselines are the same whether this spec runs alone or after the whole
// suite. The MCP's port is fixed too (backend.ts MCP_PORT).
import type { Page, Route } from "@playwright/test";
import type {
  LogHistogram, LogIndexStatus, LogItem, LogPage, LogUserCount, McpActivity, Notice, NoticeVersionSummary, SystemStatus, TamperEvent,
} from "../src/lib/api-types";
import { THEME_STORAGE_KEY } from "../src/lib/theme";
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

// The board's overview and the "서버 PC 리소스" panel come over the SSE stream: the check history
// (strip, rate, uptime and their tones) depends on what earlier specs staged, and the PC readings
// (rings, memory, disks: how many and how full) on this PC at this moment. A mask would hide the
// numbers but not the ring fills, the bar lengths, the disk rows or the tile tones, so the stream's
// MCP measurements and `system` readings are replaced with fixed ones in the page (fetch wrapper:
// the board stream is fetch-based, and route.fulfill cannot keep a stream open). States, names and
// times stay real (times are data-volatile).
const SPARK: (number | null)[] = Array.from({ length: 60 }, (_, i) => (i === 41 ? null : 30 + ((i * 7) % 11)));
const SYSTEM: SystemStatus = {
  at: AT,
  interval_sec: 5,
  cpu: { percent: 23.4, cores: 8 },
  memory: { total: 17_179_869_184, used: 9_448_928_051, percent: 55 },
  disks: [
    { name: "C:", total: 511_101_108_224, used: 306_660_664_934, percent: 60 },
    { name: "D:", total: 1_000_202_039_296, used: 850_171_733_401, percent: 85 },
  ],
  network: { sent_bps: 52_400, recv_bps: 1_310_720 },
  boot_at: "2026-11-01T08:00:00.000+09:00",
  history: {
    cpu: Array.from({ length: 60 }, (_, i) => 15 + ((i * 13) % 20)),
    memory: Array.from({ length: 60 }, (_, i) => 52 + (i % 7)),
  },
};

async function fixBoardStream(page: Page): Promise<void> {
  await page.addInitScript(
    ({ spark, system }) => {
      const measured = (item: Record<string, unknown>) => ({ ...item, latency_ms: 38, sparkline: spark, uptime_24h: 0.9995 });
      const rewrite = (block: string): string => {
        const m = /^event: (board|mcp|system)\ndata: (.*)\n\n$/s.exec(block);
        if (!m) return block;
        const data = JSON.parse(m[2]!) as Record<string, unknown>;
        let out: unknown = data;
        if (m[1] === "system") out = system;
        else if (m[1] === "mcp") out = measured(data);
        else out = { ...data, system, mcps: (data.mcps as Record<string, unknown>[]).map(measured) };
        return `event: ${m[1]}\ndata: ${JSON.stringify(out)}\n\n`;
      };
      const realFetch = window.fetch.bind(window);
      window.fetch = async (input, init) => {
        const res = await realFetch(input, init);
        const url = new URL(input instanceof Request ? input.url : String(input), location.href);
        if (url.pathname !== "/api/stream" || !res.ok || !res.body) return res;
        let buffer = "";
        const blocks = new TransformStream<string, string>({
          transform(chunk, ctl) {
            buffer += chunk;
            for (let end = buffer.indexOf("\n\n"); end !== -1; end = buffer.indexOf("\n\n")) {
              ctl.enqueue(rewrite(buffer.slice(0, end + 2)));
              buffer = buffer.slice(end + 2);
            }
          },
        });
        const body = res.body.pipeThrough(new TextDecoderStream()).pipeThrough(blocks).pipeThrough(new TextEncoderStream());
        return new Response(body, { status: res.status, statusText: res.statusText, headers: res.headers });
      };
    },
    { spark: SPARK, system: SYSTEM },
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
  test(`screenshot ${screen.name}`, async ({ page, state, loginAs }, testInfo) => {
    // Light is the default theme (no saved choice): the light project shows that; the dark project
    // picks "dark" in the theme menu's storage, so each baseline is the theme its project names.
    if (testInfo.project.use.colorScheme === "dark") {
      await page.addInitScript((key) => {
        try {
          localStorage.setItem(key, "dark");
        } catch {
          // about:blank has no storage; the app's pages do
        }
      }, THEME_STORAGE_KEY);
    }
    await fixHistoryReads(page, state);
    await fixBoardStream(page);
    if (screen.who) await loginAs(page, screen.who, "local");
    await page.goto(`${state.localUrl}${screen.path.replace("{id}", String(state.mcpId))}`);
    await screen.ready(page);
    await page.evaluate(() => document.fonts.ready);
    await expect(page).toHaveScreenshot(`${screen.name}.png`, { fullPage: true, mask: [page.locator("[data-volatile]")] });
  });
}
