import "@testing-library/jest-dom/vitest";
import { session } from "@/lib/session";
import { server } from "./msw/server";

// ---- MSW: one server for every test file; unknown requests fail the test --------------------

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterEach(() => {
  server.resetHandlers();
  server.events.removeAllListeners(); // trackRequests() and ad-hoc listeners are per test
  session.me = null;
  session.csrf = null;
  session.onUnauthorized = null;
  session.onChange.clear();
});
afterAll(() => server.close());

// ---- jsdom gaps (F15): APIs Radix, cmdk and CodeMirror call that jsdom does not implement ---------

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver;

if (!window.matchMedia) {
  // no media query ever matches: light theme, motion allowed, desktop width
  window.matchMedia = (query: string): MediaQueryList =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList;
}

// TanStack Router's scroll restoration scrolls the window on every navigation
window.scrollTo = () => {};

// Radix Select/Dropdown use pointer capture and scroll the active option into view
Element.prototype.hasPointerCapture ??= () => false;
Element.prototype.setPointerCapture ??= () => {};
Element.prototype.releasePointerCapture ??= () => {};
Element.prototype.scrollIntoView ??= () => {};

// CodeMirror measures text ranges
const emptyRect = (): DOMRect => ({ x: 0, y: 0, width: 0, height: 0, top: 0, right: 0, bottom: 0, left: 0, toJSON: () => ({}) });
Range.prototype.getBoundingClientRect ??= emptyRect;
Range.prototype.getClientRects ??= () =>
  ({ length: 0, item: () => null, [Symbol.iterator]: [][Symbol.iterator] }) as unknown as DOMRectList;
