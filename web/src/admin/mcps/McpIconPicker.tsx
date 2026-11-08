import { useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { useWatch, type Control } from "react-hook-form";
import { McpIcon } from "@/components/status/McpIcon";
import { FormField, FormItem, FormMessage } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { copy } from "@/copy/ko";
import type { McpConfig } from "@/lib/api-types";
import { CURATED_EMOJI, isMcpEmoji, type EmojiGroup } from "@/lib/mcp-emoji";
import { DEFAULT_MCP_ICON } from "@/lib/mcp-icon";
import { cn } from "@/lib/utils";
import type { McpFormValues } from "./mcp-schema";

interface Option {
  value: string | null;
  label: string;
  content: ReactNode;
}

const DefaultGlyph = DEFAULT_MCP_ICON;
const GROUPS = Object.keys(CURATED_EMOJI) as EmojiGroup[];
const CURATED = new Set<string>(GROUPS.flatMap((g) => CURATED_EMOJI[g]));

const emojiOption = (e: string, label: string): Option => ({
  value: e,
  label,
  content: (
    <span aria-hidden="true" className="mcp-emoji">
      {e}
    </span>
  ),
});

const DEFAULT_OPTION: Option = { value: null, label: copy.mcp.icon.defaultIcon, content: <DefaultGlyph aria-hidden="true" /> };
const SECTIONS = GROUPS.map((g) => ({
  group: g,
  options: CURATED_EMOJI[g].map((e) => emojiOption(e, copy.mcp.icon.names[e] ?? e)),
}));

/**
 * The MCP's icon: one emoji or the default MCP icon, with a live preview of the board card's
 * header. The ready-made emoji are one radio group in sections (WAI-ARIA radio pattern: one Tab
 * stop, arrow keys move and select, Home/End jump to the ends); any other emoji can be pasted and
 * is checked as it is typed, by the same rules as the server. Read-only keeps it focusable but
 * unchangeable.
 */
export function McpIconPicker({ control, readOnly }: { control: Control<McpFormValues, unknown, McpConfig>; readOnly: boolean }) {
  const [name, icon] = useWatch({ control, name: ["name", "icon"] });
  const previewId = useId();

  return (
    <div className="flex min-w-0 flex-col gap-4 @lg:col-span-2">
      <figure className="flex flex-col gap-1.5" aria-labelledby={previewId}>
        <figcaption id={previewId} className="text-xs text-fg-muted">
          {copy.mcp.icon.preview}
        </figcaption>
        <div
          data-testid="mcp-icon-preview"
          className="flex max-w-80 min-w-0 items-center gap-2.5 rounded-lg border border-border bg-surface px-4 py-3"
        >
          <McpIcon icon={icon} />
          <span className={cn("min-w-0 truncate text-lg leading-tight font-semibold", name?.trim() ? "text-fg" : "text-fg-muted")}>
            {name?.trim() || copy.mcp.icon.previewName}
          </span>
        </div>
      </figure>

      <FormField
        control={control}
        name="icon"
        render={({ field }) => (
          <FormItem className="min-w-0">
            <IconChoice value={field.value ?? null} onChange={field.onChange} onBlur={field.onBlur} readOnly={readOnly} />
            <FormMessage />
          </FormItem>
        )}
      />
      <p className="text-sm text-fg-muted">{copy.mcp.icon.hint}</p>
    </div>
  );
}

function IconChoice({
  value,
  onChange,
  onBlur,
  readOnly,
}: {
  value: string | null;
  onChange: (value: string | null) => void;
  onBlur: () => void;
  readOnly: boolean;
}) {
  const ids = { group: useId(), paste: useId(), pasteHint: useId(), pasteError: useId(), section: useId() };
  const custom = value !== null && !CURATED.has(value) ? value : null;
  const [text, setText] = useState(custom ?? "");
  const [invalid, setInvalid] = useState(false);
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);

  // a pasted emoji outside the list is offered (checked) above the sections
  const head: Option[] = [DEFAULT_OPTION, ...(custom ? [emojiOption(custom, copy.mcp.icon.custom(custom))] : [])];
  const flat = [...head, ...SECTIONS.flatMap((s) => s.options)];
  const found = flat.findIndex((o) => o.value === value);
  const active = found === -1 ? 0 : found; // an unusable stored value: the default takes the Tab stop

  const choose = (v: string | null) => {
    if (readOnly) return;
    onChange(v);
    if (v === null || CURATED.has(v)) setText("");
    setInvalid(false);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>, i: number) => {
    const n = flat.length;
    const next =
      e.key === "ArrowRight" || e.key === "ArrowDown"
        ? (i + 1) % n
        : e.key === "ArrowLeft" || e.key === "ArrowUp"
          ? (i - 1 + n) % n
          : e.key === "Home"
            ? 0
            : e.key === "End"
              ? n - 1
              : null;
    if (next === null) return;
    e.preventDefault();
    buttons.current[next]?.focus();
    choose(flat[next]!.value); // selection follows focus (radio pattern)
  };

  let index = 0;
  const radio = (o: Option, className?: string) => {
    const i = index++;
    return (
      <button
        key={o.value ?? "default"}
        ref={(el) => {
          buttons.current[i] = el;
        }}
        type="button"
        role="radio"
        aria-checked={i === found}
        aria-label={o.label}
        title={o.label}
        tabIndex={i === active ? 0 : -1}
        onClick={() => choose(o.value)}
        onKeyDown={(e) => onKeyDown(e, i)}
        className={cn(
          "inline-flex h-10 items-center justify-center rounded-md border border-border text-xl text-fg-muted transition-colors duration-(--motion-fast) ease-hover hover:bg-hover hover:text-fg [&_svg]:size-5",
          "aria-checked:border-fg aria-checked:bg-selected aria-checked:text-fg aria-checked:shadow-[inset_0_0_0_1px_var(--color-fg)]",
          readOnly && "cursor-default hover:bg-transparent",
          className,
        )}
      >
        {o.content}
      </button>
    );
  };

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <div className="flex flex-col gap-2">
        <span id={ids.group} className="text-sm font-medium text-fg">
          {copy.mcp.icon.choiceLabel}
        </span>
        <div
          role="radiogroup"
          aria-labelledby={ids.group}
          aria-readonly={readOnly || undefined}
          data-testid="mcp-icon-options"
          className="flex flex-col gap-3"
          onBlur={(e) => {
            if (!e.currentTarget.contains(e.relatedTarget)) onBlur();
          }}
        >
          <div className="flex flex-wrap gap-1.5">
            {head.map((o) =>
              radio(
                o.value === null
                  ? {
                      ...o,
                      content: (
                        <>
                          {o.content}
                          <span className="text-sm">{o.label}</span>
                        </>
                      ),
                    }
                  : o,
                o.value === null ? "gap-1.5 px-3" : "w-10",
              ),
            )}
          </div>
          {SECTIONS.map((s) => (
            <div key={s.group} role="group" aria-labelledby={`${ids.section}-${s.group}`} className="flex flex-col gap-1.5">
              <span id={`${ids.section}-${s.group}`} className="text-xs text-fg-muted">
                {copy.mcp.icon.groups[s.group]}
              </span>
              <div className="grid grid-cols-[repeat(auto-fill,minmax(2.5rem,1fr))] gap-1.5">{s.options.map((o) => radio(o))}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="flex max-w-80 flex-col gap-2">
        <Label htmlFor={ids.paste}>{copy.mcp.icon.pasteLabel}</Label>
        <Input
          id={ids.paste}
          value={text}
          readOnly={readOnly}
          autoComplete="off"
          spellCheck={false}
          maxLength={32}
          aria-invalid={invalid || undefined}
          aria-describedby={invalid ? `${ids.pasteHint} ${ids.pasteError}` : ids.pasteHint}
          className="mcp-emoji text-lg"
          onChange={(e) => {
            if (readOnly) return;
            const raw = e.target.value;
            setText(raw);
            const t = raw.trim();
            if (t === "") {
              setInvalid(false);
            } else if (isMcpEmoji(t)) {
              setInvalid(false);
              onChange(t);
            } else {
              setInvalid(true);
            }
          }}
        />
        <p id={ids.pasteHint} className="text-sm text-fg-muted">
          {copy.mcp.icon.pasteHint}
        </p>
        {invalid ? (
          <p id={ids.pasteError} className="text-sm text-danger">
            {copy.mcp.icon.invalid}
          </p>
        ) : null}
      </div>
    </div>
  );
}
