// Shared provider wrapper for component tests (F17). Task 9 adds `route` (admin router) and
// `store` (LiveProvider) once those exist; this covers the session and React Query.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderOptions } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import type { Me } from "@/lib/api-types";
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

export interface ProviderOptions extends Omit<RenderOptions, "wrapper"> {
  /** Session to start with (sets `session.me` and its CSRF token); omit for no session loaded. */
  me?: Me | null;
  qc?: QueryClient;
}

export function renderWithProviders(ui: ReactElement, { me, qc = createTestQueryClient(), ...options }: ProviderOptions = {}) {
  if (me !== undefined) {
    session.me = me;
    session.csrf = me?.csrf_token ?? null;
  }
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  return { ...render(ui, { wrapper, ...options }), qc };
}
