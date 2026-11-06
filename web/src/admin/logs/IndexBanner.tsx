import { InfoIcon } from "lucide-react";
import { copy } from "@/copy/ko";
import { useLogStatus } from "../queries";

/** While the log index is still being built, results may be missing lines: say so (re-read every 5 s). */
export function IndexBanner() {
  const { data } = useLogStatus();
  if (!data || data.ready) return null;
  return (
    <div role="status" className="flex items-start gap-2 rounded-md border bg-surface px-4 py-3 text-sm text-fg">
      <InfoIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-fg-muted" />
      <p>{copy.logs.indexing(data.pending_files)}</p>
    </div>
  );
}
