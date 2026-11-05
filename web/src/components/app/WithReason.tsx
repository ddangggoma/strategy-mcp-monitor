import {
  cloneElement,
  useId,
  useState,
  type HTMLAttributes,
  type KeyboardEvent,
  type ReactElement,
  type SyntheticEvent,
} from "react";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { copy, type DisabledReason } from "@/copy/ko";

type ChildProps = HTMLAttributes<HTMLElement>;

function block(e: SyntheticEvent): void {
  e.preventDefault();
  e.stopPropagation();
}

function blockActivation(e: KeyboardEvent<HTMLElement>): void {
  if (e.key === "Enter" || e.key === " ") block(e);
}

/**
 * A control the user cannot use right now, kept visible with its reason (§4.4, U26): instead of
 * `disabled` (unfocusable, no tooltip), the child gets aria-disabled, stays in the tab order,
 * ignores clicks and Enter/Space, and explains itself twice — a tooltip on hover and focus, and
 * an always-present description for screen readers. Without a reason the child works normally
 * (with `label`, its tooltip still names it).
 *
 * The element tree is the same with and without a reason, so a reason that comes or goes (a save
 * that leaves nothing to save, an action that starts running) never remounts the control and
 * never drops the keyboard focus on <body>.
 */
export function WithReason({
  reason,
  children,
  side,
  label,
}: {
  reason: DisabledReason | null;
  children: ReactElement<ChildProps>;
  /** Tooltip side (default top); a sidebar item uses right so the tip does not cover its neighbours. */
  side?: "top" | "right" | "bottom" | "left";
  /** Shown above the reason in the tooltip, for a control whose own text is not visible (icon rail). */
  label?: string;
}) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const text = reason === null ? null : copy.deny[reason];
  const hasTip = text !== null || label !== undefined;

  const trigger =
    text === null
      ? children
      : cloneElement(children, {
          "aria-disabled": true,
          "aria-describedby": [children.props["aria-describedby"], id].filter(Boolean).join(" "),
          onClick: block,
          onKeyDown: blockActivation,
        });

  return (
    <>
      <TooltipProvider>
        <Tooltip open={hasTip && open} onOpenChange={setOpen}>
          <TooltipTrigger asChild>{trigger}</TooltipTrigger>
          {hasTip ? (
            <TooltipContent side={side}>
              {/* Both parts are for the eye only. The label is already the control's name, and the
                  reason is read from the hidden description below: Radix also points the trigger's
                  aria-describedby at an open tooltip, which would read the reason twice. */}
              {label ? (
                <span aria-hidden="true" className={text === null ? undefined : "block font-semibold"}>
                  {label}
                </span>
              ) : null}
              {text === null ? null : <span aria-hidden="true">{text}</span>}
            </TooltipContent>
          ) : null}
        </Tooltip>
      </TooltipProvider>
      {text === null ? null : (
        <span id={id} hidden>
          {text}
        </span>
      )}
    </>
  );
}
