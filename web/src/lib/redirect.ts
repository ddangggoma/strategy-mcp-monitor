// Where to go after login. `redirect` comes from the URL, so it is untrusted: only same-origin
// paths are followed (no `//host` or `/\host`, which browsers treat as another host), and never
// an API route.

/** `raw` when it is a safe same-origin page path (query kept), else `fallback`. */
export function safeRedirect(raw: string | undefined, fallback = "/admin"): string {
  if (!raw || !raw.startsWith("/")) return fallback;
  if (raw.startsWith("//") || raw.startsWith("/\\")) return fallback;
  if (raw.startsWith("/api/")) return fallback;
  return raw;
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
