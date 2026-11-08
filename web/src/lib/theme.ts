// Theme preference: light by default; "dark" pins dark and "system" follows the OS through
// `color-scheme: light dark` + light-dark(). The choice is always written to <html data-theme>
// (tokens.css starts in light, so the first paint is light before this runs). Called from each
// entry's main.tsx before the first render (no inline <head> script: CSP is script-src 'self').

export type ThemePref = "system" | "dark" | "light";

export const THEME_STORAGE_KEY = "mcpmon.theme";

/** What a browser without a saved choice gets. */
export const DEFAULT_THEME: ThemePref = "light";

function isThemePref(v: unknown): v is ThemePref {
  return v === "system" || v === "dark" || v === "light";
}

export function getThemePref(): ThemePref {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    return isThemePref(stored) ? stored : DEFAULT_THEME;
  } catch {
    return DEFAULT_THEME; // storage blocked (privacy mode, policy)
  }
}

function apply(pref: ThemePref): void {
  document.documentElement.dataset.theme = pref;
}

/** Applies the saved preference (light when none). Call first thing in every entry. */
export function applyStoredTheme(): void {
  apply(getThemePref());
}

let switchTimer: ReturnType<typeof setTimeout> | undefined;

/**
 * Saves and applies a preference (the default is not stored). Transitions are suppressed for the
 * flip (base.css `[data-theme-switching]`), so every surface changes at once instead of fading.
 */
export function setThemePref(pref: ThemePref): void {
  try {
    if (pref === DEFAULT_THEME) localStorage.removeItem(THEME_STORAGE_KEY);
    else localStorage.setItem(THEME_STORAGE_KEY, pref);
  } catch {
    // not persisted; still applied to this page below
  }
  const root = document.documentElement;
  root.dataset.themeSwitching = "";
  apply(pref);
  clearTimeout(switchTimer);
  // two frames is enough for the new colors to paint; a timer also works in background tabs
  switchTimer = setTimeout(() => delete root.dataset.themeSwitching, 50);
}
