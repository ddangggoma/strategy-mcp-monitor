import { PlayIcon, RotateCwIcon, SquareIcon, type LucideIcon } from "lucide-react";
import { useRef, useState } from "react";
import { toast } from "sonner";
import { WithReason } from "@/components/app/WithReason";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { copy, messageForError, type DisabledReason } from "@/copy/ko";
import { trackerTimeoutMs } from "@/lib/action-tracker";
import { ApiError } from "@/lib/api";
import type { McpDetail, ScriptKind } from "@/lib/api-types";
import { denyReason } from "@/lib/permissions";
import { useSession } from "@/lib/session";
import { useLive } from "../live";
import { useManualAction } from "../queries";

const KINDS: readonly { kind: ScriptKind; icon: LucideIcon }[] = [
  { kind: "start", icon: PlayIcon },
  { kind: "restart", icon: RotateCwIcon },
  { kind: "stop", icon: SquareIcon },
];

/**
 * Start / restart / stop for one MCP. Unavailable buttons stay visible with their reason (U26):
 * permission first, then a script already running, then a broken saved config. Stop asks first,
 * because it also turns maintenance on and so pauses automatic recovery. A 202 hands the run id to
 * the tab's ActionTracker, which owns the toast from then on. Size sm (table rows) shows icon buttons
 * whose names live in aria-label and a tooltip, so the column stays narrow.
 */
export function McpActions({ mcp, size = "md" }: { mcp: McpDetail; size?: "sm" | "md" }) {
  const me = useSession();
  const { tracker } = useLive();
  const action = useManualAction();
  const [busy, setBusy] = useState<ScriptKind | null>(null);
  const [confirmStop, setConfirmStop] = useState(false);
  const stopButton = useRef<HTMLButtonElement>(null);
  // sm (table rows): icon buttons named by aria-label, the name shown in a tooltip
  const compact = size === "sm";

  const reason: DisabledReason | null =
    denyReason(me, "mcp_manual_action", mcp.owner?.id ?? null) ??
    (mcp.live?.running ? "running" : null) ??
    (mcp.config_error ? "config_error" : null);

  const run = (kind: ScriptKind) => {
    if (busy) return;
    setBusy(kind);
    action.mutate(
      { id: mcp.id, kind },
      {
        onSuccess: ({ run_id }) => {
          tracker?.track({
            runId: run_id,
            mcpId: mcp.id,
            mcpName: mcp.name,
            requested: kind,
            timeoutMs: trackerTimeoutMs(mcp.script_timeout_sec),
          });
        },
        onError: (err) => {
          toast.error(messageForError(err instanceof ApiError ? err.code : "internal"));
        },
        onSettled: () => setBusy(null),
      },
    );
  };

  return (
    <TooltipProvider>
      <div role="group" aria-label={copy.mcp.actionsLabel(mcp.name)} className="flex items-center gap-1.5">
        {KINDS.map(({ kind, icon: Icon }) => {
          const label = copy.mcp[kind];
          const button = (
            <Button
              variant={kind === "stop" ? "outline" : "secondary"}
              size={compact ? "icon-sm" : "default"}
              aria-label={compact ? label : undefined}
              ref={kind === "stop" ? stopButton : undefined}
              aria-busy={busy === kind ? true : undefined}
              onClick={() => (kind === "stop" ? setConfirmStop(true) : run(kind))}
            >
              <Icon aria-hidden="true" />
              {compact ? null : label}
            </Button>
          );
          if (reason !== null || !compact) {
            // a compact button's name is not visible: the reason tooltip shows it too
            return (
              <WithReason key={kind} reason={reason} label={compact ? label : undefined}>
                {button}
              </WithReason>
            );
          }
          return (
            <Tooltip key={kind}>
              <TooltipTrigger asChild>{button}</TooltipTrigger>
              <TooltipContent>
                <span aria-hidden="true">{label}</span>
              </TooltipContent>
            </Tooltip>
          );
        })}
        <AlertDialog open={confirmStop} onOpenChange={setConfirmStop}>
          <AlertDialogContent
            onCloseAutoFocus={(e) => {
              // the dialog is opened by state, not a Radix trigger: hand focus back to the stop button
              e.preventDefault();
              stopButton.current?.focus();
            }}
          >
            <AlertDialogHeader>
              <AlertDialogTitle>{copy.mcp.stopConfirmTitle(mcp.name)}</AlertDialogTitle>
              <AlertDialogDescription>{copy.mcp.stopConfirm}</AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>{copy.common.cancel}</AlertDialogCancel>
              <AlertDialogAction variant="destructive" onClick={() => run("stop")}>
                {copy.mcp.stop}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>
    </TooltipProvider>
  );
}
