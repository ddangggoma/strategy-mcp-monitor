import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import type { ComponentType } from "react";
import { copy } from "@/copy/ko";
import type { Me, RetentionPreview, Settings } from "@/lib/api-types";
import { formatBytes } from "@/lib/time";
import { meFixture, previewFixture, serviceStatusFixture, settingsFixture } from "../../../tests/msw/fixtures";
import { server, trackRequests } from "../../../tests/msw/server";
import { renderWithProviders } from "../../../tests/render";
import { UsersPage } from "../users/UsersPage";
import { SettingsPage } from "./SettingsPage";
import { settingsSchema } from "./settings-schema";
import { warmChunks } from "../../../tests/warm";

warmChunks("settings", "users", "dashboard");

/** Method + path (+ query) of every request from now on. */
function trackCalls(): () => string[] {
  const seen: string[] = [];
  server.events.on("request:start", ({ request }) => {
    const url = new URL(request.url);
    seen.push(`${request.method} ${url.pathname}${url.search}`);
  });
  return () => [...seen];
}

/**
 * The settings page in the full admin app. GET /api/settings answers `settings`; the retention
 * preview answers `preview` for its own `days` and the default fixture for any other value.
 */
async function renderSettings(settings: Settings, preview?: RetentionPreview, me: Me = meFixture("admin", "local")) {
  server.use(
    http.get("/api/settings", () => HttpResponse.json(settings)),
    http.get("/api/settings/retention/preview", ({ request }) => {
      const days = Number(new URL(request.url).searchParams.get("days"));
      return HttpResponse.json(preview && preview.days === days ? preview : previewFixture({ days }));
    }),
  );
  const r = renderWithProviders(null, { route: "/admin/settings", me });
  // the first test of a run pays for compiling the lazy route chunk under load
  await screen.findByLabelText(copy.settings.fields.log_retention_days, {}, { timeout: 5000 });
  return r;
}

async function setNumber(label: string, value: number) {
  const input = screen.getByLabelText(label);
  await userEvent.clear(input);
  await userEvent.type(input, String(value));
}

const saveButton = () => screen.getByRole("button", { name: copy.common.save });

/** Records each PUT /api/settings body; the reply is the fixture merged with the body. */
function capturePuts(base: Settings): unknown[] {
  const bodies: unknown[] = [];
  server.use(
    http.put("/api/settings", async ({ request }) => {
      const body = (await request.json()) as Partial<Settings>;
      bodies.push(body);
      return HttpResponse.json({ ...base, ...body });
    }),
  );
  return bodies;
}

// ---- schema ------------------------------------------------------------------------------

it("schema follows the server ranges and the compress ≤ retention rule on both paths", () => {
  const values: Partial<Settings> = settingsFixture();
  delete values.otp_provider;
  expect(settingsSchema.safeParse(values).success).toBe(true);
  for (const [key, bad] of [
    ["ping_interval_sec", 0], ["ping_interval_sec", 301], ["issue_check_interval_sec", 4], ["issue_check_interval_sec", 61],
    ["confirm_interval_sec", 0], ["confirm_interval_sec", 11], ["log_retention_days", 6], ["log_retention_days", 3651],
    ["log_compress_after_days", 0], ["ping_interval_sec", ""], ["ping_interval_sec", "2.5"],
  ] as const) {
    expect(settingsSchema.safeParse({ ...values, [key]: bad }).success, `${key}=${bad}`).toBe(false);
  }
  expect(settingsSchema.safeParse({ ...values, service_start_type: "boot" }).success).toBe(false);
  expect(settingsSchema.safeParse({ ...values, log_retention_days: 3650, log_compress_after_days: 3650 }).success).toBe(true);

  const r = settingsSchema.safeParse({ ...values, log_retention_days: 20, log_compress_after_days: 30 });
  expect(r.success).toBe(false);
  const paths = r.error?.issues.filter((i) => i.message === copy.settings.retentionBelowCompress).map((i) => i.path.join("."));
  expect(paths?.sort()).toEqual(["log_compress_after_days", "log_retention_days"]);
});

// ---- page --------------------------------------------------------------------------------

it("explains that both retention values must be lowered together", async () => {
  const calls = trackCalls();
  await renderSettings(settingsFixture({ log_retention_days: 180, log_compress_after_days: 30 }));
  await setNumber(copy.settings.fields.log_retention_days, 20);
  await userEvent.click(screen.getByRole("button", { name: copy.common.save }));
  expect(await screen.findByText(copy.settings.retentionBelowCompress)).toBeInTheDocument();
  for (const label of [copy.settings.fields.log_retention_days, copy.settings.fields.log_compress_after_days]) {
    expect(screen.getByLabelText(label)).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText(label)).toHaveAccessibleDescription(expect.stringContaining(copy.settings.retentionBelowCompress));
  }
  expect(calls().filter((c) => c.startsWith("PUT") || c.includes("days=20"))).toEqual([]);

  // lowering both fixes it
  await setNumber(copy.settings.fields.log_compress_after_days, 10);
  await userEvent.click(saveButton());
  await waitFor(() => expect(screen.queryByText(copy.settings.retentionBelowCompress)).not.toBeInTheDocument());
  expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
});

it("reducing retention opens a preview confirm before saving", async () => {
  let put = 0;
  let body: unknown;
  server.use(http.put("/api/settings", async ({ request }) => {
    put++;
    body = await request.json();
    return HttpResponse.json(settingsFixture({ log_retention_days: 90 }));
  }));
  await renderSettings(settingsFixture({ log_retention_days: 180 }), previewFixture({ days: 90, delete_files: 3, delete_bytes: 3_000_000, delete_from: "2026-05-09", delete_to: "2026-08-05" }));
  await setNumber(copy.settings.fields.log_retention_days, 90); await userEvent.click(screen.getByRole("button", { name: copy.common.save }));
  const dialog = await screen.findByRole("alertdialog");
  expect(dialog).toHaveTextContent("2026-05-09");
  expect(dialog).toHaveTextContent("2026-08-05");
  expect(dialog).toHaveTextContent(copy.settings.filesCount(3));
  expect(dialog).toHaveTextContent(formatBytes(3_000_000));
  expect(dialog).toHaveTextContent(copy.settings.confirmBody(180, 90));
  expect(put).toBe(0);
  await userEvent.click(screen.getByRole("button", { name: copy.settings.confirmDelete })); await waitFor(() => expect(put).toBe(1));
  expect(body).toEqual({ log_retention_days: 90, log_compress_after_days: 30 });
  expect(await screen.findByText(copy.common.saved)).toBeInTheDocument();
  await waitFor(() => expect(saveButton()).toHaveAttribute("aria-disabled", "true"));
});

it("cancelling the preview confirm sends nothing and keeps the edit", async () => {
  const calls = trackCalls();
  await renderSettings(settingsFixture({ log_retention_days: 180 }));
  await setNumber(copy.settings.fields.log_retention_days, 120);
  await userEvent.click(saveButton());
  const dialog = await screen.findByRole("alertdialog");
  await userEvent.click(within(dialog).getByRole("button", { name: copy.common.cancel }));
  await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
  expect(calls()).toContain("GET /api/settings/retention/preview?days=120");
  expect(calls().filter((c) => c.startsWith("PUT"))).toEqual([]);
  expect(screen.getByLabelText(copy.settings.fields.log_retention_days)).toHaveValue(120);
  expect(saveButton()).toHaveFocus();
});

it("says when reducing deletes nothing", async () => {
  const puts = capturePuts(settingsFixture());
  await renderSettings(settingsFixture({ log_retention_days: 180 }), previewFixture({ days: 150, delete_files: 0, delete_bytes: 0, delete_from: null, delete_to: null }));
  await setNumber(copy.settings.fields.log_retention_days, 150);
  await userEvent.click(saveButton());
  const dialog = await screen.findByRole("alertdialog");
  expect(dialog).toHaveTextContent(copy.settings.noDelete);
  expect(within(dialog).queryByRole("button", { name: copy.settings.confirmDelete })).not.toBeInTheDocument();
  await userEvent.click(within(dialog).getByRole("button", { name: copy.settings.confirmReduce }));
  await waitFor(() => expect(puts).toEqual([{ log_retention_days: 150, log_compress_after_days: 30 }]));
});

it("a failed preview saves nothing and says so", async () => {
  const puts = capturePuts(settingsFixture());
  await renderSettings(settingsFixture({ log_retention_days: 180 }));
  server.use(http.get("/api/settings/retention/preview", () => HttpResponse.json({ error: "internal" }, { status: 500 })));
  await setNumber(copy.settings.fields.log_retention_days, 100);
  await userEvent.click(saveButton());
  expect(await screen.findByText(copy.settings.previewError)).toHaveAttribute("role", "alert");
  expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  expect(puts).toEqual([]);
});

it("increasing retention saves without a confirm", async () => {
  const puts = capturePuts(settingsFixture());
  await renderSettings(settingsFixture({ log_retention_days: 180 }));
  await setNumber(copy.settings.fields.log_retention_days, 365);
  await userEvent.click(saveButton());
  await waitFor(() => expect(puts).toHaveLength(1));
  expect(puts[0]).toEqual({ log_retention_days: 365, log_compress_after_days: 30 });
  expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  expect(await screen.findByText(copy.common.saved)).toBeInTheDocument();
});

it("sends both retention values when either changes, and only the changed field otherwise", async () => {
  const puts = capturePuts(settingsFixture());
  await renderSettings(settingsFixture({ log_retention_days: 180, log_compress_after_days: 30 }));
  await setNumber(copy.settings.fields.log_compress_after_days, 20);
  await userEvent.click(saveButton());
  await waitFor(() => expect(puts).toEqual([{ log_compress_after_days: 20, log_retention_days: 180 }]));
  await waitFor(() => expect(saveButton()).toHaveAttribute("aria-disabled", "true"));

  await setNumber(copy.settings.fields.ping_interval_sec, 7);
  await userEvent.click(saveButton());
  await waitFor(() => expect(puts).toHaveLength(2));
  expect(puts[1]).toEqual({ ping_interval_sec: 7 });
});

it("saves the start type and shows the read-only and planned sections", async () => {
  const puts = capturePuts(settingsFixture());
  await renderSettings(settingsFixture({ service_start_type: "delayed-auto" }));
  expect(await screen.findByText(copy.settings.service.current("delayed-auto"))).toBeInTheDocument();
  expect(screen.queryByText(copy.settings.service.mismatch)).toBeNull();
  expect(screen.getByText(copy.settings.otpDummy)).toBeInTheDocument();
  expect(screen.getByText(copy.deny.planned_alerts).closest("[data-planned]")).toHaveAttribute("data-planned", "planned_alerts");
  const select = screen.getByRole("combobox", { name: copy.settings.fields.service_start_type });
  expect(select).toHaveTextContent(copy.settings.startTypes["delayed-auto"]);
  await userEvent.click(select);
  await userEvent.click(await screen.findByRole("option", { name: copy.settings.startTypes.manual }));
  await userEvent.click(saveButton());
  await waitFor(() => expect(puts).toEqual([{ service_start_type: "manual" }]));
});

it("shows the current log usage from the saved retention value", async () => {
  const calls = trackCalls();
  await renderSettings(settingsFixture({ log_retention_days: 180 }), previewFixture({ days: 180, total_files: 12, total_bytes: 12_900_000, oldest_date: "2026-04-01" }));
  expect(await screen.findByText(copy.settings.currentUsage(12, formatBytes(12_900_000)))).toBeInTheDocument();
  expect(screen.getByText("2026-04-01")).toBeInTheDocument();
  expect(calls()).toContain("GET /api/settings/retention/preview?days=180");
  // typing a new value does not fetch a preview on every keystroke
  await setNumber(copy.settings.fields.log_retention_days, 365);
  expect(calls().filter((c) => c.includes("days=3") || c.includes("days=36"))).toEqual([]);
});

it("says when there are no log files yet", async () => {
  await renderSettings(settingsFixture(), previewFixture({ days: 180, total_files: 0, total_bytes: 0, oldest_date: null, delete_files: 0, delete_bytes: 0, delete_from: null, delete_to: null }));
  expect(await screen.findByText(copy.settings.noLogs)).toBeInTheDocument();
});

it("blocks out-of-range input with the field's range", async () => {
  const puts = capturePuts(settingsFixture());
  await renderSettings(settingsFixture());
  await setNumber(copy.settings.fields.ping_interval_sec, 0);
  await userEvent.click(saveButton());
  expect(await screen.findByText(copy.mcp.rangeError(1, 300))).toBeInTheDocument();
  expect(screen.getByLabelText(copy.settings.fields.ping_interval_sec)).toHaveAttribute("aria-invalid", "true");
  expect(puts).toEqual([]);
});

it("shows a server 422 under the form and discard puts the saved values back", async () => {
  server.use(http.put("/api/settings", () => HttpResponse.json({ error: "validation" }, { status: 422 })));
  await renderSettings(settingsFixture({ ping_interval_sec: 5 }));
  expect(screen.getByRole("button", { name: copy.settings.discard })).toHaveAttribute("aria-disabled", "true");
  expect(screen.getByRole("button", { name: copy.settings.discard })).toHaveAccessibleDescription(copy.deny.unchanged);
  expect(saveButton()).toHaveAccessibleDescription(copy.deny.unchanged);
  await setNumber(copy.settings.fields.ping_interval_sec, 9);
  await userEvent.click(saveButton());
  expect(await screen.findByText(copy.errors.validation)).toHaveAttribute("role", "alert");
  await userEvent.click(screen.getByRole("button", { name: copy.settings.discard }));
  expect(screen.getByLabelText(copy.settings.fields.ping_interval_sec)).toHaveValue(5);
  expect(saveButton()).toHaveAttribute("aria-disabled", "true");
});

it("asks before leaving with unsaved settings", async () => {
  const { router } = await renderSettings(settingsFixture());
  await setNumber(copy.settings.fields.confirm_interval_sec, 3);
  void router.navigate({ to: "/admin" });
  expect(await screen.findByRole("alertdialog", { name: copy.common.unsavedTitle })).toBeInTheDocument();
  expect(router.state.location.pathname).toBe("/admin/settings");
});

// ---- local only --------------------------------------------------------------------------

function renderAs(Page: ComponentType, me: Me) {
  return renderWithProviders(<Page />, { me });
}

it("local-only pages on external explain and make no request", async () => {
  const spy = trackRequests();
  const clients = [UsersPage, SettingsPage].map((page) => renderAs(page, meFixture("admin", "external")).qc);
  expect(screen.getAllByText(copy.deny.local_only)).toHaveLength(2);
  expect(screen.getByRole("heading", { level: 1, name: copy.users.title })).toBeInTheDocument();
  expect(screen.getByRole("heading", { level: 1, name: copy.settings.title })).toBeInTheDocument();
  // deterministic: a query would be in the cache from its first render, before any request leaves
  for (const qc of clients) expect(qc.getQueryCache().getAll()).toEqual([]);
  expect(spy.paths().filter((p) => p.startsWith("/api/users") || p.startsWith("/api/settings"))).toEqual([]);
});

it("developer on local sees the admin-only reason", async () => {
  const spy = trackRequests();
  const clients = [UsersPage, SettingsPage].map((page) => renderAs(page, meFixture("developer", "local")).qc);
  expect(screen.getAllByText(copy.deny.admin_only)).toHaveLength(2);
  expect(screen.queryByText(copy.deny.local_only)).not.toBeInTheDocument();
  for (const qc of clients) expect(qc.getQueryCache().getAll().filter((q) => q.state.fetchStatus !== "idle")).toEqual([]);
  expect(spy.paths()).toEqual([]);
});

// ---- Plan 5 Task 12: index rows in the retention confirm, the Windows service -----------------

it("the retention confirm shows index rows and that cleanup runs soon", async () => {
  await renderSettings(settingsFixture({ log_retention_days: 180 }), previewFixture({ days: 90, delete_files: 3, delete_bytes: 3_000_000,
    delete_from: "2026-05-09", delete_to: "2026-08-05", delete_events: 41_200 }));
  await setNumber(copy.settings.fields.log_retention_days, 90); await userEvent.click(screen.getByRole("button", { name: copy.common.save }));
  const dialog = await screen.findByRole("alertdialog");
  expect(dialog).toHaveTextContent(copy.settings.retentionDeleteEvents(41_200)); expect(dialog).toHaveTextContent(copy.settings.retentionRunsSoon);
});
it("the retention confirm leaves out the row count while the index cannot tell", async () => {
  await renderSettings(settingsFixture({ log_retention_days: 180 }), previewFixture({ days: 90, delete_files: 3, delete_events: null }));
  await setNumber(copy.settings.fields.log_retention_days, 90); await userEvent.click(saveButton());
  const dialog = await screen.findByRole("alertdialog");
  expect(dialog).not.toHaveTextContent(new RegExp(copy.settings.retentionDeleteEvents(1).replace("1", "[\\d,]+")));
  expect(dialog).toHaveTextContent(copy.settings.retentionRunsSoon);
});
it("announces a failed service status read", async () => {
  server.use(http.get("/api/service", () => HttpResponse.json({ error: "unavailable" }, { status: 503 })));
  await renderSettings(settingsFixture());
  expect(await screen.findByRole("alert")).toHaveTextContent(copy.settings.service.loadError);
});
it("shows the installed service start type and a mismatch", async () => {
  server.use(http.get("/api/service", () => HttpResponse.json(serviceStatusFixture({ installed: true, start_type: "auto", desired: "delayed-auto", in_sync: false }))));
  await renderSettings(settingsFixture());
  expect(await screen.findByText(copy.settings.service.current("auto"))).toBeInTheDocument();
  expect(screen.getByText(copy.settings.service.mismatch)).toBeInTheDocument();
});
it("shows a disabled service as disabled, not as manual", async () => {
  // plan review minor 17: an admin disabled the service in the SCM; the server never re-enables it
  server.use(http.get("/api/service", () => HttpResponse.json(serviceStatusFixture({ installed: true, start_type: "disabled", desired: "delayed-auto", in_sync: false }))));
  await renderSettings(settingsFixture());
  expect(await screen.findByText(copy.settings.service.current("disabled"))).toBeInTheDocument();
  expect(copy.settings.service.current("disabled")).toContain("사용 안 함");
  expect(screen.getByText(copy.settings.service.disabled)).toBeInTheDocument();
  expect(screen.queryByText(copy.settings.service.mismatch)).toBeNull();
  expect(screen.queryByRole("option", { name: "사용 안 함" })).toBeNull();
});
it("tells a bundle without the service from a development run", async () => {
  server.use(http.get("/api/service", () => HttpResponse.json(serviceStatusFixture({ installed: false, running_as_service: false, start_type: null, in_sync: false, bundle: true }))));
  const { unmount } = await renderSettings(settingsFixture());
  expect(await screen.findByText(copy.settings.service.notInstalled)).toBeInTheDocument();
  expect(screen.queryByText(copy.settings.service.devMode)).toBeNull();
  unmount();
  server.use(http.get("/api/service", () => HttpResponse.json(serviceStatusFixture({ installed: false, running_as_service: false, start_type: null, in_sync: false, bundle: false }))));
  await renderSettings(settingsFixture());
  expect(await screen.findByText(copy.settings.service.devMode)).toBeInTheDocument();
  expect(screen.queryByText(copy.settings.service.notInstalled)).toBeNull();
});
it("reads the service status again after saving a new start type", async () => {
  capturePuts(settingsFixture());
  let reads = 0;
  server.use(http.get("/api/service", () => {
    reads++;
    return HttpResponse.json(serviceStatusFixture({ start_type: reads > 1 ? "manual" : "delayed-auto", desired: reads > 1 ? "manual" : "delayed-auto" }));
  }));
  await renderSettings(settingsFixture({ service_start_type: "delayed-auto" }));
  expect(await screen.findByText(copy.settings.service.current("delayed-auto"))).toBeInTheDocument();
  await userEvent.click(screen.getByRole("combobox", { name: copy.settings.fields.service_start_type }));
  await userEvent.click(await screen.findByRole("option", { name: copy.settings.startTypes.manual }));
  await userEvent.click(saveButton());
  expect(await screen.findByText(copy.settings.service.current("manual"))).toBeInTheDocument();
});
it("says when the service status cannot be read", async () => {
  server.use(http.get("/api/service", () => HttpResponse.json({ error: "internal" }, { status: 500 })));
  await renderSettings(settingsFixture());
  expect(await screen.findByText(copy.settings.service.loadError)).toBeInTheDocument();
});
it("does not call /api/service on the external channel", async () => {
  const tracker = trackRequests();
  renderWithProviders(<SettingsPage />, { me: meFixture("admin", "external") });
  await screen.findByText(copy.deny.local_only);
  expect(tracker.paths()).not.toContain("/api/service");
});
