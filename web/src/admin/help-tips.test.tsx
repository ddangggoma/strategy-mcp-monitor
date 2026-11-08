// Every screen shows its key help tips (docs/design/help-tips.md) with the right words: each tip is
// opened by its button's name ("<label> 설명") and read from the open tooltip.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { helpText, type HelpContent } from "@/components/app/InfoTip";
import { copy } from "@/copy/ko";
import type { BoardItem } from "@/lib/api-types";
import { BoardStore } from "@/lib/board-store";
import type { BoardStreamClient } from "@/lib/board-stream";
import { session } from "@/lib/session";
import { BoardPage } from "@/board/BoardPage";
import {
  boardEvent, failureFixture, item, mcpDetailFixture, meFixture, rdpSession, sessionsHistoryFixture,
} from "../../tests/msw/fixtures";
import { server } from "../../tests/msw/server";
import { renderWithProviders } from "../../tests/render";
import { warmChunks } from "../../tests/warm";

warmChunks("login", "setup", "dashboard", "sessions", "mcpList", "mcpCreate", "mcpDetail", "chart", "users", "settings", "notice", "logs", "audit");

const ADMIN = meFixture("admin", "local");

/** Opens the tip named after `label` (the first one, or the one inside `scope`), checks its words, closes it. */
async function expectTip(label: string, content: HelpContent, scope?: HTMLElement) {
  const where = scope ? within(scope) : screen;
  const buttons = await where.findAllByRole("button", { name: copy.help.label(label) });
  const button = buttons[0]!;
  await userEvent.click(button);
  const tip = await screen.findByRole("tooltip");
  // the open tip lays a list out as terms and meanings; the words are the same as the text form
  const words = (s: string | null) => (s ?? "").replace(/[\s:]/g, "");
  expect(words(tip.textContent)).toBe(words(helpText(content)));
  if (typeof content !== "string") for (const [term] of content.items) expect(within(tip).getByText(term).tagName).toBe("DT");
  expect(button.getAttribute("aria-describedby")).toBe(tip.id); // the open tip describes its button
  await userEvent.click(button); // pinned by the click: a second click closes it
  await waitFor(() => expect(screen.queryByRole("tooltip")).toBeNull());
}

it("board: the state legend, card metrics, issue, countdown, session fields and channel", async () => {
  const counting: BoardItem = { ...item(2, "SUSPECT", "weather"), action_in_sec: 20, action_delay_sec: 30 };
  const store = new BoardStore();
  store.apply(boardEvent({ mcps: [item(1, "HEALTHY", "calc"), counting], sessions: [rdpSession()] }));
  store.setStatus("open");
  session.me = meFixture(null, "external");
  render(<BoardPage store={store} stream={{ restart: vi.fn() } as unknown as BoardStreamClient} />);

  await expectTip(copy.help.stateLabel, copy.help.stateLegend);
  await expectTip(copy.board.latency, copy.help.latency);
  await expectTip(copy.board.uptime24h, copy.help.uptime);
  await expectTip(copy.issues.PROCESS_DOWN, copy.help.issues.PROCESS_DOWN);
  await expectTip(copy.board.autoAction, copy.help.countdown);
  await expectTip(copy.sessions.fields.idle, copy.help.session.idle);
  await expectTip(copy.sessions.fields.reverseDns, copy.help.session.reverseDns);
  await expectTip(copy.sessions.fields.notice, copy.help.session.notice);
  await expectTip(copy.sessions.fields.state, copy.help.session.state);
  await expectTip(copy.channel.external, copy.channel.externalHint);
});

it("login: the development OTP badge", async () => {
  renderWithProviders(null, { route: "/admin/login", me: meFixture(null, "local") });
  await expectTip(copy.login.devBadge, copy.help.devOtp);
  await expectTip(copy.channel.local, copy.channel.localHint);
});

it("setup: what an Admin is", async () => {
  server.use(http.get("/api/bootstrap", () => HttpResponse.json({ needed: true })));
  renderWithProviders(null, { route: "/admin/setup", me: meFixture(null, "local") });
  await expectTip(copy.roles.admin, copy.help.setupAdmin);
});

it("dashboard: every card", async () => {
  const r = renderWithProviders(null, { route: "/admin", me: ADMIN });
  r.store.apply(boardEvent({ mcps: [item(1, "HEALTHY")], sessions: [] }));
  await expectTip(copy.dashboard.mcpSummary, copy.help.stateLegend);
  await expectTip(copy.dashboard.recentActivity, copy.help.dashboard.recent);
  await expectTip(copy.dashboard.loginFailures.title, copy.help.dashboard.loginFailures);
  await expectTip(copy.dashboard.bypassEvents, copy.help.dashboard.tamper);
});

it("MCP list: the state, latency, uptime and action headers keep their names", async () => {
  renderWithProviders(null, { route: "/admin/mcps", me: ADMIN });
  await expectTip(copy.mcp.columns.state, copy.help.stateLegend);
  await expectTip(copy.mcp.columns.latency, copy.help.latency);
  await expectTip(copy.mcp.columns.uptime, copy.help.uptime);
  await expectTip(copy.mcp.columns.actions, copy.help.mcp.actions);
  expect(screen.getByRole("columnheader", { name: copy.mcp.columns.latency })).toBeInTheDocument();
});

it("MCP detail: the current state, owner, actions and every non-obvious setting", async () => {
  server.use(
    http.get("/api/mcps/:id", () =>
      HttpResponse.json(mcpDetailFixture({ id: 1, live: { ...item(1, "FAILED"), issue: "UNRESPONSIVE" } })),
    ),
  );
  renderWithProviders(null, { route: "/admin/mcps/1", me: ADMIN });
  await expectTip(copy.help.stateLabel, { lead: copy.help.states.FAILED, items: [[copy.issues.UNRESPONSIVE, copy.help.issues.UNRESPONSIVE]] });
  await expectTip(copy.mcp.owner, copy.help.mcp.owner);
  await expectTip(copy.mcp.columns.actions, copy.help.mcp.actions);
  await expectTip(copy.help.mcp.recoveryGroupLabel, copy.help.mcp.recoveryGroup);
  const f = copy.mcp.fields;
  const h = copy.help.mcp.fields;
  await expectTip(f.host, h.host);
  await expectTip(f.path, h.path);
  await expectTip(f.probe, h.probe);
  await expectTip(f.expected_process_name, h.expected_process_name);
  await expectTip(f.action_delay_sec, h.action_delay_sec);
  await expectTip(f.startup_grace_sec, h.startup_grace_sec);
  await expectTip(f.max_auto_actions, h.max_auto_actions);
  await expectTip(f.window_sec, h.window_sec);
  await expectTip(f.script_timeout_sec, h.script_timeout_sec);
  await expectTip(f.auto_recovery, h.auto_recovery);
  await expectTip(f.maintenance, h.maintenance);
  await expectTip(f.autostart_on_boot, h.autostart_on_boot);
  await expectTip(copy.mcp.icon.legend, copy.help.mcp.icon);
  await expectTip(copy.mcp.icon.image, copy.help.mcp.iconImage);
  // the tips stand beside the labels: fields and groups keep their own names
  expect(screen.getByRole("spinbutton", { name: f.action_delay_sec })).toBeInTheDocument();
  expect(screen.getByRole("switch", { name: f.auto_recovery })).toBeInTheDocument();
  expect(screen.getByRole("group", { name: copy.mcp.groups.recovery })).toBeInTheDocument();
  expect(screen.getByRole("group", { name: copy.mcp.icon.legend })).toBeInTheDocument();
}, 15_000); // twenty tips over the whole settings form (with the icon picker): slow under a loaded full run

it("MCP history: the chart and the action log", async () => {
  renderWithProviders(null, { route: "/admin/mcps/1?tab=history", me: ADMIN });
  await expectTip(copy.mcp.chartTitle, copy.help.mcp.chart);
  await expectTip(copy.mcp.actionsTitle, copy.help.mcp.actionLog);
});

it("MCP scripts: the script kind and the version history", async () => {
  renderWithProviders(null, { route: "/admin/mcps/1?tab=scripts", me: meFixture("developer", "local", 1) });
  await expectTip(copy.scripts.kinds.start, copy.help.scripts.kinds.start);
  await expectTip(copy.scripts.versions, copy.help.scripts.versions);
});

it("MCP registration: each script kind and the extension, with the groups still named by their legends", async () => {
  renderWithProviders(null, { route: "/admin/mcps/new", me: ADMIN });
  await expectTip(copy.scripts.kinds.stop, copy.help.scripts.kinds.stop);
  await expectTip(copy.scripts.kinds.restart, copy.help.scripts.kinds.restart);
  await expectTip(copy.scripts.ext, copy.help.scripts.ext);
  expect(screen.getByRole("group", { name: copy.scripts.kinds.stop })).toBeInTheDocument();
});

it("sessions: connection kind, notice, logon failure columns and collectors", async () => {
  server.use(http.get("/api/sessions/history", () => HttpResponse.json(sessionsHistoryFixture({ failures: [failureFixture()] }))));
  renderWithProviders(null, { route: "/admin/sessions", me: ADMIN });
  await expectTip(copy.sessions.columns.kind, copy.help.sessions.kind);
  await expectTip(copy.sessions.fields.notice, copy.help.sessions.notice, await screen.findByRole("table", { name: copy.sessions.history }));
  await expectTip(copy.sessions.columns.logonType, copy.help.sessions.logonType);
  await expectTip(copy.sessions.columns.status, copy.help.sessions.status);
  await expectTip(copy.sessions.collectors, copy.help.sessions.collectors);
  expect(screen.getByRole("columnheader", { name: copy.sessions.columns.kind })).toBeInTheDocument();
});

it("logs: session number, keyword, view and the command log", async () => {
  renderWithProviders(null, { route: "/admin/logs", me: ADMIN });
  await expectTip(copy.logs.session, copy.help.logs.session);
  await expectTip(copy.logs.keyword, copy.logs.keywordHint);
  await expectTip(copy.logs.viewLabel, copy.help.logs.view);
  await expectTip(copy.logs.cats["activity.command"], copy.logs.cmdLimitHelp);
  expect(screen.getByRole("textbox", { name: copy.logs.session })).toBeInTheDocument();
});

it("audit: record kinds, channel and result", async () => {
  renderWithProviders(null, { route: "/admin/audit", me: ADMIN });
  await expectTip(copy.audit.tabsLabel, copy.help.audit.kinds);
  await expectTip(copy.audit.columns.channel, copy.help.audit.channel);
  await expectTip(copy.audit.columns.result, copy.help.audit.result);
});

it("users: role, active and owned MCPs", async () => {
  renderWithProviders(null, { route: "/admin/users", me: ADMIN });
  await expectTip(copy.users.role, copy.help.users.role);
  await expectTip(copy.users.active, copy.help.users.active);
  await expectTip(copy.users.ownedMcps, copy.help.users.ownedMcps);
});

it("settings: every interval, retention, compression, start type and OTP provider", async () => {
  renderWithProviders(null, { route: "/admin/settings", me: ADMIN });
  const f = copy.settings.fields;
  const h = copy.help.settings;
  await expectTip(f.ping_interval_sec, h.ping_interval_sec);
  await expectTip(f.issue_check_interval_sec, h.issue_check_interval_sec);
  await expectTip(f.confirm_interval_sec, h.confirm_interval_sec);
  await expectTip(f.log_retention_days, h.log_retention_days);
  await expectTip(f.log_compress_after_days, h.log_compress_after_days);
  await expectTip(f.service_start_type, h.service_start_type);
  await expectTip(f.otp_provider, h.otp_provider);
  expect(screen.getByRole("spinbutton", { name: f.log_retention_days })).toBeInTheDocument();
});

it("notice editor: what the notice is and its button", async () => {
  renderWithProviders(null, { route: "/admin/notice", me: ADMIN });
  await expectTip(copy.notice.title, copy.help.notice.what);
  await expectTip(copy.notice.fields.button_text, copy.help.notice.button);
  expect(screen.getByRole("textbox", { name: copy.notice.fields.button_text })).toBeInTheDocument();
});
