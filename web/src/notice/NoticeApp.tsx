import { useEffect, useRef, useState } from "react";
import { copy } from "@/copy/ko";
import { NoticeDialog } from "./NoticeDialog";
import { loadNoticeContent, NoticeLoadError, notifyHost, type LoadedNotice, type NoticeSource } from "./source";

type State =
  | { t: "loading" }
  | { t: "ready"; notice: LoadedNotice; sending: boolean }
  /** The button was pressed but the server did not record it: the dialog is gone, a retry button stays. */
  | { t: "ackFailed"; notice: LoadedNotice; sending: boolean }
  | { t: "acknowledged" }
  /** Display mode also offers a retry: the token has left the address, so a reload cannot help. */
  | { t: "loadFailed"; retry: boolean }
  /** Display mode 404: acknowledged already, replaced by a newer connection's notice, or not this session's. */
  | { t: "expired" };

/** Loads the text; never rejects: a failure becomes the state that explains it. */
async function loadState(source: NoticeSource): Promise<State> {
  try {
    return { t: "ready", notice: await loadNoticeContent(source), sending: false };
  } catch (err) {
    const display = source.mode === "display";
    if (display && err instanceof NoticeLoadError && err.status === 404) return { t: "expired" };
    return { t: "loadFailed", retry: display };
  }
}

/**
 * The `/notice` page: load the text, show it as the modal notice, and on the button report the
 * acknowledgement and close. Until the text arrives the page stays empty (no flash of a message).
 * In display mode (the notice window the session agent opens) the report goes to the server with
 * the display's token and can fail: then the page says so and offers a retry. In preview mode there
 * is nothing to record, so the button always ends in the acknowledged message.
 * React, react-dom and the notice files only — no Motion, Radix or Query (bundle < 100 KB).
 */
export function NoticeApp({ source }: { source: NoticeSource }) {
  const [state, setState] = useState<State>({ t: "loading" });
  const alive = useRef(true);
  const sending = useRef(false);
  const retryRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    alive.current = true;
    loadState(source).then((next) => alive.current && setState(next));
    return () => {
      alive.current = false;
    };
  }, [source]);

  const acknowledge = async (notice: LoadedNotice, from: "ready" | "ackFailed") => {
    if (sending.current) return; // one report at a time, however often the button is pressed
    sending.current = true;
    setState({ t: from, notice, sending: true });
    const ok = await notifyHost({ type: "notice_ack", version: notice.version }, source);
    sending.current = false;
    if (!alive.current) return;
    setState(ok || source.mode === "preview" ? { t: "acknowledged" } : { t: "ackFailed", notice, sending: false });
  };

  const retry = () => {
    if (state.t === "ackFailed") {
      void acknowledge(state.notice, "ackFailed");
    } else if (state.t === "loadFailed") {
      setState({ t: "loading" });
      loadState(source).then((next) => alive.current && setState(next));
    }
  };

  // the dialog (and the focus in it) is gone when the report fails: put the focus on the way forward
  const ackFailed = state.t === "ackFailed";
  useEffect(() => {
    if (ackFailed) retryRef.current?.focus();
  }, [ackFailed]);

  const message =
    state.t === "acknowledged" ? copy.notice.acknowledged : state.t === "expired" ? copy.notice.displayExpired : null;
  let problem: string | null = null;
  if (state.t === "ackFailed") problem = copy.notice.ackFailed;
  else if (state.t === "loadFailed") problem = state.retry ? copy.notice.loadFailedRetry : copy.notice.loadFailed;
  const canRetry = state.t === "ackFailed" || (state.t === "loadFailed" && state.retry);
  const retryBusy = state.t === "ackFailed" && state.sending;

  return (
    <main className="notice-page">
      {state.t === "ready" ? (
        <NoticeDialog
          content={state.notice}
          mode="standalone"
          busy={state.sending}
          onAcknowledge={() => void acknowledge(state.notice, "ready")}
        />
      ) : null}
      <div className="notice-page-content">
        {/* one live region for the whole page, present from the start so its changes are announced */}
        <p role="status" className={message ? "notice-page-message" : "sr-only"}>
          {message ?? (state.t === "loading" ? copy.common.loading : "")}
        </p>
        {problem ? (
          <p role="alert" className="notice-page-message">
            {problem}
          </p>
        ) : null}
        {canRetry ? (
          <button
            ref={retryRef}
            type="button"
            className="notice-button"
            // never `disabled` while busy: the focus stays on the button
            aria-busy={retryBusy || undefined}
            onClick={retryBusy ? undefined : retry}
          >
            {copy.notice.retry}
          </button>
        ) : null}
      </div>
    </main>
  );
}
