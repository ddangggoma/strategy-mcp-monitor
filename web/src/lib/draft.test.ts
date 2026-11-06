import { meFixture } from "../../tests/msw/fixtures";
import { clearAllDrafts, clearDraft, loadDraft, saveDraft } from "./draft";
import { session } from "./session";

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
  expect(sessionStorage.getItem("mcpmon.draft.script:1:start")).toBe('{"owner":null,"value":{"ext":".ps1"}}');
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

describe("drafts belong to the user who wrote them", () => {
  afterEach(() => {
    session.me = null;
  });

  it("stamps the logged-in user and gives the draft back only to them", () => {
    session.me = meFixture("admin", "local", 1);
    saveDraft("notice", { title: "X's edit" });
    expect(loadDraft("notice")).toEqual({ title: "X's edit" });
    session.me = meFixture("admin", "local", 2); // the session expired and someone else logged in on this tab
    expect(loadDraft("notice")).toBeNull();
    session.me = meFixture("admin", "local", 1);
    expect(loadDraft("notice")).toBeNull(); // dropped once another user saw (not) it
  });

  it("keeps the draft while nobody is logged in (the login page after a 401)", () => {
    session.me = meFixture("admin", "local", 1);
    saveDraft("notice", { title: "t" });
    session.me = meFixture(null, "local");
    expect(loadDraft("notice")).toBeNull();
    session.me = meFixture("admin", "local", 1);
    expect(loadDraft("notice")).toEqual({ title: "t" });
  });

  it("takes an explicit owner for both sides", () => {
    saveDraft("k", "v", 7);
    expect(loadDraft("k", 7)).toBe("v");
    expect(loadDraft("k", 8)).toBeNull();
    expect(loadDraft("k", 7)).toBeNull();
  });

  it("treats a stored value without the owner envelope as no draft", () => {
    session.me = meFixture("admin", "local", 1);
    sessionStorage.setItem("mcpmon.draft.k", JSON.stringify({ title: "legacy" }));
    expect(loadDraft("k")).toBeNull();
  });
});
