import { screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { copy } from "@/copy/ko";
import { meFixture } from "../../tests/msw/fixtures";
import { renderWithProviders } from "../../tests/render";

// Chromium has view transitions with types; jsdom has neither, so both are stubbed here.
const start = vi.fn((arg: { update: () => unknown } | (() => unknown)) => {
  const update = typeof arg === "function" ? arg : arg.update;
  const done = Promise.resolve(update()).then(() => undefined);
  return { updateCallbackDone: done, finished: done, ready: done, skipTransition: () => {} };
});
const hadCss = "CSS" in window;

beforeEach(() => {
  start.mockClear();
  Object.defineProperty(document, "startViewTransition", { value: start, configurable: true });
  if (!hadCss) Object.defineProperty(window, "CSS", { value: { supports: () => true }, configurable: true });
  else vi.spyOn(window.CSS, "supports").mockReturnValue(true);
});

afterEach(() => {
  Reflect.deleteProperty(document, "startViewTransition");
  if (!hadCss) Reflect.deleteProperty(window, "CSS");
  vi.restoreAllMocks();
});

it("does not crossfade the first screen, only later navigations (Task 15: clicks are not swallowed after load)", async () => {
  const { router } = renderWithProviders(null, { me: meFixture("admin", "local"), route: "/admin" });
  await screen.findByRole("navigation", { name: copy.nav.label });
  await waitFor(() => expect(router.state.status).toBe("idle"));
  expect(start).not.toHaveBeenCalled();

  await router.navigate({ to: "/admin/mcps" });
  await waitFor(() => expect(router.state.location.pathname).toBe("/admin/mcps"));
  expect(start).toHaveBeenCalledTimes(1);
});
