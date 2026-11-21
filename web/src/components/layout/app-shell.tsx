import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

/**
 * App chrome: fixed sidebar on >=lg, slide-over navigation below it, and a
 * content column that owns its own scrolling so the shell never scrolls.
 */
export function AppShell({
  sidebar,
  mobileNav,
  children,
  className,
}: {
  sidebar: ReactNode;
  mobileNav: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className="flex h-full min-h-0 overflow-hidden bg-canvas">
      <div className="hidden shrink-0 lg:block">{sidebar}</div>
      {mobileNav}
      <div className={cn("flex min-w-0 flex-1 flex-col", className)}>
        {children}
      </div>
    </div>
  );
}
