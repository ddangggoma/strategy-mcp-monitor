import { act, renderHook } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { meFixture } from "../../tests/msw/fixtures";
import { server } from "../../tests/msw/server";
import { clearSession, refreshSession, session, setSessionFromLogin, useSession } from "./session";

it("refreshSession loads me, stores the token and notifies listeners", async () => {
  const me = meFixture("developer", "external", 4);
  server.use(http.get("/api/auth/me", () => HttpResponse.json(me)));
  const heard = vi.fn();
  session.onChange.add(heard);
  await expect(refreshSession()).resolves.toEqual(me);
  expect(session.me).toEqual(me);
  expect(session.csrf).toBe(me.csrf_token);
  expect(heard).toHaveBeenCalledWith(me);
});

it("setSessionFromLogin keeps channel and otp_provider from the previous me", async () => {
  server.use(http.get("/api/auth/me", () => HttpResponse.json(meFixture(null, "external"))));
  await refreshSession();
  setSessionFromLogin({ id: 9, email: "n@x.com", name: "n", role: "admin" }, "csrf-9");
  expect(session.me).toEqual({
    user: { id: 9, email: "n@x.com", name: "n", role: "admin" },
    channel: "external",
    csrf_token: "csrf-9",
    otp_provider: "dummy",
  });
  expect(session.csrf).toBe("csrf-9");
});

it("setSessionFromLogin without a previous me assumes the less privileged external channel", () => {
  setSessionFromLogin({ id: 9, email: "n@x.com", name: "n", role: "admin" }, "csrf-9");
  expect(session.me?.channel).toBe("external");
});

it("clearSession drops user and token but keeps the channel", async () => {
  server.use(http.get("/api/auth/me", () => HttpResponse.json(meFixture("admin", "local"))));
  await refreshSession();
  clearSession();
  expect(session.me).toEqual({ user: null, channel: "local", csrf_token: null, otp_provider: "dummy" });
  expect(session.csrf).toBeNull();
});

it("useSession follows the store", async () => {
  const { result } = renderHook(() => useSession());
  expect(result.current).toBeNull();
  const me = meFixture("developer", "local");
  server.use(http.get("/api/auth/me", () => HttpResponse.json(me)));
  await act(() => refreshSession());
  expect(result.current).toEqual(me);
  act(() => clearSession());
  expect(result.current?.user).toBeNull();
});
