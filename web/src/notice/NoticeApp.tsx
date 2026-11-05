import { useEffect, useState } from "react";
import { copy } from "@/copy/ko";
import { NoticeDialog } from "./NoticeDialog";
import { loadNoticeContent, notifyHost, type LoadedNotice } from "./source";

type State = { t: "loading" } | { t: "ready"; notice: LoadedNotice } | { t: "failed" } | { t: "acknowledged" };

/**
 * The `/notice` page: load the text, show it as the modal notice, and on the button tell the host
 * and close. React, react-dom and the notice files only — no Motion, Radix or Query (bundle < 100 KB).
 */
export function NoticeApp() {
  const [state, setState] = useState<State>({ t: "loading" });

  useEffect(() => {
    let live = true;
    loadNoticeContent().then(
      (notice) => live && setState({ t: "ready", notice }),
      () => live && setState({ t: "failed" }),
    );
    return () => {
      live = false;
    };
  }, []);

  const acknowledge = (version: number | null) => {
    notifyHost({ type: "notice_ack", version });
    setState({ t: "acknowledged" });
  };

  return (
    <main className="notice-page">
      {state.t === "ready" ? (
        <NoticeDialog content={state.notice} mode="standalone" onAcknowledge={() => acknowledge(state.notice.version)} />
      ) : null}
      {/* one live region for the whole page, present from the start so its changes are announced */}
      <p role="status" className={state.t === "acknowledged" ? "notice-page-message" : "sr-only"}>
        {state.t === "acknowledged" ? copy.notice.acknowledged : state.t === "loading" ? copy.common.loading : ""}
      </p>
      {state.t === "failed" ? (
        <p role="alert" className="notice-page-message">
          {copy.notice.loadFailed}
        </p>
      ) : null}
    </main>
  );
}
