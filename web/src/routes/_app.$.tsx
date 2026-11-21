import { createFileRoute, notFound, redirect } from "@tanstack/react-router";

import { resolveLegacyPath } from "@/lib/legacy-routes";

/**
 * Catches every path the new shell does not own. Old dashboard URLs are
 * redirected (keeping ?search and #hash); anything else is a real 404.
 */
export const Route = createFileRoute("/_app/$")({
  beforeLoad: ({ location }) => {
    const target = resolveLegacyPath(location.pathname);
    if (!target) throw notFound();
    // TanStack strips the leading "#" from location.hash; put it back so the
    // bookmark's anchor survives the hop.
    const hash = location.hash
      ? location.hash.startsWith("#")
        ? location.hash
        : `#${location.hash}`
      : "";
    throw redirect({
      href: `${target}${location.searchStr}${hash}`,
      replace: true,
    });
  },
});
