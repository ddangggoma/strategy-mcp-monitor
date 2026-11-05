import {
  CircleCheckIcon,
  CirclePauseIcon,
  CircleXIcon,
  RefreshCwIcon,
  TriangleAlertIcon,
  WrenchIcon,
  type LucideIcon,
} from "lucide-react";
import { AnimatePresence, LazyMotion, domAnimation, m } from "motion/react";
import { copy } from "@/copy/ko";
import type { Issue, McpState } from "@/lib/api-types";
import { cn } from "@/lib/utils";

/** One icon per state, so a state never relies on color alone (WCAG 1.4.1). */
export const STATE_ICONS: Record<McpState, LucideIcon> = {
  HEALTHY: CircleCheckIcon,
  SUSPECT: TriangleAlertIcon,
  ACTION: WrenchIcon,
  RECOVERING: RefreshCwIcon,
  FAILED: CircleXIcon,
  MAINTENANCE: CirclePauseIcon,
};

// Full class names (Tailwind only sees literal strings)
const BADGE_TONE: Record<McpState, string> = {
  HEALTHY: "bg-state-healthy-soft text-state-healthy-fg",
  SUSPECT: "bg-state-suspect-soft text-state-suspect-fg",
  ACTION: "bg-state-action-soft text-state-action-fg",
  RECOVERING: "bg-state-recovering-soft text-state-recovering-fg",
  FAILED: "bg-state-failed-soft text-state-failed-fg",
  MAINTENANCE: "bg-state-maintenance-soft text-state-maintenance-fg",
};

/** Text color of the state's -fg role: the board verdict sentence uses it. */
export const STATE_TEXT: Record<McpState, string> = {
  HEALTHY: "text-state-healthy-fg",
  SUSPECT: "text-state-suspect-fg",
  ACTION: "text-state-action-fg",
  RECOVERING: "text-state-recovering-fg",
  FAILED: "text-state-failed-fg",
  MAINTENANCE: "text-state-maintenance-fg",
};

const SIZE = {
  sm: "gap-1 px-1.5 py-0.5 text-xs [&_svg]:size-3.5",
  lg: "gap-1.5 px-2 py-1 text-sm [&_svg]:size-4",
} as const;

// --motion-fast with --ease-out (direction.md §6)
const FADE = { duration: 0.12, ease: [0.23, 1, 0.32, 1] } as const;

export interface StatusBadgeProps {
  state: McpState;
  issue?: Issue | null;
  size?: "sm" | "lg";
  className?: string;
}

/** Icon + state word on the state's soft fill; a state change crossfades (opacity only). */
export function StatusBadge({ state, issue, size = "sm", className }: StatusBadgeProps) {
  const Icon = STATE_ICONS[state];
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      {/* old and new badge share one grid cell while they crossfade */}
      <span data-state={state} data-anim="fade" className="inline-grid shrink-0">
        <LazyMotion features={domAnimation}>
          <AnimatePresence initial={false}>
            <m.span
              key={state}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={FADE}
              className={cn(
                "col-start-1 row-start-1 inline-flex items-center rounded-sm font-medium whitespace-nowrap",
                SIZE[size],
                BADGE_TONE[state],
              )}
            >
              <Icon aria-hidden="true" />
              {copy.states[state]}
            </m.span>
          </AnimatePresence>
        </LazyMotion>
      </span>
      {issue ? <span className={cn("text-fg", size === "lg" ? "text-sm" : "text-xs")}>{copy.issues[issue]}</span> : null}
    </span>
  );
}
