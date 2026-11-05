import { isAdminPath, safeRedirect } from "./redirect";

it.each([
  ["/admin/mcps", "/admin/mcps"],
  ["/", "/"],
  [undefined, "/admin"],
  ["//evil.com", "/admin"],
  ["/\\evil.com", "/admin"],
  ["https://evil.com", "/admin"],
  ["/api/auth/logout", "/admin"],
])("safeRedirect(%s) = %s", (raw, out) => expect(safeRedirect(raw)).toBe(out));

it("keeps the query and uses the given fallback", () => {
  expect(safeRedirect("/admin/mcps/3?tab=history")).toBe("/admin/mcps/3?tab=history");
  expect(safeRedirect("", "/x")).toBe("/x");
  expect(safeRedirect("javascript:alert(1)", "/x")).toBe("/x");
  expect(safeRedirect("/api", "/x")).toBe("/api"); // only the /api/ prefix is the API
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
