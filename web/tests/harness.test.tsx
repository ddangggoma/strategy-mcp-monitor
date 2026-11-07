// The shared test harness itself: MSW defaults, request tracking, the SSE handler and the
// provider wrapper that later tasks build on.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { screen, waitFor } from "@testing-library/react";
import { api } from "@/lib/api";
import { BoardStore } from "@/lib/board-store";
import { BoardStreamClient } from "@/lib/board-stream";
import * as endpoints from "@/lib/endpoints";
import { session, useSession } from "@/lib/session";
import {
  boardFixture, histogramFixture, logItem, logPage, logStatusFixture, meFixture, previewFixture, serviceStatusFixture, userCounts,
} from "./msw/fixtures";
import { trackRequests } from "./msw/server";
import { renderWithProviders } from "./render";

it("default handlers answer with typed fixtures", async () => {
  await expect(endpoints.me()).resolves.toEqual(meFixture(null, "local"));
  await expect(endpoints.board()).resolves.toEqual(boardFixture());
  const detail = await endpoints.mcp(3);
  expect(detail.id).toBe(3);
  await expect(endpoints.updateMcp(3, { maintenance: true })).resolves.toMatchObject({ id: 3, maintenance: true });
  await expect(endpoints.manualAction(3, "start")).resolves.toEqual({ run_id: expect.any(String) });
});

it("default log, audit and service handlers answer with typed fixtures", async () => {
  const q = { from: "2026-11-04T13:00:00.000+09:00", to: "2026-11-04T14:00:00.000+09:00" };
  await expect(endpoints.logs(q)).resolves.toEqual(logPage([logItem()]));
  await expect(endpoints.audit({ ...q, kind: "admin" })).resolves.toEqual(logPage([logItem({ cat: "admin.audit", event: "user_create" })]));
  await expect(endpoints.logUsers(q)).resolves.toEqual(userCounts());
  await expect(endpoints.logStatus()).resolves.toEqual(logStatusFixture());
  await expect(endpoints.serviceStatus()).resolves.toEqual(serviceStatusFixture());
  const h = await endpoints.logHistogram(q, { buckets: 10, group: "cat" });
  expect(h).toEqual(histogramFixture());
  expect(h.starts).toHaveLength(6);
  expect(h.starts[1]).toBe("2026-11-04T13:10:00.000+09:00");
  expect(h.series.flatMap((s) => s.counts).reduce((a, b) => a + b, 0)).toBe(h.total);
  expect(previewFixture().delete_events).toBe(0);
});

it("jsdom gets pointer events with a pointer id and a ResizeObserver", () => {
  const seen: number[] = [];
  const el = document.createElement("div");
  el.addEventListener("pointerdown", (e) => seen.push(e.pointerId));
  el.dispatchEvent(new PointerEvent("pointerdown", { pointerId: 7, clientX: 5, bubbles: true }));
  expect(seen).toEqual([7]);
  expect(new PointerEvent("pointermove", { clientX: 12 }).clientX).toBe(12);
  expect(new PointerEvent("pointerup")).toBeInstanceOf(MouseEvent);
  const ro = new ResizeObserver(() => {});
  expect(() => { ro.observe(el); ro.disconnect(); }).not.toThrow();
});

it("an unhandled request fails instead of reaching the network", async () => {
  const errors = vi.spyOn(console, "error").mockImplementation(() => {});
  await expect(api("/api/no-such-route")).rejects.toMatchObject({ status: 0, code: "network" });
  expect(errors).toHaveBeenCalled();
  errors.mockRestore();
});

it("trackRequests lists the paths requested during this test only", async () => {
  await endpoints.board();
  const spy = trackRequests();
  await endpoints.mcps();
  await endpoints.mcpHistory(1, 24);
  expect(spy.paths()).toEqual(["/api/mcps", "/api/mcps/1/history"]);
  expect(spy.urls()).toEqual(["/api/mcps", "/api/mcps/1/history?hours=24"]);
});

it("the default /api/stream handler feeds a real BoardStreamClient over fetch", async () => {
  const store = new BoardStore();
  const c = new BoardStreamClient({ onEvent: (e) => store.apply(e), onStatus: (s) => store.setStatus(s) });
  c.start();
  await waitFor(() => expect(store.getSnapshot().status).toBe("open"));
  await waitFor(() => expect(store.getSnapshot().items.size).toBe(boardFixture().mcps.length));
  c.stop();
  expect(store.getSnapshot().status).toBe("stopped");
});

function Probe() {
  const me = useSession();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["board"], queryFn: endpoints.board });
  return (
    <p>
      {me?.user?.role ?? "anon"}:{me?.channel}:{q.data ? q.data.mcps.length : "…"}:{qc ? "qc" : ""}
    </p>
  );
}

it("renderWithProviders sets the session and wraps a fresh QueryClient", async () => {
  const { qc } = renderWithProviders(<Probe />, { me: meFixture("admin", "external") });
  expect(session.csrf).toBe(meFixture("admin", "external").csrf_token);
  expect(await screen.findByText(`admin:external:${boardFixture().mcps.length}:qc`)).toBeInTheDocument();
  expect(qc.getDefaultOptions().queries?.retry).toBe(false);
});
