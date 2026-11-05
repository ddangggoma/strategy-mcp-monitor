// Test-only helper: resolves color tokens from tokens.css the way a browser would and measures
// WCAG contrast. Not imported by any bundle.
import { converter, displayable, parse, toGamut, wcagContrast, type Oklch, type Rgb } from "culori";
import tokensCss from "./tokens.css?raw";

export type Theme = "light" | "dark";

const toOklch = converter("oklch");
const toRgb = converter("rgb");
const mapToSrgb = toGamut("rgb", "oklch");

/** Declarations at the top level of the first `:root { ... }` block (nested blocks are skipped). */
function readRootDeclarations(css: string): Map<string, string> {
  const text = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const start = text.indexOf(":root {");
  if (start === -1) throw new Error("tokens.css has no :root block");
  const decls = new Map<string, string>();
  let depth = 0;
  let buf = "";
  for (let i = text.indexOf("{", start); i < text.length; i++) {
    const ch = text[i];
    if (ch === "{") {
      depth++;
      if (depth > 1) buf = "";
      continue;
    }
    if (ch === "}") {
      depth--;
      buf = "";
      if (depth === 0) break;
      continue;
    }
    if (depth !== 1) continue;
    if (ch === ";") {
      const m = /^\s*(--[\w-]+)\s*:\s*([\s\S]+?)\s*$/.exec(buf);
      if (m?.[1] && m[2]) decls.set(m[1], m[2].replace(/\s+/g, " "));
      buf = "";
    } else {
      buf += ch;
    }
  }
  return decls;
}

const DECLS = readRootDeclarations(tokensCss);

/** Split on commas that are not nested in parentheses. */
function splitTopLevel(s: string, sep: RegExp): string[] {
  const parts: string[] = [];
  let depth = 0;
  let cur = "";
  for (const ch of s) {
    if (ch === "(") depth++;
    if (ch === ")") depth--;
    if (depth === 0 && sep.test(ch)) {
      if (cur.trim()) parts.push(cur.trim());
      cur = "";
    } else {
      cur += ch;
    }
  }
  if (cur.trim()) parts.push(cur.trim());
  return parts;
}

function fnArgs(value: string, name: string): string[] | null {
  if (!value.startsWith(`${name}(`) || !value.endsWith(")")) return null;
  return splitTopLevel(value.slice(name.length + 1, -1), /,/);
}

/** CSS Color 5 color-mix() in oklch with premultiplied alpha (what browsers render). */
function mixOklch(a: Oklch, pa: number, b: Oklch, pb: number): Oklch {
  const aa = (a.alpha ?? 1) * pa;
  const ab = (b.alpha ?? 1) * pb;
  const alpha = aa + ab;
  if (alpha === 0) return { mode: "oklch", l: 0, c: 0, h: undefined, alpha: 0 };
  const hue =
    a.h === undefined || aa === 0 ? b.h : b.h === undefined || ab === 0 ? a.h : (a.h * pa + b.h * pb) / (pa + pb);
  return {
    mode: "oklch",
    l: (a.l * aa + b.l * ab) / alpha,
    c: (a.c * aa + b.c * ab) / alpha,
    h: hue,
    alpha,
  };
}

function resolveValue(theme: Theme, value: string, seen: string[]): Oklch {
  const v = value.trim();
  const ref = /^var\(\s*(--[\w-]+)\s*\)$/.exec(v);
  if (ref?.[1]) return resolveVar(theme, ref[1], seen);

  const ld = fnArgs(v, "light-dark");
  if (ld) {
    if (ld.length !== 2) throw new Error(`light-dark() needs two values: ${v}`);
    return resolveValue(theme, theme === "light" ? ld[0]! : ld[1]!, seen);
  }

  const mix = fnArgs(v, "color-mix");
  if (mix) {
    const [space, s1, s2] = mix;
    if (space !== "in oklch" || !s1 || !s2 || mix.length !== 3) throw new Error(`unsupported color-mix: ${v}`);
    const stop = (s: string): [Oklch, number | null] => {
      const parts = splitTopLevel(s, /\s/);
      const pct = parts.length > 1 && parts.at(-1)!.endsWith("%") ? Number(parts.pop()!.slice(0, -1)) / 100 : null;
      return [resolveValue(theme, parts.join(" "), seen), pct];
    };
    const [c1, p1] = stop(s1);
    const [c2, p2] = stop(s2);
    const w1 = p1 ?? (p2 === null ? 0.5 : 1 - p2);
    const w2 = p2 ?? 1 - w1;
    return mixOklch(c1, w1, c2, w2);
  }

  if (v === "transparent") return { mode: "oklch", l: 0, c: 0, h: undefined, alpha: 0 };
  const parsed = parse(v);
  if (!parsed) throw new Error(`not a color: ${v}`);
  const ok = toOklch(parsed);
  return { ...ok, alpha: ok.alpha ?? 1 };
}

function resolveVar(theme: Theme, name: string, seen: string[]): Oklch {
  if (seen.includes(name)) throw new Error(`cycle: ${[...seen, name].join(" -> ")}`);
  const raw = DECLS.get(name);
  if (raw === undefined) throw new Error(`unknown token ${name}`);
  return resolveValue(theme, raw, [...seen, name]);
}

/** `"fg"` → the resolved value of `--color-fg` in the given theme (alpha kept). */
export function resolveToken(theme: Theme, token: string): Oklch {
  return resolveVar(theme, `--color-${token}`, []);
}

/** Every `--color-*` token name (without the prefix). */
export function colorTokenNames(): string[] {
  return [...DECLS.keys()].filter((k) => k.startsWith("--color-")).map((k) => k.slice("--color-".length));
}

/** Whether the token's color sits inside sRGB, so every target browser paints the same value. */
export function isDisplayable(theme: Theme, token: string): boolean {
  return displayable({ ...resolveToken(theme, token), alpha: 1 });
}

/** Source-over compositing in gamma-encoded sRGB, as browsers paint translucent colors. */
export function compositeOver(top: Oklch | Rgb, bottom: Oklch | Rgb): Rgb {
  const t = toRgb(mapToSrgb(top));
  const b = toRgb(mapToSrgb(bottom));
  const a = top.alpha ?? 1;
  if ((bottom.alpha ?? 1) < 1) throw new Error("the backdrop must be opaque");
  return { mode: "rgb", r: t.r * a + b.r * (1 - a), g: t.g * a + b.g * (1 - a), b: t.b * a + b.b * (1 - a), alpha: 1 };
}

/**
 * WCAG contrast of `fg` over `bg` in a theme. A translucent `bg` (the `*-soft` tokens) is first
 * composited over `backdrop` (default `surface`); a translucent `fg` over the result.
 */
export function contrastPairs(theme: Theme, fg: string, bg: string, backdrop = "surface"): number {
  const base = resolveToken(theme, backdrop);
  if ((base.alpha ?? 1) < 1) throw new Error(`backdrop ${backdrop} must be opaque`);
  const back = compositeOver(resolveToken(theme, bg), base);
  const front = compositeOver(resolveToken(theme, fg), back);
  return wcagContrast(front, back);
}
