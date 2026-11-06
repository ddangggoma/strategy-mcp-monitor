// Unsaved editor content kept per browser tab (sessionStorage), so a session expiry, a reload or a
// trip to the login page does not lose it. Keys: `script:<mcpId>:<kind>`, `mcp-create`, `notice`.
// Storage can be missing, full or blocked (privacy settings): every access is guarded and a failure
// only means no draft — never an error on screen.
// Each draft records the user who wrote it: after a session expiry someone else may log in on the
// same tab, and they must not get (and could save) the previous user's edits.
import { session } from "./session";

const PREFIX = "mcpmon.draft.";

type Owner = number | null;

interface Stored {
  owner: Owner;
  value: unknown;
}

function currentUser(): Owner {
  return session.me?.user?.id ?? null;
}

function isStored(v: unknown): v is Stored {
  return typeof v === "object" && v !== null && "owner" in v && "value" in v && (typeof v.owner === "number" || v.owner === null);
}

function storage(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

/** Keeps `value` for `owner` (default: the logged-in user). */
export function saveDraft(key: string, value: unknown, owner: Owner = currentUser()): void {
  try {
    storage()?.setItem(PREFIX + key, JSON.stringify({ owner, value } satisfies Stored));
  } catch {
    // full or blocked: the draft is best effort
  }
}

/**
 * The value `owner` (default: the logged-in user) stored, or null when there is none, it cannot be
 * read or it is someone else's. Another user's draft is deleted when a user asks; with nobody
 * logged in (the login page after a 401) it is kept for its owner. The caller checks its shape.
 */
export function loadDraft<T>(key: string, owner: Owner = currentUser()): T | null {
  try {
    const raw = storage()?.getItem(PREFIX + key) ?? null;
    if (raw === null) return null;
    const stored: unknown = JSON.parse(raw);
    if (isStored(stored) && stored.owner === owner) return stored.value as T;
    if (owner !== null) clearDraft(key);
    return null;
  } catch {
    return null;
  }
}

export function clearDraft(key: string): void {
  try {
    storage()?.removeItem(PREFIX + key);
  } catch {
    // nothing to do
  }
}

/** On logout: the next person to log in on this tab must not find this person's drafts. */
export function clearAllDrafts(): void {
  try {
    const s = storage();
    if (!s) return;
    const keys: string[] = [];
    for (let i = 0; i < s.length; i++) {
      const k = s.key(i);
      if (k?.startsWith(PREFIX)) keys.push(k);
    }
    for (const k of keys) s.removeItem(k);
  } catch {
    // nothing to do
  }
}
