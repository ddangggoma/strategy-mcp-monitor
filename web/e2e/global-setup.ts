import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import {
  AUTH_DIR,
  ADMIN_EMAIL,
  DEV_EMAIL,
  STATE_FILE,
  loginWithFixedCode,
  startBackend,
  stopBackend,
  type ChannelName,
  type SavedSession,
  type Who,
} from "./backend";

/**
 * Starts the backend, then signs in (admin | dev) x (local | external) once each and stores the
 * cookies under e2e/.auth/ (see backend.ts for the login budgets this avoids). These sessions are
 * never logged out during the run.
 */
export default async function globalSetup(): Promise<void> {
  const { state, adminLocal } = await startBackend();
  try {
    const sessions: Record<`${Who}-${ChannelName}`, SavedSession> = {
      "admin-local": adminLocal,
      "admin-external": await loginWithFixedCode(state.externalUrl, "external", ADMIN_EMAIL),
      "dev-local": await loginWithFixedCode(state.localUrl, "local", DEV_EMAIL),
      "dev-external": await loginWithFixedCode(state.externalUrl, "external", DEV_EMAIL),
    };
    await mkdir(AUTH_DIR, { recursive: true });
    for (const [key, session] of Object.entries(sessions)) {
      await writeFile(join(AUTH_DIR, `${key}.json`), JSON.stringify(session, null, 2));
    }
    await writeFile(STATE_FILE, JSON.stringify(state, null, 2));
  } catch (e) {
    await stopBackend(state, adminLocal);
    throw e;
  }
}
