import { diffLines } from "diff";
import { useMemo } from "react";
import { copy } from "@/copy/ko";

type Op = "same" | "add" | "del";

interface Row {
  op: Op;
  before: number | null;
  after: number | null;
  text: string;
}

/** LF line endings and a final newline: the server stores CRLF, the editor hands out LF. */
function normalize(s: string): string {
  const lf = s.replace(/\r\n?/g, "\n");
  return lf === "" || lf.endsWith("\n") ? lf : lf + "\n";
}

export function diffRows(before: string, after: string): { rows: Row[]; added: number; removed: number } {
  const rows: Row[] = [];
  let b = 0;
  let a = 0;
  let added = 0;
  let removed = 0;
  for (const part of diffLines(normalize(before), normalize(after))) {
    const op: Op = part.added ? "add" : part.removed ? "del" : "same";
    const lines = part.value.replace(/\n$/, "").split("\n");
    for (const text of lines) {
      if (op === "del") {
        removed++;
        rows.push({ op, before: ++b, after: null, text });
      } else if (op === "add") {
        added++;
        rows.push({ op, before: null, after: ++a, text });
      } else {
        rows.push({ op, before: ++b, after: ++a, text });
      }
    }
  }
  return { rows, added, removed };
}

const ROW_BG: Record<Op, string | undefined> = { same: undefined, add: "bg-diff-add", del: "bg-diff-del" };

/**
 * Line diff of two texts (jsdiff `diffLines`, U19): both line numbers, a +/− sign next to the tint
 * (colour is never the only cue, and the sign is named for screen readers), no animation. The table
 * scrolls inside its own frame; long lines scroll sideways instead of wrapping.
 */
export function TextDiff({ before, after, labels }: { before: string; after: string; labels: [string, string] }) {
  const { rows, added, removed } = useMemo(() => diffRows(before, after), [before, after]);
  const caption = copy.diff.caption(labels[0], labels[1]);
  const changed = added + removed > 0;

  return (
    <div className="flex min-w-0 flex-col gap-2">
      <p className="text-sm text-fg-muted">{changed ? copy.diff.summary(removed, added) : copy.diff.same}</p>
      <div
        role="region"
        aria-label={caption}
        // a scrolling box must take keyboard focus to be scrolled without a mouse (WCAG 2.1.1, axe scrollable-region-focusable)
        // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
        tabIndex={0}
        className="max-h-[60vh] overflow-auto rounded-md border border-border bg-surface"
      >
        <table className="w-full border-collapse font-mono text-xs">
          <caption className="sr-only">{caption}</caption>
          <thead className="sticky top-0 bg-surface text-fg-muted">
            <tr className="border-b border-border">
              <th scope="col" className="w-px px-2 py-1 text-right font-sans font-medium whitespace-nowrap">
                {labels[0]}
              </th>
              <th scope="col" className="w-px px-2 py-1 text-right font-sans font-medium whitespace-nowrap">
                {labels[1]}
              </th>
              <th scope="col" className="w-px px-1 py-1">
                <span className="sr-only">{copy.diff.change}</span>
              </th>
              <th scope="col" className="px-2 py-1">
                <span className="sr-only">{copy.diff.content}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              // rows never reorder: the index is a stable key for one diff
              <tr key={i} data-op={r.op} className={ROW_BG[r.op]}>
                <td className="w-px px-2 text-right whitespace-nowrap text-fg-muted tabular-nums select-none">{r.before ?? ""}</td>
                <td className="w-px px-2 text-right whitespace-nowrap text-fg-muted tabular-nums select-none">{r.after ?? ""}</td>
                <td className="w-px px-1 text-center text-fg select-none">
                  {r.op === "same" ? null : (
                    <>
                      <span aria-hidden="true">{r.op === "add" ? "+" : "−"}</span>
                      <span className="sr-only">{r.op === "add" ? copy.diff.added : copy.diff.removed}</span>
                    </>
                  )}
                </td>
                <td className="px-2 whitespace-pre text-fg">{r.text}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
