import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryHistory, createRootRoute, createRouter } from "@tanstack/react-router";
import { http, HttpResponse } from "msw";
import { MotionConfigContext } from "motion/react";
import { useContext } from "react";
import { AdminApp, type AdminRouter } from "@/admin/router";
import { copy, type DisabledReason } from "@/copy/ko";
import { BoardStore } from "@/lib/board-store";
import type { Me } from "@/lib/api-types";
import { loadDraft, saveDraft } from "@/lib/draft";
import { mcps } from "@/lib/endpoints";
import { session } from "@/lib/session";
import { mcpDetailFixture, meFixture } from "../../../tests/msw/fixtures";
import { server } from "../../../tests/msw/server";
import { createTestQueryClient, fakeStream, renderWithProviders } from "../../../tests/render";
import { NAV_ITEMS, navReason } from "./Nav";
import { PlannedFeature } from "./PlannedFeature";
import { warmChunks } from "../../../tests/warm";

warmChunks("dashboard", "mcpList", "mcpDetail", "chart", "login", "settings", "palette", "logs", "audit");

/** The admin app at `route` with `me` logged in; waits until the shell's navigation is there. */
async function renderShell(me: Me, route = "/admin") {
  const r = renderWithProviders(null, { route, me });
  // the first test of a run pays for compiling the shell and route chunks under the parallel suite
  await screen.findByRole("navigation", { name: copy.nav.label }, { timeout: 5000 });
  return r;
}

const navLink = (name: string) =>
  within(screen.getByRole("navigation", { name: copy.nav.label })).getByRole("link", { name });

it("shows planned and forbidden nav items disabled with reasons", async () => {
  await renderShell(meFixture("developer", "external"));
  const blocked: [string, DisabledReason][] = [
    [copy.nav.users, "local_only"],
    [copy.nav.notice, "local_only"],
    [copy.nav.settings, "local_only"],
  ];
  for (const [name, reason] of blocked) {
    const link = navLink(name);
    expect(link).toHaveAttribute("aria-disabled", "true");
    expect(link).toHaveAccessibleDescription(copy.deny[reason]);
    expect(link).not.toHaveAttribute("href");
  }
  expect(navLink(copy.nav.dashboard)).toHaveAttribute("href", "/admin");
  expect(navLink(copy.nav.mcps)).toHaveAttribute("href", "/admin/mcps");
  expect(navLink(copy.nav.mcps)).not.toHaveAttribute("aria-disabled");
});

it("opens the sessions nav item for developers on both channels and gates it for anonymous", async () => {
  const { unmount } = await renderShell(meFixture("developer", "external"));
  expect(navLink(copy.nav.sessions)).not.toHaveAttribute("aria-disabled");
  expect(navLink(copy.nav.sessions)).toHaveAttribute("href", "/admin/sessions");
  unmount();
  await renderShell(meFixture("developer", "local"));
  expect(navLink(copy.nav.sessions)).toHaveAttribute("href", "/admin/sessions");
  const sessions = NAV_ITEMS.find((i) => i.key === "sessions");
  if (!sessions) throw new Error("no sessions nav item");
  expect(navReason(meFixture(null, "external"), sessions)).toBe("login");
  expect(navReason(meFixture(null, "local"), sessions)).toBe("login");
  expect(sessions.planned).toBeNull();
});

it("opens the logs and audit nav for signed-in users on both channels", async () => {
  for (const channel of ["local", "external"] as const) {
    const { unmount } = await renderShell(meFixture("developer", channel));
    for (const name of [copy.nav.logs, copy.nav.audit])
      expect(screen.getByRole("link", { name })).not.toHaveAttribute("aria-disabled");
    expect(navLink(copy.nav.logs)).toHaveAttribute("href", "/admin/logs");
    expect(navLink(copy.nav.audit)).toHaveAttribute("href", "/admin/audit");
    unmount();
  }
  for (const key of ["logs", "audit"] as const) {
    const item = NAV_ITEMS.find((i) => i.key === key);
    if (!item) throw new Error(`no ${key} nav item`);
    expect(item.planned).toBeNull();
    expect(navReason(meFixture(null, "external"), item)).toBe("login");
  }
  // no screen is "planned" any more; the reasons stay for the copy deck (like planned_sessions)
  expect(NAV_ITEMS.filter((i) => i.planned !== null)).toEqual([]);
});

it("opens the logs and audit pages with a heading, from the nav and from the palette", async () => {
  const { router } = await renderShell(meFixture("developer", "external"));
  await userEvent.click(navLink(copy.nav.logs));
  await waitFor(() => expect(router.state.location.pathname).toBe("/admin/logs"));
  expect(await screen.findByRole("heading", { level: 1, name: copy.logs.title }, { timeout: 5000 })).toBeInTheDocument();
  expect(navLink(copy.nav.logs)).toHaveAttribute("aria-current", "page");
  await userEvent.click(screen.getByRole("button", { name: new RegExp(copy.common.commandTitle) }));
  const dialog = await screen.findByRole("dialog", { name: copy.common.commandTitle });
  const audit = within(dialog).getByRole("option", { name: new RegExp(copy.nav.audit) });
  expect(audit).not.toHaveAttribute("aria-disabled", "true");
  await userEvent.click(audit);
  await waitFor(() => expect(router.state.location.pathname).toBe("/admin/audit"));
  expect(await screen.findByRole("heading", { level: 1, name: copy.audit.title }, { timeout: 5000 })).toBeInTheDocument();
});

it("keeps valid log and audit filters in the URL and drops the rest", async () => {
  const route = '/admin/logs?range=%227d%22&cat=%5B%22auth%22%2C%22nope%22%5D&session=-1&q=notepad';
  const { router } = await renderShell(meFixture("developer", "local"), route);
  await screen.findByRole("heading", { level: 1, name: copy.logs.title }, { timeout: 5000 });
  expect(router.state.location.search).toEqual({ range: "7d", cat: ["auth"], q: "notepad" });
  expect(router.state.location.search).not.toHaveProperty("session", -1);
  await router.navigate({ to: "/admin/audit", search: { kind: "auth", result: ["fail"], channel: "external" } });
  await screen.findByRole("heading", { level: 1, name: copy.audit.title }, { timeout: 5000 });
  expect(router.state.location.search).toEqual({ kind: "auth", result: ["fail"], channel: "external" });
});

it("gives a local developer the admin-only reason and a local admin every link", async () => {
  const { unmount } = await renderShell(meFixture("developer", "local"));
  expect(navLink(copy.nav.users)).toHaveAccessibleDescription(copy.deny.admin_only);
  unmount();
  await renderShell(meFixture("admin", "local"));
  expect(navLink(copy.nav.users)).toHaveAttribute("href", "/admin/users");
  expect(navLink(copy.nav.notice)).toHaveAttribute("href", "/admin/notice");
  expect(navLink(copy.nav.settings)).toHaveAttribute("href", "/admin/settings");
  expect(navLink(copy.nav.sessions)).toHaveAttribute("href", "/admin/sessions");
});

it("does not navigate from a disabled item", async () => {
  const { router } = await renderShell(meFixture("developer", "external"), "/admin/mcps");
  await userEvent.click(navLink(copy.nav.users));
  navLink(copy.nav.users).focus();
  await userEvent.keyboard("{Enter}");
  expect(router.state.location.pathname).toBe("/admin/mcps");
});

it("marks the current page and moves between pages", async () => {
  const { router } = await renderShell(meFixture("admin", "local"));
  expect(navLink(copy.nav.dashboard)).toHaveAttribute("aria-current", "page");
  await userEvent.click(navLink(copy.nav.mcps));
  await waitFor(() => expect(router.state.location.pathname).toBe("/admin/mcps"));
  expect(await screen.findByRole("heading", { level: 1, name: copy.mcp.title })).toBeInTheDocument();
  expect(navLink(copy.nav.mcps)).toHaveAttribute("aria-current", "page");
  expect(navLink(copy.nav.dashboard)).not.toHaveAttribute("aria-current");
});

it("shows the channel badge and role", async () => {
  await renderShell(meFixture("admin", "local"));
  expect(screen.getByText("로컬 관리 모드")).toBeInTheDocument();
  expect(screen.getByText("Admin")).toBeInTheDocument();
});

it("shows the remote channel and the developer role", async () => {
  await renderShell(meFixture("developer", "external"));
  expect(screen.getByText("원격 모드")).toBeInTheDocument();
  expect(screen.getByText("MCP 개발자")).toBeInTheDocument();
});

it("redirects to login with the current path on a 401", async () => {
  server.use(http.get("/api/mcps", () => HttpResponse.json({ error: "login_required" }, { status: 401 })));
  const { router, stream } = await renderShell(meFixture("admin", "local"), "/admin/mcps");
  await act(async () => {
    await mcps().catch(() => {}); // any page query
  });
  await waitFor(() => expect(router.state.location.href).toBe("/admin/login?redirect=%2Fadmin%2Fmcps"));
  expect(stream.restart).toHaveBeenCalledTimes(1);
  expect(session.me?.user).toBeNull();
  expect(await screen.findByLabelText(copy.login.email)).toBeInTheDocument();
  expect(screen.getByText(copy.errors.login_required)).toBeInTheDocument(); // why the user is here
});

it("goes to login on a 401 even while a page blocks navigation (F12)", async () => {
  server.use(http.get("/api/mcps", () => HttpResponse.json({ error: "login_required" }, { status: 401 })));
  const { router } = await renderShell(meFixture("admin", "local"), "/admin/settings");
  const unblock = router.history.block({ blockerFn: () => true }); // an editor with unsaved changes
  try {
    await act(async () => {
      await mcps().catch(() => {});
    });
    await waitFor(() => expect(router.state.location.href).toBe("/admin/login?redirect=%2Fadmin%2Fsettings"));
  } finally {
    unblock();
  }
});

it("sends an anonymous visitor to login with the requested page", async () => {
  const { router } = renderWithProviders(null, { route: "/admin/mcps/3?tab=history", me: meFixture(null, "external") });
  expect(await screen.findByLabelText(copy.login.email)).toBeInTheDocument();
  expect(router.state.location.pathname).toBe("/admin/login");
  expect(router.state.location.search).toEqual({ redirect: "/admin/mcps/3?tab=history" });
});

it("logs out to the login page and restarts the stream", async () => {
  const { router, stream } = await renderShell(meFixture("admin", "local"));
  await userEvent.click(screen.getByRole("button", { name: copy.common.accountMenu("user1") }));
  await userEvent.click(await screen.findByRole("menuitem", { name: copy.common.logout }));
  await waitFor(() => expect(router.state.location.pathname).toBe("/admin/login"));
  expect(stream.restart).toHaveBeenCalledTimes(1);
  expect(session.me?.user).toBeNull();
});

it("logging out drops this tab's unsaved drafts (a 401 keeps them: scripts.test)", async () => {
  saveDraft("script:1:start", { ext: ".ps1", content: "x", baseVersion: 1 }, 1);
  saveDraft("mcp-create", { name: "files" }, 1);
  const { router } = await renderShell(meFixture("admin", "local"));
  await userEvent.click(screen.getByRole("button", { name: copy.common.accountMenu("user1") }));
  await userEvent.click(await screen.findByRole("menuitem", { name: copy.common.logout }));
  await waitFor(() => expect(router.state.location.pathname).toBe("/admin/login"));
  expect(loadDraft("script:1:start", 1)).toBeNull();
  expect(loadDraft("mcp-create", 1)).toBeNull();
});

it("logging out from a page with unsaved edits still reaches the login page", async () => {
  const { router, qc } = renderWithProviders(null, { route: "/admin/settings", me: meFixture("admin", "local") });
  const field = await screen.findByLabelText(copy.settings.fields.confirm_interval_sec, {}, { timeout: 5000 });
  await userEvent.clear(field);
  await userEvent.type(field, "3"); // dirty: the page's leave guard is armed
  const clear = vi.spyOn(qc, "clear");
  await userEvent.click(screen.getByRole("button", { name: copy.common.accountMenu("user1") }));
  await userEvent.click(await screen.findByRole("menuitem", { name: copy.common.logout }));
  await waitFor(() => expect(router.state.location.pathname).toBe("/admin/login"));
  expect(await screen.findByLabelText(copy.login.email)).toBeInTheDocument(); // not a blank page
  expect(screen.queryByRole("alertdialog")).toBeNull(); // logging out is the deliberate discard
  expect(clear).toHaveBeenCalled();
});

it("opens the command palette with Ctrl+K and navigates to an MCP", async () => {
  server.use(http.get("/api/mcps", () => HttpResponse.json([mcpDetailFixture({ id: 1, name: "calc" }), mcpDetailFixture({ id: 2, name: "weather" })])));
  const { router } = await renderShell(meFixture("admin", "local"));
  await userEvent.keyboard("{Control>}k{/Control}");
  const dialog = await screen.findByRole("dialog", { name: copy.common.commandTitle });
  await userEvent.click(await within(dialog).findByRole("option", { name: /calc/ }));
  await waitFor(() => expect(router.state.location.pathname).toBe("/admin/mcps/1"));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
});

it("closing a shortcut-opened palette puts focus on the page content, not <body>", async () => {
  await renderShell(meFixture("admin", "local"));
  (document.activeElement as HTMLElement | null)?.blur();
  expect(document.activeElement).toBe(document.body);
  await userEvent.keyboard("{Control>}k{/Control}");
  await screen.findByRole("dialog", { name: copy.common.commandTitle });
  await userEvent.keyboard("{Escape}");
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("main")));
});

it("closing a palette opened from the quick-jump button gives focus back to the button", async () => {
  await renderShell(meFixture("admin", "local"));
  const opener = screen.getByRole("button", { name: new RegExp(copy.common.commandTitle) });
  await userEvent.click(opener);
  await screen.findByRole("dialog", { name: copy.common.commandTitle });
  await userEvent.keyboard("{Escape}");
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  await waitFor(() => expect(opener).toHaveFocus()); // Radix restores focus on the next tick
});

it("lists blocked screens in the palette as disabled with the reason", async () => {
  const { router } = await renderShell(meFixture("developer", "external"));
  await userEvent.click(screen.getByRole("button", { name: new RegExp(copy.common.commandTitle) }));
  const dialog = await screen.findByRole("dialog", { name: copy.common.commandTitle });
  const users = within(dialog).getByRole("option", { name: new RegExp(copy.nav.users) });
  expect(users).toHaveAttribute("aria-disabled", "true");
  expect(users).toHaveTextContent(copy.deny.local_only);
  await userEvent.click(users);
  expect(router.state.location.pathname).toBe("/admin");
  await userEvent.click(within(dialog).getByRole("option", { name: new RegExp(copy.nav.mcps) }));
  await waitFor(() => expect(router.state.location.pathname).toBe("/admin/mcps"));
});

it("collapses to an icon rail in a narrow window, labels kept as names and shown as tooltips", async () => {
  const original = window.matchMedia;
  window.matchMedia = ((query: string) => ({ ...original(query), matches: query === "(width < 64rem)" })) as typeof window.matchMedia;
  try {
    await renderShell(meFixture("developer", "local"));
    const nav = screen.getByRole("navigation", { name: copy.nav.label });
    expect(nav).toHaveAttribute("data-rail");
    navLink(copy.nav.mcps).focus();
    expect(await screen.findByRole("tooltip")).toHaveTextContent(copy.nav.mcps);
    navLink(copy.nav.users).focus(); // blocked: the tooltip names the item, then the reason
    await waitFor(() => expect(screen.getByRole("tooltip")).toHaveTextContent(`${copy.nav.users}${copy.deny.admin_only}`));
    const description = navLink(copy.nav.users).getAttribute("aria-describedby") ?? "";
    expect(description).not.toBe("");
    expect(navLink(copy.nav.users)).toHaveAccessibleDescription(expect.stringContaining(copy.deny.admin_only));
    expect(navLink(copy.nav.users)).not.toHaveAccessibleDescription(expect.stringContaining(copy.nav.users));
  } finally {
    window.matchMedia = original;
  }
});

it("keeps the full sidebar without tooltips on a wide window", async () => {
  await renderShell(meFixture("admin", "local"));
  expect(screen.getByRole("navigation", { name: copy.nav.label })).not.toHaveAttribute("data-rail");
  navLink(copy.nav.mcps).focus();
  await new Promise((r) => setTimeout(r, 50));
  expect(screen.queryByRole("tooltip")).toBeNull();
});

it("follows the user's reduced-motion setting for Motion on every admin page", () => {
  let seen: string | undefined;
  function Probe() {
    seen = useContext(MotionConfigContext).reducedMotion;
    return null;
  }
  const root = createRootRoute({ component: Probe });
  const router = createRouter({ routeTree: root, history: createMemoryHistory({ initialEntries: ["/"] }) });
  render(<AdminApp router={router as unknown as AdminRouter} qc={createTestQueryClient()} live={{ store: new BoardStore(), stream: fakeStream(), tracker: null }} />);
  return waitFor(() => expect(seen).toBe("user"));
});

it("shows a planned feature as an empty state without data", () => {
  render(<PlannedFeature reason="planned_logs" />);
  const card = screen.getByText(copy.deny.planned_logs).closest("[data-planned]");
  expect(card).not.toBeNull();
  expect(card).toHaveAttribute("data-planned", "planned_logs");
  expect(card?.querySelector("svg[aria-hidden=true]")).not.toBeNull();
  expect(card?.querySelector("canvas, table, [role=img], [data-testid=card-skeleton]")).toBeNull();
});

it("shows a not-found page for unknown admin paths inside the shell, with a heading", async () => {
  await renderShell(meFixture("admin", "local"), "/admin/nowhere/deeper");
  const main = screen.getByRole("main");
  expect(await within(main).findByRole("heading", { level: 1, name: copy.common.notFoundTitle })).toBeInTheDocument();
  expect(within(main).getByText(copy.common.notFound)).toBeInTheDocument();
  expect(within(main).getByRole("link", { name: copy.common.adminHome })).toHaveAttribute("href", "/admin");
  // the navigation stays, so the way back is not only the one link
  expect(navLink(copy.nav.mcps)).toHaveAttribute("href", "/admin/mcps");
});

it("sends an anonymous visitor of an unknown admin path to login first", async () => {
  const { router } = renderWithProviders(null, { route: "/admin/nowhere", me: meFixture(null, "local") });
  await waitFor(() => expect(router.state.location.pathname).toBe("/admin/login"));
  expect(router.state.location.search).toMatchObject({ redirect: "/admin/nowhere" });
});
