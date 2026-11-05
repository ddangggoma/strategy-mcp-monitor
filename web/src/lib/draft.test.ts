import { clearAllDrafts, clearDraft, loadDraft, saveDraft } from "./draft";

afterEach(() => {
  vi.restoreAllMocks();
  sessionStorage.clear();
});

it("round-trips and clears", () => {
  saveDraft("k", { a: 1 });
  expect(loadDraft("k")).toEqual({ a: 1 });
  clearDraft("k");
  expect(loadDraft("k")).toBeNull();
});

it("stores under the mcpmon.draft. prefix in sessionStorage", () => {
  saveDraft("script:1:start", { ext: ".ps1" });
  expect(sessionStorage.getItem("mcpmon.draft.script:1:start")).toBe('{"ext":".ps1"}');
});

it("never throws when storage is unavailable", () => {
  vi.spyOn(window, "sessionStorage", "get").mockImplementation(() => {
    throw new DOMException("denied", "SecurityError");
  });
  expect(() => saveDraft("k", { a: 1 })).not.toThrow();
  expect(loadDraft("k")).toBeNull();
  expect(() => clearDraft("k")).not.toThrow();
  expect(() => clearAllDrafts()).not.toThrow();
});

it("ignores a full storage and unreadable JSON", () => {
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new DOMException("full", "QuotaExceededError");
  });
  expect(() => saveDraft("k", { a: 1 })).not.toThrow();
  vi.restoreAllMocks();
  sessionStorage.setItem("mcpmon.draft.bad", "{not json");
  expect(loadDraft("bad")).toBeNull();
});

it("clearAllDrafts removes only drafts", () => {
  saveDraft("script:1:start", "a");
  saveDraft("mcp-create", "b");
  sessionStorage.setItem("other", "keep");
  clearAllDrafts();
  expect(loadDraft("script:1:start")).toBeNull();
  expect(loadDraft("mcp-create")).toBeNull();
  expect(sessionStorage.getItem("other")).toBe("keep");
});
