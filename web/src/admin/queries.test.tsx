import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { logItem, logPage, logStatusFixture, meFixture } from "../../tests/msw/fixtures";
import { server, trackRequests } from "../../tests/msw/server";
import { createTestQueryClient } from "../../tests/render";
import { session } from "@/lib/session";
import type { LogQuery, Me } from "@/lib/api-types";
import {
  useAuditPages, useLogHistogram, useLogPages, useLogStatus, useLogUsers, useMcps, useNotice, useScripts, useServiceStatus,
  useSettings, useUsers,
} from "./queries";

function wrap(me: Me) {
  session.me = me;
  session.csrf = me.csrf_token;
  const qc = createTestQueryClient();
  return ({ children }: { children: ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

function useLocalOnly() {
  return [useScripts(1), useUsers(), useSettings(), useNotice(), useServiceStatus()];
}

const Q: LogQuery = { from: "2026-11-04T13:00:00.000+09:00", to: "2026-11-04T14:00:00.000+09:00" };

function useLogReads() {
  return [useLogPages(Q), useLogHistogram(Q, "cat", 60), useLogUsers(Q), useLogStatus(), useAuditPages({ ...Q, kind: "admin" })];
}

it("never requests Local-only data on the external channel", async () => {
  const seen = trackRequests();
  const { result } = renderHook(() => ({ local: useLocalOnly(), mcps: useMcps() }), { wrapper: wrap(meFixture("admin", "external")) });
  await waitFor(() => expect(result.current.mcps.isSuccess).toBe(true));
  expect(seen.paths()).toEqual(["/api/mcps"]);
  for (const q of result.current.local) expect(q.fetchStatus).toBe("idle");
});

it("requests them for a local admin, and respects the caller's enabled flag", async () => {
  const seen = trackRequests();
  const { result } = renderHook(() => ({ local: useLocalOnly(), off: useMcps({ enabled: false }) }), {
    wrapper: wrap(meFixture("admin", "local")),
  });
  await waitFor(() => expect(result.current.local.every((q) => q.isSuccess)).toBe(true));
  expect(seen.paths().sort()).toEqual(["/api/mcps/1/scripts", "/api/notice", "/api/service", "/api/settings", "/api/users"]);
  expect(result.current.off.fetchStatus).toBe("idle");
});

it("keeps admin-only data from a local developer", async () => {
  const seen = trackRequests();
  const { result } = renderHook(() => useLocalOnly(), { wrapper: wrap(meFixture("developer", "local")) });
  await waitFor(() => expect(result.current[0]?.isSuccess).toBe(true)); // scripts: any local user
  expect(seen.paths()).toEqual(["/api/mcps/1/scripts"]);
});

it("reads logs and audit for a signed-in developer on the external channel", async () => {
  const seen = trackRequests();
  const { result } = renderHook(() => useLogReads(), { wrapper: wrap(meFixture("developer", "external")) });
  await waitFor(() => expect(result.current.every((q) => q.isSuccess)).toBe(true));
  expect(seen.paths().sort()).toEqual(["/api/audit", "/api/logs", "/api/logs/histogram", "/api/logs/status", "/api/logs/users"]);
});

it("reads no logs without a signed-in user, nor when the caller turns them off", async () => {
  const seen = trackRequests();
  const anon = renderHook(() => useLogReads(), { wrapper: wrap(meFixture(null, "local")) });
  const off = renderHook(
    () => [useLogPages(Q, { enabled: false }), useLogStatus({ enabled: false }), useAuditPages(Q, { enabled: false })],
    { wrapper: wrap(meFixture("admin", "local")) },
  );
  await new Promise((r) => setTimeout(r, 50));
  expect(seen.paths()).toEqual([]);
  for (const q of [...anon.result.current, ...off.result.current]) expect(q.fetchStatus).toBe("idle");
});

it("pages logs on with the next cursor and stops at the last page", async () => {
  const cursors: (string | null)[] = [];
  server.use(
    http.get("/api/logs", ({ request }) => {
      const cursor = new URL(request.url).searchParams.get("cursor");
      cursors.push(cursor);
      return HttpResponse.json(cursor === null ? logPage([logItem({ id: 2 })], "c2") : logPage([logItem({ id: 1 })]));
    }),
  );
  const { result } = renderHook(() => useLogPages(Q), { wrapper: wrap(meFixture("developer", "local")) });
  await waitFor(() => expect(result.current.hasNextPage).toBe(true));
  await act(() => result.current.fetchNextPage());
  await waitFor(() => expect(result.current.data?.pages).toHaveLength(2));
  expect(cursors).toEqual([null, "c2"]);
  expect(result.current.hasNextPage).toBe(false);
  expect(result.current.data?.pages.flatMap((p) => p.items.map((i) => i.id))).toEqual([2, 1]);
});

it("re-reads the index status every 5 s until it is ready, then stops", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  try {
    let calls = 0;
    server.use(
      http.get("/api/logs/status", () => {
        calls += 1;
        return HttpResponse.json(logStatusFixture(calls === 1 ? { ready: false, rebuilding: true, pending_files: 3 } : {}));
      }),
    );
    const { result } = renderHook(() => useLogStatus(), { wrapper: wrap(meFixture("developer", "local")) });
    await waitFor(() => expect(result.current.data?.ready).toBe(false));
    expect(calls).toBe(1);
    await act(() => vi.advanceTimersByTimeAsync(5000));
    await waitFor(() => expect(result.current.data?.ready).toBe(true));
    expect(calls).toBe(2);
    await act(() => vi.advanceTimersByTimeAsync(20_000));
    expect(calls).toBe(2);
  } finally {
    vi.useRealTimers();
  }
});
