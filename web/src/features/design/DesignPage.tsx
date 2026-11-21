import { Moon, Sun } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Topbar } from "@/components/layout/topbar";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Segmented } from "@/components/ui/tabs";
import { useUiStore } from "@/stores/ui";

import {
  ColorSection,
  ScaleSection,
  TypeSection,
} from "./token-sections";
import { ComponentSection } from "./component-sections";

const sections = [
  { id: "color", key: "color" },
  { id: "type", key: "type" },
  { id: "scales", key: "spacing" },
  { id: "components", key: "components" },
] as const;

export function DesignPage() {
  const { t } = useTranslation("design");
  const theme = useUiStore((state) => state.theme);
  const setTheme = useUiStore((state) => state.setTheme);

  return (
    <>
      <Topbar
        title={t("title")}
        subtitle={t("subtitle")}
        actions={
          <Segmented
            ariaLabel={t("theme.light")}
            value={theme}
            onChange={setTheme}
            options={[
              { value: "light", label: t("theme.light"), icon: <Sun /> },
              { value: "dark", label: t("theme.dark"), icon: <Moon /> },
            ]}
          />
        }
      />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto grid w-full max-w-[var(--hc-content-max)] gap-8 px-4 py-6 md:px-8 lg:grid-cols-[180px_1fr]">
          <nav aria-label={t("title")} className="hidden lg:block">
            <div className="sticky top-0 grid gap-0.5">
              <div className="mb-2 flex items-center gap-2">
                <img
                  src="/brand/happyclaw-icon.svg"
                  alt=""
                  className="size-8 rounded-md"
                />
                <div>
                  <p className="text-sm font-semibold">HappyClaw</p>
                  <Badge tone="accent">v0.2 · web</Badge>
                </div>
              </div>
              {sections.map((section) => (
                <a
                  key={section.id}
                  href={`#${section.id}`}
                  className="rounded-sm px-2 py-1.5 text-sm text-fg-muted transition-colors hover:bg-hover hover:text-fg"
                >
                  {t(`sections.${section.key}`)}
                </a>
              ))}
            </div>
          </nav>

          <div className="grid min-w-0 gap-8">
            <ColorSection />
            <TypeSection />
            <ScaleSection />
            <ComponentSection />
            <footer className="border-t border-line-subtle pt-6 pb-4">
              <Button
                variant="link"
                onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
              >
                {theme === "dark" ? t("theme.light") : t("theme.dark")}
              </Button>
            </footer>
          </div>
        </div>
      </div>
    </>
  );
}
