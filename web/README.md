# web

Frontend for the MCP monitor: three Vite entries (`board.html`, `admin.html`, `notice.html`), React 19, TypeScript.

## Toolchain (Windows)

- Node **26.13.0 LTS** (`engines`: `>=26.13.0 <27`). This PC uses nvm-windows: `nvm install 26.13.0`, then `nvm use 26.13.0` (needs one UAC approval). nvm-windows ignores `.nvmrc`; the file is informational.
- pnpm is pinned in `packageManager` (corepack adds a `+sha512...` suffix; compare only the version prefix). Node 26 does not bundle corepack: `npm i -g corepack`, `corepack enable pnpm`. Set `COREPACK_ENABLE_DOWNLOAD_PROMPT=0` for non-interactive shells.
- All dependency versions are exact. `pnpm audit` must report no known vulnerabilities (the `minimatch` override in `pnpm-workspace.yaml` exists for that).

## Scripts

`pnpm dev | build | typecheck | lint | test | test:budget | e2e | audit`

- `test:budget` reads `dist/`, so run `pnpm build` first.
- `pnpm e2e --project smoke` serves `dist/` with `vite preview` on 127.0.0.1:4173 (loopback IPv4 explicitly: `localhost` resolves to `::1` only and the Playwright URL check never succeeds).

## Windows app control

Checked on this PC (Task 1): `node`, `pnpm`, rolldown (Vite 8 bundler, native binding), Vitest, and Playwright's Chromium all run directly; no launcher was blocked and no `node node_modules/...` workaround or `channel: "msedge"` fallback was needed. If a launcher is blocked later, run the package entry with node directly, e.g. `node node_modules/vite/bin/vite.js build`.
