import { useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import { toast } from "sonner";
import { TextDiff } from "@/components/app/TextDiff";
import { WithReason } from "@/components/app/WithReason";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter,
  AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { copy, messageForError } from "@/copy/ko";
import { ApiError } from "@/lib/api";
import type { ScriptKind, ScriptVersion } from "@/lib/api-types";
import { revertScript } from "@/lib/endpoints";
import type { DenyReason } from "@/lib/permissions";
import { formatKst } from "@/lib/time";
import { useScriptVersion, useScriptVersions } from "../queries";
import { qk } from "../query-keys";

export interface VersionListProps {
  mcpId: number;
  kind: ScriptKind;
  /** The script as it is now on the server; null when this kind has no script. */
  current: { version: number; content: string } | null;
  /** Why this person may not revert (null = owner on the local channel). */
  revertReason: DenyReason | null;
}

/**
 * Version history of one script, newest first. Picking a version shows its line diff against the
 * current script; the owner can publish it again as a new version ("revert", with confirmation).
 * A deletion is a version too: marked “삭제됨”, nothing to compare and nothing to revert to.
 */
export function VersionList({ mcpId, kind, current, revertReason }: VersionListProps) {
  const versions = useScriptVersions(mcpId, kind);
  const [selected, setSelected] = useState<number | null>(null);
  const headingId = useId();
  const picked = versions.data?.find((v) => v.version === selected) ?? null;

  return (
    <section aria-labelledby={headingId} className="@container flex min-w-0 flex-col gap-3 border-t border-border pt-4">
      <h3 id={headingId} className="text-sm font-semibold text-fg">
        {copy.scripts.versions}
      </h3>
      {versions.isPending ? (
        <div role="status" className="flex flex-col gap-2">
          <span className="sr-only">{copy.common.loading}</span>
          <Skeleton className="h-10 w-full max-w-72" />
          <Skeleton className="h-10 w-full max-w-72" />
        </div>
      ) : versions.isError ? (
        <p role="alert" className="text-sm text-fg">
          {copy.scripts.versionsError}
        </p>
      ) : versions.data.length === 0 ? (
        <p className="text-sm text-fg-muted">{copy.scripts.noVersions}</p>
      ) : (
        <div className="grid min-w-0 gap-4 @3xl:grid-cols-[16rem_minmax(0,1fr)]">
          <ul aria-label={copy.scripts.versions} className="flex max-h-[60vh] flex-col gap-1 overflow-auto">
            {versions.data.map((v) => (
              <li key={v.version}>
                <VersionButton
                  v={v}
                  current={current?.version === v.version}
                  pressed={selected === v.version}
                  onPick={() => setSelected(v.version)}
                />
              </li>
            ))}
          </ul>
          <div className="min-w-0">
            {picked ? (
              <VersionDetail
                key={picked.version}
                mcpId={mcpId}
                kind={kind}
                v={picked}
                current={current}
                revertReason={revertReason}
              />
            ) : (
              <p className="text-sm text-fg-muted">{copy.scripts.pickVersion}</p>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

function VersionButton({ v, current, pressed, onPick }: { v: ScriptVersion; current: boolean; pressed: boolean; onPick(): void }) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onPick}
      className="flex w-full flex-col items-start gap-0.5 rounded-md px-3 py-2 text-left text-sm transition-[background-color] duration-(--motion-fast) ease-hover hover:bg-hover aria-pressed:bg-selected"
    >
      <span className="flex flex-wrap items-center gap-2">
        <span className="font-semibold text-fg">{copy.scripts.versionLabel(v.version)}</span>
        {current ? (
          <span className="rounded-sm border border-border-strong px-1.5 text-xs text-fg">{copy.scripts.current}</span>
        ) : null}
        {v.deleted ? (
          <span className="rounded-sm border border-dashed border-border-strong px-1.5 text-xs text-fg-muted">{copy.scripts.deletedTag}</span>
        ) : v.ext ? (
          <span className="font-mono text-xs text-fg-muted">{v.ext}</span>
        ) : null}
      </span>
      <span className="text-xs text-fg-muted">
        {v.author?.name ?? copy.scripts.systemAuthor} <span data-volatile>{formatKst(v.created_at)}</span>
      </span>
    </button>
  );
}

function VersionDetail({ mcpId, kind, v, current, revertReason }: { v: ScriptVersion } & Omit<VersionListProps, "kind"> & { kind: ScriptKind }) {
  const isCurrent = current?.version === v.version;
  const content = useScriptVersion(mcpId, kind, v.version, { enabled: !v.deleted && !isCurrent });
  const noteId = useId();
  const label = copy.scripts.versionLabel(v.version);

  // why this version cannot be reverted to, besides permission
  const note = v.deleted ? copy.scripts.deletedNote : isCurrent ? copy.scripts.currentNote : null;

  return (
    <div className="flex min-w-0 flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-sm font-semibold text-fg">{label}</h4>
        {revertReason !== null ? (
          <WithReason reason={revertReason}>
            <Button variant="outline" size="sm">
              {copy.scripts.revert}
            </Button>
          </WithReason>
        ) : note !== null ? (
          <Button variant="outline" size="sm" aria-disabled={true} aria-describedby={noteId} onClick={(e) => e.preventDefault()}>
            {copy.scripts.revert}
          </Button>
        ) : (
          <RevertDialog mcpId={mcpId} kind={kind} version={v.version} />
        )}
      </div>
      {note !== null ? (
        <p id={noteId} className="text-sm text-fg-muted">
          {note}
        </p>
      ) : content.isPending ? (
        <div role="status">
          <span className="sr-only">{copy.common.loading}</span>
          <Skeleton className="h-40 w-full" />
        </div>
      ) : content.isError || content.data.content === null ? (
        <p role="alert" className="text-sm text-fg">
          {copy.scripts.versionError}
        </p>
      ) : (
        <TextDiff before={content.data.content} after={current?.content ?? ""} labels={[label, copy.scripts.current]} />
      )}
    </div>
  );
}

function RevertDialog({ mcpId, kind, version }: { mcpId: number; kind: ScriptKind; version: number }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const confirm = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const s = await revertScript(mcpId, kind, version);
      await Promise.all([
        qc.invalidateQueries({ queryKey: qk.script(mcpId, kind), exact: true }),
        qc.invalidateQueries({ queryKey: qk.scriptVersions(mcpId, kind) }),
        qc.invalidateQueries({ queryKey: qk.scripts(mcpId) }),
      ]);
      toast.success(copy.scripts.reverted(version, s.version));
      setOpen(false);
    } catch (err) {
      const code = err instanceof ApiError ? err.code : "internal";
      if (code !== "login_required") setError(messageForError(code));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AlertDialog
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (o) setError(null);
      }}
    >
      <AlertDialogTrigger asChild>
        <Button variant="outline" size="sm">
          {copy.scripts.revert}
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{copy.scripts.revertTitle(version)}</AlertDialogTitle>
          <AlertDialogDescription>{copy.scripts.revertBody}</AlertDialogDescription>
        </AlertDialogHeader>
        {error ? (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        ) : null}
        <AlertDialogFooter>
          <AlertDialogCancel>{copy.common.cancel}</AlertDialogCancel>
          <AlertDialogAction
            aria-disabled={busy || undefined}
            onClick={(e) => {
              e.preventDefault(); // stay open until the request settles
              void confirm();
            }}
          >
            {busy ? copy.scripts.reverting : copy.scripts.revertAction}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
