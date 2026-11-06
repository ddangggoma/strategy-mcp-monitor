import { useId, useState, type FormEvent, type ReactNode, type Ref } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { copy } from "@/copy/ko";
import { cn } from "@/lib/utils";
import type { QuickRange } from "./search";

const QUICK: readonly QuickRange[] = ["1h", "today", "yesterday", "7d"];
const LOCAL_MINUTE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/;

/** `YYYY-MM-DDTHH:mm` (a datetime-local value, read as KST) of a `+09:00` bound. */
const toLocal = (kst: string) => kst.slice(0, 16);
/** The KST bound of a datetime-local value: the UI is always KST, whatever the PC's time zone. */
const toKst = (local: string) => `${local}:00.000+09:00`;

/** An `aria-pressed` toggle in the shape of the sessions period buttons (no transition: log area). */
export function Toggle({ pressed, onClick, children, ref }: { pressed: boolean; onClick(): void; children: string; ref?: Ref<HTMLButtonElement> }) {
  return (
    <button
      ref={ref}
      type="button"
      aria-pressed={pressed}
      onClick={onClick}
      className="h-(--size-control-sm) rounded-sm px-3 text-sm whitespace-nowrap text-fg-muted hover:text-fg aria-pressed:bg-selected aria-pressed:text-fg"
    >
      {children}
    </button>
  );
}

export function ToggleGroup({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <div role="group" aria-label={label} className={cn("flex w-fit max-w-full flex-wrap rounded-md border border-border-strong p-0.5", className)}>
      {children}
    </div>
  );
}

/**
 * Quick ranges (recomputed on every visit, W34) and a custom KST minute range. The custom fields
 * start from the bounds in use; an empty or inverted range is not applied.
 */
export function TimeRangePicker({
  range, custom, from, to, onQuick, onCustom,
}: {
  range: QuickRange;
  /** Custom bounds are in use (no quick range is pressed). */
  custom: boolean;
  /** The resolved bounds in use (`+09:00`). */
  from: string;
  to: string;
  onQuick(r: QuickRange): void;
  onCustom(from: string, to: string): void;
}) {
  return (
    <div className="flex flex-wrap items-end gap-x-4 gap-y-2">
      <ToggleGroup label={copy.logs.quickLabel}>
        {QUICK.map((r) => (
          <Toggle key={r} pressed={!custom && r === range} onClick={() => onQuick(r)}>
            {copy.logs.quick[r]}
          </Toggle>
        ))}
      </ToggleGroup>
      {/* new bounds in use reset the drafts */}
      <CustomRange key={`${from}|${to}`} from={from} to={to} onApply={onCustom} />
    </div>
  );
}

function CustomRange({ from, to, onApply }: { from: string; to: string; onApply(from: string, to: string): void }) {
  const id = useId();
  const [a, setA] = useState(() => toLocal(from));
  const [b, setB] = useState(() => toLocal(to));
  const [error, setError] = useState<string | null>(null);

  // a blocked Apply moves focus to the field to fix (the alert says why)
  const fail = (message: string, key: "from" | "to") => {
    setError(message);
    document.getElementById(`${id}-${key}`)?.focus();
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!LOCAL_MINUTE.test(a)) return fail(copy.logs.incompleteRange, "from");
    if (!LOCAL_MINUTE.test(b)) return fail(copy.logs.incompleteRange, "to");
    if (a >= b) return fail(copy.logs.invertedRange, "to"); // same-format strings order like the times
    setError(null);
    onApply(toKst(a), toKst(b));
  };

  const field = (key: "from" | "to", value: string, set: (v: string) => void) => (
    <div className="flex min-w-0 flex-col gap-1">
      <label htmlFor={`${id}-${key}`} className="text-xs text-fg-muted">
        {copy.logs[key]}
      </label>
      <Input
        id={`${id}-${key}`}
        type="datetime-local"
        step={60}
        value={value}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${id}-error` : undefined}
        onChange={(e) => {
          set(e.target.value);
          setError(null);
        }}
        className="w-[min(100%,13.5rem)] tabular-nums max-[25rem]:px-1.5"
      />
    </div>
  );

  return (
    <form onSubmit={submit} className="flex min-w-0 flex-col gap-1">
      <div className="flex flex-wrap items-end gap-2">
        {field("from", a, setA)}
        {field("to", b, setB)}
        <Button type="submit" variant="outline">
          {copy.logs.apply}
        </Button>
      </div>
      {error ? (
        <p id={`${id}-error`} role="alert" className="text-sm text-danger">
          {error}
        </p>
      ) : null}
    </form>
  );
}
