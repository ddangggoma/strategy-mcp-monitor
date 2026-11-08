import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { HistoryIcon, LockIcon } from "lucide-react";
import { lazy, Suspense, useEffect, useId, useRef, useState, type FormEvent, type RefObject } from "react";
import { useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";
import { InfoTip } from "@/components/app/InfoTip";
import { Button } from "@/components/ui/button";
import { Form } from "@/components/ui/form";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { copy, messageForError } from "@/copy/ko";
import { ApiError } from "@/lib/api";
import type { McpConfig, McpCreate, ScriptExt, ScriptKind, ScriptUpload } from "@/lib/api-types";
import { clearDraft, loadDraft, saveDraft } from "@/lib/draft";
import { createMcp } from "@/lib/endpoints";
import { isMcpEmoji } from "@/lib/mcp-emoji";
import { denyReason } from "@/lib/permissions";
import { useSession } from "@/lib/session";
import { qk } from "../query-keys";
import type { CodeEditorHandle } from "../scripts/ScriptEditor";
import { McpConfigFields } from "./McpConfigFields";
import { mcpConfigSchema, type McpFormValues } from "./mcp-schema";

// the editor chunk (CodeMirror) is shared with the scripts tab and loads after the page
const ScriptField = lazy(() => import("../scripts/ScriptEditor").then((m) => ({ default: m.ScriptField })));

const DRAFT_KEY = "mcp-create";
const KINDS: readonly ScriptKind[] = ["start", "stop", "restart"];
const EXTS: readonly ScriptExt[] = [".ps1", ".bat", ".cmd"];
const MAX_SCRIPT_CHARS = 65_536; // same as ScriptEditor (kept here so the page does not pull the editor chunk)
const MAX_SCRIPT_BYTES = 65_536;

type Scripts = Record<ScriptKind, ScriptUpload>;
type ScriptErrors = Partial<Record<ScriptKind, string>>;

/** The server's McpConfig defaults; the host is this PC, where the MCPs run. */
const DEFAULTS: McpFormValues = {
  name: "",
  host: "127.0.0.1",
  port: "",
  path: "/mcp",
  probe: "mcp_ping",
  expected_process_name: "",
  action_delay_sec: 30,
  startup_grace_sec: 30,
  max_auto_actions: 3,
  window_sec: 600,
  auto_recovery: true,
  autostart_on_boot: false,
  maintenance: false,
  script_timeout_sec: 120,
  icon: null,
};
const KEYS = Object.keys(DEFAULTS) as (keyof McpFormValues)[];
const EMPTY_SCRIPTS: Scripts = {
  start: { ext: ".ps1", content: "" },
  stop: { ext: ".ps1", content: "" },
  restart: { ext: ".ps1", content: "" },
};

type CreateDraft = McpFormValues & { scripts: Scripts };

/** Field order fixed by DEFAULTS, so equal forms give equal strings. */
function snapshotOf(values: Partial<McpFormValues>, scripts: Scripts): string {
  return JSON.stringify({ ...Object.fromEntries(KEYS.map((k) => [k, values[k]])), scripts });
}
const EMPTY_SNAPSHOT = snapshotOf(DEFAULTS, EMPTY_SCRIPTS);

const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

/** A stored draft with the right shape, else null (a draft from an older build is dropped, not trusted). */
function readDraft(): CreateDraft | null {
  const d = loadDraft<unknown>(DRAFT_KEY);
  if (d === null) return null;
  const bad = () => {
    clearDraft(DRAFT_KEY);
    return null;
  };
  if (!isRecord(d) || !isRecord(d.scripts)) return bad();
  const scripts = { ...EMPTY_SCRIPTS };
  for (const k of KINDS) {
    const s = d.scripts[k];
    if (!isRecord(s) || !EXTS.includes(s.ext as ScriptExt) || typeof s.content !== "string") return bad();
    scripts[k] = { ext: s.ext as ScriptExt, content: s.content };
  }
  const values: Record<string, unknown> = { ...DEFAULTS };
  for (const k of KEYS) {
    const want = DEFAULTS[k];
    const got = d[k];
    if (got === undefined) continue;
    const ok =
      k === "icon"
        ? got === null || isMcpEmoji(got)
        : typeof got === typeof want ||
          (typeof got === "string" && typeof want === "number") || // a number input being edited
          (k === "port" && typeof got === "number") ||
          (k === "expected_process_name" && got === null);
    if (!ok) return bad();
    values[k] = got;
  }
  return { ...(values as McpFormValues), scripts };
}

function validateScripts(scripts: Scripts): ScriptErrors {
  const errors: ScriptErrors = {};
  for (const k of KINDS) {
    const { content } = scripts[k];
    if (k !== "restart" && content.trim() === "") errors[k] = copy.mcp.scriptRequired(copy.scripts.kinds[k]);
    else if ([...content].length > MAX_SCRIPT_CHARS) errors[k] = copy.scripts.tooLong;
  }
  return errors;
}

/** Bytes the server will write (CRLF; UTF-8 + BOM for .ps1). UTF-8 is an upper bound for the OEM code page. */
function estimatedBytes(s: ScriptUpload): number {
  const crlf = s.content.replace(/\r\n?|\n/g, "\r\n");
  return new TextEncoder().encode(crlf.endsWith("\r\n") ? crlf : crlf + "\r\n").length + (s.ext === ".ps1" ? 3 : 0);
}

/**
 * Which scripts a 422 is about. The server names no script, so the likely ones are picked: encoding
 * errors only happen in .bat/.cmd (code page) and need non-ASCII text, size errors in the biggest.
 */
export function scriptErrorKinds(code: string, scripts: Scripts): ScriptKind[] {
  const sent = KINDS.filter((k) => k !== "restart" || scripts[k].content.trim() !== "");
  const pick = (cands: ScriptKind[], fallback: ScriptKind[]) => (cands.length > 0 ? cands : fallback);
  switch (code) {
    case "script_encoding": {
      const codePage = sent.filter((k) => scripts[k].ext !== ".ps1");
      return pick(codePage.filter((k) => /[^\p{ASCII}]/u.test(scripts[k].content)), pick(codePage, sent));
    }
    case "script_too_large": {
      const sizes = sent.map((k) => [k, estimatedBytes(scripts[k])] as const);
      const largest = sizes.reduce((a, b) => (b[1] > a[1] ? b : a));
      return pick(sizes.filter(([, n]) => n > MAX_SCRIPT_BYTES).map(([k]) => k), [largest[0]]);
    }
    case "script_empty":
    case "scripts_required":
      return pick(sent.filter((k) => scripts[k].content.trim() === ""), ["start", "stop"]);
    default:
      return [];
  }
}

const SCRIPT_CODES = new Set(["script_encoding", "script_too_large", "script_empty", "scripts_required"]);

/**
 * Register an MCP (local channel only: its scripts run as SYSTEM). On the external channel the page
 * says why and requests nothing. Everything typed is kept as a draft in this tab (`mcp-create`)
 * until the MCP is created or the person cancels.
 */
export function McpCreatePage() {
  const me = useSession();
  const reason = denyReason(me, "create_mcp");

  return (
    <div className="flex min-w-0 flex-col gap-5">
      <header className="flex max-w-(--size-prose) flex-col gap-1.5">
        <h1 className="text-xl font-semibold text-fg">{copy.mcp.create}</h1>
        {reason === null ? <p className="text-sm text-fg-muted">{copy.mcp.createLead}</p> : null}
      </header>
      {reason === null ? (
        <CreateForm />
      ) : (
        <div className="flex max-w-(--size-prose) items-start gap-3 rounded-md border bg-surface px-4 py-3 text-sm text-fg-muted">
          <LockIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          <p>{copy.deny[reason]}</p>
        </div>
      )}
    </div>
  );
}

function CreateForm() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [draft] = useState(readDraft);
  const form = useForm<McpFormValues, unknown, McpConfig>({
    resolver: zodResolver(mcpConfigSchema),
    defaultValues: draft ?? DEFAULTS,
  });
  const [scripts, setScripts] = useState<Scripts>(draft?.scripts ?? EMPTY_SCRIPTS);
  const [scriptErrors, setScriptErrors] = useState<ScriptErrors>({});
  const [restored, setRestored] = useState(draft !== null);
  const finished = useRef(false);
  const editors = {
    start: useRef<CodeEditorHandle>(null),
    stop: useRef<CodeEditorHandle>(null),
    restart: useRef<CodeEditorHandle>(null),
  };

  const values = useWatch({ control: form.control });
  const snapshot = snapshotOf(values, scripts);
  useEffect(() => {
    if (finished.current) return; // created or cancelled: do not write it back
    if (snapshot === EMPTY_SNAPSHOT) clearDraft(DRAFT_KEY);
    else saveDraft(DRAFT_KEY, JSON.parse(snapshot));
  }, [snapshot]);

  const { isSubmitting, errors } = form.formState;
  const serverError = errors.root?.server?.message;

  const setScript = (kind: ScriptKind, patch: Partial<ScriptUpload>) => {
    setScripts((s) => ({ ...s, [kind]: { ...s[kind], ...patch } }));
    setScriptErrors((e) => (e[kind] ? { ...e, [kind]: undefined } : e));
  };

  const discardDraft = () => {
    clearDraft(DRAFT_KEY);
    form.reset(DEFAULTS);
    setScripts(EMPTY_SCRIPTS);
    setScriptErrors({});
    setRestored(false);
  };

  const cancel = () => {
    finished.current = true;
    clearDraft(DRAFT_KEY);
    void navigate({ to: "/admin/mcps" });
  };

  const create = async (config: McpConfig) => {
    const body: McpCreate = {
      ...config,
      scripts: {
        start: scripts.start,
        stop: scripts.stop,
        ...(scripts.restart.content.trim() !== "" ? { restart: scripts.restart } : {}),
      },
    };
    try {
      const detail = await createMcp(body);
      finished.current = true;
      clearDraft(DRAFT_KEY);
      qc.setQueryData(qk.mcp(detail.id), detail);
      void qc.invalidateQueries({ queryKey: qk.mcps });
      toast.success(copy.mcp.created(detail.name));
      await navigate({ to: "/admin/mcps/$mcpId", params: { mcpId: String(detail.id) } });
    } catch (err) {
      const code = err instanceof ApiError ? err.code : "internal";
      if (code === "login_required") return; // on the way to login; the draft stays
      if (code === "name_taken" || code === "endpoint_taken") {
        form.setError(code === "name_taken" ? "name" : "port", { type: "server", message: copy.errors[code] }, { shouldFocus: true });
      } else if (SCRIPT_CODES.has(code)) {
        const kinds = scriptErrorKinds(code, scripts);
        setScriptErrors(Object.fromEntries(kinds.map((k) => [k, messageForError(code)])));
        if (kinds[0]) editors[kinds[0]].current?.focus();
      } else {
        form.setError("root.server", { type: "server", message: messageForError(code) });
      }
    }
  };

  const onSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (isSubmitting) return;
    const found = validateScripts(scripts);
    setScriptErrors(found);
    void form.handleSubmit(async (config) => {
      const first = KINDS.find((k) => found[k]);
      if (first) {
        editors[first].current?.focus();
        return;
      }
      await create(config);
    })();
  };

  return (
    <>
      {restored ? (
        <div role="status" className="flex max-w-(--size-prose) flex-wrap items-center justify-between gap-x-4 gap-y-2 rounded-md border border-border-strong bg-surface px-4 py-2.5 text-sm text-fg">
          <p className="flex items-start gap-2.5">
            <HistoryIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
            {copy.scripts.draftRestored}
          </p>
          <Button variant="outline" size="sm" onClick={discardDraft}>
            {copy.scripts.discardDraft}
          </Button>
        </div>
      ) : null}
      <Form {...form}>
        <form noValidate onSubmit={onSubmit} className="flex min-w-0 flex-col gap-6" aria-busy={isSubmitting || undefined}>
          <div className="flex max-w-(--size-prose) flex-col gap-6">
            <McpConfigFields control={form.control} readOnly={isSubmitting} nameError={errors.name !== undefined} />
          </div>

          <fieldset className="flex min-w-0 max-w-5xl flex-col gap-5 border-t border-border pt-4">
            <legend className="pr-2 text-sm font-semibold text-fg">{copy.mcp.scriptsLegend}</legend>
            <p className="-mt-2 text-sm text-fg-muted">{copy.scripts.encodingNote}</p>
            {KINDS.map((k) => (
              <ScriptBlock
                key={k}
                kind={k}
                value={scripts[k]}
                error={scriptErrors[k]}
                editorRef={editors[k]}
                onChange={(patch) => setScript(k, patch)}
              />
            ))}
          </fieldset>

          {serverError ? (
            <p role="alert" className="text-sm text-danger">
              {serverError}
            </p>
          ) : null}

          <div className="flex flex-wrap items-center gap-2">
            <Button type="submit" aria-disabled={isSubmitting || undefined}>
              {isSubmitting ? copy.mcp.creating : copy.mcp.createSubmit}
            </Button>
            <Button variant="outline" onClick={cancel}>
              {copy.mcp.createCancel}
            </Button>
          </div>
        </form>
      </Form>
    </>
  );
}

function ScriptBlock({
  kind,
  value,
  error,
  editorRef,
  onChange,
}: {
  kind: ScriptKind;
  value: ScriptUpload;
  error: string | undefined;
  editorRef: RefObject<CodeEditorHandle | null>;
  onChange(patch: Partial<ScriptUpload>): void;
}) {
  const ids = { ext: useId(), error: useId(), hint: useId(), legend: useId() };
  const required = kind !== "restart";
  const describedBy = [error ? ids.error : null, required ? null : ids.hint].filter(Boolean).join(" ") || undefined;

  return (
    // named by the legend's words alone (aria-labelledby), not by the tip button inside the legend
    <fieldset data-testid={`script-field-${kind}`} aria-labelledby={ids.legend} className="flex min-w-0 flex-col gap-2">
      <legend className="mb-2 flex items-center text-sm font-medium text-fg">
        <span id={ids.legend}>{copy.scripts.kinds[kind]}</span>
        <InfoTip label={copy.scripts.kinds[kind]} content={copy.help.scripts.kinds[kind]} className="ms-0.5" />
        {/* the editor says "required" itself (aria-required): shown, not read twice */}
        <span aria-hidden="true" className="ml-2 text-xs font-normal text-fg-muted">
          {required ? copy.common.required : copy.common.optional}
        </span>
      </legend>
      {required ? null : (
        <p id={ids.hint} className="text-xs text-fg-muted">
          {copy.scripts.optionalRestart}
        </p>
      )}
      <div className="flex items-center gap-2">
        <Label htmlFor={ids.ext} className="text-sm text-fg-muted">
          {copy.scripts.ext}
        </Label>
        <InfoTip label={copy.scripts.ext} content={copy.help.scripts.ext} className="-ms-1.5" />
        <Select value={value.ext} onValueChange={(v) => onChange({ ext: v as ScriptExt })}>
          <SelectTrigger id={ids.ext} size="sm" className="w-24 font-mono">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {EXTS.map((x) => (
              <SelectItem key={x} value={x} className="font-mono">
                {x}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <Suspense
        fallback={
          <div role="status">
            <span className="sr-only">{copy.common.loading}</span>
            <Skeleton className="h-48 w-full" />
          </div>
        }
      >
        <ScriptField
          ref={editorRef}
          value={value.content}
          onChange={(content) => onChange({ content })}
          ext={value.ext}
          label={copy.scripts.editorLabel(copy.scripts.kinds[kind])}
          aria-describedby={describedBy}
          aria-invalid={error !== undefined}
          aria-required={required}
        />
      </Suspense>
      {error ? (
        <p id={ids.error} className="text-sm text-danger">
          {error}
        </p>
      ) : null}
    </fieldset>
  );
}
