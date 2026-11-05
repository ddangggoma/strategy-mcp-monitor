import { CircleCheckIcon, CircleXIcon, ClockAlertIcon, TriangleAlertIcon, type LucideIcon } from "lucide-react";
import { copy } from "@/copy/ko";
import type { ActionRecord, ScriptStatus } from "@/lib/api-types";
import { cn } from "@/lib/utils";

const STATUS_ICON: Record<ScriptStatus, LucideIcon> = {
  ok: CircleCheckIcon,
  failed: CircleXIcon,
  timeout: ClockAlertIcon,
  error: TriangleAlertIcon,
};

/** A script result as icon + word; failures in fg weight, success muted (the eye goes to trouble). */
export function ActionResult({ status }: { status: ScriptStatus }) {
  const Icon = STATUS_ICON[status];
  return (
    <span className={cn("inline-flex items-center gap-1 whitespace-nowrap", status === "ok" ? "text-fg-muted" : "font-medium text-fg")}>
      <Icon aria-hidden="true" className="size-3.5" />
      {copy.mcp.scriptStatus[status]}
    </span>
  );
}

/** “시작”, or “다시 시작(종료 단계)” for a restart that fell back to stop + start (U9). */
export function actionKindLabel(a: Pick<ActionRecord, "requested" | "kind">): string {
  return a.requested === a.kind ? copy.mcp[a.kind] : copy.mcp.requestedStep(a.requested, a.kind);
}

/** The action's reason in words: an issue name, a known reason, else the raw value. */
export function reasonLabel(reason: string): string {
  if (Object.hasOwn(copy.issues, reason)) return copy.issues[reason as keyof typeof copy.issues];
  return Object.hasOwn(copy.mcp.reasons, reason) ? copy.mcp.reasons[reason]! : reason;
}
