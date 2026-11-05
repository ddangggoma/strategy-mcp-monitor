import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import type { Mock } from "vitest";
import { copy } from "@/copy/ko";
import type { Me } from "@/lib/api-types";
import { documentNav } from "@/lib/redirect";
import { session } from "@/lib/session";
import { ResendRing } from "./ResendRing";
import { meFixture } from "../../../tests/msw/fixtures";
import { server, trackRequests } from "../../../tests/msw/server";
import { fakeStream, renderWithProviders } from "../../../tests/render";

interface LoginOptions {
  search?: Record<string, string>;
  restart?: Mock<() => void>;
  me?: Me;
}

/** The admin app at /admin/login (lazy page: callers await the first findBy). */
function renderLogin({ search = {}, restart, me = meFixture(null, "external") }: LoginOptions = {}) {
  const stream = fakeStream();
  if (restart) stream.restart = restart;
  const qs = new URLSearchParams(search).toString();
  return renderWithProviders(null, { route: `/admin/login${qs ? `?${qs}` : ""}`, me, live: { stream } });
}

const cell = (i: number) => screen.getByLabelText(copy.login.codeDigit(i + 1)) as HTMLInputElement;

async function requestCode(email = "admin@x.com") {
  await userEvent.type(await screen.findByLabelText(copy.login.email), email);
  await userEvent.click(screen.getByRole("button", { name: copy.login.sendCode }));
  await screen.findByRole("group", { name: copy.login.codeGroup });
}

async function enterCode(code: string) {
  await userEvent.click(cell(0));
  await userEvent.paste(code);
}

it("logs in with email then OTP, restarts the stream and returns to the redirect target", async () => {
  server.use(
    http.post("/api/auth/otp/verify", () =>
      HttpResponse.json({ user: { id: 1, email: "admin@x.com", name: "관리자", role: "admin" }, csrf_token: "csrf-from-verify" }),
    ),
  );
  const restart = vi.fn<() => void>();
  const { router } = renderLogin({ search: { redirect: "/admin/mcps/3?tab=history" }, restart });
  await userEvent.type(await screen.findByLabelText(copy.login.email), "admin@x.com");
  await userEvent.click(screen.getByRole("button", { name: copy.login.sendCode }));
  expect(await screen.findByText(copy.login.codeSent("admin@x.com"))).toBeInTheDocument();
  const group = screen.getByRole("group", { name: copy.login.codeGroup });
  expect(group).toHaveAccessibleDescription(copy.login.codeSent("admin@x.com"));
  await waitFor(() => expect(cell(0)).toHaveFocus()); // straight to the code
  await userEvent.click(cell(0));
  await userEvent.paste("246810");
  await waitFor(() => expect(router.state.location.href).toBe("/admin/mcps/3?tab=history"));
  expect(restart).toHaveBeenCalledTimes(1);
  expect(session.csrf).toBe("csrf-from-verify");
  expect(session.me?.user?.email).toBe("admin@x.com");
  expect(await screen.findByRole("heading", { level: 1, name: copy.mcp.detail })).toBeInTheDocument();
});

it("sends the email and the code to the server", async () => {
  const bodies: unknown[] = [];
  server.use(
    http.post("/api/auth/otp/request", async ({ request }) => {
      bodies.push(await request.json());
      return HttpResponse.json({}, { status: 202 });
    }),
    http.post("/api/auth/otp/verify", async ({ request }) => {
      bodies.push(await request.json());
      return HttpResponse.json({ user: { id: 1, email: "a@x.com", name: "a", role: "admin" }, csrf_token: "c" });
    }),
  );
  const { router } = renderLogin();
  await requestCode("a@x.com");
  await enterCode("135790");
  await waitFor(() => expect(router.state.location.pathname).toBe("/admin"));
  expect(bodies).toEqual([{ email: "a@x.com" }, { email: "a@x.com", code: "135790" }]);
});

it("leaves the admin router with a full page load when the target is the board (F11)", async () => {
  const assign = vi.spyOn(documentNav, "assign").mockImplementation(() => {});
  const { router } = renderLogin({ search: { redirect: "/" } });
  await requestCode();
  await enterCode("246810");
  await waitFor(() => expect(assign).toHaveBeenCalledWith("/"));
  expect(router.state.location.pathname).toBe("/admin/login");
});

it("ignores an unsafe redirect target", async () => {
  const assign = vi.spyOn(documentNav, "assign").mockImplementation(() => {});
  const { router } = renderLogin({ search: { redirect: "//evil.com" } });
  await requestCode();
  await enterCode("246810");
  await waitFor(() => expect(router.state.location.pathname).toBe("/admin"));
  expect(assign).not.toHaveBeenCalled();
});

it("shows the dev OTP badge for the dummy provider", async () => {
  renderLogin({ me: meFixture(null, "local") });
  expect(await screen.findByText(copy.login.devBadge)).toBeInTheDocument();
  expect(screen.queryByText(copy.login.devHint)).toBeNull(); // the hint belongs to the code step
  await requestCode();
  expect(screen.getByText(copy.login.devHint)).toBeInTheDocument();
});

it("shows the lockout message when Retry-After exceeds 60 s", async () => {
  server.use(
    http.post("/api/auth/otp/request", () =>
      HttpResponse.json({ error: "rate_limited" }, { status: 429, headers: { "Retry-After": "1800" } }),
    ),
  );
  renderLogin();
  await userEvent.type(await screen.findByLabelText(copy.login.email), "admin@x.com");
  await userEvent.click(screen.getByRole("button", { name: copy.login.sendCode }));
  expect(await screen.findByRole("alert")).toHaveTextContent(copy.login.lockedFor(30));
  expect(screen.queryByRole("group", { name: copy.login.codeGroup })).toBeNull();
});

it("goes on to the code step with the ring set to a short Retry-After (F05)", async () => {
  server.use(
    http.post("/api/auth/otp/request", () =>
      HttpResponse.json({ error: "rate_limited" }, { status: 429, headers: { "Retry-After": "42" } }),
    ),
  );
  renderLogin();
  await requestCode();
  expect(screen.getByText(copy.login.resendIn(42))).toBeInTheDocument();
  expect(screen.getByRole("button", { name: copy.login.resend })).toHaveAttribute("aria-disabled", "true");
});

it("shakes and hints after a wrong code, and asks for a new code after 5 failures", async () => {
  server.use(http.post("/api/auth/otp/verify", () => HttpResponse.json({ error: "login_required" }, { status: 401 })));
  renderLogin();
  await requestCode();
  const group = screen.getByRole("group", { name: copy.login.codeGroup });

  await enterCode("111111");
  expect(await screen.findByText(copy.login.wrongCode)).toBeInTheDocument();
  expect(screen.getByText(copy.login.failedCount(1))).toBeInTheDocument();
  expect(screen.getByText(copy.login.failureHint)).toBeInTheDocument();
  expect(group).toHaveAttribute("data-invalid");
  await waitFor(() => expect(cell(0)).toHaveFocus());
  expect(cell(0).value).toBe("");

  for (const n of [2, 3, 4]) {
    await enterCode("111111");
    expect(await screen.findByText(copy.login.failedCount(n))).toBeInTheDocument();
  }
  expect(screen.queryByText(copy.login.codeExhausted)).toBeNull();
  await enterCode("111111");
  expect(await screen.findByText(copy.login.codeExhausted)).toBeInTheDocument();
  expect(screen.queryByText(copy.login.wrongCode)).toBeNull();
  expect(screen.getByText(copy.login.failureHint)).toBeInTheDocument();
  expect(cell(0)).toBeDisabled();
  await waitFor(() => expect(screen.getByRole("button", { name: copy.login.resend })).toHaveFocus()); // not lost to <body>
  expect(session.me?.user).toBeNull();
});

it("shows a field error for an invalid email", async () => {
  server.use(http.post("/api/auth/otp/request", () => HttpResponse.json({ error: "invalid_email" }, { status: 422 })));
  renderLogin();
  const email = await screen.findByLabelText(copy.login.email);
  await userEvent.type(email, "not-an-email");
  await userEvent.click(screen.getByRole("button", { name: copy.login.sendCode }));
  expect(await screen.findByText(copy.errors.invalid_email)).toBeInTheDocument();
  expect(email).toHaveAttribute("aria-invalid", "true");
  expect(email).toHaveAccessibleDescription(copy.errors.invalid_email);
  expect(email).toHaveFocus();
});

it("asks for an email without calling the server when the field is empty", async () => {
  const seen = trackRequests();
  renderLogin();
  await screen.findByLabelText(copy.login.email);
  await userEvent.click(screen.getByRole("button", { name: copy.login.sendCode }));
  expect(await screen.findByText(copy.errors.invalid_email)).toBeInTheDocument();
  expect(seen.paths()).not.toContain("/api/auth/otp/request");
});

it("goes back to the email step and requests a new code once the ring ends", async () => {
  let requests = 0;
  server.use(
    http.post("/api/auth/otp/request", () => {
      requests += 1;
      return HttpResponse.json({}, { status: 202 });
    }),
  );
  renderLogin({ search: { email: "pre@x.com" } });
  expect(await screen.findByLabelText(copy.login.email)).toHaveValue("pre@x.com");
  await userEvent.click(screen.getByRole("button", { name: copy.login.sendCode }));
  await screen.findByRole("group", { name: copy.login.codeGroup });

  const resend = screen.getByRole("button", { name: copy.login.resend });
  await userEvent.click(resend); // still counting down: ignored
  expect(requests).toBe(1);

  await userEvent.click(screen.getByRole("button", { name: copy.login.changeEmail }));
  expect(screen.getByLabelText(copy.login.email)).toHaveValue("pre@x.com");
  expect(screen.queryByRole("group", { name: copy.login.codeGroup })).toBeNull();
});

it("redirects to setup on local when bootstrap is needed", async () => {
  server.use(http.get("/api/bootstrap", () => HttpResponse.json({ needed: true })));
  const { router } = renderLogin({ me: meFixture(null, "local") });
  expect(await screen.findByRole("heading", { name: copy.setup.title })).toBeInTheDocument();
  expect(router.state.location.pathname).toBe("/admin/setup");
});

it("never asks the external channel about bootstrap", async () => {
  const seen = trackRequests();
  renderLogin({ me: meFixture(null, "external") });
  expect(await screen.findByLabelText(copy.login.email)).toBeInTheDocument();
  expect(seen.paths()).not.toContain("/api/bootstrap");
});

it("creates the first admin and continues to login with the email filled in", async () => {
  let body: unknown;
  let needed = true;
  server.use(
    http.get("/api/bootstrap", () => HttpResponse.json({ needed })),
    http.post("/api/bootstrap", async ({ request }) => {
      body = await request.json();
      needed = false;
      return HttpResponse.json({ id: 1, email: "first@x.com", name: "첫 관리자", role: "admin" }, { status: 201 });
    }),
  );
  const { router } = renderWithProviders(null, { route: "/admin/setup", me: meFixture(null, "local") });
  await userEvent.type(await screen.findByLabelText(copy.setup.email), "first@x.com");
  await userEvent.type(screen.getByLabelText(copy.setup.name), "첫 관리자");
  await userEvent.click(screen.getByRole("button", { name: copy.setup.submit }));
  await waitFor(() => expect(router.state.location.pathname).toBe("/admin/login"));
  expect(body).toEqual({ email: "first@x.com", name: "첫 관리자" });
  expect(await screen.findByLabelText(copy.login.email)).toHaveValue("first@x.com");
  expect(screen.getByText(copy.setup.done)).toBeInTheDocument();
});

it("sends setup to login when another tab finished it first (409)", async () => {
  let needed = true;
  server.use(
    http.get("/api/bootstrap", () => HttpResponse.json({ needed })),
    http.post("/api/bootstrap", () => {
      needed = false; // another tab got there first
      return HttpResponse.json({ error: "bootstrap_done" }, { status: 409 });
    }),
  );
  const { router } = renderWithProviders(null, { route: "/admin/setup", me: meFixture(null, "local") });
  await userEvent.type(await screen.findByLabelText(copy.setup.email), "first@x.com");
  await userEvent.type(screen.getByLabelText(copy.setup.name), "a");
  await userEvent.click(screen.getByRole("button", { name: copy.setup.submit }));
  await waitFor(() => expect(router.state.location.pathname).toBe("/admin/login"));
  expect(await screen.findByText(copy.errors.bootstrap_done)).toBeInTheDocument();
});

it.each([
  ["external channel", meFixture(null, "external"), true],
  ["setup already done", meFixture(null, "local"), false],
])("does not show setup (%s)", async (_label, me, needed) => {
  server.use(http.get("/api/bootstrap", () => HttpResponse.json({ needed })));
  const { router } = renderWithProviders(null, { route: "/admin/setup", me });
  expect(await screen.findByLabelText(copy.login.email)).toBeInTheDocument();
  expect(router.state.location.pathname).toBe("/admin/login");
});

it("counts the resend ring down and calls onDone once", () => {
  vi.useFakeTimers();
  try {
    const onDone = vi.fn();
    render(<ResendRing seconds={3} startedAt={performance.now()} onDone={onDone} />);
    expect(screen.getByRole("timer")).toHaveTextContent(copy.login.resendIn(3));
    act(() => vi.advanceTimersByTime(1000));
    expect(screen.getByRole("timer")).toHaveTextContent(copy.login.resendIn(2));
    act(() => vi.advanceTimersByTime(2000));
    expect(onDone).toHaveBeenCalledTimes(1);
    act(() => vi.advanceTimersByTime(3000));
    expect(onDone).toHaveBeenCalledTimes(1);
    expect(document.querySelector("[data-anim=ring]")).not.toBeNull();
  } finally {
    vi.useRealTimers();
  }
});
