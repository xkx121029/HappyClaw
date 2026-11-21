/**
 * Router seam for the ported chat hooks.
 *
 * The dashboard called `react-router-dom`; this app routes with TanStack
 * Router. The ported hooks only ever (a) push a `/chat/...` URL and (b) read
 * the current location's `state.newChat` flag, so one small adapter keeps every
 * call site unchanged and puts the router choice in a single place.
 */
import { useNavigate, useRouterState } from "@tanstack/react-router";

export interface ChatNavigateOptions {
  replace?: boolean;
  state?: unknown;
}

export interface ChatLocation {
  pathname: string;
  state: unknown;
}

export function useChatLocation(): ChatLocation {
  return useRouterState({
    select: (state) => ({
      pathname: state.location.pathname,
      state: state.location.state,
    }),
  });
}

export function useChatNavigate(): (to: string, options?: ChatNavigateOptions) => void {
  const navigate = useNavigate();
  return (to, options) => {
    // `href` takes the path as-is, which is what the ported call sites build
    // (`/chat/<agent>/<thread>?quick=1`); typed route objects belong to the UI
    // layer that owns the route tree.
    void navigate({
      href: to,
      replace: options?.replace ?? false,
      state: options?.state as never,
    });
  };
}
