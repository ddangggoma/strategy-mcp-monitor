import { LockIcon } from "lucide-react";
import type { ReactNode } from "react";
import { copy } from "@/copy/ko";
import { denyReason, type Action } from "@/lib/permissions";
import { useSession } from "@/lib/session";

/**
 * A page only some people may open (Local-only, Admin-only). When `denyReason(me, action)` says no,
 * it draws the page title and one sentence with the reason, and does not render its children at
 * all, so none of their queries run: on the external channel a Local-only API is never called and
 * its 404 never read as "nothing here" (Global Constraints). A lock, not the hourglass of
 * PlannedFeature: the screen exists, this person or channel just cannot use it.
 */
export function LocalOnlyPage({ action, title, children }: { action: Action; title: string; children: ReactNode }) {
  const me = useSession();
  const reason = denyReason(me, action);
  if (reason === null) return children;

  return (
    <>
      <h1 className="text-xl font-semibold text-fg">{title}</h1>
      <div
        data-denied={reason}
        className="flex max-w-(--size-prose) items-start gap-3 rounded-md border bg-surface px-4 py-3 text-sm text-fg-muted"
      >
        <LockIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
        <p>{copy.deny[reason]}</p>
      </div>
    </>
  );
}
