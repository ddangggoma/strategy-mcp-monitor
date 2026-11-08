// Board state fed by SSE events. Immutable updates (new Maps per change) so useSyncExternalStore
// re-renders only when something changed; anything unparseable leaves the snapshot as it was.
import { useSyncExternalStore } from "react";
import type { ActionEvent, BoardItem, McpState, RdpSession, SystemStatus, TamperEvent } from "./api-types";
import type { StreamStatus } from "./board-stream";
import type { SseEvent } from "./sse";

export interface BoardState {
  now: string | null;
  items: ReadonlyMap<number, BoardItem>;
  sessions: RdpSession[] | undefined;
  /** This PC's resources; undefined until the first reading arrives. */
  system: SystemStatus | undefined;
  status: StreamStatus;
  receivedAt: ReadonlyMap<number, number> /* performance.now() at item receipt */;
}

/** U17: problems first. Lower sorts earlier. */
export const STATE_SEVERITY: Record<McpState, number> = {
  FAILED: 0,
  ACTION: 1,
  SUSPECT: 2,
  RECOVERING: 3,
  MAINTENANCE: 4,
  HEALTHY: 5,
};

const byName = new Intl.Collator("ko", { sensitivity: "base", numeric: true });

/** Severity, then name (case-insensitive, like the server's order), then id. Does not mutate. */
export function sortBoard(items: Iterable<BoardItem>): BoardItem[] {
  return Array.from(items).sort(
    (a, b) => STATE_SEVERITY[a.state] - STATE_SEVERITY[b.state] || byName.compare(a.name, b.name) || a.id - b.id,
  );
}

function parse(data: string): unknown {
  try {
    return JSON.parse(data);
  } catch {
    return undefined;
  }
}

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function isItem(v: unknown): v is BoardItem {
  return isObject(v) && typeof v.id === "number";
}

function isSystem(v: unknown): v is SystemStatus {
  return isObject(v) && isObject(v.cpu) && isObject(v.memory) && Array.isArray(v.disks) && isObject(v.history);
}

export class BoardStore {
  private state: BoardState = {
    now: null,
    items: new Map(),
    sessions: undefined,
    system: undefined,
    status: "connecting",
    receivedAt: new Map(),
  };
  private readonly listeners = new Set<() => void>();
  private readonly actionListeners = new Set<(e: ActionEvent) => void>();
  private readonly tamperListeners = new Set<(e: TamperEvent) => void>();
  private readonly reconnectedListeners = new Set<() => void>();
  private readonly sessionsChangedListeners = new Set<() => void>();

  // arrow properties: stable references for useSyncExternalStore
  readonly getSnapshot = (): BoardState => this.state;

  readonly subscribe = (fn: () => void): (() => void) => {
    this.listeners.add(fn);
    return () => {
      this.listeners.delete(fn);
    };
  };

  onAction(fn: (e: ActionEvent) => void): () => void {
    this.actionListeners.add(fn);
    return () => {
      this.actionListeners.delete(fn);
    };
  }

  /** SSE `tamper` (authenticated streams only): not board state, handed to listeners as it comes. */
  onTamper(fn: (e: TamperEvent) => void): () => void {
    this.tamperListeners.add(fn);
    return () => {
      this.tamperListeners.delete(fn);
    };
  }

  /**
   * Signed-in streams: the sessions screen's data changed (current sessions incl. disconnected ones,
   * connection history), which the board's own session list does not cover (M16).
   */
  onSessionsChanged(fn: () => void): () => void {
    this.sessionsChangedListeners.add(fn);
    return () => {
      this.sessionsChangedListeners.delete(fn);
    };
  }

  /** Called when the stream opens again after a drop: events may have been missed meanwhile. */
  onReconnected(fn: () => void): () => void {
    this.reconnectedListeners.add(fn);
    return () => {
      this.reconnectedListeners.delete(fn);
    };
  }

  apply(e: SseEvent): void {
    const data = parse(e.data);
    switch (e.event) {
      case "board": {
        if (!isObject(data) || !Array.isArray(data.mcps)) return;
        const at = performance.now();
        const items = new Map<number, BoardItem>();
        const receivedAt = new Map<number, number>();
        for (const it of data.mcps) {
          if (!isItem(it)) continue;
          items.set(it.id, it);
          receivedAt.set(it.id, at);
        }
        const sessions = Array.isArray(data.sessions) ? (data.sessions as RdpSession[]) : this.state.sessions;
        const system = isSystem(data.system) ? data.system : this.state.system;
        this.set({ ...this.state, now: typeof data.now === "string" ? data.now : this.state.now, items, sessions, system, receivedAt });
        return;
      }
      case "system": {
        if (!isSystem(data)) return;
        this.set({ ...this.state, system: data });
        return;
      }
      case "mcp": {
        if (!isItem(data)) return;
        this.set({
          ...this.state,
          items: new Map(this.state.items).set(data.id, data),
          receivedAt: new Map(this.state.receivedAt).set(data.id, performance.now()),
        });
        return;
      }
      case "mcp_removed": {
        if (!isObject(data) || typeof data.id !== "number" || !this.state.items.has(data.id)) return;
        const items = new Map(this.state.items);
        const receivedAt = new Map(this.state.receivedAt);
        items.delete(data.id);
        receivedAt.delete(data.id);
        this.set({ ...this.state, items, receivedAt });
        return;
      }
      case "sessions": {
        if (!isObject(data) || !Array.isArray(data.sessions)) return;
        this.set({ ...this.state, sessions: data.sessions as RdpSession[] });
        return;
      }
      case "action": {
        if (!isObject(data) || typeof data.run_id !== "string") return;
        for (const fn of [...this.actionListeners]) fn(data as unknown as ActionEvent);
        return;
      }
      case "tamper": {
        if (!isObject(data) || typeof data.event !== "string" || typeof data.at !== "string") return;
        for (const fn of [...this.tamperListeners]) fn(data as TamperEvent);
        return;
      }
      case "sessions_changed": {
        for (const fn of [...this.sessionsChangedListeners]) fn();
        return;
      }
      default:
        return; // unknown events are ignored (forward compatible)
    }
  }

  setStatus(s: StreamStatus): void {
    const prev = this.state.status;
    if (s === prev) return;
    this.set({ ...this.state, status: s });
    if (s === "open" && prev === "reconnecting") for (const fn of [...this.reconnectedListeners]) fn();
  }

  private set(next: BoardState): void {
    this.state = next;
    for (const fn of [...this.listeners]) fn();
  }
}

export function useBoard(store: BoardStore): BoardState {
  return useSyncExternalStore(store.subscribe, store.getSnapshot);
}
