import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { copy } from "@/copy/ko";
import type { Me } from "@/lib/api-types";
import {
  boardEvent, collectorFixture, connectionFixture, currentSessionFixture, failureFixture, meFixture, rdpSession,
  sessionsHistoryFixture,
} from "../../../tests/msw/fixtures";
import { server } from "../../../tests/msw/server";
import { renderWithProviders } from "../../../tests/render";
import { warmChunks } from "../../../tests/warm";
import { connectLive } from "../live";

warmChunks("sessions");

/** The sessions page in the admin app; waits for its heading (the lazy chunk compiles once per run). */
async function renderSessions(me: Me = meFixture("developer", "local"), route = "/admin/sessions") {
  const r = renderWithProviders(null, { route, me });
  await screen.findByRole("heading", { level: 1, name: copy.sessions.title }, { timeout: 5000 });
  return r;
}

const region = (name: string) => screen.getByRole("region", { name });

it("lists current sessions including disconnected ones", async () => {
  server.use(http.get("/api/sessions/current", () => HttpResponse.json({ ready: true, sessions: [
    currentSessionFixture({ session_id: 2, state: "active" }), currentSessionFixture({ session_id: 3, user: "kim", state: "disconnected" })] })));
  await renderSessions(meFixture("developer", "external"));
  expect(await screen.findByText(copy.sessions.state.disconnected)).toBeInTheDocument();
});

it("shows history with kinds, first-seen badges and notice status", async () => {
  server.use(http.get("/api/sessions/history", () => HttpResponse.json(sessionsHistoryFixture({ connections: [
    connectionFixture({ id: 9, kind: "reconnect", first_seen_ip: true, notice: { version: 0, attempts: 1, first_shown_at: "2026-11-04T14:00:00.000+09:00",
      acknowledged_at: "2026-11-04T14:00:02.000+09:00", ack_ms: 2000, closed_reason: "acknowledged" } }),
    connectionFixture({ id: 8, kind: "logon", notice: { version: 0, attempts: 2, first_shown_at: null, acknowledged_at: null, ack_ms: null, closed_reason: "superseded" } })] }))));
  await renderSessions();
  const rows = await screen.findAllByTestId("connection-row");
  expect(within(rows[0]!).getByText(copy.sessions.kinds.reconnect)).toBeInTheDocument();
  expect(within(rows[0]!).getByText(copy.sessions.firstSeenIp)).toBeInTheDocument();
  expect(within(rows[0]!).getByText(copy.sessions.ackIn(2000))).toBeInTheDocument();
  expect(within(rows[1]!).getByText(copy.sessions.unacked)).toBeInTheDocument();
});

it("loads more with before_id", async () => {
  const seen: (string | null)[] = [];
  server.use(http.get("/api/sessions/history", ({ request }) => {
    const before = new URL(request.url).searchParams.get("before_id"); seen.push(before);
    return HttpResponse.json(before ? sessionsHistoryFixture({ connections: [connectionFixture({ id: 1 })], next_before_id: null })
                                    : sessionsHistoryFixture({ connections: [connectionFixture({ id: 5 })], next_before_id: 5 }));
  }));
  await renderSessions();
  await userEvent.click(await screen.findByRole("button", { name: copy.sessions.more }));
  expect(await screen.findAllByTestId("connection-row")).toHaveLength(2);
  expect(seen).toEqual([null, "5"]);
  expect(screen.queryByRole("button", { name: copy.sessions.more })).toBeNull();
  // the button went away under the keyboard: focus lands on the table it extended
  await waitFor(() => expect(screen.getAllByTestId("connection-row")[0]!.closest("[data-slot=table-container]")).toHaveFocus());
});

it("shows logon failures and collector problems", async () => {
  server.use(
    http.get("/api/sessions/history", () => HttpResponse.json(sessionsHistoryFixture({ failures: [failureFixture({ client_ip: "203.0.113.9", status: "0xc000006d" })] }))),
    http.get("/api/sessions/collectors", () => HttpResponse.json([collectorFixture({ name: "eventlog:security", ok: false, error: "access denied" })])));
  await renderSessions();
  expect(await screen.findByText("203.0.113.9")).toBeInTheDocument();
  expect(await screen.findByText(copy.sessions.collectorDown("access denied"))).toBeInTheDocument();
});

it("changes the period through the URL", async () => {
  const days: (string | null)[] = [];
  server.use(http.get("/api/sessions/history", ({ request }) => {
    days.push(new URL(request.url).searchParams.get("days")); return HttpResponse.json(sessionsHistoryFixture());
  }));
  const { router } = await renderSessions();
  await userEvent.click(await screen.findByRole("button", { name: copy.sessions.days(30) }));
  expect(router.state.location.search).toEqual({ days: 30 });
  await vi.waitFor(() => expect(days).toContain("30"));
  expect(days[0]).toBe("7");
  expect(screen.getByRole("button", { name: copy.sessions.days(30) })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("button", { name: copy.sessions.days(7) })).toHaveAttribute("aria-pressed", "false");
});

// ---- beyond the plan's sketches ----------------------------------------------------------

it("starts from the period in the URL and ignores values outside the list", async () => {
  const days: (string | null)[] = [];
  server.use(http.get("/api/sessions/history", ({ request }) => {
    days.push(new URL(request.url).searchParams.get("days")); return HttpResponse.json(sessionsHistoryFixture());
  }));
  const { unmount } = await renderSessions(meFixture("developer", "local"), "/admin/sessions?days=90");
  await vi.waitFor(() => expect(days).toEqual(["90"]));
  expect(screen.getByRole("button", { name: copy.sessions.days(90) })).toHaveAttribute("aria-pressed", "true");
  unmount();
  days.length = 0;
  await renderSessions(meFixture("developer", "local"), "/admin/sessions?days=5");
  await vi.waitFor(() => expect(days).toEqual(["7"]));
});

it("uses the live board card for a board session and a status line for the others", async () => {
  server.use(http.get("/api/sessions/current", () => HttpResponse.json({ ready: true, sessions: [
    currentSessionFixture({ session_id: 2, user: "hong", state: "active" }),
    currentSessionFixture({ session_id: 3, user: "kim", domain: null, client_name: "KIM-PC", client_ip: "10.0.3.40", state: "disconnected",
      disconnected_at: "2026-11-04T13:00:00.000+09:00" })] })));
  const { store } = await renderSessions();
  act(() => store.apply(boardEvent({ sessions: [rdpSession({ session_id: 2, user: "hong", notice_acknowledged: false })] })));
  const current = region(copy.sessions.current);
  // the board's own card: every §6.2 field, the pending notice included
  const card = await within(current).findByRole("article", { name: "hong" });
  expect(within(card).getByText(copy.sessions.noticePending)).toBeInTheDocument();
  // the disconnected one: one line, no domain prefix, the time it went away
  const line = within(current).getByTestId("session-line");
  expect(within(line).getByText("kim")).toBeInTheDocument();
  expect(within(line).getByText(copy.sessions.state.disconnected)).toBeInTheDocument();
  expect(within(line).getByText(copy.sessions.disconnectedAt)).toBeInTheDocument();
  expect(within(line).getByText("2026-11-04 13:00:00")).toBeInTheDocument();
  expect(within(line).getByText("10.0.3.40")).toBeInTheDocument();
  expect(within(current).getAllByRole("article")).toHaveLength(1);
});

it("says when sessions are not collected yet or nobody is connected", async () => {
  server.use(http.get("/api/sessions/current", () => HttpResponse.json({ ready: false, sessions: [] })));
  const { unmount } = await renderSessions();
  expect(await within(region(copy.sessions.current)).findByText(copy.board.sessionsNotReady)).toBeInTheDocument();
  unmount();
  server.use(http.get("/api/sessions/current", () => HttpResponse.json({ ready: true, sessions: [] })));
  await renderSessions();
  expect(await within(region(copy.sessions.current)).findByText(copy.sessions.currentEmpty)).toBeInTheDocument();
});

it("refetches current sessions when the board's sessions change", async () => {
  let calls = 0;
  server.use(http.get("/api/sessions/current", () => {
    calls++;
    return HttpResponse.json({ ready: true, sessions: calls === 1 ? [] : [currentSessionFixture({ user: "park", state: "connected" })] });
  }));
  const r = await renderSessions();
  connectLive(r.store, r.qc);
  await within(region(copy.sessions.current)).findByText(copy.sessions.currentEmpty);
  act(() => r.store.apply({ event: "sessions", data: JSON.stringify({ sessions: [] }) }));
  expect(await within(region(copy.sessions.current)).findByText(copy.sessions.state.connected)).toBeInTheDocument();
  expect(calls).toBe(2);
});

it("drops a disconnected session that logs off and updates the history live (sessions_changed, M16)", async () => {
  let phase = 0;
  server.use(
    http.get("/api/sessions/current", () =>
      HttpResponse.json({ ready: true, sessions: phase === 0 ? [currentSessionFixture({ user: "kim", state: "disconnected" })] : [] })),
    http.get("/api/sessions/history", () =>
      HttpResponse.json(sessionsHistoryFixture({ connections: phase === 0 ? [] : [connectionFixture({ user: "kim", end_reason: "logoff", ended_at: "2026-11-04T14:00:00.000+09:00" })] }))),
  );
  const r = await renderSessions();
  connectLive(r.store, r.qc);
  await within(region(copy.sessions.current)).findByText(copy.sessions.state.disconnected);
  phase = 1;
  // the board's own session list does not change: only the sessions screen's signal arrives
  act(() => r.store.apply({ event: "sessions_changed", data: "{}" }));
  expect(await within(region(copy.sessions.current)).findByText(copy.sessions.currentEmpty)).toBeInTheDocument();
  expect(await within(region(copy.sessions.history)).findByText(copy.sessions.endReasons.logoff)).toBeInTheDocument();
});

it("shows every column of a finished connection", async () => {
  server.use(http.get("/api/sessions/history", () => HttpResponse.json(sessionsHistoryFixture({ connections: [
    connectionFixture({ id: 3, user: "hong", domain: "CORP", client_name: "HONG-PC", client_ip: "10.0.3.21", reverse_dns: "hong.corp.example",
      connected_at: "2026-11-04T09:00:00.000+09:00", ended_at: "2026-11-04T10:30:00.000+09:00", end_reason: "logoff",
      first_seen_device: true, notice: null }),
    connectionFixture({ id: 2, domain: null, user: "kim", client_ip: null, ended_at: null, end_reason: null,
      notice: { version: 1, attempts: 1, first_shown_at: "2026-11-04T08:00:00.000+09:00", acknowledged_at: null, ack_ms: null, closed_reason: null } }),
  ] }))));
  await renderSessions();
  const [done, open] = (await screen.findAllByTestId("connection-row")) as [HTMLElement, HTMLElement];
  expect(within(done).getByRole("rowheader", { name: "2026-11-04 09:00:00" })).toBeInTheDocument();
  expect(within(done).getByText("CORP\\hong")).toBeInTheDocument();
  expect(within(done).getByText("HONG-PC")).toBeInTheDocument();
  expect(within(done).getByText(copy.sessions.firstSeenDevice)).toBeInTheDocument();
  expect(within(done).queryByText(copy.sessions.firstSeenIp)).toBeNull();
  expect(within(done).getByText("hong.corp.example")).toBeInTheDocument();
  expect(within(done).getByText(copy.sessions.kinds.logon)).toBeInTheDocument();
  expect(within(done).getByText("2026-11-04 10:30:00")).toBeInTheDocument();
  expect(within(done).getByText(copy.sessions.endReasons.logoff)).toBeInTheDocument();
  expect(within(done).getAllByText("—").length).toBeGreaterThanOrEqual(1); // no notice for this connection
  expect(within(open).getByText("kim")).toBeInTheDocument();
  expect(within(open).getByText(copy.sessions.ongoing)).toBeInTheDocument();
  expect(within(open).getByText(copy.sessions.unacked)).toBeInTheDocument(); // still open: not acknowledged
  // a wide table in a narrow window scrolls in its own frame: a keyboard can reach that frame
  const frame = done.closest("[data-slot=table-container]");
  expect(frame).toHaveAttribute("tabindex", "0");
  expect(frame).toHaveAccessibleName(copy.sessions.history);
});

it("says when the period has no connections or failures", async () => {
  server.use(http.get("/api/sessions/history", () => HttpResponse.json(sessionsHistoryFixture({ connections: [], failures: [] }))));
  await renderSessions();
  expect(await within(region(copy.sessions.history)).findByText(copy.sessions.empty)).toBeInTheDocument();
  expect(within(region(copy.sessions.failures)).getByText(copy.sessions.failuresEmpty)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: copy.sessions.more })).toBeNull();
});

it("shows a failure row in full and a healthy collector", async () => {
  server.use(
    http.get("/api/sessions/history", () => HttpResponse.json(sessionsHistoryFixture({ failures: [failureFixture({
      at: "2026-11-04T12:00:00.000+09:00", user: "admin", domain: "CORP", client_ip: "198.51.100.7", workstation: "EVIL-PC", logon_type: 10,
      status: "0xc000006d", sub_status: "0xc000006a" })] }))),
    http.get("/api/sessions/collectors", () => HttpResponse.json([collectorFixture({ name: "wts", ok: true, error: null })])));
  await renderSessions();
  const failures = region(copy.sessions.failures);
  const row = (await within(failures).findByText("198.51.100.7")).closest("tr")!;
  expect(within(row).getByText("2026-11-04 12:00:00")).toBeInTheDocument();
  expect(within(row).getByText("CORP\\admin")).toBeInTheDocument();
  expect(within(row).getByText("EVIL-PC")).toBeInTheDocument();
  expect(within(row).getByText(copy.sessions.logonType(10))).toBeInTheDocument();
  expect(within(row).getByText("0xc000006d")).toBeInTheDocument();
  expect(within(row).getByText("0xc000006a")).toBeInTheDocument();
  const collectors = region(copy.sessions.collectors);
  expect(await within(collectors).findByText("wts")).toBeInTheDocument();
  expect(within(collectors).getByText(copy.sessions.collectorOk)).toBeInTheDocument();
});

it("shows an error instead of empty sections when a read fails", async () => {
  server.use(
    http.get("/api/sessions/history", () => HttpResponse.json({ error: "internal" }, { status: 500 })),
    http.get("/api/sessions/current", () => HttpResponse.json({ error: "internal" }, { status: 500 })));
  await renderSessions();
  // current, history and the failures that come with the history read
  await waitFor(() => expect(screen.getAllByRole("alert")).toHaveLength(3));
  expect(within(region(copy.sessions.failures)).getByRole("alert")).toHaveTextContent(copy.sessions.loadError);
  expect(screen.queryByText(copy.sessions.empty)).toBeNull();
  expect(screen.queryByText(copy.sessions.failuresEmpty)).toBeNull();
});

it("keeps the more button and says so when the next page fails", async () => {
  server.use(http.get("/api/sessions/history", ({ request }) =>
    new URL(request.url).searchParams.get("before_id")
      ? HttpResponse.json({ error: "internal" }, { status: 500 })
      : HttpResponse.json(sessionsHistoryFixture({ connections: [connectionFixture({ id: 5 })], next_before_id: 5 }))));
  await renderSessions();
  await userEvent.click(await screen.findByRole("button", { name: copy.sessions.more }));
  expect(await screen.findByText(copy.sessions.moreError)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: copy.sessions.more })).toBeInTheDocument();
  expect(screen.getAllByTestId("connection-row")).toHaveLength(1);
});
