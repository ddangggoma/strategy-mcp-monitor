import { useId } from "react";
import { useFormState } from "react-hook-form";
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
import { copy } from "@/copy/ko";
import type { RetentionPreview } from "@/lib/api-types";
import { formatBytes } from "@/lib/time";
import { useRetentionPreview } from "../queries";
import { NumberField, type SettingsControl } from "./NumberField";
import { RETENTION_KEYS } from "./settings-schema";

/**
 * Retention days and compress-after days, plus how much log there is now (the preview for the
 * saved value). When compression would start after deletion both inputs are marked and one
 * sentence under the pair says to fix them together.
 */
export function RetentionSection({
  control,
  readOnly,
  savedDays,
}: {
  control: SettingsControl;
  readOnly: boolean;
  /** The saved retention value: what the current usage is measured against. */
  savedDays: number;
}) {
  const sharedId = useId();
  const { errors } = useFormState({ control, name: [...RETENTION_KEYS] });
  const together = RETENTION_KEYS.some((k) => errors[k]?.message === copy.settings.retentionBelowCompress);
  const shared = { id: sharedId, message: copy.settings.retentionBelowCompress };

  return (
    <>
      <NumberField control={control} name="log_retention_days" readOnly={readOnly} hint={copy.settings.retentionRange} shared={shared} />
      <NumberField control={control} name="log_compress_after_days" readOnly={readOnly} hint={copy.settings.compressHint} shared={shared} />
      {together ? (
        <p id={sharedId} className="text-sm text-danger @lg:col-span-2">
          {copy.settings.retentionBelowCompress}
        </p>
      ) : null}
      <CurrentUsage days={savedDays} />
    </>
  );
}

function CurrentUsage({ days }: { days: number }) {
  const { data, isError } = useRetentionPreview(days);
  let body;
  if (isError) body = <p>{copy.settings.usageError}</p>;
  else if (!data) body = <p role="status">{copy.common.loading}</p>;
  else if (data.total_files === 0) body = <p>{copy.settings.noLogs}</p>;
  else {
    body = (
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
        <dt>{copy.settings.currentLogs}</dt>
        <dd className="text-fg tabular-nums">{copy.settings.currentUsage(data.total_files, formatBytes(data.total_bytes))}</dd>
        {data.oldest_date ? (
          <>
            <dt>{copy.settings.oldest}</dt>
            <dd className="text-fg tabular-nums">{data.oldest_date}</dd>
          </>
        ) : null}
      </dl>
    );
  }
  return <div className="text-sm text-fg-muted @lg:col-span-2">{body}</div>;
}

export interface RetentionChange {
  from: number;
  to: number;
  preview: RetentionPreview;
}

/**
 * The confirm shown before a lower retention is saved: the period, file count and size that the
 * new value deletes, in large figures (the one bold element of these screens). Nothing is sent
 * until the person confirms. `change` is kept while the dialog closes so its exit can play.
 */
export function RetentionConfirm({
  change,
  open,
  onCancel,
  onConfirm,
  returnFocus,
}: {
  change: RetentionChange | null;
  open: boolean;
  onCancel: () => void;
  onConfirm: () => void;
  /** Opened by state, not a Radix trigger: where focus goes when it closes (the save button). */
  returnFocus: () => void;
}) {
  if (!change) return null;
  const { from, to, preview } = change;
  const none = preview.delete_files === 0;
  const s = copy.settings;

  return (
    <AlertDialog
      open={open}
      onOpenChange={(o) => {
        if (!o) onCancel();
      }}
    >
      <AlertDialogContent
        onCloseAutoFocus={(e) => {
          e.preventDefault();
          returnFocus();
        }}
      >
        <AlertDialogHeader>
          <AlertDialogTitle>{none ? s.confirmReduceTitle : s.confirmDeleteTitle}</AlertDialogTitle>
          <AlertDialogDescription>{none ? s.confirmBodyNone(from, to) : s.confirmBody(from, to)}</AlertDialogDescription>
        </AlertDialogHeader>
        <dl className="grid grid-cols-[auto_1fr] items-baseline gap-x-6 gap-y-2 text-sm">
          <dt className="text-fg-muted">{s.deleteRange}</dt>
          <dd className="text-lg font-semibold text-fg tabular-nums">
            {none || !preview.delete_from || !preview.delete_to ? s.noDelete : `${preview.delete_from} – ${preview.delete_to}`}
          </dd>
          {none ? null : (
            <>
              <dt className="text-fg-muted">{s.deleteFiles}</dt>
              <dd className="text-lg font-semibold text-fg tabular-nums">{s.filesCount(preview.delete_files)}</dd>
              <dt className="text-fg-muted">{s.deleteSize}</dt>
              <dd className="text-lg font-semibold text-fg tabular-nums">{formatBytes(preview.delete_bytes)}</dd>
            </>
          )}
        </dl>
        <div className="flex flex-col gap-1 text-sm text-fg-muted">
          {/* the log index rows of those days go with them (null: the index cannot tell yet) */}
          {!none && typeof preview.delete_events === "number" ? <p>{s.retentionDeleteEvents(preview.delete_events)}</p> : null}
          <p>{s.retentionRunsSoon}</p>
        </div>
        <AlertDialogFooter>
          <AlertDialogCancel>{copy.common.cancel}</AlertDialogCancel>
          <AlertDialogAction variant={none ? "default" : "destructive"} onClick={onConfirm}>
            {none ? s.confirmReduce : s.confirmDelete}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
