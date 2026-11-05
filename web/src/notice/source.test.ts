import { http, HttpResponse } from "msw";
import { copy } from "@/copy/ko";
import { meFixture, noticeFixture } from "../../tests/msw/fixtures";
import { server, trackRequests } from "../../tests/msw/server";
import { loadNoticeContent, notifyHost } from "./source";

const builtIn = { ...copy.notice.builtIn, version: null };

it("a local Admin sees the saved notice from GET /api/notice", async () => {
  server.use(
    http.get("/api/auth/me", () => HttpResponse.json(meFixture("admin", "local"))),
    http.get("/api/notice", () => HttpResponse.json(noticeFixture({ version: 4, title: "저장된 고지" }))),
  );
  expect(await loadNoticeContent()).toEqual({
    title: "저장된 고지",
    body: noticeFixture().body,
    button_text: "확인",
    version: 4,
  });
});

it.each([
  ["nobody signed in", meFixture(null, "local")],
  ["a developer", meFixture("developer", "local")],
  ["the external channel", meFixture("admin", "external")],
])("%s gets the built-in text and no Admin-only request (F18)", async (_label, me) => {
  server.use(http.get("/api/auth/me", () => HttpResponse.json(me)));
  const spy = trackRequests();
  expect(await loadNoticeContent()).toEqual(builtIn);
  expect(spy.paths()).toEqual(["/api/auth/me"]);
});

it("fails when the server cannot be read", async () => {
  server.use(http.get("/api/auth/me", () => HttpResponse.error()));
  await expect(loadNoticeContent()).rejects.toThrow();
  server.use(
    http.get("/api/auth/me", () => HttpResponse.json(meFixture("admin", "local"))),
    http.get("/api/notice", () => HttpResponse.json({ error: "internal" }, { status: 500 })),
  );
  await expect(loadNoticeContent()).rejects.toThrow();
});

describe("notifyHost", () => {
  afterEach(() => {
    delete (window as { chrome?: unknown }).chrome;
  });

  it("posts the acknowledgement to the WebView2 host", () => {
    const postMessage = vi.fn();
    (window as { chrome?: unknown }).chrome = { webview: { postMessage } };
    notifyHost({ type: "notice_ack", version: 3 });
    expect(postMessage).toHaveBeenCalledWith({ type: "notice_ack", version: 3 });
  });

  it("does nothing in an ordinary browser", () => {
    expect(() => notifyHost({ type: "notice_ack", version: null })).not.toThrow();
    (window as { chrome?: unknown }).chrome = {}; // Chrome's own window.chrome has no webview
    expect(() => notifyHost({ type: "notice_ack", version: null })).not.toThrow();
  });
});
