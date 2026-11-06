// Visual baselines, run in both the chromium-dark and chromium-light projects. Values that change
// from run to run (times, latency, sparklines, countdowns, uptime, activity rows) carry
// data-volatile and are masked (F32: earlier specs leave history behind).
// A mask hides values but not how many rows there are, so the reads whose length depends on what
// earlier specs (or this PC) did (recent activity, notice versions, tamper events) are answered with
// fixed data here: the baselines are the same whether this spec runs alone or after the whole
// suite. The MCP's port is fixed too (backend.ts MCP_PORT).
import type { Page, Route } from "@playwright/test";
import type { McpActivity, Notice, NoticeVersionSummary, TamperEvent } from "../src/lib/api-types";
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
