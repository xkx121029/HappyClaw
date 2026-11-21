import { createRouter } from "@tanstack/react-router";

import { routeTree } from "@/routeTree.gen";

/**
 * `defaultPreload: "intent"` warms a route's chunk on hover/focus, which keeps
 * navigation instant without shipping every page in the initial bundle.
 */
export const router = createRouter({
  routeTree,
  defaultPreload: "intent",
  defaultPreloadStaleTime: 15_000,
  scrollRestoration: true,
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
