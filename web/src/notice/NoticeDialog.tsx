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
export function NoticeDialog({ content, mode, onAcknowledge, busy = false }: NoticeDialogProps) {
  const ids = { title: useId(), body: useId() };
  const body = useMemo(() => renderNoticeMarkup(parseNoticeMarkup(content.body)), [content.body]);
  const standalone = mode === "standalone";
  const Title = standalone ? "h1" : "h2";

  const panel = (
    <div className="notice-panel">
      <Title id={ids.title} className="notice-title">
        {content.title}
      </Title>
      <div
        id={ids.body}
        className="notice-body"
        // a long notice scrolls inside the panel: keyboard users need to reach it to scroll it
        // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
        tabIndex={standalone ? 0 : undefined}
      >
        {body}
      </div>
      <div className="notice-actions">
        <button
          type="button"
          className="notice-button"
          // in the preview the button is a picture of the button: no tab stop, no action, and a
          // screen reader hears it is unavailable (its look is not dimmed: the preview shows the real one)
          tabIndex={standalone ? undefined : -1}
          aria-disabled={standalone ? undefined : true}
          // never `disabled` while busy: the focus stays on the button
          aria-busy={standalone && busy ? true : undefined}
          onClick={standalone && !busy ? onAcknowledge : undefined}
        >
          {content.button_text}
        </button>
      </div>
    </div>
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
