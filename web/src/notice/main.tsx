import "@/styles/app.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { applyStoredTheme } from "@/lib/theme";
import { NoticeApp } from "./NoticeApp";

applyStoredTheme(); // before the first paint of React content; no inline <head> script (CSP)

const root = document.getElementById("root");
if (!root) throw new Error("#root not found");

createRoot(root).render(
  <StrictMode>
    <NoticeApp />
  </StrictMode>,
);
