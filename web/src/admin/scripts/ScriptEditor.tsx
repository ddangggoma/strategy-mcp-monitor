// CodeMirror 6 lives only in this module, which is always imported lazily (its own chunk): read-only
// viewers use a <pre> and the board/admin entries never load an editor (U18, §7 budget).
import { defaultKeymap, history, historyKeymap } from "@codemirror/commands";
import { HighlightStyle, StreamLanguage, syntaxHighlighting } from "@codemirror/language";
import { powerShell } from "@codemirror/legacy-modes/mode/powershell";
import { Annotation, Compartment, EditorState, type Extension } from "@codemirror/state";
import {
  EditorView, drawSelection, highlightActiveLine, highlightActiveLineGutter, keymap, lineNumbers,
} from "@codemirror/view";
import { tags } from "@lezer/highlight";
import { HistoryIcon } from "lucide-react";
import { useEffect, useId, useImperativeHandle, useMemo, useRef, useState, type CSSProperties, type KeyboardEvent, type Ref } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { copy, messageForError } from "@/copy/ko";
import { ApiError } from "@/lib/api";
import type { ScriptContent, ScriptExt, ScriptKind, ScriptSummary } from "@/lib/api-types";
import { clearDraft, loadDraft, saveDraft } from "@/lib/draft";
import { putScript } from "@/lib/endpoints";
import { cn } from "@/lib/utils";

export const SCRIPT_EXTS: readonly ScriptExt[] = [".ps1", ".bat", ".cmd"];
/** Server limit on characters (ScriptBody.content max_length); the byte limit is checked there after encoding. */
export const MAX_SCRIPT_CHARS = 65_536;

/** The editor hands out LF; the server stores CRLF. Compare and edit in LF. */
export const toLf = (s: string) => s.replace(/\r\n?/g, "\n");
/** Characters as the server counts them (Python len = code points). */
export const charCount = (s: string) => [...s].length;

// ---- CodeMirror setup ------------------------------------------------------------------

const ps1 = StreamLanguage.define(powerShell);
const languageFor = (ext: ScriptExt): Extension => (ext === ".ps1" ? ps1 : []);

/**
 * Hue is reserved for MCP states (direction.md): syntax is told apart by weight, style and the muted tone.
 * `invalid` is left plain: the legacy PowerShell mode flags any non-ASCII word (Korean text) as an error.
 */
const highlight = HighlightStyle.define([
  { tag: tags.comment, color: "var(--color-fg-muted)", fontStyle: "italic" },
  { tag: [tags.string, tags.special(tags.string)], color: "var(--color-fg-muted)" },
  { tag: [tags.keyword, tags.controlKeyword, tags.operatorKeyword, tags.definitionKeyword, tags.modifier], fontWeight: "600" },
  { tag: [tags.variableName, tags.special(tags.variableName)], fontWeight: "500" },
]);

const theme = EditorView.theme({
  "&": {
    color: "var(--color-fg)",
    backgroundColor: "var(--color-surface)",
    fontSize: "var(--text-sm)",
    maxHeight: "60vh",
  },
  "&.cm-focused": { outline: "none" }, // the frame draws the shared focus ring
  ".cm-scroller": { fontFamily: "var(--font-mono)", lineHeight: "1.6", overflow: "auto" },
  ".cm-content": { caretColor: "var(--color-fg)", padding: "0.5rem 0", minHeight: "var(--editor-min-height, 12rem)" },
  ".cm-content:focus-visible": { outline: "none" },
  ".cm-gutters": {
    backgroundColor: "var(--color-sunken)",
    color: "var(--color-fg-muted)",
    borderRight: "1px solid var(--color-border)",
    minHeight: "var(--editor-min-height, 12rem)",
  },
  ".cm-activeLine": { backgroundColor: "var(--color-hover)" },
  ".cm-activeLineGutter": { backgroundColor: "var(--color-selected)", color: "var(--color-fg)" },
  ".cm-cursor, .cm-dropCursor": { borderLeftColor: "var(--color-fg)" },
  "&.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection": {
    backgroundColor: "color-mix(in oklch, var(--color-focus) 28%, transparent)",
  },
});

/** Marks our own value syncs so they are not reported back as edits. */
const external = Annotation.define<boolean>();

export interface CodeEditorHandle {
  focus(): void;
}

interface CodeEditorProps {
  value: string;
  onChange(v: string): void;
  ext: ScriptExt;
  /** Accessible name of the text area. */
  label: string;
  id?: string;
  "aria-describedby"?: string;
  "aria-invalid"?: boolean;
  "aria-required"?: boolean;
  /** Shorter when empty (several editors on one page). */
  compact?: boolean;
  ref?: Ref<CodeEditorHandle>;
}

/**
 * One CodeMirror view in a framed box. Tab is not bound (it moves focus, WCAG 2.1.2); Ctrl+Z/Y
 * history and the default keymap apply. `value` is controlled: outside changes (discard, revert)
 * replace the document without being echoed back through `onChange`.
 */
function CodeEditor({ value, onChange, ext, label, id, compact = false, ref, ...aria }: CodeEditorProps) {
  const host = useRef<HTMLDivElement>(null);
  const viewRef = useRef<EditorView | null>(null);
  const [language] = useState(() => new Compartment());
  const [attributes] = useState(() => new Compartment());
  const onChangeRef = useRef(onChange);
  const initial = useRef({ value, ext });

  useEffect(() => {
    onChangeRef.current = onChange;
  });

  const describedBy = aria["aria-describedby"];
  const invalid = aria["aria-invalid"] === true;
  const required = aria["aria-required"] === true;
  const contentAttributes = useMemo(() => {
    const attrs: Record<string, string> = { "aria-label": label, "aria-invalid": String(invalid) };
    if (id) attrs.id = id;
    if (describedBy) attrs["aria-describedby"] = describedBy;
    if (required) attrs["aria-required"] = "true";
    return EditorView.contentAttributes.of(attrs);
  }, [label, id, describedBy, invalid, required]);
  const attributesRef = useRef(contentAttributes);

  useEffect(() => {
    const parent = host.current;
    if (!parent) return;
    const view = new EditorView({
      parent,
      state: EditorState.create({
        doc: initial.current.value,
        extensions: [
          lineNumbers(),
          highlightActiveLineGutter(),
          history(),
          drawSelection(),
          highlightActiveLine(),
          keymap.of([...defaultKeymap, ...historyKeymap]),
          syntaxHighlighting(highlight),
          language.of(languageFor(initial.current.ext)),
          attributes.of(attributesRef.current),
          theme,
          EditorView.updateListener.of((u) => {
            if (u.docChanged && !u.transactions.some((t) => t.annotation(external))) {
              onChangeRef.current(u.state.doc.toString());
            }
          }),
        ],
      }),
    });
    viewRef.current = view;
    return () => {
      view.destroy();
      viewRef.current = null;
    };
  }, [language, attributes]);

  useEffect(() => {
    const view = viewRef.current;
    if (view && view.state.doc.toString() !== toLf(value)) {
      view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: toLf(value) }, annotations: external.of(true) });
    }
  }, [value]);

  useEffect(() => {
    viewRef.current?.dispatch({ effects: language.reconfigure(languageFor(ext)) });
  }, [ext, language]);

  useEffect(() => {
    attributesRef.current = contentAttributes;
    viewRef.current?.dispatch({ effects: attributes.reconfigure(contentAttributes) });
  }, [contentAttributes, attributes]);

  useImperativeHandle(ref, () => ({ focus: () => viewRef.current?.focus() }), []);

  return (
    <div
      ref={host}
      // shorter empty editors when several share a page (the theme reads this variable)
      style={compact ? ({ "--editor-min-height": "7.5rem" } as CSSProperties) : undefined}
      className={cn(
        "min-w-0 overflow-hidden rounded-md border border-border-strong",
        "focus-within:outline-(length:--focus-ring-width) focus-within:outline-offset-(length:--focus-ring-offset) focus-within:outline-focus focus-within:outline-solid",
        invalid && "border-danger",
      )}
    />
  );
}

// ---- ScriptField: the bare editor for a form (MCP registration) -------------------------------

export interface ScriptFieldProps extends Omit<CodeEditorProps, "onChange"> {
  onChange(v: string): void;
}

/** The same CodeMirror set-up without save, draft or extension picker: the form owns those. */
export function ScriptField(props: ScriptFieldProps) {
  return <CodeEditor compact {...props} />;
}

// ---- ScriptEditor: one MCP script, saved as a new version ------------------------------

interface ScriptDraft {
  ext: ScriptExt;
  content: string;
  /** The server version the draft was started from. */
  baseVersion: number;
}

function isScriptDraft(d: unknown): d is ScriptDraft {
  if (!d || typeof d !== "object") return false;
  const v = d as Record<string, unknown>;
  return SCRIPT_EXTS.includes(v.ext as ScriptExt) && typeof v.content === "string" && typeof v.baseVersion === "number";
}

interface Base {
  ext: ScriptExt;
  content: string;
  version: number;
}

const baseOf = (s: ScriptContent): Base => ({ ext: s.ext, content: toLf(s.content), version: s.version });

interface Start extends Base {
  restored: boolean;
  /** The script was saved again after the draft was made. */
  stale: boolean;
}

/** Start from a stored draft when it differs from the server's script; a draft equal to it is dropped. */
function startFrom(key: string, initial: ScriptContent): Start {
  const base = baseOf(initial);
  const draft = loadDraft<unknown>(key);
  if (!isScriptDraft(draft)) {
    if (draft !== null) clearDraft(key);
    return { ...base, restored: false, stale: false };
  }
  const content = toLf(draft.content);
  if (draft.ext === base.ext && content === base.content) {
    clearDraft(key);
    return { ...base, restored: false, stale: false };
  }
  return { ext: draft.ext, content, version: base.version, restored: true, stale: draft.baseVersion !== base.version };
}

export interface ScriptEditorProps {
  mcpId: number;
  kind: ScriptKind;
  initial: ScriptContent;
  onSaved(s: ScriptSummary): void;
  /** Unsaved edits on screen (the page's leave guard). */
  onDirtyChange?(dirty: boolean): void;
}

/**
 * The owner's editor (local channel only): extension picker, character count against the server's
 * limit, save (button or Ctrl+S) as a new version. Every change is kept as a draft in this tab
 * (`script:<id>:<kind>`) until it is saved, so a session expiry or a reload loses nothing; on mount a
 * draft that differs from the server is restored with a notice and a discard button.
 */
export function ScriptEditor({ mcpId, kind, initial, onSaved, onDirtyChange }: ScriptEditorProps) {
  const key = `script:${mcpId}:${kind}`;
  const [start] = useState(() => startFrom(key, initial));
  const [base, setBase] = useState<Base>(() => baseOf(initial));
  const [ext, setExt] = useState<ScriptExt>(start.ext);
  const [content, setContent] = useState(start.content);
  const [restored, setRestored] = useState(start.restored ? { stale: start.stale } : null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const editor = useRef<CodeEditorHandle>(null);
  const ids = { ext: useId(), error: useId(), count: useId(), hint: useId() };

  const dirty = ext !== base.ext || content !== base.content;
  const length = useMemo(() => charCount(content), [content]);
  const tooLong = length > MAX_SCRIPT_CHARS;
  const canSave = dirty && !tooLong && !saving;

  // the server's script moved on (a revert, a save in another tab): adopt it unless there are edits here.
  // Only a newer version: right after a save the refetch may still hand back the older one.
  if (initial.version > base.version && !saving) {
    const next = baseOf(initial);
    setBase(next);
    if (!dirty) {
      setExt(next.ext);
      setContent(next.content);
    }
  }

  useEffect(() => {
    onDirtyChange?.(dirty);
  }, [dirty, onDirtyChange]);
  useEffect(() => () => onDirtyChange?.(false), [onDirtyChange]);

  const change = (nextExt: ScriptExt, nextContent: string) => {
    setExt(nextExt);
    setContent(nextContent);
    setError(null);
    if (nextExt === base.ext && nextContent === base.content) clearDraft(key);
    else saveDraft(key, { ext: nextExt, content: nextContent, baseVersion: base.version } satisfies ScriptDraft);
  };

  const discard = () => {
    clearDraft(key);
    setExt(base.ext);
    setContent(base.content);
    setRestored(null);
    setError(null);
  };

  const save = async () => {
    if (!canSave) return;
    if (content.trim() === "") {
      setError(copy.errors.script_empty);
      editor.current?.focus();
      return;
    }
    const sent = { ext, content };
    setSaving(true);
    setError(null);
    try {
      const saved = await putScript(mcpId, kind, sent);
      clearDraft(key);
      setBase({ ext: saved.ext, content: sent.content, version: saved.version });
      setRestored(null);
      toast.success(copy.scripts.savedVersion(saved.version));
      onSaved(saved);
    } catch (err) {
      const code = err instanceof ApiError ? err.code : "internal";
      // session expired: the shell is already on its way to login; the draft stays for the return
      if (code !== "login_required") setError(messageForError(code));
    } finally {
      setSaving(false);
    }
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.code === "KeyS") {
      e.preventDefault(); // never the browser's "save page"
      void save();
    }
  };

  const describedBy = [error ? ids.error : null, tooLong ? ids.count : null, ids.hint].filter(Boolean).join(" ");

  return (
    // the group only listens for the Ctrl+S shortcut bubbling up from the editor and the extension picker
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <div
      role="group"
      aria-label={copy.scripts.kinds[kind]}
      data-testid="script-editor"
      onKeyDown={onKeyDown}
      className="flex min-w-0 flex-col gap-3"
    >
      {restored ? (
        <div role="status" className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 rounded-md border border-border-strong bg-surface px-4 py-2.5 text-sm text-fg">
          <div className="flex min-w-0 items-start gap-2.5">
            <HistoryIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
            <div className="flex flex-col gap-0.5">
              <p>{copy.scripts.draftRestored}</p>
              {restored.stale ? <p className="text-fg-muted">{copy.scripts.draftStale(initial.version)}</p> : null}
            </div>
          </div>
          <Button variant="outline" size="sm" onClick={discard}>
            {copy.scripts.discardDraft}
          </Button>
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <Label htmlFor={ids.ext} className="text-sm text-fg-muted">
          {copy.scripts.ext}
        </Label>
        <Select value={ext} onValueChange={(v) => change(v as ScriptExt, content)}>
          <SelectTrigger id={ids.ext} size="sm" className="w-24 font-mono">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SCRIPT_EXTS.map((x) => (
              <SelectItem key={x} value={x} className="font-mono">
                {x}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <span className="text-xs text-fg-muted">{copy.scripts.encodingNote}</span>
      </div>

      <CodeEditor
        ref={editor}
        value={content}
        onChange={(v) => change(ext, v)}
        ext={ext}
        label={copy.scripts.editorLabel(copy.scripts.kinds[kind])}
        aria-describedby={describedBy}
        aria-invalid={error !== null || tooLong}
      />

      {error ? (
        <p id={ids.error} role="alert" className="text-sm text-danger">
          {error}
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <Button aria-disabled={canSave ? undefined : true} onClick={() => void save()}>
          {saving ? copy.common.saving : copy.common.save}
        </Button>
        <p id={ids.hint} className="min-w-0 flex-1 text-xs text-fg-muted">
          {copy.scripts.saveHint}
        </p>
        <div id={ids.count} className={cn("text-xs tabular-nums", tooLong ? "text-danger" : "text-fg-muted")}>
          <p>{copy.scripts.count(length, MAX_SCRIPT_CHARS)}</p>
          {tooLong ? <p>{copy.scripts.tooLong}</p> : null}
        </div>
      </div>
    </div>
  );
}
