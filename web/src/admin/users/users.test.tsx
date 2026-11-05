import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { copy } from "@/copy/ko";
import type { AdminUser, Me, UserCreate, UserPatch } from "@/lib/api-types";
import { formatKst } from "@/lib/time";
import { adminUser, meFixture, NOW } from "../../../tests/msw/fixtures";
import { server } from "../../../tests/msw/server";
import { renderWithProviders } from "../../../tests/render";

/** Method + path of every request from now on. */
function trackCalls(): () => string[] {
  const seen: string[] = [];
  server.events.on("request:start", ({ request }) => {
    seen.push(`${request.method} ${new URL(request.url).pathname}`);
  });
  return () => [...seen];
}

/** The users page in the full admin app (shell, toasts); GET /api/users answers `list` (a live array). */
async function renderUsers(list: AdminUser[], me: Me = meFixture("admin", "local")) {
  server.use(http.get("/api/users", () => HttpResponse.json(list)));
  const r = renderWithProviders(null, { route: "/admin/users", me });
  // the first test of a run pays for compiling the lazy route chunk under load
  await screen.findByRole("table", { name: copy.users.listLabel }, { timeout: 5000 });
  return r;
}

function userRow(id: number): HTMLElement {
  const row = document.querySelector<HTMLElement>(`tr[data-id="${id}"]`);
  if (!row) throw new Error(`no row for user ${id}`);
  return row;
}

const roleSelect = (id: number) => within(userRow(id)).getByRole("combobox", { name: copy.users.role });
const activeSwitch = (id: number) => within(userRow(id)).getByRole("switch", { name: copy.users.active });

it("lists users with owned MCP counts and adds a user", async () => {
  const list = [
    adminUser({ id: 1, name: "관리자", email: "admin@corp.kr" }),
    adminUser({ id: 2, name: "홍길동", email: "hong@corp.kr", role: "developer", owned_mcps: 2, last_login_at: null }),
  ];
  let body: UserCreate | undefined;
  server.use(
    http.post("/api/users", async ({ request }) => {
      body = (await request.json()) as UserCreate;
      const created = adminUser({ id: 3, ...body, last_login_at: null, owned_mcps: 0 });
      list.push(created);
      return HttpResponse.json(created, { status: 201 });
    }),
  );
  await renderUsers(list);

  const row2 = within(userRow(2));
  expect(row2.getByRole("rowheader")).toHaveTextContent("홍길동");
  expect(row2.getByText("hong@corp.kr")).toBeInTheDocument();
  expect(row2.getByRole("cell", { name: "2" })).toBeInTheDocument();
  expect(row2.getByText(copy.users.neverLoggedIn)).toBeInTheDocument();
  expect(roleSelect(2)).toHaveTextContent(copy.roles.developer);
  expect(within(userRow(1)).getByText(formatKst(NOW))).toBeInTheDocument();
  expect(roleSelect(1)).toHaveTextContent(copy.roles.admin);

  await userEvent.click(screen.getByRole("button", { name: copy.users.add }));
  const dialog = await screen.findByRole("dialog", { name: copy.users.addTitle });
  await userEvent.type(within(dialog).getByLabelText(copy.users.email), "  new@corp.kr ");
  await userEvent.type(within(dialog).getByLabelText(copy.users.name), "새사람");
  await userEvent.click(within(dialog).getByRole("combobox", { name: copy.users.role }));
  await userEvent.click(await screen.findByRole("option", { name: copy.roles.admin }));
  await userEvent.click(within(dialog).getByRole("button", { name: copy.users.addSubmit }));

  await waitFor(() => expect(body).toEqual({ email: "new@corp.kr", name: "새사람", role: "admin" }));
  expect(await screen.findByText(copy.users.added("새사람"))).toBeInTheDocument();
  await waitFor(() => expect(screen.queryByRole("dialog", { name: copy.users.addTitle })).not.toBeInTheDocument());
  // the list is fetched again: the new row comes from the server
  expect(await within(await screen.findByRole("table")).findByText("new@corp.kr")).toBeInTheDocument();
  expect(within(userRow(3)).getByRole("cell", { name: "0" })).toBeInTheDocument();
});

it("guards the last active admin", async () => {
  await renderUsers([adminUser({ id: 1, role: "admin", active: true }), adminUser({ id: 2, role: "developer" })]);
  expect(within(userRow(1)).getByRole("switch", { name: copy.users.active })).toHaveAttribute("aria-disabled", "true");
  expect(within(userRow(1)).getByText(copy.users.lastAdmin)).toBeInTheDocument();
  // the row header (read before every cell) is the name alone, not the note or the edit button
  expect(within(userRow(1)).getByRole("rowheader")).toHaveTextContent(/^user1$/);
  expect(roleSelect(1)).toHaveAttribute("aria-disabled", "true");
  expect(roleSelect(1)).toHaveAccessibleDescription(expect.stringContaining(copy.users.lastAdmin));
  expect(activeSwitch(1)).toHaveAccessibleDescription(expect.stringContaining(copy.users.lastAdmin));

  const calls = trackCalls();
  await userEvent.click(activeSwitch(1));
  expect(activeSwitch(1)).toBeChecked();
  await userEvent.click(roleSelect(1));
  expect(screen.queryByRole("option")).not.toBeInTheDocument();
  expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  expect(calls().filter((c) => c.startsWith("PATCH"))).toEqual([]);

  // the developer's row is not guarded
  expect(roleSelect(2)).not.toHaveAttribute("aria-disabled");
  expect(within(userRow(2)).queryByText(copy.users.lastAdmin)).not.toBeInTheDocument();
});

it("does not guard an admin while another active admin exists (an inactive admin does not count)", async () => {
  await renderUsers([
    adminUser({ id: 1 }),
    adminUser({ id: 2 }),
    adminUser({ id: 3, active: false }),
  ]);
  expect(activeSwitch(1)).not.toHaveAttribute("aria-disabled");
  expect(activeSwitch(2)).not.toHaveAttribute("aria-disabled");
  expect(screen.queryByText(copy.users.lastAdmin)).not.toBeInTheDocument();
  expect(within(userRow(3)).getByText(copy.users.inactive)).toBeInTheDocument();
});

it("shows the server last_admin error", async () => {
  server.use(http.patch("/api/users/2", () => HttpResponse.json({ error: "last_admin" }, { status: 409 })));
  await renderUsers([adminUser({ id: 1 }), adminUser({ id: 2 })]);
  await userEvent.click(activeSwitch(2));
  const confirm = await screen.findByRole("alertdialog");
  await userEvent.click(within(confirm).getByRole("button", { name: copy.users.deactivateConfirm }));
  expect(await screen.findByText(copy.errors.last_admin)).toBeInTheDocument();
  expect(activeSwitch(2)).toBeChecked();
});

it("asks before changing a role, with the sign-out notice, and sends only the role", async () => {
  let body: UserPatch | undefined;
  server.use(
    http.patch("/api/users/2", async ({ request }) => {
      body = (await request.json()) as UserPatch;
      return HttpResponse.json(adminUser({ id: 2, name: "홍길동", role: "admin" }));
    }),
  );
  const list = [adminUser({ id: 1 }), adminUser({ id: 2, name: "홍길동", role: "developer" })];
  await renderUsers(list);

  await userEvent.click(roleSelect(2));
  await userEvent.click(await screen.findByRole("option", { name: copy.roles.admin }));
  let confirm = await screen.findByRole("alertdialog", { name: copy.users.roleTitle("홍길동", copy.roles.admin) });
  expect(confirm).toHaveTextContent(copy.users.revokeNotice);
  expect(confirm).not.toHaveTextContent(copy.users.revokeSelf);
  await userEvent.click(within(confirm).getByRole("button", { name: copy.common.cancel }));
  await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
  expect(body).toBeUndefined();
  expect(roleSelect(2)).toHaveTextContent(copy.roles.developer);
  expect(roleSelect(2)).toHaveFocus();

  await userEvent.click(roleSelect(2));
  await userEvent.click(await screen.findByRole("option", { name: copy.roles.admin }));
  confirm = await screen.findByRole("alertdialog");
  list[1] = adminUser({ id: 2, name: "홍길동", role: "admin" }); // what the refetch returns
  await userEvent.click(within(confirm).getByRole("button", { name: copy.users.roleConfirm }));
  await waitFor(() => expect(body).toEqual({ role: "admin" }));
  expect(await screen.findByText(copy.users.roleChanged("홍길동", copy.roles.admin))).toBeInTheDocument();
  await waitFor(() => expect(roleSelect(2)).toHaveTextContent(copy.roles.admin));
});

it("asks before deactivating; activating needs no confirm", async () => {
  const bodies: UserPatch[] = [];
  server.use(
    http.patch("/api/users/:id", async ({ params, request }) => {
      const patch = (await request.json()) as UserPatch;
      bodies.push(patch);
      return HttpResponse.json(adminUser({ id: Number(params.id), role: "developer", ...patch }));
    }),
  );
  await renderUsers([adminUser({ id: 1 }), adminUser({ id: 2, role: "developer" }), adminUser({ id: 3, role: "developer", active: false })]);

  await userEvent.click(activeSwitch(2));
  const confirm = await screen.findByRole("alertdialog", { name: copy.users.deactivateTitle("user2") });
  expect(confirm).toHaveTextContent(copy.users.revokeNotice);
  expect(bodies).toEqual([]);
  await userEvent.click(within(confirm).getByRole("button", { name: copy.users.deactivateConfirm }));
  await waitFor(() => expect(bodies).toEqual([{ active: false }]));
  expect(await screen.findByText(copy.users.deactivated("user2"))).toBeInTheDocument();
  expect(activeSwitch(2)).toHaveFocus();

  await userEvent.click(activeSwitch(3));
  await waitFor(() => expect(bodies).toEqual([{ active: false }, { active: true }]));
  expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  expect(await screen.findByText(copy.users.activated("user3"))).toBeInTheDocument();
});

it("edits a name in a dialog and refuses an empty one", async () => {
  let body: UserPatch | undefined;
  const list = [adminUser({ id: 1 }), adminUser({ id: 2, role: "developer" })];
  server.use(
    http.patch("/api/users/2", async ({ request }) => {
      body = (await request.json()) as UserPatch;
      list[1] = adminUser({ id: 2, role: "developer", name: body.name });
      return HttpResponse.json(list[1]);
    }),
  );
  await renderUsers(list);

  const edit = within(userRow(2)).getByRole("button", { name: copy.users.editName("user2") });
  await userEvent.click(edit);
  const dialog = await screen.findByRole("dialog", { name: copy.users.editNameTitle });
  const input = within(dialog).getByLabelText(copy.users.name);
  expect(input).toHaveValue("user2");
  await userEvent.clear(input);
  await userEvent.type(input, "   ");
  await userEvent.click(within(dialog).getByRole("button", { name: copy.common.save }));
  expect(await within(dialog).findByText(copy.users.nameRequired)).toBeInTheDocument();
  expect(input).toHaveAttribute("aria-invalid", "true");
  expect(body).toBeUndefined();

  await userEvent.clear(input);
  await userEvent.type(input, " 김철수 ");
  await userEvent.click(within(dialog).getByRole("button", { name: copy.common.save }));
  await waitFor(() => expect(body).toEqual({ name: "김철수" }));
  expect(await screen.findByText(copy.users.nameSaved)).toBeInTheDocument();
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  await waitFor(() => expect(within(userRow(2)).getByRole("rowheader")).toHaveTextContent("김철수"));
  expect(edit).toHaveFocus();
});

it("puts user_exists and invalid_email on the email field", async () => {
  let reply: { error: string; status: number } = { error: "user_exists", status: 409 };
  server.use(http.post("/api/users", () => HttpResponse.json({ error: reply.error }, { status: reply.status })));
  await renderUsers([adminUser({ id: 1 })]);

  await userEvent.click(screen.getByRole("button", { name: copy.users.add }));
  const dialog = await screen.findByRole("dialog", { name: copy.users.addTitle });
  const email = within(dialog).getByLabelText(copy.users.email);
  await userEvent.type(email, "admin@corp.kr");
  await userEvent.type(within(dialog).getByLabelText(copy.users.name), "중복");
  await userEvent.click(within(dialog).getByRole("button", { name: copy.users.addSubmit }));
  expect(await within(dialog).findByText(copy.errors.user_exists)).toBeInTheDocument();
  expect(email).toHaveAttribute("aria-invalid", "true");
  expect(email).toHaveFocus();

  reply = { error: "invalid_email", status: 422 };
  await userEvent.clear(email);
  await userEvent.type(email, "not-an-email");
  await userEvent.click(within(dialog).getByRole("button", { name: copy.users.addSubmit }));
  expect(await within(dialog).findByText(copy.errors.invalid_email)).toBeInTheDocument();
  expect(email).toHaveAccessibleDescription(expect.stringContaining(copy.errors.invalid_email));
});

it("needs an email and a name before adding", async () => {
  const calls = trackCalls();
  await renderUsers([adminUser({ id: 1 })]);
  await userEvent.click(screen.getByRole("button", { name: copy.users.add }));
  const dialog = await screen.findByRole("dialog", { name: copy.users.addTitle });
  expect(within(dialog).getByRole("combobox", { name: copy.users.role })).toHaveTextContent(copy.roles.developer);
  await userEvent.click(within(dialog).getByRole("button", { name: copy.users.addSubmit }));
  expect(await within(dialog).findByText(copy.users.emailRequired)).toBeInTheDocument();
  expect(within(dialog).getByText(copy.users.nameRequired)).toBeInTheDocument();
  expect(calls()).not.toContain("POST /api/users");
});

it("changing my own role signs me out through the 401 flow", async () => {
  const list = [adminUser({ id: 1, name: "나" }), adminUser({ id: 3 })];
  server.use(
    http.patch("/api/users/1", () => {
      // the server revokes my sessions: from now on every request is anonymous
      server.use(http.get("/api/users", () => HttpResponse.json({ error: "login_required" }, { status: 401 })));
      return HttpResponse.json(adminUser({ id: 1, name: "나", role: "developer" }));
    }),
  );
  const { router, stream } = await renderUsers(list);

  await userEvent.click(roleSelect(1));
  await userEvent.click(await screen.findByRole("option", { name: copy.roles.developer }));
  const confirm = await screen.findByRole("alertdialog");
  expect(confirm).toHaveTextContent(copy.users.revokeSelf);
  await userEvent.click(within(confirm).getByRole("button", { name: copy.users.roleConfirm }));

  await waitFor(() => expect(router.state.location.pathname).toBe("/admin/login"));
  expect(router.state.location.search).toEqual({ redirect: "/admin/users" });
  expect(stream.restart).toHaveBeenCalled();
});

it("shows a load error", async () => {
  server.use(http.get("/api/users", () => HttpResponse.json({ error: "internal" }, { status: 500 })));
  renderWithProviders(null, { route: "/admin/users", me: meFixture("admin", "local") });
  expect(await screen.findByText(copy.users.loadError, {}, { timeout: 5000 })).toHaveAttribute("role", "alert");
});
