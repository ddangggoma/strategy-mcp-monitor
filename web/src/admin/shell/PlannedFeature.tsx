import { HourglassIcon } from "lucide-react";
import { copy } from "@/copy/ko";
import type { PlannedReason } from "./Nav";

/**
 * A feature whose data arrives in a later plan (U13): one quiet sentence, no fake numbers,
 * charts or skeletons that would suggest data is loading.
 */
export function PlannedFeature({ reason }: { reason: PlannedReason }) {
  return (
    <div data-planned={reason} className="flex items-start gap-3 rounded-md border bg-surface px-4 py-3 text-sm text-fg-muted">
      <HourglassIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
      <p>{copy.deny[reason]}</p>
    </div>
  );
}
