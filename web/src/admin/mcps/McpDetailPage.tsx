import { Link, getRouteApi } from "@tanstack/react-router";
import { OctagonAlertIcon } from "lucide-react";
import { useState } from "react";
import { InfoTip, type HelpContent } from "@/components/app/InfoTip";
import { McpIcon } from "@/components/status/McpIcon";
import { StatusBadge } from "@/components/status/StatusBadge";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { copy } from "@/copy/ko";
import { ApiError } from "@/lib/api";
import type { Issue, McpDetail, McpState } from "@/lib/api-types";
import { useMcp } from "../queries";
import type { McpTab } from "../router";
import { ScriptsTab } from "../scripts/ScriptsTab";
import { LeaveGuard } from "../shell/LeaveGuard";
import { ConfigErrorBadge } from "./ConfigErrorBadge";
import { DeleteMcpDialog } from "./DeleteMcpDialog";
import { HistoryTab } from "./HistoryTab";
import { McpActions } from "./McpActions";
import { OwnerTransferDialog } from "./OwnerTransferDialog";
import { SettingsTab } from "./SettingsTab";

const route = getRouteApi("/authed/admin/mcps/$mcpId");

/** A path id the server could know: a positive integer ("abc" never reaches the API). */
function parseId(raw: string): number | null {
  return /^[1-9]\d{0,15}$/.test(raw) ? Number(raw) : null;
}

/**
 * One MCP: header (state, endpoint, owner, manual actions, ownership transfer, delete), the
 * config-error warning, and three tabs kept in `?tab=` (settings by default). The settings form
 * stays mounted while another tab is open, so unsaved edits survive a look at the history.
 */
export function McpDetailPage() {
  const { mcpId } = route.useParams();
  const id = parseId(mcpId);
  const query = useMcp(id ?? 0, { enabled: id !== null });

  const notFound = id === null || (query.error instanceof ApiError && query.error.status === 404);
  if (notFound) return <NotFound />;
  // keyed by id: moving to another MCP starts a fresh form (no edits carried across)
  if (query.data) return <Detail key={query.data.id} mcp={query.data} />;
  if (query.isError) {
    return (
      <p role="alert" className="text-sm text-fg">
        {copy.mcp.loadError}
      </p>
    );
  }
  return (
    <div role="status" className="flex flex-col gap-3">
      <span className="sr-only">{copy.common.loading}</span>
      <Skeleton className="h-8 w-48" />
      <Skeleton className="h-5 w-72" />
      <Skeleton className="h-9 w-full max-w-(--size-prose)" />
    </div>
  );
}

/** What the MCP's state (and its issue, if any) means right now. */
function stateHelp(state: McpState, issue: Issue | null): HelpContent {
  if (!issue) return copy.help.states[state];
  return { lead: copy.help.states[state], items: [[copy.issues[issue], copy.help.issues[issue]]] };
}

function NotFound() {
  return (
    <div className="flex max-w-(--size-prose) flex-col items-start gap-3">
      <h1 className="text-xl font-semibold text-fg">{copy.mcp.detail}</h1>
      <p className="text-sm text-fg">{copy.mcp.notFound}</p>
      <Link to="/admin/mcps" className="text-sm font-semibold text-fg underline underline-offset-4">
        {copy.mcp.backToList}
      </Link>
    </div>
  );
}

function Detail({ mcp }: { mcp: McpDetail }) {
  const { tab = "settings" } = route.useSearch();
  const navigate = route.useNavigate();
  const [settingsDirty, setSettingsDirty] = useState(false);
  const [scriptsDirty, setScriptsDirty] = useState(false);

  return (
    <div className="flex min-w-0 flex-col gap-5">
      <header className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="flex min-w-0 flex-col gap-1.5">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="inline-flex min-w-0 items-center gap-3">
              <McpIcon icon={mcp.icon} size="lg" />
              <h1 className="text-xl font-semibold break-all text-fg">{mcp.name}</h1>
            </span>
            {mcp.config_error ? (
              <ConfigErrorBadge size="lg" />
            ) : mcp.live ? (
              <span className="inline-flex items-center gap-1">
                <StatusBadge state={mcp.live.state} issue={mcp.live.issue} size="lg" />
                <InfoTip label={copy.help.stateLabel} content={stateHelp(mcp.live.state, mcp.live.issue)} side="bottom" align="start" />
              </span>
            ) : (
              <span className="text-sm text-fg-muted">{copy.mcp.noLive}</span>
            )}
          </div>
          <dl className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
            <div className="flex min-w-0 gap-2">
              <dt className="text-fg-muted">{copy.mcp.hostPort}</dt>
              <dd className="font-mono break-all text-fg">{`${mcp.host}:${mcp.port}`}</dd>
            </div>
            <div className="flex items-center gap-2">
              <dt className="flex items-center gap-0.5 text-fg-muted">
                {copy.mcp.owner}
                <InfoTip label={copy.mcp.owner} content={copy.help.mcp.owner} />
              </dt>
              <dd className={mcp.owner ? "text-fg" : "text-fg-muted"}>{mcp.owner?.name ?? copy.mcp.noOwner}</dd>
            </div>
          </dl>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <McpActions mcp={mcp} />
          <InfoTip label={copy.mcp.columns.actions} content={copy.help.mcp.actions} side="bottom" align="end" />
          <span aria-hidden="true" className="mx-1 hidden h-6 w-px bg-border sm:block" />
          <OwnerTransferDialog mcp={mcp} />
          <DeleteMcpDialog mcp={mcp} />
        </div>
      </header>

      {mcp.config_error ? (
        <div role="alert" className="flex items-start gap-3 rounded-md border border-border-strong bg-surface px-4 py-3 text-sm text-fg">
          <OctagonAlertIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          <p>{copy.mcp.configError}</p>
        </div>
      ) : null}

      <Tabs value={tab} onValueChange={(v) => void navigate({ search: (s) => ({ ...s, tab: v as McpTab }), replace: true })}>
        <TabsList variant="line">
          <TabsTrigger value="settings">{copy.mcp.tabs.settings}</TabsTrigger>
          <TabsTrigger value="scripts">{copy.mcp.tabs.scripts}</TabsTrigger>
          <TabsTrigger value="history">{copy.mcp.tabs.history}</TabsTrigger>
        </TabsList>
        {/* kept mounted (hidden) so unsaved edits survive switching tabs */}
        <TabsContent value="settings" forceMount hidden={tab !== "settings"} className="pt-4">
          <SettingsTab mcp={mcp} onDirtyChange={setSettingsDirty} />
        </TabsContent>
        <TabsContent value="scripts" className="pt-4">
          <ScriptsTab mcp={mcp} onDirtyChange={setScriptsDirty} />
        </TabsContent>
        <TabsContent value="history" className="pt-4">
          <HistoryTab mcpId={mcp.id} />
        </TabsContent>
      </Tabs>
      <LeaveGuard when={settingsDirty || scriptsDirty} />
    </div>
  );
}
