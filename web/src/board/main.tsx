import "@/styles/app.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BoardStore } from "@/lib/board-store";
import { BoardStreamClient } from "@/lib/board-stream";
import { refreshSession } from "@/lib/session";
import { applyStoredTheme } from "@/lib/theme";
import { BoardPage } from "./BoardPage";

applyStoredTheme(); // before the first paint of React content; no inline <head> script (CSP)

// one store and one stream per tab (U5); the page restarts the stream after logout
const store = new BoardStore();
const stream = new BoardStreamClient({
  onEvent: (e) => store.apply(e),
  onStatus: (s) => store.setStatus(s),
});
stream.start();
refreshSession().catch(() => {}); // the account area stays empty until the server answers

const root = document.getElementById("root");
if (!root) throw new Error("#root not found");

createRoot(root).render(
  <StrictMode>
    <BoardPage store={store} stream={stream} />
  </StrictMode>,
);
