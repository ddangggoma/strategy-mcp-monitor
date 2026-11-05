import { useQueryClient } from "@tanstack/react-query";
import { getRouteApi } from "@tanstack/react-router";
import { LockIcon, Trash2Icon } from "lucide-react";
import { lazy, Suspense, useId, useState } from "react";
import { toast } from "sonner";
import { WithReason } from "@/components/app/WithReason";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter,
  AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { copy, messageForError } from "@/copy/ko";
import { ApiError } from "@/lib/api";
import type { McpDetail, ScriptContent, ScriptKind, ScriptListItem } from "@/lib/api-types";
import { clearDraft, loadDraft } from "@/lib/draft";
import { deleteScript } from "@/lib/endpoints";
import { denyReason, type DenyReason } from "@/lib/permissions";
import { useSession } from "@/lib/session";
import { formatKst } from "@/lib/time";
import { useScript, useScripts } from "../queries";
import { qk } from "../query-keys";
import { ScriptViewer } from "./ScriptViewer";
import { VersionList } from "./VersionList";

// CodeMirror is its own chunk: only the owner on the local channel ever downloads it (U18)
const ScriptEditor = lazy(() => import("./ScriptEditor").then((m) => ({ default: m.ScriptEditor })));

const route = getRouteApi("/authed/admin/mcps/$mcpId");
const KINDS: readonly ScriptKind[] = ["start", "stop", "restart"];

/** A restart script that does not exist yet, opened for writing. */
const emptyScript = (kind: ScriptKind): ScriptContent => ({ kind, ext: ".ps1", version: 0, sha256: "", content: "", editable: true });

/**
 * Scripts of one MCP (local channel only: they run as SYSTEM). On the external channel the tab only
 * says why and requests nothing (a 404 there would read as "no scripts"). The kind is kept in
 * `?kind=`. The owner edits in CodeMirror; everybody else reads a <pre> and sees why they cannot edit.
 */
export function ScriptsTab({ mcp, onDirtyChange }: { mcp: McpDetail; onDirtyChange?: (dirty: boolean) => void }) {
  const me = useSession();
  const viewReason = denyReason(me, "view_scripts");
  if (viewReason !== null) {
    return (
      <div className="flex max-w-(--size-prose) items-start gap-3 rounded-md border bg-surface px-4 py-3 text-sm text-fg-muted">
        <LockIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
        <p>{copy.deny[viewReason]}</p>
      </div>
    );
  }
  return <Scripts mcp={mcp} onDirtyChange={onDirtyChange} />;
}

function Scripts({ mcp, onDirtyChange }: { mcp: McpDetail; onDirtyChange?: (dirty: boolean) => void }) {
  const me = useSession();
  const { kind = "start" } = route.useSearch();
  const navigate = route.useNavigate();
  const list = useScripts(mcp.id);
  const editReason = denyReason(me, "edit_scripts", mcp.owner?.id ?? null);

  const exists = (k: ScriptKind) => list.data?.some((s) => s.kind === k) ?? true;

  return (
    <div className="flex min-w-0 flex-col gap-5">
      <div role="group" aria-label={copy.scripts.kindsLabel} className="inline-flex w-fit max-w-full flex-wrap rounded-md border border-border-strong p-0.5">
        {KINDS.map((k) => (
          <button
            key={k}
            type="button"
            aria-pressed={k === kind}
            onClick={() => void navigate({ search: (s) => ({ ...s, kind: k }), replace: true })}
            className="h-(--size-control-sm) rounded-sm px-3 text-sm text-fg-muted transition-[background-color,color] duration-(--motion-fast) ease-hover hover:text-fg aria-pressed:bg-selected aria-pressed:font-semibold aria-pressed:text-fg"
          >
            {copy.scripts.kinds[k]}
            {exists(k) ? null : <span className="font-normal text-fg-muted">{` ${copy.scripts.missing}`}</span>}
          </button>
        ))}
      </div>

      {list.isPending ? (
        <div role="status" className="flex flex-col gap-3">
          <span className="sr-only">{copy.common.loading}</span>
          <Skeleton className="h-6 w-48" />
          <Skeleton className="h-48 w-full" />
        </div>
      ) : list.isError ? (
        <p role="alert" className="text-sm text-fg">
          {copy.scripts.loadError}
        </p>
      ) : (
        // keyed by kind: each kind starts with its own state (adding, selected version)
        <KindPane
          key={kind}
          mcpId={mcp.id}
          kind={kind}
          item={list.data.find((s) => s.kind === kind) ?? null}
          editReason={editReason}
          onDirtyChange={onDirtyChange}
        />
      )}
    </div>
  );
}

interface KindPaneProps {
  mcpId: number;
  kind: ScriptKind;
  /** This kind in the script list; null when the MCP has no such script. */
  item: ScriptListItem | null;
  editReason: DenyReason | null;
  onDirtyChange?: (dirty: boolean) => void;
}

function KindPane({ mcpId, kind, item, editReason, onDirtyChange }: KindPaneProps) {
  const qc = useQueryClient();
  const headingId = useId();
  const script = useScript(mcpId, kind, { enabled: item !== null });
  // a draft for a script that does not exist yet reopens the editor so it can be restored
  const [adding, setAdding] = useState(() => item === null && editReason === null && loadDraft(`script:${mcpId}:${kind}`) !== null);

  const invalidate = () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: qk.scripts(mcpId) }),
      qc.invalidateQueries({ queryKey: qk.script(mcpId, kind), exact: true }),
      qc.invalidateQueries({ queryKey: qk.scriptVersions(mcpId, kind) }),
    ]);

  // drop it from the list first: the script query turns off instead of refetching a 404
  const removeRestart = () => {
    qc.setQueryData<ScriptListItem[]>(qk.scripts(mcpId), (l) => l?.filter((s) => s.kind !== kind));
    qc.removeQueries({ queryKey: qk.script(mcpId, kind), exact: true });
    return Promise.all([
      qc.invalidateQueries({ queryKey: qk.scripts(mcpId) }),
      qc.invalidateQueries({ queryKey: qk.scriptVersions(mcpId, kind) }),
    ]);
  };

  // one editor position for "adding" and "existing": saving a new restart script keeps the same editor
  const editorInitial = script.data?.editable ? script.data : item === null && adding ? emptyScript(kind) : null;
  const current = item !== null && script.data ? { version: script.data.version, content: script.data.content } : null;

  return (
    <section aria-labelledby={headingId} className="flex min-w-0 flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="flex min-w-0 flex-col gap-0.5">
          <h2 id={headingId} className="text-base font-semibold text-fg">
            {copy.scripts.kinds[kind]}
          </h2>
          {item ? (
            <p className="flex flex-wrap gap-x-3 text-xs text-fg-muted">
              <span className="font-mono">{item.ext}</span>
              <span>{copy.scripts.versionLabel(item.version)}</span>
              <span>
                {copy.scripts.lastSaved} {item.updated_by_user?.name ?? copy.scripts.systemAuthor}{" "}
                <span data-volatile>{formatKst(item.updated_at)}</span>
              </span>
            </p>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {script.data && !script.data.editable ? (
            <WithReason reason={editReason}>
              {/* allowed but not editable means the server's view changed (ownership): ask again */}
              <Button variant="outline" onClick={() => void qc.invalidateQueries({ queryKey: qk.script(mcpId, kind), exact: true })}>
                {copy.scripts.edit}
              </Button>
            </WithReason>
          ) : null}
          {kind === "restart" && item !== null ? (
            <DeleteRestart mcpId={mcpId} reason={editReason} onDeleted={removeRestart} />
          ) : null}
        </div>
      </div>

      {item === null && !adding ? (
        <div className="flex max-w-(--size-prose) flex-col items-start gap-3 rounded-md border border-dashed border-border-strong px-4 py-3 text-sm">
          <div className="flex flex-col gap-0.5">
            <p className="text-fg">{kind === "restart" ? copy.scripts.noRestart : copy.scripts.loadError}</p>
            {kind === "restart" ? <p className="text-fg-muted">{copy.scripts.optionalRestart}</p> : null}
          </div>
          <WithReason reason={editReason}>
            <Button variant="outline" onClick={() => setAdding(true)}>
              {copy.scripts.addRestart}
            </Button>
          </WithReason>
        </div>
      ) : editorInitial ? (
        <Suspense fallback={<EditorSkeleton />}>
          <ScriptEditor
            mcpId={mcpId}
            kind={kind}
            initial={editorInitial}
            onSaved={() => void invalidate()}
            onDirtyChange={onDirtyChange}
          />
        </Suspense>
      ) : script.isError ? (
        <p role="alert" className="text-sm text-fg">
          {copy.scripts.loadError}
        </p>
      ) : script.data ? (
        <ScriptViewer content={script.data.content} ext={script.data.ext} label={copy.scripts.editorLabel(copy.scripts.kinds[kind])} />
      ) : (
        <EditorSkeleton />
      )}

      <VersionList mcpId={mcpId} kind={kind} current={current} revertReason={editReason} />
    </section>
  );
}

function EditorSkeleton() {
  return (
    <div role="status">
      <span className="sr-only">{copy.common.loading}</span>
      <Skeleton className="h-56 w-full" />
    </div>
  );
}

function DeleteRestart({ mcpId, reason, onDeleted }: { mcpId: number; reason: DenyReason | null; onDeleted(): Promise<unknown> }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const trigger = (
    <Button variant="ghost">
      <Trash2Icon aria-hidden="true" />
      {copy.scripts.deleteRestart}
    </Button>
  );
  if (reason !== null) return <WithReason reason={reason}>{trigger}</WithReason>;

  const confirm = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await deleteScript(mcpId, "restart");
      clearDraft(`script:${mcpId}:restart`);
      setOpen(false);
      await onDeleted();
      toast.success(copy.scripts.restartDeleted);
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
      <AlertDialogTrigger asChild>{trigger}</AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{copy.scripts.deleteRestartTitle}</AlertDialogTitle>
          <AlertDialogDescription>{copy.scripts.deleteRestartBody}</AlertDialogDescription>
        </AlertDialogHeader>
        {error ? (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        ) : null}
        <AlertDialogFooter>
          <AlertDialogCancel>{copy.common.cancel}</AlertDialogCancel>
          <AlertDialogAction
            variant="destructive"
            aria-disabled={busy || undefined}
            onClick={(e) => {
              e.preventDefault();
              void confirm();
            }}
          >
            {copy.common.delete}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
