import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { QueryClientProvider } from "@tanstack/react-query";
import { meFixture } from "../../tests/msw/fixtures";
import { trackRequests } from "../../tests/msw/server";
import { createTestQueryClient } from "../../tests/render";
import { session } from "@/lib/session";
import type { Me } from "@/lib/api-types";
import { useMcps, useNotice, useScripts, useSettings, useUsers } from "./queries";

function wrap(me: Me) {
  session.me = me;
  session.csrf = me.csrf_token;
  const qc = createTestQueryClient();
  return ({ children }: { children: ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

function useLocalOnly() {
  return [useScripts(1), useUsers(), useSettings(), useNotice()];
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
  expect(seen.paths().sort()).toEqual(["/api/mcps/1/scripts", "/api/notice", "/api/settings", "/api/users"]);
  expect(result.current.off.fetchStatus).toBe("idle");
});

it("keeps admin-only data from a local developer", async () => {
  const seen = trackRequests();
  const { result } = renderHook(() => useLocalOnly(), { wrapper: wrap(meFixture("developer", "local")) });
  await waitFor(() => expect(result.current[0]?.isSuccess).toBe(true)); // scripts: any local user
  expect(seen.paths()).toEqual(["/api/mcps/1/scripts"]);
});
