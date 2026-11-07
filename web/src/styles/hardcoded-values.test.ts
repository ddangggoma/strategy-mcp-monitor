// Living version of the design-system "hardcoded value" audit: colors are spelled out only in
// tokens.css, and components speak only our role-token vocabulary (no shadcn default names, no
// Tailwind palette, no dark: overrides — light-dark() tokens flip on their own).
const sources = import.meta.glob<string>(["/src/**/*.{ts,tsx,css}", "!/src/**/*.test.{ts,tsx}"], {
  query: "?raw",
  import: "default",
  eager: true,
});

const RAW_COLOR = /#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(|\boklch\(|\boklab\(|\blab\(|\blch\(/;
const PALETTE =
  "slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose";
const FOREIGN_CLASS = new RegExp(
  String.raw`(?:^|[\s"'\x60:])(?:bg|text|border|ring|ring-offset|fill|stroke|outline|decoration|divide|from|via|to|shadow|caret|placeholder|accent)-` +
    String.raw`(?:background|foreground|primary|secondary|muted|popover|card|destructive|input|ring|sidebar|chart-\d|black|white|(?:${PALETTE})-\d{2,3})\b` +
    String.raw`|(?:^|[\s"'\x60])dark:[a-z[]`,
);

function offenders(re: RegExp, skip: (path: string) => boolean): string[] {
  const hits: string[] = [];
  for (const [path, text] of Object.entries(sources)) {
    if (skip(path)) continue;
    // comments may name forbidden things to explain them; blank them but keep line numbers
    const code = text.replace(/\/\*[\s\S]*?\*\//g, (c) => c.replace(/[^\n]/g, " "));
    code.split("\n").forEach((line, i) => {
      if (re.test(line.replace(/\/\/.*$/, ""))) hits.push(`${path}:${i + 1}: ${line.trim()}`);
    });
  }
  return hits;
}

it("scans the real sources", () => {
  const paths = Object.keys(sources);
  expect(paths).toContain("/src/styles/tokens.css");
  expect(paths).toContain("/src/components/ui/button.tsx");
  // raw CSS really is loaded (Vitest strips CSS unless vitest.config.ts includes it)
  expect(sources["/src/styles/tokens.css"]).toMatch(/oklch\(/);
  expect(sources["/src/styles/base.css"]).toMatch(/prefers-reduced-motion/);
  expect(sources["/src/styles/app.css"]).toMatch(/@theme inline reference/);
});

it("spells colors only in tokens.css", () => {
  // contrast-helpers parses colors as data; it is test tooling, not UI
  const skip = (p: string) => p === "/src/styles/tokens.css" || p === "/src/styles/contrast-helpers.ts";
  expect(offenders(RAW_COLOR, skip)).toEqual([]);
});

it("uses role tokens, not shadcn or Tailwind palette names", () => {
  expect(offenders(FOREIGN_CLASS, () => false)).toEqual([]);
});

it("the patterns do catch the things they forbid", () => {
  for (const bad of ['"bg-background"', " text-muted-foreground", '"border-red-500"', " dark:bg-surface", "color: #fff", "rgb(0 0 0)"]) {
    expect(RAW_COLOR.test(bad) || FOREIGN_CLASS.test(bad), bad).toBe(true);
  }
  for (const ok of ['"bg-surface text-fg"', '"text-state-failed-fg"', '"border-border-strong"', '"bg-accent text-accent-fg"']) {
    expect(RAW_COLOR.test(ok) || FOREIGN_CLASS.test(ok), ok).toBe(false);
  }
});
