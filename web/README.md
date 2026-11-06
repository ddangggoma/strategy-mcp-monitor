# web

Frontend for the MCP monitor: three Vite entries (`board.html`, `admin.html`, `notice.html`), React 19, TypeScript.

## Toolchain (Windows)

- Node **26.13.0 LTS** (`engines`: `>=26.13.0 <27`). This PC uses nvm-windows: `nvm install 26.13.0`, then `nvm use 26.13.0` (needs one UAC approval). nvm-windows ignores `.nvmrc`; the file is informational.
- pnpm is pinned in `packageManager` (corepack adds a `+sha512...` suffix; compare only the version prefix). Node 26 does not bundle corepack: `npm i -g corepack`, `corepack enable pnpm`. Set `COREPACK_ENABLE_DOWNLOAD_PROMPT=0` for non-interactive shells.
- All dependency versions are exact. `pnpm audit` must report no known vulnerabilities (the `minimatch` override in `pnpm-workspace.yaml` exists for that).

## Scripts

`pnpm dev | build | typecheck | lint | test | test:budget | e2e | audit`

- `test:budget` reads `dist/`, so run `pnpm build` first.
- `pnpm e2e` runs Playwright against the real backend (`e2e/backend.ts`): `globalSetup` starts `uv run python -m app` on a throwaway root with two free loopback ports (local, external) and the dummy MCP on the fixed port 47815 (a free one only if that is taken), `--external-host 127.0.0.1` and the dev OTP code, seeds an Admin, a developer, four UI-login users and the `calculator` dummy MCP, and signs each (user, channel) pair in once; `globalTeardown` stops the MCP, kills the server and deletes the root. Before it: `pnpm build` (it serves `dist/`), `uv sync` in `dummy-mcps/`, and `UV_EXE=<path to uv.exe>` when `uv` is not on PATH. `MCPMON_E2E_ROOT=<dir>` uses (and keeps) a fixed root; `MCPMON_E2E_KEEP=1` keeps the temporary one (server output: `<root>/backend.out.log`).
- The suite is serial and order-dependent on purpose: one backend, and the login budgets (see `e2e/backend.ts`) allow each UI-login email once per run. The visual baselines (`e2e/visual.spec.ts-snapshots/`, projects `chromium-dark` and `chromium-light`) do not depend on that order: the spec answers the history-dependent reads (recent activity, notice versions) with fixed data and the MCP port is fixed, so `pnpm e2e e2e/visual.spec.ts` alone and a full run compare against the same images. Update them with `pnpm e2e e2e/visual.spec.ts --update-snapshots=all`, then open each PNG before committing.

## Windows app control

Checked on this PC (Task 1): `node`, `pnpm`, rolldown (Vite 8 bundler, native binding), Vitest, and Playwright's Chromium all run directly; no launcher was blocked and no `node node_modules/...` workaround or `channel: "msedge"` fallback was needed. If a launcher is blocked later, run the package entry with node directly, e.g. `node node_modules/vite/bin/vite.js build`.
