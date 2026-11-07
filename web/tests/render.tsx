// Shared provider wrapper for component tests (F17): session, React Query, the live store/stream
// (LiveProvider) and, with `route`, the whole admin router on an in-memory history.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryHistory } from "@tanstack/react-router";
import { render, type RenderOptions } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import type { Mock } from "vitest";
import { AdminApp, createAdminRouter, type AdminRouter } from "@/admin/router";
import { LiveProvider, type LiveValue } from "@/admin/live";
import type { Me } from "@/lib/api-types";
import { BoardStore } from "@/lib/board-store";
import type { BoardStreamClient } from "@/lib/board-stream";
import { session } from "@/lib/session";

/** No retries (errors surface at once) and no garbage collection timers left behind after a test. */
export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity, staleTime: Infinity },
      mutations: { retry: false },
    },
  });
}

export type FakeStream = BoardStreamClient & { restart: Mock<() => void>; start: Mock<() => void>; stop: Mock<() => void> };

/** A stream double: tests drive the BoardStore directly and assert restart() calls. */
export function fakeStream(): FakeStream {
  return { restart: vi.fn(), start: vi.fn(), stop: vi.fn(), status: "open" } as unknown as FakeStream;
}

export interface ProviderOptions extends Omit<RenderOptions, "wrapper"> {
  /** Session to start with (sets `session.me` and its CSRF token); omit for no session loaded. */
  me?: Me | null;
  qc?: QueryClient;
  /** Render the admin router at this URL (path + search) instead of `ui`; pass `ui` = null. */
  route?: string;
  /** Override parts of the live context; the default is a fresh BoardStore and a fakeStream(). */
  live?: Partial<LiveValue>;
}

export interface ProviderResult extends ReturnType<typeof render> {
  qc: QueryClient;
  store: BoardStore;
  stream: FakeStream;
  live: LiveValue;
  /** The admin router (only with `route`). */
  router: AdminRouter;
}

export function renderWithProviders(
  ui: ReactElement | null,
  { me, qc = createTestQueryClient(), route, live: liveOverride, ...options }: ProviderOptions = {},
): ProviderResult {
  if (me !== undefined) {
    session.me = me;
    session.csrf = me?.csrf_token ?? null;
  }
  const live: LiveValue = { store: new BoardStore(), stream: fakeStream(), tracker: null, ...liveOverride };

  if (route !== undefined) {
    if (ui !== null) throw new Error("renderWithProviders: pass ui = null together with route");
    const router = createAdminRouter({ qc, history: createMemoryHistory({ initialEntries: [route] }) });
    const result = render(<AdminApp router={router} qc={qc} live={live} />, options);
    return { ...result, qc, live, store: live.store, stream: live.stream as FakeStream, router };
  }

  if (ui === null) throw new Error("renderWithProviders: ui is required without route");
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>
      <LiveProvider value={live}>{children}</LiveProvider>
    </QueryClientProvider>
  );
  const result = render(ui, { wrapper, ...options });
  return {
    ...result,
    qc,
    live,
    store: live.store,
    stream: live.stream as FakeStream,
    get router(): AdminRouter {
      throw new Error("renderWithProviders: no router without route");
    },
  };
}
