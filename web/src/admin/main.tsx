import "@/styles/app.css";
import { QueryClient } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { ApiError } from "@/lib/api";
import { BoardStore } from "@/lib/board-store";
import { BoardStreamClient } from "@/lib/board-stream";
import { refreshSession } from "@/lib/session";
import { applyStoredTheme } from "@/lib/theme";
import { connectLive, type LiveValue } from "./live";
import { AdminApp, createAdminRouter } from "./router";

applyStoredTheme(); // before the first paint of React content; no inline <head> script (CSP)

const qc = new QueryClient({
  defaultOptions: {
    queries: {
      // a 4xx will not change on retry (401 also hands over to login); network and 5xx retry
      retry: (failures, error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500) && failures < 3,
    },
  },
});

// one store and one stream per tab (U5), mirrored into the query cache
const store = new BoardStore();
const stream = new BoardStreamClient({
  onEvent: (e) => store.apply(e),
  onStatus: (s) => store.setStatus(s),
});
connectLive(store, qc);
stream.start();

const live: LiveValue = { store, stream, tracker: null };
const router = createAdminRouter({ qc });

const root = document.getElementById("root");
if (!root) throw new Error("#root not found");

// routes decide login/setup from the session, so it is loaded first (a failure reads as anonymous)
void refreshSession()
  .catch(() => {})
  .finally(() => {
    createRoot(root).render(
      <StrictMode>
        <AdminApp router={router} qc={qc} live={live} />
      </StrictMode>,
    );
  });
