// The per-MCP icon (`icon`: one emoji) for the settings form: the same rules as the server
// (server/app/monitor/icons.py, which stays final); both run the shared cases in mcp-icon-cases.json.
// An icon is text drawn in the system emoji font — never markup, a URL or an upload.
export const MAX_ICON_UTF16 = 16;

const ZWJ = String.fromCodePoint(0x200d);
const VS16 = String.fromCodePoint(0xfe0f);
const KEYCAP = String.fromCodePoint(0x20e3);
const KEYCAP_BASES = new Set("0123456789#*");
const BLACK_FLAG = "\u{1f3f4}";
const CANCEL_TAG = "\u{e007f}";

const BASE_RANGES: readonly (readonly [number, number])[] = [
  [0x00a9, 0x00a9], [0x00ae, 0x00ae], [0x203c, 0x203c], [0x2049, 0x2049], [0x2122, 0x2122],
  [0x2139, 0x2139], [0x2190, 0x21ff], [0x2300, 0x23ff], [0x24c2, 0x24c2], [0x25a0, 0x25ff],
  [0x2600, 0x27bf], [0x2900, 0x297f], [0x2b00, 0x2bff], [0x3030, 0x3030], [0x303d, 0x303d],
  [0x3297, 0x3297], [0x3299, 0x3299], [0x1f000, 0x1faff],
];
const BASE_CATEGORY = /^[\p{So}\p{Sm}\p{Po}\p{Pd}\p{Ll}]$/u;
const UNASSIGNED = /^\p{Cn}$/u;
const NEW_EMOJI: readonly [number, number] = [0x1f900, 0x1faff];

const cp = (c: string) => c.codePointAt(0)!;
const within = (n: number, [lo, hi]: readonly [number, number]) => lo <= n && n <= hi;
const regional = (c: string) => within(cp(c), [0x1f1e6, 0x1f1ff]);
const modifier = (c: string) => within(cp(c), [0x1f3fb, 0x1f3ff]);
const tag = (c: string) => within(cp(c), [0xe0020, 0xe007e]);

function base(c: string): boolean {
  const n = cp(c);
  if (regional(c) || modifier(c) || !BASE_RANGES.some((r) => within(n, r))) return false;
  return BASE_CATEGORY.test(c) || (UNASSIGNED.test(c) && within(n, NEW_EMOJI));
}

/** One ZWJ element: a base, then optionally U+FE0F, then optionally a skin-tone modifier. */
function element(part: string): boolean {
  const cps = [...part];
  if (cps.length === 0 || !base(cps[0]!)) return false;
  let rest = cps.slice(1);
  if (rest[0] === VS16) rest = rest.slice(1);
  return rest.length === 0 || (rest.length === 1 && modifier(rest[0]!));
}

/** Exactly one emoji: a flag, a keycap, a tag sequence or ZWJ-joined elements; ≤ 16 UTF-16 units. */
export function isMcpEmoji(value: unknown): value is string {
  if (typeof value !== "string" || value === "" || value.length > MAX_ICON_UTF16) return false;
  const cps = [...value];
  if (cps.length === 2 && regional(cps[0]!) && regional(cps[1]!)) return true;
  if (KEYCAP_BASES.has(cps[0]!)) {
    const rest = cps.slice(1).join("");
    return rest === KEYCAP || rest === VS16 + KEYCAP;
  }
  if (cps[0] === BLACK_FLAG && cps.length > 2 && tag(cps[1]!)) {
    return cps.at(-1) === CANCEL_TAG && cps.slice(1, -1).every(tag);
  }
  return value.split(ZWJ).every(element);
}

/** The picker's ready-made emoji, by group (names: copy.mcp.icon.names, group labels: copy.mcp.icon.groups). */
export const CURATED_EMOJI = {
  tech: ["🤖", "🧠", "✨", "💡", "⚙️", "🛠️", "🔧", "💻", "🖥️", "🗄️", "☁️", "🌐", "🔌", "📡", "🛰️", "🧩", "🔬", "🧪"],
  data: ["📊", "📈", "📉", "📁", "📂", "📄", "🗂️", "🔍", "🧾", "📚", "📝", "📦"],
  talk: ["💬", "✉️", "📧", "📞", "🔔", "📣", "🌍"],
  daily: ["☀️", "🌤️", "🌧️", "❄️", "⏰", "🕒", "📅", "🧮", "🗺️", "📍", "🎵", "🎨", "📷", "🛒", "💳", "🍽️"],
  status: ["🔒", "🛡️", "🔑", "🚀", "⭐", "🔥", "⚡", "🎯", "🏁"],
} as const;

export type EmojiGroup = keyof typeof CURATED_EMOJI;
export type CuratedEmoji = (typeof CURATED_EMOJI)[EmojiGroup][number];
