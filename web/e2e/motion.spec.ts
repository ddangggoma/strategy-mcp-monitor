// Reduced motion (constraints: no CSS animation, transition or view transition under
// prefers-reduced-motion: reduce). Each check also runs once with motion allowed, so a check that
// finds nothing to stop fails instead of passing vacuously (F08).
//
// The board has no live pulse (sessions arrive in Plan 4) and no RECOVERING card unless a failure
// is staged, so those two are checked on real board elements put into that state: the presence dot
// the ConnectionBanner renders for a connected session, and the calculator card marked as
// recovering (data-anim="spin" is exactly what McpCard sets for RECOVERING).
import type { Page } from "@playwright/test";
import { MCP_NAME, copy, expect, test } from "./fixtures";

interface Motion {
  /** Every [data-anim] element on the page, with its own and its pseudo-elements' animations. */
  marked: { anim: string; durations: number[] }[];
  ringAnimation: string;
  pulseAnimation: string;
}

async function inspectBoard(page: Page): Promise<Motion> {
  return page.evaluate(() => {
    const seconds = (v: string) => Math.max(...v.split(",").map((d) => (d.trim().endsWith("ms") ? parseFloat(d) / 1000 : parseFloat(d))));
    const animated = (s: CSSStyleDeclaration) => (s.animationName === "none" ? 0 : seconds(s.animationDuration));
    const marked = [...document.querySelectorAll<HTMLElement>("[data-anim]")].map((el) => ({
      anim: el.dataset.anim ?? "",
      durations: [animated(getComputedStyle(el)), animated(getComputedStyle(el, "::before")), animated(getComputedStyle(el, "::after"))],
    }));
    const card = document.querySelector<HTMLElement>("[data-testid='mcp-card']");
    if (!card) throw new Error("no card");
    card.dataset.anim = "spin"; // McpCard's RECOVERING marker
    const ringAnimation = getComputedStyle(card, "::before").animationName;
    delete card.dataset.anim;
    const dot = document.createElement("span");
    dot.className = "presence-dot";
    dot.dataset.presence = "on";
    dot.dataset.anim = "pulse"; // what ConnectionBanner renders while someone is connected
    document.body.append(dot);
    const pulseAnimation = getComputedStyle(dot, "::after").animationName;
    dot.remove();
    return { marked, ringAnimation, pulseAnimation };
  });
}

/** Counts, for each route change, the view-transition animations running once the transition is ready. */
async function recordViewTransitions(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const w = window as unknown as { __vt: number[] };
    w.__vt = [];
    const start = document.startViewTransition?.bind(document);
    if (!start) return;
    document.startViewTransition = ((arg: Parameters<typeof start>[0]) => {
      const vt = start(arg);
      void vt.ready
        .then(() => {
          const running = document
            .getAnimations()
            .filter((a) => String((a.effect as KeyframeEffect | null)?.pseudoElement ?? "").startsWith("::view-transition"));
          w.__vt.push(running.length);
        })
        .catch(() => w.__vt.push(0));
      return vt;
    }) as typeof document.startViewTransition;
  });
}

async function navigateAdmin(page: Page, url: string): Promise<number[]> {
  await page.goto(`${url}/admin`);
  const nav = page.getByRole("navigation", { name: copy.nav.label });
  await nav.getByRole("link", { name: copy.nav.mcps }).click();
  await expect(page.getByRole("table", { name: copy.mcp.listLabel }).getByRole("row", { name: new RegExp(MCP_NAME) })).toBeVisible();
  await nav.getByRole("link", { name: copy.nav.dashboard }).click();
  await expect(page.getByRole("heading", { level: 1, name: copy.dashboard.title })).toBeVisible();
  await expect.poll(() => page.evaluate(() => (window as unknown as { __vt: number[] }).__vt.length)).toBeGreaterThanOrEqual(2);
  return page.evaluate(() => (window as unknown as { __vt: number[] }).__vt);
}

test.describe("prefers-reduced-motion: reduce", () => {
  test.use({ reducedMotion: "reduce" });

  test("reduced motion stops the pulse, the recovering ring and every marked animation on the board", async ({ page, state }) => {
    await page.goto(`${state.externalUrl}/`);
    await expect(page.getByTestId("mcp-card").getByText(copy.states.HEALTHY)).toBeVisible();
    expect(await page.evaluate(() => matchMedia("(prefers-reduced-motion: reduce)").matches)).toBe(true);
    const m = await inspectBoard(page);
    expect(m.marked.length).toBeGreaterThan(0);
    for (const el of m.marked) for (const d of el.durations) expect(d, `[data-anim=${el.anim}]`).toBeLessThanOrEqual(0.0001);
    expect(m.ringAnimation).toBe("none");
    expect(m.pulseAnimation).toBe("none");
  });

  test("reduced motion turns off route view transitions", async ({ page, state, loginAs }) => {
    await recordViewTransitions(page);
    await loginAs(page, "admin", "local");
    const counts = await navigateAdmin(page, state.localUrl);
    expect(counts.every((n) => n === 0)).toBe(true);
  });
});

test.describe("motion allowed (control)", () => {
  test.use({ reducedMotion: "no-preference" });

  test("the same checks find running animations when motion is allowed", async ({ page, state, loginAs }) => {
    await page.goto(`${state.externalUrl}/`);
    await expect(page.getByTestId("mcp-card").getByText(copy.states.HEALTHY)).toBeVisible();
    const m = await inspectBoard(page);
    expect(m.ringAnimation).not.toBe("none");
    expect(m.pulseAnimation).not.toBe("none");

    await recordViewTransitions(page);
    await loginAs(page, "admin", "local");
    const counts = await navigateAdmin(page, state.localUrl);
    expect(counts.some((n) => n > 0)).toBe(true);
  });
});
