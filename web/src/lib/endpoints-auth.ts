// The auth and bootstrap routes of endpoints.ts (which re-exports them), in a module of their own so
// the board, which needs only these, does not load every admin endpoint (board budget, §7).
import { api } from "./api";
import type { Me, SessionUser } from "./api-types";

// ---- auth (both channels) ------------------------------------------------------------

export const me = () => api<Me>("/api/auth/me");
export const otpRequest = (email: string) =>
  api<Record<string, never>>("/api/auth/otp/request", { method: "POST", body: { email } });
export const otpVerify = (email: string, code: string) =>
  api<{ user: SessionUser; csrf_token: string }>("/api/auth/otp/verify", { method: "POST", body: { email, code } });
export const logout = () => api<void>("/api/auth/logout", { method: "POST" });

// ---- bootstrap (Local) ---------------------------------------------------------------

export const bootstrapStatus = () => api<{ needed: boolean }>("/api/bootstrap");
export const bootstrap = (b: { email: string; name: string }) =>
  api<SessionUser>("/api/bootstrap", { method: "POST", body: b });
