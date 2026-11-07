import { useBlocker } from "@tanstack/react-router";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { copy } from "@/copy/ko";

/**
 * Asks before leaving the page while `when` holds (unsaved edits): a dialog for in-app moves,
 * the browser's own prompt for a reload or a closed tab. Moves within the same page (a tab kept in
 * `?tab=`) pass. A session expiry navigates with `ignoreBlocker` (F12) and is never held up.
 */
export function LeaveGuard({ when }: { when: boolean }) {
  const blocker = useBlocker({
    shouldBlockFn: ({ current, next }) => when && current.pathname !== next.pathname,
    enableBeforeUnload: when,
    withResolver: true,
  });
  const blocked = blocker.status === "blocked";

  return (
    <AlertDialog
      open={blocked}
      onOpenChange={(open) => {
        if (!open && blocked) blocker.reset();
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{copy.common.unsavedTitle}</AlertDialogTitle>
          <AlertDialogDescription>{copy.common.unsavedBody}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>{copy.common.stay}</AlertDialogCancel>
          <AlertDialogAction variant="destructive" onClick={() => (blocked ? blocker.proceed() : undefined)}>
            {copy.common.leave}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
