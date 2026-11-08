import { InfoTip } from "@/components/app/InfoTip";
import { copy } from "@/copy/ko";
import type { LogCategory } from "@/lib/api-types";
import { CATEGORY_GROUP, GROUP_COLOR_VAR, LOG_CATEGORIES, LOG_GROUPS } from "./categories";

const BY_GROUP = LOG_GROUPS.map((g) => [g, LOG_CATEGORIES.filter((c) => CATEGORY_GROUP[c] === g)] as const);

/**
 * One toggle per category, bundled by colour group (W32). The dot carries the group colour; the
 * name always says which category it is, so colour is never the only cue.
 */
export function CategoryChips({ selected, onToggle }: { selected: readonly LogCategory[]; onToggle(c: LogCategory): void }) {
  const on = new Set(selected);
  return (
    <div role="group" aria-label={copy.logs.categories} className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2">
      {BY_GROUP.map(([g, cats]) => (
        <div key={g} role="group" aria-label={copy.logs.groups[g]} className="flex min-w-0 flex-wrap items-center gap-1.5">
          <span aria-hidden="true" className="mr-0.5 text-xs text-fg-muted">
            {copy.logs.groups[g]}
          </span>
          {cats.map((c) => (
            <button
              key={c}
              type="button"
              aria-pressed={on.has(c)}
              onClick={() => onToggle(c)}
              className="inline-flex h-(--size-control-sm) items-center gap-1.5 rounded-full border border-border px-2.5 text-sm whitespace-nowrap text-fg-muted hover:text-fg aria-pressed:border-fg aria-pressed:bg-selected aria-pressed:text-fg"
            >
              <span aria-hidden="true" className="size-2 rounded-full" style={{ background: GROUP_COLOR_VAR[g] }} />
              {copy.logs.cats[c]}
            </button>
          ))}
        </div>
      ))}
      <CommandLogHelp />
    </div>
  );
}

/** What the command log does not see (spec §2 #7), next to the chips that filter it. */
function CommandLogHelp() {
  return <InfoTip label={copy.logs.cats["activity.command"]} content={copy.logs.cmdLimitHelp} align="start" />;
}
