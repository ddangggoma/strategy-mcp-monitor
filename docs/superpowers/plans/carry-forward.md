# Carry-forward items from completed plans

Every later plan reads this file before it is written and checks off the items it covers.

## From Plan 1 (core service & auth)

### Plan 2 (MCP monitoring backend)
- [ ] **(Important, do in Plan 2 Task 1)** The External User-Agent header has no length limit. `AuditLogger.auth()`/`admin()` and `SessionStore.create` store the raw User-Agent. The httptools parser has no header-size limit, so an anonymous request can still fill the disk.
  - Cap `user_agent` at 512 characters in `AuditLogger` and `SessionStore.create`.
  - Add `extra="forbid"` to `OtpRequestBody`/`OtpVerifyBody`.
  - Consider a request body-size limit middleware (for example 64 KB).
- [ ] The audit throttle key is (event, ip). After one per-email cooldown 429, later 429s for other emails from the same IP go unrecorded for 10 minutes. Consider keying by (event, ip, email-hash).
- [ ] Remove the global `pydantic.ValidationError` → 422 handler (`app_factory.py`). Use `ApiError(422)` in the settings route instead, so server-side model bugs return 500, not a client 422. Also handle a corrupt stored settings row.
- [ ] `Database.transaction()`: raise `RuntimeError` when a transaction is already open (`in_transaction`) to prevent re-entry within the same thread.
- [ ] `can()` hardening:
  - normalize an inactive user to `None` up front;
  - type `Rule.min_role` as `Role | None`;
  - check the channel with `get_args(Channel)`;
  - freeze `RULES` with `MappingProxyType`.
  - Do this when DELETE_MCP and EDIT_SCRIPTS get wired to routes.
- [ ] Align the spec text:
  - §4.4 `can(user, action, resource, channel)` should read `can(user, action, channel, owner_id)`;
  - §8 `PUT /api/users` should read `PATCH /api/users/{id}`.
- [ ] `Database.execute()` returns `lastrowid`, which is meaningless for non-INSERT statements. Document this, or add `rowcount`.
- [ ] Run ruff and mypy once (install them as dev dependencies).

### Plan 3 (Web UI)
- [ ] Lowering only the retention period below `log_compress_after_days` returns 422. The UI must explain that both values have to be lowered together.
- [ ] Both ports use the same cookie name (`mcpmon_sid`), and browser cookies are scoped by host, not port. Logging in on one channel overwrites the other channel's cookie. Consider per-channel cookie names.
- [ ] Show an OTP lockout message: up to 1 hour after 10 failures. Optionally clear the failure history after a successful login.
- [ ] Read the CSRF token from `GET /api/auth/me` (added in the Plan 1 final fixes).

### Plan 4 (Windows collection)
- [ ] `LogWriter.emit()` is loop-thread only. Collector threads must go through `loop.call_soon_threadsafe`.
- [ ] Collectors need an event-time override for `ts`: `emit` currently ignores a caller-supplied `ts`.
- [ ] Once a second process (agent or collector) opens `config.db`, cross-process contention can block the event loop for up to 5 s (`busy_timeout`). Move DB access off the loop or keep the second process off `config.db`.
- [ ] Record the localhost login's Windows account (spec §4.1.5).

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

### Later (real OTP provider)
- [ ] A `provider.send` failure distinguishes registered emails (enumeration), and sending inline creates a timing difference. Move sending off the request path, and make failures behave the same either way.
