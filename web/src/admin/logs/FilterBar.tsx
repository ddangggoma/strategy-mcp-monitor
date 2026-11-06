import { XIcon } from "lucide-react";
import { useEffect, useId, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { copy } from "@/copy/ko";
import type { LogCategory, LogQuery } from "@/lib/api-types";
import { logExportUrl } from "@/lib/endpoints";
import { CategoryChips } from "./CategoryChips";
import { ExportMenu } from "./ExportMenu";
import type { LogSearch, QuickRange } from "./search";
import { TimeRangePicker } from "./TimeRangePicker";
import type { LogSearchPatch } from "./use-log-search";
import { UserFilter } from "./UserFilter";

/** Typing settles for this long before it becomes a filter (one request per pause, not per key). */
export const TYPE_DEBOUNCE_MS = 300;

const toggle = <T,>(list: readonly T[] | undefined, v: T): T[] => {
  const cur = list ?? [];
  return cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v];
};

/**
 * A labelled text filter that writes itself to the URL after a pause. The URL value wins when it
 * changes from elsewhere (clear, "filter by this session"), except for the value this field sent.
 */
export function TypedFilter({
  label, value, normalize, onCommit, hint, invalid, inputMode, className,
}: {
  label: string;
  value: string;
  /** The value to send, or null when the text is not a valid value yet. */
  normalize(text: string): string | null;
  onCommit(v: string): void;
  hint?: string;
  /** Shown under the field while the text is not a valid value. */
  invalid?: string;
  inputMode?: "numeric" | "text";
  className?: string;
}) {
  const id = useId();
  const [text, setText] = useState(value);
  const [seen, setSeen] = useState(value);
  const [sent, setSent] = useState(value);
  if (value !== seen) {
    setSeen(value);
    if (value !== sent) setText(value); // changed elsewhere: show it
  }

  useEffect(() => {
    const next = normalize(text);
    if (next === null || next === value) return;
    const t = setTimeout(() => {
      setSent(next);
      onCommit(next);
    }, TYPE_DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [text, value, normalize, onCommit]);

  const bad = normalize(text) === null;
  return (
    <div className={className}>
      <label htmlFor={id} className="mb-1 block text-xs text-fg-muted">
        {label}
      </label>
      <Input
        id={id}
        value={text}
        inputMode={inputMode}
        title={hint}
        aria-describedby={[hint ? `${id}-hint` : "", bad && invalid ? `${id}-error` : ""].filter(Boolean).join(" ") || undefined}
        aria-invalid={bad || undefined}
        onChange={(e) => setText(e.target.value)}
        autoComplete="off"
        spellCheck={false}
      />
      {bad && invalid ? (
        <p id={`${id}-error`} className="mt-1 text-xs text-danger">
          {invalid}
        </p>
      ) : null}
      {hint ? (
        <span id={`${id}-hint`} hidden>
          {hint}
        </span>
      ) : null}
    </div>
  );
}

export const keepText = (t: string) => t.trim();
const sessionText = (t: string) => (t.trim() === "" || /^\d+$/.test(t.trim()) ? t.trim() : null);

/** The filter rows above the histogram (a container: rows wrap inside it at any width, W41). */
export function FilterBar({
  search, query, onChange, onQuickRange,
}: {
  search: LogSearch;
  query: LogQuery;
  onChange(patch: LogSearchPatch, opts?: { replace?: boolean }): void;
  onQuickRange(r: QuickRange): void;
}) {
  // typing replaces the history entry: one entry per filter, not per pause
  const commit = useMemo(() => {
    const typed = (key: "q" | "ip" | "session") => (v: string) =>
      onChange({ [key]: v === "" ? undefined : key === "session" ? Number(v) : v }, { replace: true });
    return { q: typed("q"), ip: typed("ip"), session: typed("session") };
  }, [onChange]);

  const extra = [
    ...(search.event ?? []).map((v) => ({ key: "event" as const, v, label: `${copy.logs.columns.event}: ${v}` })),
    ...(search.outcome ?? []).map((v) => ({ key: "outcome" as const, v, label: `${copy.audit.columns.result}: ${v}` })),
  ];
  const filtered =
    !!search.users?.length || !!search.cat?.length || extra.length > 0 || search.session !== undefined || !!search.ip || !!search.q;

  return (
    <div className="@container/filters flex min-w-0 flex-col gap-3 rounded-md border bg-surface p-3">
      <TimeRangePicker
        range={search.range ?? "1h"}
        custom={search.from !== undefined && search.to !== undefined}
        from={query.from}
        to={query.to}
        onQuick={onQuickRange}
        onCustom={(from, to) => onChange({ from, to, range: undefined })}
      />
      <CategoryChips selected={search.cat ?? []} onToggle={(c: LogCategory) => onChange((s) => ({ cat: toggle(s.cat, c) }))} />
      <div className="flex min-w-0 flex-wrap items-end gap-2">
        <UserFilter query={query} selected={search.users ?? []} onToggle={(u) => onChange((s) => ({ users: toggle(s.users, u) }))} />
        <TypedFilter
          label={copy.logs.session}
          value={search.session === undefined ? "" : String(search.session)}
          normalize={sessionText}
          onCommit={commit.session}
          invalid={copy.logs.sessionInvalid}
          inputMode="numeric"
          className="w-[min(100%,7rem)]"
        />
        <TypedFilter label={copy.logs.ip} value={search.ip ?? ""} normalize={keepText} onCommit={commit.ip} className="w-[min(100%,10rem)]" />
        <TypedFilter
          label={copy.logs.keyword}
          value={search.q ?? ""}
          normalize={keepText}
          onCommit={commit.q}
          hint={copy.logs.keywordHint}
          className="w-[min(100%,16rem)] max-w-96 grow"
        />
        {extra.length > 0 ? (
          <div role="group" aria-label={copy.logs.moreConditions} className="flex flex-wrap items-center gap-1.5">
            <span aria-hidden="true" className="text-xs text-fg-muted">
              {copy.logs.moreConditions}
            </span>
            {extra.map((x) => (
              <span key={`${x.key}-${x.v}`} className="inline-flex h-(--size-control-sm) items-center gap-1 rounded-full border border-border-strong pr-1 pl-2.5 text-sm">
                <span className="font-mono text-xs">{x.label}</span>
                <button
                  type="button"
                  aria-label={copy.logs.removeCondition(x.label)}
                  onClick={() => onChange((s) => ({ [x.key]: (s[x.key] as string[] | undefined)?.filter((v) => v !== x.v) }))}
                  className="inline-flex size-6 items-center justify-center rounded-full text-fg-muted hover:bg-hover hover:text-fg"
                >
                  <XIcon aria-hidden="true" className="size-3.5" />
                </button>
              </span>
            ))}
          </div>
        ) : null}
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {filtered ? (
            <Button
              variant="ghost"
              onClick={() =>
                onChange({ users: undefined, cat: undefined, event: undefined, outcome: undefined, session: undefined, ip: undefined, q: undefined })
              }
            >
              {copy.logs.clear}
            </Button>
          ) : null}
          <ExportMenu hrefFor={(f) => logExportUrl(query, f)} />
        </div>
      </div>
    </div>
  );
}
