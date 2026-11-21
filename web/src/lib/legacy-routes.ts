/**
 * Every URL the old dashboard served, mapped onto the new shell.
 *
 * Two rules from the migration review:
 *  - nothing 404s: a bookmarked old URL always lands somewhere real;
 *  - `?search` and `#hash` survive the hop, because 15 of the old redirects
 *    were `RedirectPreserveSearch` and users may have them bookmarked.
 *
 * `target` is the final home of that page. A target only takes effect once the
 * route exists in the new shell; until then the hop lands on `fallback`, so the
 * table can be written once and filled in batch by batch (see
 * `docs/MIGRATION-PLAN.md`).
 */

export interface LegacyRedirect {
  target: string;
  batch?: "B1" | "B2" | "B3" | "B4" | "B5" | "B6";
}

const FALLBACK = "/home";

export const legacyRedirects: Record<string, LegacyRedirect> = {
  // Old top-level entries.
  "/workspace": { target: "/experts", batch: "B3" },
  "/sessions": { target: "/chat" },
  "/cron-jobs": { target: "/tasks", batch: "B3" },
  "/models": { target: "/admin/models", batch: "B4" },
  "/plugins": { target: "/admin/plugins", batch: "B2" },
  "/updates": { target: "/admin/advanced", batch: "B4" },
  "/advanced-settings": { target: "/admin/advanced", batch: "B4" },
  "/environments": { target: "/admin/advanced", batch: "B4" },

  // Personalization tabs that became their own top-level pages.
  "/skills": { target: "/personalization/skills", batch: "B3" },
  "/skills/*": { target: "/personalization/skills", batch: "B3" },
  "/channels": { target: "/personalization/channels", batch: "B3" },
  "/subagents": { target: "/personalization/subagents", batch: "B3" },
  "/mbti": { target: "/personalization/mbti", batch: "B3" },
  "/memory": { target: "/personalization/memory", batch: "B3" },
  "/personalization/acp": { target: "/acp", batch: "B3" },

  // Workbench and remote control.
  "/terminal": { target: "/workbench/terminal", batch: "B6" },
  "/remote-browser": { target: "/workbench/browser", batch: "B6" },
  "/remote-phone": { target: "/remote-desktop/link", batch: "B6" },
  "/remote-android": { target: "/remote-desktop/link", batch: "B6" },
  "/remote-desktop/phone": { target: "/remote-desktop/link", batch: "B6" },
  "/remote-desktop/phone/screen": { target: "/remote-desktop/link", batch: "B6" },
  "/remote-desktop/phone/shell": { target: "/remote-desktop/link", batch: "B6" },

  // Admin entries that were retired or merged.
  "/admin/users": { target: "/chat" },
  "/admin/sso": { target: "/chat" },
  "/admin/agents": { target: "/chat" },
  "/admin/shared-models": { target: "/admin/models", batch: "B4" },
  "/admin/audit": { target: "/admin/security", batch: "B4" },
  "/admin/voice": { target: "/admin/models", batch: "B4" },
  "/admin/updates": { target: "/admin/advanced", batch: "B4" },
  "/admin/storage": { target: "/admin/backend", batch: "B2" },

  // Bookmarks from the pre-HappyClaw eras. The path literals are historical and
  // stay verbatim on purpose: they are what users have in their browsers, not
  // product naming.
  "/orca/cron": { target: "/tasks", batch: "B3" },
  "/octop/cron": { target: "/tasks", batch: "B3" },
  "/orca/channels": { target: "/personalization/channels", batch: "B3" },
  "/octop/channels": { target: "/personalization/channels", batch: "B3" },
  "/orca/admin/users": { target: "/chat" },
  "/octop/admin/users": { target: "/chat" },
  "/orca/admin/audit": { target: "/admin/security", batch: "B4" },
  "/octop/admin/audit": { target: "/admin/security", batch: "B4" },

  // The phone layout tree. Deleted by decision: the new shell is responsive, so
  // every /m/* URL lands on its desktop equivalent instead of a second UI.
  "/m/home": { target: "/home" },
  "/m/quick": { target: "/chat" },
  "/m/chat": { target: "/chat" },
  "/m/experts": { target: "/experts", batch: "B3" },
  "/m/bao": { target: "/bao", batch: "B3" },
  "/m/tasks": { target: "/tasks", batch: "B3" },
  "/m/connectors": { target: "/connectors", batch: "B2" },
  "/m/knowledge-bases": { target: "/knowledge-bases", batch: "B2" },
  "/m/token-usage": { target: "/token-usage", batch: "B1" },
  "/m/personalization": { target: "/personalization", batch: "B3" },
  "/m/admin": { target: "/admin/models", batch: "B4" },
  "/m/more": { target: "/settings" },
};

/**
 * Routes that exist in the new shell today. Anything not listed here yet falls
 * back to `/home`; each batch deletes its own entries from this set.
 */
const liveRoutes = new Set([
  "/home",
  "/chat",
  "/settings",
  "/token-usage",
  "/agent-config",
  "/design",
  "/setup",
]);

/** Resolves an old pathname (including `/m/chat/:id` style prefixes) to a live path. */
export function resolveLegacyPath(pathname: string): string | null {
  const direct = legacyRedirects[pathname];
  if (direct) return liveRoutes.has(direct.target) ? direct.target : FALLBACK;

  // Prefix rules: /skills/<name>, /m/chat/<id>, /personalization/<tab>, …
  const prefixCandidates = [
    ["/skills/", "/skills/*"],
    ["/m/personalization", "/m/personalization"],
    ["/m/admin", "/m/admin"],
    ["/m/chat", "/m/chat"],
    ["/personalization/", null],
  ] as const;

  for (const [prefix, key] of prefixCandidates) {
    if (!pathname.startsWith(prefix)) continue;
    if (key) {
      const entry = legacyRedirects[key];
      if (entry) return liveRoutes.has(entry.target) ? entry.target : FALLBACK;
    }
  }

  // Any remaining /m/* (chat by id, per-section admin pages, …).
  if (pathname.startsWith("/m/")) return FALLBACK;
  return null;
}
