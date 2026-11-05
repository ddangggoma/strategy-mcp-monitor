import { useQueryClient } from "@tanstack/react-query";
import { BoldIcon, ExternalLinkIcon, HistoryIcon, ListIcon } from "lucide-react";
import { useEffect, useId, useLayoutEffect, useMemo, useRef, useState, type FormEvent, type ReactNode, type Ref } from "react";
import { toast } from "sonner";
import { TextDiff } from "@/components/app/TextDiff";
import { WithReason } from "@/components/app/WithReason";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter,
  AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { copy, messageForError } from "@/copy/ko";
import { ApiError } from "@/lib/api";
import type { Notice, NoticeContent, NoticeVersionSummary } from "@/lib/api-types";
import { clearDraft, loadDraft, saveDraft } from "@/lib/draft";
import { putNotice, revertNotice } from "@/lib/endpoints";
import { formatKst } from "@/lib/time";
import { cn } from "@/lib/utils";
import { NoticeDialog } from "@/notice/NoticeDialog";
import { useNotice, useNoticeVersion, useNoticeVersions } from "../queries";
import { qk } from "../query-keys";
import { LeaveGuard } from "../shell/LeaveGuard";
import { LocalOnlyPage } from "../shell/LocalOnlyPage";

type Field = keyof NoticeContent;
const FIELDS: Field[] = ["title", "body", "button_text"];
/** Server limits in code points (U14); the server checks again after trimming. */
const LIMITS: Record<Field, number> = { title: 80, body: 4000, button_text: 20 };
const DRAFT_KEY = "notice";

const chars = (s: string) => [...s].length;
const contentOf = (n: NoticeContent): NoticeContent => ({ title: n.title, body: n.body, button_text: n.button_text });
const sameContent = (a: NoticeContent, b: NoticeContent) => FIELDS.every((f) => a[f] === b[f]);

function problem(field: Field, value: string): "required" | "tooLong" | null {
  if (value.trim() === "") return "required";
  return chars(value) > LIMITS[field] ? "tooLong" : null;
}

/** `/admin/notice`: Local + Admin only; anyone else gets the reason and no request (LocalOnlyPage). */
export function NoticeEditorPage() {
  return (
    <LocalOnlyPage action="edit_notice" title={copy.notice.title}>
      <NoticeEditor />
    </LocalOnlyPage>
  );
}

function NoticeEditor() {
  const notice = useNotice();
  const [dirty, setDirty] = useState(false);
  const noteId = useId();

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="flex max-w-(--size-prose) flex-col gap-1">
          <h1 className="text-xl font-semibold text-fg">{copy.notice.title}</h1>
          <p className="text-sm text-fg-muted">{copy.notice.lead}</p>
        </div>
        <div className="flex flex-col items-start gap-1">
          <a
            href="/notice"
            target="_blank"
            rel="noopener noreferrer"
            aria-describedby={noteId}
            className={buttonVariants({ variant: "outline" })}
          >
            <ExternalLinkIcon aria-hidden="true" />
            {copy.notice.fullPreview}
          </a>
          <p id={noteId} className="text-xs text-fg-muted">
            {copy.notice.fullPreviewNote}
          </p>
        </div>
      </header>

      {notice.isPending ? (
        <div role="status" className="grid gap-4">
          <span className="sr-only">{copy.common.loading}</span>
          <Skeleton className="h-9 w-full max-w-(--size-prose)" />
          <Skeleton className="h-60 w-full max-w-(--size-prose)" />
        </div>
      ) : notice.isError ? (
        <p role="alert" className="text-sm text-fg">
          {copy.notice.loadError}
        </p>
      ) : (
        <>
          <NoticeForm initial={notice.data} onDirtyChange={setDirty} />
          <VersionHistory current={notice.data} dirty={dirty} />
        </>
      )}
      <LeaveGuard when={dirty} />
    </div>
  );
}

// ---- the form + live preview -------------------------------------------------------------

interface NoticeDraft extends NoticeContent {
  /** The saved version the draft was started from. */
  baseVersion: number;
}

function isNoticeDraft(d: unknown): d is NoticeDraft {
  if (!d || typeof d !== "object") return false;
  const v = d as Record<string, unknown>;
  return FIELDS.every((f) => typeof v[f] === "string") && typeof v.baseVersion === "number";
}

interface Start {
  values: NoticeContent;
  /** A draft was restored; `stale` when the notice was saved again after it was made. */
  restored: { stale: boolean } | null;
}

/** Start from a stored draft when it differs from the saved notice; an equal or malformed one is dropped. */
function startFrom(initial: Notice): Start {
  const draft = loadDraft<unknown>(DRAFT_KEY);
  if (!isNoticeDraft(draft) || sameContent(draft, initial)) {
    if (draft !== null) clearDraft(DRAFT_KEY);
    return { values: contentOf(initial), restored: null };
  }
  return { values: contentOf(draft), restored: { stale: draft.baseVersion !== initial.version } };
}

interface Selection {
  start: number;
  end: number;
}

function NoticeForm({ initial, onDirtyChange }: { initial: Notice; onDirtyChange(dirty: boolean): void }) {
  const qc = useQueryClient();
  const [start] = useState(() => startFrom(initial));
  const [base, setBase] = useState<Notice>(initial);
  const [values, setValues] = useState<NoticeContent>(start.values);
  const [restored, setRestored] = useState(start.restored);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const body = useRef<HTMLTextAreaElement>(null);
  const pendingSelection = useRef<Selection | null>(null);
  const ids = { error: useId(), help: useId() };

  const dirty = !sameContent(values, base);
  const problems = useMemo(
    () => Object.fromEntries(FIELDS.map((f) => [f, problem(f, values[f])])) as Record<Field, ReturnType<typeof problem>>,
    [values],
  );
  const valid = FIELDS.every((f) => problems[f] === null);
  const canSave = dirty && valid && !saving;

  // the saved notice moved on (a revert, another tab): adopt it unless there are edits here.
  // Only a newer version: right after a save the cache may still hold the older one for a moment.
  if (initial.version > base.version && !saving) {
    setBase(initial);
    if (!dirty) setValues(contentOf(initial));
  }

  useEffect(() => {
    onDirtyChange(dirty);
  }, [dirty, onDirtyChange]);
  useEffect(() => () => onDirtyChange(false), [onDirtyChange]);

  // a format button changed the body: put the selection where the inserted markers say
  useLayoutEffect(() => {
    const sel = pendingSelection.current;
    const el = body.current;
    if (!sel || !el) return;
    pendingSelection.current = null;
    el.focus();
    el.setSelectionRange(sel.start, sel.end);
  }, [values.body]);

  const change = (next: NoticeContent) => {
    setValues(next);
    setError(null);
    if (sameContent(next, base)) clearDraft(DRAFT_KEY);
    else saveDraft(DRAFT_KEY, { ...next, baseVersion: base.version } satisfies NoticeDraft);
  };
  const set = (field: Field, value: string) => change({ ...values, [field]: value });

  const format = (apply: (value: string, sel: Selection) => { value: string; sel: Selection }) => {
    const el = body.current;
    if (!el) return;
    const out = apply(el.value, { start: el.selectionStart, end: el.selectionEnd });
    pendingSelection.current = out.sel;
    set("body", out.value);
  };

  const discard = () => {
    clearDraft(DRAFT_KEY);
    setValues(contentOf(base));
    setRestored(null);
    setError(null);
  };

  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (!canSave) return;
    setSaving(true);
    setError(null);
    try {
      const saved = await putNotice(values);
      const created = saved.version !== base.version;
      clearDraft(DRAFT_KEY);
      setBase(saved);
      setValues(contentOf(saved)); // the server's trimmed, normalized text
      setRestored(null);
      qc.setQueryData(qk.notice, saved);
      if (created) {
        await qc.invalidateQueries({ queryKey: qk.noticeVersions });
        toast.success(copy.notice.savedVersion(saved.version));
      } else {
        toast(copy.notice.unchanged);
      }
    } catch (err) {
      const code = err instanceof ApiError ? err.code : "internal";
      // session expired: the shell is already on its way to login; the draft stays for the return
      if (code !== "login_required") setError(messageForError(code));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex min-w-0 flex-col gap-4">
      {restored ? (
        <div
          role="status"
          className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 rounded-md border border-border-strong bg-surface px-4 py-2.5 text-sm text-fg"
        >
          <div className="flex min-w-0 items-start gap-2.5">
            <HistoryIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
            <div className="flex flex-col gap-0.5">
              <p>{copy.notice.draftRestored}</p>
              {restored.stale ? <p className="text-fg-muted">{copy.notice.draftStale(initial.version)}</p> : null}
            </div>
          </div>
          <Button variant="outline" size="sm" onClick={discard}>
            {copy.notice.discardDraft}
          </Button>
        </div>
      ) : null}

      <div className="@container min-w-0">
        <div className="grid min-w-0 gap-6 @4xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <form noValidate onSubmit={(e) => void save(e)} className="flex min-w-0 flex-col gap-5">
            <TextField field="title" value={values.title} problem={problems.title} onChange={(v) => set("title", v)} />

            <TextField
              field="body"
              value={values.body}
              problem={problems.body}
              onChange={(v) => set("body", v)}
              helpId={ids.help}
              inputRef={body}
              toolbar={
                <div role="group" aria-label={copy.notice.formatLabel} className="flex gap-1.5">
                  <Button type="button" variant="outline" size="sm" onClick={() => format(wrapBold)}>
                    <BoldIcon aria-hidden="true" />
                    {copy.notice.insertBold}
                  </Button>
                  <Button type="button" variant="outline" size="sm" onClick={() => format(toggleList)}>
                    <ListIcon aria-hidden="true" />
                    {copy.notice.insertList}
                  </Button>
                </div>
              }
            />
            <p id={ids.help} className="-mt-3 text-xs text-fg-muted">
              {copy.notice.markupHelp}
            </p>

            <TextField
              field="button_text"
              value={values.button_text}
              problem={problems.button_text}
              onChange={(v) => set("button_text", v)}
            />

            {error ? (
              <p id={ids.error} role="alert" className="text-sm text-danger">
                {error}
              </p>
            ) : null}
            <div>
              {/* nothing to save yet: say so instead of a silently dimmed button (U26) */}
              <WithReason reason={dirty ? null : "unchanged"}>
                <Button type="submit" aria-disabled={canSave ? undefined : true} aria-describedby={error ? ids.error : undefined}>
                  {saving ? copy.common.saving : copy.common.save}
                </Button>
              </WithReason>
            </div>
          </form>

          <div className="flex min-w-0 flex-col gap-2 @4xl:sticky @4xl:top-[calc(var(--size-topbar)+1.5rem)] @4xl:self-start">
            <p aria-hidden="true" className="text-sm font-medium text-fg">
              {copy.notice.previewLabel}
              <span className="ml-2 font-normal text-fg-muted">{copy.notice.previewNote}</span>
            </p>
            <NoticeDialog content={values} mode="preview" />
          </div>
        </div>
      </div>
    </div>
  );
}

interface TextFieldProps {
  field: Field;
  value: string;
  problem: "required" | "tooLong" | null;
  onChange(value: string): void;
  helpId?: string;
  inputRef?: Ref<HTMLTextAreaElement>;
  toolbar?: ReactNode;
}

/** One labelled field with its length against the limit and, when it cannot be saved, why. */
function TextField({ field, value, problem, onChange, helpId, inputRef, toolbar }: TextFieldProps) {
  const ids = { input: useId(), count: useId(), error: useId() };
  const max = LIMITS[field];
  const used = chars(value);
  const describedBy = [problem ? ids.error : null, ids.count, helpId ?? null].filter(Boolean).join(" ");
  const message = problem === "required" ? copy.notice.required[field] : problem === "tooLong" ? copy.notice.tooLong(max) : null;
  const common = {
    id: ids.input,
    value,
    "aria-invalid": problem ? true : undefined,
    "aria-describedby": describedBy,
  } as const;

  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <Label htmlFor={ids.input}>{copy.notice.fields[field]}</Label>
        {toolbar}
      </div>
      {field === "body" ? (
        <Textarea
          {...common}
          ref={inputRef}
          rows={12}
          onChange={(e) => onChange(e.target.value)}
          className="max-h-[60vh] min-h-48 text-base leading-(--text-base--line-height)"
        />
      ) : (
        <Input {...common} onChange={(e) => onChange(e.target.value)} className={field === "button_text" ? "max-w-60" : undefined} />
      )}
      <div className="flex items-start justify-between gap-3 text-xs">
        {message ? (
          <p id={ids.error} className="text-danger">
            {message}
          </p>
        ) : (
          <span />
        )}
        <p id={ids.count} className={cn("shrink-0 tabular-nums", problem === "tooLong" ? "text-danger" : "text-fg-muted")}>
          {copy.notice.count(used, max)}
        </p>
      </div>
    </div>
  );
}

// ---- format buttons (pure: value + selection in, value + selection out) -------------------

/** Wraps the selection in `**`, line by line (bold never spans a line); an empty one gets a pair to type into. */
function wrapBold(value: string, sel: Selection): { value: string; sel: Selection } {
  const picked = value.slice(sel.start, sel.end);
  if (picked === "") {
    return { value: `${value.slice(0, sel.start)}****${value.slice(sel.end)}`, sel: { start: sel.start + 2, end: sel.start + 2 } };
  }
  const wrapped = picked
    .split("\n")
    .map((line) => (line.trim() === "" ? line : `**${line}**`))
    .join("\n");
  const firstMarked = picked.split("\n")[0]!.trim() !== "";
  return {
    value: value.slice(0, sel.start) + wrapped + value.slice(sel.end),
    sel: { start: sel.start + (firstMarked ? 2 : 0), end: sel.start + wrapped.length - 2 },
  };
}

/** Makes the lines the selection touches a list ("- "), or takes the bullets off when they all have one. */
function toggleList(value: string, sel: Selection): { value: string; sel: Selection } {
  const from = value.lastIndexOf("\n", sel.start - 1) + 1;
  const endBreak = value.indexOf("\n", sel.end > sel.start && value[sel.end - 1] === "\n" ? sel.end - 1 : sel.end);
  const to = endBreak === -1 ? value.length : endBreak;
  const lines = value.slice(from, to).split("\n");
  const filled = lines.filter((l) => l.trim() !== "");
  const allBullets = filled.length > 0 && filled.every((l) => l.startsWith("- "));
  const block = lines
    .map((l) => (l.trim() === "" ? l : allBullets ? l.slice(2) : l.startsWith("- ") ? l : `- ${l}`))
    .join("\n");
  return { value: value.slice(0, from) + block + value.slice(to), sel: { start: from, end: from + block.length } };
}

// ---- version history + revert --------------------------------------------------------------

type VersionRow = Omit<NoticeVersionSummary, "created_at"> & { created_at: string | null };

/** Version 0 is never stored: it is the built-in text, always available to go back to. */
const BUILT_IN_ROW: VersionRow = {
  version: 0,
  title: copy.notice.builtIn.title,
  created_at: null,
  author: null,
  reverted_from: null,
};

function VersionHistory({ current, dirty }: { current: Notice; dirty: boolean }) {
  const versions = useNoticeVersions();
  const [selected, setSelected] = useState<number | null>(null);
  const headingId = useId();
  const rows: VersionRow[] = useMemo(() => [...(versions.data ?? []), BUILT_IN_ROW], [versions.data]);
  const picked = rows.find((v) => v.version === selected) ?? null;

  return (
    <section aria-labelledby={headingId} className="@container flex min-w-0 flex-col gap-3 border-t border-border pt-5">
      <div className="flex flex-col gap-1">
        <h2 id={headingId} className="text-base font-semibold text-fg">
          {copy.notice.versions}
        </h2>
        <p className="max-w-(--size-prose) text-sm text-fg-muted">{copy.notice.defaultNote}</p>
      </div>
      {versions.isPending ? (
        <div role="status" className="flex flex-col gap-2">
          <span className="sr-only">{copy.common.loading}</span>
          <Skeleton className="h-12 w-full max-w-72" />
          <Skeleton className="h-12 w-full max-w-72" />
        </div>
      ) : versions.isError ? (
        <p role="alert" className="text-sm text-fg">
          {copy.notice.versionsError}
        </p>
      ) : (
        <div className="grid min-w-0 gap-4 @3xl:grid-cols-[18rem_minmax(0,1fr)]">
          <ul aria-label={copy.notice.versions} className="flex max-h-[60vh] flex-col gap-1 overflow-auto">
            {rows.map((v) => (
              <li key={v.version}>
                <VersionButton
                  v={v}
                  current={current.version === v.version}
                  pressed={selected === v.version}
                  onPick={() => setSelected(v.version)}
                />
              </li>
            ))}
          </ul>
          <div className="min-w-0">
            {picked ? (
              <VersionDetail key={picked.version} version={picked.version} current={current} dirty={dirty} />
            ) : (
              <p className="text-sm text-fg-muted">{copy.notice.pickVersion}</p>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

function VersionButton({ v, current, pressed, onPick }: { v: VersionRow; current: boolean; pressed: boolean; onPick(): void }) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      onClick={onPick}
      className="flex w-full min-w-0 flex-col items-start gap-0.5 rounded-md px-3 py-2 text-left text-sm transition-[background-color] duration-(--motion-fast) ease-hover hover:bg-hover aria-pressed:bg-selected"
    >
      <span className="flex flex-wrap items-center gap-2">
        <span className="font-semibold text-fg">{copy.notice.versionLabel(v.version)}</span>
        {current ? (
          <span className="rounded-sm border border-border-strong px-1.5 text-xs text-fg">{copy.notice.current}</span>
        ) : null}
      </span>
      <span className="w-full truncate text-fg">{v.title}</span>
      <span className="text-xs text-fg-muted">
        {v.created_at === null ? (
          copy.notice.builtInMeta
        ) : (
          <>
            {v.author?.name ?? copy.notice.systemAuthor} <span data-volatile>{formatKst(v.created_at)}</span>
          </>
        )}
      </span>
      {v.reverted_from !== null ? <span className="text-xs text-fg-muted">{copy.notice.reverted(v.reverted_from)}</span> : null}
    </button>
  );
}

function VersionDetail({ version, current, dirty }: { version: number; current: Notice; dirty: boolean }) {
  const isCurrent = current.version === version;
  const content = useNoticeVersion(version, { enabled: !isCurrent });
  const noteId = useId();
  const label = copy.notice.versionLabel(version);

  return (
    <div className="flex min-w-0 flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-fg">{label}</h3>
        {isCurrent ? (
          <Button variant="outline" size="sm" aria-disabled={true} aria-describedby={noteId} onClick={(e) => e.preventDefault()}>
            {copy.notice.revert}
          </Button>
        ) : (
          <RevertDialog version={version} current={current} dirty={dirty} />
        )}
      </div>
      {isCurrent ? (
        <p id={noteId} className="text-sm text-fg-muted">
          {copy.notice.currentNote}
        </p>
      ) : content.isPending ? (
        <div role="status">
          <span className="sr-only">{copy.common.loading}</span>
          <Skeleton className="h-40 w-full" />
        </div>
      ) : content.isError ? (
        <p role="alert" className="text-sm text-fg">
          {copy.notice.versionError}
        </p>
      ) : (
        <TextDiff before={content.data.body} after={current.body} labels={[label, copy.notice.current]} />
      )}
    </div>
  );
}

function RevertDialog({ version, current, dirty }: { version: number; current: Notice; dirty: boolean }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const confirm = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const n = await revertNotice(version);
      qc.setQueryData(qk.notice, n);
      if (n.version === current.version) {
        toast(copy.notice.unchanged);
      } else {
        await qc.invalidateQueries({ queryKey: qk.noticeVersions });
        toast.success(copy.notice.revertedTo(version, n.version));
      }
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
          {copy.notice.revert}
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{copy.notice.revertTitle(version)}</AlertDialogTitle>
          <AlertDialogDescription>
            {copy.notice.revertBody}
            {dirty ? ` ${copy.notice.revertKeepsEdits}` : null}
          </AlertDialogDescription>
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
            {busy ? copy.notice.reverting : copy.notice.revertAction}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
