import { act, renderHook } from "@testing-library/react";
import { item, rdpSession } from "../../tests/msw/fixtures";
import type { ActionEvent } from "./api-types";
import { BoardStore, STATE_SEVERITY, sortBoard, useBoard } from "./board-store";

it("applies board, mcp, mcp_removed and sessions events", () => {
  const s = new BoardStore();
  s.apply({ event: "board", data: JSON.stringify({ now: "t", mcps: [item(1, "HEALTHY"), item(2, "FAILED")] }) });
  expect(s.getSnapshot().sessions).toBeUndefined();
  expect(s.getSnapshot().now).toBe("t");
  s.apply({ event: "mcp", data: JSON.stringify(item(1, "SUSPECT")) });
  s.apply({ event: "mcp_removed", data: '{"id":2}' });
  s.apply({ event: "sessions", data: '{"sessions":[]}' });
  const snap = s.getSnapshot();
  expect([...snap.items.values()].map((i) => [i.id, i.state])).toEqual([[1, "SUSPECT"]]);
  expect(snap.sessions).toEqual([]);
  expect([...snap.receivedAt.keys()]).toEqual([1]);
});

it("a board snapshot replaces items, keeps sessions when absent and replaces them when present", () => {
  const s = new BoardStore();
  const sessions = [rdpSession({ user: "hong" })];
  s.apply({ event: "board", data: JSON.stringify({ now: "t1", mcps: [item(1, "HEALTHY"), item(2, "HEALTHY")], sessions }) });
  expect(s.getSnapshot().sessions).toEqual(sessions);
  s.apply({ event: "board", data: JSON.stringify({ now: "t2", mcps: [item(3, "FAILED")] }) });
  expect([...s.getSnapshot().items.keys()]).toEqual([3]);
  expect([...s.getSnapshot().receivedAt.keys()]).toEqual([3]);
  expect(s.getSnapshot().sessions).toEqual(sessions);
  s.apply({ event: "board", data: JSON.stringify({ now: "t3", mcps: [], sessions: [] }) });
  expect(s.getSnapshot().sessions).toEqual([]);
});

it("records performance.now() at receipt per item", () => {
  const now = vi.spyOn(performance, "now").mockReturnValue(1000);
  const s = new BoardStore();
  s.apply({ event: "board", data: JSON.stringify({ now: "t", mcps: [item(1, "HEALTHY"), item(2, "HEALTHY")] }) });
  now.mockReturnValue(2500);
  s.apply({ event: "mcp", data: JSON.stringify(item(2, "SUSPECT")) });
  expect(Object.fromEntries(s.getSnapshot().receivedAt)).toEqual({ 1: 1000, 2: 2500 });
  now.mockRestore();
});

it("updates immutably: a change gives new Maps and leaves the old snapshot intact", () => {
  const s = new BoardStore();
  s.apply({ event: "board", data: JSON.stringify({ now: "t", mcps: [item(1, "HEALTHY")] }) });
  const before = s.getSnapshot();
  s.apply({ event: "mcp", data: JSON.stringify(item(1, "FAILED")) });
  const after = s.getSnapshot();
  expect(after).not.toBe(before);
  expect(after.items).not.toBe(before.items);
  expect(before.items.get(1)?.state).toBe("HEALTHY");
  expect(after.items.get(1)?.state).toBe("FAILED");
});

it("ignores malformed JSON and unknown events without changing the snapshot", () => {
  const s = new BoardStore();
  s.apply({ event: "board", data: JSON.stringify({ now: "t", mcps: [item(1, "HEALTHY")] }) });
  const listener = vi.fn();
  s.subscribe(listener);
  const snap = s.getSnapshot();
  for (const e of [
    { event: "board", data: "{not json" },
    { event: "board", data: '{"now":"t"}' }, // no mcps array
    { event: "mcp", data: '{"name":"no id"}' },
    { event: "mcp", data: "null" },
    { event: "mcp_removed", data: '{"id":99}' }, // unknown id: nothing to remove
    { event: "mcp_removed", data: "[]" },
    { event: "sessions", data: '{"sessions":"nope"}' },
    { event: "sessions", data: "{" },
    { event: "message", data: "{}" },
    { event: "whatever", data: '{"id":1}' },
  ]) {
    s.apply(e);
  }
  expect(s.getSnapshot()).toBe(snap);
  expect(listener).not.toHaveBeenCalled();
});

it("routes action events to listeners", () => {
  const s = new BoardStore();
  const got: ActionEvent[] = [];
  const off = s.onAction((e) => got.push(e));
  const ev: ActionEvent = {
    run_id: "r1", mcp_id: 1, kind: "stop", requested: "restart", trigger: "manual",
    status: "ok", exit_code: 0, duration_ms: 120,
  };
  const snap = s.getSnapshot();
  s.apply({ event: "action", data: JSON.stringify(ev) });
  expect(got).toEqual([ev]);
  expect(s.getSnapshot()).toBe(snap); // an action event is not board state
  s.apply({ event: "action", data: "{broken" });
  expect(got).toHaveLength(1);
  off();
  s.apply({ event: "action", data: JSON.stringify(ev) });
  expect(got).toHaveLength(1);
});

it("fires onReconnected only after reconnecting → open", () => {
  const s = new BoardStore();
  const fn = vi.fn();
  const off = s.onReconnected(fn);
  s.setStatus("connecting");
  s.setStatus("open");
  expect(fn).toHaveBeenCalledTimes(0);
  s.setStatus("reconnecting");
  expect(s.getSnapshot().status).toBe("reconnecting");
  s.setStatus("open");
  expect(fn).toHaveBeenCalledTimes(1);
  s.setStatus("open"); // no change, no second call
  expect(fn).toHaveBeenCalledTimes(1);
  off();
  s.setStatus("reconnecting");
  s.setStatus("open");
  expect(fn).toHaveBeenCalledTimes(1);
});

it("setStatus with the same status keeps the snapshot", () => {
  const s = new BoardStore();
  s.setStatus("open");
  const snap = s.getSnapshot();
  s.setStatus("open");
  expect(s.getSnapshot()).toBe(snap);
});

it("useBoard re-renders on changes only", () => {
  const s = new BoardStore();
  let renders = 0;
  const { result } = renderHook(() => {
    renders++;
    return useBoard(s);
  });
  const first = renders;
  act(() => s.apply({ event: "mcp", data: JSON.stringify(item(1, "HEALTHY")) }));
  expect(result.current.items.get(1)?.state).toBe("HEALTHY");
  const second = renders;
  expect(second).toBeGreaterThan(first);
  act(() => s.apply({ event: "whatever", data: "{}" }));
  act(() => s.setStatus(s.getSnapshot().status));
  expect(renders).toBe(second);
});

it("sorts by severity then name", () => {
  expect(
    sortBoard([item(1, "HEALTHY", "a"), item(2, "FAILED", "z"), item(3, "SUSPECT", "b"), item(4, "FAILED", "c")]).map((i) => i.id),
  ).toEqual([4, 2, 3, 1]);
});

it("orders every state by U17 and does not mutate its input", () => {
  expect(Object.entries(STATE_SEVERITY).sort((a, b) => a[1] - b[1]).map(([k]) => k)).toEqual([
    "FAILED", "ACTION", "SUSPECT", "RECOVERING", "MAINTENANCE", "HEALTHY",
  ]);
  const input = [item(1, "HEALTHY", "b"), item(2, "HEALTHY", "B"), item(3, "HEALTHY", "a")];
  const sorted = sortBoard(input);
  expect(sorted.map((i) => i.id)).toEqual([3, 1, 2]); // case-insensitive name, then id
  expect(input.map((i) => i.id)).toEqual([1, 2, 3]);
  expect(sortBoard(new Map(input.map((i) => [i.id, i])).values()).map((i) => i.id)).toEqual([3, 1, 2]);
});
