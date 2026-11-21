import { createFileRoute, Outlet, useRouterState } from "@tanstack/react-router";
import { useEffect } from "react";

import { AppShell } from "@/components/layout/app-shell";
import { Sidebar } from "@/components/layout/sidebar";
import { MobileNav } from "@/components/layout/topbar";
import { useUiStore } from "@/stores/ui";

export const Route = createFileRoute("/_app")({
  component: AppLayout,
});

function AppLayout() {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const mobileNavOpen = useUiStore((state) => state.mobileNavOpen);
  const setMobileNavOpen = useUiStore((state) => state.setMobileNavOpen);

  useEffect(() => {
    setMobileNavOpen(false);
  }, [pathname, setMobileNavOpen]);

  return (
    <AppShell
      sidebar={<Sidebar pathname={pathname} />}
      mobileNav={
        <MobileNav open={mobileNavOpen} onClose={() => setMobileNavOpen(false)}>
          <Sidebar pathname={pathname} onNavigate={() => setMobileNavOpen(false)} />
        </MobileNav>
      }
    >
      <Outlet />
    </AppShell>
  );
}
