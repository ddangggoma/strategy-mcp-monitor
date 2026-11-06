// both read as text (Vite ?raw): the agent's window search and the page title must not drift apart
import dialogPy from "../../../agent/mcp_agent/dialog.py?raw";
import noticeHtml from "../../notice.html?raw";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { delay, http, HttpResponse } from "msw";
import { copy } from "@/copy/ko";
import { meFixture, noticeFixture } from "../../tests/msw/fixtures";
import { server, trackRequests } from "../../tests/msw/server";
import { NoticeApp } from "./NoticeApp";

const PREVIEW = { mode: "preview" } as const;
const SRC = { mode: "display", displayId: 12, token: "tok_ABCDEFGHIJKLmnop" } as const;
const open = () => server.use(http.post("/api/notice/display/open", () =>
  HttpResponse.json({ display_id: 12, version: 3, title: "안내 제목", body: "**본문**", button_text: "확인했습니다" })));

afterEach(() => {
  delete (window as { chrome?: unknown }).chrome;
});

it("keeps the page title the session agent finds the notice window by (Task 15 NOTICE_TITLE)", () => {
  const html = new DOMParser().parseFromString(noticeHtml, "text/html");
  const agentTitle = /^NOTICE_TITLE = "([^"]+)"$/m.exec(dialogPy)?.[1];
  expect(agentTitle).toBe("MCP Monitor");
  expect(html.title).toBe(agentTitle);
});

describe("preview mode", () => {
  it("shows the loaded notice, then tells the host and thanks the user on the button", async () => {
    const postMessage = vi.fn();
    (window as { chrome?: unknown }).chrome = { webview: { postMessage } };
    server.use(
      http.get("/api/auth/me", () => HttpResponse.json(meFixture("admin", "local"))),
      http.get("/api/notice", () => HttpResponse.json(noticeFixture({ version: 7, title: "접속 안내", button_text: "동의" }))),
    );
    render(<NoticeApp source={PREVIEW} />);
    const dialog = await screen.findByRole("dialog", { name: "접속 안내" });
    await userEvent.click(screen.getByRole("button", { name: "동의" }));
    expect(postMessage).toHaveBeenCalledWith({ type: "notice_ack", version: 7 });
    await waitFor(() => expect(dialog).not.toBeInTheDocument());
    expect(screen.getByRole("status")).toHaveTextContent(copy.notice.acknowledged);
  });

  it("shows the built-in text to someone who is not a local Admin", async () => {
    render(<NoticeApp source={PREVIEW} />); // default handler: nobody signed in
    expect(await screen.findByRole("dialog", { name: copy.notice.builtIn.title })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: copy.notice.builtIn.button_text })).toBeInTheDocument();
  });

  it("thanks the user in an ordinary browser too, without any acknowledgement request", async () => {
    render(<NoticeApp source={PREVIEW} />);
    const button = await screen.findByRole("button", { name: copy.notice.builtIn.button_text });
    const spy = trackRequests();
    await userEvent.click(button);
    expect(await screen.findByText(copy.notice.acknowledged)).toBeInTheDocument();
    expect(screen.queryByText(copy.notice.ackFailed)).toBeNull();
    expect(spy.paths()).toEqual([]);
  });

  it("says so when the notice cannot be loaded", async () => {
    server.use(http.get("/api/auth/me", () => HttpResponse.error()));
    render(<NoticeApp source={PREVIEW} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(copy.notice.loadFailed);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull(); // a reload works here: the address is unchanged
  });
});

describe("display mode", () => {
  it("shows the dialog and the acknowledged message after the button", async () => {
    open(); server.use(http.post("/api/notice/display/ack", () => new HttpResponse(null, { status: 204 })));
    render(<NoticeApp source={SRC} />);
    expect(await screen.findByRole("dialog")).toHaveTextContent("안내 제목");
    await userEvent.click(screen.getByRole("button", { name: "확인했습니다" }));
    expect(await screen.findByText(copy.notice.acknowledged)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("shows nothing but a hidden loading line until the notice arrives", async () => {
    server.use(http.post("/api/notice/display/open", async () => {
      await delay(50);
      return HttpResponse.json({ display_id: 12, version: 3, title: "안내 제목", body: "본문", button_text: "확인했습니다" });
    }));
    render(<NoticeApp source={SRC} />);
    expect(screen.getByRole("status")).toHaveTextContent(copy.common.loading);
    expect(screen.getByRole("status")).toHaveClass("sr-only");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("marks the button busy while the acknowledgement is on its way, and sends it once", async () => {
    open();
    let calls = 0;
    let release!: () => void;
    const held = new Promise<void>((r) => (release = r));
    server.use(http.post("/api/notice/display/ack", async () => {
      calls++;
      await held;
      return new HttpResponse(null, { status: 204 });
    }));
    render(<NoticeApp source={SRC} />);
    const button = await screen.findByRole("button", { name: "확인했습니다" });
    await userEvent.click(button);
    expect(button).toHaveAttribute("aria-busy", "true");
    expect(button).toHaveFocus(); // never disabled: focus stays where it was
    await userEvent.click(button); // a second press while busy does nothing
    release();
    expect(await screen.findByText(copy.notice.acknowledged)).toBeInTheDocument();
    expect(calls).toBe(1);
  });

  it("shows the expired message when the display is gone", async () => {
    server.use(http.post("/api/notice/display/open", () => HttpResponse.json({ error: "not_found" }, { status: 404 })));
    render(<NoticeApp source={SRC} />);
    expect(await screen.findByText(copy.notice.displayExpired)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("offers to load again when the server cannot be reached (the token is no longer in the address)", async () => {
    let fail = true;
    server.use(http.post("/api/notice/display/open", () =>
      fail
        ? HttpResponse.error()
        : HttpResponse.json({ display_id: 12, version: 3, title: "안내 제목", body: "본문", button_text: "확인했습니다" })));
    render(<NoticeApp source={SRC} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(copy.notice.loadFailedRetry);
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: copy.notice.retry }));
    expect(await screen.findByRole("dialog", { name: "안내 제목" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("offers a retry when the acknowledgement fails", async () => {
    open(); let ok = false;
    server.use(http.post("/api/notice/display/ack", () => (ok ? new HttpResponse(null, { status: 204 }) : HttpResponse.json({ error: "not_found" }, { status: 404 }))));
    render(<NoticeApp source={SRC} />);
    await userEvent.click(await screen.findByRole("button", { name: "확인했습니다" }));
    expect(await screen.findByText(copy.notice.ackFailed)).toBeInTheDocument();
    ok = true; await userEvent.click(screen.getByRole("button", { name: copy.notice.retry }));
    expect(await screen.findByText(copy.notice.acknowledged)).toBeInTheDocument();
  });

  it("announces the failure and puts the focus on the retry button", async () => {
    open();
    server.use(http.post("/api/notice/display/ack", () => HttpResponse.json({ error: "not_found" }, { status: 404 })));
    render(<NoticeApp source={SRC} />);
    await userEvent.click(await screen.findByRole("button", { name: "확인했습니다" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(copy.notice.ackFailed);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("button", { name: copy.notice.retry })).toHaveFocus();
    await userEvent.keyboard("{Enter}"); // still failing: stays on the retry, no acknowledgement
    expect(await screen.findByRole("alert")).toHaveTextContent(copy.notice.ackFailed);
    expect(screen.queryByText(copy.notice.acknowledged)).toBeNull();
  });
});
