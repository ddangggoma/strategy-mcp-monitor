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
- [ ] Lowering only the retention period below `log_compress_after_days` returns 422. The UI must explain that both values have to be lowered together.
- [ ] Both ports use the same cookie name (`mcpmon_sid`), and browser cookies are scoped by host, not port. Logging in on one channel overwrites the other channel's cookie. Consider per-channel cookie names.
- [ ] Show an OTP lockout message: up to 1 hour after 10 failures. Optionally clear the failure history after a successful login.
- [ ] Read the CSRF token from `GET /api/auth/me` (added in the Plan 1 final fixes).
- [ ] (From Plan 2) The board is `GET /api/board` plus the SSE events `board` / `mcp` / `mcp_removed` / `action` on `GET /api/stream`.
- [ ] (From Plan 2) A manual action returns 202 + `run_id`; show the result toast from the `action` event (signed-in developer+ only; anonymous streams never get `action` events).
- [ ] (From Plan 2) Compute script diffs in the client from the versions API content (`GET .../scripts/{kind}/versions[/{version}]`).
- [ ] (From Plan 2) The anonymous board omits host:port, owner and config; those come from `GET /api/mcps[/{id}]` (developer+).
- [ ] (From Plan 2) An SSE stream keeps the auth level it connected with: after logout, close and reopen `/api/stream`.

### Plan 4 (Windows collection)
- [ ] `LogWriter.emit()` is loop-thread only. Collector threads must go through `loop.call_soon_threadsafe`.
- [ ] Collectors need an event-time override for `ts`: `emit` currently ignores a caller-supplied `ts`.
- [ ] Once a second process (agent or collector) opens `config.db`, cross-process contention can block the event loop for up to 5 s (`busy_timeout`). Move DB access off the loop or keep the second process off `config.db`.
- [ ] Record the localhost login's Windows account (spec §4.1.5).
- [ ] (From Plan 2) Add `sessions` to `GET /api/board` and to the SSE board events.

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
- [ ] An SSE stream's auth level is fixed at connect time, so a logout does not cut a live stream. The UI should reconnect the stream on login and logout. The server could also re-check the auth level periodically.
- [ ] A client that loses the race for the last stream slot gets an empty 200 instead of 503. Make the UI's EventSource reconnect with backoff.
- [ ] The per-IP stream cap is 5, and on the local channel every browser on the PC shares 127.0.0.1. Keep each tab to one stream, and consider raising the cap for loopback.
- [ ] MCP detail always includes `config_error` (true/false), and an invalid row has `live: null`. Show an "invalid config — rename or delete" state.
- [ ] MCP names are now allowlisted: Unicode letters and digits, space, `.`, `_`, `-`. Explain this in the form's validation text.
- [ ] Manual action returns 202 `{run_id}`, and the result arrives as an SSE `action` event that only authenticated users receive. A concurrent request returns 409 `action_in_progress`.

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
