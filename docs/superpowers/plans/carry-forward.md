# Carry-forward items from completed plans

Every later plan reads this file before it is written and checks off the items it covers.

## From Plan 1 (core service & auth)

### Plan 2 (MCP monitoring backend)
- [x] **(Important, do in Plan 2 Task 1)** The External User-Agent header has no length limit. `AuditLogger.auth()`/`admin()` and `SessionStore.create` store the raw User-Agent. The httptools parser has no header-size limit, so an anonymous request can still fill the disk. (Plan 2 Task 1)
  - Cap `user_agent` at 512 characters in `AuditLogger` and `SessionStore.create`.
  - Add `extra="forbid"` to `OtpRequestBody`/`OtpVerifyBody`.
  - Consider a request body-size limit middleware (for example 64 KB).
- [x] The audit throttle key is (event, ip). After one per-email cooldown 429, later 429s for other emails from the same IP go unrecorded for 10 minutes. Consider keying by (event, ip, email-hash). (Plan 2 Task 1)
- [x] Remove the global `pydantic.ValidationError` → 422 handler (`app_factory.py`). Use `ApiError(422)` in the settings route instead, so server-side model bugs return 500, not a client 422. Also handle a corrupt stored settings row. (Plan 2 Task 2)
- [x] `Database.transaction()`: raise `RuntimeError` when a transaction is already open (`in_transaction`) to prevent re-entry within the same thread. (Plan 2 Task 2)
- [x] `can()` hardening: (Plan 2 Task 2)
  - normalize an inactive user to `None` up front;
  - type `Rule.min_role` as `Role | None`;
  - check the channel with `get_args(Channel)`;
  - freeze `RULES` with `MappingProxyType`.
  - Do this when DELETE_MCP and EDIT_SCRIPTS get wired to routes.
- [x] Align the spec text: (Plan 2 Task 14, docs/PLAN.md v0.5)
  - §4.4 `can(user, action, resource, channel)` should read `can(user, action, channel, owner_id)`;
  - §8 `PUT /api/users` should read `PATCH /api/users/{id}`.
- [x] `Database.execute()` returns `lastrowid`, which is meaningless for non-INSERT statements. Document this, or add `rowcount`. (Plan 2 Task 2: documented, `execute_rowcount` added)
- [x] Run ruff and mypy once (install them as dev dependencies). (Plan 2 Task 14: both clean; config in `server/pyproject.toml`)

### Plan 3 (Web UI)
- [x] Lowering only the retention period below `log_compress_after_days` returns 422. The UI must explain that both values have to be lowered together. (Plan 3 Task 13)
- [x] Both ports use the same cookie name (`mcpmon_sid`), and browser cookies are scoped by host, not port. Logging in on one channel overwrites the other channel's cookie. Consider per-channel cookie names. (Plan 3 Task 3)
- [x] Show an OTP lockout message: up to 1 hour after 10 failures. Optionally clear the failure history after a successful login. (Plan 3 Task 3, 9)
- [x] Read the CSRF token from `GET /api/auth/me` (added in the Plan 1 final fixes). (Plan 3 Task 7)
- [x] (From Plan 2) The board is `GET /api/board` plus the SSE events `board` / `mcp` / `mcp_removed` / `action` on `GET /api/stream`. (Plan 3 Task 7, 8)
- [x] (From Plan 2) A manual action returns 202 + `run_id`; show the result toast from the `action` event (signed-in developer+ only; anonymous streams never get `action` events). (Plan 3 Task 10)
- [x] (From Plan 2) Compute script diffs in the client from the versions API content (`GET .../scripts/{kind}/versions[/{version}]`). (Plan 3 Task 12)
- [x] (From Plan 2) The anonymous board omits host:port, owner and config; those come from `GET /api/mcps[/{id}]` (developer+). (Plan 3 Task 8)
- [x] (From Plan 2) An SSE stream keeps the auth level it connected with: after logout, close and reopen `/api/stream`. (Plan 3 Task 7, 9)

### Plan 4 (Windows collection)
- [x] `LogWriter.emit()` is loop-thread only. Collector threads must go through `loop.call_soon_threadsafe`. (Plan 4 Task 1)
- [x] Collectors need an event-time override for `ts`: `emit` currently ignores a caller-supplied `ts`. (Plan 4 Task 1)
- [x] Once a second process (agent or collector) opens `config.db`, cross-process contention can block the event loop for up to 5 s (`busy_timeout`). Move DB access off the loop or keep the second process off `config.db`. (Plan 4 Task 7, 15: bookmarks in `data/collector-state.json`; the agent speaks HTTP only and never opens `config.db`)
- [x] Record the localhost login's Windows account (spec §4.1.5). (Plan 4 Task 2)
- [x] (From Plan 2) Add `sessions` to `GET /api/board` and to the SSE board events. (Plan 4 Task 5)

### Plan 5 (log viewer, retention, packaging)
- [ ] Reader and indexer:
  - split JSONL on `\n` only, because U+2028/2029 can appear raw inside a line;
  - tolerate duplicate lines from a mid-batch retry that spans two days.
- [ ] Retention job:
  - purge expired `auth_sessions` rows;
  - purge `otp_codes` rows for unknown emails;
  - purge old `otp_failures` and `otp_verify_ip` rows.
  - Note the timestamp formats differ: `users` and `auth_sessions` store UTC microseconds, the OTP tables store KST milliseconds.
- [ ] `LogWriter.stop()`: warn about discarded events on a failing disk, handle cancellation safely, and bound the queue during an outage.
- [ ] Windows service host:
  - `serve()` needs an Event-based stop hook when it runs off the main thread;
  - a busy port currently exits with code 3 plus a CancelledError traceback, so exit cleanly;
  - pin the root path explicitly (the service's cwd is System32);
  - `build_services` leaks the DB handle when startup fails.
- [ ] Database upgrade story:
  - reject a database newer than the code;
  - read `user_version` inside the transaction;
  - verify WAL mode is active.
- [ ] Packaging:
  - pin `.python-version` to the exact patch;
  - add PyInstaller hiddenimports for httptools, websockets and watchfiles;
  - switch back to `uvicorn[standard]` once pyyaml has a cp315 wheel.
- [ ] e2e test: assert `lp != ep`, assert the POST statuses, and set `stdin=DEVNULL`.
- [ ] (From Plan 2) ACL on `scripts/` (SYSTEM + Administrators only; spec §5.8).
- [ ] (From Plan 2) Retention purge for `mcp_actions` and `mcp_transitions` (`mcp_minutes` already has an hourly purge).
- [ ] (From Plan 2) Apply the service start type (auto, delayed) from the global settings.
- [ ] (From Plan 2) Service stop: `Monitor.stop()` abandons a still-running script after 10 s (the script process keeps running); decide whether the service host should wait longer or kill the tree.

### Later
- [ ] (From Plan 2) `Alert` effects (alert-only issues, FAILED) only write an `mcp.health` log line; a notification channel (spec §14) is needed.
- [ ] (From Plan 2) `E501` is not enforced (about 80 app lines exceed the configured 100 columns); enforce it or run `ruff format` once.

### Later (real OTP provider)
- [ ] A `provider.send` failure distinguishes registered emails (enumeration), and sending inline creates a timing difference. Move sending off the request path, and make failures behave the same either way.

## From the Plan 2 whole-plan review

### Plan 3 (Web UI)
- [x] An SSE stream's auth level is fixed at connect time, so a logout does not cut a live stream. The UI should reconnect the stream on login and logout. The server could also re-check the auth level periodically. (Plan 3 Task 9)
- [x] A client that loses the race for the last stream slot gets an empty 200 instead of 503. Make the UI's EventSource reconnect with backoff. (Plan 3 Task 7)
- [x] The per-IP stream cap is 5, and on the local channel every browser on the PC shares 127.0.0.1. Keep each tab to one stream, and consider raising the cap for loopback. (Plan 3 Task 3, 7)
- [x] MCP detail always includes `config_error` (true/false), and an invalid row has `live: null`. Show an "invalid config — rename or delete" state. (Plan 3 Task 11)
- [x] MCP names are now allowlisted: Unicode letters and digits, space, `.`, `_`, `-`. Explain this in the form's validation text. (Plan 3 Task 11)
- [x] Manual action returns 202 `{run_id}`, and the result arrives as an SSE `action` event that only authenticated users receive. A concurrent request returns 409 `action_in_progress`. (Plan 3 Task 10)

### Plan 5 (log viewer, retention, packaging)
- [ ] FAILED status and the auto-action budget reset on service restart. Decide whether to persist them.
- [ ] The runner path where a timeout kill fails is untested. The next run can start while the old script is still alive. Log it, and add a test.
- [ ] BodySizeLimit: log the exception it swallows after rejecting a request, and fill the test gaps (bad_host combined with oversize, a single 413, websocket passthrough).
- [ ] The script store calls `os.replace` before COMMIT, so a COMMIT failure leaves the file changed. Use the run-time hash check, or reorder.
- [ ] At loop shutdown, the script is killed but its children are not. The "Task was destroyed but it is pending" message is cosmetic.
- [ ] Add retention for the MCP action and transition tables.
- [ ] If the defensive `_apply` refusal ever fires, it is settled as an error that consumes a budget slot. It is unreachable today. Consider an engine-side cancel.

### Later
- [ ] E501 is not enforced (about 80 lines over 100 columns), and ruff is pinned to `E4,E7,E9,F,I,UP,B`.
- [ ] Add a unit test for the `--open-meteo` wiring.
- [ ] `MCP_ACTOR` (the user email) is not allowlisted for script env vars. Only an admin registers emails, but consider tightening email validation.

## From Plan 3 (web UI)

### Plan 4 (Windows collection)
- [x] The board `sessions` field and the SSE `sessions` event (`{sessions}`, a full replacement) fill exactly the keys of `RdpSession` in `web/src/lib/api-types.ts`. Without the field the UI shows the "not collected yet" line (`board.sessionsNotReady`: "원격 접속 정보는 다음 업데이트부터 표시돼요."). (Plan 4 Task 4, 5, 17)
- [x] Replace the notice bundle's `loadNoticeContent()` and `notifyHost()` (U16) with the agent path. (Plan 4 Task 17)
- [x] The notice version recorded in `notice_shown` is `NoticeStore.current().version` (0 = the built-in text). (Plan 4 Task 11)
- [x] The dashboard "현재 세션" card uses the same sessions data. (Plan 4 Task 18)

### Plan 5 (log viewer, retention, packaging)
- [ ] The retention purge must use `app.logstore.retention.retention_cutoff`, so it matches the settings preview.
- [x] Fill the sessions navigation item and the dashboard "우회 탐지 이벤트" card. (Plan 4 Task 18)
- [ ] Fill the logs and audit-log navigation items and the dashboard "로그인 실패 추이" card (still `PlannedFeature`).
- [ ] The log table uses TanStack Virtual and no animation.
- [ ] PyInstaller packaging: change the `--static-dir` default (now `<repo>/web/dist`) to a path relative to the executable.

### Later
- [ ] Server 422 responses carry no field information, so forms rely on client validation (U27).
- [ ] Script `PUT` has no optimistic locking (`If-Match`).

## From the Plan 3 whole-plan review

### Plan 5 (log viewer, retention, packaging)
- [ ] Every SSE `action` event refetches all of that MCP's active history windows (1 h, 24 h, 7 d), because the history response carries buckets, transitions and actions together. Add an actions-only history read (or an `actions` field the client can merge), then refetch only the action list.
- [ ] After a `session_changed` error (another tab switched the shared cookie to another user), the editors (`ScriptEditor`, `NoticeEditorPage`, `McpCreatePage`) keep the previous user's edits on screen. The next change stores them as the new user's draft, and a second Save writes as the new user. Treat `session_changed` like a user switch: `clearAllDrafts()`, `qc.clear()`, then navigate to `/admin` with `ignoreBlocker: true` (or reload).
- [ ] Dependency allowlist wording: name the implied toolchain packages (`@types/node`, `@types/react*`, `@vitejs/plugin-react`, `@tailwindcss/vite`, `vite`, `typescript`). If Chromium 123 is a real target, verify the computed colour of the `-soft` tokens there (`light-dark()` inside `color-mix()`).
- [ ] `server/tests/test_e2e_serve.py::test_two_channels_live` is load-sensitive: it failed once with "server did not become ready" while vitest ran at the same time, and passes alone. Raise its 10 s readiness deadline, or run the two suites one after the other in CI.

### Later
- [ ] Some web unit tests still sleep 30–50 ms before asserting that something does *not* arrive (no toast later in `mcps.test`, no tooltip on a wide window in `shell.test`, an older refetch in `scripts.test`, `status.test`). There is no signal to wait on; replace them if one appears.

## From Plan 4 (Windows collection)

### Plan 5 (log viewer, retention, packaging)
- [ ] Retention purge also covers `rdp_connections`, `rdp_logon_failures` and `notice_displays` (V29). Before deleting a log file, call `TamperScanner.expect_log_removed(name)`; otherwise the scanner reports a `log_file_removed` tamper event.
- [ ] The Windows service host calls `SessionCollector.nudge()` (reachable as `SessionsComponent.nudge()` in `app/collect/manager.py`) on `SERVICE_CONTROL_SESSIONCHANGE`, so a session change is picked up at once instead of at the next 0.5 s poll (V6).
- [ ] The Windows service stop must go through `ShutdownSequence.request` (`server/app/main.py`), like Ctrl+C does today: the collectors stop first, so the agent supervisor can still deliver `exit` over the Local channel and each agent closes its Edge notice window, and only then the HTTP servers.
- [ ] Packaging the agent: if PyInstaller builds `mcp-agent.exe`, set `AgentOptions.python` and the launch `argv` to that executable (instead of `<python> -m mcp_agent` with `PYTHONPATH`). Whatever runs the agent must be readable by every user session: today `AgentOptions.python` is the server venv's base interpreter, which uv installs under the installing user's `%APPDATA%\uv\python`, out of reach of a standard user's session under `WtsLauncher`. Every agent launch must pass both `MCPMON_AGENT_TOKEN` and `MCPMON_AGENT_SERVER_KEY` (32-byte hex) in the environment (the agent removes both at once); an agent started by hand without the key exits at argument parsing (exit 2).
- [ ] `install.ps1` enables the audit policy and registry values the collectors need: `auditpol` Process Creation (success), Logon (success, failure), Logoff (success), Other Logon/Logoff Events (success), Audit Policy Change (success); `ProcessCreationIncludeCmdLine_Enabled = 1`; `EnableScriptBlockLogging = 1` (commands in `docs/verification/win11-pro-p4-p5.md` §1).
- [ ] Uninstall removes `data/collector-state.json` and each user's Edge notice profile folder (`%LOCALAPPDATA%\mcp-monitor\notice-edge`).
- [ ] Tamper baselines (script hashes, log file sizes, audit registry values) live in memory only, so a change made while the service is stopped is not reported. Persist the baseline or compare against the last known state at startup.
- [ ] Log viewer: filters for the `session`, `notice`, `activity.*` and `tamper` categories, and the dashboard "로그인 실패 추이" card (source: `rdp_logon_failures`).
- [ ] Move the agent launch and kill off the event loop (`asyncio.to_thread`, as `stop()` already does): `AgentSupervisor` calls `PopenProcess.kill` (`taskkill`, up to 5 s) and `WtsLauncher.launch` (`CreateEnvironmentBlock` + `CreateProcessAsUser`) on the loop from `forget`, `_tick_alive` and `_launch` (`server/app/activity/agent_supervisor.py`, `server/app/win/launch.py`). The production `HandleProcess.kill` is a bare `TerminateProcess` and the launch takes milliseconds, so only the dev `LocalLauncher` blocks today (review M14).
- [ ] Live updates on the sessions screen: "현재 세션" refetches only when the board's active session list changes, so a disconnected session that logs off stays in the table until another change, and the connection history never updates live (`web/src/admin/live.ts`, SessionsPage). Also invalidate both on any `sessions` SSE event and on `Closed` (needs a small server signal; review M16).
- [ ] Report the agent's dropped window events: `EventSender.dropped` (buffer overflow, batches the server refused) never reaches the server. Send the count with the next batch, or as a `collector.dropped`-style line (needs an events-schema change; review M13, the part the fix wave left).

### Later
- [ ] A notification channel for tamper events (toast, mail, webhook; spec §14). Today they are logged, shown on the dashboard card and sent as SSE `tamper` to signed-in developers.
- [ ] GeoIP for client IPs (spec §5.3, optional).
- [ ] Apply the notice text to the Windows pre-logon legal notice (`legalnoticecaption`/`legalnoticetext`; spec §5.5 optional, V33).
- [ ] Make the notice window a true modal: replace the Edge `--app` `NoticeWindow` with a WebView2 host (pywebview), V3.
- [ ] A WTS session-notification window (`WTSRegisterSessionNotification`) instead of, or next to, the 0.5 s poll (V6), if the real machine misses the 2-second target.
- [ ] Close the last window-events gap with proof and data on one connection: today `verified_only` checks a flag and then opens a new TCP connection, so a batch whose check passed just before the service died can reach whatever owns the port at connect time (at most one batch of one user's window titles, only when the service crashes). Keep one keep-alive `http.client.HTTPConnection` for events, send a proven request on it (heartbeat, or an empty `POST /api/agent/events`), then the batch on the same connection (re-review R2).
- [ ] Make a wildcard squatter visible: `SO_EXCLUSIVEADDRUSE` on `127.0.0.1:8700` does not stop another process binding `0.0.0.0:8700` or `[::]:8700`, which takes the connections the moment the service dies (the HMAC proof still blocks it). At startup and in the tamper scan, look for a LISTEN socket on the wildcard address and our local port owned by another pid (`psutil.net_connections`, as `peer.py` does) and report a `tamper` event (e.g. `local_port_squatted` with pid, user, exe; re-review R1, optional).
- [ ] Session tracker edge cases (`server/app/sessions/tracker.py`): a session unreadable in the very first WTS snapshot and readable later opens as `logon` instead of `existing` (the notice is shown either way; only the history kind differs), and a session that stays enumerated but unreadable keeps its last state forever. Add a max age for the unreadable state (log off after it, or at least a `system` `collector.warning` after N consecutive unreadable polls) and note (a) next to P4-3 (re-review R6).

### Win 11 Pro real-machine check
- [ ] Every `대기` item in `docs/verification/win11-pro-p4-p5.md`: P4-1–P4-13, P5-1–P5-14, X-1–X-10. Move each failure here as its own item.
