import { useEffect, useId, useMemo, useRef, type ReactNode } from "react";
import { copy } from "@/copy/ko";
import type { NoticeContent } from "@/lib/api-types";
import { parseNoticeMarkup, renderNoticeMarkup } from "./markup";
import "./NoticeDialog.css";

export interface NoticeDialogProps {
  content: NoticeContent;
  /** `standalone`: the real notice, a native modal dialog. `preview`: the same panel, drawn in place. */
  mode: "standalone" | "preview";
  onAcknowledge?: () => void;
  /** Standalone: the acknowledgement is on its way — the button says so (aria-busy) and ignores presses. */
  busy?: boolean;
  /** Standalone: a control drawn above the panel, inside the dialog (`/notice` in preview mode: the way back). */
  aside?: ReactNode;
}

export interface NoticePanelProps {
  content: NoticeContent;
  titleId: string;
  bodyId: string;
  heading: "h1" | "h2";
  /** The real notice: the body is a tab stop (it scrolls) and the button acts. Otherwise a picture of it. */
  live: boolean;
  onAcknowledge?: () => void;
  busy?: boolean;
}

/** The notice panel itself — the one drawing of title, body and button that every mode shares. */
export function NoticePanel({ content, titleId, bodyId, heading: Title, live, onAcknowledge, busy = false }: NoticePanelProps) {
  const body = useMemo(() => renderNoticeMarkup(parseNoticeMarkup(content.body)), [content.body]);
  return (
    <div className="notice-panel">
      <Title id={titleId} className="notice-title">
        {content.title}
      </Title>
      <div
        id={bodyId}
        className="notice-body"
        // a long notice scrolls inside the panel: keyboard users need to reach it to scroll it
        // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
        tabIndex={live ? 0 : undefined}
      >
        {body}
      </div>
      <div className="notice-actions">
        <button
          type="button"
          className="notice-button"
          // in the preview the button is a picture of the button: no tab stop, no action, and a
          // screen reader hears it is unavailable (its look is not dimmed: the preview shows the real one)
          tabIndex={live ? undefined : -1}
          aria-disabled={live ? undefined : true}
          // never `disabled` while busy: the focus stays on the button
          aria-busy={live && busy ? true : undefined}
          onClick={live && !busy ? onAcknowledge : undefined}
        >
          {content.button_text}
        </button>
      </div>
    </div>
  );
}

/**
 * The pre-connection notice: title, body (the notice format, `markup.ts`) and one button. Both
 * modes draw the same panel with the same classes, so the editor's preview is what people will see.
 *
 * Standalone is a native `<dialog>` opened with `showModal()`: the browser traps focus and makes the
 * page behind it inert. It cannot be dismissed — Escape is refused (keydown and `cancel`), and if a
 * close gets through anyway (Chromium lets a repeated Escape close a dialog whose `cancel` was
 * already refused) it opens again. Only the button acknowledges.
 */
export function NoticeDialog({ content, mode, onAcknowledge, busy = false, aside }: NoticeDialogProps) {
  const ids = { title: useId(), body: useId() };
  const standalone = mode === "standalone";

  const panel = (
    <NoticePanel
      content={content}
      titleId={ids.title}
      bodyId={ids.body}
      heading={standalone ? "h1" : "h2"}
      live={standalone}
      onAcknowledge={onAcknowledge}
      busy={busy}
    />
  );

  if (!standalone) {
    return (
      <div role="group" aria-label={copy.notice.previewLabel} className="notice-preview">
        {panel}
      </div>
    );
  }
  return (
    <StandaloneDialog titleId={ids.title} bodyId={ids.body}>
      {aside}
      {panel}
    </StandaloneDialog>
  );
}

function StandaloneDialog({ titleId, bodyId, children }: { titleId: string; bodyId: string; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    const open = () => {
      if (!dialog.open) dialog.showModal();
      dialog.querySelector<HTMLButtonElement>(".notice-button")?.focus();
    };
    const refuse = (e: Event) => e.preventDefault();
    const refuseEscape = (e: KeyboardEvent) => {
      if (e.key === "Escape") e.preventDefault();
    };
    dialog.addEventListener("cancel", refuse);
    dialog.addEventListener("keydown", refuseEscape);
    dialog.addEventListener("close", open);
    open();
    return () => {
      dialog.removeEventListener("cancel", refuse);
      dialog.removeEventListener("keydown", refuseEscape);
      dialog.removeEventListener("close", open);
      if (dialog.open) dialog.close();
    };
  }, []);

  return (
    <dialog ref={ref} className="notice-dialog" aria-labelledby={titleId} aria-describedby={bodyId} data-anim="notice">
      {children}
    </dialog>
  );
}
