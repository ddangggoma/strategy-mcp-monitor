// the server module is read as text (Vite ?raw) to catch drift between the two copies
import defaultsPy from "../../../server/app/notice/defaults.py?raw";
import { LOG_CATEGORIES } from "@/admin/logs/categories";
import { API_ERROR_CODES, DISABLED_REASONS, copy, messageForError } from "./ko";

const ERROR_CODES = ["validation", "invalid_email", "rate_limited", "login_required", "forbidden", "csrf", "not_found",
  "bootstrap_done", "user_exists", "last_admin", "name_taken", "endpoint_taken", "action_in_progress", "script_required",
  "scripts_required", "script_too_large", "script_encoding", "script_empty", "invalid_owner", "too_many_streams",
  "body_too_large", "bad_host", "internal", "unavailable", "method_not_allowed", "network", "session_changed"];

const REASONS = ["login", "local_only", "admin_only", "owner_only", "no_owner", "running", "config_error",
  "planned_sessions", "planned_logs", "planned_audit", "planned_alerts", "unchanged"];

/** Every leaf string in the deck, with function leaves called on sample arguments. */
function leaves(node: unknown, path = "copy"): [string, string][] {
  if (typeof node === "string") return [[path, node]];
  if (typeof node === "function") {
    const out = (node as (...a: unknown[]) => unknown)(3, "restart");
    return typeof out === "string" ? [[`${path}()`, out]] : [];
  }
  if (node && typeof node === "object") {
    return Object.entries(node).flatMap(([k, v]) => leaves(v, `${path}.${k}`));
  }
  return [];
}

it("covers every API error code", () => {
  expect([...API_ERROR_CODES].sort()).toEqual([...ERROR_CODES].sort());
  for (const c of ERROR_CODES) expect(copy.errors[c as keyof typeof copy.errors]).toMatch(/\S/);
  expect(Object.keys(copy.errors).sort()).toEqual([...ERROR_CODES].sort());
  expect(messageForError("something_new")).toBe(copy.errors.internal);
  expect(messageForError("csrf")).toBe(copy.errors.csrf);
  expect(messageForError("toString")).toBe(copy.errors.internal); // no prototype leaks
});

it("explains every disabled reason", () => {
  expect([...DISABLED_REASONS].sort()).toEqual([...REASONS].sort());
  expect(Object.keys(copy.deny).sort()).toEqual([...REASONS].sort());
  for (const r of REASONS) expect(copy.deny[r as keyof typeof copy.deny]).toMatch(/\S/);
});

it("pins the fixed terms", () => {
  expect(copy.roles).toEqual({ developer: "MCP 개발자", admin: "Admin" });
  expect(copy.channel).toMatchObject({ local: "로컬 관리 모드", external: "원격 모드" });
  expect(copy.states).toEqual({ HEALTHY: "정상", SUSPECT: "이상 감지", ACTION: "조치 중", RECOVERING: "복구 중", FAILED: "실패", MAINTENANCE: "점검 중" });
  expect(copy.issues).toEqual({ PROCESS_DOWN: "프로세스 중지", UNRESPONSIVE: "응답 없음", NETWORK_DOWN: "네트워크 연결 안 됨", WRONG_PROCESS: "다른 프로세스가 포트 사용" });
  expect(copy.deny.local_only).toContain("127.0.0.1:8700");
});

it("has every top-level section the screens import", () => {
  expect(Object.keys(copy).sort()).toEqual(["audit", "board", "channel", "common", "dashboard", "deny", "diff", "errors", "issues", "login",
    "logs", "mcp", "nav", "notice", "roles", "scripts", "sessions", "settings", "setup", "states", "stream", "tamper", "toasts", "users"].sort());
});

it("names every tamper event", () => {
  const names = ["agent_exited", "agent_unresponsive", "agent_restart_storm", "agent_impersonation", "notice_token_misuse",
    "script_hash_mismatch", "script_file_changed", "script_file_missing", "log_file_removed", "log_file_truncated",
    "audit_policy_changed", "log_cleared", "audit_config_changed"];
  for (const n of names) expect(copy.tamper.events[n as keyof typeof copy.tamper.events]).toMatch(/\S/);
  expect(Object.keys(copy.tamper.events).sort()).toEqual([...names].sort()); // exactly the Global Constraints list
});

it("names every session state, connection kind and end reason the server sends", () => {
  expect(Object.keys(copy.sessions.state).sort()).toEqual(["active", "connected", "disconnected", "locked"]);
  expect(Object.keys(copy.sessions.kinds).sort()).toEqual(["existing", "logon", "reconnect"]);
  expect(Object.keys(copy.sessions.endReasons).sort()).toEqual(["disconnect", "logoff", "reconnected", "service_stop"]);
  // one place for the session card's words (F16): the board no longer has its own copy
  expect(copy.board).not.toHaveProperty("session");
  expect(copy.dashboard).not.toHaveProperty("tamperTitle");
});

it("formats session numbers in words", () => {
  expect(copy.sessions.idle(1)).toBe("1분");
  expect(copy.sessions.idle(60)).toBe("1시간");
  expect(copy.sessions.idle(61)).toBe("1시간 1분");
  expect(copy.sessions.resolution(1920, 1080, 32)).toBe("1920×1080, 32비트");
  expect(copy.sessions.resolution(1920, 1080, null)).toBe("1920×1080");
  expect(copy.sessions.ackIn(2000)).toBe("2초 만에 확인");
  expect(copy.sessions.ackIn(400)).toBe("1초 안에 확인");
  expect(copy.sessions.ackIn(125_000)).toBe("2분 5초 만에 확인");
  expect(copy.sessions.days(30)).toContain("30일");
  expect(copy.sessions.collectorDown("access denied")).toContain("access denied");
  expect(copy.sessions.logonType(10)).toBe("원격 대화형(10)");
  expect(copy.sessions.logonType(3)).toBe("네트워크(3)");
  expect(copy.sessions.logonType(99)).toBe("99"); // unknown types keep the number alone
  expect(copy.tamper.session(3)).toBe("세션 3");
});

it("tells the notice window what happened in display mode", () => {
  expect(copy.board.sessionsNotReady).toBe("원격 접속 정보를 아직 받지 못했어요.");
  for (const k of ["displayExpired", "ackFailed", "retry", "loadFailedRetry"] as const) expect(copy.notice[k]).toMatch(/\S/);
  // the token left the address bar, so a reload cannot help: the retry button is the way back
  expect(copy.notice.loadFailedRetry).not.toMatch(/새로 고/);
});

it("states the login lock and code rules with numbers", () => {
  expect(copy.login.lockedFor(42)).toContain("42분");
  expect(copy.login.failureHint).toMatch(/10번/);
  expect(copy.login.failureHint).toMatch(/1시간/);
  expect(copy.login.codeExhausted).toMatch(/5번/);
});

it("states the retention and MCP name rules", () => {
  // a plain string: Task 13 finds it with findByText
  expect(copy.settings.retentionBelowCompress).toMatch(/압축/);
  expect(copy.settings.retentionBelowCompress).toMatch(/보존 기간/);
  expect(copy.settings.retentionRange).toMatch(/7–3,650일/);
  expect(copy.mcp.nameRule).toMatch(/글자/);
  expect(copy.mcp.nameRule).toMatch(/숫자/);
  for (const ch of [".", "_", "-"]) expect(copy.mcp.nameRule).toContain(ch);
});

it("keeps the house style: no ASCII ellipsis, straight quotes, apologies or exclamations", () => {
  const all = leaves(copy);
  expect(all.length).toBeGreaterThan(150);
  for (const [path, text] of all) {
    expect(text, path).not.toMatch(/\.\.\./);
    expect(text, path).not.toMatch(/["']/);
    expect(text, path).not.toMatch(/죄송|불편을 드려|!/);
    expect(text, path).toBe(text.trim());
  }
});

it("ships the same built-in notice text as the server (version 0)", () => {
  const py = defaultsPy;
  const field = (name: string): string => {
    const m = new RegExp(`${name}=\\(?((?:\\s*"(?:[^"\\\\]|\\\\.)*"\\s*)+)\\)?,`).exec(py);
    if (!m?.[1]) throw new Error(`${name} not found in defaults.py`);
    return [...m[1].matchAll(/"((?:[^"\\]|\\.)*)"/g)].map((s) => JSON.parse(`"${s[1]}"`) as string).join("");
  };
  expect(copy.notice.builtIn).toEqual({
    title: field("title"),
    body: field("body"),
    button_text: field("button_text"),
  });
});

it("names every log category and group", () => {
  for (const c of LOG_CATEGORIES) expect(copy.logs.cats[c]).toMatch(/\S/);
  for (const g of ["session", "activity", "mcp", "security", "system"] as const) expect(copy.logs.groups[g]).toMatch(/\S/);
  expect(copy.logs.cmdLimitHelp).toContain("cmd");
});

it("gives every category chip and group its own name", () => {
  const names = [...Object.values(copy.logs.cats), ...Object.values(copy.logs.groups)];
  expect(new Set(names).size).toBe(names.length); // chips are found by name: no two alike
  expect(Object.keys(copy.logs.cats).sort()).toEqual([...LOG_CATEGORIES].sort());
});

it("says what the command log leaves out (spec §2 #7)", () => {
  for (const part of ["cmd /c", "dir", "cd", "del", "배치 파일", "키 입력", "클립보드"]) expect(copy.logs.cmdLimitHelp).toContain(part);
});

it("puts numbers and ranges into the log and audit sentences", () => {
  expect(copy.logs.indexing(3)).toContain("3");
  expect(copy.logs.usersCount(2)).toContain("2");
  expect(copy.logs.histogramLabel("13:00", "14:00", 1234)).toContain("1,234");
  expect(copy.logs.histogramLabel("13:00", "14:00", 1234)).toContain("13:00");
  expect(copy.logs.selection("13:10", "13:40", 6)).toContain("13:40");
  expect(copy.logs.selection("13:10", "13:40", 6)).toContain("6");
  expect(Object.keys(copy.audit.results).sort()).toEqual(["denied", "error", "fail", "ok"]);
  expect(Object.keys(copy.audit.kinds).sort()).toEqual(["admin", "all", "auth"]);
});

it("has the login-failure card, retention and service sentences", () => {
  // the Global Constraints keys plus the chart name and the read error (Task 12)
  expect(Object.keys(copy.dashboard.loginFailures).sort()).toEqual(["chartLabel", "empty", "error", "openLogs", "rdp", "title", "web"]);
  expect(copy.dashboard.loginFailures.chartLabel(1_204)).toContain("1,204");
  expect(copy.dashboard.loginFailures.title).toBe("로그인 실패 추이");
  expect(copy.settings.retentionDeleteEvents(41_200)).toContain("41,200");
  expect(copy.settings.retentionRunsSoon).toMatch(/\S/);
  expect(copy.settings.service.current("delayed-auto")).toContain(copy.settings.startTypes["delayed-auto"]);
  for (const k of ["title", "notInstalled", "mismatch", "devMode"] as const) expect(copy.settings.service[k]).toMatch(/\S/);
});
