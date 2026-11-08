import { useEffect, useMemo, useRef, useState } from "react";
import { InfoTip } from "@/components/app/InfoTip";
import { copy } from "@/copy/ko";
import type { LogQuery } from "@/lib/api-types";
import { denyReason } from "@/lib/permissions";
import { useSession } from "@/lib/session";
import { useElementWidth } from "@/lib/use-element-width";
import { cn } from "@/lib/utils";
import { useLogHistogram } from "../queries";
import { FilterBar } from "./FilterBar";
import { IndexBanner } from "./IndexBanner";
import { LogHistogram } from "./LogHistogram";
import { LogTable } from "./LogTable";
import { toLogQuery, type QuickRange } from "./search";
import { Toggle, ToggleGroup } from "./TimeRangePicker";
import { useLogNavigate, useLogSearch } from "./use-log-search";
import { UserTimeline } from "./UserTimeline";

/** Bars for a content width (W41: 2 px or more even at 640; the server takes 10–200). */
export function bucketsFor(width: number): number {
  if (width >= 1024) return 60;
  if (width >= 640) return 40;
  return 24;
}

// the histogram's own height (16 + 112 + 18) plus its legend line: a placeholder of the same size
// keeps the table from jumping when the first answer arrives
const HISTOGRAM_BOX = "h-[10.25rem]";

function HistogramPanel({ query, buckets, onSelect }: { query: LogQuery; buckets: number; onSelect(from: string, to: string): void }) {
  const { data, isPending, isError, isPlaceholderData } = useLogHistogram(query, "cat", buckets, { enabled: buckets > 0 });
  if (isPending) {
    return (
      <div role="status" className={cn(HISTOGRAM_BOX, "rounded-sm bg-selected")}>
        <span className="sr-only">{copy.common.loading}</span>
      </div>
    );
  }
  if (isError && !data) {
    return (
      <p role="alert" className="text-sm text-fg">
        {copy.logs.loadError}
      </p>
    );
  }
  return (
    <div aria-busy={isPlaceholderData || undefined} className={cn("min-w-0", isPlaceholderData && "opacity-60")}>
      <LogHistogram data={data} onSelect={onSelect} />
    </div>
  );
}

/**
 * Log search (spec §6.4 #4, docs/design/screens/logs.md): filters, a drag-to-select histogram, and
 * the lines as a virtual table or per-user timeline. The URL search is the only state (W34): the
 * API query is computed once per navigation (quick ranges are relative to that moment).
 */
export function LogsPage() {
  const me = useSession();
  const reason = denyReason(me, "view_logs");
  const search = useLogSearch();
  const go = useLogNavigate();
  // clicking a quick range again recomputes it even when the URL does not change
  const [refreshed, setRefreshed] = useState(0);
  const query = useMemo(
    // reading the clock is the point: once per navigation, so quick ranges end at "now" (W34)
    // eslint-disable-next-line react-hooks/purity
    () => toLogQuery(search, new Date(Math.max(Date.now(), refreshed))),
    [search, refreshed],
  );
  const [rootRef, width] = useElementWidth<HTMLDivElement>();
  const buckets = width > 0 ? bucketsFor(width) : 0; // nothing is asked before the width is known
  const view = search.view ?? "table";
  // a timeline cell opens the table: the focused lane goes away with the timeline, so focus moves
  // to the pressed 표 toggle instead of falling to <body>
  const tableToggle = useRef<HTMLButtonElement>(null);
  const focusTableToggle = useRef(false);
  useEffect(() => {
    if (view !== "table" || !focusTableToggle.current) return;
    focusTableToggle.current = false;
    tableToggle.current?.focus();
  }, [view]);

  const onQuickRange = (r: QuickRange) => {
    setRefreshed(Date.now());
    go({ range: r, from: undefined, to: undefined });
  };

  return (
    <div ref={rootRef} className="flex min-w-0 flex-col gap-4">
      <h1 className="text-xl font-semibold text-fg">{copy.logs.title}</h1>
      {reason ? (
        <p className="text-sm text-fg-muted">{copy.deny[reason]}</p>
      ) : (
        <>
          <IndexBanner />
          <FilterBar search={search} query={query} onChange={go} onQuickRange={onQuickRange} />
          <HistogramPanel query={query} buckets={buckets} onSelect={(from, to) => go({ from, to, range: undefined })} />
          <div className="flex items-center gap-1">
            <ToggleGroup label={copy.logs.viewLabel}>
              {(["table", "timeline"] as const).map((v) => (
                <Toggle key={v} ref={v === "table" ? tableToggle : undefined} pressed={view === v} onClick={() => go({ view: v })}>
                  {copy.logs.view[v]}
                </Toggle>
              ))}
            </ToggleGroup>
            <InfoTip label={copy.logs.viewLabel} content={copy.help.logs.view} align="start" />
          </div>
          {view === "timeline" ? (
            <UserTimeline
              query={query}
              buckets={buckets}
              onOpen={(user, from, to) => {
                focusTableToggle.current = true;
                go({ users: [user], from, to, range: undefined, view: "table" });
              }}
            />
          ) : (
            <LogTable query={query} onFilterUser={(u) => go({ users: [u] })} onFilterSession={(id) => go({ session: id })} />
          )}
        </>
      )}
    </div>
  );
}
