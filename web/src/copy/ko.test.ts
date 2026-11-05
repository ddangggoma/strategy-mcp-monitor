// the server module is read as text (Vite ?raw) to catch drift between the two copies
import defaultsPy from "../../../server/app/notice/defaults.py?raw";
import { API_ERROR_CODES, DISABLED_REASONS, copy, messageForError } from "./ko";

const ERROR_CODES = ["validation", "invalid_email", "rate_limited", "login_required", "forbidden", "csrf", "not_found",
  "bootstrap_done", "user_exists", "last_admin", "name_taken", "endpoint_taken", "action_in_progress", "script_required",
  "scripts_required", "script_too_large", "script_encoding", "script_empty", "invalid_owner", "too_many_streams",
  "body_too_large", "bad_host", "internal", "method_not_allowed", "network"];

const REASONS = ["login", "local_only", "admin_only", "owner_only", "no_owner", "running", "config_error",
  "planned_sessions", "planned_logs", "planned_audit", "planned_alerts"];

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
  expect(Object.keys(copy).sort()).toEqual(["board", "channel", "common", "dashboard", "deny", "diff", "errors", "issues", "login",
    "mcp", "nav", "notice", "roles", "scripts", "settings", "setup", "states", "stream", "toasts", "users"].sort());
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
