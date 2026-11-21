import { Menu } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import { useUiStore } from "@/stores/ui";

import { ThemeLanguageControls } from "./sidebar";

export function Topbar({
  title,
  subtitle,
  actions,
  children,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  const { t } = useTranslation();
  const setMobileNavOpen = useUiStore((state) => state.setMobileNavOpen);

  return (
    <header className="flex h-topbar shrink-0 items-center gap-3 border-b border-line bg-surface/80 px-3 backdrop-blur-sm md:px-4">
      <Button
        variant="ghost"
        size="icon-sm"
        className="lg:hidden"
        aria-label={t("shell.openNavigation")}
        onClick={() => setMobileNavOpen(true)}
      >
        <Menu />
      </Button>

      <div className="flex min-w-0 flex-1 items-center gap-2">
        {title ? (
          <div className="min-w-0">
            <h1 className="truncate text-md font-semibold text-fg">{title}</h1>
            {subtitle ? (
              <p className="truncate text-2xs text-fg-subtle">{subtitle}</p>
            ) : null}
          </div>
        ) : null}
        {children}
      </div>

      <div className="flex items-center gap-1.5">
        {actions}
        <ThemeLanguageControls />
      </div>
    </header>
  );
}

/** Standard scroll body for a page: centred, padded, with an optional toolbar. */
export function PageBody({
  children,
  className,
  width = "full",
}: {
  children: ReactNode;
  className?: string;
  width?: "full" | "reading";
}) {
  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div
        className={cn(
          "mx-auto w-full px-4 py-5 md:px-6 md:py-6",
          width === "reading" ? "max-w-reading" : "max-w-[var(--hc-content-max)]",
          className,
        )}
      >
        {children}
      </div>
    </div>
  );
}

export function MobileNav({
  children,
  open,
  onClose,
}: {
  children: ReactNode;
  open: boolean;
  onClose: () => void;
}) {
  return (
    <div
      className={cn(
        "fixed inset-0 z-(--hc-z-overlay) lg:hidden",
        open ? "pointer-events-auto" : "pointer-events-none",
      )}
      aria-hidden={!open}
    >
      <div
        onClick={onClose}
        className={cn(
          "absolute inset-0 bg-overlay transition-opacity duration-(--hc-duration-base)",
          open ? "opacity-100" : "opacity-0",
        )}
      />
      <div
        className={cn(
          "absolute inset-y-0 left-0 w-[min(80vw,280px)] shadow-overlay transition-transform duration-(--hc-duration-base) ease-out",
          open ? "translate-x-0" : "-translate-x-full",
        )}
      >
        {children}
      </div>
    </div>
  );
}
