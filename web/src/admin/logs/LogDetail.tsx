import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { copy } from "@/copy/ko";
import type { LogItem } from "@/lib/api-types";
import { formatKstMs } from "@/lib/time";
import { CATEGORY_GROUP, GROUP_COLOR_VAR } from "./categories";

const c = copy.logs.columns;

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-fg-muted">{label}</dt>
      <dd className="truncate">{children ?? <span className="text-fg-muted">{copy.common.none}</span>}</dd>
    </div>
  );
}

/**
 * One log line in full: its facts and the original event as JSON. The panel itself never scrolls
 * (only the JSON does), so both close controls stay in view in a 640×600 window.
 */
export function LogDetail({
  item, open, onClose, onCloseAutoFocus, onFilterUser, onFilterSession,
}: {
  /** The line shown; it stays while the dialog closes (no empty panel on the way out). */
  item: LogItem | null;
  open: boolean;
  onClose(): void;
  /** Where focus goes back to (there is no trigger: a table row opened the dialog). */
  onCloseAutoFocus(e: Event): void;
  onFilterUser(user: string): void;
  /** Without it (the audit screen: no session filter there) the session button is left out. */
  onFilterSession?(id: number): void;
}) {
  return (
    <Dialog open={open && item !== null} onOpenChange={(o) => !o && onClose()}>
      {item ? (
        <DialogContent
          aria-describedby={undefined}
          onCloseAutoFocus={onCloseAutoFocus}
          className="flex max-h-[calc(100dvh-2rem)] max-w-[calc(100vw-32px)] flex-col overflow-hidden sm:max-w-2xl"
        >
          <DialogHeader>
            <DialogTitle>{copy.logs.detail}</DialogTitle>
          </DialogHeader>
          <dl className="grid grid-cols-[repeat(auto-fill,minmax(min(100%,11rem),1fr))] gap-x-6 gap-y-2 text-sm">
            <Field label={c.ts}>
              <time dateTime={item.ts} className="tabular-nums">
                {formatKstMs(item.ts)}
              </time>
            </Field>
            <Field label={c.cat}>
              <span className="inline-flex items-center gap-1.5">
                <span aria-hidden="true" className="size-2 rounded-full" style={{ background: GROUP_COLOR_VAR[CATEGORY_GROUP[item.cat]] }} />
                {copy.logs.cats[item.cat] ?? item.cat}
              </span>
            </Field>
            <Field label={c.user}>{item.user}</Field>
            <Field label={c.session}>{item.session_id === null ? null : <span className="font-mono">{item.session_id}</span>}</Field>
            <Field label={c.ip}>{item.client_ip === null ? null : <span className="font-mono">{item.client_ip}</span>}</Field>
            <Field label={c.event}>{item.event === null ? null : <span className="font-mono">{item.event}</span>}</Field>
          </dl>
          <div className="flex min-h-0 flex-col gap-1">
            <h3 className="text-xs text-fg-muted">{copy.logs.raw}</h3>
            {/* the scroller is focusable so a keyboard can read a long event */}
            {/* eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- scrollable region (WCAG 2.1.1) */}
            <pre tabIndex={0} className="min-h-0 overflow-auto rounded-sm border bg-sunken p-3 font-mono text-xs break-all whitespace-pre-wrap">
              {JSON.stringify(item.data, null, 2)}
            </pre>
          </div>
          <DialogFooter showCloseButton className="flex-wrap">
            {item.user !== null ? (
              <Button variant="outline" onClick={() => onFilterUser(item.user!)}>
                {copy.logs.byUser}
              </Button>
            ) : null}
            {item.session_id !== null && onFilterSession ? (
              <Button variant="outline" onClick={() => onFilterSession(item.session_id!)}>
                {copy.logs.bySession}
              </Button>
            ) : null}
          </DialogFooter>
        </DialogContent>
      ) : null}
    </Dialog>
  );
}
