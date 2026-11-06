import { Link } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { copy } from "@/copy/ko";
import type { LogCategory, LogHistogram as Histogram, LogQuery } from "@/lib/api-types";
import { denyReason } from "@/lib/permissions";
import { useSession } from "@/lib/session";
import { CATEGORY_GROUP, GROUP_COLOR_VAR } from "../logs/categories";
import { LogHistogram } from "../logs/LogHistogram";
import { kstIso } from "../logs/search";
import { useLogHistogram } from "../queries";

const MINUTE = 60_000;
const WINDOW = 24 * 60 * MINUTE;
/** One bar per hour. */
const BARS = 24;
/** The window moves on while the dashboard stays open. */
const SLIDE_MS = 5 * MINUTE;

/** Failed web logins (`auth`) and failed remote desktop logons (`session`), in stack order. */
const SERIES: readonly { cat: LogCategory; name: string }[] = [
  { cat: "auth", name: copy.dashboard.loginFailures.web },
  { cat: "session", name: copy.dashboard.loginFailures.rdp },
];
// the histogram folds categories into their groups: name the two groups after the two series
const GROUP_NAMES = Object.fromEntries(SERIES.map((s) => [CATEGORY_GROUP[s.cat], s.name]));

/** The last 24 hours up to the next whole minute (minute bounds take the rollup path, W8). */
function lastDay(nowMs: number): LogQuery {
  const end = Math.ceil(nowMs / MINUTE) * MINUTE;
  return {
    from: kstIso(end - WINDOW),
    to: kstIso(end),
    cat: SERIES.map((s) => s.cat),
    event: ["login", "logon_failed"],
    outcome: ["fail"],
  };
}

function useLastDay(): LogQuery {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), SLIDE_MS);
    return () => clearInterval(t);
  }, []);
  return useMemo(() => lastDay(now), [now]);
}

const sumOf = (data: Histogram, cat: LogCategory) =>
  data.series.filter((s) => s.key === cat).reduce((a, s) => a + s.counts.reduce((x, y) => x + y, 0), 0);

/**
 * The dashboard's “로그인 실패 추이” card: failed web logins and remote desktop logons over the last
 * 24 hours as small hourly bars (a picture, no selection), the total of each with its colour, and a
 * link that opens the same lines in the log viewer.
 */
export function LoginFailuresCard() {
  const reason = denyReason(useSession(), "view_logs");
  const query = useLastDay();
  const { data, isPending, isError } = useLogHistogram(query, "cat", BARS, { enabled: reason === null });

  if (reason) return <p className="text-sm text-fg-muted">{copy.deny[reason]}</p>;

  let body;
  if (isPending) {
    body = (
      <div role="status" className="h-[4.75rem] rounded-sm bg-selected">
        <span className="sr-only">{copy.common.loading}</span>
      </div>
    );
  } else if (isError && !data) {
    body = (
      <p role="alert" className="text-sm text-fg">
        {copy.dashboard.loginFailures.error}
      </p>
    );
  } else if (!data || data.total === 0) {
    body = <p className="text-sm text-fg-muted">{copy.dashboard.loginFailures.empty}</p>;
  } else {
    body = (
      <div className="flex min-w-0 flex-col gap-2">
        {/* the legend carries the numbers: the bars are never the only way to read them */}
        <div className="flex flex-wrap items-baseline gap-x-5 gap-y-1 text-sm">
          <ul className="flex flex-wrap items-baseline gap-x-5 gap-y-1">
            {SERIES.map((s) => (
              <li key={s.cat} className="inline-flex items-baseline gap-1.5">
                <span aria-hidden="true" className="size-2.5 shrink-0 self-center rounded-xs" style={{ background: GROUP_COLOR_VAR[CATEGORY_GROUP[s.cat]] }} />
                <span className="text-fg-muted">{s.name}</span>
                <span className="font-semibold text-fg tabular-nums">{copy.logs.count(sumOf(data, s.cat))}</span>
              </li>
            ))}
          </ul>
          <span className="text-fg-muted tabular-nums">{copy.logs.total(data.total)}</span>
        </div>
        <LogHistogram data={data} compact label={copy.dashboard.loginFailures.chartLabel(data.total)} names={GROUP_NAMES} />
      </div>
    );
  }

  return (
    <>
      {body}
      <Link
        to="/admin/logs"
        search={{ from: query.from, to: query.to, cat: query.cat, event: query.event, outcome: query.outcome }}
        className="self-start text-sm font-medium text-fg underline underline-offset-4"
      >
        {copy.dashboard.loginFailures.openLogs}
      </Link>
    </>
  );
}
