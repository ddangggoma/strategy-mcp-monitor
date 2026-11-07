# Plan 2 pre-flight consistency scan

Plan: docs/superpowers/plans/2026-11-05-plan2-mcp-monitor.md (14 tasks). Spec: docs/PLAN.md v0.4. Read-only scan. Executed checks: (a) Task 5 migration loaded into sqlite3 (loads clean, `trigger` column is legal, IntegrityError texts `mcps.name` / `mcps.host, mcps.port` match the plan's mapping); (b) AST pass over the plan's python blocks for unused imports. Ruff, uv and the dummy project were not run. "OK" = names and signatures agree. "F#" = see Findings.

## A. Task-pair rows (shared file or interface)

| ID | Tasks | Produces vs Consumes (exact names) | Match |
|---|---|---|---|
| P01 | T1-T2 | `app_factory.py`: T1 adds `BodySizeLimit`/`MAX_BODY_BYTES`; T2 deletes `_pydantic_validation_handler` and the `ValidationError` import. Disjoint hunks. | OK |
| P02 | T1-T13 | `MAX_BODY_BYTES=262_144` vs `POST /api/mcps` with up to 3 scripts of 65,536 B each plus JSON escaping (`"`, `\`, CRLF). Carry-forward suggested 64 KB. | Tight (F20) |
| P03 | T2-T5 | `db.py` + `test_db.py`: T2 adds re-entry guard, `execute_rowcount`, rewrites version asserts (lines 18, 100, 131 = `3`, `3`, `4`); T5 appends migration #4 and extends the table-list test. Line 131 expectation is `len(orig)+1` (one good appended migration, one failing), not `len(MIGRATIONS)` as written. | Ambiguous (F17) |
| P04 | T2-existing tests | `RULES: Mapping = MappingProxyType(...)` vs `tests/test_policy.py::test_unlisted_action_is_denied` (`monkeypatch.delitem(RULES, ...)`) and `tests/test_settings_api.py::test_retention_keys_require_edit_retention` (`monkeypatch.setitem(policy.RULES, ...)`). Both raise TypeError on a mappingproxy. T2 Files lists test_policy.py but not test_settings_api.py, and gives no fix. | MISMATCH (F1) |
| P05 | T2-T13 | `Action.VIEW_SCRIPTS = Rule("developer", local_only=True)` and matrix row `(A.VIEW_SCRIPTS,0,1,1,True,False)` vs `require(Action.VIEW_SCRIPTS)` on GET scripts/versions routes. Existing `test_matrix`, `test_matrix_covers_every_action`, `test_every_action_has_a_rule` still hold. | OK |
| P06 | T2-T5/T10 | `Database.execute_rowcount(sql, params) -> int` produced; no task declares it consumed (needed by `McpStore.delete` not-found and `McpHistory.purge() -> int`). | OK, undeclared (F28) |
| P07 | T3-T4 | T3 CLI `--pid-file/--chaos/--host/--port` and `tests/helpers.py` (`free_port, listener_pid, rpc, ROOT`) vs T4 `test_examples.py` imports and script arguments. | OK |
| P08 | T3 internal | `common.server.run(name, tools, argv, default_port)` parses argv itself; weather-only `--open-meteo` and its `fetch` closure have no hook in that signature. | Gap (F23) |
| P09 | T4-T14 | Example `.ps1` env contract (`MCP_ID/NAME/HOST/PORT`, `DUMMY_MCPS_DIR`, `DUMMY_MCP_RUN_DIR`, `DUMMY_MCP_CHAOS`, names `calculator`/`seoul-clock`) vs T14 fixture `monkeypatch.setenv` and `TIMING`. Runner inherits `os.environ`. Scripts go through `prepare_script` (BOM + CRLF) and are re-hashed; read with `utf-8-sig`. | OK |
| P10 | T4 internal | start/stop/restart each repeat env validation, module map, python-path check, pid/port wait loops (restart inlines start+stop by mandate). | Plan-mandated duplication (F15) |
| P11 | T5-T6 | `McpStore.insert(conn, config, owner_id, created_by) -> int`, `.get`, `McpNotFoundError`; `ScriptStore(db, paths, clock, mcps)`; `AppPaths.scripts_dir` exists. | OK |
| P12 | T5-T6 | `create_mcp` needs the new id to build `scripts/<id>/`, but the write order says tmp file (step 2) precedes the transaction (step 3). For create the tmp write can only follow `insert`. | Clarify (F25) |
| P13 | T5-T8/T9/T10 | `McpConfig`, `McpState`, `Issue`, `ALERT_ONLY_ISSUES`, `CheckResult`, `Trigger`, `ActionKind`, `ScriptStatus` consumed with identical names/values. `tests.test_mcp_store.cfg` imported by T6, T8, T10; `fakes.make_mcp` (T9) is a second builder. | OK / smell (F16) |
| P14 | T5-T10 | Migration #4 columns vs `McpHistory`/`ActionRecord`/`TransitionRecord`/`MinuteBucket` (all 17 `mcp_actions` columns map; `actual_sha256` is not stored and round-trips as None). Additive UPSERT `latency_max` NULL handling unspecified. | OK / pitfall (F11) |
| P15 | T5-T11 | `McpStore.create/get/list/update/set_maintenance/set_owner/delete/effective_owner_id` all consumed. `Monitor.manual_action` persists maintenance but does not say it refreshes the engine config / its cached `Mcp`. | Gap (F5) |
| P16 | T6-T11 | `ScriptStore.get(...).path/.sha256`, `ScriptUpload(ext, content)` field order, restart-missing fallback (`get(id,"restart") is None`). | OK |
| P17 | T6-T13 | All 8 `ScriptStore` methods used by T13 exist; `ScriptValidationError.code`, `ScriptRequiredError`, `ScriptNotFoundError` map to Global codes; `ScriptInfo.path` is excluded from JSON. | OK |
| P18 | T7-T10 | `ScriptResult(status, exit_code, duration_ms, stdout, stderr, stdout_truncated, stderr_truncated, killed, error, actual_sha256)` vs T10 positional `ScriptResult("ok",0,120,"out","",False,False,0,None,None)`. | OK |
| P19 | T7-T11 | `ScriptRunner.run(path,*,expected_sha256,timeout_sec,env,lock_key)` = `ScriptRunnerLike` = `FakeRunner.run`; `RunCall` fields match; `peak_active` must be a settable attribute (test resets it). | OK |
| P20 | T8-T11 | `McpEngine` API (`on_check/boot/tick/on_action_done/manual/set_maintenance/reconfigure/needs_*/snapshot`), effects `Transition/RunScript/Alert`, `ActionInProgressError` consumed as named. | OK |
| P21 | T8-T11 | `boot()` on a non-autostart engine (`eng(clock).boot(bad)` -> SUSPECT) and `Transition.issue` on the boot path (test expects PD) are absent from T8's table/issue rule. | Gap (F22) |
| P22 | T9-T11 | `Prober.probe/check/forget(mcp_id)/aclose`, `ProbeResult` = `ProberLike`; `FakeProber` mirrors. `McpPingClient.forget(url)` vs `Prober.forget(mcp_id)` mapping unspecified; `Monitor.remove` does not call `prober.forget`. | OK / gap (F24) |
| P23 | T9-T12/T14 | `tests.live.free_port/live_app` produced in T9 (and `test_e2e_serve.py` switched), consumed by T12 and T14. | OK |
| P24 | T10-T11 | `McpHistory.record(mcp_id, at, ok, latency_ms, counted=)`, `record_transition`, `record_action`, `sparkline`, `uptime`, `last_check_at`, `forget` match. Board `latency_ms` has no history accessor (must come from `sparkline()[-1]`). `actions()` ordering with equal timestamps (FakeClock) needs an id tie-break. | OK / gap (F12, F24) |
| P25 | T10-T12 | `BoardBus._max_streams` appears only in T12's trailing note; T10 Interfaces list `BoardBus(max_streams)` only. `Subscription.dirty/events/wake` match `board_stream`. `/history?hours`: `buckets(since)` only; `transitions(limit)`/`actions(limit)` take no time bound. | Mismatch (F9, F12) |
| P26 | T11-T12 | `monitor.board()/board_item/engine/reconfigure/manual_action/remove/wait_idle`; the 12 board-item keys equal the `KEYS` test set. `mcp_detail(services, mcp)` signature matches T13's use. | OK |
| P27 | T11-T13 | `monitor.add/remove`, `ActionInProgressError` (from `engine`), `require(..., owner_id=mcp_owner)` (a callback raising `ApiError` passes through `require`'s `(ValueError, KeyError)` catch). | OK |
| P28 | T12-T13 | Shared `GET/PUT /api/mcps/{id}` vs local `POST /api/mcps` and `DELETE /api/mcps/{id}`: same path, different method gives PARTIAL/405 on external. | Needs handling (F2, F3) |
| P29 | T13-Plan 1 `test_channels.py` | `test_local_routes_absent_on_external._serves` treats `Match.PARTIAL` as served; T13 only says "add `mcp_local.router.routes`". POST `/api/mcps` and DELETE `/api/mcps/{mcp_id}` give PARTIAL on external. T13 Files omits test_channels.py. | MISMATCH (F3) |
| P30 | T13-Plan 1 `test_errors_and_serve.py` | Blanket "external and 405 -> 404" vs existing `test_framework_errors_use_error_code_bodies` (`POST /api/channel` on external == 405 `method_not_allowed`). Not in T13 Files. | MISMATCH (F2) |
| P31 | T7-T14 | `pyproject.toml`/`uv.lock` edited by T7 (psutil, httpx runtime) and T14 (marker, addopts, ruff, mypy, dev deps); consistent with Global dependency list. | OK |
| P32 | T11-T14 | `build_services(...)` defaults (`ScriptRunner()`, `Prober(clock)`), `serve()` start/stop order, integration fixture `monitor.start()/stop()` then `log.stop()` then `db.close()`. | OK |
| P33 | T14-T1..T13 | Ruff default gate vs test style used by plan and Plan 1 tests (`;`, one-line `with ...: stmt`); unused imports in plan code. | MISMATCH (F10) |
| P34 | T14-spec | PLAN.md edits (v0.4.1 row, §4.4, §8 users, §8 scripts split) vs the authority doc; new endpoints and `VIEW_SCRIPTS` not added to §4.3/§8. | Partial (F21) |

## B. Per-task self-consistency rows

| ID | Task | Result |
|---|---|---|
| T01 | Task 1 | Tests agree with interfaces (`cap_user_agent`, `scope`, forbid, 413 for Content-Length and chunked). `test_rate_limit_scope`: the cooldown rejection inserts no IP row, so 9 more requests fill the 10 and "new" hits the IP limit: OK. Cap value see F20. |
| T02 | Task 2 | Breaks 2 existing tests (F1). `test_unknown_channel_denied` duplicates an existing test; `test_inactive_owner_is_not_owner` already passes today (can() already nulls inactive role), so "Step 2 FAIL" is true only for rules_frozen/VIEW_SCRIPTS/db/settings/500 tests (F17). Corrupt-row warning fires on every `get()` (F26). |
| T03 | Task 3 | Tests match CLI/tool signatures (evaluate cases, 25 districts, `+09:00`). `test_calculator_tool_call` is 2/3 skips (F23). Fixture `p.kill()` on a launcher may orphan the real server (F23). Conditional `common/jsonrpc.py` fallback not in Files (acceptable). |
| T04 | Task 4 | Contract and tests agree (exit codes 0/1/2, pid file == listener pid). Mandated duplication (F15). |
| T05 | Task 5 | Migration SQL loads; error mapping verified. `test_host_normalized_and_url` asserts no URL; IPv6 `[host]` branch of `Mcp.url` untested (F27). |
| T06 | Task 6 | Tests match signatures; `test_create_failure_leaves_nothing` patches the global `os.replace` via `mod.os` (needs `import os` + `os.replace` in `scripts.py`). Write-order text vs create_mcp (F25). `.bat` "oem" codec is Windows-only but tests are not skipped (F28). |
| T07 | Task 7 | Tests match API; Review-Focus tests exist. `proc._transport.close()` private (F14). `test_decode_output` covers BOM only (F14). `test_timeout_kills_tree` worst case (2 s + 5 s kill wait + 1 s drain) sits on the `< 8` bound. |
| T08 | Task 8 | Walked all 15 tests against the transition table: consistent. Gaps for boot paths and spec §5.7 RECOVERING->FAILED (F22). |
| T09 | Task 9 | Tests match signatures; `classify` PROCESS_DOWN rule too eager (F4); port-lookup exception swallowed (F13); no tests for endless/no-id SSE, `bad_response`, `no_reply`, `http_<status>`. `make_mcp(id=1, **config)` matches its uses. |
| T10 | Task 10 | Tests match API; `buckets()` must include the unflushed bucket (test needs it, interface silent); `max()` NULL pitfall (F11); ordering ties (F12). |
| T11 | Task 11 | `test_no_overlapping_checks...` is valid (rounds never yield); `test_loops_follow_settings` does not prove per-round re-read (F18); unused `ScriptUpload` import (F10); manual_action order (F5); in-flight sets (F6); loose ends (F24). |
| T12 | Task 12 | Tests match routes/KEYS/SSE format; unused `pytest` import (F10); subscription leak (F8); anonymous `action` events (F7); `_max_streams` (F9). GET `actions/{action_id}` vs POST `actions/{kind}` resolves by method. |
| T13 | Task 13 | Tests match routes/codes; unused `pytest` import (F10); mismatches with Plan 1 tests (F2, F3); unbounded `version`/`user_id` ints (F19). `PUT /api/mcps/abc/...` -> validation works because `require`'s owner callback runs before param validation. |
| T14 | Task 14 | Integration test consistent with T4/T11/T13 contracts; "1 passed, 60초 이내" vs worst-case waits ~145 s (F29); ruff gate (F10); doc edits (F21). Carry-forward has exactly 8 Plan 2 items and the plan maps all 8 (T1: 1-2, T2: 3,4,5,7, T14: 6,8). |

## C. "Consumes" vs existing Plan 1 code

| ID | Name consumed | Existing code | Result |
|---|---|---|---|
| C01 | `Database.query/execute/transaction`, `migrate` | present; `execute` returns `lastrowid` | OK; `execute_rowcount` new in T2 |
| C02 | `deps.require(action, owner_id=cb)`, `ApiError(status, code, headers)`, `client_ip(request)`, `get_services`, `get_channel` | present, same signatures; `require` runs the owner callback only for logged-in users and catches `(ValueError, KeyError)` | OK |
| C03 | `policy.Action`, `can(user, action, channel, owner_id)`, `Rule`, `OwnerRule` | present; `Role` exists in `users/store.py` for `Rule.min_role: Role \| None` | OK; `VIEW_SCRIPTS` new |
| C04 | `build_services(root, clock, otp_provider, dev_fixed_code)`, `Services` dataclass | present; T11 appends fields/params; one construction site only | OK |
| C05 | `LogWriter.emit(cat, **fields)`, `.flush()`, `.start()/.stop()` | present; `emit` loop-thread only; caller `ts` ignored | OK |
| C06 | `AuditLogger.admin(actor, action, channel, ip, target, result)` | present, identical | OK |
| C07 | `AuditLogger.auth_rate_limited(event,email,channel,ip,user_agent,now)` | all call sites use keywords; T1 adds trailing `scope="ip"` | OK |
| C08 | `Settings.ping_interval_sec / issue_check_interval_sec / confirm_interval_sec`, `SettingsStore.get/update` | present, same names and ranges (1-300 / 5-60 / 1-10) | OK |
| C09 | `AppPaths.scripts_dir`, `logs_dir`, `ensure()` | present (`root/"scripts"`, created by `ensure`) | OK |
| C10 | `UserStore.create(email,name,role,created_by)`, `.get`, `.set_active`; `SessionStore.create(user_id,channel,ip,user_agent)` | present; positional order matches the plan's calls | OK |
| C11 | `Clock`, `FakeClock.advance`, `to_kst_iso` | present | OK |
| C12 | conftest fixtures `clock, paths, db, services, local_client, external_client` | present with those names; `services` must gain `runner=FakeRunner(), prober=FakeProber(clock)` and `await monitor.stop()` before `log.stop()` (order not stated) | OK / note |
| C13 | `tests.test_auth_api.bootstrap/login/audit_events` | present; `audit_events` reads hard-coded `2026-11-04.jsonl` (FakeClock day) | OK |
| C14 | `CapturingOtpProvider`; `services.otp.provider.sent` | present | OK |
| C15 | `app.__version__` | present (`0.1.0`) | OK |
| C16 | `test_e2e_serve.free_port` | present; T9 moves it to `tests/live.py` | OK |
| C17 | `UserNotFoundError`, `LastAdminError` interplay | `set_active(owner)` on a developer needs no last-admin handling | OK |
| C18 | Implementer baseline "341 passed with `-W error`" | plan never mentions `-W error`; new subprocess transports, uvicorn in-process, unclosed httpx client in sync `build_services` tests are unverified under it | Unverified (F14) |

## D. Reviewer-rubric defects mandated by the plan

| ID | Defect | Where | Finding |
|---|---|---|---|
| R01 | Test passes before implementation / duplicate test | T2 `test_inactive_owner_is_not_owner`, `test_unknown_channel_denied` | F17 |
| R02 | Test does not assert what its name claims | T5 `test_host_normalized_and_url`; T11 `test_loops_follow_settings` | F27, F18 |
| R03 | Duplicated logic | T4 three scripts; T11 `counted` rule in ping and check flows; three Mcp builders in tests (T5 `cfg`, T9 `make_mcp`, T11 `seed_mcp`) | F15, F24, F16 |
| R04 | Swallowed error | T9 `except Exception -> port_known=False` with no trace; T2 corrupt settings silently defaulted | F13, F26 |
| R05 | Private API | T7 `proc._transport.close()` (plan-labeled) | F14 |
| R06 | Unused imports (ruff F401) | T11 `ScriptUpload`; T12, T13 `pytest` | F10 |
| R07 | Test-to-test import as helper | `from tests.test_mcp_store import cfg` in T6/T8/T10 | F16 |
| R08 | Parametrized skip in place of a test | T3 `test_calculator_tool_call` (2 of 3 params skipped) | F23 |

## E. Contradictions with Global Constraints or the spec

| ID | Item | Result |
|---|---|---|
| G01 | Global "Windows-only tests skip off win32" vs T5/T6/T11/T12/T13 tests that build `.bat` through the `"oem"` codec without a skip | Minor (F28) |
| G02 | Architecture "asyncio loops 3" vs T11 four loops (ping, issue, confirm, 60 s cleanup) | Text only (F24) |
| G03 | Global "no nested db.transaction()" vs call sites | No nesting in `otp.py`, `sessions.py`, `users/store.py`, `settings/store.py`, `services.py`; T6 passes `conn` to `McpStore.insert`. The guard must raise before the try/except that rolls back, or the inner call would roll back the outer transaction. OK |
| G04 | Global "LogWriter.emit loop thread only" | T7/T9 use `to_thread` only for pure functions; OK (F13's fix must log from the loop) |
| G05 | Spec §4.3: anonymous gets no MCP status history; T12 broadcasts `action` events (kind, trigger, status, exit_code, duration_ms) on the anonymous `/api/stream` | Conflict (F7) |
| G06 | Spec §5.7: RECOVERING failure beyond limit -> stop + FAILED; T8 goes RECOVERING -> SUSPECT -> (delay) -> FAILED | Deviation, ledger-adopted (F22) |
| G07 | Spec §8 footnote "script routes owner only" vs T2/T13 `VIEW_SCRIPTS` (developer read); §6.4 supports read-only for non-owners | Plan edits the authority doc in T14 (F21) |
| G08 | Global new error codes vs T12/T13 codes | All 11 used with matching status; `not_found`/`validation`/`forbidden`/`csrf` pre-exist |
| G09 | Global dependency rule vs T9/T14 imports (`uvicorn`, `starlette`) | Already runtime/transitive; OK |
| G10 | Global SSE (1 s coalesce, 15 s heartbeat, 100 streams) | T12 defaults equal; OK |

---

## Findings and proposed rulings

Severity: H = test or gate fails as written; M = behavior or spec risk; L = polish.

| # | Sev | Task | Finding | Proposed ruling | Cost if wrong |
|---|---|---|---|---|---|
| F1 | H | T2 | Freezing `RULES` breaks `test_policy.py::test_unlisted_action_is_denied` (`delitem`) and `test_settings_api.py::test_retention_keys_require_edit_retention` (`setitem`). | Add `test_settings_api.py` to T2 Files; both tests use `monkeypatch.setattr(policy, "RULES", MappingProxyType({...}))`. | Two red tests at T2 Step 4 |
| F2 | H | T13 | Blanket "external + 405 -> 404" breaks `test_errors_and_serve.py::test_framework_errors_use_error_code_bodies` (expects 405 for `POST /api/channel` on external). | Convert only when the path matches some `mcp_local.router` route (any method); keep 405 elsewhere. Add the test file to Files. Alternative: change that test to expect 404. | One red test, or shared routes lose the informative 405 |
| F3 | H | T13 | `_serves` counts `Match.PARTIAL` as served, so `POST /api/mcps` and `DELETE /api/mcps/{mcp_id}` (shared GET/PUT exist) fail `test_local_routes_absent_on_external` once `mcp_local.router.routes` is added. | Change `_serves` to `== Match.FULL` and add a client-level 404 assertion for those two; list `test_channels.py` in Files. | Red test at T13 Step 4 |
| F4 | M | T9 | `classify` returns PROCESS_DOWN on "no listening pid" even when the probe succeeded (0.5 s port cache right after a restart, pid-less entry). Only the probe-failed case is tested. | PROCESS_DOWN requires `listening_pid is None and not probe_ok`; add row `{listening_pid None, probe_ok True} -> None`. | False SUSPECT and, if persistent, an auto start on a healthy MCP |
| F5 | M | T11 | `manual_action` order unspecified: if the DB write precedes `engine.manual`, a rejected stop (409) still persists `maintenance=True`; after a successful manual stop the engine config / cached `Mcp` keep `maintenance=False`, so a later `PUT {"maintenance": false}` can be seen as "unchanged". | Call `engine.manual()` first (raises before any write), then persist, then `engine.reconfigure(new_config)` and refresh the cached `Mcp`. Add test: manual stop, then PUT maintenance false -> HEALTHY. | Stuck MAINTENANCE or phantom flag |
| F6 | M | T11/T14 | "같은 MCP의 ping·점검이 이미 진행 중이면 건너뜁니다" is ambiguous. A shared guard lets a 3 s hung ping starve the 1 s re-measure and delay ACTION. | Two in-flight sets (ping, check); boot check uses the check set. | Slow or flaky hang detection; integration timeouts |
| F7 | M | T12 | `action` events go to anonymous SSE subscribers; spec §4.3 denies anonymous MCP history and `GET .../actions/{id}` needs login. | Tag `Subscription.authed`; send `action` only to authed subscribers (or strip to `{mcp_id, kind, status}` for anonymous). | Spec conflict / info disclosure |
| F8 | M | T12 | Route subscribes, but `finally: unsubscribe` runs only if the generator starts; an early abort leaks a slot, and anonymous clients can then exhaust the 100 slots. | Make `unsubscribe` idempotent and release it in a StreamingResponse subclass `finally`/`background`; add a test that cancels before the first `anext`. | Permanent 503 on `/api/stream` |
| F9 | M | T10/T12 | `BoardBus._max_streams` is a private name defined only in T12's trailing note; the T10 implementer will not know. | Put "limit stored in `self._max_streams`" in T10 Interfaces. | T12 test red / rename churn |
| F10 | M | T14 | Ruff default rules (E4, E7, E9, F) include E701/E702; the plan's tests and Plan 1 tests use `;` and one-line `with ...: stmt` throughout, so "ruff check app tests -> 0" forces a mass rewrite. Also F401: `ScriptUpload` (test_monitor), `pytest` (test_mcp_shared_api, test_mcp_local_api). | Add `[tool.ruff.lint.per-file-ignores] "tests/*" = ["E701","E702"]` and drop the 3 unused imports in the plan text. | Large unplanned diff in T14 |
| F11 | M | T10 | `ON CONFLICT ... latency_max = max(latency_max, excluded.latency_max)` yields NULL when either side is NULL; `test_rollover_buckets_and_additive_flush` expects 4.0 after a failure-only flush. | Specify a NULL-safe form (CASE, or `max(coalesce(a,b), coalesce(b,a))`). | Red test, found quickly |
| F12 | L | T10/T12 | Ties: `actions()`/`transitions()` "latest first" with equal `at` (FakeClock) must give `["start","stop"]` in `test_restart_fallback`; `buckets()` must include the unflushed bucket; `hours` bounds only buckets. | Specify `ORDER BY at DESC, id DESC`, merge pending in `buckets`, document `hours` scope. | Order flake / API ambiguity |
| F13 | L | T9 | Any port-lookup exception becomes `port_known=False` with no trace; a permanent AccessDenied silently disables PROCESS_DOWN/WRONG_PROCESS. | Return the failure via `CheckResult.error` (e.g. `port_lookup:<ExcType>`); Monitor logs `system` once per N minutes on the loop thread. | Silent loss of detection |
| F14 | L | T7 | Private `proc._transport.close()` (plan-mandated); OEM fallback of `decode_output` untested off a Korean locale; behavior under baseline `-W error` unverified. | Wrap with a `getattr` guard and comment; add a `"가".encode("cp949")` decode test gated on codec/locale; run the full suite with `-W error` at T7. | Break on an asyncio update |
| F15 | L | T4 | start/stop/restart duplicate nearly all logic (restart inlines both) by design (per-file hash). | Accept; add a "keep in sync" header and a test comparing the shared block across the 3 files. | Drift between scripts |
| F16 | L | T5-T10 | Tests import `cfg` from `tests.test_mcp_store`; `make_mcp` and `mcp_helpers` are separate builders. | Create `tests/mcp_helpers.py` in T5 with `cfg`; `make_mcp` reuses it. | Reviewer "test-to-test import / duplication" |
| F17 | L | T2 | `test_unknown_channel_denied` duplicates an existing test; `test_inactive_owner_is_not_owner` passes pre-change; test_db line-131 value must be `len(original)+1` (capture before monkeypatch), lines 18/100 become `len(MIGRATIONS)` / `>= 3`. | Drop the duplicate, keep the owner test as a regression, state the exact expressions. | Cosmetic / wrong constant |
| F18 | L | T11 | `test_loops_follow_settings` sets the interval before `start()`, so it does not show per-round re-read. | Start at 5 s, update to 1 s mid-run, assert the cadence changes (or count `settings.get` calls per round). | Global constraint untested |
| F19 | L | T13 | `version` path int and body `user_id` unbounded -> `OverflowError` 500 (Plan 1 ruling capped path ints). | `Annotated[int, Path(ge=1, le=2**63-1)]` and `Field(ge=1, le=2**63-1)`; add one 422 test. | 500 on crafted input |
| F20 | L | T1 | Body cap 262,144 B vs three maximal scripts with escapes; carry-forward said 64 KB. | Raise to 524,288 or document the derivation. | A legitimate large create returns 413 |
| F21 | L | T14 | PLAN.md header still says v0.4 / "구현 착수 전"; §8 footnote "owner only" not updated; new endpoints and `VIEW_SCRIPTS` row absent from §4.3/§8; the spec is the authority. | Accept the §6.4-based read-only rule, but also update header, footnote and add endpoint/matrix rows; get the user's nod since it edits the authority doc. | Spec/impl drift |
| F22 | L | T8 | Table lacks `boot()` for non-autostart or non-PROCESS_DOWN (tests expect on_check behavior) and the boot `Transition.issue`; spec §5.7 sends a failed RECOVERING straight to FAILED, the plan goes via SUSPECT. | Add the missing rows; record the RECOVERING deviation (already ledger-adopted). | Implementer guess |
| F23 | L | T3 | `run()` has no hook for `--open-meteo`; `test_calculator_tool_call` skips 2/3; teardown `p.kill()` may orphan the real server behind the launcher. | Add an `extra_args`/tools-factory parameter to `run`; make the calculator call its own test; teardown asserts the port is free (kill by `listener_pid` if not). | Interface churn, leaked processes |
| F24 | L | T11 | Undefined: `remove` should call `prober.forget(mcp_id)` and `Prober` needs an id->url map; `start()` when engines already exist (test removes first); `latency_ms` source (use `sparkline()[-1]`); `counted` logic duplicated in ping/check; "3 loops" vs 4. | State each rule; add a `_record()` helper. | Leaks / inconsistent boards |
| F25 | L | T6 | create_mcp cannot write the tmp file before the transaction (id unknown). | State: create_mcp writes tmp files after `insert` inside the transaction; put/revert as written. | Implementer confusion |
| F26 | L | T2/T11 | A corrupt settings row warns on stderr at every `get()`; monitor loops call it each round. | Warn once per distinct stored value. | Log spam |
| F27 | L | T5 | `test_host_normalized_and_url` has no URL assertion; IPv6 `[host]` branch untested. | Rename and add an `Mcp.url` IPv6 case. | Untested branch |
| F28 | L | Global | `execute_rowcount` consumer undeclared; Windows-only `"oem"` codec used by non-skipped tests. | Declare consumers in T5/T10; accept (Windows-only product) or skip-mark. | None practical |
| F29 | L | T14/T11 | "1 passed, 60초 이내" vs worst-case waits ~145 s in the test; T11 Step 4 never asserts the server shuts down with the monitor. | Say "typically < 60 s, hard cap 150 s"; extend the e2e to terminate and check exit. | Misleading gate |
