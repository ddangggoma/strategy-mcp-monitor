import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { copy } from "@/copy/ko";
import { auditExportUrl } from "@/lib/endpoints";
import { logItem, logPage, meFixture } from "../../../tests/msw/fixtures";
import { server, trackRequests } from "../../../tests/msw/server";
import { renderWithProviders } from "../../../tests/render";
import { warmChunks } from "../../../tests/warm";
import { auditTarget } from "./AuditPage";

warmChunks("audit");

const ME = meFixture("developer", "external");
beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({ left: 0, top: 0, width: 1200, height: 800, right: 1200, bottom: 800, x: 0, y: 0, toJSON: () => ({}) } as DOMRect);
});

/** Query parameters of every /api/audit request so far. */
const auditParams = (tracker: ReturnType<typeof trackRequests>) =>
  tracker
    .urls()
    .map((u) => new URL(u, "http://x"))
    .filter((u) => u.pathname === "/api/audit")
    .map((u) => u.searchParams);

// ---- plan tests --------------------------------------------------------------------------

it("lists admin actions with channel and result", async () => {
  server.use(http.get("/api/audit", () => HttpResponse.json(logPage([logItem({ cat: "admin.audit", event: "user_create", user: "a@x.com",
    outcome: "denied", client_ip: "127.0.0.1", data: { channel: "local", target: { email: "b@x.com" }, result: "denied" } })]))));
  renderWithProviders(null, { me: ME, route: "/admin/audit" });
  const row = (await screen.findByText("user_create")).closest("tr")!;
  expect(row).toHaveTextContent("a@x.com"); expect(row).toHaveTextContent(copy.channel.local);
  expect(row).toHaveTextContent(copy.audit.results.denied); expect(row).toHaveTextContent("email=b@x.com");
});
it("puts the result right after the action, before the free-width target (Task 16 critique)", async () => {
  server.use(http.get("/api/audit", () => HttpResponse.json(logPage([logItem({ cat: "admin.audit", event: "user_create" })]))));
  renderWithProviders(null, { me: ME, route: "/admin/audit" });
  const table = await screen.findByRole("table", { name: copy.audit.title });
  await within(table).findByText("user_create");
  const c = copy.audit.columns;
  expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual([c.ts, c.actor, c.channel, c.ip, c.action, c.result, c.target]);
});
it("switching to the login tab requests kind=auth", async () => {
  const tracker = trackRequests();
  const { router } = renderWithProviders(null, { me: ME, route: "/admin/audit" });
  await userEvent.click(await screen.findByRole("tab", { name: copy.audit.kinds.auth }));
  await waitFor(() => expect(router.state.location.search).toMatchObject({ kind: "auth" }));
  await waitFor(() => expect(tracker.urls().some((u) => new URL(u, "http://x").searchParams.get("kind") === "auth")).toBe(true));
});
it("filters by result through chips", async () => {
  const { router } = renderWithProviders(null, { me: ME, route: "/admin/audit" });
  await userEvent.click(await screen.findByRole("button", { name: copy.audit.results.denied }));
  await waitFor(() => expect(router.state.location.search).toMatchObject({ result: ["denied"] }));
});

// ---- added -------------------------------------------------------------------------------

it("asks for admin actions of the last 7 days by default, on minute bounds", async () => {
  const tracker = trackRequests();
  renderWithProviders(null, { me: ME, route: "/admin/audit" });
  expect(await screen.findByRole("tab", { name: copy.audit.kinds.admin, selected: true })).toBeInTheDocument();
  await waitFor(() => expect(auditParams(tracker).length).toBeGreaterThan(0));
  const p = auditParams(tracker)[0]!;
  expect(p.get("kind")).toBe("admin");
  expect(p.get("from")).toMatch(/^\d{4}-\d{2}-\d{2}T00:00:00\.000\+09:00$/);
  expect(p.get("to")).toMatch(/:00\.000\+09:00$/);
  expect((Date.parse(p.get("to")!) - Date.parse(p.get("from")!)) / 86_400_000).toBeGreaterThan(6);
  expect(screen.getByRole("button", { name: copy.logs.quick["7d"] })).toHaveAttribute("aria-pressed", "true");
});

it("shows the result chips of each kind and drops results the new kind does not have", async () => {
  const { router } = renderWithProviders(null, { me: ME, route: "/admin/audit?result=%5B%22denied%22%5D" });
  const chips = await screen.findByRole("group", { name: copy.audit.columns.result });
  expect(within(chips).getAllByRole("button").map((b) => b.textContent)).toEqual([copy.audit.results.ok, copy.audit.results.denied, copy.audit.results.error]);
  expect(within(chips).getByRole("button", { name: copy.audit.results.denied })).toHaveAttribute("aria-pressed", "true");
  await userEvent.click(screen.getByRole("tab", { name: copy.audit.kinds.auth }));
  await waitFor(() => expect(router.state.location.search).toMatchObject({ kind: "auth" }));
  expect(router.state.location.search).not.toHaveProperty("result");
  const authChips = screen.getByRole("group", { name: copy.audit.columns.result });
  expect(within(authChips).getAllByRole("button").map((b) => b.textContent)).toEqual([copy.audit.results.ok, copy.audit.results.fail]);
  await userEvent.click(screen.getByRole("tab", { name: copy.audit.kinds.all }));
  await waitFor(() => expect(router.state.location.search).toMatchObject({ kind: "all" }));
  expect(within(screen.getByRole("group", { name: copy.audit.columns.result })).getAllByRole("button")).toHaveLength(4);
});

it("filters by channel and sends it", async () => {
  const tracker = trackRequests();
  const { router } = renderWithProviders(null, { me: ME, route: "/admin/audit" });
  const group = await screen.findByRole("group", { name: copy.audit.columns.channel });
  expect(within(group).getByRole("button", { name: copy.audit.channels.all })).toHaveAttribute("aria-pressed", "true");
  await userEvent.click(within(group).getByRole("button", { name: copy.audit.channels.external }));
  await waitFor(() => expect(router.state.location.search).toMatchObject({ channel: "external" }));
  await waitFor(() => expect(auditParams(tracker).some((p) => p.get("channel") === "external")).toBe(true));
  await userEvent.click(within(group).getByRole("button", { name: copy.audit.channels.all }));
  await waitFor(() => expect(router.state.location.search).not.toHaveProperty("channel"));
});

it("shows login attempts with the browser, the Windows account and a failure mark", async () => {
  const ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36";
  server.use(http.get("/api/audit", () => HttpResponse.json(logPage([logItem({ cat: "auth", event: "login", user: "kim@x.com", outcome: "fail",
    client_ip: "10.0.3.9", data: { channel: "external", email: "kim@x.com", ok: false, user_agent: ua } }),
  logItem({ id: 2, cat: "auth", event: "login", user: "lee@x.com", outcome: "ok", client_ip: "127.0.0.1",
    data: { channel: "local", email: "lee@x.com", ok: true, user_agent: ua, windows_user: "CORP\\lee" } })]))));
  renderWithProviders(null, { me: ME, route: "/admin/audit?kind=%22auth%22" });
  const failed = (await screen.findByText("kim@x.com")).closest("tr")!;
  expect(failed).toHaveTextContent(copy.channel.external);
  expect(failed).toHaveTextContent(ua.slice(0, 60));
  expect(failed).not.toHaveTextContent(ua.slice(0, 61));
  expect(failed).toHaveTextContent(copy.audit.results.fail);
  // the result is an icon and a word, never the colour alone
  expect(within(failed).getByText(copy.audit.results.fail).closest("[data-result]")!.querySelector("svg")).not.toBeNull();
  const ok = screen.getByText("lee@x.com").closest("tr")!;
  expect(ok).toHaveTextContent(copy.audit.windowsUser("CORP\\lee"));
  expect(ok).toHaveTextContent(copy.audit.results.ok);
});

it("summarizes admin targets as key=value pairs in at most 120 characters", () => {
  const admin = (target: unknown) => logItem({ cat: "admin.audit", event: "x", data: { target } });
  expect(auditTarget(admin({ email: "b@x.com", role: "admin" }))).toBe("email=b@x.com, role=admin");
  expect(auditTarget(admin({ changes: { ping_interval_sec: [5, 7] } }))).toBe('changes={"ping_interval_sec":[5,7]}');
  expect(auditTarget(admin({ id: 3, enabled: false, note: null }))).toBe("id=3, enabled=false, note=null");
  const long = auditTarget(admin({ q: "a".repeat(300) }));
  expect(long).toHaveLength(120);
  expect(long.endsWith("…")).toBe(true);
  expect(auditTarget(admin(undefined))).toBe("");
  expect(auditTarget(logItem({ cat: "auth", data: { user_agent: "UA" } }))).toBe("UA");
  expect(auditTarget(logItem({ cat: "auth", data: { windows_user: "CORP\\kim" } }))).toBe(copy.audit.windowsUser("CORP\\kim"));
});

it("says when nothing matches", async () => {
  server.use(http.get("/api/audit", () => HttpResponse.json(logPage([]))));
  renderWithProviders(null, { me: ME, route: "/admin/audit" });
  expect(await screen.findByText(copy.audit.empty)).toBeInTheDocument();
});

it("counts actors from the audit categories of the tab", async () => {
  const tracker = trackRequests();
  const { router } = renderWithProviders(null, { me: ME, route: "/admin/audit?kind=%22all%22" });
  await userEvent.click(await screen.findByRole("button", { name: copy.audit.columns.actor }));
  await userEvent.click(await screen.findByRole("option", { name: /CORP\\hong/ }));
  await waitFor(() => expect(router.state.location.search).toMatchObject({ users: ["CORP\\hong"] }));
  const users = tracker.urls().map((u) => new URL(u, "http://x")).filter((u) => u.pathname === "/api/logs/users");
  expect(users[0]!.searchParams.getAll("cat").sort()).toEqual(["admin.audit", "auth"]);
  await waitFor(() => expect(auditParams(tracker).some((p) => p.getAll("users").includes("CORP\\hong"))).toBe(true));
});

it("exports the filter set with the audit export links", async () => {
  renderWithProviders(null, { me: ME, route: "/admin/audit?channel=%22local%22" });
  await userEvent.click(await screen.findByRole("button", { name: copy.logs.export.menu }));
  const csv = await screen.findByRole("menuitem", { name: copy.logs.export.csv });
  const href = new URL(csv.getAttribute("href")!);
  expect(href.pathname).toBe("/api/audit/export");
  expect(href.searchParams.get("format")).toBe("csv");
  expect(href.searchParams.get("kind")).toBe("admin");
  expect(href.searchParams.get("channel")).toBe("local");
  expect(csv.getAttribute("href")).toBe(auditExportUrl({ from: href.searchParams.get("from")!, to: href.searchParams.get("to")!, kind: "admin", channel: "local" }, "csv"));
});

it("opens a row in the detail dialog and nothing in the log area moves", async () => {
  server.use(http.get("/api/audit", () => HttpResponse.json(logPage([logItem({ cat: "admin.audit", event: "user_create", user: "a@x.com",
    data: { channel: "local", target: { email: "b@x.com" }, result: "ok" } })]))));
  renderWithProviders(null, { me: ME, route: "/admin/audit" });
  await userEvent.click(await screen.findByText("user_create"));
  const dialog = await screen.findByRole("dialog", { name: copy.logs.detail });
  expect(dialog).toHaveTextContent('"email": "b@x.com"');
  // the dialog hides the page from the accessibility tree: look it up directly
  expect(document.querySelector("main")!.querySelector("[data-anim]")).toBeNull();
});
