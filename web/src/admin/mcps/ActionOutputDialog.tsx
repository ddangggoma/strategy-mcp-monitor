import type { ReactNode } from "react";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { copy } from "@/copy/ko";
import type { ActionRecord } from "@/lib/api-types";
import { formatDuration, formatKst } from "@/lib/time";
import { useActionDetail } from "../queries";
import { ActionResult, actionKindLabel, reasonLabel } from "./ActionResult";

/**
 * One script run in full: the history row's facts, then stdout and stderr as preformatted text
 * (the server keeps the first part of a long output and says so: `*_truncated`). Opened by state
 * from a table row, so focus goes back to the row's button on close.
 */
export function ActionOutputDialog({
  mcpId,
  action,
  open,
  onClose,
  returnFocus,
}: {
  mcpId: number;
  /** The run to show; kept after closing so the exit animation still has content. */
  action: ActionRecord | null;
  open: boolean;
  onClose: () => void;
  returnFocus: () => void;
}) {
  return (
    <Dialog open={open && action !== null} onOpenChange={(o) => (o ? undefined : onClose())}>
      {action ? (
        <DialogContent
          className="sm:max-w-3xl"
          onCloseAutoFocus={(e) => {
            e.preventDefault();
            returnFocus();
          }}
        >
          <Output mcpId={mcpId} action={action} />
        </DialogContent>
      ) : null}
    </Dialog>
  );
}

function Output({ mcpId, action }: { mcpId: number; action: ActionRecord }) {
  const detail = useActionDetail(mcpId, action.id);
  const c = copy.mcp.historyColumns;
  const d = detail.data;

  return (
    <>
      <DialogHeader>
        <DialogTitle>{copy.mcp.outputTitle(actionKindLabel(action), formatKst(action.at))}</DialogTitle>
        <DialogDescription asChild>
          <dl className="flex flex-wrap gap-x-5 gap-y-1 text-sm">
            <Fact label={c.result}>
              <ActionResult status={action.status} />
            </Fact>
            <Fact label={c.exitCode}>{action.exit_code ?? copy.common.none}</Fact>
            <Fact label={c.duration}>{formatDuration(action.duration_ms)}</Fact>
            <Fact label={c.trigger}>{copy.mcp.triggers[action.trigger]}</Fact>
            <Fact label={c.reason}>{reasonLabel(action.reason)}</Fact>
            <Fact label={c.actor}>{action.actor?.name ?? copy.mcp.systemActor}</Fact>
          </dl>
        </DialogDescription>
      </DialogHeader>

      {action.error ? (
        <p className="text-sm text-fg">
          <span className="font-semibold">{copy.mcp.runErrorLabel}</span> <span className="font-mono text-xs">{action.error}</span>
        </p>
      ) : null}

      {detail.isError ? (
        <p role="alert" className="text-sm text-fg">
          {copy.mcp.outputError}
        </p>
      ) : !d ? (
        <div role="status" className="flex flex-col gap-2">
          <span className="sr-only">{copy.common.loading}</span>
          <Skeleton className="h-24 w-full" />
        </div>
      ) : (
        <div className="flex min-w-0 flex-col gap-4">
          <Stream title={copy.mcp.stdout} text={d.stdout} truncated={d.stdout_truncated} />
          <Stream title={copy.mcp.stderr} text={d.stderr} truncated={d.stderr_truncated} />
        </div>
      )}
    </>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex gap-1.5">
      <dt className="text-fg-muted">{label}</dt>
      <dd className="text-fg">{children}</dd>
    </div>
  );
}

function Stream({ title, text, truncated }: { title: string; text: string; truncated: boolean }) {
  return (
    <section className="flex min-w-0 flex-col gap-1.5">
      <h3 className="text-sm font-semibold text-fg">{title}</h3>
      {text === "" ? (
        <p className="text-sm text-fg-muted">{copy.mcp.noOutput}</p>
      ) : (
        <pre
          // a scrolling box must take keyboard focus to be scrolled without a mouse (WCAG 2.1.1, axe scrollable-region-focusable)
          // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
          tabIndex={0}
          aria-label={title}
          className="max-h-64 overflow-auto rounded-sm border bg-sunken p-3 font-mono text-xs whitespace-pre text-fg"
        >
          {text}
        </pre>
      )}
      {truncated ? <p className="text-xs text-fg-muted">{copy.mcp.truncated}</p> : null}
    </section>
  );
}
