// Where to go after login. `redirect` comes from the URL, so it is untrusted. A prefix check on
// the raw text is not enough: browsers strip tab/newline before parsing (`/\t/evil.com` becomes
// `//evil.com`) and treat `\` like `/`. So the value is resolved the way the browser would resolve
// it, and only a same-origin page of this app (board, notice, admin) is followed.

// eslint-disable-next-line no-control-regex -- the point is to reject control characters
const CONTROL = /[\u0000-\u001f\u007f]/;

function isPagePath(path: string): boolean {
  return path === "/" || path === "/notice" || isAdminPath(path);
}

/** A same-origin page path (`pathname + search + hash`) when `raw` is safe, else `fallback`. */
export function safeRedirect(raw: string | undefined, fallback = "/admin"): string {
  if (!raw || CONTROL.test(raw) || raw.trim() !== raw) return fallback;
  let url: URL;
  try {
    url = new URL(raw, window.location.origin);
  } catch {
    return fallback;
  }
  if (url.origin !== window.location.origin || !isPagePath(url.pathname)) return fallback;
  return url.pathname + url.search + url.hash;
}

/** True for `/admin` and anything below it: those pages belong to the admin router. */
export function isAdminPath(href: string): boolean {
  const path = href.split(/[?#]/, 1)[0] ?? "";
  return path === "/admin" || path.startsWith("/admin/");
}

/**
 * A full page load, for targets outside the admin router (the board at `/` is another HTML entry,
 * F11). An object so tests can replace `assign` (jsdom does not navigate).
 */
export const documentNav = {
  assign(href: string): void {
    window.location.assign(href);
  },
};
