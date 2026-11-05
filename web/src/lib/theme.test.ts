import { applyStoredTheme, getThemePref, setThemePref, THEME_STORAGE_KEY } from "./theme";

const root = document.documentElement;

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  delete root.dataset.theme;
});

it("stores the preference and sets data-theme; system removes it", () => {
  setThemePref("light");
  expect(root.dataset.theme).toBe("light");
  expect(getThemePref()).toBe("light");
  expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");

  setThemePref("system");
  expect(root.dataset.theme).toBeUndefined();
  expect(getThemePref()).toBe("system");
  expect(localStorage.getItem(THEME_STORAGE_KEY)).toBeNull();
});

it("uses the mcpmon.theme key", () => {
  expect(THEME_STORAGE_KEY).toBe("mcpmon.theme");
});

it("applyStoredTheme restores the saved preference on page start", () => {
  localStorage.setItem("mcpmon.theme", "dark");
  applyStoredTheme();
  expect(root.dataset.theme).toBe("dark");
});

it("treats an unknown stored value as system", () => {
  localStorage.setItem("mcpmon.theme", "sepia");
  expect(getThemePref()).toBe("system");
  root.dataset.theme = "dark";
  applyStoredTheme();
  expect(root.dataset.theme).toBeUndefined();
});

it("survives a throwing localStorage", () => {
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new DOMException("quota", "QuotaExceededError");
  });
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new DOMException("denied", "SecurityError");
  });
  expect(() => setThemePref("dark")).not.toThrow();
  // the choice still applies to this page even though it could not be saved
  expect(root.dataset.theme).toBe("dark");
  expect(getThemePref()).toBe("system");
  expect(() => applyStoredTheme()).not.toThrow();
});

it("suppresses transitions while the theme flips, then lifts the guard", async () => {
  setThemePref("dark");
  expect(root.dataset.themeSwitching).toBe("");
  await new Promise((r) => setTimeout(r, 120));
  expect(root.dataset.themeSwitching).toBeUndefined();
});
