// Theme preference: "system" follows the OS through `color-scheme: light dark` + light-dark();
// "dark"/"light" pin it with <html data-theme>. Called from each entry's main.tsx before the
// first render (no inline <head> script: CSP is script-src 'self').

export type ThemePref = "system" | "dark" | "light";

export const THEME_STORAGE_KEY = "mcpmon.theme";

function isPinned(v: unknown): v is "dark" | "light" {
  return v === "dark" || v === "light";
}

export function getThemePref(): ThemePref {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    return isPinned(stored) ? stored : "system";
  } catch {
    return "system"; // storage blocked (privacy mode, policy): fall back to the OS
  }
}

function apply(pref: ThemePref): void {
  const root = document.documentElement;
  if (isPinned(pref)) root.dataset.theme = pref;
  else delete root.dataset.theme;
}

/** Applies the saved preference. Call first thing in every entry. */
export function applyStoredTheme(): void {
  apply(getThemePref());
}

let switchTimer: ReturnType<typeof setTimeout> | undefined;

/**
 * Saves and applies a preference. Transitions are suppressed for the flip (base.css
 * `[data-theme-switching]`), so every surface changes at once instead of fading piecemeal.
 */
export function setThemePref(pref: ThemePref): void {
  try {
    if (isPinned(pref)) localStorage.setItem(THEME_STORAGE_KEY, pref);
    else localStorage.removeItem(THEME_STORAGE_KEY);
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
