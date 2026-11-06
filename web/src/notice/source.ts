// Where the notice bundle gets its text and where it reports the acknowledgement (U16).
//   - display mode: the session agent opens `/notice#d=<display id>&t=<token>` in the notice window
//     (Plan 4, V15/V16). The page reads the token, takes it out of the address at once, and talks
//     to the Local-only display API with it — `fetch` directly, no cookies (V30). The token stays
//     only in the page's own history entry (`history.state`), so a reload (F5) is still the display.
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

/** What the history entry keeps of a display source (`history.state`). */
interface KeptSource {
  noticeDisplay: { d: number; t: string };
}

function keptSource(state: unknown): NoticeSource {
  const kept: unknown = (state as Partial<KeptSource> | null | undefined)?.noticeDisplay;
  if (typeof kept !== "object" || kept === null) return PREVIEW;
  const { d, t } = kept as Record<string, unknown>;
  if (typeof d !== "number" || !Number.isSafeInteger(d) || d < 1 || typeof t !== "string" || !TOKEN.test(t)) return PREVIEW;
  return { mode: "display", displayId: d, token: t };
}

/**
 * Reads the source once and, in display mode, removes the token from the address bar (and so from
 * a copied URL and the window title bar) before anything else runs. The source moves into the
 * history entry's state, which a reload of the notice window (F5) reads back: without it the reload
 * would fall back to preview mode, and its button would record nothing. A new address always wins.
 */
export function takeNoticeSource(
  loc: Pick<Location, "hash" | "pathname" | "search"> = window.location,
  hist: Pick<History, "replaceState" | "state"> = window.history,
): NoticeSource {
  const src = readNoticeSource(loc.hash);
  if (src.mode !== "display") return keptSource(hist.state);
  const kept: KeptSource = { noticeDisplay: { d: src.displayId, t: src.token } };
  hist.replaceState(kept, "", loc.pathname + loc.search);
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
 * How the acknowledgement report ended: `sent` reached its receiver; `expired` = the display is
 * gone (acknowledged, replaced by a newer connection's notice, or not ours), so retrying cannot
 * help; `failed` = it did not get through, and a retry may.
 */
export type AckResult = "sent" | "expired" | "failed";

/**
 * Reports the acknowledgement.
 *
 * Display mode: POST /api/notice/display/ack with the token. 204 → `sent`; 404 → `expired` at
 * once; anything else (no answer, 5xx, 403) is tried again after each of `retryDelaysMs`, then
 * `failed`.
 *
 * Preview mode: the WebView2 host bridge when there is one (`sent`), otherwise nobody to tell
 * (`failed`).
 */
export async function notifyHost(
  message: NoticeAck,
  src: NoticeSource = PREVIEW,
  opts: { retryDelaysMs?: readonly number[] } = {},
): Promise<AckResult> {
  if (src.mode === "preview") {
    const host = window.chrome?.webview;
    if (!host) return "failed";
    host.postMessage(message);
    return "sent";
  }
  const delays = opts.retryDelaysMs ?? ACK_RETRY_DELAYS_MS;
  for (let attempt = 0; ; attempt++) {
    const res = await displayPost("ack", src.token);
    if (res?.status === 204) return "sent";
    if (res?.status === 404) return "expired";
    if (attempt >= delays.length) return "failed";
    await wait(delays[attempt]!);
  }
}
