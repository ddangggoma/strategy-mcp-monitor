import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test as base, expect, type APIRequestContext, type APIResponse, type Locator, type Page } from "@playwright/test";
import { copy } from "../src/copy/ko";
import { THEME_STORAGE_KEY } from "../src/lib/theme";
import {
  AUTH_DIR,
  DEV_OTP_CODE,
  STATE_FILE,
  UI_USERS,
  type BackendState,
  type ChannelName,
  type SavedSession,
  type UiUser,
  type Who,
} from "./backend";

export { expect, copy };
export { DEV_OTP_CODE, UI_USERS, MCP_NAME } from "./backend";
export type { BackendState, ChannelName, UiUser, Who } from "./backend";

function readState(): BackendState {
  return JSON.parse(readFileSync(STATE_FILE, "utf-8")) as BackendState;
}

function readSession(who: Who, channel: ChannelName): SavedSession {
  return JSON.parse(readFileSync(join(AUTH_DIR, `${who}-${channel}.json`), "utf-8")) as SavedSession;
}

export function urlFor(s: BackendState, channel: ChannelName): string {
  return channel === "local" ? s.localUrl : s.externalUrl;
}

const FAILED_RESOURCE = /^Failed to load resource: the server responded with a status of (\d{3})/;

interface Fixtures {
  state: BackendState;
  /** HTTP statuses a test provokes on purpose (e.g. 401 for a wrong code); Chrome logs them as errors. */
  expectedStatuses: number[];
  consoleErrors: string[];
  loginAs(page: Page, who: Who, channel: ChannelName): Promise<void>;
  loginViaUi(page: Page, user: UiUser, channel: ChannelName): Promise<void>;
}

export const test = base.extend<Fixtures>({
  state: async ({}, use) => {
    await use(readState());
  },

  expectedStatuses: [[], { option: true }],

  // Every test ends with no console error (CSP violations included). A failed /api/ request whose
  // status the test declared in `expectedStatuses` is the one exception (F06).
  consoleErrors: [
    async ({ context, expectedStatuses }, use) => {
      const errors: string[] = [];
      context.on("console", (msg) => {
        if (msg.type() !== "error") return;
        const failed = FAILED_RESOURCE.exec(msg.text());
        const url = msg.location().url;
        if (failed && url && new URL(url).pathname.startsWith("/api/") && expectedStatuses.includes(Number(failed[1]))) return;
        errors.push(`${msg.text()} @ ${url}`);
      });
      context.on("weberror", (err) => errors.push(`uncaught: ${err.error().message}`));
      await use(errors);
      expect(errors, "console errors").toEqual([]);
    },
    { auto: true },
  ],

  loginAs: async ({ state }, use) => {
    await use(async (page, who, channel) => {
      const { cookie } = readSession(who, channel);
      await page.context().addCookies([
        { name: cookie.name, value: cookie.value, domain: "127.0.0.1", path: "/", httpOnly: true, sameSite: "Strict" },
      ]);
      await page.goto(`${urlFor(state, channel)}/admin`);
      await expect(page.getByRole("navigation", { name: copy.nav.label })).toBeVisible();
    });
  },

  loginViaUi: async ({ state }, use) => {
    await use(async (page, user, channel) => {
      const base = urlFor(state, channel);
      await page.goto(`${base}/admin/login`);
      await page.getByLabel(copy.login.email).fill(UI_USERS[user].email);
      await page.getByRole("button", { name: copy.login.sendCode }).click();
      await page.getByRole("group", { name: copy.login.codeGroup }).locator("input").first().fill(DEV_OTP_CODE);
      await expect(page).toHaveURL(`${base}/admin`);
    });
  },
});

/** Presses Tab (Shift+Tab with `back`) until `target` has focus (never clicks): the keyboard-only paths use it. */
export async function tabTo(page: Page, target: Locator, { max = 60, back = false }: { max?: number; back?: boolean } = {}): Promise<void> {
  for (let i = 0; i < max; i += 1) {
    if (await target.evaluate((el) => el === document.activeElement).catch(() => false)) return;
    await page.keyboard.press(back ? "Shift+Tab" : "Tab");
  }
  throw new Error(`could not reach ${String(target)} with Tab`);
}

/** The two themes a page can show: light is the default (nothing saved), dark is the saved choice. */
export const THEMES = ["light", "dark"] as const;
export type Theme = (typeof THEMES)[number];

/**
 * Opens every later page of `page` in `theme`: dark is saved in the theme menu's storage before the
 * app runs (what picking "다크" does), light is the default and needs nothing. Call before goto.
 */
export async function useTheme(page: Page, theme: Theme): Promise<void> {
  if (theme === "light") return;
  await page.addInitScript(
    ({ key, value }) => {
      try {
        localStorage.setItem(key, value);
      } catch {
        // about:blank has no storage; the app's pages do
      }
    },
    { key: THEME_STORAGE_KEY, value: theme },
  );
}

/** The page shows `theme` (a check that the theme was not silently left at the default). */
export async function expectTheme(page: Page, theme: Theme): Promise<void> {
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
}

/**
 * Waits until no finite animation is running (panels rising in, digits rolling, bars filling):
 * axe blends a fading element's opacity into its contrast, so it must read the page at rest.
 * Endless ones (the live pulse) and scroll-driven ones (the top bar's shadow, which never "finishes"
 * on the time axis) are left alone; a round that starts new ones (a late SSE reading) is waited out too.
 */
export async function settled(page: Page): Promise<void> {
  await page.evaluate(async () => {
    for (let round = 0; round < 10; round += 1) {
      const running = document
        .getAnimations()
        .filter(
          (a) => a.timeline === document.timeline && a.playState === "running" && a.effect?.getComputedTiming().endTime !== Infinity,
        );
      if (running.length === 0) return;
      await Promise.all(running.map((a) => a.finished.catch(() => undefined)));
    }
  });
}

export interface AdminApi {
  get(path: string): Promise<APIResponse>;
  post(path: string, data?: unknown): Promise<APIResponse>;
  put(path: string, data: unknown): Promise<APIResponse>;
}

/** Calls the Local API as `who` with the session and CSRF token globalSetup saved (no login). */
export async function adminApi(request: APIRequestContext, s: BackendState, who: Who = "admin"): Promise<AdminApi> {
  const { cookie, csrf } = readSession(who, "local");
  const headers = { Cookie: `${cookie.name}=${cookie.value}`, "X-CSRF-Token": csrf };
  return {
    get: (path) => request.get(`${s.localUrl}${path}`, { headers }),
    post: (path, data) => request.post(`${s.localUrl}${path}`, { headers, data }),
    put: (path, data) => request.put(`${s.localUrl}${path}`, { headers, data }),
  };
}
