import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { copy } from "@/copy/ko";
import type { McpDetail, Me } from "@/lib/api-types";
import { historyFixture, item, mcpDetailFixture, meFixture, record } from "../../../tests/msw/fixtures";
import { server, trackRequests } from "../../../tests/msw/server";
import { renderWithProviders } from "../../../tests/render";
import { connectLive } from "../live";
import { warmChunks } from "../../../tests/warm";

warmChunks("mcpList", "mcpDetail", "chart", "dashboard");

/** The MCP list page in the full admin app (shell, toasts, tracker), mirrored from the live store like main.tsx. */
async function renderList(list: McpDetail[], { me = meFixture("admin", "local"), route = "/admin/mcps" }: { me?: Me; route?: string } = {}) {
  server.use(http.get("/api/mcps", () => HttpResponse.json(list)));
  const r = renderWithProviders(null, { route, me });
  connectLive(r.store, r.qc);
  // the first test of a run pays for compiling the lazy route chunk under load
  await screen.findByRole("heading", { level: 1, name: copy.mcp.title }, { timeout: 5000 });
  if (list.length > 0) await screen.findByRole("table", { name: copy.mcp.listLabel });
  return r;
}

/** The table row whose name cell is `name`. */
function row(name: string): HTMLElement {
  const cell = screen.getByRole("rowheader", { name });
  const tr = cell.closest("tr");
  if (!tr) throw new Error(`no row for ${name}`);
  return tr;
}

const rowNames = () => screen.getAllByRole("rowheader").map((c) => c.textContent);

const actionEvent = (p: Record<string, unknown>) => ({
  event: "action",
  data: JSON.stringify({ run_id: "r9", mcp_id: 1, kind: "start", requested: "start", trigger: "manual", status: "ok", exit_code: 0, duration_ms: 1200, ...p }),
});

it("start posts the action, shows a pending toast and resolves it from the SSE action event", async () => {
  const { store } = await renderList([mcpDetailFixture({ id: 1, name: "calc" })]);
  server.use(http.post("/api/mcps/1/actions/start", () => HttpResponse.json({ run_id: "r9" }, { status: 202 })));
  await userEvent.click(within(row("calc")).getByRole("button", { name: copy.mcp.start }));
  expect(await screen.findByText(copy.toasts.pending("calc", "start"))).toBeInTheDocument();
  act(() => store.apply(actionEvent({})));
  expect(await screen.findByText(copy.toasts.ok("calc", "start"))).toBeInTheDocument();
  expect(screen.getByText(copy.toasts.exitAndDuration(0, "1.2초"))).toBeInTheDocument();
  expect(screen.queryByText(copy.toasts.pending("calc", "start"))).not.toBeInTheDocument();
});

it("shows a failure with exit code, duration and a link to the history", async () => {
  const { store } = await renderList([mcpDetailFixture({ id: 1, name: "calc" })]);
  server.use(http.post("/api/mcps/1/actions/start", () => HttpResponse.json({ run_id: "r9" }, { status: 202 })));
  await userEvent.click(within(row("calc")).getByRole("button", { name: copy.mcp.start }));
  await screen.findByText(copy.toasts.pending("calc", "start"));
  act(() => store.apply(actionEvent({ status: "failed", exit_code: 3 })));
  expect(await screen.findByText(copy.toasts.failed("calc", "start"))).toBeInTheDocument();
  expect(screen.getByText(copy.toasts.exitAndDuration(3, "1.2초"))).toBeInTheDocument();
  expect(screen.getByRole("link", { name: copy.toasts.viewHistory })).toHaveAttribute("href", "/admin/mcps/1?tab=history");
});

it("keeps a fallback restart pending through its stop step", async () => {
  const { store } = await renderList([mcpDetailFixture({ id: 1, name: "calc" })]);
  server.use(http.post("/api/mcps/1/actions/restart", () => HttpResponse.json({ run_id: "r9" }, { status: 202 })));
  await userEvent.click(within(row("calc")).getByRole("button", { name: copy.mcp.restart }));
  await screen.findByText(copy.toasts.pending("calc", "restart"));
  act(() => store.apply(actionEvent({ kind: "stop", requested: "restart" })));
  expect(await screen.findByText(copy.toasts.restartStep)).toBeInTheDocument();
  expect(screen.getByText(copy.toasts.pending("calc", "restart"))).toBeInTheDocument();
  act(() => store.apply(actionEvent({ kind: "start", requested: "restart", status: "timeout", exit_code: null, duration_ms: 120_000 })));
  expect(await screen.findByText(copy.toasts.failed("calc", "restart"))).toBeInTheDocument();
  expect(screen.getByText(copy.toasts.timedOut("2분"))).toBeInTheDocument();
});

it("ignores action events for runs this tab did not start", async () => {
  const { store } = await renderList([mcpDetailFixture({ id: 1, name: "calc" })]);
  server.use(http.post("/api/mcps/1/actions/start", () => HttpResponse.json({ run_id: "r9" }, { status: 202 })));
  await userEvent.click(within(row("calc")).getByRole("button", { name: copy.mcp.start }));
  await screen.findByText(copy.toasts.pending("calc", "start"));
  // someone else's run on the same MCP (another tab, or an automatic action)
  act(() => store.apply(actionEvent({ run_id: "someone-else", status: "failed", exit_code: 1 })));
  await new Promise((r) => setTimeout(r, 50));
  expect(screen.queryByText(copy.toasts.failed("calc", "start"))).not.toBeInTheDocument();
  expect(screen.getByText(copy.toasts.pending("calc", "start"))).toBeInTheDocument();
});

it("whole flow (RF3): after the stream reconnects, a run whose event was missed is settled from history", async () => {
  const { store } = await renderList([mcpDetailFixture({ id: 1, name: "calc" })]);
  server.use(http.post("/api/mcps/1/actions/start", () => HttpResponse.json({ run_id: "r9" }, { status: 202 })));
  await userEvent.click(within(row("calc")).getByRole("button", { name: copy.mcp.start }));
  await screen.findByText(copy.toasts.pending("calc", "start"));
  // the stream drops; the run's SSE event goes out meanwhile and is never seen by this tab
  act(() => store.setStatus("reconnecting"));
  const asked: string[] = [];
  server.use(
    http.get("/api/mcps/1/history", ({ request }) => {
      asked.push(new URL(request.url).search);
      return HttpResponse.json({
        ...historyFixture(),
        actions: [record({ run_id: "r9", kind: "start", requested: "start", status: "failed", exit_code: 2, duration_ms: 1500 })],
      });
    }),
  );
  act(() => store.setStatus("open")); // reconnected: AppShell asks the tracker to reconcile
  expect(await screen.findByText(copy.toasts.failed("calc", "start"))).toBeInTheDocument();
  expect(screen.getByText(copy.toasts.exitAndDuration(2, "1.5초"))).toBeInTheDocument();
  expect(asked).toEqual(["?hours=1"]);
  expect(screen.queryByText(copy.toasts.pending("calc", "start"))).not.toBeInTheDocument();
});

it("drops pending toasts when the shell goes away (Sonner would replay them to the next login)", async () => {
  const { unmount } = await renderList([mcpDetailFixture({ id: 1, name: "calc" })]);
  server.use(http.post("/api/mcps/1/actions/start", () => HttpResponse.json({ run_id: "r9" }, { status: 202 })));
  await userEvent.click(within(row("calc")).getByRole("button", { name: copy.mcp.start }));
  await screen.findByText(copy.toasts.pending("calc", "start"));
  unmount();
  await renderList([mcpDetailFixture({ id: 1, name: "calc" })]);
  await new Promise((r) => setTimeout(r, 50));
  expect(screen.queryByText(copy.toasts.pending("calc", "start"))).not.toBeInTheDocument();
});

/** Logs out through the account menu, answers the gated action, then logs in again (a new shell on this tab). */
async function logOutBeforeTheAnswer(kind: "restart" | "start", answer: () => Response) {
  const { router, unmount } = await renderList([mcpDetailFixture({ id: 1, name: "calc" })]);
  let release!: () => void;
  const gate = new Promise<void>((r) => (release = r));
  let answered!: () => void;
  const done = new Promise<void>((r) => (answered = r));
  server.use(
    http.post(`/api/mcps/1/actions/${kind}`, async () => {
      await gate;
      queueMicrotask(answered);
      return answer();
    }),
  );
  await userEvent.click(within(row("calc")).getByRole("button", { name: copy.mcp[kind] }));
  await userEvent.click(screen.getByRole("button", { name: copy.common.accountMenu("user1") }));
  await userEvent.click(await screen.findByRole("menuitem", { name: copy.common.logout }));
  await waitFor(() => expect(router.state.location.pathname).toBe("/admin/login"));
  await screen.findByLabelText(copy.login.email); // the shell is gone: its tracker is disposed
  release();
  await done;
  await new Promise((r) => setTimeout(r, 50)); // the mutation's onSuccess / onError runs after the body is read
  unmount();
  await renderList([mcpDetailFixture({ id: 1, name: "calc" })]);
  await new Promise((r) => setTimeout(r, 50)); // Sonner would replay a queued toast on the Toaster's first render
}

it("a 202 that arrives after logging out shows no toast at the next login", async () => {
  await logOutBeforeTheAnswer("restart", () => HttpResponse.json({ run_id: "r9" }, { status: 202 }));
  expect(screen.queryByText(copy.toasts.pending("calc", "restart"))).not.toBeInTheDocument();
});

it("an error that arrives after logging out shows no toast at the next login", async () => {
  await logOutBeforeTheAnswer("start", () => HttpResponse.json({ error: "action_in_progress" }, { status: 409 }));
  expect(screen.queryByText(copy.errors.action_in_progress)).not.toBeInTheDocument();
});

it("stop asks for confirmation first", async () => {
  const requests = trackRequests();
  await renderList([mcpDetailFixture({ id: 1, name: "calc" })]);
  const posted = () => requests.paths().filter((p) => p === "/api/mcps/1/actions/stop");

  await userEvent.click(within(row("calc")).getByRole("button", { name: copy.mcp.stop }));
  const dialog = await screen.findByRole("alertdialog", { name: copy.mcp.stopConfirmTitle("calc") });
  expect(dialog).toHaveAccessibleDescription(copy.mcp.stopConfirm);
  expect(posted()).toHaveLength(0);
  await userEvent.click(within(dialog).getByRole("button", { name: copy.common.cancel }));
  await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
  expect(posted()).toHaveLength(0);
  expect(within(row("calc")).getByRole("button", { name: copy.mcp.stop })).toHaveFocus();

  await userEvent.click(within(row("calc")).getByRole("button", { name: copy.mcp.stop }));
  const again = await screen.findByRole("alertdialog");
  await userEvent.click(within(again).getByRole("button", { name: copy.mcp.stop }));
  expect(await screen.findByText(copy.toasts.pending("calc", "stop"))).toBeInTheDocument();
  expect(posted()).toHaveLength(1);
});

it("409 action_in_progress shows an error toast", async () => {
  await renderList([mcpDetailFixture({ id: 1, name: "calc" })]);
  server.use(http.post("/api/mcps/1/actions/start", () => HttpResponse.json({ error: "action_in_progress" }, { status: 409 })));
  await userEvent.click(within(row("calc")).getByRole("button", { name: copy.mcp.start }));
  expect(await screen.findByText(copy.errors.action_in_progress)).toBeInTheDocument();
  expect(screen.queryByText(copy.toasts.pending("calc", "start"))).not.toBeInTheDocument();
});

it("keeps the toast when the button is gone before the 202 (moved to the detail page)", async () => {
  const { router, store } = await renderList([mcpDetailFixture({ id: 1, name: "calc" })]);
  let release!: () => void;
  const gate = new Promise<void>((r) => (release = r));
  server.use(
    http.post("/api/mcps/1/actions/restart", async () => {
      await gate;
      return HttpResponse.json({ run_id: "r9" }, { status: 202 });
    }),
  );
  await userEvent.click(within(row("calc")).getByRole("button", { name: copy.mcp.restart }));
  await act(() => router.navigate({ to: "/admin/mcps/$mcpId", params: { mcpId: "1" } }));
  await waitFor(() => expect(screen.queryByRole("table", { name: copy.mcp.listLabel })).toBeNull()); // the row unmounted
  release();
  expect(await screen.findByText(copy.toasts.pending("calc", "restart"))).toBeInTheDocument();
  act(() => store.apply(actionEvent({ kind: "start", requested: "restart" })));
  expect(await screen.findByText(copy.toasts.ok("calc", "restart"))).toBeInTheDocument();
});

it("keeps the error toast when the button is gone before the answer", async () => {
  const { router } = await renderList([mcpDetailFixture({ id: 1, name: "calc" })]);
  let release!: () => void;
  const gate = new Promise<void>((r) => (release = r));
  server.use(
    http.post("/api/mcps/1/actions/start", async () => {
      await gate;
      return HttpResponse.json({ error: "action_in_progress" }, { status: 409 });
    }),
  );
  await userEvent.click(within(row("calc")).getByRole("button", { name: copy.mcp.start }));
  await act(() => router.navigate({ to: "/admin" }));
  release();
  expect(await screen.findByText(copy.errors.action_in_progress)).toBeInTheDocument();
});

it("marks the button busy while the request is in flight", async () => {
  await renderList([mcpDetailFixture({ id: 1, name: "calc" })]);
  let release!: () => void;
  const gate = new Promise<void>((r) => (release = r));
  server.use(
    http.post("/api/mcps/1/actions/start", async () => {
      await gate;
      return HttpResponse.json({ run_id: "r9" }, { status: 202 });
    }),
  );
  const button = within(row("calc")).getByRole("button", { name: copy.mcp.start });
  await userEvent.click(button);
  await waitFor(() => expect(button).toHaveAttribute("aria-busy", "true"));
  release();
  await waitFor(() => expect(button).not.toHaveAttribute("aria-busy"));
});

it("action buttons explain why they are disabled while a script runs", async () => {
  const requests = trackRequests();
  await renderList([mcpDetailFixture({ id: 1, name: "calc", live: { ...item(1, "ACTION", "calc"), running: "start" } })]);
  for (const name of [copy.mcp.start, copy.mcp.restart, copy.mcp.stop]) {
    const button = within(row("calc")).getByRole("button", { name });
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).toHaveAccessibleDescription(copy.deny.running);
    await userEvent.click(button);
  }
  expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  expect(requests.paths().filter((p) => p.includes("/actions/"))).toHaveLength(0);
});

it("explains a config error instead of running scripts", async () => {
  await renderList([mcpDetailFixture({ id: 1, name: "calc", config_error: true, live: null })]);
  const button = within(row("calc")).getByRole("button", { name: copy.mcp.start });
  expect(button).toHaveAccessibleDescription(copy.deny.config_error);
  expect(within(row("calc")).getByText(copy.mcp.configErrorBadge)).toBeInTheDocument();
});

it("create button is disabled with the local-only reason on external", async () => {
  await renderList([mcpDetailFixture({ id: 1, name: "calc" })], { me: meFixture("developer", "external") });
  const create = screen.getByRole("button", { name: copy.mcp.create });
  expect(create).toHaveAttribute("aria-disabled", "true");
  expect(create).toHaveAccessibleDescription(copy.deny.local_only);
  expect(screen.queryByRole("link", { name: copy.mcp.create })).not.toBeInTheDocument();
  // a remote developer may still run scripts
  expect(within(row("calc")).getByRole("button", { name: copy.mcp.start })).not.toHaveAttribute("aria-disabled");
});

it("create links to the registration page on the local channel", async () => {
  await renderList([], { me: meFixture("developer", "local") });
  expect(screen.getByRole("link", { name: copy.mcp.create })).toHaveAttribute("href", "/admin/mcps/new");
  expect(await screen.findByText(copy.mcp.listEmpty)).toBeInTheDocument();
});

it("live mcp events update the list without refetching", async () => {
  const requests = trackRequests();
  const { store } = await renderList([mcpDetailFixture({ id: 1, name: "calc" }), mcpDetailFixture({ id: 2, name: "files" })]);
  expect(within(row("calc")).getByText(copy.states.HEALTHY)).toBeInTheDocument();
  act(() => store.apply({ event: "mcp", data: JSON.stringify({ ...item(1, "FAILED", "calc"), latency_ms: null }) }));
  expect(await within(row("calc")).findByText(copy.states.FAILED)).toBeInTheDocument();
  expect(rowNames()).toEqual(["calc", "files"]);
  act(() => store.apply({ event: "mcp", data: JSON.stringify(item(2, "FAILED", "files")) }));
  await waitFor(() => expect(within(row("files")).getByText(copy.states.FAILED)).toBeInTheDocument());
  expect(requests.paths().filter((p) => p === "/api/mcps")).toHaveLength(1);
});

it("does not move rows under the pointer when a state changes, and re-sorts once it leaves", async () => {
  const { store } = await renderList([mcpDetailFixture({ id: 1, name: "calc" }), mcpDetailFixture({ id: 2, name: "files" })]);
  const body = screen.getAllByRole("rowgroup")[1];
  if (!body) throw new Error("no table body");
  await userEvent.hover(body);
  act(() => store.apply({ event: "mcp", data: JSON.stringify(item(2, "FAILED", "files")) }));
  await within(row("files")).findByText(copy.states.FAILED);
  expect(rowNames()).toEqual(["calc", "files"]);
  await userEvent.unhover(body);
  await waitFor(() => expect(rowNames()).toEqual(["files", "calc"]));
});

it("does not move rows while keyboard focus is in them, and re-sorts once focus leaves", async () => {
  const { store } = await renderList([mcpDetailFixture({ id: 1, name: "calc" }), mcpDetailFixture({ id: 2, name: "files" })]);
  act(() => within(row("calc")).getByRole("button", { name: copy.mcp.start }).focus());
  act(() => store.apply({ event: "mcp", data: JSON.stringify(item(2, "FAILED", "files")) }));
  await within(row("files")).findByText(copy.states.FAILED);
  expect(rowNames()).toEqual(["calc", "files"]);
  // moving focus from row to row keeps the order too
  const filesStart = within(row("files")).getByRole("button", { name: copy.mcp.start });
  act(() => filesStart.focus());
  expect(rowNames()).toEqual(["calc", "files"]);
  act(() => filesStart.blur());
  await waitFor(() => expect(rowNames()).toEqual(["files", "calc"]));
});

it("lets rows move again when the focused row is removed (no blur arrives)", async () => {
  const { store } = await renderList([
    mcpDetailFixture({ id: 1, name: "calc" }),
    mcpDetailFixture({ id: 2, name: "files" }),
    mcpDetailFixture({ id: 3, name: "zeta" }),
  ]);
  act(() => {
    for (const [id, name] of [[1, "calc"], [2, "files"], [3, "zeta"]] as const) {
      store.apply({ event: "mcp", data: JSON.stringify(item(id, "HEALTHY", name)) });
    }
  });
  act(() => within(row("calc")).getByRole("button", { name: copy.mcp.start }).focus());
  act(() => store.apply({ event: "mcp_removed", data: JSON.stringify({ id: 1 }) }));
  await waitFor(() => expect(rowNames()).toEqual(["files", "zeta"]));
  act(() => store.apply({ event: "mcp", data: JSON.stringify(item(3, "FAILED", "zeta")) }));
  await within(row("zeta")).findByText(copy.states.FAILED);
  await waitFor(() => expect(rowNames()).toEqual(["zeta", "files"]));
});

it("shows every column of a row", async () => {
  await renderList([
    mcpDetailFixture({ id: 1, name: "calc", owner: null, live: { ...item(1, "HEALTHY", "calc"), latency_ms: 42, uptime_24h: 0.9876 } }),
  ]);
  const r = within(row("calc"));
  expect(r.getByRole("link", { name: "calc" })).toHaveAttribute("href", "/admin/mcps/1");
  expect(r.getByText("127.0.0.1:9001")).toBeInTheDocument();
  expect(r.getByText("42")).toBeInTheDocument();
  expect(r.getByText("98.8%")).toBeInTheDocument();
  expect(r.getByText(copy.mcp.noOwner)).toBeInTheDocument();
  const headers = screen.getAllByRole("columnheader").map((h) => h.textContent);
  expect(headers).toEqual(Object.values(copy.mcp.columns));
});

it("sorts by severity, then name, and by a clicked column", async () => {
  await renderList([
    mcpDetailFixture({ id: 1, name: "b-ok", live: { ...item(1, "HEALTHY", "b-ok"), latency_ms: 5 } }),
    mcpDetailFixture({ id: 2, name: "a-ok", live: { ...item(2, "HEALTHY", "a-ok"), latency_ms: 50 } }),
    mcpDetailFixture({ id: 3, name: "z-fail", live: item(3, "FAILED", "z-fail") }),
    mcpDetailFixture({ id: 4, name: "m-suspect", live: item(4, "SUSPECT", "m-suspect") }),
    mcpDetailFixture({ id: 5, name: "broken", config_error: true, live: null }),
  ]);
  expect(rowNames()).toEqual(["broken", "z-fail", "m-suspect", "a-ok", "b-ok"]);
  const stateHeader = screen.getByRole("columnheader", { name: copy.mcp.columns.state });
  expect(stateHeader).toHaveAttribute("aria-sort", "ascending");

  await userEvent.click(screen.getByRole("button", { name: copy.mcp.columns.name }));
  expect(rowNames()).toEqual(["a-ok", "b-ok", "broken", "m-suspect", "z-fail"]);
  expect(screen.getByRole("columnheader", { name: copy.mcp.columns.name })).toHaveAttribute("aria-sort", "ascending");
  expect(stateHeader).toHaveAttribute("aria-sort", "none");

  await userEvent.click(screen.getByRole("button", { name: copy.mcp.columns.latency }));
  // no latency (null) stays last whichever way
  expect(rowNames().slice(0, 2)).toEqual(["b-ok", "a-ok"]);
  await userEvent.click(screen.getByRole("button", { name: copy.mcp.columns.latency }));
  expect(rowNames().slice(0, 2)).toEqual(["a-ok", "b-ok"]);
  expect(screen.getByRole("columnheader", { name: copy.mcp.columns.latency })).toHaveAttribute("aria-sort", "descending");
});

it("filters by state from the URL and offers the state chips with counts", async () => {
  const { router } = await renderList(
    [
      mcpDetailFixture({ id: 1, name: "calc" }),
      mcpDetailFixture({ id: 2, name: "files", live: item(2, "FAILED", "files") }),
    ],
    { route: "/admin/mcps?state=FAILED" },
  );
  expect(rowNames()).toEqual(["files"]);
  const filters = screen.getByRole("navigation", { name: copy.mcp.filterLabel });
  const failed = within(filters).getByRole("link", { name: /실패\s*1/ });
  expect(failed).toHaveAttribute("aria-current", "page");
  const all = within(filters).getByRole("link", { name: /전체\s*2/ });
  expect(all).toHaveAttribute("href", "/admin/mcps");
  expect(all).not.toHaveAttribute("aria-current");

  await userEvent.click(within(filters).getByRole("link", { name: /정상\s*1/ }));
  await waitFor(() => expect(router.state.location.search).toEqual({ state: "HEALTHY" }));
  expect(rowNames()).toEqual(["calc"]);

  await userEvent.click(within(filters).getByRole("link", { name: /점검 중\s*0/ }));
  expect(await screen.findByText(copy.mcp.filterEmpty(copy.states.MAINTENANCE))).toBeInTheDocument();
  await userEvent.click(screen.getByRole("link", { name: copy.mcp.clearFilter }));
  await waitFor(() => expect(rowNames()).toEqual(["files", "calc"]));
});
