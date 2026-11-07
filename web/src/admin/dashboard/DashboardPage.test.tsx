import { act, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { copy } from "@/copy/ko";
import type { BoardItem, McpActivity, RdpSession } from "@/lib/api-types";
import { BoardStore } from "@/lib/board-store";
import { NOW, activityFixture, boardEvent, histogramFixture, item, meFixture, rdpSession, record, tamperFixture } from "../../../tests/msw/fixtures";
import { server, trackRequests } from "../../../tests/msw/server";
import { renderWithProviders } from "../../../tests/render";
import { warmChunks } from "../../../tests/warm";
import { connectLive } from "../live";

warmChunks("dashboard", "mcpList");

/** The dashboard in the admin app, with the live store already holding `mcps` (and `sessions` when given). */
async function renderDashboard({ mcps, activity, sessions }: { mcps: BoardItem[]; activity: McpActivity; sessions?: RdpSession[] }) {
  server.use(http.get("/api/mcp-activity", () => HttpResponse.json(activity)));
  const store = new BoardStore();
  store.apply(boardEvent({ mcps, ...(sessions ? { sessions } : {}) }));
  const r = renderWithProviders(null, { route: "/admin", me: meFixture("developer", "external"), live: { store } });
  connectLive(store, r.qc); // what admin/main.tsx does for the tab
  // the first test of a run pays for compiling the lazy route chunk under load
  await screen.findByRole("heading", { level: 1, name: copy.dashboard.title }, { timeout: 5000 });
  return r;
}

const card = (name: string) => screen.getByRole("region", { name });

it("summarizes states, lists recent activity and has no planned card left", async () => {
  await renderDashboard({ mcps: [item(1, "FAILED"), item(2, "HEALTHY"), item(3, "HEALTHY")], activity: activityFixture() });
  expect(screen.getByRole("link", { name: /실패\s*1/ })).toHaveAttribute("href", "/admin/mcps?state=FAILED");
  expect(screen.queryByText(copy.deny.planned_logs)).toBeNull();
  const activity = card(copy.dashboard.recentActivity);
  expect(await within(activity).findAllByText("seoul-weather")).toHaveLength(2);
});

it("links each non-zero state count and the total, and leaves zero counts as plain text", async () => {
  await renderDashboard({ mcps: [item(1, "FAILED"), item(2, "HEALTHY"), item(3, "HEALTHY")], activity: activityFixture() });
  const summary = card(copy.dashboard.mcpSummary);
  expect(within(summary).getByRole("link", { name: /정상\s*2/ })).toHaveAttribute("href", "/admin/mcps?state=HEALTHY");
  expect(within(summary).getByRole("link", { name: /전체\s*3/ })).toHaveAttribute("href", "/admin/mcps");
  expect(within(summary).queryByRole("link", { name: /이상 감지/ })).not.toBeInTheDocument();
  expect(within(summary).getByText(copy.states.SUSPECT)).toBeInTheDocument();
  expect(within(summary).getAllByRole("link")).toHaveLength(3);
});

it("lists the newest ten issues and actions in KST, skipping recoveries to healthy", async () => {
  const transitions: McpActivity["transitions"] = [
    { at: "2026-11-04T14:00:00.000+09:00", from: "FAILED", to: "HEALTHY", issue: null, mcp_id: 1, name: "calc" },
    ...Array.from({ length: 12 }, (_, i) => ({
      at: `2026-11-04T13:${String(10 + i).padStart(2, "0")}:00.000+09:00`,
      from: "HEALTHY" as const,
      to: "SUSPECT" as const,
      issue: "UNRESPONSIVE" as const,
      mcp_id: 2,
      name: `m${i}`,
    })),
  ];
  const actions: McpActivity["actions"] = [
    { ...record({ id: 9, run_id: "x", at: "2026-11-04T13:59:00.000+09:00", trigger: "auto", kind: "restart", status: "failed" }), mcp_id: 3, name: "files" },
  ];
  await renderDashboard({ mcps: [], activity: { transitions, actions } });
  const table = await within(card(copy.dashboard.recentActivity)).findByRole("table");
  const rows = within(table).getAllByRole("row").slice(1); // header row first
  expect(rows).toHaveLength(10);
  expect(table).toHaveAttribute("data-volatile"); // rows depend on earlier history: masked in visual baselines (F32)
  const [first, second] = rows as [HTMLElement, HTMLElement];
  expect(within(first).getByText("files")).toBeInTheDocument();
  expect(within(first).getByText("2026-11-04 13:59:00")).toBeInTheDocument();
  expect(within(first).getByText(copy.dashboard.actionLine(copy.mcp.triggers.auto, "restart"))).toBeInTheDocument();
  expect(within(first).getByText(copy.mcp.scriptStatus.failed)).toBeInTheDocument();
  expect(within(second).getByText("m11")).toBeInTheDocument();
  expect(within(second).getByText(copy.states.SUSPECT)).toBeInTheDocument();
  expect(within(second).getByText(copy.issues.UNRESPONSIVE)).toBeInTheDocument();
  expect(within(second).getByRole("link", { name: "m11" })).toHaveAttribute("href", "/admin/mcps/2");
  expect(within(table).queryByText("calc")).not.toBeInTheDocument(); // recovered to HEALTHY
  expect(within(table).queryByText("m0")).not.toBeInTheDocument(); // 11th and later
});

it("says when there is no recent activity", async () => {
  await renderDashboard({ mcps: [], activity: { transitions: [], actions: [] } });
  expect(await screen.findByText(copy.dashboard.noActivity)).toBeInTheDocument();
  expect(within(card(copy.dashboard.mcpSummary)).getByText(copy.dashboard.noMcp)).toBeInTheDocument();
});

it("shows the activity error instead of an empty list", async () => {
  server.use(http.get("/api/mcp-activity", () => HttpResponse.json({ error: "internal" }, { status: 500 })));
  const store = new BoardStore();
  renderWithProviders(null, { route: "/admin", me: meFixture("admin", "local"), live: { store } });
  expect(await screen.findByText(copy.dashboard.activityError, {}, { timeout: 5000 })).toBeInTheDocument();
  expect(screen.queryByText(copy.dashboard.noActivity)).not.toBeInTheDocument();
});

it("shows the session banner and cards from the live store", async () => {
  await renderDashboard({ mcps: [], activity: activityFixture(), sessions: [rdpSession({ user: "hong", connected_at: NOW })] });
  const sessions = card(copy.dashboard.currentSessions);
  expect(within(sessions).getByText(copy.board.connected)).toBeInTheDocument();
  expect(within(sessions).getByText("hong")).toBeInTheDocument();
});

it("says sessions are not collected yet when the board has none", async () => {
  await renderDashboard({ mcps: [], activity: activityFixture() });
  expect(within(card(copy.dashboard.currentSessions)).getByText(copy.board.sessionsNotReady)).toBeInTheDocument();
});

it("shows recent tamper events and prepends live ones", async () => {
  server.use(http.get("/api/tamper/recent", () => HttpResponse.json([tamperFixture({ event: "log_cleared", at: "2026-11-04T13:00:00.000+09:00" })])));
  const { store } = await renderDashboard({ mcps: [item(1, "HEALTHY")], activity: activityFixture() });
  expect(await screen.findByText(copy.tamper.events.log_cleared)).toBeInTheDocument();
  act(() => store.apply({ event: "tamper", data: JSON.stringify(tamperFixture({ event: "agent_exited" })) }));
  expect(await screen.findByText(copy.tamper.events.agent_exited)).toBeInTheDocument();
  // newest first
  const items = within(card(copy.dashboard.bypassEvents)).getAllByRole("listitem");
  expect(items[0]).toHaveTextContent(copy.tamper.events.agent_exited);
  expect(items[1]).toHaveTextContent(copy.tamper.events.log_cleared);
});

it("current-session card follows the board sessions (Plan 3 contract)", async () => {
  const { store } = await renderDashboard({ mcps: [item(1, "HEALTHY")], activity: activityFixture() });
  act(() => store.apply(boardEvent({ mcps: [item(1, "HEALTHY")], sessions: [rdpSession({ user: "hong", notice_acknowledged: true })] })));
  expect(await screen.findByText(copy.board.connected)).toBeInTheDocument();
  expect(screen.getByText(copy.sessions.noticeAcked)).toBeInTheDocument();
  act(() => store.apply({ event: "sessions", data: '{"sessions":[]}' }));
  expect(await screen.findByText(copy.board.noSession)).toBeInTheDocument();
});

it("summarizes each tamper event by user and session, or by the file it is about, in KST", async () => {
  server.use(http.get("/api/tamper/recent", () => HttpResponse.json([
    tamperFixture({ event: "agent_exited", at: "2026-11-04T13:05:00.000+09:00", session_id: 3, user: "CORP\\kim" }),
    { at: "2026-11-04T13:00:00.000+09:00", event: "log_file_removed", file: "2026-11-04.jsonl" },
  ])));
  await renderDashboard({ mcps: [], activity: activityFixture() });
  const tamper = card(copy.dashboard.bypassEvents);
  const [first, second] = (await within(tamper).findAllByRole("listitem")) as [HTMLElement, HTMLElement];
  expect(within(first).getByText("2026-11-04 13:05:00")).toBeInTheDocument();
  expect(within(first).getByText(`CORP\\kim, ${copy.tamper.session(3)}`)).toBeInTheDocument();
  expect(within(second).getByText(copy.tamper.events.log_file_removed)).toBeInTheDocument();
  expect(within(second).getByText("2026-11-04.jsonl")).toBeInTheDocument();
});

it("shows at most ten tamper events and says when there are none", async () => {
  server.use(http.get("/api/tamper/recent", () =>
    HttpResponse.json(Array.from({ length: 12 }, (_, i) => tamperFixture({ session_id: i + 1 })))));
  const { unmount } = await renderDashboard({ mcps: [], activity: activityFixture() });
  expect(await within(card(copy.dashboard.bypassEvents)).findAllByRole("listitem")).toHaveLength(10);
  unmount();
  server.use(http.get("/api/tamper/recent", () => HttpResponse.json([])));
  await renderDashboard({ mcps: [], activity: activityFixture() });
  expect(await within(card(copy.dashboard.bypassEvents)).findByText(copy.tamper.empty)).toBeInTheDocument();
});

it("refetches tamper events after the stream reconnects", async () => {
  let calls = 0;
  server.use(http.get("/api/tamper/recent", () => {
    calls++;
    return HttpResponse.json(calls === 1 ? [] : [tamperFixture({ event: "audit_policy_changed" })]);
  }));
  const { store } = await renderDashboard({ mcps: [], activity: activityFixture() });
  await within(card(copy.dashboard.bypassEvents)).findByText(copy.tamper.empty);
  act(() => {
    store.setStatus("open");
    store.setStatus("reconnecting");
    store.setStatus("open");
  });
  expect(await screen.findByText(copy.tamper.events.audit_policy_changed)).toBeInTheDocument();
});

// ---- login failure trend (Plan 5 Task 12) ------------------------------------------------

it("shows the login failure trend for web and RDP", async () => {
  server.use(http.get("/api/logs/histogram", ({ request }) => {
    const p = new URL(request.url).searchParams;
    expect(p.getAll("outcome")).toEqual(["fail"]); expect(p.getAll("cat").sort()).toEqual(["auth", "session"]);
    return HttpResponse.json(histogramFixture({ series: [{ key: "auth", counts: [1, 0, 2, 0, 0, 0] }, { key: "session", counts: [0, 0, 0, 0, 3, 0] }], total: 6 }));
  }));
  await renderDashboard({ mcps: [], activity: activityFixture() });
  const card = (await screen.findByRole("heading", { name: copy.dashboard.loginFailures.title })).closest("section")!;
  expect(card).toHaveTextContent(copy.dashboard.loginFailures.web); expect(card).toHaveTextContent(copy.dashboard.loginFailures.rdp);
  expect(within(card).getByRole("link", { name: copy.dashboard.loginFailures.openLogs }).getAttribute("href")).toContain("/admin/logs");
  expect(screen.queryByText(copy.deny.planned_logs)).toBeNull();
});

it("asks for the last 24 hours in 24 bars and links the same conditions in the log viewer", async () => {
  const tracker = trackRequests();
  server.use(http.get("/api/logs/histogram", () =>
    HttpResponse.json(histogramFixture({ series: [{ key: "auth", counts: [1, 0, 2, 0, 0, 0] }, { key: "session", counts: [0, 0, 0, 0, 3, 0] }], total: 6 }))));
  await renderDashboard({ mcps: [], activity: activityFixture() });
  const region = card(copy.dashboard.loginFailures.title);
  // per-series totals as text: the chart is never the only way to read them
  await waitFor(() => expect(within(region).getByText(copy.dashboard.loginFailures.web).closest("li")).toHaveTextContent("3"));
  expect(within(region).getByText(copy.dashboard.loginFailures.rdp).closest("li")).toHaveTextContent("3");
  expect(region).toHaveTextContent(copy.logs.total(6));
  const [req] = tracker.urls().map((u) => new URL(u, "http://x")).filter((u) => u.pathname === "/api/logs/histogram");
  const p = req!.searchParams;
  expect([p.get("buckets"), p.get("group")]).toEqual(["24", "cat"]);
  expect(p.getAll("event").sort()).toEqual(["login", "logon_failed"]);
  const from = p.get("from")!, to = p.get("to")!;
  expect(to).toMatch(/:00\.000\+09:00$/);
  expect(Date.parse(to) - Date.parse(from)).toBe(24 * 3_600_000);
  // the link reproduces the same window and conditions (custom bounds, not "today")
  const href = new URL(within(region).getByRole("link", { name: copy.dashboard.loginFailures.openLogs }).getAttribute("href")!, "http://x");
  expect(href.pathname).toBe("/admin/logs");
  // the router writes arrays as JSON and plain strings as they are
  const value = (v: string): unknown => { try { return JSON.parse(v); } catch { return v; } };
  const search = Object.fromEntries([...href.searchParams].map(([k, v]) => [k, value(v)]));
  expect(search).toEqual({ from, to, cat: ["auth", "session"], event: ["login", "logon_failed"], outcome: ["fail"] });
  // a picture with a name, not a control: no drag, no tab stop
  const chart = within(region).getByRole("img", { name: copy.dashboard.loginFailures.chartLabel(6) });
  expect(chart).not.toHaveAttribute("tabindex");
});

it("says when there were no login failures", async () => {
  server.use(http.get("/api/logs/histogram", () => HttpResponse.json(histogramFixture({ series: [], total: 0 }))));
  await renderDashboard({ mcps: [], activity: activityFixture() });
  expect(await within(card(copy.dashboard.loginFailures.title)).findByText(copy.dashboard.loginFailures.empty)).toBeInTheDocument();
  expect(within(card(copy.dashboard.loginFailures.title)).queryByRole("img")).toBeNull();
});

it("says when the trend cannot be read", async () => {
  server.use(http.get("/api/logs/histogram", () => HttpResponse.json({ error: "internal" }, { status: 500 })));
  await renderDashboard({ mcps: [], activity: activityFixture() });
  expect(await within(card(copy.dashboard.loginFailures.title)).findByRole("alert")).toHaveTextContent(copy.dashboard.loginFailures.error);
});
