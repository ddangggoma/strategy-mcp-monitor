import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { copy } from "@/copy/ko";
import { meFixture, noticeFixture } from "../../tests/msw/fixtures";
import { server } from "../../tests/msw/server";
import { NoticeApp } from "./NoticeApp";

afterEach(() => {
  delete (window as { chrome?: unknown }).chrome;
});

it("shows the loaded notice, then tells the host and thanks the user on the button", async () => {
  const postMessage = vi.fn();
  (window as { chrome?: unknown }).chrome = { webview: { postMessage } };
  server.use(
    http.get("/api/auth/me", () => HttpResponse.json(meFixture("admin", "local"))),
    http.get("/api/notice", () => HttpResponse.json(noticeFixture({ version: 7, title: "접속 안내", button_text: "동의" }))),
  );
  render(<NoticeApp />);
  const dialog = await screen.findByRole("dialog", { name: "접속 안내" });
  await userEvent.click(screen.getByRole("button", { name: "동의" }));
  expect(postMessage).toHaveBeenCalledWith({ type: "notice_ack", version: 7 });
  expect(dialog).not.toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent(copy.notice.acknowledged);
});

it("shows the built-in text to someone who is not a local Admin", async () => {
  render(<NoticeApp />); // default handler: nobody signed in
  expect(await screen.findByRole("dialog", { name: copy.notice.builtIn.title })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: copy.notice.builtIn.button_text })).toBeInTheDocument();
});

it("says so when the notice cannot be loaded", async () => {
  server.use(http.get("/api/auth/me", () => HttpResponse.error()));
  render(<NoticeApp />);
  expect(await screen.findByRole("alert")).toHaveTextContent(copy.notice.loadFailed);
  expect(screen.queryByRole("dialog")).toBeNull();
});
