import { createRootRoute, Link, Outlet } from "@tanstack/react-router";
import { Compass } from "lucide-react";

import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import i18n from "@/lib/i18n";

function NotFound() {
  return (
    <div className="flex h-full items-center justify-center bg-canvas p-6">
      <EmptyState
        size="lg"
        icon={<Compass />}
        title={i18n.t("state.notFoundTitle")}
        description={i18n.t("state.notFoundDescription")}
        action={
          <Button variant="secondary" size="sm" asChild>
            <Link to="/chat">{i18n.t("nav.chat")}</Link>
          </Button>
        }
      />
    </div>
  );
}

export const Route = createRootRoute({
  component: () => <Outlet />,
  notFoundComponent: NotFound,
});
