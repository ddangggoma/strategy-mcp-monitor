// Admin routes (TanStack Router, code-based, full paths without basepath). Pages load per route
// (lazyRouteComponent); the shell is eager because every logged-in page needs it.
import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import {
  Link,
  Outlet,
  RouterProvider,
  createRootRouteWithContext,
  createRoute,
  createRouter,
  lazyRouteComponent,
  redirect,
  type RouterHistory,
} from "@tanstack/react-router";
import { MotionConfig } from "motion/react";
import { buttonVariants } from "@/components/ui/button";
import { copy } from "@/copy/ko";
import type { McpState, ScriptKind } from "@/lib/api-types";
import { bootstrapStatus } from "@/lib/endpoints";
import { session } from "@/lib/session";
import { AppShell } from "./shell/AppShell";
import { LiveProvider, type LiveValue } from "./live";
import { parseAuditSearch, parseLogSearch, type AuditSearch, type LogSearch } from "./logs/search";
import { qk } from "./query-keys";
import { parseDays, type SessionDays } from "./sessions/period";

export interface RouterContext {
  qc: QueryClient;
}

export interface LoginSearch {
  redirect?: string;
  email?: string;
}
/** Sessions screen period (days); 7 when absent. */
export interface SessionsSearch {
  days?: SessionDays;
}
export type McpTab = "settings" | "scripts" | "history";
export interface McpDetailSearch {
  tab?: McpTab;
  kind?: ScriptKind;
}

const STATES: ReadonlySet<string> = new Set<McpState>(["HEALTHY", "SUSPECT", "ACTION", "RECOVERING", "FAILED", "MAINTENANCE"]);
const TABS: ReadonlySet<string> = new Set<McpTab>(["settings", "scripts", "history"]);
const KINDS: ReadonlySet<string> = new Set<ScriptKind>(["start", "stop", "restart"]);

/** A search value from the URL as a string (TanStack parses `?a=1` to a number), else undefined. */
function str(v: unknown): string | undefined {
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  return undefined;
}

function oneOf<T extends string>(set: ReadonlySet<string>, v: unknown): T | undefined {
  const s = str(v);
  return s !== undefined && set.has(s) ? (s as T) : undefined;
}

/** Local, nobody logged in, no user yet: the first Admin has to be created. Errors count as "no". */
async function setupNeeded(qc: QueryClient): Promise<boolean> {
  const me = session.me;
  if (me?.channel !== "local" || me.user) return false; // the external channel never asks
  try {
    const r = await qc.fetchQuery({ queryKey: qk.bootstrap, queryFn: bootstrapStatus, staleTime: 0 });
    return r.needed;
  } catch {
    return false;
  }
}

/** Heading, what happened and the way back; inside the shell for a logged-in user (authedRoute). */
function NotFoundBody() {
  return (
    <div className="flex max-w-(--size-prose) flex-col items-start gap-3">
      <h1 className="text-xl font-semibold text-fg">{copy.common.notFoundTitle}</h1>
      <p className="text-sm text-fg">{copy.common.notFound}</p>
      <Link to="/admin" className={buttonVariants({ variant: "outline" })}>
        {copy.common.adminHome}
      </Link>
    </div>
  );
}

/** Outside every route (no shell): a page of its own with a main landmark. */
function NotFound() {
  return (
    <main className="mx-auto max-w-(--size-prose) px-6 py-16">
      <NotFoundBody />
    </main>
  );
}

const rootRoute = createRootRouteWithContext<RouterContext>()({
  component: Outlet,
  notFoundComponent: NotFound,
});

const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/admin/login",
  validateSearch: (s: Record<string, unknown>): LoginSearch => ({ redirect: str(s.redirect), email: str(s.email) }),
  beforeLoad: async ({ context }) => {
    if (await setupNeeded(context.qc)) throw redirect({ to: "/admin/setup" });
  },
  component: lazyRouteComponent(() => import("./auth/LoginPage"), "LoginPage"),
});

const setupRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/admin/setup",
  beforeLoad: async ({ context }) => {
    if (!(await setupNeeded(context.qc))) throw redirect({ to: "/admin/login" });
  },
  component: lazyRouteComponent(() => import("./auth/SetupPage"), "SetupPage"),
});

/** Every page below needs a logged-in user; otherwise login, then back here. */
const authedRoute = createRoute({
  getParentRoute: () => rootRoute,
  id: "authed",
  beforeLoad: ({ location }) => {
    if (!session.me?.user) throw redirect({ to: "/admin/login", search: { redirect: location.href } });
  },
  component: AppShell,
  // any other /admin path for a logged-in user: the not-found page keeps the shell and navigation
  notFoundComponent: NotFoundBody,
});

const dashboardRoute = createRoute({
  getParentRoute: () => authedRoute,
  path: "/admin",
  component: lazyRouteComponent(() => import("./dashboard/DashboardPage"), "DashboardPage"),
});

const mcpListRoute = createRoute({
  getParentRoute: () => authedRoute,
  path: "/admin/mcps",
  validateSearch: (s: Record<string, unknown>): { state?: McpState } => ({ state: oneOf<McpState>(STATES, s.state) }),
  component: lazyRouteComponent(() => import("./mcps/McpListPage"), "McpListPage"),
});

const mcpCreateRoute = createRoute({
  getParentRoute: () => authedRoute,
  path: "/admin/mcps/new",
  component: lazyRouteComponent(() => import("./mcps/McpCreatePage"), "McpCreatePage"),
});

const mcpDetailRoute = createRoute({
  getParentRoute: () => authedRoute,
  path: "/admin/mcps/$mcpId",
  validateSearch: (s: Record<string, unknown>): McpDetailSearch => ({
    tab: oneOf<McpTab>(TABS, s.tab),
    kind: oneOf<ScriptKind>(KINDS, s.kind),
  }),
  component: lazyRouteComponent(() => import("./mcps/McpDetailPage"), "McpDetailPage"),
});

const sessionsRoute = createRoute({
  getParentRoute: () => authedRoute,
  path: "/admin/sessions",
  validateSearch: (s: Record<string, unknown>): SessionsSearch => ({ days: parseDays(s.days) }),
  component: lazyRouteComponent(() => import("./sessions/SessionsPage"), "SessionsPage"),
});

/** Filters live only in the URL (W34); malformed values are dropped by the parsers. */
const logsRoute = createRoute({
  getParentRoute: () => authedRoute,
  path: "/admin/logs",
  validateSearch: (s: Record<string, unknown>): LogSearch => parseLogSearch(s),
  component: lazyRouteComponent(() => import("./logs/LogsPage"), "LogsPage"),
});

const auditRoute = createRoute({
  getParentRoute: () => authedRoute,
  path: "/admin/audit",
  validateSearch: (s: Record<string, unknown>): AuditSearch => parseAuditSearch(s),
  component: lazyRouteComponent(() => import("./audit/AuditPage"), "AuditPage"),
});

const usersRoute = createRoute({
  getParentRoute: () => authedRoute,
  path: "/admin/users",
  component: lazyRouteComponent(() => import("./users/UsersPage"), "UsersPage"),
});

const settingsRoute = createRoute({
  getParentRoute: () => authedRoute,
  path: "/admin/settings",
  component: lazyRouteComponent(() => import("./settings/SettingsPage"), "SettingsPage"),
});

const noticeRoute = createRoute({
  getParentRoute: () => authedRoute,
  path: "/admin/notice",
  component: lazyRouteComponent(() => import("./notice/NoticeEditorPage"), "NoticeEditorPage"),
});

const routeTree = rootRoute.addChildren([
  loginRoute,
  setupRoute,
  authedRoute.addChildren([
    dashboardRoute,
    mcpListRoute,
    mcpCreateRoute,
    mcpDetailRoute,
    sessionsRoute,
    logsRoute,
    auditRoute,
    usersRoute,
    settingsRoute,
    noticeRoute,
  ]),
]);

export function createAdminRouter({ qc, history }: { qc: QueryClient; history?: RouterHistory }) {
  return createRouter({
    routeTree,
    history,
    context: { qc },
    defaultViewTransition: true,
    // the API is the cache (React Query); route loaders do not cache anything themselves
    defaultPreloadStaleTime: 0,
    scrollRestoration: true,
  });
}

export type AdminRouter = ReturnType<typeof createAdminRouter>;

/** One-time note for the login page, carried in history state (not in the URL). */
export type LoginFlash = "setup_done" | "bootstrap_done" | "expired";

declare module "@tanstack/react-router" {
  interface Register {
    router: AdminRouter;
  }
  interface HistoryState {
    flash?: LoginFlash;
  }
}

/** Providers + router: one QueryClient, one live store/stream for the whole tab. */
export function AdminApp({ router, qc, live }: { router: AdminRouter; qc: QueryClient; live: LiveValue }) {
  return (
    <QueryClientProvider client={qc}>
      <LiveProvider value={live}>
        {/* Motion follows prefers-reduced-motion on every admin page (Global Constraints) */}
        <MotionConfig reducedMotion="user">
          <RouterProvider router={router} />
        </MotionConfig>
      </LiveProvider>
    </QueryClientProvider>
  );
}
