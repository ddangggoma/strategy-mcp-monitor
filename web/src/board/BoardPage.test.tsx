import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { copy } from "@/copy/ko";
import type { Me } from "@/lib/api-types";
import { BoardStore } from "@/lib/board-store";
import type { BoardStreamClient } from "@/lib/board-stream";
import { session } from "@/lib/session";
import type { SseEvent } from "@/lib/sse";
import { boardEvent, item, meFixture, rdpSession } from "../../tests/msw/fixtures";
import { server, trackRequests } from "../../tests/msw/server";
import { BoardPage } from "./BoardPage";

function fakeStream() {
  return { restart: vi.fn() };
}

/** New BoardStore with `ev` applied (none: still loading), `session.me` set, BoardPage rendered on a fake stream. */
function renderBoard(ev: SseEvent | null, me: Me | null = meFixture(null, "external")) {
  const store = new BoardStore();
  if (ev) store.apply(ev);
  store.setStatus("open");
  session.me = me;
  session.csrf = me?.csrf_token ?? null;
  const stream = fakeStream();
  render(<BoardPage store={store} stream={stream as unknown as BoardStreamClient} />);
  return Object.assign(store, { stream });
}

const card = (id: number) => {
  const found = screen.getAllByTestId("mcp-card").find((c) => c.dataset.id === String(id));
  if (!found) throw new Error(`no card ${id}`);
  return found;
};

it("shows the not-ready state while the board has no sessions field", () => {
  renderBoard(boardEvent({ mcps: [item(1, "HEALTHY")] }));
  expect(screen.getByText(copy.board.sessionsNotReady)).toBeInTheDocument();
  expect(screen.queryByText(copy.board.connected)).toBeNull();
});

it("shows 접속자 없음 for an empty sessions list", () => {
  renderBoard(boardEvent({ mcps: [], sessions: [] }));
  expect(screen.getByText(copy.board.noSession)).toBeInTheDocument();
});

it("shows 접속 중 and the full client IP for a session", () => {
  renderBoard(boardEvent({ mcps: [], sessions: [rdpSession({ client_ip: "10.0.3.21", user: "hong" })] }));
  expect(screen.getByText(copy.board.connected)).toBeInTheDocument();
  expect(screen.getByText("10.0.3.21")).toBeInTheDocument();
});

it("orders problem MCPs first and updates a card from an mcp event", async () => {
  const store = renderBoard(boardEvent({ mcps: [item(1, "HEALTHY", "a"), item(2, "FAILED", "b")] }));
  expect(screen.getAllByTestId("mcp-card").map((c) => c.dataset.id)).toEqual(["2", "1"]);
  act(() => store.apply({ event: "mcp", data: JSON.stringify(item(1, "MAINTENANCE", "a")) }));
  expect(await within(card(1)).findByText("점검 중")).toBeInTheDocument();
  act(() => store.apply({ event: "mcp", data: JSON.stringify(item(1, "FAILED", "a")) }));
  expect(screen.getAllByTestId("mcp-card").map((c) => c.dataset.id)).toEqual(["1", "2"]);
});

it("never renders host, port or owner", () => {
  // BoardItem has no such fields; inject them into the SSE payload to prove extras are not rendered
  const leaky = { ...item(1, "HEALTHY", "calc"), host: "10.9.8.7", port: 9123, owner: { id: 5, email: "owner@example.com", name: "ownername" } };
  renderBoard({ event: "board", data: JSON.stringify({ now: "2026-11-04T14:03:22.418+09:00", mcps: [leaky] }) });
  const text = card(1).textContent ?? "";
  expect(text).toContain("calc");
  for (const bad of ["10.9.8.7", "9123", "owner@example.com", "ownername"]) expect(document.body.textContent).not.toContain(bad);
});

it("states the verdict: problems, maintenance only, all healthy, no MCP", () => {
  const store = renderBoard(boardEvent({ mcps: [item(1, "HEALTHY"), item(2, "FAILED"), item(3, "SUSPECT")] }));
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(copy.board.problems(2));
  act(() => store.apply(boardEvent({ mcps: [item(1, "HEALTHY"), item(2, "MAINTENANCE")] })));
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(copy.board.maintenanceOnly(1));
  act(() => store.apply(boardEvent({ mcps: [item(1, "HEALTHY")] })));
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(copy.board.allHealthy);
  act(() => store.apply(boardEvent({ mcps: [] })));
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(copy.board.noMcp);
  expect(screen.getByText(copy.board.noMcpHint)).toBeInTheDocument();
  expect(screen.queryByTestId("mcp-card")).toBeNull();
});

it("shows skeletons until the first board event", () => {
  const store = renderBoard(null);
  expect(screen.getByText(copy.common.loading).closest("[role='status']")).not.toBeNull();
  expect(screen.getAllByTestId("card-skeleton").length).toBeGreaterThan(0);
  act(() => store.apply(boardEvent({ mcps: [item(1, "HEALTHY")] })));
  expect(screen.queryByTestId("card-skeleton")).toBeNull();
  expect(screen.getAllByTestId("mcp-card")).toHaveLength(1);
});

it("tells the stream is reconnecting only after 3 s", () => {
  vi.useFakeTimers();
  try {
    const store = renderBoard(boardEvent({ mcps: [] }));
    act(() => store.setStatus("reconnecting"));
    expect(screen.queryByText(copy.stream.reconnecting)).toBeNull();
    act(() => vi.advanceTimersByTime(3000));
    expect(screen.getByText(copy.stream.reconnecting)).toBeInTheDocument();
  } finally {
    vi.useRealTimers();
  }
});

it("shows the bootstrap hint only on local when setup is needed", async () => {
  server.use(http.get("/api/bootstrap", () => HttpResponse.json({ needed: true })));
  renderBoard(boardEvent({ mcps: [] }), meFixture(null, "local"));
  const link = await screen.findByRole("link", { name: copy.board.setupLink });
  expect(link).toHaveAttribute("href", "/admin/setup");
});

it("does not show the bootstrap hint when setup is done", async () => {
  const spy = trackRequests();
  renderBoard(boardEvent({ mcps: [] }), meFixture(null, "local"));
  await waitFor(() => expect(spy.paths()).toContain("/api/bootstrap"));
  // let the answer land, then check nothing appeared
  await act(async () => {});
  expect(screen.queryByRole("link", { name: copy.board.setupLink })).toBeNull();
});

it("never asks for bootstrap on the external channel", async () => {
  const spy = trackRequests();
  renderBoard(boardEvent({ mcps: [] }), meFixture(null, "external"));
  await act(async () => {});
  expect(spy.paths()).not.toContain("/api/bootstrap");
  expect(screen.queryByRole("link", { name: copy.board.setupLink })).toBeNull();
});

it("anonymous visitors get the channel badge and a login link back to the board", () => {
  renderBoard(boardEvent({ mcps: [] }), meFixture(null, "external"));
  expect(screen.getByText(copy.channel.external)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: copy.common.login })).toHaveAttribute("href", "/admin/login?redirect=/");
});

it("the account menu shows who is logged in and links to the admin", async () => {
  renderBoard(boardEvent({ mcps: [] }), meFixture("developer", "local", 4));
  expect(screen.queryByRole("link", { name: copy.common.login })).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: copy.common.accountMenu("user4") }));
  const menu = await screen.findByRole("menu");
  expect(within(menu).getByText("user4@example.com")).toBeInTheDocument();
  expect(within(menu).getByText(copy.roles.developer)).toBeInTheDocument();
  expect(within(menu).getByRole("menuitem", { name: copy.common.adminHome })).toHaveAttribute("href", "/admin");
});

it("logout restarts the stream", async () => {
  const spy = trackRequests();
  const store = renderBoard(boardEvent({ mcps: [] }), meFixture("admin", "local"));
  await userEvent.click(screen.getByRole("button", { name: copy.common.accountMenu("user1") }));
  await userEvent.click(await screen.findByRole("menuitem", { name: copy.common.logout }));
  await waitFor(() => expect(store.stream.restart).toHaveBeenCalledTimes(1));
  expect(spy.paths()).toContain("/api/auth/logout");
  expect(session.me?.user).toBeNull();
  expect(await screen.findByRole("link", { name: copy.common.login })).toBeInTheDocument();
});

it("a failed logout keeps the session and the stream", async () => {
  server.use(http.post("/api/auth/logout", () => HttpResponse.json({ error: "internal" }, { status: 500 })));
  server.use(http.get("/api/auth/me", () => HttpResponse.json(meFixture("admin", "local"))));
  const store = renderBoard(boardEvent({ mcps: [] }), meFixture("admin", "local"));
  await userEvent.click(screen.getByRole("button", { name: copy.common.accountMenu("user1") }));
  await userEvent.click(await screen.findByRole("menuitem", { name: copy.common.logout }));
  await act(async () => {});
  expect(store.stream.restart).not.toHaveBeenCalled();
  expect(session.me?.user?.id).toBe(1);
});

it("the first Tab reaches a skip link to the main content", async () => {
  renderBoard(boardEvent({ mcps: [] }));
  await userEvent.tab();
  const skip = screen.getByRole("link", { name: copy.common.skipToContent });
  expect(skip).toHaveFocus();
  expect(skip).toHaveAttribute("href", "#main");
  expect(screen.getByRole("main")).toHaveAttribute("id", "main");
});
