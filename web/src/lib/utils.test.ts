import { cn } from "./utils";

it("merges our token utilities by kind, not by prefix", () => {
  expect(cn("text-fg", "text-metric")).toBe("text-fg text-metric"); // color + size both stay
  expect(cn("text-sm", "text-metric")).toBe("text-metric"); // later size wins
  expect(cn("text-fg", "text-state-failed-fg")).toBe("text-state-failed-fg");
  expect(cn("bg-surface", "bg-state-suspect-soft")).toBe("bg-state-suspect-soft");
  expect(cn("rounded-md", "rounded-lg")).toBe("rounded-lg");
  expect(cn("shadow-md", "shadow-lg")).toBe("shadow-lg");
  expect(cn("ease-out", "ease-in-out")).toBe("ease-in-out");
  const wide = Math.random() > 2; // always false, but not a constant expression
  expect(cn("p-2", wide && "p-4", ["px-3"])).toBe("p-2 px-3");
});
