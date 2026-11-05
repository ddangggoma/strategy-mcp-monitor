// Where the notice bundle gets its text and where it reports the acknowledgement (U16). Plan 4
// replaces both functions (the RDP host shows the dialog); nothing else in the bundle changes.
import { copy } from "@/copy/ko";
import type { NoticeContent } from "@/lib/api-types";
import { me, notice } from "@/lib/endpoints";

/** The text to show, and which saved version it is (null: not known to this page). */
export type LoadedNotice = NoticeContent & { version: number | null };

/**
 * For now `/notice` is the local Admin's full-screen preview: a local Admin gets the saved notice
 * (GET /api/notice); anyone else sees the built-in text, so the page never ends on a 401 and never
 * calls an Admin-only route it may not use (F18). Rejects when the server cannot be read.
 */
export async function loadNoticeContent(): Promise<LoadedNotice> {
  const who = await me();
  if (who.channel !== "local" || who.user?.role !== "admin") return { ...copy.notice.builtIn, version: null };
  const n = await notice();
  return { title: n.title, body: n.body, button_text: n.button_text, version: n.version };
}

export interface NoticeAck {
  type: "notice_ack";
  version: number | null;
}

declare global {
  interface Window {
    /** WebView2 host bridge; Chrome's own `window.chrome` has no `webview`. */
    chrome?: { webview?: { postMessage(message: unknown): void } };
  }
}

/** Tells the WebView2 host the notice was acknowledged; in an ordinary browser it does nothing. */
export function notifyHost(message: NoticeAck): void {
  window.chrome?.webview?.postMessage(message);
}
