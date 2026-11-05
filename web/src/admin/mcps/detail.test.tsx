import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { copy } from "@/copy/ko";
import type { McpDetail, Me } from "@/lib/api-types";
import {
  actionDetailFixture, adminUser, historyFixture, item, mcpDetailFixture, meFixture, record, userSummary,
} from "../../../tests/msw/fixtures";
import { server, trackRequests } from "../../../tests/msw/server";
import { renderWithProviders } from "../../../tests/render";
import { qk } from "../query-keys";
import { SettingsTab } from "./SettingsTab";

/** The detail page in the full admin app (shell, toasts), with GET /api/mcps/:id answering `detail`. */
async function renderDetail(detail: McpDetail, { me = meFixture("admin", "local"), route }: { me?: Me; route?: string } = {}) {
  server.use(http.get(`/api/mcps/${detail.id}`, () => HttpResponse.json(detail)));
  const r = renderWithProviders(null, { route: route ?? `/admin/mcps/${detail.id}`, me });
  // the first test of a run pays for compiling the lazy route chunk under load
  await screen.findByRole("heading", { level: 1, name: detail.name }, { timeout: 5000 });
  return r;
}

const field = (label: string) => screen.getByLabelText(label);

/** Method + path of every request from now on (trackRequests() records paths only, and GET and PUT share one). */
function trackCalls(): () => string[] {
  const seen: string[] = [];
  server.events.on("request:start", ({ request }) => {
    seen.push(`${request.method} ${new URL(request.url).pathname}`);
  });
  return () => [...seen];
}
const saveButton = () => screen.getByRole("button", { name: copy.common.save });

async function retype(label: string, value: string) {
  await userEvent.clear(field(label));
  await userEvent.type(field(label), value);
}

// ---- settings ------------------------------------------------------------------------

it("live update keeps dirty fields", async () => {
  const { qc } = await renderDetail(mcpDetailFixture({ id: 1, action_delay_sec: 30, maintenance: false }));
  await userEvent.clear(field(copy.mcp.fields.action_delay_sec)); await userEvent.type(field(copy.mcp.fields.action_delay_sec), "45");
  act(() => qc.setQueryData(qk.mcp(1), mcpDetailFixture({ id: 1, action_delay_sec: 30, maintenance: true })));
  // React Query notifies observers on its own tick: wait for the update to land, then check the dirty field survived it
  await waitFor(() => expect(screen.getByRole("switch", { name: copy.mcp.fields.maintenance })).toBeChecked());
  expect(field(copy.mcp.fields.action_delay_sec)).toHaveValue(45);
});

it("live update replaces clean fields, including text and select values", async () => {
  const { qc } = await renderDetail(mcpDetailFixture({ id: 1, name: "calc", port: 9001 }));
  await retype(copy.mcp.fields.path, "/v2");
  act(() => qc.setQueryData(qk.mcp(1), mcpDetailFixture({ id: 1, name: "calc", port: 9100, path: "/mcp", probe: "tcp" })));
  await waitFor(() => expect(field(copy.mcp.fields.port)).toHaveValue(9100));
  expect(field(copy.mcp.fields.path)).toHaveValue("/v2");
  expect(screen.getByRole("combobox", { name: copy.mcp.fields.probe })).toHaveTextContent(copy.mcp.probes.tcp);
});

it("PUT sends only dirty fields", async () => {
  let body: unknown; server.use(http.put("/api/mcps/1", async ({ request }) => { body = await request.json(); return HttpResponse.json(mcpDetailFixture({ id: 1, action_delay_sec: 45 })); }));
  await renderDetail(mcpDetailFixture({ id: 1 }));
  expect(saveButton()).toHaveAttribute("aria-disabled", "true");
  // a dimmed button says why (U26)
  expect(saveButton()).toHaveAccessibleDescription(copy.deny.unchanged);
  expect(screen.getByRole("button", { name: copy.mcp.discard })).toHaveAccessibleDescription(copy.deny.unchanged);
  await retype(copy.mcp.fields.action_delay_sec, "45");
  expect(saveButton()).not.toHaveAttribute("aria-disabled");
  expect(saveButton()).not.toHaveAccessibleDescription(copy.deny.unchanged);
  await userEvent.click(saveButton());
  await waitFor(() => expect(body).toEqual({ action_delay_sec: 45 }));
  expect(await screen.findByText(copy.common.saved)).toBeInTheDocument();
  await waitFor(() => expect(saveButton()).toHaveAttribute("aria-disabled", "true"));
  expect(field(copy.mcp.fields.action_delay_sec)).toHaveValue(45);
});

it("sends normalized values and the maintenance switch as part of the same form", async () => {
  let body: unknown;
  server.use(http.put("/api/mcps/1", async ({ request }) => {
    body = await request.json();
    return HttpResponse.json(mcpDetailFixture({ id: 1, host: "example.com", maintenance: true }));
  }));
  await renderDetail(mcpDetailFixture({ id: 1 }));
  await retype(copy.mcp.fields.host, "  Example.COM ");
  await userEvent.click(screen.getByRole("switch", { name: copy.mcp.fields.maintenance }));
  await userEvent.click(saveButton());
  await waitFor(() => expect(body).toEqual({ host: "example.com", maintenance: true }));
});

it("does nothing when nothing changed, and a field typed back to its value is clean", async () => {
  const calls = trackCalls();
  await renderDetail(mcpDetailFixture({ id: 1, action_delay_sec: 30 }));
  await retype(copy.mcp.fields.action_delay_sec, "31");
  await retype(copy.mcp.fields.action_delay_sec, "30");
  expect(saveButton()).toHaveAttribute("aria-disabled", "true");
  await userEvent.click(saveButton());
  await new Promise((r) => setTimeout(r, 30));
  expect(calls()).not.toContain("PUT /api/mcps/1");
});

it("discard puts the server values back", async () => {
  await renderDetail(mcpDetailFixture({ id: 1, port: 9001 }));
  await retype(copy.mcp.fields.port, "9500");
  await userEvent.click(screen.getByRole("button", { name: copy.mcp.discard }));
  expect(field(copy.mcp.fields.port)).toHaveValue(9001);
  expect(saveButton()).toHaveAttribute("aria-disabled", "true");
});

it("blocks invalid input on the client with the field's rule", async () => {
  const calls = trackCalls();
  await renderDetail(mcpDetailFixture({ id: 1 }));
  await userEvent.clear(field(copy.mcp.fields.port));
  await retype(copy.mcp.fields.name, "a&b");
  await userEvent.click(saveButton());
  expect(await screen.findByText(copy.mcp.rangeError(1, 65535))).toBeInTheDocument();
  expect(screen.getByText(copy.mcp.nameRule, { selector: "[data-slot=form-message]" })).toBeInTheDocument();
  expect(field(copy.mcp.fields.port)).toHaveAttribute("aria-invalid", "true");
  expect(field(copy.mcp.fields.port)).toHaveAccessibleDescription(expect.stringContaining(copy.mcp.rangeError(1, 65535)));
  expect(calls()).not.toContain("PUT /api/mcps/1");
});

it("puts name_taken on the name field", async () => {
  server.use(http.put("/api/mcps/1", () => HttpResponse.json({ error: "name_taken" }, { status: 409 })));
  await renderDetail(mcpDetailFixture({ id: 1 }));
  await retype(copy.mcp.fields.name, "files");
  await userEvent.click(saveButton());
  expect(await screen.findByText(copy.errors.name_taken)).toBeInTheDocument();
  expect(field(copy.mcp.fields.name)).toHaveAttribute("aria-invalid", "true");
  expect(field(copy.mcp.fields.name)).toHaveValue("files"); // the edit stays for fixing
});

it("puts endpoint_taken on the port field", async () => {
  server.use(http.put("/api/mcps/1", () => HttpResponse.json({ error: "endpoint_taken" }, { status: 409 })));
  await renderDetail(mcpDetailFixture({ id: 1 }));
  await retype(copy.mcp.fields.port, "9002");
  await userEvent.click(saveButton());
  expect(await screen.findByText(copy.errors.endpoint_taken)).toBeInTheDocument();
  expect(field(copy.mcp.fields.port)).toHaveAttribute("aria-invalid", "true");
});

it("shows a server 422 as a form error", async () => {
  server.use(http.put("/api/mcps/1", () => HttpResponse.json({ error: "validation" }, { status: 422 })));
  await renderDetail(mcpDetailFixture({ id: 1 }));
  await retype(copy.mcp.fields.host, "999.1.1.1");
  await userEvent.click(saveButton());
  expect(await screen.findByText(copy.errors.validation)).toBeInTheDocument();
  expect(screen.getByText(copy.errors.validation).closest("[role=alert]")).not.toBeNull();
});

it("shows the config_error banner and still allows fixing", async () => {
  let body: unknown;
  server.use(http.put("/api/mcps/1", async ({ request }) => {
    body = await request.json();
    return HttpResponse.json(mcpDetailFixture({ id: 1, name: "calc", port: 9100 }));
  }));
  await renderDetail(mcpDetailFixture({ id: 1, name: "calc", config_error: true, live: null }));
  expect(screen.getByText(copy.mcp.configError).closest("[role=alert]")).not.toBeNull();
  expect(screen.getByText(copy.mcp.configErrorBadge)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: copy.mcp.start })).toHaveAccessibleDescription(copy.deny.config_error);
  await retype(copy.mcp.fields.port, "9100");
  await userEvent.click(saveButton());
  await waitFor(() => expect(body).toEqual({ port: 9100 }));
  await waitFor(() => expect(screen.queryByText(copy.mcp.configError)).not.toBeInTheDocument());
});

it("marks the stored values that break the rules when the config is in error", async () => {
  await renderDetail(mcpDetailFixture({ id: 1, name: "calc", config_error: true, live: null, script_timeout_sec: 999 }));
  expect(await screen.findByText(copy.mcp.rangeError(10, 120))).toBeInTheDocument();
  expect(field(copy.mcp.fields.script_timeout_sec)).toHaveAttribute("aria-invalid", "true");
  expect(field(copy.mcp.fields.port)).toHaveAttribute("aria-invalid", "false");
});

it("keeps unsaved settings while another tab is open", async () => {
  await renderDetail(mcpDetailFixture({ id: 1, port: 9001 }));
  await retype(copy.mcp.fields.port, "9500");
  await userEvent.click(screen.getByRole("tab", { name: copy.mcp.tabs.history }));
  await screen.findByRole("table", { name: copy.mcp.transitionsTitle });
  await userEvent.click(screen.getByRole("tab", { name: copy.mcp.tabs.settings }));
  expect(field(copy.mcp.fields.port)).toHaveValue(9500);
});

it("asks before leaving the page with unsaved settings", async () => {
  const { router } = await renderDetail(mcpDetailFixture({ id: 1 }));
  await retype(copy.mcp.fields.port, "9500");
  const nav = screen.getByRole("navigation", { name: copy.nav.label });
  await userEvent.click(within(nav).getByRole("link", { name: copy.nav.mcps }));
  const ask = await screen.findByRole("alertdialog", { name: copy.common.unsavedTitle });
  await userEvent.click(within(ask).getByRole("button", { name: copy.common.stay }));
  await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
  expect(router.state.location.pathname).toBe("/admin/mcps/1");
  expect(field(copy.mcp.fields.port)).toHaveValue(9500);

  await userEvent.click(within(nav).getByRole("link", { name: copy.nav.mcps }));
  await userEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: copy.common.leave }));
  await waitFor(() => expect(router.state.location.pathname).toBe("/admin/mcps"));
});

it("a delete leaves without asking, even with unsaved settings", async () => {
  const { router } = await renderDetail(mcpDetailFixture({ id: 1, name: "calc" }));
  await retype(copy.mcp.fields.port, "9500");
  await userEvent.click(screen.getByRole("button", { name: copy.common.delete }));
  const dialog = await screen.findByRole("alertdialog");
  await userEvent.type(within(dialog).getByLabelText(copy.mcp.deleteNameLabel), "calc");
  await userEvent.click(within(dialog).getByRole("button", { name: copy.mcp.deleteAction }));
  await waitFor(() => expect(router.state.location.pathname).toBe("/admin/mcps"));
  expect(screen.queryByRole("alertdialog", { name: copy.common.unsavedTitle })).not.toBeInTheDocument();
});

it("makes every input read-only with the reason when settings may not be edited", () => {
  renderWithProviders(<SettingsTab mcp={mcpDetailFixture({ id: 1 })} />, { me: meFixture(null, "local") });
  expect(field(copy.mcp.fields.name)).toHaveAttribute("readonly");
  expect(field(copy.mcp.fields.port)).toHaveAttribute("readonly");
  expect(screen.getByRole("switch", { name: copy.mcp.fields.maintenance })).toHaveAttribute("aria-disabled", "true");
  expect(screen.getByRole("combobox", { name: copy.mcp.fields.probe })).toBeDisabled();
  expect(saveButton()).toHaveAttribute("aria-disabled", "true");
  expect(saveButton()).toHaveAccessibleDescription(copy.deny.login);
});

// ---- header, permissions, not found ---------------------------------------------------

it("shows the header: state, endpoint, owner and the actions", async () => {
  await renderDetail(mcpDetailFixture({ id: 1, name: "calc", host: "10.0.0.5", port: 9102, owner: userSummary(7), live: item(1, "FAILED", "calc") }));
  expect(screen.getByText(copy.states.FAILED)).toBeInTheDocument();
  expect(screen.getByText("10.0.0.5:9102")).toBeInTheDocument();
  expect(screen.getByText(userSummary(7).name)).toBeInTheDocument();
  expect(screen.getByRole("group", { name: copy.mcp.actionsLabel("calc") })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: copy.mcp.tabs.settings })).toHaveAttribute("aria-selected", "true");
});

it("says when there is no owner", async () => {
  await renderDetail(mcpDetailFixture({ id: 1, owner: null }));
  expect(screen.getByText(copy.mcp.noOwner)).toBeInTheDocument();
});

it("transfer and delete are disabled with reasons for a developer non-owner", async () => {
  const requests = trackRequests();
  await renderDetail(mcpDetailFixture({ id: 1, owner: userSummary(6) }), { me: meFixture("developer", "local", 5) });
  const transfer = screen.getByRole("button", { name: copy.mcp.transferOwner });
  const del = screen.getByRole("button", { name: copy.common.delete });
  expect(transfer).toHaveAttribute("aria-disabled", "true");
  expect(transfer).toHaveAccessibleDescription(copy.deny.admin_only);
  expect(del).toHaveAttribute("aria-disabled", "true");
  expect(del).toHaveAccessibleDescription(copy.deny.owner_only);
  await userEvent.click(transfer);
  await userEvent.click(del);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  expect(requests.paths()).not.toContain("/api/users");
});

it("the owner developer may delete; remote mode allows neither", async () => {
  const { unmount } = await renderDetail(mcpDetailFixture({ id: 1, owner: userSummary(5) }), { me: meFixture("developer", "local", 5) });
  expect(screen.getByRole("button", { name: copy.common.delete })).not.toHaveAttribute("aria-disabled");
  unmount();
  await renderDetail(mcpDetailFixture({ id: 1, owner: userSummary(5) }), { me: meFixture("admin", "external", 5) });
  expect(screen.getByRole("button", { name: copy.common.delete })).toHaveAccessibleDescription(copy.deny.local_only);
  expect(screen.getByRole("button", { name: copy.mcp.transferOwner })).toHaveAccessibleDescription(copy.deny.local_only);
});

it("shows a not-found state with a way back for an unknown MCP", async () => {
  server.use(http.get("/api/mcps/99", () => HttpResponse.json({ error: "not_found" }, { status: 404 })));
  renderWithProviders(null, { route: "/admin/mcps/99", me: meFixture("admin", "local") });
  expect(await screen.findByText(copy.mcp.notFound, undefined, { timeout: 5000 })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: copy.mcp.backToList })).toHaveAttribute("href", "/admin/mcps");
});

it("treats a non-numeric id as not found without asking the server", async () => {
  const requests = trackRequests();
  renderWithProviders(null, { route: "/admin/mcps/abc", me: meFixture("admin", "local") });
  expect(await screen.findByText(copy.mcp.notFound, undefined, { timeout: 5000 })).toBeInTheDocument();
  expect(requests.paths().filter((p) => p.startsWith("/api/mcps/"))).toEqual([]);
});

// ---- ownership transfer ---------------------------------------------------------------

it("transfers ownership to an active user", async () => {
  let body: unknown;
  server.use(
    http.get("/api/users", () =>
      HttpResponse.json([
        adminUser({ id: 1 }),
        adminUser({ id: 2, role: "developer" }),
        adminUser({ id: 3, role: "developer", active: false }),
      ]),
    ),
    http.post("/api/mcps/1/owner", async ({ request }) => {
      body = await request.json();
      return HttpResponse.json(mcpDetailFixture({ id: 1, name: "calc", owner: userSummary(2) }));
    }),
  );
  await renderDetail(mcpDetailFixture({ id: 1, name: "calc", owner: userSummary(1) }));
  await userEvent.click(screen.getByRole("button", { name: copy.mcp.transferOwner }));
  const dialog = await screen.findByRole("dialog", { name: copy.mcp.transferOwner });
  await userEvent.click(within(dialog).getByRole("combobox", { name: copy.mcp.newOwner }));
  const options = await screen.findAllByRole("option");
  expect(options.map((o) => o.textContent)).toEqual([
    expect.stringContaining("user1"),
    expect.stringContaining("user2"),
  ]); // the inactive user3 is not offered
  expect(options[0]).toHaveAttribute("aria-disabled", "true"); // the current owner
  await userEvent.click(screen.getByRole("option", { name: /user2/ }));
  await userEvent.click(within(dialog).getByRole("button", { name: copy.mcp.transferSubmit }));
  await waitFor(() => expect(body).toEqual({ user_id: 2 }));
  expect(await screen.findByText(copy.mcp.transferred("calc", "user2"))).toBeInTheDocument();
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(screen.getByText("user2")).toBeInTheDocument();
});

it("shows invalid_owner inside the transfer dialog", async () => {
  server.use(http.post("/api/mcps/1/owner", () => HttpResponse.json({ error: "invalid_owner" }, { status: 422 })));
  await renderDetail(mcpDetailFixture({ id: 1, owner: userSummary(1) }));
  await userEvent.click(screen.getByRole("button", { name: copy.mcp.transferOwner }));
  const dialog = await screen.findByRole("dialog");
  await userEvent.click(within(dialog).getByRole("combobox", { name: copy.mcp.newOwner }));
  await userEvent.click(await screen.findByRole("option", { name: /user2/ }));
  await userEvent.click(within(dialog).getByRole("button", { name: copy.mcp.transferSubmit }));
  expect(await within(dialog).findByRole("alert")).toHaveTextContent(copy.errors.invalid_owner);
});

it("transfer needs a chosen user", async () => {
  const requests = trackRequests();
  await renderDetail(mcpDetailFixture({ id: 1 }));
  await userEvent.click(screen.getByRole("button", { name: copy.mcp.transferOwner }));
  const dialog = await screen.findByRole("dialog");
  const submit = within(dialog).getByRole("button", { name: copy.mcp.transferSubmit });
  expect(submit).toHaveAttribute("aria-disabled", "true");
  await userEvent.click(submit);
  expect(requests.paths()).not.toContain("/api/mcps/1/owner");
});

// ---- delete ---------------------------------------------------------------------------

it("delete needs the name typed again", async () => {
  const calls = trackCalls();
  const { router } = await renderDetail(mcpDetailFixture({ id: 1, name: "calc" }));
  await userEvent.click(screen.getByRole("button", { name: copy.common.delete }));
  const dialog = await screen.findByRole("alertdialog", { name: copy.mcp.deleteTitle("calc") });
  expect(dialog).toHaveAccessibleDescription(expect.stringContaining(copy.mcp.deleteConfirm));
  const confirm = within(dialog).getByRole("button", { name: copy.mcp.deleteAction });
  expect(confirm).toHaveAttribute("aria-disabled", "true");
  await userEvent.type(within(dialog).getByLabelText(copy.mcp.deleteNameLabel), "cal");
  await userEvent.click(confirm);
  expect(calls()).not.toContain("DELETE /api/mcps/1");
  await userEvent.type(within(dialog).getByLabelText(copy.mcp.deleteNameLabel), "c");
  expect(confirm).not.toHaveAttribute("aria-disabled");
  await userEvent.click(confirm);
  await waitFor(() => expect(router.state.location.pathname).toBe("/admin/mcps"));
  expect(calls()).toContain("DELETE /api/mcps/1");
  expect(await screen.findByText(copy.mcp.deleted("calc"))).toBeInTheDocument();
});

it("shows action_in_progress inside the delete dialog", async () => {
  server.use(http.delete("/api/mcps/1", () => HttpResponse.json({ error: "action_in_progress" }, { status: 409 })));
  const { router } = await renderDetail(mcpDetailFixture({ id: 1, name: "calc" }));
  await userEvent.click(screen.getByRole("button", { name: copy.common.delete }));
  const dialog = await screen.findByRole("alertdialog");
  await userEvent.type(within(dialog).getByLabelText(copy.mcp.deleteNameLabel), "calc");
  await userEvent.click(within(dialog).getByRole("button", { name: copy.mcp.deleteAction }));
  expect(await within(dialog).findByRole("alert")).toHaveTextContent(copy.errors.action_in_progress);
  expect(router.state.location.pathname).toBe("/admin/mcps/1");
});

// ---- history --------------------------------------------------------------------------

it("history lists transitions and actions and switches the period", async () => {
  const requests = trackRequests();
  await renderDetail(mcpDetailFixture({ id: 1 }), { route: "/admin/mcps/1?tab=history" });
  const transitions = await screen.findByRole("table", { name: copy.mcp.transitionsTitle });
  expect(within(transitions).getAllByRole("row")).toHaveLength(3); // header + 2
  expect(within(transitions).getAllByText(copy.issues.UNRESPONSIVE)).toHaveLength(2);
  const actions = screen.getByRole("table", { name: copy.mcp.actionsTitle });
  const cells = within(actions).getAllByRole("row")[1]!;
  expect(cells).toHaveTextContent(copy.mcp.triggers.manual);
  expect(cells).toHaveTextContent("user1");
  expect(cells).toHaveTextContent(copy.mcp.scriptStatus.ok);
  expect(cells).toHaveTextContent("1.2초");
  expect(requests.paths()).toContain("/api/mcps/1/history");

  const seen: string[] = [];
  server.events.on("request:start", ({ request }) => {
    const url = new URL(request.url);
    if (url.pathname === "/api/mcps/1/history") seen.push(url.searchParams.get("hours") ?? "");
  });
  const period = screen.getByRole("group", { name: copy.mcp.periodLabel });
  expect(within(period).getByRole("button", { name: copy.mcp.periods[24] })).toHaveAttribute("aria-pressed", "true");
  await userEvent.click(within(period).getByRole("button", { name: copy.mcp.periods[168] }));
  await waitFor(() => expect(seen).toEqual(["168"]));
  expect(within(period).getByRole("button", { name: copy.mcp.periods[168] })).toHaveAttribute("aria-pressed", "true");
});

it("history summarizes the period and draws the chart with a rule per transition", async () => {
  // jsdom has no layout: give the chart containers a size so Recharts draws
  const size = vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue(new DOMRect(0, 0, 800, 216));
  onTestFinished(() => size.mockRestore());
  const { container } = await renderDetail(mcpDetailFixture({ id: 1 }), { route: "/admin/mcps/1?tab=history" });
  // historyFixture: avg (11.5 + 30) / 2, max 80, uptime 22 / 36
  expect(await screen.findByText(copy.mcp.chartSummary(copy.mcp.periods[24], "21ms", "80ms", "61.1%"))).toBeInTheDocument();
  const figure = screen.getByRole("figure");
  expect(await within(figure).findByText(copy.mcp.chartTransition, undefined, { timeout: 5000 })).toBeInTheDocument(); // lazy legend
  // both transitions fall inside the minutes shown, drawn on the latency plot and the uptime strip
  await waitFor(() => expect(container.querySelectorAll(".recharts-reference-line")).toHaveLength(4));
  expect(container.querySelectorAll(".recharts-line")).toHaveLength(2);
}, 20_000); // two lazy chunks (page, chart) compile on first use under the parallel suite

it("history says so when the period has no records", async () => {
  server.use(http.get("/api/mcps/1/history", () => HttpResponse.json({ buckets: [], transitions: [], actions: [] })));
  await renderDetail(mcpDetailFixture({ id: 1 }), { route: "/admin/mcps/1?tab=history" });
  expect(await screen.findByText(copy.mcp.noHistory)).toBeInTheDocument();
  expect(screen.getByText(copy.mcp.noChartData)).toBeInTheDocument();
});

it("shows the restart fallback's stop step and an automatic action without an actor", async () => {
  server.use(
    http.get("/api/mcps/1/history", () =>
      HttpResponse.json({
        ...historyFixture(),
        actions: [record({ id: 8, requested: "restart", kind: "stop", trigger: "auto", actor: null, actor_id: null, reason: "PROCESS_DOWN" })],
      }),
    ),
  );
  await renderDetail(mcpDetailFixture({ id: 1 }), { route: "/admin/mcps/1?tab=history" });
  const actions = await screen.findByRole("table", { name: copy.mcp.actionsTitle });
  const r = within(actions).getAllByRole("row")[1]!;
  expect(r).toHaveTextContent(copy.mcp.requestedStep("restart", "stop"));
  expect(r).toHaveTextContent(copy.mcp.triggers.auto);
  expect(r).toHaveTextContent(copy.mcp.systemActor);
});

it("action rows open the output dialog with truncation notes", async () => {
  server.use(
    http.get("/api/mcps/1/history", () => HttpResponse.json({ ...historyFixture(), actions: [record({ id: 7 })] })),
    http.get("/api/mcps/1/actions/7", () =>
      HttpResponse.json(actionDetailFixture({ id: 7, stdout: "booting\nready", stderr: "warn: slow", stdout_truncated: true })),
    ),
  );
  await renderDetail(mcpDetailFixture({ id: 1 }), { route: "/admin/mcps/1?tab=history" });
  const actions = await screen.findByRole("table", { name: copy.mcp.actionsTitle });
  await userEvent.click(within(actions).getAllByRole("row")[1]!);
  const dialog = await screen.findByRole("dialog");
  const stdout = await within(dialog).findByText(/booting/);
  expect(stdout.tagName).toBe("PRE");
  expect(stdout).toHaveTextContent("booting ready");
  expect(within(dialog).getByText("warn: slow").tagName).toBe("PRE");
  expect(within(dialog).getAllByText(copy.mcp.truncated)).toHaveLength(1); // stdout only
});

it("an action row also opens from the keyboard", async () => {
  server.use(http.get("/api/mcps/1/history", () => HttpResponse.json({ ...historyFixture(), actions: [record({ id: 7 })] })));
  await renderDetail(mcpDetailFixture({ id: 1 }), { route: "/admin/mcps/1?tab=history" });
  const actions = await screen.findByRole("table", { name: copy.mcp.actionsTitle });
  const open = within(actions).getByRole("button", { name: new RegExp(copy.mcp.viewOutput) });
  open.focus();
  await userEvent.keyboard("{Enter}");
  const dialog = await screen.findByRole("dialog");
  expect(await within(dialog).findByText(/started/)).toBeInTheDocument();
  expect(within(dialog).getByText(copy.mcp.noOutput)).toBeInTheDocument(); // empty stderr
  await userEvent.keyboard("{Escape}");
  await waitFor(() => expect(open).toHaveFocus());
});

it("switching tabs writes the tab to the URL", async () => {
  const { router } = await renderDetail(mcpDetailFixture({ id: 1 }));
  await userEvent.click(screen.getByRole("tab", { name: copy.mcp.tabs.history }));
  await waitFor(() => expect(router.state.location.search).toEqual({ tab: "history" }));
  await userEvent.click(screen.getByRole("tab", { name: copy.mcp.tabs.scripts }));
  await waitFor(() => expect(router.state.location.search).toEqual({ tab: "scripts" }));
});
