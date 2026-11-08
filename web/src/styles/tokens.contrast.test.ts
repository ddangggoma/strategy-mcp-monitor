// Reads tokens.css, picks the light-dark() branch per theme, composites translucent tokens
// (the *-soft color-mix values) over their backdrop and checks WCAG contrast with culori.
import { converter, wcagContrast } from "culori";
import { GROUP_STACK } from "@/admin/logs/categories";
import { colorTokenNames, compositeOver, contrastPairs, isDisplayable, resolveToken } from "./contrast-helpers";

const STATES = ["healthy", "suspect", "action", "recovering", "failed", "maintenance"] as const;
const THEMES = ["light", "dark"] as const;

it.each(THEMES)("text tokens meet 4.5:1 in %s", (theme) => {
  const pairs: [string, string][] = [
    ["fg", "bg"],
    ["fg", "surface"],
    ["fg", "surface-raised"],
    ["fg-muted", "bg"],
    ["fg-muted", "surface"],
    ["fg-muted", "surface-raised"],
    ["accent-fg", "accent"],
    ["danger-fg", "danger"],
    ["danger", "bg"], // inline field errors are written in --color-danger
    ["danger", "surface"],
    ["danger", "surface-raised"],
    ...STATES.map((s): [string, string] => [`state-${s}-fg`, `state-${s}-soft`]),
  ];
  for (const [fg, bg] of pairs) {
    expect(contrastPairs(theme, fg, bg), `${fg} on ${bg}`).toBeGreaterThanOrEqual(4.5);
  }
});

it.each(THEMES)("state badge text stays readable on a soft badge placed on the page bg in %s", (theme) => {
  for (const s of STATES) {
    expect(contrastPairs(theme, `state-${s}-fg`, `state-${s}-soft`, "bg"), s).toBeGreaterThanOrEqual(4.5);
  }
});

// WCAG 1.4.11 non-text contrast applies to boundaries a user needs to see: the focus ring,
// state icons/strokes and input borders (border-strong). The decorative hairline --color-border
// only groups content and is deliberately quiet (preflight F27), so it is not held to 3:1.
it.each(THEMES)("UI tokens meet 3:1 in %s", (theme) => {
  const ui = ["border-strong", "focus", ...STATES.map((s) => `state-${s}`)];
  for (const token of ui) {
    for (const bg of ["bg", "surface", "surface-raised"]) {
      expect(contrastPairs(theme, token, bg), `${token} on ${bg}`).toBeGreaterThanOrEqual(3);
    }
  }
});

// Log category groups (W32): histogram bars, timeline marks and chip dots are non-text UI that has
// to stand out from every surface a log screen paints (WCAG 1.4.11).
const CAT_GROUPS = ["session", "activity", "mcp", "security", "system"] as const;

it.each(THEMES)("UI 3:1 대비 surface: log category colors in %s", (theme) => {
  for (const g of CAT_GROUPS) {
    for (const bg of ["bg", "surface", "surface-raised"]) {
      expect(contrastPairs(theme, `cat-${g}`, bg), `cat-${g} on ${bg}`).toBeGreaterThanOrEqual(3);
    }
  }
});

it.each(THEMES)("log category colors are told apart from each other in %s", (theme) => {
  // OKLab distance between every pair: stacked bars sit side by side, so neighbours must differ
  const lab = (name: string) => {
    const c = resolveToken(theme, name);
    const h = ((c.h ?? 0) * Math.PI) / 180;
    return [c.l, c.c * Math.cos(h), c.c * Math.sin(h)] as const;
  };
  for (const [i, a] of CAT_GROUPS.entries()) {
    for (const b of CAT_GROUPS.slice(i + 1)) {
      const [p, q] = [lab(`cat-${a}`), lab(`cat-${b}`)];
      const d = Math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2]);
      expect(d, `${a} vs ${b}`).toBeGreaterThanOrEqual(0.1);
    }
  }
});

// Stacked histogram segments touch their neighbours in GROUP_STACK order (dataviz skill, check 4):
// adjacent pairs stay apart under protan/deutan simulation (Machado 2009, severity 1) by ΔE ≥ 8
// and under normal vision by ΔE ≥ 15 (OKLab ×100).
const MACHADO = {
  protan: [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]],
  deutan: [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.01182, 0.04294, 0.968881]],
} as const;
const toLrgb = converter("lrgb");
const toLab = converter("oklab");

function okLab(rgb: [number, number, number]): [number, number, number] {
  const c = toLab({ mode: "lrgb", r: rgb[0], g: rgb[1], b: rgb[2] });
  return [c.l, c.a, c.b];
}

function seen(theme: (typeof THEMES)[number], token: string, kind?: keyof typeof MACHADO): [number, number, number] {
  const c = toLrgb(resolveToken(theme, token));
  const v = [c.r, c.g, c.b].map((x) => Math.min(1, Math.max(0, x)));
  if (!kind) return okLab(v as [number, number, number]);
  const m = MACHADO[kind];
  const sim = m.map((row) => Math.min(1, Math.max(0, row[0] * v[0]! + row[1] * v[1]! + row[2] * v[2]!)));
  return okLab(sim as [number, number, number]);
}

it.each(THEMES)("stacked category neighbours stay apart for colour-blind and normal vision in %s", (theme) => {
  const dist = (p: number[], q: number[]) => 100 * Math.hypot(p[0]! - q[0]!, p[1]! - q[1]!, p[2]! - q[2]!);
  for (const [i, a] of GROUP_STACK.slice(0, -1).entries()) {
    const b = GROUP_STACK[i + 1]!;
    for (const kind of ["protan", "deutan"] as const) {
      expect(dist(seen(theme, `cat-${a}`, kind), seen(theme, `cat-${b}`, kind)), `${a}/${b} ${kind}`).toBeGreaterThanOrEqual(8);
    }
    expect(dist(seen(theme, `cat-${a}`), seen(theme, `cat-${b}`)), `${a}/${b} normal`).toBeGreaterThanOrEqual(15);
  }
});

it.each(THEMES)("the decorative border is visible but quieter than border-strong in %s", (theme) => {
  const border = contrastPairs(theme, "border", "surface");
  expect(border).toBeGreaterThan(1.1);
  expect(border).toBeLessThan(contrastPairs(theme, "border-strong", "surface"));
});

it("themes really differ and soft tokens are translucent", () => {
  expect(resolveToken("light", "bg").l).toBeGreaterThan(0.9);
  expect(resolveToken("dark", "bg").l).toBeLessThan(0.3);
  for (const s of STATES) {
    expect(resolveToken("dark", `state-${s}-soft`).alpha).toBeCloseTo(0.18, 5);
    expect(resolveToken("light", `state-${s}-soft`).alpha).toBeCloseTo(0.18, 5);
  }
});

it.each(THEMES)("every color token resolves inside sRGB in %s", (theme) => {
  const names = colorTokenNames();
  expect(names.length).toBeGreaterThanOrEqual(30);
  for (const name of names) expect(isDisplayable(theme, name), name).toBe(true);
});

it("composites like a browser: half-transparent black over white is mid grey", () => {
  const grey = compositeOver({ mode: "rgb", r: 0, g: 0, b: 0, alpha: 0.5 }, { mode: "rgb", r: 1, g: 1, b: 1 });
  expect(grey.r).toBeCloseTo(0.5, 5);
  expect(grey.alpha).toBe(1);
});

it("rejects unknown tokens instead of measuring nothing", () => {
  expect(() => contrastPairs("dark", "no-such-token", "bg")).toThrow(/no-such-token/);
});

// Board problem cards (McpCard.css) paint state-*-soft over the surface and keep ordinary text,
// muted labels and the state-colored sparkline/gauge on top of it.
it.each(THEMES)("text and state strokes stay readable on a soft problem card in %s", (theme) => {
  for (const s of ["suspect", "action", "recovering", "failed"]) {
    const soft = `state-${s}-soft`;
    expect(contrastPairs(theme, "fg", soft, "surface"), `fg on ${soft}`).toBeGreaterThanOrEqual(4.5);
    expect(contrastPairs(theme, "fg-muted", soft, "surface"), `fg-muted on ${soft}`).toBeGreaterThanOrEqual(4.5);
    expect(contrastPairs(theme, `state-${s}`, soft, "surface"), `state-${s} on ${soft}`).toBeGreaterThanOrEqual(3);
  }
});

// TextDiff paints diff-add/diff-del rows on a surface panel (not sunken: muted line numbers would drop below 4.5:1); line text is fg, line numbers fg-muted.
it.each(THEMES)("diff rows keep code and line numbers readable in %s", (theme) => {
  for (const row of ["diff-add", "diff-del"]) {
    expect(contrastPairs(theme, "fg", row, "surface"), `fg on ${row}`).toBeGreaterThanOrEqual(4.5);
    expect(contrastPairs(theme, "fg-muted", row, "surface"), `fg-muted on ${row}`).toBeGreaterThanOrEqual(4.5);
  }
});

// Board metric accents (BoardOverview.css): ring and bar gradients (both ends), sparklines and chip
// glyphs are non-text UI on every surface a board tile paints (WCAG 1.4.11).
const RESOURCE_ROW = ["cpu", "memory", "gpu", "disk", "network"] as const;
const OVERVIEW_ROW = ["states", "latency", "checks", "uptime"] as const;
const GRADIENT_ENDS = ["cpu-2", "memory-2", "gpu-2", "disk-2"] as const;

it.each(THEMES)("board metric accents meet 3:1 on every surface in %s", (theme) => {
  for (const m of [...RESOURCE_ROW, ...OVERVIEW_ROW, ...GRADIENT_ENDS]) {
    for (const bg of ["bg", "surface", "surface-raised"]) {
      expect(contrastPairs(theme, `metric-${m}`, bg), `metric-${m} on ${bg}`).toBeGreaterThanOrEqual(3);
    }
  }
  expect(contrastPairs(theme, "brand", "surface")).toBeGreaterThanOrEqual(3);
});

it.each(THEMES)("a tile's chip glyph stays 3:1 on its own 14%% tint in %s", (theme) => {
  const surface = resolveToken(theme, "surface");
  for (const m of [...RESOURCE_ROW, ...OVERVIEW_ROW]) {
    const hue = resolveToken(theme, `metric-${m}`);
    const chip = compositeOver({ ...hue, alpha: 0.14 }, surface);
    expect(wcagContrast(compositeOver(hue, chip), chip), m).toBeGreaterThanOrEqual(3);
  }
});

// Tiles sit side by side in these orders: neighbours stay apart under protan/deutan by the floor
// ΔE 6 (every tile also carries its title and icon, the secondary encoding) and under normal
// vision by ΔE 15 (OKLab ×100).
it.each(THEMES)("neighbouring board tiles keep their accents apart in %s", (theme) => {
  const dist = (p: number[], q: number[]) => 100 * Math.hypot(p[0]! - q[0]!, p[1]! - q[1]!, p[2]! - q[2]!);
  for (const row of [RESOURCE_ROW, OVERVIEW_ROW] as const) {
    for (const [i, a] of row.slice(0, -1).entries()) {
      const b = row[i + 1]!;
      for (const kind of ["protan", "deutan"] as const) {
        expect(dist(seen(theme, `metric-${a}`, kind), seen(theme, `metric-${b}`, kind)), `${a}/${b} ${kind}`).toBeGreaterThanOrEqual(6);
      }
      expect(dist(seen(theme, `metric-${a}`), seen(theme, `metric-${b}`)), `${a}/${b} normal`).toBeGreaterThanOrEqual(15);
    }
  }
});

// A resource's hue must not pass for a trouble state: the amber and red its load turns to, or the
// orange of an action. (Next to healthy green it may sit closer: under its thresholds a load is fine.)
it.each(THEMES)("metric accents stay clear of the state hues in %s", (theme) => {
  const dist = (p: number[], q: number[]) => 100 * Math.hypot(p[0]! - q[0]!, p[1]! - q[1]!, p[2]! - q[2]!);
  for (const m of [...RESOURCE_ROW, ...GRADIENT_ENDS]) {
    for (const s of ["suspect", "action", "failed"]) {
      expect(dist(seen(theme, `metric-${m}`), seen(theme, `state-${s}`)), `${m} vs ${s}`).toBeGreaterThanOrEqual(15);
    }
  }
});
