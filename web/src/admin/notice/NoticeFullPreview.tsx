import { XIcon } from "lucide-react";
import { Dialog as DialogPrimitive } from "radix-ui";
import { useId } from "react";
import { Button } from "@/components/ui/button";
import { copy } from "@/copy/ko";
import type { NoticeContent } from "@/lib/api-types";
import { NoticePanel } from "@/notice/NoticeDialog";

/**
 * The editor's full-screen preview (inside a `Dialog.Root` whose trigger opens it): the saved
 * notice drawn as `/notice` draws it — the same panel and classes on the same backdrop — but in
 * place, over the editor. Closing it is a step back to the editor, never a page with no way out (the
 * desktop app has one window, and `/notice` in a tab is a modal that cannot be dismissed).
 *
 * A modal Radix dialog: the focus moves in (to the close control, the first one), stays in, and goes
 * back to the trigger; the editor behind is aria-hidden and takes no pointer; Escape closes. The
 * notice's own button closes it too and records nothing — this page never reports an acknowledgement.
 */
export function NoticeFullPreview({ content, onClose }: { content: NoticeContent; onClose: () => void }) {
  const ids = { title: useId(), body: useId() };
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Content className="notice-full" data-anim="notice">
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b bg-surface px-4 py-2">
          <div className="flex min-w-0 flex-col gap-0.5">
            {/* the dialog's name, not a heading: the notice's own title is the one heading inside */}
            <DialogPrimitive.Title asChild>
              <p className="text-sm font-semibold text-fg">{copy.notice.fullPreview}</p>
            </DialogPrimitive.Title>
            <DialogPrimitive.Description className="text-xs text-fg-muted">
              {copy.notice.fullPreviewDescription}
            </DialogPrimitive.Description>
          </div>
          <DialogPrimitive.Close asChild>
            <Button variant="outline" size="sm">
              <XIcon aria-hidden="true" />
              {copy.notice.fullPreviewClose}
            </Button>
          </DialogPrimitive.Close>
        </div>
        <div className="notice-full-stage">
          <NoticePanel content={content} titleId={ids.title} bodyId={ids.body} heading="h2" live onAcknowledge={onClose} />
        </div>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}
