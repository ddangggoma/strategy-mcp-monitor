/**
 * RDP sessions for the E2E backend: it reads `<root>/sessions.json` (`--session-source json:`) on
 * every poll, so a test connects, disconnects and logs users off by rewriting that file. A session
 * with `session_id: "self"` is this PC's own Windows session: the server launches the real session
 * agent for it (`--agent-launcher local --agent-dialog print`), and the agent writes each notice it
 * shows to `<root>/run/agent-<session id>.url` as `OPEN <display id> <url>` (`CLOSE <id>` when it
 * closes the window).
 */
import { readdir, readFile, rename, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { SESSIONS_FILE, type BackendState } from "./backend";

/** One JSON-source session; `p` overrides any field (e.g. `session_id: 42` for a board-only session). */
export function rdp(p: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    session_id: "self",
    user: "hong",
    domain: "CORP",
    client_ip: "10.0.3.21",
    client_name: "HONG-LAPTOP",
    logon_at: "2026-11-04T13:00:00+09:00",
    connected_at: new Date().toISOString(),
    state: "active",
    ...p,
  };
}

/** Replaces the sessions file atomically (write a temp file, then rename), so a poll never reads half a file. */
export async function setSessions(s: BackendState, sessions: unknown[]): Promise<void> {
  const target = join(s.root, SESSIONS_FILE);
  const tmp = `${target}.tmp`;
  await writeFile(tmp, JSON.stringify({ sessions }), "utf-8");
  await rename(tmp, target);
}

/**
 * Logs every session off and waits until the server has applied it (the board lists none), so the
 * next spec never starts on a board that still shows this one's session (the file is polled).
 */
export async function clearSessions(s: BackendState, timeoutMs = 10_000): Promise<void> {
  await setSessions(s, []);
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const board = (await (await fetch(`${s.localUrl}/api/board`)).json()) as { sessions: unknown[] | null };
    if (board.sessions?.length === 0) return;
    if (Date.now() > deadline) throw new Error(`the board still lists ${JSON.stringify(board.sessions)} after ${timeoutMs} ms`);
    await new Promise((r) => setTimeout(r, 100));
  }
}

async function readLines(path: string): Promise<string[]> {
  try {
    return (await readFile(path, "utf-8")).split(/\r?\n/);
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw e;
  }
}

async function filesIn(dir: string, test: (name: string) => boolean): Promise<string[]> {
  try {
    return (await readdir(dir)).filter(test).sort().map((name) => join(dir, name));
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === "ENOENT") return [];
    throw e;
  }
}

/** Every notice the agents opened so far (`OPEN <id> <url>` lines of `<root>/run/agent-*.url`), oldest first. */
export async function noticeOpens(s: BackendState): Promise<{ id: number; url: string }[]> {
  const files = await filesIn(join(s.root, "run"), (n) => /^agent-\d+\.url$/.test(n));
  const opens: { id: number; url: string }[] = [];
  for (const file of files) {
    // only finished lines: the text after the last newline may still be being written
    for (const line of (await readLines(file)).slice(0, -1)) {
      const m = /^OPEN (\d+) (\S+)$/.exec(line);
      if (m) opens.push({ id: Number(m[1]), url: m[2] as string });
    }
  }
  return opens;
}

/** Waits until the agents have opened `n` notices in all and returns the `n`-th URL. */
export async function waitForNoticeUrl(s: BackendState, n: number, timeoutMs = 20_000): Promise<string> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const opens = await noticeOpens(s);
    if (opens.length >= n) return (opens[n - 1] as { url: string }).url;
    if (Date.now() > deadline) throw new Error(`timed out after ${timeoutMs} ms waiting for notice #${n} (${opens.length} opened)`);
    await new Promise((r) => setTimeout(r, 100));
  }
}

/** Every `<root>/logs/*.jsonl` line of category `cat`, in file order. */
export async function logEvents(s: BackendState, cat: string): Promise<Record<string, unknown>[]> {
  const files = await filesIn(join(s.root, "logs"), (n) => n.endsWith(".jsonl"));
  const out: Record<string, unknown>[] = [];
  for (const file of files) {
    const lines = await readLines(file);
    lines.forEach((line, i) => {
      if (!line.trim()) return;
      let e: Record<string, unknown>;
      try {
        e = JSON.parse(line) as Record<string, unknown>;
      } catch (err) {
        if (i === lines.length - 1) return; // the writer is still writing this last line
        throw err;
      }
      if (e.cat === cat) out.push(e);
    });
  }
  return out;
}
