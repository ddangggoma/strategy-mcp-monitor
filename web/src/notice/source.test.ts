import { http, HttpResponse } from "msw";
import { copy } from "@/copy/ko";
import { meFixture, noticeFixture } from "../../tests/msw/fixtures";
import { server, trackRequests } from "../../tests/msw/server";
import { loadNoticeContent, NoticeLoadError, notifyHost, readNoticeSource, takeNoticeSource } from "./source";

const builtIn = { ...copy.notice.builtIn, version: null };
const SRC = { mode: "display", displayId: 12, token: "tok_ABCDEFGHIJKLmnop" } as const;

describe("preview mode (no display in the address)", () => {
  it("a local Admin sees the saved notice from GET /api/notice", async () => {
    server.use(
      http.get("/api/auth/me", () => HttpResponse.json(meFixture("admin", "local"))),
      http.get("/api/notice", () => HttpResponse.json(noticeFixture({ version: 4, title: "저장된 고지" }))),
    );
    const want = { title: "저장된 고지", body: noticeFixture().body, button_text: "확인", version: 4 };
    expect(await loadNoticeContent()).toEqual(want);
    expect(await loadNoticeContent({ mode: "preview" })).toEqual(want);
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

    it("posts the acknowledgement to the WebView2 host", async () => {
      const postMessage = vi.fn();
      (window as { chrome?: unknown }).chrome = { webview: { postMessage } };
      await expect(notifyHost({ type: "notice_ack", version: 3 })).resolves.toBe(true);
      expect(postMessage).toHaveBeenCalledWith({ type: "notice_ack", version: 3 });
    });

    it("tells nobody in an ordinary browser, and makes no request", async () => {
      const spy = trackRequests();
      await expect(notifyHost({ type: "notice_ack", version: null })).resolves.toBe(false);
      (window as { chrome?: unknown }).chrome = {}; // Chrome's own window.chrome has no webview
      await expect(notifyHost({ type: "notice_ack", version: null }, { mode: "preview" })).resolves.toBe(false);
      expect(spy.paths()).toEqual([]);
    });
  });
});

describe("display mode (#d=<id>&t=<token>)", () => {
  it("reads the display id and token from the hash", () => {
    expect(readNoticeSource("#d=12&t=tok_ABCDEFGHIJKLmnop")).toEqual(SRC);
    expect(readNoticeSource("")).toEqual({ mode: "preview" });
    expect(readNoticeSource("#d=x&t=tok_ABCDEFGHIJKLmnop")).toEqual({ mode: "preview" });
    expect(readNoticeSource("#d=12&t=short")).toEqual({ mode: "preview" });
  });

  it("accepts only a positive id and a URL-safe token of 16–128 characters", () => {
    const t16 = "a".repeat(16);
    expect(readNoticeSource(`#d=1&t=${t16}`)).toEqual({ mode: "display", displayId: 1, token: t16 });
    expect(readNoticeSource(`#d=7&t=${"Z9_-".repeat(32)}`)).toMatchObject({ mode: "display", displayId: 7 });
    for (const hash of [
      `#d=0&t=${t16}`, `#d=-3&t=${t16}`, `#d=012&t=${t16}`, `#d=1.5&t=${t16}`, `#d=1&t=${"a".repeat(15)}`,
      `#d=1&t=${"a".repeat(129)}`, `#d=1&t=${"a".repeat(15)}+`, `#d=1&t=${"a".repeat(16)}%20`, `#d=1`, `#t=${t16}`,
      `d=1&t=${t16}`,
    ]) {
      expect(readNoticeSource(hash), hash).toEqual({ mode: "preview" });
    }
  });

  it("takes the token out of the address bar", () => {
    const replaceState = vi.fn();
    expect(takeNoticeSource({ hash: "#d=12&t=tok_ABCDEFGHIJKLmnop", pathname: "/notice", search: "" }, { replaceState })).toEqual(SRC);
    expect(replaceState).toHaveBeenCalledWith(null, "", "/notice");
    replaceState.mockClear();
    takeNoticeSource({ hash: "#d=12&t=tok_ABCDEFGHIJKLmnop", pathname: "/notice", search: "?x=1" }, { replaceState });
    expect(replaceState).toHaveBeenCalledWith(null, "", "/notice?x=1");
  });

  it("leaves a preview address alone", () => {
    const replaceState = vi.fn();
    expect(takeNoticeSource({ hash: "", pathname: "/notice", search: "" }, { replaceState })).toEqual({ mode: "preview" });
    expect(replaceState).not.toHaveBeenCalled();
  });

  it("reads the real location by default", () => {
    window.history.replaceState(null, "", "/notice#d=12&t=tok_ABCDEFGHIJKLmnop");
    expect(takeNoticeSource()).toEqual(SRC);
    expect(window.location.hash).toBe("");
    expect(window.location.pathname).toBe("/notice");
  });

  it("opens the display with the token header", async () => {
    let token: string | null = null;
    server.use(http.post("/api/notice/display/open", ({ request }) => {
      token = request.headers.get("X-Notice-Token");
      return HttpResponse.json({ display_id: 12, version: 3, title: "안내", body: "본문", button_text: "확인" });
    }));
    await expect(loadNoticeContent(SRC)).resolves.toEqual({ title: "안내", body: "본문", button_text: "확인", version: 3 });
    expect(token).toBe("tok_ABCDEFGHIJKLmnop");
  });

  it("sends no cookies, skips the HTTP cache and never asks for the saved notice", async () => {
    const spy = trackRequests();
    // Node's Request (what MSW sees) does not keep credentials/cache, so read what the page asked fetch for
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    try {
      await loadNoticeContent(SRC);
      await notifyHost({ type: "notice_ack", version: 3 }, SRC);
      const inits = fetchSpy.mock.calls.map(([, init]) => ({ credentials: init?.credentials, cache: init?.cache }));
      expect(inits).toEqual([{ credentials: "omit", cache: "no-store" }, { credentials: "omit", cache: "no-store" }]);
    } finally {
      fetchSpy.mockRestore();
    }
    expect(spy.paths()).toEqual(["/api/notice/display/open", "/api/notice/display/ack"]);
  });

  it("maps a missing display to NoticeLoadError 404", async () => {
    server.use(http.post("/api/notice/display/open", () => HttpResponse.json({ error: "not_found" }, { status: 404 })));
    await expect(loadNoticeContent(SRC)).rejects.toMatchObject({ status: 404 });
    await expect(loadNoticeContent(SRC)).rejects.toBeInstanceOf(NoticeLoadError);
  });

  it("maps other failures to NoticeLoadError with their status, 0 for no response", async () => {
    server.use(http.post("/api/notice/display/open", () => HttpResponse.json({ error: "forbidden" }, { status: 403 })));
    await expect(loadNoticeContent(SRC)).rejects.toMatchObject({ status: 403 });
    server.use(http.post("/api/notice/display/open", () => HttpResponse.error()));
    const err = await loadNoticeContent(SRC).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(NoticeLoadError);
    expect(err).toMatchObject({ status: 0 });
  });

  it("acknowledges with retries and stops at 404", async () => {
    let calls = 0;
    server.use(http.post("/api/notice/display/ack", () => (++calls < 3 ? HttpResponse.json({ error: "internal" }, { status: 503 }) : new HttpResponse(null, { status: 204 }))));
    await expect(notifyHost({ type: "notice_ack", version: 3 }, SRC, { retryDelaysMs: [0, 0] })).resolves.toBe(true);
    expect(calls).toBe(3);
    calls = 0;
    server.use(http.post("/api/notice/display/ack", () => { calls++; return HttpResponse.json({ error: "not_found" }, { status: 404 }); }));
    await expect(notifyHost({ type: "notice_ack", version: 3 }, SRC, { retryDelaysMs: [0, 0] })).resolves.toBe(false);
    expect(calls).toBe(1);
  });

  it("sends the token on every attempt and gives up after the last delay", async () => {
    const tokens: (string | null)[] = [];
    server.use(http.post("/api/notice/display/ack", ({ request }) => {
      tokens.push(request.headers.get("X-Notice-Token"));
      return tokens.length === 1 ? HttpResponse.error() : HttpResponse.json({ error: "internal" }, { status: 500 });
    }));
    await expect(notifyHost({ type: "notice_ack", version: 3 }, SRC, { retryDelaysMs: [0, 0] })).resolves.toBe(false);
    expect(tokens).toEqual(Array(3).fill(SRC.token));
  });

  it("waits the default 1 s and 2 s between attempts", async () => {
    // record the waits and skip them; any other timer (the fetch machinery's) runs as it would
    const realSetTimeout = globalThis.setTimeout;
    const waits: number[] = [];
    const spy = vi.spyOn(globalThis, "setTimeout").mockImplementation(((fn: () => void, ms?: number, ...args: unknown[]) => {
      if (ms === 1000 || ms === 2000) {
        waits.push(ms);
        return realSetTimeout(fn, 0);
      }
      return realSetTimeout(fn, ms, ...args);
    }) as typeof setTimeout);
    try {
      let calls = 0;
      server.use(http.post("/api/notice/display/ack", () => {
        calls++;
        return HttpResponse.json({ error: "internal" }, { status: 503 });
      }));
      await expect(notifyHost({ type: "notice_ack", version: 3 }, SRC)).resolves.toBe(false);
      expect(calls).toBe(3);
      expect(waits).toEqual([1000, 2000]); // between the attempts, none after the last
    } finally {
      spy.mockRestore();
    }
  });

  it("does not use the WebView2 bridge", async () => {
    const postMessage = vi.fn();
    (window as { chrome?: unknown }).chrome = { webview: { postMessage } };
    try {
      await expect(notifyHost({ type: "notice_ack", version: 3 }, SRC)).resolves.toBe(true); // default handler: 204
      expect(postMessage).not.toHaveBeenCalled();
    } finally {
      delete (window as { chrome?: unknown }).chrome;
    }
  });
});
