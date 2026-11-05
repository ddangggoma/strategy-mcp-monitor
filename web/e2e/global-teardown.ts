import { existsSync } from "node:fs";
import { readFile, rm } from "node:fs/promises";
import { join } from "node:path";
import { AUTH_DIR, STATE_FILE, stopBackend, type BackendState, type SavedSession } from "./backend";

export default async function globalTeardown(): Promise<void> {
  if (!existsSync(STATE_FILE)) return; // setup failed and already cleaned up
  const state = JSON.parse(await readFile(STATE_FILE, "utf-8")) as BackendState;
  const authFile = join(AUTH_DIR, "admin-local.json");
  const admin = existsSync(authFile) ? (JSON.parse(await readFile(authFile, "utf-8")) as SavedSession) : null;
  try {
    await stopBackend(state, admin);
  } finally {
    await rm(STATE_FILE, { force: true });
    await rm(AUTH_DIR, { recursive: true, force: true });
  }
}
