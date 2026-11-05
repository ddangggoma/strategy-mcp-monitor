// One shared 1-second clock for everything on screen that counts (countdowns, elapsed times,
// "3초 전"): a single interval for the whole page instead of one per card, and it runs only
// while something is subscribed. `perf` (performance.now) measures time since an event was
// received, so a countdown never depends on the server and PC clocks agreeing (U8); `wall`
// (Date.now) is for comparing with server timestamps.
import { useSyncExternalStore } from "react";

export interface ClockTick {
  perf: number;
  wall: number;
}

const listeners = new Set<() => void>();
let snapshot: ClockTick | null = null;
let timer: ReturnType<typeof setInterval> | null = null;

function read(): ClockTick {
  return { perf: performance.now(), wall: Date.now() };
}

function tick(): void {
  snapshot = read();
  for (const fn of [...listeners]) fn();
}

function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  if (listeners.size === 1) {
    // first subscriber: start fresh (React re-reads the snapshot after subscribing)
    snapshot = read();
    timer = setInterval(tick, 1000);
  }
  return () => {
    listeners.delete(fn);
    if (listeners.size > 0) return;
    if (timer !== null) clearInterval(timer);
    timer = null;
    snapshot = null; // the next first reader gets the current time, not a stale tick
  };
}

function getSnapshot(): ClockTick {
  snapshot ??= read();
  return snapshot;
}

/** The current time, re-rendering the caller once a second. */
export function useClock(): ClockTick {
  return useSyncExternalStore(subscribe, getSnapshot);
}
