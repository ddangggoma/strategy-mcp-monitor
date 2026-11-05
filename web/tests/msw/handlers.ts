// Default MSW handlers: every Appendix B route answers with a typed fixture. Tests override what
// they need with server.use(...). Relative paths resolve against jsdom's location (vitest config).
import { http, HttpResponse } from "msw";
import type { McpConfig, McpCreate, NoticeContent, ScriptKind, ScriptUpload, Settings, UserCreate, UserPatch } from "@/lib/api-types";
import {
  actionDetailFixture, activityFixture, adminUser, boardFixture, historyFixture, mcpDetailFixture, meFixture,
  noticeFixture, noticeVersionFixture, previewFixture, scriptFixture, scriptListFixture, scriptVersionFixture,
  settingsFixture,
} from "./fixtures";

const id = (v: string | readonly string[] | undefined) => Number(v);
const noContent = () => new HttpResponse(null, { status: 204 });

/** Sends the board snapshot, then stays open (like the server between heartbeats) until aborted. */
function boardStream(request: Request): Response {
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      c.enqueue(new TextEncoder().encode(`event: board\ndata: ${JSON.stringify(boardFixture())}\n\n`));
      request.signal.addEventListener("abort", () => c.close(), { once: true });
    },
  });
  return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream; charset=utf-8" } });
}

export const handlers = [
  // auth
  http.get("/api/auth/me", () => HttpResponse.json(meFixture(null, "local"))),
  http.post("/api/auth/otp/request", () => HttpResponse.json({}, { status: 202 })),
  http.post("/api/auth/otp/verify", () => {
    const me = meFixture("admin", "local");
    return HttpResponse.json({ user: me.user, csrf_token: me.csrf_token });
  }),
  http.post("/api/auth/logout", noContent),

  // bootstrap
  http.get("/api/bootstrap", () => HttpResponse.json({ needed: false })),
  http.post("/api/bootstrap", async ({ request }) => {
    const b = (await request.json()) as { email: string; name: string };
    return HttpResponse.json({ id: 1, email: b.email, name: b.name, role: "admin" }, { status: 201 });
  }),

  // board + stream
  http.get("/api/board", () => HttpResponse.json(boardFixture())),
  http.get("/api/stream", ({ request }) => boardStream(request)),

  // MCPs
  http.get("/api/mcps", () => HttpResponse.json([mcpDetailFixture({ id: 1 }), mcpDetailFixture({ id: 2, name: "seoul-weather" })])),
  http.post("/api/mcps", async ({ request }) => {
    const config = (await request.json()) as Partial<McpCreate>;
    delete config.scripts;
    return HttpResponse.json(mcpDetailFixture({ ...config, id: 3, live: null }), { status: 201 });
  }),
  http.get("/api/mcps/:id", ({ params }) => HttpResponse.json(mcpDetailFixture({ id: id(params.id) }))),
  http.put("/api/mcps/:id", async ({ params, request }) => {
    const patch = (await request.json()) as Partial<McpConfig>;
    return HttpResponse.json(mcpDetailFixture({ id: id(params.id), ...patch }));
  }),
  http.delete("/api/mcps/:id", noContent),
  http.get("/api/mcps/:id/history", () => HttpResponse.json(historyFixture())),
  http.get("/api/mcps/:id/actions/:aid", ({ params }) => HttpResponse.json(actionDetailFixture({ id: id(params.aid) }))),
  http.post("/api/mcps/:id/actions/:kind", () => HttpResponse.json({ run_id: "run-1" }, { status: 202 })),
  http.post("/api/mcps/:id/owner", async ({ params, request }) => {
    const { user_id } = (await request.json()) as { user_id: number };
    return HttpResponse.json(
      mcpDetailFixture({ id: id(params.id), owner: { id: user_id, email: `user${user_id}@example.com`, name: `user${user_id}` } }),
    );
  }),
  http.get("/api/mcp-activity", () => HttpResponse.json(activityFixture())),

  // scripts
  http.get("/api/mcps/:id/scripts", () => HttpResponse.json(scriptListFixture())),
  http.get("/api/mcps/:id/scripts/:kind", ({ params }) => HttpResponse.json(scriptFixture({ kind: params.kind as ScriptKind }))),
  http.put("/api/mcps/:id/scripts/:kind", async ({ params, request }) => {
    const b = (await request.json()) as ScriptUpload;
    return HttpResponse.json({ kind: params.kind as ScriptKind, ext: b.ext, version: 2, sha256: "b".repeat(64) });
  }),
  http.delete("/api/mcps/:id/scripts/:kind", noContent),
  http.get("/api/mcps/:id/scripts/:kind/versions", () => HttpResponse.json([scriptVersionFixture()])),
  http.get("/api/mcps/:id/scripts/:kind/versions/:v", ({ params }) =>
    HttpResponse.json({ ...scriptVersionFixture({ version: id(params.v) }), content: "Write-Host start" }),
  ),
  http.post("/api/mcps/:id/scripts/:kind/versions/:v/revert", ({ params }) =>
    HttpResponse.json({ kind: params.kind as ScriptKind, ext: ".ps1", version: 3, sha256: "c".repeat(64) }),
  ),

  // users
  http.get("/api/users", () => HttpResponse.json([adminUser({ id: 1 }), adminUser({ id: 2, role: "developer", owned_mcps: 2 })])),
  http.post("/api/users", async ({ request }) => {
    const b = (await request.json()) as UserCreate;
    return HttpResponse.json(adminUser({ id: 3, ...b, last_login_at: null }), { status: 201 });
  }),
  http.patch("/api/users/:id", async ({ params, request }) => {
    const patch = (await request.json()) as UserPatch;
    return HttpResponse.json(adminUser({ id: id(params.id), ...patch }));
  }),

  // settings
  http.get("/api/settings", () => HttpResponse.json(settingsFixture())),
  http.put("/api/settings", async ({ request }) => HttpResponse.json(settingsFixture((await request.json()) as Partial<Settings>))),
  http.get("/api/settings/retention/preview", ({ request }) => {
    const days = Number(new URL(request.url).searchParams.get("days"));
    return HttpResponse.json(previewFixture({ days }));
  }),

  // notice
  http.get("/api/notice", () => HttpResponse.json(noticeFixture())),
  http.put("/api/notice", async ({ request }) =>
    HttpResponse.json(noticeFixture({ ...((await request.json()) as NoticeContent), version: 2 })),
  ),
  http.get("/api/notice/versions", () => HttpResponse.json([noticeVersionFixture()])),
  http.get("/api/notice/versions/:v", ({ params }) => HttpResponse.json(noticeFixture({ version: id(params.v) }))),
  http.post("/api/notice/versions/:v/revert", ({ params }) =>
    HttpResponse.json(noticeFixture({ version: 2, reverted_from: id(params.v) })),
  ),
];
