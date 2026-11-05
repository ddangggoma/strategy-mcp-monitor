import "@/styles/app.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { copy } from "@/copy/ko";
import { applyStoredTheme } from "@/lib/theme";

applyStoredTheme(); // before the first paint of React content; no inline <head> script (CSP)

const root = document.getElementById("root");
if (!root) throw new Error("#root not found");

createRoot(root).render(
  <StrictMode>
    <h1>{copy.board.title}</h1>
  </StrictMode>,
);
