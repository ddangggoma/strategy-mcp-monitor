import { ChevronDownIcon, DownloadIcon } from "lucide-react";
import { WithReason } from "@/components/app/WithReason";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { copy } from "@/copy/ko";
import type { LogQuery } from "@/lib/api-types";
import { logExportUrl } from "@/lib/endpoints";
import { denyReason } from "@/lib/permissions";
import { useSession } from "@/lib/session";

const FORMATS = ["csv", "jsonl"] as const;

/** Download the current filter set (export_logs): plain links, the browser does the download. */
export function ExportMenu({ query }: { query: LogQuery }) {
  const reason = denyReason(useSession(), "export_logs");
  const label = (
    <>
      <DownloadIcon aria-hidden="true" />
      {copy.logs.export.menu}
      <ChevronDownIcon aria-hidden="true" className="size-3.5 text-fg-muted" />
    </>
  );
  if (reason) {
    return (
      <WithReason reason={reason}>
        <Button variant="outline">{label}</Button>
      </WithReason>
    );
  }
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="outline">{label}</Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {FORMATS.map((f) => (
          <DropdownMenuItem key={f} asChild>
            <a href={logExportUrl(query, f)} download>
              {copy.logs.export[f]}
            </a>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
