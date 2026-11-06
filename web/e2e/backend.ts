/**
 * The real backend for the E2E suite (U24): a throwaway data root, three free loopback ports, the
 * server started through `uv run python -m app`, and a small seed made through the Local API.
 *
 * Login budgets on the server (all E2E traffic comes from 127.0.0.1, so every budget is shared):
 *   - OTP request: 10 per IP per 10 min, and 60 s cooldown per email.
 *   - OTP verify: 30 per IP per 10 min (every call counts, success or not).
 *   - A requested code row accepts 5 attempts; after that even the dev fixed code fails for that
 *     email until a new code is requested (no code row at all: the fixed code passes directly).
 *   - 10 failed verifies per email per hour lock that email.
 * So: globalSetup signs in each (user, channel) pair once with the fixed code and no request, and
 * the tests reuse those cookies; each test that logs in through the UI uses its own seeded email
 * (`UI_USERS`), so no email ever meets the cooldown or the 5-attempt rule twice.
 */
import { spawn } from "node:child_process";
import { execFile } from "node:child_process";
import { closeSync, existsSync, openSync } from "node:fs";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

export const WEB_DIR = resolve(fileURLToPath(new URL("..", import.meta.url)));
export const REPO_DIR = resolve(WEB_DIR, "..");
export const SERVER_DIR = join(REPO_DIR, "server");
export const DUMMY_MCPS_DIR = join(REPO_DIR, "dummy-mcps");
export const DIST_DIR = join(WEB_DIR, "dist");
export const STATE_FILE = join(WEB_DIR, "e2e", ".state.json");
export const AUTH_DIR = join(WEB_DIR, "e2e", ".auth");
/** The JSON session source in the data root (`--session-source json:`), rewritten by e2e/sessions.ts. */
export const SESSIONS_FILE = "sessions.json";

export const DEV_OTP_CODE = "246810";
export const ADMIN_EMAIL = "admin@e2e.test";
export const DEV_EMAIL = "dev@e2e.test";
export const MCP_NAME = "calculator";

/** One seeded user per UI-login test (F05): none of them is ever signed in twice. */
export const UI_USERS = {
  login: { email: "ui1@e2e.test", name: "UI 로그인", role: "admin" },
  wrongCode: { email: "ui2@e2e.test", name: "UI 오답", role: "developer" },
  logout: { email: "ui3@e2e.test", name: "UI 로그아웃", role: "admin" },
  keyboard: { email: "ui4@e2e.test", name: "UI 키보드", role: "admin" },
} as const;
export type UiUser = keyof typeof UI_USERS;

export type Who = "admin" | "dev";
export type ChannelName = "local" | "external";

export interface BackendState {
  root: string;
  localUrl: string;
  externalUrl: string;
  pid: number;
  mcpId: number;
  mcpPort: number;
  adminEmail: typeof ADMIN_EMAIL;
  devEmail: typeof DEV_EMAIL;
  /** KST days of the log files written before the server starts: [older, newer] (see seedOldLogs). */
  oldLogDays: [string, string];
}

/** What `.auth/<who>-<channel>.json` holds: the session cookie and its CSRF token. */
export interface SavedSession {
  cookie: { name: string; value: string };
  csrf: string;
}

const SESSION_COOKIE: Record<ChannelName, string> = { local: "mcpmon_sid_local", external: "mcpmon_sid_ext" };

const STARTUP_TIMEOUT_MS = 30_000;
const STATE_TIMEOUT_MS = 30_000;

async function freePort(): Promise<number> {
  return new Promise((ok, fail) => {
    const srv = createServer();
    srv.once("error", fail);
    srv.listen(0, "127.0.0.1", () => {
      const addr = srv.address();
      const port = typeof addr === "object" && addr !== null ? addr.port : 0;
      srv.close(() => ok(port));
    });
  });
}

async function freePorts(n: number): Promise<number[]> {
  const ports = new Set<number>();
  while (ports.size < n) ports.add(await freePort());
  return [...ports];
}

/**
 * The MCP's port shows on screen (list, detail, settings form), so the visual baselines need the
 * same number every run: a fixed port, or a free one only when something else holds it.
 */
export const MCP_PORT = 47815;

async function portIsFree(port: number): Promise<boolean> {
  return new Promise((ok) => {
    const srv = createServer();
    srv.once("error", () => ok(false));
    srv.listen(port, "127.0.0.1", () => srv.close(() => ok(true)));
  });
}

async function mcpPortAvoiding(taken: number[]): Promise<number> {
  if (!taken.includes(MCP_PORT) && (await portIsFree(MCP_PORT))) return MCP_PORT;
  for (;;) {
    const p = await freePort();
    if (!taken.includes(p)) return p;
  }
}

async function pollUntil<T>(what: string, timeoutMs: number, probe: () => Promise<T | undefined>): Promise<T> {
  const deadline = Date.now() + timeoutMs;
  let lastError: unknown = null;
  while (Date.now() < deadline) {
    try {
      const value = await probe();
      if (value !== undefined) return value;
    } catch (e) {
      lastError = e;
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error(`timed out after ${timeoutMs} ms waiting for ${what}${lastError ? ` (last error: ${String(lastError)})` : ""}`);
}

/** A minimal cookie+CSRF client for the seed and for teardown (no browser involved). */
export class ApiClient {
  constructor(
    readonly baseUrl: string,
    readonly session: SavedSession | null = null,
  ) {}

  async call(method: string, path: string, body?: unknown): Promise<Response> {
    const headers: Record<string, string> = {};
    if (this.session) {
      headers.Cookie = `${this.session.cookie.name}=${this.session.cookie.value}`;
      headers["X-CSRF-Token"] = this.session.csrf;
    }
    if (body !== undefined) headers["Content-Type"] = "application/json";
    return fetch(`${this.baseUrl}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  }

  async json<T>(method: string, path: string, body?: unknown, expected = [200, 201, 202]): Promise<T> {
    const res = await this.call(method, path, body);
    const text = await res.text();
    if (!expected.includes(res.status)) throw new Error(`${method} ${path} -> ${res.status} ${text}`);
    return (text ? JSON.parse(text) : {}) as T;
  }
}

/**
 * Signs `email` in on `baseUrl` with the dev fixed code. No code is requested first: without a
 * code row the server accepts the fixed code directly, which costs one verify and no request.
 */
export async function loginWithFixedCode(baseUrl: string, channel: ChannelName, email: string): Promise<SavedSession> {
  const res = await fetch(`${baseUrl}/api/auth/otp/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, code: DEV_OTP_CODE }),
  });
  if (res.status !== 200) throw new Error(`login ${email} on ${channel} -> ${res.status} ${await res.text()}`);
  const { csrf_token } = (await res.json()) as { csrf_token: string };
  const name = SESSION_COOKIE[channel];
  const cookie = res.headers
    .getSetCookie()
    .map((c) => c.split(";")[0] ?? "")
    .find((c) => c.startsWith(`${name}=`));
  if (!cookie) throw new Error(`login ${email} on ${channel}: no ${name} cookie`);
  return { cookie: { name, value: cookie.slice(name.length + 1) }, csrf: csrf_token };
}

interface BoardItem {
  id: number;
  state: string;
}

export async function waitForState(api: ApiClient, mcpId: number, state: string, timeoutMs = STATE_TIMEOUT_MS): Promise<void> {
  await pollUntil(`MCP ${mcpId} to reach ${state}`, timeoutMs, async () => {
    const board = await api.json<{ mcps: BoardItem[] }>("GET", "/api/board");
    return board.mcps.find((m) => m.id === mcpId)?.state === state ? true : undefined;
  });
}

async function readScript(kind: "start" | "stop" | "restart"): Promise<string> {
  const text = await readFile(join(DUMMY_MCPS_DIR, "examples", `${kind}.ps1`), "utf-8");
  return text.startsWith("﻿") ? text.slice(1) : text; // utf-8-sig
}

function killTree(pid: number): Promise<void> {
  return promisify(execFile)("taskkill", ["/PID", String(pid), "/T", "/F"]).then(
    () => undefined,
    () => undefined, // already gone
  );
}

/**
 * Safety net: any process still running from the root (a dummy MCP the stop step missed). The
 * dummy is started through Start-Process, so it is not in the server's process tree.
 */
function killStragglers(root: string): Promise<void> {
  const literal = root.replaceAll("'", "''");
  const script =
    `Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine.Contains('${literal}') -and $_.ProcessId -ne $PID } | ` +
    "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }";
  return promisify(execFile)("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", script]).then(
    () => undefined,
    () => undefined,
  );
}

const DAY_MS = 86_400_000;
const KST_OFFSET_MS = 9 * 3_600_000; // no daylight saving time in Korea

/** The KST calendar day `days` before today, `YYYY-MM-DD` (the log file name). */
export function kstDaysAgo(days: number, now = Date.now()): string {
  return new Date(now + KST_OFFSET_MS - days * DAY_MS).toISOString().slice(0, 10);
}

/** Days before today of the two seeded log files: older and newer. */
export const OLD_LOG_AGES = [100, 30] as const;

/**
 * Writes `<root>/logs/<day>.jsonl` with three `system` lines for each of OLD_LOG_AGES before the
 * server starts (retention.spec purges the older one). Both stay inside the default 180-day
 * retention, so the server's own startup retention run (60 s after start, F05) leaves them alone;
 * retention.spec's 60 days deletes only the older one.
 */
async function seedOldLogs(root: string): Promise<[string, string]> {
  const logs = join(root, "logs");
  await mkdir(logs, { recursive: true });
  const days = OLD_LOG_AGES.map((age) => kstDaysAgo(age)) as [string, string];
  for (const day of days) {
    const lines = [1, 2, 3].map((n) =>
      JSON.stringify({ ts: `${day}T09:0${n}:00.000+09:00`, cat: "system", event: "e2e.seed", n }),
    );
    await writeFile(join(logs, `${day}.jsonl`), `${lines.join("\n")}\n`, "utf-8");
  }
  return days;
}

/** Starts the server on a fresh root and seeds it. On any failure the process is killed. */
export async function startBackend(): Promise<{ state: BackendState; adminLocal: SavedSession }> {
  if (!existsSync(join(DIST_DIR, "board.html"))) throw new Error(`no built web app in ${DIST_DIR}: run \`pnpm build\` first`);
  if (!existsSync(join(DUMMY_MCPS_DIR, ".venv", "Scripts", "python.exe")))
    throw new Error(`no dummy-mcps venv: run \`uv sync\` in ${DUMMY_MCPS_DIR}`);

  const root = process.env.MCPMON_E2E_ROOT ?? (await mkdtemp(join(tmpdir(), "mcpmon-e2e-")));
  await mkdir(root, { recursive: true });
  const [localPort, externalPort] = (await freePorts(2)) as [number, number];
  const mcpPort = await mcpPortAvoiding([localPort, externalPort]);
  const localUrl = `http://127.0.0.1:${localPort}`;
  const externalUrl = `http://127.0.0.1:${externalPort}`;
  const sessionsFile = join(root, SESSIONS_FILE);
  await writeFile(sessionsFile, JSON.stringify({ sessions: [] }), "utf-8");
  const oldLogDays = await seedOldLogs(root);

  // a file, not a pipe: the dummy MCP the server starts inherits these handles, and a pipe it keeps
  // open would hold the test runner open after the server is gone
  const out = openSync(join(root, "backend.out.log"), "a");
  const child = spawn(
    process.env.UV_EXE ?? "uv",
    [
      "run", "python", "-m", "app",
      "--root", root,
      "--local-port", String(localPort),
      "--external-port", String(externalPort),
      // F36: the fixed code must never be reachable from the network
      "--external-host", "127.0.0.1",
      "--dev-otp-code", DEV_OTP_CODE,
      "--static-dir", DIST_DIR,
      // RDP sessions come from a file the tests rewrite (e2e/sessions.ts), never from this PC's
      // own sessions; "self" sessions get the real agent, which prints each notice URL to
      // <root>/run/agent-<session id>.url instead of opening Edge. No process/command collection.
      "--session-source", `json:${sessionsFile}`,
      "--agent-launcher", "local",
      "--agent-dialog", "print",
      "--activity", "off",
    ],
    {
      cwd: SERVER_DIR,
      env: { ...process.env, DUMMY_MCPS_DIR, DUMMY_MCP_RUN_DIR: join(root, "run") },
      stdio: ["ignore", out, out],
      windowsHide: true,
    },
  );
  closeSync(out); // the child has its own copy
  child.unref();
  const pid = child.pid;
  if (pid === undefined) throw new Error("could not start the backend (no pid)");
  let exited: number | null = null;
  child.once("exit", (code) => (exited = code ?? -1));

  try {
    for (const url of [localUrl, externalUrl]) {
      await pollUntil(`${url}/api/channel`, STARTUP_TIMEOUT_MS, async () => {
        if (exited !== null) throw new Error(`backend exited with ${exited}; see ${join(root, "backend.out.log")}`);
        const res = await fetch(`${url}/api/channel`);
        return res.ok ? true : undefined;
      });
    }

    const anon = new ApiClient(localUrl);
    await anon.json("POST", "/api/bootstrap", { email: ADMIN_EMAIL, name: "E2E Admin" });
    const adminLocal = await loginWithFixedCode(localUrl, "local", ADMIN_EMAIL);
    const admin = new ApiClient(localUrl, adminLocal);

    await admin.json("POST", "/api/users", { email: DEV_EMAIL, name: "E2E Developer", role: "developer" });
    for (const u of Object.values(UI_USERS)) await admin.json("POST", "/api/users", u);

    const mcp = await admin.json<{ id: number }>("POST", "/api/mcps", {
      name: MCP_NAME,
      host: "127.0.0.1",
      port: mcpPort,
      expected_process_name: "python.exe",
      action_delay_sec: 1,
      startup_grace_sec: 1,
      script_timeout_sec: 30,
      scripts: {
        start: { ext: ".ps1", content: await readScript("start") },
        stop: { ext: ".ps1", content: await readScript("stop") },
        restart: { ext: ".ps1", content: await readScript("restart") },
      },
    });
    await admin.json("POST", `/api/mcps/${mcp.id}/actions/start`);
    await waitForState(admin, mcp.id, "HEALTHY");

    const state: BackendState = {
      root, localUrl, externalUrl, pid, mcpId: mcp.id, mcpPort, adminEmail: ADMIN_EMAIL, devEmail: DEV_EMAIL, oldLogDays,
    };
    return { state, adminLocal };
  } catch (e) {
    await killTree(pid);
    await killStragglers(root);
    throw e;
  }
}

/** Stops the MCP (so no dummy process outlives the run), kills the server tree, removes the root. */
export async function stopBackend(s: BackendState, adminLocal: SavedSession | null): Promise<void> {
  try {
    if (adminLocal) {
      const admin = new ApiClient(s.localUrl, adminLocal);
      // 409 action_in_progress: a test's action is still running; ask again once it settles
      await pollUntil("the stop action to be accepted", STATE_TIMEOUT_MS, async () => {
        const res = await admin.call("POST", `/api/mcps/${s.mcpId}/actions/stop`);
        if (res.status === 202) return true;
        if (res.status !== 409) throw new Error(`stop -> ${res.status} ${await res.text()}`);
        return undefined;
      });
      await waitForState(admin, s.mcpId, "MAINTENANCE");
    }
  } finally {
    await killTree(s.pid);
    await killStragglers(s.root);
    if (!process.env.MCPMON_E2E_ROOT && !process.env.MCPMON_E2E_KEEP) {
      // the killed processes may hold log files for a moment
      await rm(s.root, { recursive: true, force: true, maxRetries: 10, retryDelay: 500 });
    }
  }
}
