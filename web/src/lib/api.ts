// One wrapper for every API call (plan Appendix B): JSON in and out, same-origin cookies, the CSRF
// header on unsafe methods, `{"error": code}` bodies mapped to ApiError, one CSRF refresh-and-retry,
// and the 401 hook that sends the admin shell to login.
import { refreshSession, session } from "./session";

export class ApiError extends Error {
  readonly status: number;
  /** Server error code (`{"error": code}`), `internal` for a non-JSON error, `network` when no response came. */
  readonly code: string;
  /** Seconds from `Retry-After` (429), else null. */
  readonly retryAfterSec: number | null;

  constructor(status: number, code: string, retryAfterSec: number | null = null) {
    super(`${status} ${code}`);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.retryAfterSec = retryAfterSec;
  }
}

export type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export interface ApiInit {
  method?: Method;
  body?: unknown;
  signal?: AbortSignal;
  query?: Record<string, string | number>;
}

/** Absolute same-origin URL: Node's fetch (tests) rejects relative ones, browsers accept both (F14). */
export function apiUrl(path: string, query?: Record<string, string | number>): string {
  const url = new URL(path, location.origin);
  if (query) for (const [k, v] of Object.entries(query)) url.searchParams.set(k, String(v));
  return url.toString();
}

/** `Retry-After` as seconds: delta-seconds or an HTTP date; null when absent or unreadable. */
export function parseRetryAfter(value: string | null): number | null {
  if (value === null) return null;
  const trimmed = value.trim();
  if (/^\d+$/.test(trimmed)) return Number(trimmed);
  const at = Date.parse(trimmed);
  return Number.isNaN(at) ? null : Math.max(0, Math.ceil((at - Date.now()) / 1000));
}

async function errorCode(res: Response): Promise<string> {
  try {
    const body: unknown = await res.json();
    if (body && typeof body === "object" && typeof (body as { error?: unknown }).error === "string") {
      return (body as { error: string }).error;
    }
  } catch {
    // not JSON (proxy page, crash): fall through
  }
  return "internal";
}

async function request<T>(path: string, init: ApiInit, csrfRetry: boolean): Promise<T> {
  const method = init.method ?? "GET";
  const headers: Record<string, string> = { Accept: "application/json" };
  if (init.body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET" && session.csrf) headers["X-CSRF-Token"] = session.csrf;

  let res: Response;
  try {
    res = await fetch(apiUrl(path, init.query), {
      method,
      headers,
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
      credentials: "same-origin",
      signal: init.signal,
    });
  } catch (e) {
    if (init.signal?.aborted) throw e; // cancellation (React Query, unmount) is not a failure
    throw new ApiError(0, "network");
  }

  if (res.ok) {
    if (res.status === 204) return undefined as T;
    const text = await res.text();
    if (text === "") return undefined as T;
    try {
      return JSON.parse(text) as T;
    } catch {
      throw new ApiError(res.status, "internal");
    }
  }

  const code = await errorCode(res);
  if (res.status === 403 && code === "csrf" && csrfRetry) {
    // another tab logged in again and revoked this tab's session token: fetch the current one, retry once
    await refreshSession();
    return request<T>(path, init, false);
  }
  if (res.status === 401 && code === "login_required" && !path.startsWith("/api/auth/")) {
    session.onUnauthorized?.();
  }
  throw new ApiError(res.status, code, parseRetryAfter(res.headers.get("Retry-After")));
}

export function api<T>(path: string, init: ApiInit = {}): Promise<T> {
  return request<T>(path, init, true);
}
