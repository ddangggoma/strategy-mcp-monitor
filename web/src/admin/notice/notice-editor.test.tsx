import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { copy } from "@/copy/ko";
import type { Me, Notice, NoticeContent, NoticeVersionSummary } from "@/lib/api-types";
import { loadDraft, saveDraft } from "@/lib/draft";
import { meFixture, noticeFixture, noticeVersionFixture, userSummary } from "../../../tests/msw/fixtures";
import { server, trackRequests } from "../../../tests/msw/server";
import { renderWithProviders } from "../../../tests/render";
import { qk } from "../query-keys";

afterEach(() => sessionStorage.clear());

const adminMe = () => meFixture("admin", "local");

/** Method + path of every request from now on. */
function trackCalls(): () => string[] {
  const seen: string[] = [];
  server.events.on("request:start", ({ request }) => {
    seen.push(`${request.method} ${new URL(request.url).pathname}`);
  });
  return () => [...seen];
}

/** A small in-memory notice server: GET answers the latest version, PUT appends unless unchanged. */
function noticeServer(initial: Notice, history: NoticeVersionSummary[] = []) {
  const state = { current: initial, history: [...history], puts: [] as NoticeContent[] };
  const same = (a: NoticeContent, b: NoticeContent) => a.title === b.title && a.body === b.body && a.button_text === b.button_text;
  server.use(
    http.get("/api/notice", () => HttpResponse.json(state.current)),
    http.get("/api/notice/versions", () => HttpResponse.json(state.history)),
    http.put("/api/notice", async ({ request }) => {
      const b = (await request.json()) as NoticeContent;
      state.puts.push(b);
      // the server trims the title and the button text
      const content = { ...b, title: b.title.trim(), button_text: b.button_text.trim() };
      if (!same(content, state.current)) {
        const version = Math.max(0, ...state.history.map((h) => h.version)) + 1;
        state.current = noticeFixture({ ...content, version, author: userSummary(1), reverted_from: null });
        state.history.unshift(noticeVersionFixture({ version, title: content.title }));
      }
      return HttpResponse.json(state.current);
    }),
  );
  return state;
}

async function renderEditor(notice: Notice, { me = adminMe(), history }: { me?: Me; history?: NoticeVersionSummary[] } = {}) {
  const state = noticeServer(notice, history);
  const r = renderWithProviders(null, { route: "/admin/notice", me });
  // the first test of a run pays for compiling the lazy route chunk under load
  await screen.findByLabelText(copy.notice.fields.title, {}, { timeout: 5000 });
  await screen.findByRole("list", { name: copy.notice.versions });
  return { ...r, state };
}

const field = (label: string) => screen.getByLabelText(label);
const preview = () => screen.getByRole("group", { name: copy.notice.previewLabel });
const saveButton = () => screen.getByRole("button", { name: copy.common.save });
const versionList = () => screen.getByRole("list", { name: copy.notice.versions });

async function retype(label: string, text: string) {
  await userEvent.clear(field(label));
  if (text) await userEvent.type(field(label), text);
}

// ---- edit + live preview ---------------------------------------------------------------

it("updates the live preview on every keystroke", async () => {
  await renderEditor(noticeFixture({ version: 0 }));
  await userEvent.clear(screen.getByLabelText(copy.notice.fields.title));
  await userEvent.type(screen.getByLabelText(copy.notice.fields.title), "새 제목");
  expect(within(screen.getByRole("group", { name: copy.notice.previewLabel })).getByText("새 제목")).toBeInTheDocument();

  await userEvent.type(field(copy.notice.fields.body), "\n\n- **굵은** 항목");
  expect(within(preview()).getByRole("listitem")).toHaveTextContent("굵은 항목");
  expect(preview().querySelector("li strong")).toHaveTextContent("굵은");
  await retype(copy.notice.fields.button_text, "동의");
  expect(within(preview()).getByRole("button", { name: "동의" })).toBeInTheDocument();
});

it("starts from the saved notice and shows each field's length", async () => {
  await renderEditor(noticeFixture({ version: 3, title: "접속 안내", body: "본문", button_text: "확인" }));
  expect(field(copy.notice.fields.title)).toHaveValue("접속 안내");
  expect(field(copy.notice.fields.body)).toHaveValue("본문");
  expect(field(copy.notice.fields.button_text)).toHaveValue("확인");
  expect(field(copy.notice.fields.title)).toHaveAccessibleDescription(expect.stringContaining(copy.notice.count(5, 80)));
  expect(field(copy.notice.fields.body)).toHaveAccessibleDescription(expect.stringContaining(copy.notice.count(2, 4000)));
  expect(field(copy.notice.fields.button_text)).toHaveAccessibleDescription(expect.stringContaining(copy.notice.count(2, 20)));
  // nothing changed yet: nothing to save, and the button says so (U26)
  expect(saveButton()).toHaveAttribute("aria-disabled", "true");
  expect(saveButton()).toHaveAccessibleDescription(copy.deny.unchanged);
  await userEvent.type(field(copy.notice.fields.title), "!");
  expect(saveButton()).not.toHaveAttribute("aria-disabled");
  expect(saveButton()).not.toHaveAccessibleDescription(copy.deny.unchanged);
});

it("counts characters by code point", async () => {
  const calls = trackCalls();
  await renderEditor(noticeFixture({ version: 1, button_text: "확인" }));
  await retype(copy.notice.fields.button_text, "😀");
  expect(field(copy.notice.fields.button_text)).toHaveAccessibleDescription(expect.stringContaining(copy.notice.count(1, 20)));

  await retype(copy.notice.fields.title, "가".repeat(81));
  expect(screen.getByText(copy.notice.count(81, 80))).toBeInTheDocument();
  expect(field(copy.notice.fields.title)).toHaveAttribute("aria-invalid", "true");
  expect(field(copy.notice.fields.title)).toHaveAccessibleDescription(expect.stringContaining(copy.notice.tooLong(80)));
  expect(saveButton()).toHaveAttribute("aria-disabled", "true");
  await userEvent.click(saveButton());
  expect(calls()).not.toContain("PUT /api/notice");

  // exactly at the limit (an emoji is one character) is fine
  await retype(copy.notice.fields.title, "😀".repeat(80));
  expect(screen.getByText(copy.notice.count(80, 80))).toBeInTheDocument();
  expect(field(copy.notice.fields.title)).not.toHaveAttribute("aria-invalid", "true");
  expect(saveButton()).not.toHaveAttribute("aria-disabled");
});

it("refuses an empty field without a request", async () => {
  const calls = trackCalls();
  await renderEditor(noticeFixture({ version: 1 }));
  await retype(copy.notice.fields.body, "   ");
  expect(field(copy.notice.fields.body)).toHaveAttribute("aria-invalid", "true");
  expect(field(copy.notice.fields.body)).toHaveAccessibleDescription(expect.stringContaining(copy.notice.required.body));
  expect(saveButton()).toHaveAttribute("aria-disabled", "true");
  await userEvent.click(saveButton());
  expect(calls()).not.toContain("PUT /api/notice");
});

it("wraps the selection in ** with the bold button", async () => {
  await renderEditor(noticeFixture({ version: 1, body: "보안 감사 안내" }));
  const body = field(copy.notice.fields.body) as HTMLTextAreaElement;
  body.focus();
  body.setSelectionRange(0, 5);
  await userEvent.click(screen.getByRole("button", { name: copy.notice.insertBold }));
  expect(body).toHaveValue("**보안 감사** 안내");
  expect(body).toHaveFocus();
  expect(preview().querySelector("strong")).toHaveTextContent("보안 감사");
  // with nothing selected: an empty pair, the caret between the markers
  body.setSelectionRange(body.value.length, body.value.length);
  await userEvent.click(screen.getByRole("button", { name: copy.notice.insertBold }));
  expect(body).toHaveValue("**보안 감사** 안내****");
  expect(body.selectionStart).toBe(body.value.length - 2);
});

it("turns the selected lines into a list with the list button, and back", async () => {
  await renderEditor(noticeFixture({ version: 1, body: "머리말\n\n접속 정보\n명령 기록" }));
  const body = field(copy.notice.fields.body) as HTMLTextAreaElement;
  body.focus();
  body.setSelectionRange(6, body.value.length - 2); // from "접속" to inside "기록"
  await userEvent.click(screen.getByRole("button", { name: copy.notice.insertList }));
  expect(body).toHaveValue("머리말\n\n- 접속 정보\n- 명령 기록");
  expect(within(preview()).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["접속 정보", "명령 기록"]);
  expect(body).toHaveFocus();
  // again on the same lines: the bullets come off
  await userEvent.click(screen.getByRole("button", { name: copy.notice.insertList }));
  expect(body).toHaveValue("머리말\n\n접속 정보\n명령 기록");
});

// ---- save ------------------------------------------------------------------------------

it("saves and shows the new version", async () => {
  const { state } = await renderEditor(noticeFixture({ version: 0, created_at: null, author: null }));
  expect(within(versionList()).getAllByRole("listitem")).toHaveLength(1); // the built-in text only
  await retype(copy.notice.fields.title, "새 안내");
  await userEvent.click(saveButton());
  expect(await screen.findByText(copy.notice.savedVersion(1))).toBeInTheDocument();
  expect(state.puts).toEqual([{ title: "새 안내", body: noticeFixture().body, button_text: "확인" }]);
  const items = await waitFor(() => {
    const li = within(versionList()).getAllByRole("listitem");
    expect(li).toHaveLength(2);
    return li;
  });
  expect(items[0]).toHaveTextContent(copy.notice.versionLabel(1));
  expect(items[0]).toHaveTextContent("새 안내");
  expect(items[0]).toHaveTextContent(copy.notice.current);
  expect(items[1]).toHaveTextContent(copy.notice.defaultVersion);
  expect(saveButton()).toHaveAttribute("aria-disabled", "true");
  expect(loadDraft("notice")).toBeNull();
});

it("says nothing changed when the server keeps the current version", async () => {
  const { state } = await renderEditor(noticeFixture({ version: 2, title: "접속 안내" }), {
    history: [noticeVersionFixture({ version: 2 }), noticeVersionFixture({ version: 1 })],
  });
  await userEvent.type(field(copy.notice.fields.title), " "); // the server trims it away
  await userEvent.click(saveButton());
  expect(await screen.findByText(copy.notice.unchanged)).toBeInTheDocument();
  expect(state.puts).toHaveLength(1);
  // the editor takes the server's text back: nothing left to save
  expect(field(copy.notice.fields.title)).toHaveValue("접속 안내");
  expect(saveButton()).toHaveAttribute("aria-disabled", "true");
});

it("shows a validation error from the server under the form", async () => {
  await renderEditor(noticeFixture({ version: 1 }));
  server.use(http.put("/api/notice", () => HttpResponse.json({ error: "validation" }, { status: 422 })));
  await retype(copy.notice.fields.title, "제어 문자");
  await userEvent.click(saveButton());
  expect(await screen.findByRole("alert")).toHaveTextContent(copy.errors.validation);
  expect(field(copy.notice.fields.title)).toHaveValue("제어 문자");
});

// ---- drafts, 401, leave guard (F12, F13) -------------------------------------------------

it("keeps a draft on every change and drops it when the text is typed back", async () => {
  await renderEditor(noticeFixture({ version: 2, title: "접속 안내" }));
  await userEvent.type(field(copy.notice.fields.title), "!");
  expect(loadDraft("notice")).toEqual({ title: "접속 안내!", body: noticeFixture().body, button_text: "확인", baseVersion: 2 });
  await userEvent.type(field(copy.notice.fields.title), "{Backspace}");
  expect(loadDraft("notice")).toBeNull();
});

it("restores the notice draft after re-login", async () => {
  saveDraft("notice", { title: "고치던 제목", body: "고치던 본문", button_text: "확인", baseVersion: 2 }, 1);
  await renderEditor(noticeFixture({ version: 2 }));
  expect(field(copy.notice.fields.title)).toHaveValue("고치던 제목");
  expect(field(copy.notice.fields.body)).toHaveValue("고치던 본문");
  expect(screen.getByText(copy.notice.draftRestored).closest('[role="status"]')).not.toBeNull();
  expect(within(preview()).getByText("고치던 본문")).toBeInTheDocument();
  expect(saveButton()).not.toHaveAttribute("aria-disabled");

  await userEvent.click(screen.getByRole("button", { name: copy.notice.discardDraft }));
  expect(field(copy.notice.fields.title)).toHaveValue("접속 안내");
  expect(screen.queryByText(copy.notice.draftRestored)).toBeNull();
  expect(loadDraft("notice")).toBeNull();
});

it("keeps the edits but says so when a newer notice is saved elsewhere meanwhile", async () => {
  const { qc } = await renderEditor(noticeFixture({ version: 2, title: "접속 안내" }));
  await retype(copy.notice.fields.title, "내 제목");
  act(() => qc.setQueryData(qk.notice, noticeFixture({ version: 5, title: "다른 사람 제목" })));
  expect(await screen.findByText(copy.notice.newerWhileEditing(5))).toBeInTheDocument();
  expect(field(copy.notice.fields.title)).toHaveValue("내 제목");
  expect(saveButton()).not.toHaveAttribute("aria-disabled");
  expect(loadDraft("notice")).toMatchObject({ title: "내 제목", baseVersion: 2 });
  await userEvent.click(screen.getByRole("button", { name: copy.notice.discardDraft }));
  expect(field(copy.notice.fields.title)).toHaveValue("다른 사람 제목");
  expect(screen.queryByText(copy.notice.newerWhileEditing(5))).toBeNull();
});

it("does not give another user's draft to the admin who logs in next on this tab", async () => {
  saveDraft("notice", { title: "X가 고치던 제목", body: "X의 본문", button_text: "확인", baseVersion: 2 }, 1);
  await renderEditor(noticeFixture({ version: 2 }), { me: meFixture("admin", "local", 2) });
  expect(field(copy.notice.fields.title)).toHaveValue(noticeFixture().title);
  expect(screen.queryByText(copy.notice.draftRestored)).toBeNull();
  expect(loadDraft("notice", 1)).toBeNull(); // gone, not kept for later
});

it("warns when the notice was saved again after the draft was made", async () => {
  saveDraft("notice", { title: "고치던 제목", body: "본문", button_text: "확인", baseVersion: 2 }, 1);
  await renderEditor(noticeFixture({ version: 5 }));
  expect(screen.getByText(copy.notice.draftStale(5))).toBeInTheDocument();
});

it("drops a draft equal to the saved notice, and a malformed one", async () => {
  const n = noticeFixture({ version: 2 });
  saveDraft("notice", { title: n.title, body: n.body, button_text: n.button_text, baseVersion: 1 }, 1);
  const { unmount } = await renderEditor(n);
  expect(screen.queryByText(copy.notice.draftRestored)).toBeNull();
  expect(loadDraft("notice")).toBeNull();
  unmount();

  saveDraft("notice", { title: 42 }, 1);
  await renderEditor(n);
  expect(field(copy.notice.fields.title)).toHaveValue(n.title);
  expect(loadDraft("notice")).toBeNull();
});

it("a 401 on save keeps the notice draft", async () => {
  const { router } = await renderEditor(noticeFixture({ version: 2 }));
  server.use(http.put("/api/notice", () => HttpResponse.json({ error: "login_required" }, { status: 401 })));
  await retype(copy.notice.fields.title, "저장 안 된 제목");
  await userEvent.click(saveButton());
  await waitFor(() => expect(router.state.location.pathname).toBe("/admin/login"));
  expect(router.state.location.href).toBe("/admin/login?redirect=%2Fadmin%2Fnotice");
  // F12: the unsaved-changes guard did not hold the forced navigation
  expect(screen.queryByRole("alertdialog", { name: copy.common.unsavedTitle })).toBeNull();
  expect(loadDraft("notice", 1)).toMatchObject({ title: "저장 안 된 제목" });
});

it("asks before leaving the page with unsaved edits", async () => {
  const { router } = await renderEditor(noticeFixture({ version: 2 }));
  await userEvent.type(field(copy.notice.fields.body), " 추가");
  const nav = screen.getByRole("navigation", { name: copy.nav.label });
  await userEvent.click(within(nav).getByRole("link", { name: copy.nav.settings }));
  const ask = await screen.findByRole("alertdialog", { name: copy.common.unsavedTitle });
  await userEvent.click(within(ask).getByRole("button", { name: copy.common.stay }));
  await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
  expect(router.state.location.pathname).toBe("/admin/notice");
  expect(field(copy.notice.fields.body)).toHaveValue(`${noticeFixture().body} 추가`);
});

// ---- versions + revert --------------------------------------------------------------------

it("lists versions with author, time, revert marks and the built-in text last", async () => {
  await renderEditor(noticeFixture({ version: 3 }), {
    history: [
      noticeVersionFixture({ version: 3, title: "셋", reverted_from: 0, author: userSummary(2) }),
      noticeVersionFixture({ version: 2, title: "둘", reverted_from: null, author: null }),
      noticeVersionFixture({ version: 1, title: "하나", reverted_from: null }),
    ],
  });
  const items = within(versionList()).getAllByRole("listitem");
  expect(items).toHaveLength(4);
  expect(items[0]).toHaveTextContent(copy.notice.versionLabel(3));
  expect(items[0]).toHaveTextContent("셋");
  expect(items[0]).toHaveTextContent("user2");
  expect(items[0]).toHaveTextContent(copy.notice.reverted(0));
  expect(items[0]).toHaveTextContent(copy.notice.current);
  expect(items[1]).toHaveTextContent(copy.notice.systemAuthor);
  expect(items[1]).not.toHaveTextContent(copy.notice.current);
  expect(items[3]).toHaveTextContent(copy.notice.defaultVersion);
  expect(items[3]).toHaveTextContent(copy.notice.builtIn.title);
});

it("compares a picked version's body with the saved one and reverts after confirming", async () => {
  let reverted: string | undefined;
  await renderEditor(noticeFixture({ version: 2, body: "새 본문" }), {
    history: [noticeVersionFixture({ version: 2 }), noticeVersionFixture({ version: 1 })],
  });
  server.use(
    http.get("/api/notice/versions/1", () => HttpResponse.json(noticeFixture({ version: 1, body: "옛 본문" }))),
    http.post("/api/notice/versions/:v/revert", ({ params }) => {
      reverted = String(params.v);
      return HttpResponse.json(noticeFixture({ version: 3, body: "옛 본문", reverted_from: 1 }));
    }),
  );
  await userEvent.click(within(versionList()).getByRole("button", { name: new RegExp(copy.notice.versionLabel(1)) }));
  const diff = await screen.findByRole("table", { name: copy.diff.caption(copy.notice.versionLabel(1), copy.notice.current) });
  expect(diff.querySelector('[data-op="del"]')).toHaveTextContent("옛 본문");
  expect(diff.querySelector('[data-op="add"]')).toHaveTextContent("새 본문");

  await userEvent.click(screen.getByRole("button", { name: copy.notice.revert }));
  const dialog = await screen.findByRole("alertdialog", { name: copy.notice.revertTitle(1) });
  await userEvent.click(within(dialog).getByRole("button", { name: copy.notice.revertAction }));
  expect(await screen.findByText(copy.notice.revertedTo(1, 3))).toBeInTheDocument();
  expect(reverted).toBe("1");
  // no edits here: the editor follows the new current version
  await waitFor(() => expect(field(copy.notice.fields.body)).toHaveValue("옛 본문"));
});

it("shows a title or button-text change even when the body is the same", async () => {
  await renderEditor(noticeFixture({ version: 2, title: "새 제목", button_text: "동의" }), {
    history: [noticeVersionFixture({ version: 2 }), noticeVersionFixture({ version: 1 })],
  });
  server.use(http.get("/api/notice/versions/1", () => HttpResponse.json(noticeFixture({ version: 1, title: "옛 제목", button_text: "확인" }))));
  await userEvent.click(within(versionList()).getByRole("button", { name: new RegExp(copy.notice.versionLabel(1)) }));
  const fields = await screen.findByRole("table", { name: copy.notice.fieldChanges });
  const titleRow = within(fields).getByRole("row", { name: new RegExp(copy.notice.fields.title) });
  expect(within(titleRow).getAllByRole("cell").map((c) => c.textContent)).toEqual(["옛 제목", "새 제목"]);
  const buttonRow = within(fields).getByRole("row", { name: new RegExp(copy.notice.fields.button_text) });
  expect(within(buttonRow).getAllByRole("cell").map((c) => c.textContent)).toEqual(["확인", "동의"]);
  expect(screen.queryByText(copy.diff.same)).toBeNull(); // the versions are not "the same"
  expect(screen.getByText(copy.notice.bodySame)).toBeInTheDocument();
});

it("reverts to the built-in default (version 0)", async () => {
  const calls = trackCalls();
  await renderEditor(noticeFixture({ version: 2, title: "고친 안내" }), {
    history: [noticeVersionFixture({ version: 2 }), noticeVersionFixture({ version: 1 })],
  });
  server.use(
    http.post("/api/notice/versions/0/revert", () =>
      HttpResponse.json(noticeFixture({ ...copy.notice.builtIn, version: 3, reverted_from: 0 })),
    ),
  );
  await userEvent.click(within(versionList()).getByRole("button", { name: new RegExp(copy.notice.defaultVersion) }));
  await userEvent.click(await screen.findByRole("button", { name: copy.notice.revert }));
  const dialog = await screen.findByRole("alertdialog", { name: copy.notice.revertTitle(0) });
  await userEvent.click(within(dialog).getByRole("button", { name: copy.notice.revertAction }));
  expect(await screen.findByText(copy.notice.revertedTo(0, 3))).toBeInTheDocument();
  expect(calls()).toContain("POST /api/notice/versions/0/revert");
  expect(calls()).toContain("GET /api/notice/versions/0");
  await waitFor(() => expect(field(copy.notice.fields.title)).toHaveValue(copy.notice.builtIn.title));
});

it("says nothing changed when a revert lands on the current text", async () => {
  await renderEditor(noticeFixture({ version: 2 }), { history: [noticeVersionFixture({ version: 2 }), noticeVersionFixture({ version: 1 })] });
  server.use(http.post("/api/notice/versions/1/revert", () => HttpResponse.json(noticeFixture({ version: 2 }))));
  await userEvent.click(within(versionList()).getByRole("button", { name: new RegExp(copy.notice.versionLabel(1)) }));
  await userEvent.click(await screen.findByRole("button", { name: copy.notice.revert }));
  await userEvent.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: copy.notice.revertAction }));
  expect(await screen.findByText(copy.notice.unchanged)).toBeInTheDocument();
});

it("offers no revert to the version in use", async () => {
  const calls = trackCalls();
  await renderEditor(noticeFixture({ version: 2 }), { history: [noticeVersionFixture({ version: 2 })] });
  await userEvent.click(within(versionList()).getByRole("button", { name: new RegExp(copy.notice.versionLabel(2)) }));
  const revert = screen.getByRole("button", { name: copy.notice.revert });
  expect(revert).toHaveAttribute("aria-disabled", "true");
  expect(revert).toHaveAccessibleDescription(copy.notice.currentNote);
  await userEvent.click(revert);
  expect(screen.queryByRole("alertdialog")).toBeNull();
  expect(calls()).not.toContain("GET /api/notice/versions/2");
});

// ---- full-screen preview, permissions -----------------------------------------------------

it("links the full-screen preview of the saved notice in a new tab", async () => {
  await renderEditor(noticeFixture({ version: 1 }));
  const link = screen.getByRole("link", { name: new RegExp(copy.notice.fullPreview) });
  expect(link).toHaveAttribute("href", "/notice");
  expect(link).toHaveAttribute("target", "_blank");
  expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
  expect(link).toHaveAccessibleDescription(copy.notice.fullPreviewNote);
});

it("notice editor on external explains and makes no request", async () => {
  const spy = trackRequests();
  renderWithProviders(null, { route: "/admin/notice", me: meFixture("admin", "external") });
  expect(await screen.findByText(copy.deny.local_only, { selector: "main p" }, { timeout: 5000 })).toBeInTheDocument();
  expect(screen.getByRole("heading", { level: 1, name: copy.notice.title })).toBeInTheDocument();
  expect(screen.queryByLabelText(copy.notice.fields.title)).toBeNull();
  expect(spy.paths().filter((p) => p.startsWith("/api/notice"))).toEqual([]);
});

it("a developer on local is told the page is for Admins, with no request", async () => {
  const spy = trackRequests();
  renderWithProviders(null, { route: "/admin/notice", me: meFixture("developer", "local") });
  expect(await screen.findByText(copy.deny.admin_only, { selector: "main p" }, { timeout: 5000 })).toBeInTheDocument();
  expect(spy.paths().filter((p) => p.startsWith("/api/notice"))).toEqual([]);
});
