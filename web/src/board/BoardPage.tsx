import { CircleDashedIcon, SettingsIcon } from "lucide-react";
import { LazyMotion, MotionConfig, domMax } from "motion/react";
import { useCallback, useEffect, useState } from "react";
import { TopBar } from "@/components/app/TopBar";
import { ConnectionBanner } from "@/components/status/ConnectionBanner";
import { McpCard } from "@/components/status/McpCard";
import { SessionCard } from "@/components/status/SessionCard";
import { STATE_ICONS, STATE_TEXT } from "@/components/status/StatusBadge";
import { Skeleton } from "@/components/ui/skeleton";
import { copy } from "@/copy/ko";
import type { BoardItem, McpState } from "@/lib/api-types";
import { sortBoard, useBoard, type BoardStore } from "@/lib/board-store";
import type { BoardStreamClient } from "@/lib/board-stream";
import { bootstrapStatus, logout } from "@/lib/endpoints";
import { clearSession, refreshSession, useSession } from "@/lib/session";
import { cn } from "@/lib/utils";
import { BoardOverview, LiveStatus } from "./BoardOverview";
import { latestCheck } from "./overview";
import { SystemPanel } from "./SystemPanel";

const GRID = "grid grid-cols-[repeat(auto-fill,minmax(min(var(--size-board-card),100%),1fr))] gap-4";
const SKELETON_CARDS = [0, 1, 2, 3, 4, 5];
const QUIET: ReadonlySet<McpState> = new Set(["HEALTHY", "MAINTENANCE"]);

interface Verdict {
  text: string;
  state: McpState | null;
}

/** The board's one bold sentence: the count of problems, in the color of the worst state. */
function verdict(sorted: BoardItem[]): Verdict {
  const worst = sorted[0];
  if (!worst) return { text: copy.board.noMcp, state: null };
  const problems = sorted.filter((i) => !QUIET.has(i.state)).length;
  if (problems > 0) return { text: copy.board.problems(problems), state: worst.state };
  const maintenance = sorted.filter((i) => i.state === "MAINTENANCE").length;
  if (maintenance > 0) return { text: copy.board.maintenanceOnly(maintenance), state: "MAINTENANCE" };
  return { text: copy.board.allHealthy, state: "HEALTHY" };
}

/** Local channel, nobody logged in: ask once whether the first Admin still has to be created. */
function useSetupNeeded(check: boolean): boolean {
  const [needed, setNeeded] = useState(false);
  useEffect(() => {
    if (!check) return;
    let current = true;
    bootstrapStatus().then(
      (r) => {
        if (current) setNeeded(r.needed);
      },
      () => {}, // not knowing only hides a hint
    );
    return () => {
      current = false;
    };
  }, [check]);
  return check && needed;
}

/**
 * Anonymous status board: who is connected, then the verdict, then MCP cards problems-first
 * (docs/design/screens/board.md). Live data comes from the BoardStore the SSE stream feeds.
 */
export function BoardPage({ store, stream }: { store: BoardStore; stream: BoardStreamClient }) {
  const board = useBoard(store);
  const me = useSession();
  const setupNeeded = useSetupNeeded(me?.channel === "local" && me.user === null);

  const onLogout = useCallback(async () => {
    try {
      await logout();
    } catch {
      await refreshSession().catch(() => {}); // still logged in: show what the server says
      return;
    }
    clearSession();
    stream.restart(); // the stream keeps the auth level it connected with
  }, [stream]);

  const loading = board.now === null;
  const sorted = sortBoard(board.items.values());
  const v = verdict(sorted);
  const VerdictIcon = v.state ? STATE_ICONS[v.state] : CircleDashedIcon;

  return (
    <LazyMotion features={domMax} strict>
      <MotionConfig reducedMotion="user">
        <a
          href="#main"
          className="sr-only rounded-md bg-accent px-3 py-2 text-sm font-medium text-accent-fg focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-(--z-tooltip)"
        >
          {copy.common.skipToContent}
        </a>
        <TopBar me={me} streamStatus={board.status} onLogout={onLogout} />
        <main id="main" tabIndex={-1} className="flex flex-col gap-8 px-4 py-6 outline-none sm:px-6 2xl:px-8 2xl:py-8">
          {setupNeeded ? (
            <p className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-border-strong bg-surface px-4 py-3 text-sm">
              <SettingsIcon aria-hidden="true" className="size-4 shrink-0 text-fg-muted" />
              <span>{copy.board.setupHint}</span>
              <a href="/admin/setup" className="font-semibold text-fg underline underline-offset-4">
                {copy.board.setupLink}
              </a>
            </p>
          ) : null}

          <section aria-label={copy.board.sessionsTitle} className="flex flex-col gap-3">
            {loading ? (
              <Skeleton className="h-7 w-40" />
            ) : (
              <>
                <ConnectionBanner sessions={board.sessions} />
                {board.sessions && board.sessions.length > 0 ? (
                  <div className="grid grid-cols-[repeat(auto-fill,minmax(min(24rem,100%),1fr))] gap-4">
                    {board.sessions.map((s) => (
                      <SessionCard key={s.session_id} session={s} />
                    ))}
                  </div>
                ) : null}
              </>
            )}
          </section>

          <section aria-labelledby="board-verdict" className="flex flex-col gap-5">
            <div data-anim="rise" className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
              <div aria-live="polite" className="min-w-0">
                <h1
                  id="board-verdict"
                  className={cn(
                    "flex items-center gap-3 text-display font-bold",
                    loading ? "text-fg-muted" : v.state ? STATE_TEXT[v.state] : "text-fg",
                  )}
                >
                  {loading ? null : <VerdictIcon aria-hidden="true" className="size-[0.8em] shrink-0" />}
                  {loading ? copy.board.title : v.text}
                </h1>
                {!loading && sorted.length === 0 ? <p className="mt-2 text-base text-fg-muted">{copy.board.noMcpHint}</p> : null}
              </div>
              {/* outside the live region: its "n초 전" changes every second */}
              {loading ? null : <LiveStatus status={board.status} lastCheckAt={latestCheck(sorted)} className="mb-1.5" />}
            </div>

            {loading ? null : <BoardOverview items={board.items} />}

            {loading ? (
              <>
                <p role="status" className="sr-only">
                  {copy.common.loading}
                </p>
                <div className={GRID} aria-hidden="true">
                  {SKELETON_CARDS.map((i) => (
                    <Skeleton key={i} data-testid="card-skeleton" className="h-56 rounded-md" />
                  ))}
                </div>
              </>
            ) : sorted.length > 0 ? (
              // cards are direct grid children: McpCard spans five subgrid rows of this grid
              <div className={GRID}>
                {sorted.map((item) => (
                  <McpCard key={item.id} item={item} receivedAt={board.receivedAt.get(item.id) ?? 0} />
                ))}
              </div>
            ) : null}
          </section>

          {loading ? null : <SystemPanel system={board.system} />}
        </main>
      </MotionConfig>
    </LazyMotion>
  );
}
