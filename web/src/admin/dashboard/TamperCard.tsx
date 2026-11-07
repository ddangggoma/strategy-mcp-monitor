import { ShieldAlertIcon } from "lucide-react";
import { useMemo } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { copy } from "@/copy/ko";
import type { TamperEvent } from "@/lib/api-types";
import { denyReason } from "@/lib/permissions";
import { useSession } from "@/lib/session";
import { formatKst } from "@/lib/time";
import { useTamperRecent } from "../queries";

/** Rows shown on the dashboard (the cache keeps TAMPER_LIMIT). */
const RECENT = 10;

/** Fields that name what an event without a user or session is about (a script, a log file, a registry value). */
const SUBJECT_FIELDS = ["path", "file", "key"] as const;

interface Summary {
  text: string;
  /** A machine value (path, file name, registry value): monospace. */
  mono: boolean;
}

/** Who and which session ("CORP\kim, 세션 3"); otherwise the file or value the event is about. */
export function tamperSummary(e: TamperEvent): Summary | null {
  const who: string[] = [];
  if (typeof e.user === "string" && e.user) who.push(e.user);
  if (typeof e.session_id === "number") who.push(copy.tamper.session(e.session_id));
  if (who.length > 0) return { text: who.join(", "), mono: false };
  for (const k of SUBJECT_FIELDS) {
    const v = e[k];
    if (typeof v === "string" && v) return { text: v, mono: true };
  }
  return null;
}

function Row({ e }: { e: TamperEvent }) {
  const summary = tamperSummary(e);
  return (
    <li className="flex gap-3 py-2 first:pt-0 last:pb-0">
      {/* bypass detection is always a thing to look at again: the house warning hue, with words */}
      <ShieldAlertIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-state-suspect" />
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3">
          <span className="font-medium text-fg">{copy.tamper.events[e.event] ?? e.event}</span>
          <time dateTime={e.at} className="text-xs text-fg-muted tabular-nums">
            {formatKst(e.at)}
          </time>
        </div>
        {summary ? (
          <span className={summary.mono ? "truncate font-mono text-xs text-fg-muted" : "truncate text-fg-muted"}>{summary.text}</span>
        ) : null}
      </div>
    </li>
  );
}

/**
 * The dashboard's “우회 탐지 이벤트” card body: the newest ten tamper events (icon + name + KST time
 * + who/what). SSE `tamper` events arrive at the front through connectLive; no row animation.
 */
export function TamperCard() {
  const me = useSession();
  const reason = denyReason(me, "view_logs");
  const { data, isPending, isError } = useTamperRecent();
  const rows = useMemo(() => data?.slice(0, RECENT) ?? [], [data]);

  if (reason) return <p className="text-sm text-fg-muted">{copy.deny[reason]}</p>;
  if (isPending) {
    return (
      <div role="status" className="flex flex-col gap-2">
        <span className="sr-only">{copy.common.loading}</span>
        <Skeleton className="h-8" />
        <Skeleton className="h-8" />
      </div>
    );
  }
  if (isError && !data) return <p role="alert" className="text-sm text-fg">{copy.sessions.loadError}</p>;
  if (rows.length === 0) return <p className="text-sm text-fg-muted">{copy.tamper.empty}</p>;
  return (
    <ol className="flex flex-col divide-y text-sm">
      {rows.map((e, i) => (
        // records have no id; position in the newest-first list is stable between two events
        <Row key={`${i}-${e.at}-${e.event}`} e={e} />
      ))}
    </ol>
  );
}
