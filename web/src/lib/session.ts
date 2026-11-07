// The tab's session: `me` (user, channel, CSRF token) shared by the API client and React.
// The session cookie is HttpOnly and never read here; only the CSRF token travels in JS.
import { useSyncExternalStore } from "react";
import { api } from "./api";
import type { Me, SessionUser } from "./api-types";

export const session: {
  csrf: string | null;
  me: Me | null;
  /** Called on a 401 outside /api/auth/ (session expired or revoked): the admin shell sends the user to login. */
  onUnauthorized: (() => void) | null;
  /**
   * Called when a CSRF refresh finds another user (or channel) in the shared cookie: the admin shell
   * treats it like a user switch, so the previous users edits cannot be saved as the new ones.
   */
  onSessionChanged: (() => void) | null;
  onChange: Set<(me: Me) => void>;
} = { csrf: null, me: null, onUnauthorized: null, onSessionChanged: null, onChange: new Set() };

function setMe(me: Me): void {
  session.me = me;
  session.csrf = me.csrf_token;
  for (const fn of [...session.onChange]) fn(me);
}

/** GET /api/auth/me: refreshes the CSRF token (also after a 403 `csrf`) and notifies listeners. */
export async function refreshSession(): Promise<Me> {
  const me = await api<Me>("/api/auth/me");
  setMe(me);
  return me;
}

/**
 * After a successful OTP verify. Channel and `otp_provider` come from the `me` loaded before login;
 * without one the channel is assumed `external`, the less privileged guess (no Local-only calls).
 */
export function setSessionFromLogin(user: SessionUser, csrf: string): void {
  const prev = session.me;
  setMe({ user, channel: prev?.channel ?? "external", csrf_token: csrf, otp_provider: prev?.otp_provider ?? "dummy" });
}

/** After logout (or a revoked session): anonymous on the same channel. */
export function clearSession(): void {
  if (session.me) setMe({ ...session.me, user: null, csrf_token: null });
  else session.csrf = null;
}

function subscribe(onStoreChange: () => void): () => void {
  const fn = () => onStoreChange();
  session.onChange.add(fn);
  return () => {
    session.onChange.delete(fn);
  };
}

function getSnapshot(): Me | null {
  return session.me;
}

export function useSession(): Me | null {
  return useSyncExternalStore(subscribe, getSnapshot);
}
