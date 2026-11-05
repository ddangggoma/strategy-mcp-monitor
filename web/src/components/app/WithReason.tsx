import {
  cloneElement,
  useId,
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
 * an always-present description for screen readers. Without a reason the child is returned as is.
 */
export function WithReason({ reason, children }: { reason: DisabledReason | null; children: ReactElement<ChildProps> }) {
  const id = useId();
  if (reason === null) return children;

  const text = copy.deny[reason];
  const describedBy = [children.props["aria-describedby"], id].filter(Boolean).join(" ");
  const trigger = cloneElement(children, {
    "aria-disabled": true,
    "aria-describedby": describedBy,
    onClick: block,
    onKeyDown: blockActivation,
  });

  return (
    <>
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>{trigger}</TooltipTrigger>
          <TooltipContent>{text}</TooltipContent>
        </Tooltip>
      </TooltipProvider>
      <span id={id} hidden>
        {text}
      </span>
    </>
  );
}
