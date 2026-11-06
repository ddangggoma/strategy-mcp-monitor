import { EditorView } from "@codemirror/view";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { copy } from "@/copy/ko";
import type { Me, ScriptContent, ScriptKind, ScriptVersion } from "@/lib/api-types";
import { loadDraft, saveDraft } from "@/lib/draft";
import {
  mcpDetailFixture, meFixture, scriptFixture, scriptListFixture, scriptVersionFixture, userSummary,
} from "../../../tests/msw/fixtures";
import { server, trackRequests } from "../../../tests/msw/server";
import { renderWithProviders } from "../../../tests/render";
import { qk } from "../query-keys";
import { warmChunks } from "../../../tests/warm";

warmChunks("mcpDetail", "scriptEditor", "login");

afterEach(() => sessionStorage.clear());

interface ScriptsOptions {
  me: Me;
  /** Owner user id, or null for an MCP without owner. */
  owner: number | null;
  script?: ScriptContent;
  kind?: ScriptKind;
  /** Kinds that exist (GET .../scripts). */
  kinds?: ScriptKind[];
  versions?: ScriptVersion[];
}

/** The detail page on the scripts tab, in the full admin app (shell, toasts, 401 handling). */
async function renderScripts({ me, owner, script = scriptFixture(), kind = "start", kinds = ["start", "stop"], versions }: ScriptsOptions) {
  const detail = mcpDetailFixture({ id: 1, name: "calc", owner: owner === null ? null : userSummary(owner) });
  server.use(
    http.get("/api/mcps/1", () => HttpResponse.json(detail)),
    http.get("/api/mcps/1/scripts", () => HttpResponse.json(scriptListFixture(kinds))),
    http.get("/api/mcps/1/scripts/:kind", ({ params }) => HttpResponse.json({ ...script, kind: params.kind as ScriptKind })),
  );
  if (versions) server.use(http.get("/api/mcps/1/scripts/:kind/versions", () => HttpResponse.json(versions)));
  const r = renderWithProviders(null, { route: `/admin/mcps/1?tab=scripts&kind=${kind}`, me });
  await screen.findByRole("heading", { level: 1, name: "calc" }, { timeout: 5000 });
  return r;
}

const ownerMe = () => meFixture("developer", "local", 5);

/** The CodeMirror view inside the script editor (lazy chunk: allow for the first compile). */
async function editorView(testId = "script-editor"): Promise<EditorView> {
  const root = await screen.findByTestId(testId, {}, { timeout: 5000 });
  return waitFor(
    () => {
      const el = root.querySelector<HTMLElement>(".cm-editor");
      const view = el ? EditorView.findFromDOM(el) : null;
      if (!view) throw new Error("editor not mounted yet");
      return view;
    },
    { timeout: 5000 },
  );
}

let view: EditorView;
const editorText = () => view.state.doc.toString();
function replaceText(v: EditorView, text: string) {
  act(() => v.dispatch({ changes: { from: 0, to: v.state.doc.length, insert: text } }));
}

/** Method + path of every request from now on. */
function trackCalls(): () => string[] {
  const seen: string[] = [];
  server.events.on("request:start", ({ request }) => {
    seen.push(`${request.method} ${new URL(request.url).pathname}`);
  });
  return () => [...seen];
}

const saveButton = () => screen.getByRole("button", { name: copy.common.save });

// ---- editor vs viewer by permission ----------------------------------------------------

it("owner on local gets the CodeMirror editor and saves a new version", async () => {
  let body: unknown;
  server.use(http.put("/api/mcps/1/scripts/start", async ({ request }) => {
    body = await request.json();
    return HttpResponse.json({ kind: "start", ext: ".ps1", version: 3, sha256: "b".repeat(64) });
  }));
  await renderScripts({ me: ownerMe(), owner: 5, script: scriptFixture({ editable: true, version: 2, content: "Write-Host start\r\n" }) });
  expect(await screen.findByTestId("script-editor", {}, { timeout: 5000 })).toBeInTheDocument();
  view = await editorView();
  expect(editorText()).toBe("Write-Host start\n");
  expect(saveButton()).toHaveAttribute("aria-disabled", "true"); // nothing changed yet
  expect(saveButton()).toHaveAccessibleDescription(copy.deny.unchanged); // and it says so (U26)
  replaceText(view, "Write-Host changed\n");
  expect(saveButton()).not.toHaveAttribute("aria-disabled");
  await userEvent.click(saveButton());
  await waitFor(() => expect(body).toEqual({ ext: ".ps1", content: "Write-Host changed\n" }));
  expect(await screen.findByText(copy.scripts.savedVersion(3))).toBeInTheDocument();
  expect(loadDraft("script:1:start")).toBeNull();
  // the refetch after the save may still answer with the older version: the saved text stays
  await new Promise((r) => setTimeout(r, 50));
  expect(editorText()).toBe("Write-Host changed\n");
  expect(saveButton()).toHaveAttribute("aria-disabled", "true");
});

it("adopts a newer server version while there are no edits", async () => {
  const { qc } = await renderScripts({ me: ownerMe(), owner: 5, script: scriptFixture({ editable: true, version: 2, content: "old" }) });
  view = await editorView();
  act(() => qc.setQueryData(qk.script(1, "start"), scriptFixture({ editable: true, version: 4, content: "reverted\r\n" })));
  await waitFor(() => expect(editorText()).toBe("reverted\n"));
  expect(saveButton()).toHaveAttribute("aria-disabled", "true");
});

it("keeps the edits but says so when a newer version is saved elsewhere meanwhile", async () => {
  const { qc } = await renderScripts({ me: ownerMe(), owner: 5, script: scriptFixture({ editable: true, version: 2, content: "old" }) });
  view = await editorView();
  replaceText(view, "my edit");
  act(() => qc.setQueryData(qk.script(1, "start"), scriptFixture({ editable: true, version: 5, content: "theirs" })));
  expect(await screen.findByText(copy.scripts.newerWhileEditing(5))).toBeInTheDocument();
  expect(editorText()).toBe("my edit"); // nothing on screen is replaced
  expect(saveButton()).not.toHaveAttribute("aria-disabled"); // the user may still overwrite, knowingly
  // a reload keeps the warning: the draft still names the version the edits started from
  expect(loadDraft("script:1:start")).toMatchObject({ content: "my edit", baseVersion: 2 });
  replaceText(view, "my edit 2");
  expect(loadDraft("script:1:start")).toMatchObject({ baseVersion: 2 });
  // dropping the edits takes the newer version
  await userEvent.click(screen.getByRole("button", { name: copy.scripts.discardDraft }));
  expect(editorText()).toBe("theirs");
  expect(screen.queryByText(copy.scripts.newerWhileEditing(5))).toBeNull();
});

it("Ctrl+S saves from inside the editor", async () => {
  const calls = trackCalls();
  await renderScripts({ me: ownerMe(), owner: 5, script: scriptFixture({ editable: true }) });
  view = await editorView();
  replaceText(view, "Write-Host via shortcut");
  view.contentDOM.focus();
  await userEvent.keyboard("{Control>}s{/Control}");
  await waitFor(() => expect(calls()).toContain("PUT /api/mcps/1/scripts/start"));
});

it("non-owner on local sees a read-only viewer and the owner reason", async () => {
  await renderScripts({ me: meFixture("developer", "local", 5), owner: 6, script: scriptFixture({ editable: false }) });
  expect(await screen.findByTestId("script-viewer")).toBeInTheDocument();
  expect(screen.queryByTestId("script-editor")).toBeNull();
  const edit = screen.getByRole("button", { name: copy.scripts.edit });
  expect(edit).toHaveAttribute("aria-disabled", "true");
  expect(edit).toHaveAccessibleDescription(copy.deny.owner_only);
});

it("owner-less MCP explains that ownership must be transferred", async () => {
  await renderScripts({ me: meFixture("admin", "local", 1), owner: null, script: scriptFixture({ editable: false }) });
  await screen.findByTestId("script-viewer");
  const edit = screen.getByRole("button", { name: copy.scripts.edit });
  expect(edit).toHaveAttribute("aria-disabled", "true");
  expect(edit).toHaveAccessibleDescription(copy.deny.no_owner);
});

it("external channel shows the local-only reason and makes no script request", async () => {
  const spy = trackRequests();
  await renderScripts({ me: meFixture("admin", "external", 1), owner: 1 });
  const panel = screen.getByRole("tabpanel", { name: copy.mcp.tabs.scripts });
  expect(await within(panel).findByText(copy.deny.local_only)).toBeInTheDocument();
  expect(spy.paths().filter((p) => p.includes("/scripts"))).toEqual([]);
  expect(screen.queryByRole("group", { name: copy.scripts.kindsLabel })).toBeNull();
});

it("the viewer numbers lines and copies the script", async () => {
  const user = userEvent.setup();
  await renderScripts({ me: meFixture("developer", "local", 5), owner: 6, script: scriptFixture({ content: "first\r\nsecond\r\n" }) });
  const viewer = await screen.findByTestId("script-viewer");
  const lines = within(viewer).getAllByTestId("script-line");
  expect(lines.map((l) => l.textContent)).toEqual(["1first", "2second"]);
  await user.click(within(viewer).getByRole("button", { name: copy.common.copyText }));
  expect(await navigator.clipboard.readText()).toBe("first\r\nsecond\r\n");
  expect(await screen.findByText(copy.common.copied)).toBeInTheDocument();
});

// ---- kinds -----------------------------------------------------------------------------

it("switches kinds through ?kind= and shows which exist", async () => {
  const { router } = await renderScripts({ me: ownerMe(), owner: 6, kinds: ["start", "stop"] });
  const kinds = await screen.findByRole("group", { name: copy.scripts.kindsLabel });
  expect(within(kinds).getByRole("button", { name: copy.scripts.kinds.start })).toHaveAttribute("aria-pressed", "true");
  await userEvent.click(within(kinds).getByRole("button", { name: copy.scripts.kinds.stop }));
  await waitFor(() => expect(router.state.location.search).toMatchObject({ tab: "scripts", kind: "stop" }));
  expect(within(kinds).getByRole("button", { name: copy.scripts.kinds.stop })).toHaveAttribute("aria-pressed", "true");
  const missing = await within(kinds).findByText(copy.scripts.missing);
  expect(missing.closest("button")).toHaveTextContent(copy.scripts.kinds.restart);
  expect(within(kinds).getAllByText(copy.scripts.missing)).toHaveLength(1);
});

it("a missing restart script offers the owner an add button and opens an empty editor", async () => {
  const spy = trackRequests();
  await renderScripts({ me: ownerMe(), owner: 5, kind: "restart", kinds: ["start", "stop"] });
  expect(await screen.findByText(copy.scripts.noRestart)).toBeInTheDocument();
  expect(spy.paths()).not.toContain("/api/mcps/1/scripts/restart"); // the list says it does not exist
  await userEvent.click(screen.getByRole("button", { name: copy.scripts.addRestart }));
  view = await editorView();
  expect(editorText()).toBe("");
});

it("a non-owner cannot add a restart script and is told why", async () => {
  await renderScripts({ me: meFixture("developer", "local", 5), owner: 6, kind: "restart", kinds: ["start", "stop"] });
  const add = await screen.findByRole("button", { name: copy.scripts.addRestart });
  expect(add).toHaveAttribute("aria-disabled", "true");
  expect(add).toHaveAccessibleDescription(copy.deny.owner_only);
});

it("deletes the restart script after confirmation; start has no delete button", async () => {
  const calls = trackCalls();
  await renderScripts({ me: ownerMe(), owner: 5, kind: "restart", kinds: ["start", "stop", "restart"], script: scriptFixture({ editable: true }) });
  await editorView();
  await userEvent.click(screen.getByRole("button", { name: copy.scripts.deleteRestart }));
  const dialog = await screen.findByRole("alertdialog", { name: copy.scripts.deleteRestartTitle });
  expect(calls()).not.toContain("DELETE /api/mcps/1/scripts/restart");
  await userEvent.click(within(dialog).getByRole("button", { name: copy.common.delete }));
  await waitFor(() => expect(calls()).toContain("DELETE /api/mcps/1/scripts/restart"));
  expect(await screen.findByText(copy.scripts.restartDeleted)).toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: copy.scripts.kinds.start }));
  await editorView();
  expect(screen.queryByRole("button", { name: copy.scripts.deleteRestart })).toBeNull();
});

// ---- versions, diff, revert ------------------------------------------------------------

const twoVersions = [scriptVersionFixture({ version: 2 }), scriptVersionFixture({ version: 1, author: userSummary(7) })];

it("diffs a selected version against the current content", async () => {
  server.use(http.get("/api/mcps/1/scripts/start/versions/1", () =>
    HttpResponse.json({ ...scriptVersionFixture({ version: 1 }), content: "Write-Host start\r\nWrite-Host one\r\n" }),
  ));
  await renderScripts({
    me: meFixture("developer", "local", 5), owner: 6, versions: twoVersions,
    script: scriptFixture({ version: 2, content: "Write-Host start\r\nWrite-Host two\r\n" }),
  });
  const list = await screen.findByRole("list", { name: copy.scripts.versions });
  expect(within(list).getByText(copy.scripts.current)).toBeInTheDocument();
  await userEvent.click(within(list).getByRole("button", { name: new RegExp(copy.scripts.versionLabel(1)) }));
  const diff = await screen.findByRole("table", { name: copy.diff.caption(copy.scripts.versionLabel(1), copy.scripts.current) });
  expect(within(diff).getByText("Write-Host one").closest("[data-op]")).toHaveAttribute("data-op", "del");
  expect(within(diff).getByText("Write-Host two").closest("[data-op]")).toHaveAttribute("data-op", "add");
  expect(within(diff).getByText("Write-Host start").closest("[data-op]")).toHaveAttribute("data-op", "same");
});

it("reverts to a version after confirmation", async () => {
  const calls = trackCalls();
  await renderScripts({ me: ownerMe(), owner: 5, versions: twoVersions, script: scriptFixture({ version: 2, editable: true }) });
  const list = await screen.findByRole("list", { name: copy.scripts.versions });
  await userEvent.click(within(list).getByRole("button", { name: new RegExp(copy.scripts.versionLabel(1)) }));
  await userEvent.click(await screen.findByRole("button", { name: copy.scripts.revert }));
  const dialog = await screen.findByRole("alertdialog", { name: copy.scripts.revertTitle(1) });
  expect(calls()).not.toContain("POST /api/mcps/1/scripts/start/versions/1/revert");
  const versionsBefore = calls().filter((c) => c === "GET /api/mcps/1/scripts/start/versions").length;
  await userEvent.click(within(dialog).getByRole("button", { name: copy.scripts.revertAction }));
  await waitFor(() => expect(calls()).toContain("POST /api/mcps/1/scripts/start/versions/1/revert"));
  expect(await screen.findByText(copy.scripts.reverted(1, 3))).toBeInTheDocument();
  // the list is invalidated: fetched again
  await waitFor(() => expect(calls().filter((c) => c === "GET /api/mcps/1/scripts/start/versions").length).toBe(versionsBefore + 1));
});

it("a non-owner can compare versions but not revert", async () => {
  await renderScripts({ me: meFixture("developer", "local", 5), owner: 6, versions: twoVersions });
  const list = await screen.findByRole("list", { name: copy.scripts.versions });
  await userEvent.click(within(list).getByRole("button", { name: new RegExp(copy.scripts.versionLabel(1)) }));
  const revert = await screen.findByRole("button", { name: copy.scripts.revert });
  expect(revert).toHaveAttribute("aria-disabled", "true");
  expect(revert).toHaveAccessibleDescription(copy.deny.owner_only);
});

it("marks a deleted version and does not offer to revert to it", async () => {
  const calls = trackCalls();
  await renderScripts({
    me: ownerMe(), owner: 5, kind: "restart", kinds: ["start", "stop", "restart"], script: scriptFixture({ version: 3, editable: true }),
    versions: [
      scriptVersionFixture({ version: 3 }),
      scriptVersionFixture({ version: 2, ext: null, sha256: null, deleted: true }),
      scriptVersionFixture({ version: 1 }),
    ],
  });
  const list = await screen.findByRole("list", { name: copy.scripts.versions });
  const deleted = within(list).getByRole("button", { name: new RegExp(copy.scripts.versionLabel(2)) });
  expect(deleted).toHaveTextContent(copy.scripts.deletedTag);
  await userEvent.click(deleted);
  expect(await screen.findByText(copy.scripts.deletedNote)).toBeInTheDocument();
  const revert = screen.getByRole("button", { name: copy.scripts.revert });
  expect(revert).toHaveAttribute("aria-disabled", "true");
  await userEvent.click(revert);
  expect(screen.queryByRole("alertdialog")).toBeNull();
  expect(calls().some((c) => c.includes("/versions/2"))).toBe(false); // nothing to fetch for a deleted version
});

it("the current version needs no revert", async () => {
  await renderScripts({ me: ownerMe(), owner: 5, versions: twoVersions, script: scriptFixture({ version: 2, editable: true }) });
  const list = await screen.findByRole("list", { name: copy.scripts.versions });
  await userEvent.click(within(list).getByRole("button", { name: new RegExp(copy.scripts.versionLabel(2)) }));
  expect(await screen.findByText(copy.scripts.currentNote)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: copy.scripts.revert })).toHaveAttribute("aria-disabled", "true");
});

// ---- drafts, errors, leaving ------------------------------------------------------------

it("restores the script draft after re-login", async () => {
  saveDraft("script:1:start", { ext: ".ps1", content: "Write-Host draft", baseVersion: 2 }, 5);
  await renderScripts({ me: ownerMe(), owner: 5, script: scriptFixture({ editable: true, version: 2, content: "Write-Host saved" }) });
  expect(await screen.findByText(copy.scripts.draftRestored, {}, { timeout: 5000 })).toBeInTheDocument();
  view = await editorView();
  expect(editorText()).toContain("Write-Host draft");
  expect(saveButton()).not.toHaveAttribute("aria-disabled");
});

it("discarding the draft puts the saved script back", async () => {
  saveDraft("script:1:start", { ext: ".ps1", content: "Write-Host draft", baseVersion: 2 }, 5);
  await renderScripts({ me: ownerMe(), owner: 5, script: scriptFixture({ editable: true, version: 2, content: "Write-Host saved" }) });
  await userEvent.click(await screen.findByRole("button", { name: copy.scripts.discardDraft }, { timeout: 5000 }));
  view = await editorView();
  expect(editorText()).toBe("Write-Host saved");
  expect(loadDraft("script:1:start")).toBeNull();
  expect(screen.queryByText(copy.scripts.draftRestored)).toBeNull();
});

it("a draft equal to the saved script is dropped silently", async () => {
  saveDraft("script:1:start", { ext: ".ps1", content: "Write-Host saved\n", baseVersion: 1 }, 5);
  await renderScripts({ me: ownerMe(), owner: 5, script: scriptFixture({ editable: true, content: "Write-Host saved\r\n" }) });
  view = await editorView();
  expect(screen.queryByText(copy.scripts.draftRestored)).toBeNull();
  expect(loadDraft("script:1:start")).toBeNull();
});

it("warns when the script was saved again after the draft was made", async () => {
  saveDraft("script:1:start", { ext: ".ps1", content: "Write-Host draft", baseVersion: 1 }, 5);
  await renderScripts({ me: ownerMe(), owner: 5, script: scriptFixture({ editable: true, version: 4 }) });
  expect(await screen.findByText(copy.scripts.draftStale(4), {}, { timeout: 5000 })).toBeInTheDocument();
});

it("writes a draft on every change and drops it when the text is typed back", async () => {
  await renderScripts({ me: ownerMe(), owner: 5, script: scriptFixture({ editable: true, version: 2, content: "Write-Host start" }) });
  view = await editorView();
  replaceText(view, "Write-Host edit");
  expect(loadDraft("script:1:start")).toEqual({ ext: ".ps1", content: "Write-Host edit", baseVersion: 2 });
  replaceText(view, "Write-Host start");
  expect(loadDraft("script:1:start")).toBeNull();
});

it("whole flow (RF1): edit, save → 401 → log in again → back on the editor with the draft", async () => {
  let expired = true;
  server.use(
    http.put("/api/mcps/1/scripts/start", () =>
      expired
        ? HttpResponse.json({ error: "login_required" }, { status: 401 })
        : HttpResponse.json({ kind: "start", ext: ".ps1", version: 3, sha256: "b".repeat(64) }),
    ),
    http.post("/api/auth/otp/verify", () => {
      expired = false;
      const me = ownerMe();
      return HttpResponse.json({ user: me.user, csrf_token: "csrf-again" });
    }),
  );
  const { router } = await renderScripts({ me: ownerMe(), owner: 5, script: scriptFixture({ editable: true, version: 2 }) });
  view = await editorView();
  replaceText(view, "Write-Host unsaved");
  await userEvent.click(saveButton());

  // the login page, then email and code as a person would
  await userEvent.type(await screen.findByLabelText(copy.login.email, {}, { timeout: 5000 }), "user5@example.com");
  await userEvent.click(screen.getByRole("button", { name: copy.login.sendCode }));
  await screen.findByRole("group", { name: copy.login.codeGroup });
  await userEvent.click(screen.getByLabelText(copy.login.codeDigit(1)));
  await userEvent.paste("246810");

  await waitFor(() => expect(router.state.location.href).toBe("/admin/mcps/1?tab=scripts&kind=start"));
  expect(await screen.findByText(copy.scripts.draftRestored, {}, { timeout: 5000 })).toBeInTheDocument();
  view = await editorView();
  expect(editorText()).toBe("Write-Host unsaved");
  await userEvent.click(saveButton());
  expect(await screen.findByText(copy.scripts.savedVersion(3))).toBeInTheDocument();
  expect(loadDraft("script:1:start")).toBeNull();
});

it("a 401 on save keeps the draft and sends the user to login with this page as redirect", async () => {
  server.use(http.put("/api/mcps/1/scripts/start", () => HttpResponse.json({ error: "login_required" }, { status: 401 })));
  const { router } = await renderScripts({ me: ownerMe(), owner: 5, script: scriptFixture({ editable: true }) });
  view = await editorView();
  replaceText(view, "Write-Host unsaved");
  await userEvent.click(saveButton());
  await waitFor(() => expect(router.state.location.pathname).toBe("/admin/login"));
  expect(router.state.location.href).toBe("/admin/login?redirect=%2Fadmin%2Fmcps%2F1%3Ftab%3Dscripts%26kind%3Dstart");
  // F12: the unsaved-changes guard did not hold the forced navigation
  expect(screen.queryByRole("alertdialog", { name: copy.common.unsavedTitle })).toBeNull();
  expect(loadDraft("script:1:start", 5)).toMatchObject({ content: "Write-Host unsaved" });
});

it("shows encoding errors under the editor", async () => {
  server.use(http.put("/api/mcps/1/scripts/start", () => HttpResponse.json({ error: "script_encoding" }, { status: 422 })));
  await renderScripts({ me: ownerMe(), owner: 5, script: scriptFixture({ editable: true }) });
  view = await editorView();
  replaceText(view, "echo 한글");
  await userEvent.click(saveButton());
  expect(await screen.findByRole("alert")).toHaveTextContent(copy.errors.script_encoding);
  expect(view.contentDOM).toHaveAttribute("aria-invalid", "true");
  expect(view.contentDOM).toHaveAccessibleDescription(expect.stringContaining(copy.errors.script_encoding));
  expect(loadDraft("script:1:start")).toMatchObject({ content: "echo 한글" });
});

it("refuses an empty script and one over the length limit without a request", async () => {
  const calls = trackCalls();
  await renderScripts({ me: ownerMe(), owner: 5, script: scriptFixture({ editable: true }) });
  view = await editorView();
  replaceText(view, "   \n");
  await userEvent.click(saveButton());
  expect(await screen.findByRole("alert")).toHaveTextContent(copy.errors.script_empty);

  replaceText(view, "x".repeat(65_537));
  expect(screen.getByText(copy.scripts.count(65_537, 65_536))).toBeInTheDocument();
  expect(screen.getByText(copy.scripts.tooLong)).toBeInTheDocument();
  expect(saveButton()).toHaveAttribute("aria-disabled", "true");
  await userEvent.click(saveButton());
  expect(calls()).not.toContain("PUT /api/mcps/1/scripts/start");
});

it("changing the extension is a change and is sent", async () => {
  let body: unknown;
  server.use(http.put("/api/mcps/1/scripts/start", async ({ request }) => {
    body = await request.json();
    return HttpResponse.json({ kind: "start", ext: ".cmd", version: 2, sha256: "b".repeat(64) });
  }));
  await renderScripts({ me: ownerMe(), owner: 5, script: scriptFixture({ editable: true, content: "echo hi" }) });
  await editorView();
  await userEvent.click(screen.getByRole("combobox", { name: copy.scripts.ext }));
  await userEvent.click(await screen.findByRole("option", { name: ".cmd" }));
  await userEvent.click(saveButton());
  await waitFor(() => expect(body).toEqual({ ext: ".cmd", content: "echo hi" }));
});

it("asks before leaving the page with unsaved script edits", async () => {
  const { router } = await renderScripts({ me: ownerMe(), owner: 5, script: scriptFixture({ editable: true }) });
  view = await editorView();
  replaceText(view, "Write-Host unsaved");
  const nav = screen.getByRole("navigation", { name: copy.nav.label });
  await userEvent.click(within(nav).getByRole("link", { name: copy.nav.mcps }));
  const ask = await screen.findByRole("alertdialog", { name: copy.common.unsavedTitle });
  await userEvent.click(within(ask).getByRole("button", { name: copy.common.stay }));
  await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  expect(router.state.location.pathname).toBe("/admin/mcps/1");
  expect(editorText()).toBe("Write-Host unsaved");
});
