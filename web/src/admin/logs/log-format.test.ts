import { summarize } from "./log-format";
import { logItem } from "../../../tests/msw/fixtures";

it.each([
  [logItem({ cat: "activity.command", data: { text: "Get-Process", shell: "powershell" } }), "Get-Process"],
  [logItem({ cat: "activity.process", event: "start", data: { name: "notepad.exe", pid: 8812 } }), "start notepad.exe (8812)"],
  [logItem({ cat: "auth", event: "login", user: "a@x.com", outcome: "fail", data: {} }), "login a@x.com"],
  [logItem({ cat: "admin.audit", event: "user_create", data: { target: { email: "b@x.com" } } }), "user_create b@x.com"],
  [logItem({ cat: "session", event: "connect", client_ip: null, data: {} }), "connect"],
  [logItem({ cat: "mcp.action", outcome: "timeout", data: { name: "calc", kind: "start" } }), "calc start timeout"],
])("summarizes %#", (item, text) => { expect(summarize(item)).toBe(text); });

it("caps long summaries at 300 chars", () => {
  expect(summarize(logItem({ cat: "activity.command", data: { text: "x".repeat(500) } }))).toHaveLength(300);
});

it.each([
  [logItem({ cat: "activity.command", data: { cmdline: "cmd.exe /c build.bat" } }), "cmd.exe /c build.bat"],
  [logItem({ cat: "activity.window", data: { title: "제목 없음 - 메모장", exe: "notepad.exe" } }), "제목 없음 - 메모장"],
  [logItem({ cat: "activity.window", data: { exe: "notepad.exe" } }), "notepad.exe"],
  [logItem({ cat: "activity.idle", event: "idle_start", data: { idle_sec: 300 } }), "idle_start"],
  [logItem({ cat: "session", event: "logon", client_ip: "10.0.3.21", data: {} }), "logon 10.0.3.21"],
  [logItem({ cat: "notice", event: "acknowledged", data: { version: 3 } }), "acknowledged v3"],
  [logItem({ cat: "notice", event: "shown", data: {} }), "shown"],
  [logItem({ cat: "admin.audit", event: "mcp_update", data: { target: { name: "calc", id: 2 } } }), "mcp_update calc"],
  [logItem({ cat: "admin.audit", event: "script_put", data: { target: { path: "scripts/2/start.ps1" } } }), "script_put scripts/2/start.ps1"],
  [logItem({ cat: "admin.audit", event: "user_patch", data: { target: { id: 7 } } }), "user_patch 7"],
  [logItem({ cat: "admin.audit", event: "logs_view", data: { target: { filters: {} } } }), "logs_view"],
  [logItem({ cat: "admin.audit", event: "settings_update", data: {} }), "settings_update"],
  [logItem({ cat: "mcp.health", data: { name: "calc", issue: "PROCESS_DOWN" } }), "calc PROCESS_DOWN"],
  [logItem({ cat: "mcp.health", data: { name: "calc", alert: true } }), "calc alert"],
  [logItem({ cat: "mcp.health", data: { name: "calc" } }), "calc"],
  [logItem({ cat: "mcp.action", outcome: null, data: { name: "calc", kind: "stop" } }), "calc stop"],
  [logItem({ cat: "tamper", event: "log_file_removed", data: { file: "x" } }), "log_file_removed"],
  [logItem({ cat: "system", event: "logindex.ready", data: { rows: 10 } }), "logindex.ready"],
  [logItem({ cat: "auth", event: "logout", user: null, data: {} }), "logout"],
])("leaves out missing pieces and keeps data verbatim %#", (item, text) => {
  expect(summarize(item)).toBe(text);
});

it("collapses runs of whitespace and line breaks into single spaces", () => {
  expect(summarize(logItem({ cat: "activity.command", data: { text: "  Get-Item\r\n   C:\\x\t y " } }))).toBe("Get-Item C:\\x y");
});

it("ignores values that are not text or numbers", () => {
  expect(summarize(logItem({ cat: "activity.process", event: "stop", data: { name: { bad: 1 }, pid: null } }))).toBe("stop");
  expect(summarize(logItem({ cat: "activity.command", data: { text: 42 } }))).toBe("42");
  expect(summarize(logItem({ cat: "activity.command", data: {} }))).toBe("");
});
