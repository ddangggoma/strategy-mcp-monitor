import { CopyIcon } from "lucide-react";
import { useMemo } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { copy } from "@/copy/ko";
import type { ScriptExt } from "@/lib/api-types";

/** Lines of a script (CRLF from the server or LF); a final newline does not add an empty line. */
function splitLines(content: string): string[] {
  const lines = content.split(/\r\n?|\n/);
  if (lines.length > 1 && lines[lines.length - 1] === "") lines.pop();
  return lines;
}

/**
 * A script for reading (U18: no editor bundle for people who cannot edit): numbered lines in the
 * mono face on the sunken surface, and a copy button that copies the script exactly as stored.
 * Line numbers are not selectable, so a manual selection copies code only.
 */
export function ScriptViewer({ content, ext, label }: { content: string; ext: ScriptExt; label?: string }) {
  const lines = useMemo(() => splitLines(content), [content]);

  const copyAll = () => {
    navigator.clipboard.writeText(content).then(
      () => toast.success(copy.common.copied),
      () => toast.error(copy.common.copyFailed),
    );
  };

  return (
    <div data-testid="script-viewer" className="flex min-w-0 flex-col overflow-hidden rounded-md border border-border bg-sunken">
      <div className="flex items-center justify-between gap-2 border-b border-border px-3 py-1">
        <span className="text-xs text-fg-muted">
          <span className="font-mono">{ext}</span> {copy.scripts.readOnly}
        </span>
        <Button variant="ghost" size="sm" onClick={copyAll}>
          <CopyIcon aria-hidden="true" />
          {copy.common.copyText}
        </Button>
      </div>
      <pre
        // a scrolling box must take keyboard focus to be scrolled without a mouse (WCAG 2.1.1, axe scrollable-region-focusable)
        // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
        tabIndex={0}
        aria-label={label}
        className="max-h-[60vh] overflow-auto py-2 font-mono text-sm leading-relaxed text-fg"
      >
        <code>
          {lines.map((line, i) => (
            // lines of one script never reorder
            <span key={i} data-testid="script-line" className="block pr-4">
              <span aria-hidden="true" className="inline-block w-12 pr-3 text-right text-fg-muted tabular-nums select-none">
                {i + 1}
              </span>
              <span className="whitespace-pre">{line}</span>
            </span>
          ))}
        </code>
      </pre>
    </div>
  );
}
