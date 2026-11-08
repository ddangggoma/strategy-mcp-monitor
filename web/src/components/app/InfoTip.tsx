import { InfoIcon } from "lucide-react";
import { Popover as PopoverPrimitive } from "radix-ui";
import { useEffect, useId, useRef, useState, type PointerEvent } from "react";
import { createPortal } from "react-dom";
import { copy } from "@/copy/ko";
import { cn } from "@/lib/utils";

/** One help entry: a sentence, or a short lead and a list of terms with what they mean. */
export type HelpContent =
  | string
  | {
      readonly lead?: string;
      readonly items: readonly (readonly [term: string, meaning: string])[];
    };

/** The same help as one line of text (the description a screen reader hears on focus). */
export function helpText(content: HelpContent): string {
  if (typeof content === "string") return content;
  const items = content.items.map(([term, meaning]) => `${term}: ${meaning}`);
  return [content.lead, ...items].filter(Boolean).join(" ");
}

// The pointer has to rest a moment before a tip opens (crossing a form must not flash tips), and
// the tip waits a moment before closing so the pointer can move onto it (WCAG 1.4.13 hoverable).
const OPEN_DELAY_MS = 300;
const CLOSE_DELAY_MS = 150;

/**
 * A small “i” button next to a label that explains it (a toggletip). It opens when the mouse rests
 * on it, when it gets keyboard focus, and on click or tap (which pins it open: WebView2 and touch
 * have no hover). Escape, leaving it, a click elsewhere or moving focus away closes it. Focus never
 * moves into the tip, so the control it explains keeps its place in the tab order.
 *
 * The button is named “<label> 설명” and is always described by the help text: by a hidden copy
 * while closed, by the open tip itself while open. Place it beside a <label>, never inside one, so
 * clicking it does not activate the field and the field's name stays the label alone.
 */
export function InfoTip({
  label,
  content,
  side = "top",
  align = "center",
  className,
}: {
  /** The visible label this explains (the button is named “<label> 설명”). */
  label: string;
  content: HelpContent;
  side?: "top" | "right" | "bottom" | "left";
  align?: "start" | "center" | "end";
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const pinned = useRef(false);
  const fromPointer = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const button = useRef<HTMLButtonElement>(null);
  const tipId = useId();
  const descId = useId();

  const cancel = () => {
    if (timer.current !== undefined) clearTimeout(timer.current);
    timer.current = undefined;
  };
  const show = (pin: boolean) => {
    cancel();
    if (pin) pinned.current = true;
    setOpen(true);
  };
  const hide = () => {
    cancel();
    pinned.current = false;
    setOpen(false);
  };
  const later = (fn: () => void, ms: number) => {
    cancel();
    timer.current = setTimeout(fn, ms);
  };
  // the pointer left: close soon, unless a click pinned the tip or the keyboard is on the button
  const pointerOut = (e: PointerEvent) => {
    if (e.pointerType !== "mouse") return;
    if (pinned.current || document.activeElement === button.current) {
      cancel();
      return;
    }
    later(hide, CLOSE_DELAY_MS);
  };
  useEffect(() => cancel, []);

  const text = helpText(content);

  return (
    <PopoverPrimitive.Root
      open={open}
      onOpenChange={(next) => {
        if (!next) hide();
      }}
    >
      <PopoverPrimitive.Anchor asChild>
        <button
          ref={button}
          type="button"
          aria-label={copy.help.label(label)}
          aria-expanded={open}
          aria-controls={open ? tipId : undefined}
          aria-describedby={open ? tipId : descId}
          data-state={open ? "open" : "closed"}
          data-infotip=""
          className={cn(
            // a 24 px target around a 14 px icon; the negative margin keeps the label's line height
            "-my-1 inline-flex size-6 shrink-0 cursor-help items-center justify-center rounded-full align-middle text-fg-muted transition-colors duration-(--motion-fast) ease-hover hover:text-fg data-[state=open]:text-fg",
            className,
          )}
          onPointerEnter={(e) => {
            if (e.pointerType !== "mouse") return; // a tap arrives as a click
            if (open) cancel();
            else later(() => setOpen(true), OPEN_DELAY_MS);
          }}
          onPointerLeave={pointerOut}
          onPointerDown={() => {
            fromPointer.current = true;
          }}
          onFocus={() => {
            // keyboard focus opens the tip; a click's focus waits for the click (which pins it)
            if (!fromPointer.current) show(false);
            fromPointer.current = false;
          }}
          onBlur={hide}
          onClick={() => {
            fromPointer.current = false;
            if (open && pinned.current) hide();
            else show(true);
          }}
        >
          <InfoIcon aria-hidden="true" className="size-3.5" />
        </button>
      </PopoverPrimitive.Anchor>
      {/* in <body>, not beside the button: the description must not join the text of the
          label, heading or table header the button sits in */}
      {createPortal(
        <span id={descId} hidden>
          {text}
        </span>,
        document.body,
      )}
      <PopoverPrimitive.Portal>
        <PopoverPrimitive.Content
          id={tipId}
          role="tooltip"
          side={side}
          align={align}
          sideOffset={6}
          collisionPadding={8}
          data-anim="fade"
          onOpenAutoFocus={(e) => e.preventDefault()}
          onCloseAutoFocus={(e) => e.preventDefault()}
          onInteractOutside={(e) => {
            // the button toggles the tip itself
            if (e.target instanceof Node && button.current?.contains(e.target)) e.preventDefault();
          }}
          onPointerEnter={(e) => {
            if (e.pointerType === "mouse") cancel();
          }}
          onPointerLeave={pointerOut}
          className="z-(--z-popover) max-h-(--radix-popover-content-available-height) w-max max-w-[min(22rem,calc(100vw-1rem))] origin-(--radix-popover-content-transform-origin) animate-in overflow-y-auto rounded-md border border-border-strong bg-surface-raised px-3 py-2 text-sm leading-relaxed break-keep text-pretty text-fg shadow-md fade-in-0 zoom-in-95 duration-(--motion-fast) ease-out data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95"
        >
          <HelpBody content={content} />
        </PopoverPrimitive.Content>
      </PopoverPrimitive.Portal>
    </PopoverPrimitive.Root>
  );
}

function HelpBody({ content }: { content: HelpContent }) {
  if (typeof content === "string") return <p>{content}</p>;
  return (
    <div className="flex flex-col gap-2">
      {content.lead ? <p>{content.lead}</p> : null}
      <dl className="flex flex-col gap-1.5">
        {content.items.map(([term, meaning]) => (
          <div key={term}>
            <dt className="font-semibold">{term}</dt>
            <dd className="text-fg-muted">{meaning}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
