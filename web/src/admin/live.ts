// The admin tab's live data: one BoardStore fed by one BoardStreamClient (U5), shared through
// context, and mirrored into the React Query cache so lists and detail pages update from SSE
// without refetching.
import type { QueryClient } from "@tanstack/react-query";
import { createContext, createElement, useContext, useSyncExternalStore, type ReactNode } from "react";
import type { BoardItem, McpDetail } from "@/lib/api-types";
import type { BoardState, BoardStore } from "@/lib/board-store";
import type { BoardStreamClient, StreamStatus } from "@/lib/board-stream";
import { qk } from "./query-keys";

export interface LiveValue {
  store: BoardStore;
  stream: BoardStreamClient;
  /** Manual-action toasts (Task 10 creates the ActionTracker in AppShell); null until then. */
  tracker: null;
}

const LiveContext = createContext<LiveValue | null>(null);

export function LiveProvider({ value, children }: { value: LiveValue; children: ReactNode }) {
  return createElement(LiveContext.Provider, { value }, children);
}

export function useLive(): LiveValue {
  const live = useContext(LiveContext);
  if (!live) throw new Error("useLive() outside <LiveProvider>");
  return live;
}

/** Only the stream status: a page that shows the indicator does not re-render on every event. */
export function useStreamStatus(store: BoardStore): StreamStatus {
  return useSyncExternalStore(store.subscribe, () => store.getSnapshot().status);
}

function withLive(detail: McpDetail, live: BoardItem | null): McpDetail {
  return detail.live === live ? detail : { ...detail, live };
}

/**
 * Mirrors BoardStore changes into the query cache. The store replaces only the items an event
 * touched (same object otherwise), so diffing two snapshots tells `mcp` (one item), `board`
 * (all items) and `mcp_removed` apart without hooking into the parser:
 * - changed item → its `live` in `qk.mcps` and `qk.mcp(id)`; an id the list does not know → refetch the list;
 * - removed id → dropped from the list, `qk.mcp(id)` invalidated;
 * - `action` event → that MCP's history windows and the activity feed are refetched.
 * Returns the unsubscribe function.
 */
export function connectLive(store: BoardStore, qc: QueryClient): () => void {
  let prev: BoardState = store.getSnapshot();

  const offState = store.subscribe(() => {
    const next = store.getSnapshot();
    if (next.items === prev.items) {
      prev = next;
      return; // status or sessions only
    }
    const changed = new Map<number, BoardItem>();
    for (const [id, item] of next.items) if (prev.items.get(id) !== item) changed.set(id, item);
    const removed = [...prev.items.keys()].filter((id) => !next.items.has(id));
    prev = next;

    const list = qc.getQueryData<McpDetail[]>(qk.mcps);
    if (list) {
      const known = new Set(list.map((m) => m.id));
      const gone = new Set(removed);
      qc.setQueryData<McpDetail[]>(
        qk.mcps,
        list.filter((m) => !gone.has(m.id)).map((m) => (changed.has(m.id) ? withLive(m, changed.get(m.id) ?? null) : m)),
      );
      if ([...changed.keys()].some((id) => !known.has(id))) void qc.invalidateQueries({ queryKey: qk.mcps, exact: true });
    }
    for (const [id, item] of changed) {
      qc.setQueryData<McpDetail>(qk.mcp(id), (d) => (d ? withLive(d, item) : d));
    }
    for (const id of removed) void qc.invalidateQueries({ queryKey: qk.mcp(id), exact: true });
  });

  const offAction = store.onAction((e) => {
    void qc.invalidateQueries({ queryKey: qk.histories(e.mcp_id) });
    void qc.invalidateQueries({ queryKey: qk.activity });
  });

  return () => {
    offState();
    offAction();
  };
}
