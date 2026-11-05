// The notice's simple format (U15), the only parser of it (U14): the editor's live preview and the
// real notice dialog both draw through here, so they can never disagree.
//   - a blank line separates paragraphs; a line break inside a paragraph is kept
//   - a paragraph whose every line starts with "- " is a bulleted list
//   - **text** is bold (within one line)
// There are no links and no HTML: everything else is shown as the characters it is. Rendering
// builds React elements from text nodes only — never dangerouslySetInnerHTML.
import { Fragment, createElement, type ReactNode } from "react";

export type Inline = { t: "text"; v: string } | { t: "strong"; v: string };
export type Block = { t: "p"; lines: Inline[][] } | { t: "ul"; items: Inline[][] };

const BOLD = /\*\*(.+?)\*\*/g;
const BULLET = "- ";

function parseInline(line: string): Inline[] {
  const out: Inline[] = [];
  let at = 0;
  for (const m of line.matchAll(BOLD)) {
    if (m.index > at) out.push({ t: "text", v: line.slice(at, m.index) });
    out.push({ t: "strong", v: m[1]! });
    at = m.index + m[0].length;
  }
  if (at < line.length) out.push({ t: "text", v: line.slice(at) });
  return out;
}

export function parseNoticeMarkup(src: string): Block[] {
  const blocks: Block[] = [];
  let lines: string[] = [];
  const flush = () => {
    if (lines.length === 0) return;
    blocks.push(
      lines.every((l) => l.startsWith(BULLET))
        ? { t: "ul", items: lines.map((l) => parseInline(l.slice(BULLET.length))) }
        : { t: "p", lines: lines.map(parseInline) },
    );
    lines = [];
  };
  for (const line of src.replace(/\r\n?/g, "\n").split("\n")) {
    if (line.trim() === "") flush();
    else lines.push(line);
  }
  flush();
  return blocks;
}

function inlines(parts: Inline[]): ReactNode[] {
  return parts.map((p, i) => (p.t === "strong" ? createElement("strong", { key: i }, p.v) : p.v));
}

/** `<p>` (lines joined by `<br>`), `<ul><li>`, `<strong>`: text nodes only. */
export function renderNoticeMarkup(blocks: Block[]): ReactNode {
  return blocks.map((b, i) =>
    b.t === "p"
      ? createElement(
          "p",
          { key: i },
          b.lines.map((line, j) => createElement(Fragment, { key: j }, j > 0 ? createElement("br") : null, inlines(line))),
        )
      : createElement(
          "ul",
          { key: i },
          b.items.map((item, j) => createElement("li", { key: j }, inlines(item))),
        ),
  );
}
