import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { copy } from "@/copy/ko";
import { session } from "@/lib/session";
import { histogramFixture, logItem, logPage, logStatusFixture, meFixture } from "../../../tests/msw/fixtures";
import { server, trackRequests } from "../../../tests/msw/server";
import { renderWithProviders } from "../../../tests/render";
import { warmChunks } from "../../../tests/warm";
import { ExportMenu } from "./ExportMenu";

warmChunks("logs");

const ME = meFixture("developer", "external");
beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({ left: 0, top: 0, width: 1200, height: 800, right: 1200, bottom: 800, x: 0, y: 0, toJSON: () => ({}) } as DOMRect);
});

it("loads the first page and renders summarized rows", async () => {
  server.use(http.get("/api/logs", () => HttpResponse.json(logPage([logItem({ id: 2, cat: "activity.command", data: { text: "Get-Process" } })]))));
  renderWithProviders(null, { me: ME, route: "/admin/logs?range=1h" });
  expect(await screen.findByText("Get-Process")).toBeInTheDocument();
  expect(screen.getByRole("table", { name: copy.logs.title })).toBeInTheDocument();
});
it("writes the selection to the URL and drops the quick range", async () => {
  const { router } = renderWithProviders(null, { me: ME, route: "/admin/logs?range=1h" });
  const svg = await screen.findByTestId("log-histogram"); svg.focus();
  await userEvent.keyboard("{ArrowRight}{Enter}");
  await waitFor(() => expect(router.state.location.search).toMatchObject({ from: "2026-11-04T13:10:00.000+09:00", to: "2026-11-04T13:20:00.000+09:00" }));
  expect(router.state.location.search).not.toHaveProperty("range");
});
it("toggles a category chip into the URL and the request", async () => {
  const tracker = trackRequests();
  const { router } = renderWithProviders(null, { me: ME, route: "/admin/logs" });
  await userEvent.click(await screen.findByRole("button", { name: copy.logs.cats.auth }));
  await waitFor(() => expect(router.state.location.search).toMatchObject({ cat: ["auth"] }));
  await waitFor(() => expect(tracker.urls().some((u) => new URL(u, "http://x").searchParams.getAll("cat").includes("auth"))).toBe(true));
});
it("shows user counts and filters by a picked user", async () => {
  server.use(http.get("/api/logs/users", () => HttpResponse.json([{ user: "CORP\\hong", count: 12 }, { user: "a@x.com", count: 3 }])));
  const { router } = renderWithProviders(null, { me: ME, route: "/admin/logs" });
  await userEvent.click(await screen.findByRole("button", { name: copy.logs.users }));
  await userEvent.click(await screen.findByRole("option", { name: /CORP\\hong.*12/ }));
  await waitFor(() => expect(router.state.location.search).toMatchObject({ users: ["CORP\\hong"] }));
});
it("debounces the keyword into q", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const { router } = renderWithProviders(null, { me: ME, route: "/admin/logs" });
  await userEvent.type(await screen.findByLabelText(copy.logs.keyword), "notepad");
  expect(router.state.location.search).not.toHaveProperty("q");
  await vi.advanceTimersByTimeAsync(300);
  await waitFor(() => expect(router.state.location.search).toMatchObject({ q: "notepad" }));
  vi.useRealTimers();
});
it("loads the next page near the end of the table", async () => {
  const first = Array.from({ length: 30 }, (_, i) => logItem({ id: 100 - i }));
  let calls = 0;
  server.use(http.get("/api/logs", ({ request }) => { calls++; return HttpResponse.json(new URL(request.url).searchParams.get("cursor") ? logPage([logItem({ id: 1 })]) : logPage(first, "c1")); }));
  renderWithProviders(null, { me: ME, route: "/admin/logs" });
  await screen.findAllByRole("row");
  await waitFor(() => expect(calls).toBe(2));
});
it("opens the detail dialog with the raw JSON", async () => {
  server.use(http.get("/api/logs", () => HttpResponse.json(logPage([logItem({ id: 7, data: { text: "secret-cmd" } })]))));
  renderWithProviders(null, { me: ME, route: "/admin/logs" });
  (await screen.findByText("secret-cmd")).closest("tr")!.focus(); await userEvent.keyboard("{Enter}");
  expect(await screen.findByRole("dialog", { name: copy.logs.detail })).toHaveTextContent('"text": "secret-cmd"');
});
it("timeline lanes link to a filtered table", async () => {
  server.use(http.get("/api/logs/histogram", ({ request }) => HttpResponse.json(new URL(request.url).searchParams.get("group") === "user"
    ? histogramFixture({ series: [{ key: "CORP\\hong", counts: [0, 5, 0, 0, 0, 0] }] }) : histogramFixture())));
  const { router } = renderWithProviders(null, { me: ME, route: "/admin/logs?view=timeline" });
  const lane = await screen.findByRole("group", { name: /CORP\\hong/ }); lane.focus();
  await userEvent.keyboard("{ArrowRight}{Enter}");
  await waitFor(() => expect(router.state.location.search).toMatchObject({ users: ["CORP\\hong"], view: "table",
    from: "2026-11-04T13:10:00.000+09:00", to: "2026-11-04T13:20:00.000+09:00" }));
});
it("export links carry the current filters", async () => {
  renderWithProviders(null, { me: ME, route: `/admin/logs?cat=${encodeURIComponent(JSON.stringify(["auth"]))}` });
  await userEvent.click(await screen.findByRole("button", { name: copy.logs.export.menu }));
  const href = (await screen.findByRole("menuitem", { name: copy.logs.export.csv })).closest("a")!.getAttribute("href")!;
  const u = new URL(href, "http://x"); expect(u.pathname).toBe("/api/logs/export"); expect(u.searchParams.getAll("cat")).toEqual(["auth"]);
});
it("shows the indexing banner until the index is ready", async () => {
  server.use(http.get("/api/logs/status", () => HttpResponse.json(logStatusFixture({ ready: false, pending_files: 3 }))));
  renderWithProviders(null, { me: ME, route: "/admin/logs" });
  expect(await screen.findByText(copy.logs.indexing(3))).toBeInTheDocument();
});
it("explains what is never collected", async () => {
  renderWithProviders(null, { me: ME, route: "/admin/logs" });
  await userEvent.click(await screen.findByRole("button", { name: copy.common.help }));
  expect(await screen.findByText(copy.logs.cmdLimitHelp)).toBeInTheDocument();
  expect(document.querySelector("main [data-anim]")).toBeNull();
});

// ---- beyond the plan ------------------------------------------------------------------

it("filter changes do not start a view transition (F16: no animation in the log area)", async () => {
  const { router } = renderWithProviders(null, { me: ME, route: "/admin/logs" });
  const chip = await screen.findByRole("button", { name: copy.logs.cats.tamper });
  const start = vi.fn((cb: () => void) => {
    cb();
    const done = Promise.resolve();
    return { updateCallbackDone: done, finished: done, ready: done, skipTransition: () => {} };
  });
  Object.defineProperty(document, "startViewTransition", { value: start, configurable: true });
  try {
    await userEvent.click(chip);
    await waitFor(() => expect(router.state.location.search).toMatchObject({ cat: ["tamper"] }));
    await userEvent.click(screen.getByRole("button", { name: copy.logs.quick.today }));
    await waitFor(() => expect(router.state.location.search).toMatchObject({ range: "today" }));
    expect(start).not.toHaveBeenCalled();
  } finally {
    Reflect.deleteProperty(document, "startViewTransition");
  }
});

it("asks the histogram for 60 bars by category on a wide page", async () => {
  const tracker = trackRequests();
  renderWithProviders(null, { me: ME, route: "/admin/logs" });
  await screen.findByTestId("log-histogram");
  const hist = tracker.urls().map((u) => new URL(u, "http://x")).filter((u) => u.pathname === "/api/logs/histogram");
  expect(hist.some((u) => u.searchParams.get("buckets") === "60" && u.searchParams.get("group") === "cat")).toBe(true);
  for (const u of hist) {
    expect(Number(u.searchParams.get("buckets"))).toBeGreaterThanOrEqual(10);
    expect(u.searchParams.get("from")).toMatch(/:00\.000\+09:00$/); // minute-aligned KST
  }
});

it("applies a custom range in minutes and drops the quick range", async () => {
  const { router } = renderWithProviders(null, { me: ME, route: "/admin/logs?range=today" });
  const from = await screen.findByLabelText(copy.logs.from);
  const to = screen.getByLabelText(copy.logs.to);
  await userEvent.clear(from); await userEvent.type(from, "2026-11-03T09:15");
  await userEvent.clear(to); await userEvent.type(to, "2026-11-03T10:45");
  await userEvent.click(screen.getByRole("button", { name: copy.logs.apply }));
  await waitFor(() => expect(router.state.location.search).toMatchObject({ from: "2026-11-03T09:15:00.000+09:00", to: "2026-11-03T10:45:00.000+09:00" }));
  expect(router.state.location.search).not.toHaveProperty("range");
});

it("blocks an inverted custom range", async () => {
  const { router } = renderWithProviders(null, { me: ME, route: "/admin/logs?range=today" });
  const from = await screen.findByLabelText(copy.logs.from);
  const to = screen.getByLabelText(copy.logs.to);
  await userEvent.clear(from); await userEvent.type(from, "2026-11-03T12:00");
  await userEvent.clear(to); await userEvent.type(to, "2026-11-03T11:00");
  await userEvent.click(screen.getByRole("button", { name: copy.logs.apply }));
  expect(await screen.findByRole("alert")).toHaveTextContent(copy.logs.invertedRange);
  expect(router.state.location.search).toMatchObject({ range: "today" });
  expect(router.state.location.search).not.toHaveProperty("from");
});

it("a quick range replaces custom bounds", async () => {
  const { router } = renderWithProviders(null, {
    me: ME, route: `/admin/logs?from=${encodeURIComponent("2026-11-03T09:00:00.000+09:00")}&to=${encodeURIComponent("2026-11-03T10:00:00.000+09:00")}`,
  });
  const yesterday = await screen.findByRole("button", { name: copy.logs.quick.yesterday });
  expect(yesterday).toHaveAttribute("aria-pressed", "false");
  await userEvent.click(yesterday);
  await waitFor(() => expect(router.state.location.search).toMatchObject({ range: "yesterday" }));
  expect(router.state.location.search).not.toHaveProperty("from");
  expect(screen.getByRole("button", { name: copy.logs.quick.yesterday })).toHaveAttribute("aria-pressed", "true");
});

it("filters by the user or the session of an opened line, and closes the dialog", async () => {
  server.use(http.get("/api/logs", () => HttpResponse.json(logPage([logItem({ id: 7, user: "CORP\\kim", session_id: 4, data: { text: "x1" } })]))));
  const { router } = renderWithProviders(null, { me: ME, route: "/admin/logs" });
  await userEvent.click(await screen.findByText("x1"));
  const dialog = await screen.findByRole("dialog", { name: copy.logs.detail });
  await userEvent.click(within(dialog).getByRole("button", { name: copy.logs.byUser }));
  await waitFor(() => expect(router.state.location.search).toMatchObject({ users: ["CORP\\kim"] }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  await userEvent.click(await screen.findByText("x1"));
  await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: copy.logs.bySession }));
  await waitFor(() => expect(router.state.location.search).toMatchObject({ session: 4 }));
});

it("shows extra URL conditions as removable chips and clears every filter", async () => {
  const route = `/admin/logs?range=today&event=${encodeURIComponent(JSON.stringify(["logon_failed"]))}&cat=${encodeURIComponent(JSON.stringify(["auth"]))}`;
  const { router } = renderWithProviders(null, { me: ME, route });
  const more = await screen.findByRole("group", { name: copy.logs.moreConditions });
  await userEvent.click(within(more).getByRole("button", { name: copy.logs.removeCondition(`${copy.logs.columns.event}: logon_failed`) }));
  await waitFor(() => expect(router.state.location.search).not.toHaveProperty("event"));
  expect(screen.queryByRole("group", { name: copy.logs.moreConditions })).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: copy.logs.clear }));
  await waitFor(() => expect(router.state.location.search).not.toHaveProperty("cat"));
  expect(router.state.location.search).toMatchObject({ range: "today" }); // the time range is not a filter
});

it("counts the picked users on the button", async () => {
  renderWithProviders(null, { me: ME, route: `/admin/logs?users=${encodeURIComponent(JSON.stringify(["a", "b"]))}` });
  expect(await screen.findByRole("button", { name: `${copy.logs.users} ${copy.logs.usersCount(2)}` })).toBeInTheDocument();
});

it("says so when nothing matches", async () => {
  server.use(http.get("/api/logs", () => HttpResponse.json(logPage([]))));
  renderWithProviders(null, { me: ME, route: "/admin/logs" });
  expect(await screen.findByText(copy.logs.empty)).toBeInTheDocument();
});

it("export stays visible with a reason when it is not allowed", async () => {
  session.me = null;
  render(<ExportMenu query={{ from: "2026-11-04T13:00:00.000+09:00", to: "2026-11-04T14:00:00.000+09:00" }} />);
  const button = screen.getByRole("button", { name: copy.logs.export.menu });
  expect(button).toHaveAttribute("aria-disabled", "true");
  expect(button).toHaveAccessibleDescription(copy.deny.login);
  await userEvent.click(button);
  expect(screen.queryByRole("menu")).toBeNull();
});

it("closing the detail dialog returns focus to the row that opened it", async () => {
  server.use(http.get("/api/logs", () => HttpResponse.json(logPage([logItem({ id: 1, data: { text: "one" } }), logItem({ id: 2, data: { text: "two" } })]))));
  renderWithProviders(null, { me: ME, route: "/admin/logs" });
  const row = (await screen.findByText("two")).closest("tr")!;
  row.focus(); await userEvent.keyboard("{Enter}");
  await screen.findByRole("dialog", { name: copy.logs.detail });
  await userEvent.keyboard("{Escape}");
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  await waitFor(() => expect(document.activeElement).toBe(screen.getByText("two").closest("tr")));
});

it("shades timeline cells against real users and keeps the other-users lane out of the keyboard path", async () => {
  server.use(http.get("/api/logs/histogram", ({ request }) => HttpResponse.json(new URL(request.url).searchParams.get("group") === "user"
    ? histogramFixture({ series: [{ key: "CORP\\hong", counts: [0, 5, 0, 0, 0, 0] }, { key: "__other__", counts: [90, 90, 0, 0, 0, 0] }, { key: null, counts: [1, 0, 0, 0, 0, 0] }] })
    : histogramFixture())));
  renderWithProviders(null, { me: ME, route: "/admin/logs?view=timeline" });
  const hong = await screen.findByRole("group", { name: /CORP\\hong/ });
  // the busiest person sets the scale (100%), not the "other users" sum (jsdom keeps color-mix only as a custom style)
  const shade = (el: Element | null) => /var\(--color-accent\) (\d+)%/.exec(el?.getAttribute("data-shade") ?? "")?.[1];
  expect(shade(hong.querySelector("[data-cell='1']"))).toBe("100");
  const other = screen.getByRole("group", { name: new RegExp(copy.logs.otherUsers) });
  const none = screen.getByRole("group", { name: new RegExp(copy.logs.noUser) });
  expect(hong).toHaveAttribute("tabindex", "0");
  expect(other).not.toHaveAttribute("tabindex");
  expect(none).not.toHaveAttribute("tabindex");
});

it("says why a session number is not applied", async () => {
  const { router } = renderWithProviders(null, { me: ME, route: "/admin/logs" });
  const field = await screen.findByLabelText(copy.logs.session);
  await userEvent.type(field, "4a");
  expect(field).toHaveAttribute("aria-invalid", "true");
  expect(field).toHaveAccessibleDescription(copy.logs.sessionInvalid);
  expect(screen.getByText(copy.logs.sessionInvalid)).toBeVisible();
  await new Promise((r) => setTimeout(r, 350));
  expect(router.state.location.search).not.toHaveProperty("session");
  await userEvent.clear(field); await userEvent.type(field, "4");
  await waitFor(() => expect(router.state.location.search).toMatchObject({ session: 4 }));
});
