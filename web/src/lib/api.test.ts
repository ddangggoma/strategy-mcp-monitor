import { http, HttpResponse } from "msw";
import { meFixture } from "../../tests/msw/fixtures";
import { server } from "../../tests/msw/server";
import { ApiError, api, apiUrl } from "./api";
import * as endpoints from "./endpoints";
import { session } from "./session";

it("builds absolute same-origin URLs with a query string", () => {
  expect(apiUrl("/api/mcps/1/history", { hours: 24 })).toBe(`${location.origin}/api/mcps/1/history?hours=24`);
  expect(apiUrl("/api/board")).toBe(`${location.origin}/api/board`);
});

it("adds X-CSRF-Token on unsafe methods only", async () => {
  session.csrf = "tok-1";
  const seen: [string, string | null][] = [];
  server.use(
    http.all("/api/probe", ({ request }) => {
      seen.push([request.method, request.headers.get("X-CSRF-Token")]);
      return HttpResponse.json({ ok: true });
    }),
  );
  for (const method of ["GET", "POST", "PUT", "PATCH", "DELETE"] as const) await api("/api/probe", { method });
  expect(seen).toEqual([
    ["GET", null],
    ["POST", "tok-1"],
    ["PUT", "tok-1"],
    ["PATCH", "tok-1"],
    ["DELETE", "tok-1"],
  ]);
});

it("sends JSON bodies and same-origin credentials", async () => {
  let got: unknown = null;
  let type: string | null = null;
  server.use(
    http.put("/api/mcps/:id", async ({ request }) => {
      got = await request.json();
      type = request.headers.get("Content-Type");
      return HttpResponse.json({ id: 1 });
    }),
  );
  const spy = vi.spyOn(globalThis, "fetch");
  await endpoints.updateMcp(1, { maintenance: true });
  expect(got).toEqual({ maintenance: true });
  expect(type).toBe("application/json");
  expect(spy.mock.calls[0]?.[1]).toMatchObject({ credentials: "same-origin", method: "PUT" });
  spy.mockRestore();
});

it("maps the error body to ApiError and reads Retry-After", async () => {
  server.use(
    http.post("/api/auth/otp/request", () =>
      HttpResponse.json({ error: "rate_limited" }, { status: 429, headers: { "Retry-After": "42" } }),
    ),
  );
  const err = await endpoints.otpRequest("a@x.com").catch((e: unknown) => e);
  expect(err).toBeInstanceOf(ApiError);
  expect(err).toMatchObject({ status: 429, code: "rate_limited", retryAfterSec: 42 });
});

it("leaves retryAfterSec null without a usable Retry-After", async () => {
  server.use(http.get("/api/board", () => HttpResponse.json({ error: "not_found" }, { status: 404, headers: { "Retry-After": "soon" } })));
  await expect(endpoints.board()).rejects.toMatchObject({ status: 404, code: "not_found", retryAfterSec: null });
});

it("retries once after a csrf refresh", async () => {
  session.me = meFixture("admin", "local");
  session.csrf = "old";
  const putTokens: (string | null)[] = [];
  let meCalls = 0;
  server.use(
    http.put("/api/settings", ({ request }) => {
      const token = request.headers.get("X-CSRF-Token");
      putTokens.push(token);
      return token === "new"
        ? HttpResponse.json({ ping_interval_sec: 7 })
        : HttpResponse.json({ error: "csrf" }, { status: 403 });
    }),
    http.get("/api/auth/me", () => {
      meCalls++;
      return HttpResponse.json({ ...meFixture("admin", "local"), csrf_token: "new" });
    }),
  );
  await expect(endpoints.updateSettings({ ping_interval_sec: 7 })).resolves.toEqual({ ping_interval_sec: 7 });
  expect(putTokens).toEqual(["old", "new"]);
  expect(meCalls).toBe(1);
  expect(session.csrf).toBe("new");
});

it("does not loop on repeated csrf", async () => {
  session.me = meFixture("admin", "local");
  session.csrf = "old";
  let puts = 0;
  let meCalls = 0;
  server.use(
    http.put("/api/settings", () => {
      puts++;
      return HttpResponse.json({ error: "csrf" }, { status: 403 });
    }),
    http.get("/api/auth/me", () => {
      meCalls++;
      return HttpResponse.json({ ...meFixture("admin", "local"), csrf_token: "new" });
    }),
  );
  await expect(endpoints.updateSettings({ ping_interval_sec: 7 })).rejects.toMatchObject({ status: 403, code: "csrf" });
  expect(puts).toBe(2);
  expect(meCalls).toBe(1);
});

it("does not replay a mutation as another user after a csrf refresh (RF2)", async () => {
  session.me = meFixture("admin", "local", 1); // the tab shows (and acts for) user 1
  session.csrf = "old";
  let puts = 0;
  const onUnauthorized = vi.fn();
  session.onUnauthorized = onUnauthorized;
  server.use(
    http.put("/api/settings", () => {
      puts++;
      return HttpResponse.json({ error: "csrf" }, { status: 403 });
    }),
    // another tab logged out and user 2 logged in on the same channel: the shared cookie is theirs
    http.get("/api/auth/me", () => HttpResponse.json(meFixture("admin", "local", 2))),
  );
  await expect(endpoints.updateSettings({ ping_interval_sec: 7 })).rejects.toMatchObject({ status: 403, code: "session_changed" });
  expect(puts).toBe(1); // never sent again under the other user's session
  expect(session.me?.user?.id).toBe(2); // the tab now shows who is really logged in
  expect(onUnauthorized).not.toHaveBeenCalled();
});

it("sends the tab to login, without a retry, when the csrf refresh finds no session", async () => {
  session.me = meFixture("admin", "local", 1);
  session.csrf = "old";
  let puts = 0;
  const onUnauthorized = vi.fn();
  session.onUnauthorized = onUnauthorized;
  server.use(
    http.put("/api/settings", () => {
      puts++;
      return HttpResponse.json({ error: "csrf" }, { status: 403 });
    }),
    http.get("/api/auth/me", () => HttpResponse.json(meFixture(null, "local"))),
  );
  await expect(endpoints.updateSettings({ ping_interval_sec: 7 })).rejects.toMatchObject({ status: 401, code: "login_required" });
  expect(puts).toBe(1);
  expect(onUnauthorized).toHaveBeenCalledTimes(1);
});

it("compares with the user the request was made for, not one set while it was in flight", async () => {
  session.me = meFixture("admin", "local", 1);
  session.csrf = "old";
  let puts = 0;
  server.use(
    http.put("/api/settings", () => {
      puts++;
      session.me = meFixture("admin", "local", 2); // e.g. a refresh elsewhere while this was in flight
      return HttpResponse.json({ error: "csrf" }, { status: 403 });
    }),
    http.get("/api/auth/me", () => HttpResponse.json(meFixture("admin", "local", 2))),
  );
  await expect(endpoints.updateSettings({ ping_interval_sec: 7 })).rejects.toMatchObject({ code: "session_changed" });
  expect(puts).toBe(1);
});

it("does not refresh on a 403 that is not csrf", async () => {
  let meCalls = 0;
  server.use(
    http.get("/api/users", () => HttpResponse.json({ error: "forbidden" }, { status: 403 })),
    http.get("/api/auth/me", () => {
      meCalls++;
      return HttpResponse.json(meFixture("admin", "local"));
    }),
  );
  await expect(endpoints.users()).rejects.toMatchObject({ status: 403, code: "forbidden" });
  expect(meCalls).toBe(0);
});

it("calls onUnauthorized on 401 outside /api/auth/", async () => {
  const onUnauthorized = vi.fn();
  session.onUnauthorized = onUnauthorized;
  server.use(
    http.get("/api/mcps", () => HttpResponse.json({ error: "login_required" }, { status: 401 })),
    http.post("/api/auth/otp/verify", () => HttpResponse.json({ error: "login_required" }, { status: 401 })),
  );
  await expect(endpoints.mcps()).rejects.toMatchObject({ status: 401, code: "login_required" });
  expect(onUnauthorized).toHaveBeenCalledTimes(1);
  await expect(endpoints.otpVerify("a@x.com", "123456")).rejects.toMatchObject({ status: 401 });
  expect(onUnauthorized).toHaveBeenCalledTimes(1);
});

it("returns undefined for 204 and maps non-JSON 500 and network errors", async () => {
  server.use(
    http.delete("/api/mcps/:id", () => new HttpResponse(null, { status: 204 })),
    http.get("/api/mcps/:id", () => new HttpResponse("<html>boom</html>", { status: 500, headers: { "Content-Type": "text/html" } })),
    http.get("/api/board", () => HttpResponse.error()),
  );
  await expect(endpoints.deleteMcp(3)).resolves.toBeUndefined();
  await expect(endpoints.mcp(3)).rejects.toMatchObject({ status: 500, code: "internal" });
  const err = await endpoints.board().catch((e: unknown) => e);
  expect(err).toBeInstanceOf(ApiError);
  expect(err).toMatchObject({ status: 0, code: "network" });
});

it("maps a JSON error body without a string code to internal", async () => {
  server.use(http.get("/api/board", () => HttpResponse.json({ detail: "x" }, { status: 422 })));
  await expect(endpoints.board()).rejects.toMatchObject({ status: 422, code: "internal" });
});

it("rethrows an abort as-is so callers can tell cancellation from failure", async () => {
  const ctrl = new AbortController();
  ctrl.abort();
  const err = await api("/api/board", { signal: ctrl.signal }).catch((e: unknown) => e);
  expect(err).not.toBeInstanceOf(ApiError);
  expect((err as Error).name).toBe("AbortError");
});

it("every endpoint calls its Appendix B method and path", async () => {
  const seen: string[] = [];
  server.events.on("request:start", ({ request }) => {
    const u = new URL(request.url);
    seen.push(`${request.method} ${u.pathname}${u.search}`);
  });
  session.csrf = "t";
  const calls: [() => Promise<unknown>, string][] = [
    [() => endpoints.me(), "GET /api/auth/me"],
    [() => endpoints.otpRequest("a@x.com"), "POST /api/auth/otp/request"],
    [() => endpoints.otpVerify("a@x.com", "123456"), "POST /api/auth/otp/verify"],
    [() => endpoints.logout(), "POST /api/auth/logout"],
    [() => endpoints.bootstrapStatus(), "GET /api/bootstrap"],
    [() => endpoints.bootstrap({ email: "a@x.com", name: "a" }), "POST /api/bootstrap"],
    [() => endpoints.board(), "GET /api/board"],
    [() => endpoints.mcps(), "GET /api/mcps"],
    [() => endpoints.mcp(2), "GET /api/mcps/2"],
    [() => endpoints.mcpHistory(2, 6), "GET /api/mcps/2/history?hours=6"],
    [() => endpoints.actionDetail(2, 9), "GET /api/mcps/2/actions/9"],
    [() => endpoints.mcpActivity(20), "GET /api/mcp-activity?limit=20"],
    [() => endpoints.updateMcp(2, { maintenance: true }), "PUT /api/mcps/2"],
    [() => endpoints.manualAction(2, "restart"), "POST /api/mcps/2/actions/restart"],
    [
      () => endpoints.createMcp({ name: "n", host: "127.0.0.1", port: 9000, scripts: { start: { ext: ".ps1", content: "x" } } }),
      "POST /api/mcps",
    ],
    [() => endpoints.deleteMcp(2), "DELETE /api/mcps/2"],
    [() => endpoints.transferOwner(2, 7), "POST /api/mcps/2/owner"],
    [() => endpoints.scripts(2), "GET /api/mcps/2/scripts"],
    [() => endpoints.script(2, "stop"), "GET /api/mcps/2/scripts/stop"],
    [() => endpoints.scriptVersions(2, "stop"), "GET /api/mcps/2/scripts/stop/versions"],
    [() => endpoints.scriptVersion(2, "stop", 3), "GET /api/mcps/2/scripts/stop/versions/3"],
    [() => endpoints.putScript(2, "stop", { ext: ".bat", content: "x" }), "PUT /api/mcps/2/scripts/stop"],
    [() => endpoints.deleteScript(2, "restart"), "DELETE /api/mcps/2/scripts/restart"],
    [() => endpoints.revertScript(2, "stop", 3), "POST /api/mcps/2/scripts/stop/versions/3/revert"],
    [() => endpoints.users(), "GET /api/users"],
    [() => endpoints.createUser({ email: "b@x.com", name: "b", role: "developer" }), "POST /api/users"],
    [() => endpoints.updateUser(7, { active: false }), "PATCH /api/users/7"],
    [() => endpoints.settings(), "GET /api/settings"],
    [() => endpoints.updateSettings({ ping_interval_sec: 3 }), "PUT /api/settings"],
    [() => endpoints.retentionPreview(90), "GET /api/settings/retention/preview?days=90"],
    [() => endpoints.notice(), "GET /api/notice"],
    [() => endpoints.putNotice({ title: "t", body: "b", button_text: "ok" }), "PUT /api/notice"],
    [() => endpoints.noticeVersions(), "GET /api/notice/versions"],
    [() => endpoints.noticeVersion(0), "GET /api/notice/versions/0"],
    [() => endpoints.revertNotice(0), "POST /api/notice/versions/0/revert"],
  ];
  for (const [call, expected] of calls) {
    seen.length = 0;
    await call();
    expect(seen).toEqual([expected]);
  }
  // nothing exported is left untested
  expect(Object.keys(endpoints).length).toBe(calls.length);
});
