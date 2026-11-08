import { applyStoredTheme, DEFAULT_THEME, getThemePref, setThemePref, THEME_STORAGE_KEY } from "./theme";

const root = document.documentElement;

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  delete root.dataset.theme;
});

it("defaults to light", () => {
  expect(DEFAULT_THEME).toBe("light");
  expect(getThemePref()).toBe("light");
  applyStoredTheme();
  expect(root.dataset.theme).toBe("light");
});

it("stores a non-default preference and always sets data-theme", () => {
  setThemePref("dark");
  expect(root.dataset.theme).toBe("dark");
  expect(getThemePref()).toBe("dark");
  expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");

  setThemePref("system");
  expect(root.dataset.theme).toBe("system"); // base.css lets the OS choose under this value
  expect(getThemePref()).toBe("system");
  expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("system");

  setThemePref("light");
  expect(root.dataset.theme).toBe("light");
  expect(localStorage.getItem(THEME_STORAGE_KEY)).toBeNull(); // the default needs no entry
});

it("uses the mcpmon.theme key", () => {
  expect(THEME_STORAGE_KEY).toBe("mcpmon.theme");
});

it("applyStoredTheme restores the saved preference on page start", () => {
  localStorage.setItem("mcpmon.theme", "dark");
  applyStoredTheme();
  expect(root.dataset.theme).toBe("dark");
});

it("treats an unknown stored value as the default", () => {
  localStorage.setItem("mcpmon.theme", "sepia");
  expect(getThemePref()).toBe("light");
  root.dataset.theme = "dark";
  applyStoredTheme();
  expect(root.dataset.theme).toBe("light");
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
  expect(getThemePref()).toBe("light");
  expect(() => applyStoredTheme()).not.toThrow();
});

it("suppresses transitions while the theme flips, then lifts the guard", async () => {
  setThemePref("dark");
  expect(root.dataset.themeSwitching).toBe("");
  await new Promise((r) => setTimeout(r, 120));
  expect(root.dataset.themeSwitching).toBeUndefined();
});
