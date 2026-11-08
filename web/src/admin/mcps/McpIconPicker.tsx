import { ImageUpIcon, XIcon } from "lucide-react";
import { useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { useWatch, type Control } from "react-hook-form";
import { InfoTip } from "@/components/app/InfoTip";
import { WithReason } from "@/components/app/WithReason";
import { McpIcon } from "@/components/status/McpIcon";
import { Button } from "@/components/ui/button";
import { FormField, FormItem, FormMessage } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { copy, messageForError, type DisabledReason } from "@/copy/ko";
import { ApiError } from "@/lib/api";
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

/** What the picker needs for the uploaded logo; its owner (settings tab or registration page) stores it. */
export interface IconImageProps {
  /** What the preview draws: the stored image's URL, a data: URL of a file held for later, or null. */
  src: string | null;
  /** An upload or removal is in flight. */
  busy: boolean;
  /** Why the image cannot be changed (permissions), or null. */
  reason: DisabledReason | null;
  /** The last upload or removal failed: what to tell the person. */
  error: string | null;
  /** A file that passed the client checks, typed with its image type (see `iconImageBlob`). */
  onPick(file: Blob): void;
  onRemove(): void;
}

// the types the server accepts (app/monitor/icon_images.py); a file without a type is known by its extension
const IMAGE_TYPES: Record<string, string> = {
  "image/png": "image/png",
  "image/jpeg": "image/jpeg",
  "image/webp": "image/webp",
  "image/gif": "image/gif",
  "image/x-icon": "image/x-icon",
  "image/vnd.microsoft.icon": "image/x-icon",
  "image/svg+xml": "image/svg+xml",
};
const EXTENSIONS: Record<string, string> = {
  png: "image/png",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  webp: "image/webp",
  gif: "image/gif",
  ico: "image/x-icon",
  svg: "image/svg+xml",
};
const ACCEPT = [...Object.keys(IMAGE_TYPES), ...Object.keys(EXTENSIONS).map((e) => `.${e}`)].join(",");
/** Same as the server's MAX_BYTES. */
export const MAX_ICON_IMAGE_BYTES = 256 * 1024;

/** The file as the server wants it (its image type as the blob type), or the reason it cannot be one. */
export function iconImageBlob(file: File): { blob: Blob } | { error: string } {
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  const type = IMAGE_TYPES[file.type.toLowerCase()] ?? (file.type === "" ? EXTENSIONS[ext] : undefined);
  if (type === undefined) return { error: copy.mcp.icon.imageWrongType };
  if (file.size > MAX_ICON_IMAGE_BYTES) return { error: copy.mcp.icon.imageTooLarge };
  return { blob: file.type === type ? file : new Blob([file], { type }) };
}

/** What to say when the server refused an upload. */
export function iconImageErrorMessage(err: unknown): string {
  const code = err instanceof ApiError ? err.code : "internal";
  if (code === "body_too_large") return copy.mcp.icon.imageTooLarge;
  if (code === "validation") return copy.mcp.icon.imageRejected;
  return messageForError(code);
}

/**
 * The MCP's icon: an uploaded logo, one emoji or the default MCP icon, with a live preview of the
 * board card's header (image before emoji before default). The logo is chosen with a file button
 * and saved by the picker's owner (at once in the settings, after creation on the registration
 * page). The ready-made emoji are one radio group in sections (WAI-ARIA radio pattern: one Tab
 * stop, arrow keys move and select, Home/End jump to the ends); any other emoji can be pasted and
 * is checked as it is typed, by the same rules as the server. Read-only keeps it focusable but
 * unchangeable.
 */
export function McpIconPicker({
  control,
  readOnly,
  image,
}: {
  control: Control<McpFormValues, unknown, McpConfig>;
  readOnly: boolean;
  image?: IconImageProps;
}) {
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
          <McpIcon icon={icon} image={image?.src} />
          <span className={cn("min-w-0 truncate text-lg leading-tight font-semibold", name?.trim() ? "text-fg" : "text-fg-muted")}>
            {name?.trim() || copy.mcp.icon.previewName}
          </span>
        </div>
      </figure>

      {image ? <ImageChoice image={image} readOnly={readOnly} /> : null}

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

/**
 * The logo: a file button ("이미지 올리기"), "이미지 제거" when there is one, and the
 * rules behind an InfoTip. The file is checked here (type, size) before the owner gets it; the
 * server checks the rest (magic bytes, pixel size, SVG content). Without permission the buttons stay
 * focusable and say why (WithReason).
 */
function ImageChoice({ image, readOnly }: { image: IconImageProps; readOnly: boolean }) {
  const ids = { label: useId(), hint: useId(), error: useId() };
  const input = useRef<HTMLInputElement>(null);
  const [localError, setLocalError] = useState<string | null>(null);
  const blocked = readOnly || image.busy;
  const error = localError ?? image.error;
  const has = image.src !== null;

  const pick = (file: File | undefined) => {
    if (!file) return;
    const checked = iconImageBlob(file);
    if ("error" in checked) {
      setLocalError(checked.error);
      return;
    }
    setLocalError(null);
    image.onPick(checked.blob);
  };

  return (
    <div role="group" aria-labelledby={ids.label} className="flex min-w-0 flex-col gap-2">
      <div className="flex items-center gap-1">
        <span id={ids.label} className="text-sm font-medium text-fg">
          {copy.mcp.icon.image}
        </span>
        <InfoTip label={copy.mcp.icon.image} content={copy.help.mcp.iconImage} />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <WithReason reason={image.reason}>
          <Button
            variant="outline"
            size="sm"
            aria-disabled={blocked || undefined}
            aria-describedby={error ? `${ids.hint} ${ids.error}` : ids.hint}
            onClick={() => {
              if (!blocked) input.current?.click();
            }}
          >
            <ImageUpIcon aria-hidden="true" />
            {copy.mcp.icon.imageUpload}
          </Button>
        </WithReason>
        {has ? (
          <WithReason reason={image.reason}>
            <Button
              variant="ghost"
              size="sm"
              aria-disabled={blocked || undefined}
              onClick={() => {
                if (blocked) return;
                setLocalError(null);
                image.onRemove();
              }}
            >
              <XIcon aria-hidden="true" />
              {copy.mcp.icon.imageRemove}
            </Button>
          </WithReason>
        ) : null}
        {/* the button above opens it; hidden from the tab order and from assistive tech */}
        <input
          ref={input}
          type="file"
          accept={ACCEPT}
          hidden
          tabIndex={-1}
          aria-hidden="true"
          data-testid="mcp-icon-file"
          onChange={(e) => {
            pick(e.target.files?.[0]);
            e.target.value = ""; // the same file can be picked again
          }}
        />
      </div>
      <p id={ids.hint} className="text-sm text-fg-muted">
        {copy.mcp.icon.imageHint}
      </p>
      {image.busy ? (
        <p role="status" className="text-sm text-fg-muted">
          {copy.common.saving}
        </p>
      ) : null}
      {error ? (
        <p id={ids.error} role="alert" className="text-sm text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}
