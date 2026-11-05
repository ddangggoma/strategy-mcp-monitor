// Sonner rendering of the manual-action lifecycle (ActionTracker → toasts). One toast per run,
// keyed by its run id, so pending → step → result replace each other in place. A result that is
// not "ok" (and an unknown one) stays longer and links to the MCP's history.
import { Link } from "@tanstack/react-router";
import { toast } from "sonner";
import { copy } from "@/copy/ko";
import type { ActionResult, ActionToasts, TrackedRun } from "@/lib/action-tracker";
import { formatDuration } from "@/lib/time";

/** Failures and unknown results stay until read (with time to reach the link). */
const STICKY_MS = 15_000;

function HistoryLink({ mcpId }: { mcpId: number }) {
  return (
    <Link
      to="/admin/mcps/$mcpId"
      params={{ mcpId: String(mcpId) }}
      search={{ tab: "history" }}
      className="ms-auto shrink-0 self-center text-sm font-semibold text-fg underline underline-offset-4"
    >
      {copy.toasts.viewHistory}
    </Link>
  );
}

/** “종료 코드 3, 1.2초 걸렸어요.” and friends: what the result means, in one sentence. */
export function resultDetail(e: ActionResult): string | undefined {
  const duration = formatDuration(e.duration_ms);
  if (e.status === "error") return copy.toasts.runError;
  if (e.status === "timeout") return copy.toasts.timedOut(duration);
  if (e.exit_code !== null) return copy.toasts.exitAndDuration(e.exit_code, duration);
  return e.duration_ms === null ? undefined : copy.toasts.duration(duration);
}

export function sonnerActionToasts(): ActionToasts {
  return {
    pending(r: TrackedRun) {
      toast.loading(copy.toasts.pending(r.mcpName, r.requested), { id: r.runId });
    },
    step(r: TrackedRun) {
      toast.loading(copy.toasts.pending(r.mcpName, r.requested), { id: r.runId, description: copy.toasts.restartStep });
    },
    done(r: TrackedRun, e: ActionResult) {
      const description = resultDetail(e);
      if (e.status === "ok") {
        toast.success(copy.toasts.ok(r.mcpName, r.requested), { id: r.runId, description, action: null });
        return;
      }
      toast.error(copy.toasts.failed(r.mcpName, r.requested), {
        id: r.runId,
        description,
        duration: STICKY_MS,
        action: <HistoryLink mcpId={r.mcpId} />,
      });
    },
    unknown(r: TrackedRun) {
      toast.warning(copy.toasts.unknown(r.mcpName), {
        id: r.runId,
        description: null,
        duration: STICKY_MS,
        action: <HistoryLink mcpId={r.mcpId} />,
      });
    },
  };
}
