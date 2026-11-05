import type { McpDetail } from "@/lib/api-types";
import { BoardStore } from "@/lib/board-store";
import { boardEvent, item, mcpDetailFixture } from "../../tests/msw/fixtures";
import { createTestQueryClient } from "../../tests/render";
import { connectLive } from "./live";
import { qk } from "./query-keys";

function setup() {
  const store = new BoardStore();
  const qc = createTestQueryClient();
  const off = connectLive(store, qc);
  qc.setQueryData<McpDetail[]>(qk.mcps, [mcpDetailFixture({ id: 1, name: "calc" }), mcpDetailFixture({ id: 2, name: "weather" })]);
  qc.setQueryData<McpDetail>(qk.mcp(1), mcpDetailFixture({ id: 1, name: "calc" }));
  const invalidate = vi.spyOn(qc, "invalidateQueries");
  return { store, qc, off, invalidate };
}

const mcpEvent = (id: number, state: Parameters<typeof item>[1], name?: string) => ({
  event: "mcp",
  data: JSON.stringify(item(id, state, name)),
});

it("an mcp event updates the live part of the list row and the detail, nothing else", () => {
  const { store, qc, invalidate } = setup();
  const before = qc.getQueryData<McpDetail[]>(qk.mcps);
  store.apply(mcpEvent(1, "FAILED", "calc"));
  const list = qc.getQueryData<McpDetail[]>(qk.mcps);
  expect(list?.[0]?.live?.state).toBe("FAILED");
  expect(list?.[0]?.host).toBe(before?.[0]?.host); // config fields untouched
  expect(list?.[1]).toBe(before?.[1]); // other rows keep their identity
  expect(qc.getQueryData<McpDetail>(qk.mcp(1))?.live?.state).toBe("FAILED");
  expect(invalidate).not.toHaveBeenCalled();
});

it("an unknown id refetches the list", () => {
  const { store, invalidate } = setup();
  store.apply(mcpEvent(9, "HEALTHY", "new"));
  expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.mcps, exact: true });
});

it("mcp_removed drops the row and invalidates its detail", () => {
  const { store, qc, invalidate } = setup();
  store.apply(boardEvent({ mcps: [item(1, "HEALTHY", "calc"), item(2, "HEALTHY", "weather")] }));
  invalidate.mockClear();
  store.apply({ event: "mcp_removed", data: JSON.stringify({ id: 2 }) });
  expect(qc.getQueryData<McpDetail[]>(qk.mcps)?.map((m) => m.id)).toEqual([1]);
  expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.mcp(2), exact: true });
});

it("a board snapshot replaces every row's live part", () => {
  const { store, qc } = setup();
  store.apply(boardEvent({ mcps: [item(1, "SUSPECT", "calc"), item(2, "MAINTENANCE", "weather")] }));
  expect(qc.getQueryData<McpDetail[]>(qk.mcps)?.map((m) => m.live?.state)).toEqual(["SUSPECT", "MAINTENANCE"]);
});

it("an action event refetches that MCP's history windows and the activity feed", async () => {
  const { store, qc } = setup();
  qc.setQueryData(qk.history(1, 24), { buckets: [], transitions: [], actions: [] });
  qc.setQueryData(qk.history(2, 24), { buckets: [], transitions: [], actions: [] });
  qc.setQueryData(qk.activity, { transitions: [], actions: [] });
  store.apply({
    event: "action",
    data: JSON.stringify({ run_id: "r", mcp_id: 1, kind: "start", requested: "start", trigger: "manual", status: "ok", exit_code: 0, duration_ms: 1 }),
  });
  expect(qc.getQueryState(qk.history(1, 24))?.isInvalidated).toBe(true);
  expect(qc.getQueryState(qk.history(2, 24))?.isInvalidated).toBe(false);
  expect(qc.getQueryState(qk.activity)?.isInvalidated).toBe(true);
});

it("status changes do not touch the cache, and unsubscribing stops the mirror", () => {
  const { store, qc, off } = setup();
  const before = qc.getQueryData<McpDetail[]>(qk.mcps);
  store.setStatus("open");
  expect(qc.getQueryData<McpDetail[]>(qk.mcps)).toBe(before);
  off();
  store.apply(mcpEvent(1, "FAILED", "calc"));
  expect(qc.getQueryData<McpDetail[]>(qk.mcps)).toBe(before);
});
