import { useEffect, useEffectEvent, useLayoutEffect, useRef } from "react";
import { copy } from "@/copy/ko";
import { useClock } from "@/lib/clock";
import "./ResendRing.css";

export interface ResendRingProps {
  /** Length of the wait (60 after a code is sent; a short Retry-After otherwise). */
  seconds: number;
  /** performance.now() when the wait began. */
  startedAt: number;
  onDone(): void;
  /** Id of the countdown text, for the resend button's aria-describedby. */
  id?: string;
}

function secondsLeft(seconds: number, startedAt: number, now: number): number {
  return Math.max(0, seconds - Math.max(0, now - startedAt) / 1000);
}

/**
 * Wait before "코드 다시 받기": a 24px ring that empties (U25's one exception: `@property
 * --progress` + conic-gradient, one CSS animation, no per-frame JS) and the seconds left as text.
 * The text ticks on the shared 1 s clock and is not announced (role=timer, aria-live=off).
 */
export function ResendRing({ seconds, startedAt, onDone, id }: ResendRingProps) {
  const { perf } = useClock();
  const left = Math.ceil(secondsLeft(seconds, startedAt, perf));
  const ring = useRef<HTMLSpanElement>(null);

  // before paint: start ratio and length from the time of mount, outside React's render
  useLayoutEffect(() => {
    const el = ring.current;
    if (!el) return;
    const remaining = secondsLeft(seconds, startedAt, performance.now());
    el.style.setProperty("--ring-from", String(seconds > 0 ? Math.min(1, remaining / seconds) : 0));
    el.style.animationDuration = `${Math.round(remaining * 1000)}ms`;
  }, [seconds, startedAt]);

  const done = useEffectEvent(onDone);
  useEffect(() => {
    if (left === 0) done();
  }, [left]);

  return (
    <span className="inline-flex items-center gap-2 text-sm text-fg-muted">
      <span ref={ring} aria-hidden="true" data-anim="ring" data-volatile="" className="resend-ring shrink-0" />
      <span id={id} role="timer" aria-live="off" data-volatile="" data-numeric="">
        {copy.login.resendIn(left)}
      </span>
    </span>
  );
}
