import { InfoIcon } from "lucide-react";
import { copy } from "@/copy/ko";
import type { RdpSession } from "@/lib/api-types";
import { cn } from "@/lib/utils";
import "./ConnectionBanner.css";

/**
 * "Is someone connected?" — the first thing the board answers. `undefined` means the collector has
 * not reported yet (Plan 4): neutral, no pulse. The dot is neutral ink, not a state hue (hue is
 * reserved for MCP state); the pulse is the signal, and it stops under reduced motion.
 */
export function ConnectionBanner({ sessions, className }: { sessions: RdpSession[] | undefined; className?: string }) {
  if (sessions === undefined) {
    return (
      <p className={cn("flex items-center gap-2 text-sm text-fg-muted", className)}>
        <InfoIcon aria-hidden="true" className="size-4 shrink-0" />
        {copy.board.sessionsNotReady}
      </p>
    );
  }
  const connected = sessions.length > 0;
  return (
    <p className={cn("flex items-center gap-3 text-lg font-semibold", connected ? "text-fg" : "text-fg-muted", className)}>
      <span
        aria-hidden="true"
        className="presence-dot"
        data-presence={connected ? "on" : "off"}
        data-anim={connected ? "pulse" : undefined}
      />
      {connected ? copy.board.connected : copy.board.noSession}
    </p>
  );
}
