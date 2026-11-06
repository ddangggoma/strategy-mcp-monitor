import "@/styles/app.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { applyStoredTheme } from "@/lib/theme";
import { NoticeApp } from "./NoticeApp";
import { takeNoticeSource } from "./source";

applyStoredTheme(); // before the first paint of React content; no inline <head> script (CSP)
// read once, before anything else: in display mode this also takes the token out of the address bar
const source = takeNoticeSource();

const root = document.getElementById("root");
if (!root) throw new Error("#root not found");

createRoot(root).render(
  <StrictMode>
    <NoticeApp source={source} />
  </StrictMode>,
);
