import { EditorView } from "@codemirror/view";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { copy } from "@/copy/ko";
import type { McpCreate, Me, ScriptKind } from "@/lib/api-types";
import { loadDraft, saveDraft } from "@/lib/draft";
import { mcpDetailFixture, meFixture } from "../../../tests/msw/fixtures";
import { server, trackRequests } from "../../../tests/msw/server";
import { renderWithProviders } from "../../../tests/render";

afterEach(() => sessionStorage.clear());

async function renderCreate(me: Me = meFixture("developer", "local", 5)) {
  const r = renderWithProviders(null, { route: "/admin/mcps/new", me });
  await screen.findByRole("heading", { level: 1, name: copy.mcp.create }, { timeout: 5000 });
  return r;
}

const field = (label: string) => screen.getByLabelText(label);
const submit = () => screen.getByRole("button", { name: copy.mcp.createSubmit });

async function scriptView(kind: ScriptKind): Promise<EditorView> {
  const root = await screen.findByTestId(`script-field-${kind}`, {}, { timeout: 5000 });
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

async function typeScript(kind: ScriptKind, text: string) {
  const view = await scriptView(kind);
  act(() => view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: text } }));
}

async function fillConfig(name = "files", port = "9300") {
  await userEvent.type(field(copy.mcp.fields.name), name);
  await userEvent.type(field(copy.mcp.fields.port), port);
}

function capturePost(): () => McpCreate | undefined {
  let body: McpCreate | undefined;
  server.use(http.post("/api/mcps", async ({ request }) => {
    body = (await request.json()) as McpCreate;
    return HttpResponse.json(mcpDetailFixture({ id: 3, name: body.name, live: null }), { status: 201 });
  }));
  return () => body;
}

it("requires start and stop scripts and posts config with scripts", async () => {
  const posted = capturePost();
  const { router } = await renderCreate();
  await fillConfig();
  await userEvent.click(submit());
  expect(await screen.findByText(copy.mcp.scriptRequired(copy.scripts.kinds.start))).toBeInTheDocument();
  expect(screen.getByText(copy.mcp.scriptRequired(copy.scripts.kinds.stop))).toBeInTheDocument();
  expect(posted()).toBeUndefined();

  await typeScript("start", "Start-Process calc");
  await typeScript("stop", "Stop-Process -Name calc");
  await userEvent.click(submit());
  await waitFor(() => expect(posted()).toBeDefined());
  const body = posted()!;
  expect(body).toMatchObject({ name: "files", host: "127.0.0.1", port: 9300, path: "/mcp", probe: "mcp_ping", script_timeout_sec: 120 });
  expect(body.scripts).toEqual({
    start: { ext: ".ps1", content: "Start-Process calc" },
    stop: { ext: ".ps1", content: "Stop-Process -Name calc" },
  });
  expect(body.scripts).not.toHaveProperty("restart");
  await waitFor(() => expect(router.state.location.pathname).toBe("/admin/mcps/3"));
  expect(await screen.findByText(copy.mcp.created("files"))).toBeInTheDocument();
  expect(loadDraft("mcp-create")).toBeNull();
});

it("sends a restart script with its extension when one is given", async () => {
  const posted = capturePost();
  await renderCreate();
  await fillConfig();
  await typeScript("start", "a");
  await typeScript("stop", "b");
  await typeScript("restart", "echo restart");
  const restart = screen.getByRole("group", { name: copy.scripts.kinds.restart });
  await userEvent.click(within(restart).getByRole("combobox", { name: copy.scripts.ext }));
  await userEvent.click(await screen.findByRole("option", { name: ".bat" }));
  await userEvent.click(submit());
  await waitFor(() => expect(posted()?.scripts.restart).toEqual({ ext: ".bat", content: "echo restart" }));
});

it("maps endpoint_taken to the port field", async () => {
  server.use(http.post("/api/mcps", () => HttpResponse.json({ error: "endpoint_taken" }, { status: 409 })));
  await renderCreate();
  await fillConfig();
  await typeScript("start", "a");
  await typeScript("stop", "b");
  await userEvent.click(submit());
  expect(await screen.findByText(copy.errors.endpoint_taken)).toBeInTheDocument();
  expect(field(copy.mcp.fields.port)).toHaveAttribute("aria-invalid", "true");
  expect(field(copy.mcp.fields.port)).toHaveFocus();
});

it("maps name_taken to the name field", async () => {
  server.use(http.post("/api/mcps", () => HttpResponse.json({ error: "name_taken" }, { status: 409 })));
  await renderCreate();
  await fillConfig();
  await typeScript("start", "a");
  await typeScript("stop", "b");
  await userEvent.click(submit());
  expect(await screen.findByText(copy.errors.name_taken)).toBeInTheDocument();
  expect(field(copy.mcp.fields.name)).toHaveAttribute("aria-invalid", "true");
});

it("puts a script encoding error on the .bat script that has non-ASCII text", async () => {
  server.use(http.post("/api/mcps", () => HttpResponse.json({ error: "script_encoding" }, { status: 422 })));
  await renderCreate();
  await fillConfig();
  await typeScript("start", "Start-Process 한글");
  await typeScript("stop", "echo 한글");
  const stop = screen.getByRole("group", { name: copy.scripts.kinds.stop });
  await userEvent.click(within(stop).getByRole("combobox", { name: copy.scripts.ext }));
  await userEvent.click(await screen.findByRole("option", { name: ".bat" }));
  await userEvent.click(submit());
  expect(await within(stop).findByText(copy.errors.script_encoding)).toBeInTheDocument();
  const start = screen.getByRole("group", { name: copy.scripts.kinds.start });
  expect(within(start).queryByText(copy.errors.script_encoding)).toBeNull(); // .ps1 is UTF-8: never the cause
  expect((await scriptView("stop")).contentDOM).toHaveAttribute("aria-invalid", "true");
});

it("shows other server errors for the whole form", async () => {
  server.use(http.post("/api/mcps", () => HttpResponse.json({ error: "validation" }, { status: 422 })));
  await renderCreate();
  await fillConfig();
  await typeScript("start", "a");
  await typeScript("stop", "b");
  await userEvent.click(submit());
  expect(await screen.findByRole("alert")).toHaveTextContent(copy.errors.validation);
});

it("validates the config fields on the client", async () => {
  const calls = trackRequests();
  await renderCreate();
  await userEvent.type(field(copy.mcp.fields.name), "a&b");
  await typeScript("start", "a");
  await typeScript("stop", "b");
  await userEvent.click(submit());
  expect(await screen.findByText(copy.mcp.nameRule, { selector: "[data-slot=form-message]" })).toBeInTheDocument();
  expect(screen.getByText(copy.mcp.rangeError(1, 65535))).toBeInTheDocument();
  expect(calls.paths()).not.toContain("/api/mcps");
});

it("keeps a draft and restores it on the next visit", async () => {
  const first = await renderCreate();
  await userEvent.type(field(copy.mcp.fields.name), "files");
  await typeScript("start", "Start-Process files");
  await waitFor(() => expect(loadDraft("mcp-create")).toMatchObject({ name: "files", scripts: { start: { content: "Start-Process files" } } }));
  first.unmount();

  await renderCreate();
  expect(await screen.findByText(copy.scripts.draftRestored)).toBeInTheDocument();
  expect(field(copy.mcp.fields.name)).toHaveValue("files");
  expect((await scriptView("start")).state.doc.toString()).toBe("Start-Process files");
  await userEvent.click(screen.getByRole("button", { name: copy.scripts.discardDraft }));
  expect(field(copy.mcp.fields.name)).toHaveValue("");
  expect((await scriptView("start")).state.doc.toString()).toBe("");
  expect(loadDraft("mcp-create")).toBeNull();
});

it("ignores a draft of the wrong shape", async () => {
  saveDraft("mcp-create", { name: 5, scripts: "nope" });
  await renderCreate();
  expect(field(copy.mcp.fields.name)).toHaveValue("");
  expect(screen.queryByText(copy.scripts.draftRestored)).toBeNull();
});

it("create page on external explains and makes no request", async () => {
  const spy = trackRequests();
  await renderCreate(meFixture("admin", "external", 1));
  expect(within(screen.getByRole("main")).getByText(copy.deny.local_only)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: copy.mcp.createSubmit })).toBeNull();
  expect(spy.paths().filter((p) => p.startsWith("/api/mcps"))).toEqual([]);
});

it("cancel drops the draft and returns to the list", async () => {
  const { router } = await renderCreate();
  await userEvent.type(field(copy.mcp.fields.name), "files");
  await waitFor(() => expect(loadDraft("mcp-create")).not.toBeNull());
  await userEvent.click(screen.getByRole("button", { name: copy.mcp.createCancel }));
  await waitFor(() => expect(router.state.location.pathname).toBe("/admin/mcps"));
  expect(loadDraft("mcp-create")).toBeNull();
});

it("marks the script editors as required or optional for assistive tech", async () => {
  await renderCreate();
  expect((await scriptView("start")).contentDOM).toHaveAttribute("aria-required", "true");
  expect((await scriptView("stop")).contentDOM).toHaveAttribute("aria-required", "true");
  const restart = (await scriptView("restart")).contentDOM;
  expect(restart).not.toHaveAttribute("aria-required");
  expect(restart).toHaveAccessibleName(copy.scripts.editorLabel(copy.scripts.kinds.restart));
  expect(restart).toHaveAccessibleDescription(copy.scripts.optionalRestart);
});
