// Unsaved editor content kept per browser tab (sessionStorage), so a session expiry, a reload or a
// trip to the login page does not lose it. Keys: `script:<mcpId>:<kind>`, `mcp-create`, `notice`.
// Storage can be missing, full or blocked (privacy settings): every access is guarded and a failure
// only means no draft — never an error on screen.

const PREFIX = "mcpmon.draft.";

function storage(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export function saveDraft(key: string, value: unknown): void {
  try {
    storage()?.setItem(PREFIX + key, JSON.stringify(value));
  } catch {
    // full or blocked: the draft is best effort
  }
}

/** The stored value, or null when there is none or it cannot be read. The caller checks its shape. */
export function loadDraft<T>(key: string): T | null {
  try {
    const raw = storage()?.getItem(PREFIX + key) ?? null;
    return raw === null ? null : (JSON.parse(raw) as T);
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
