import { isAdminPath, safeRedirect } from "./redirect";

it.each([
  ["/admin/mcps", "/admin/mcps"],
  ["/", "/"],
  ["/notice", "/notice"],
  [undefined, "/admin"],
  ["//evil.com", "/admin"],
  ["/\\evil.com", "/admin"],
  ["\\\\evil.com", "/admin"],
  ["https://evil.com", "/admin"],
  ["/api/auth/logout", "/admin"],
  // Browsers strip tab/newline/CR from URLs before parsing: these resolve to //evil.com.
  ["/\t/evil.com", "/admin"],
  ["/\n/evil.com", "/admin"],
  ["/\r/evil.com", "/admin"],
  ["\t//evil.com", "/admin"],
  [" //evil.com", "/admin"],
  ["/%09/evil.com", "/admin"],
  ["/%2F/evil.com", "/admin"],
  ["/admin/\u0000x", "/admin"],
  ["/admin\u007f", "/admin"],
  ["/administrator", "/admin"],
  ["/assets/x.js", "/admin"],
])("safeRedirect(%j) = %s", (raw, out) => expect(safeRedirect(raw)).toBe(out));

it("keeps the query and hash, and uses the given fallback", () => {
  expect(safeRedirect("/admin/mcps/3?tab=history")).toBe("/admin/mcps/3?tab=history");
  expect(safeRedirect("/admin/mcps/3?tab=history#x")).toBe("/admin/mcps/3?tab=history#x");
  expect(safeRedirect("", "/x")).toBe("/x");
  expect(safeRedirect("javascript:alert(1)", "/x")).toBe("/x");
  expect(safeRedirect("/api", "/x")).toBe("/x"); // not a page this app serves
});

it("returns the normalised same-origin path, never a host", () => {
  expect(safeRedirect("/admin/../admin/mcps")).toBe("/admin/mcps");
  expect(safeRedirect(`${window.location.origin}/admin/users`)).toBe("/admin/users");
});

it.each([
  ["/admin", true],
  ["/admin/", true],
  ["/admin?x=1", true],
  ["/admin/mcps/3?tab=history", true],
  ["/", false],
  ["/administrator", false],
  ["/notice", false],
])("isAdminPath(%s) = %s", (path, out) => expect(isAdminPath(path)).toBe(out));
