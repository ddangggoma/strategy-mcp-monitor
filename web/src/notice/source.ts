// Where the notice bundle gets its text and where it reports the acknowledgement (U16).
//   - display mode: the session agent opens `/notice#d=<display id>&t=<token>` in the notice window
//     (Plan 4, V15/V16). The page reads the token, takes it out of the address at once, and talks
//     to the Local-only display API with it — `fetch` directly, no cookies (V30).
//   - preview mode: any other address — the local Admin's full-screen preview (Plan 3, F18).
import { copy } from "@/copy/ko";
import type { NoticeContent, NoticeDisplayContent } from "@/lib/api-types";
import { me, notice } from "@/lib/endpoints";

export type NoticeSource = { mode: "display"; displayId: number; token: string } | { mode: "preview" };

const PREVIEW: NoticeSource = { mode: "preview" };
const DISPLAY_ID = /^[1-9]\d*$/;
const TOKEN = /^[A-Za-z0-9_-]{16,128}$/;

/** `"#d=<positive integer>&t=<[A-Za-z0-9_-]{16,128}>"` → display; anything else → preview. */
export function readNoticeSource(hash: string): NoticeSource {
  if (!hash.startsWith("#")) return PREVIEW;
  const params = new URLSearchParams(hash.slice(1));
  const d = params.get("d");
  const t = params.get("t");
  if (d === null || t === null || !DISPLAY_ID.test(d) || !TOKEN.test(t)) return PREVIEW;
  const displayId = Number(d);
  return Number.isSafeInteger(displayId) ? { mode: "display", displayId, token: t } : PREVIEW;
}

/**
 * Reads the source once and, in display mode, removes the token from the address bar (and so from
 * history, a copied URL and the window title bar) before anything else runs.
 */
export function takeNoticeSource(
  loc: Pick<Location, "hash" | "pathname" | "search"> = window.location,
  hist: Pick<History, "replaceState"> = window.history,
): NoticeSource {
  const src = readNoticeSource(loc.hash);
  if (src.mode === "display") hist.replaceState(null, "", loc.pathname + loc.search);
  return src;
}

/** The text to show, and which saved version it is (null: not known to this page). */
export interface LoadedNotice extends NoticeContent {
  version: number | null;
}

/** The display API answered with something other than success; `status` 0 = no answer at all. */
export class NoticeLoadError extends Error {
  readonly status: number;

  constructor(status: number) {
    super(`notice display request failed (${status})`);
    this.name = "NoticeLoadError";
    this.status = status;
  }
}

/** POSTs to the display API with the token; never throws (a network failure is status 0). */
async function displayPost(path: "open" | "ack", token: string): Promise<Response | null> {
  try {
    return await fetch(`/api/notice/display/${path}`, {
      method: "POST",
      headers: { "X-Notice-Token": token },
      credentials: "omit",
      cache: "no-store",
    });
  } catch {
    return null;
  }
}

/**
 * Display mode: the display's pinned text (`notice_shown` is logged by the server on this call);
 * rejects with `NoticeLoadError` (404 = the display is gone: acknowledged, replaced or not ours).
 *
 * Preview mode: a local Admin gets the saved notice (GET /api/notice); anyone else sees the
 * built-in text, so the page never ends on a 401 and never calls an Admin-only route it may not
 * use (F18). Rejects when the server cannot be read.
 */
export async function loadNoticeContent(src: NoticeSource = PREVIEW): Promise<LoadedNotice> {
  if (src.mode === "display") {
    const res = await displayPost("open", src.token);
    if (res?.status !== 200) throw new NoticeLoadError(res?.status ?? 0);
    const n = (await res.json()) as NoticeDisplayContent;
    return { title: n.title, body: n.body, button_text: n.button_text, version: n.version };
  }
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

/** V30: the first try at once, then after 1 s and 2 s. */
const ACK_RETRY_DELAYS_MS: readonly number[] = [1000, 2000];

const wait = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/**
 * Reports the acknowledgement; resolves whether it reached its receiver.
 *
 * Display mode: POST /api/notice/display/ack with the token. 204 → true; 404 → false at once (the
 * display is gone, retrying cannot help); anything else (no answer, 5xx, 403) is tried again after
 * each of `retryDelaysMs`, then false.
 *
 * Preview mode: the WebView2 host bridge when there is one (true), otherwise nobody to tell (false).
 */
export async function notifyHost(
  message: NoticeAck,
  src: NoticeSource = PREVIEW,
  opts: { retryDelaysMs?: readonly number[] } = {},
): Promise<boolean> {
  if (src.mode === "preview") {
    const host = window.chrome?.webview;
    if (!host) return false;
    host.postMessage(message);
    return true;
  }
  const delays = opts.retryDelaysMs ?? ACK_RETRY_DELAYS_MS;
  for (let attempt = 0; ; attempt++) {
    const res = await displayPost("ack", src.token);
    if (res?.status === 204) return true;
    if (res?.status === 404 || attempt >= delays.length) return false;
    await wait(delays[attempt]!);
  }
}
