import { useTranslation } from "react-i18next";

import { cn } from "@/lib/cn";

import { Section, SubGrid, Swatch } from "./section";

const coralRamp = [
  ["50", "--hc-coral-50"],
  ["100", "--hc-coral-100"],
  ["200", "--hc-coral-200"],
  ["300", "--hc-coral-300"],
  ["400", "--hc-coral-400"],
  ["500", "--hc-coral-500"],
  ["600", "--hc-coral-600"],
  ["700", "--hc-coral-700"],
  ["800", "--hc-coral-800"],
  ["900", "--hc-coral-900"],
] as const;

const neutralRamp = [
  ["0", "--hc-neutral-0"],
  ["50", "--hc-neutral-50"],
  ["100", "--hc-neutral-100"],
  ["200", "--hc-neutral-200"],
  ["300", "--hc-neutral-300"],
  ["400", "--hc-neutral-400"],
  ["500", "--hc-neutral-500"],
  ["600", "--hc-neutral-600"],
  ["700", "--hc-neutral-700"],
  ["800", "--hc-neutral-800"],
  ["900", "--hc-neutral-900"],
  ["950", "--hc-neutral-950"],
] as const;

const typeScale = [
  ["4xl / 40px", "text-4xl", "Display headline"],
  ["3xl / 32px", "text-3xl", "Empty-state hero"],
  ["2xl / 26px", "text-2xl", "Page display"],
  ["xl / 21px", "text-xl", "Page title"],
  ["lg / 18px", "text-lg", "Section title"],
  ["md / 16px", "text-md", "Reading text"],
  ["base / 14px", "text-base", "Default UI text"],
  ["sm / 13px", "text-sm", "Dense UI"],
  ["xs / 12px", "text-xs", "Captions and meta"],
  ["2xs / 11px", "text-2xs", "Badges and labels"],
] as const;

const spacing = [1, 2, 3, 4, 5, 6, 8, 10, 12, 16] as const;
const radii = [
  ["xs", "4px", "rounded-xs"],
  ["sm", "6px", "rounded-sm"],
  ["md", "10px", "rounded-md"],
  ["lg", "14px", "rounded-lg"],
  ["xl", "18px", "rounded-xl"],
  ["2xl", "24px", "rounded-2xl"],
] as const;
const shadows = [
  ["xs", "shadow-xs", "Static cards"],
  ["sm", "shadow-sm", "Hover, inputs"],
  ["md", "shadow-md", "Popovers, menus"],
  ["lg", "shadow-lg", "Sheets"],
  ["overlay", "shadow-overlay", "Dialogs, toasts"],
] as const;
const durations = [
  ["instant", "80ms", "--hc-duration-instant"],
  ["fast", "120ms", "--hc-duration-fast"],
  ["base", "180ms", "--hc-duration-base"],
  ["slow", "280ms", "--hc-duration-slow"],
  ["slower", "420ms", "--hc-duration-slower"],
] as const;

export function ColorSection() {
  const { t } = useTranslation("design");
  return (
    <Section
      id="color"
      title={t("sections.color")}
      description={t("color.accentDescription")}
    >
      <div className="grid gap-6">
        <SubGrid title={t("color.primitives")} columns={5}>
          {coralRamp.map(([step, variable]) => (
            <Swatch key={variable} name={`coral ${step}`} variable={variable} />
          ))}
        </SubGrid>

        <SubGrid title="Neutral ramp" columns={6}>
          {neutralRamp.map(([step, variable]) => (
            <Swatch key={variable} name={`neutral ${step}`} variable={variable} />
          ))}
        </SubGrid>

        <SubGrid title={t("color.semantic")} columns={4}>
          <Swatch name={`${t("color.surface")} · canvas`} variable="--hc-bg-canvas" />
          <Swatch name={`${t("color.surface")} · surface`} variable="--hc-bg-surface" />
          <Swatch name={`${t("color.surface")} · raised`} variable="--hc-bg-raised" />
          <Swatch name={`${t("color.surface")} · sunken`} variable="--hc-bg-sunken" />
          <Swatch name={`${t("color.text")} · default`} variable="--hc-fg-default" />
          <Swatch name={`${t("color.text")} · muted`} variable="--hc-fg-muted" />
          <Swatch name={`${t("color.text")} · subtle`} variable="--hc-fg-subtle" />
          <Swatch name={`${t("color.border")} · default`} variable="--hc-border-default" />
          <Swatch name={`${t("color.accent")} · default`} variable="--hc-accent-default" />
          <Swatch name={`${t("color.accent")} · soft`} variable="--hc-accent-soft" />
          <Swatch name={`${t("color.accent")} · hover`} variable="--hc-accent-hover" />
          <Swatch name={`${t("color.border")} · strong`} variable="--hc-border-strong" />
        </SubGrid>

        <SubGrid title={t("color.status")} description={t("color.statusDescription")} columns={4}>
          <Swatch name="success" variable="--hc-success-default" />
          <Swatch name="success soft" variable="--hc-success-soft" />
          <Swatch name="warning" variable="--hc-warning-default" />
          <Swatch name="warning soft" variable="--hc-warning-soft" />
          <Swatch name="danger" variable="--hc-danger-default" />
          <Swatch name="danger soft" variable="--hc-danger-soft" />
          <Swatch name="info" variable="--hc-info-default" />
          <Swatch name="info soft" variable="--hc-info-soft" />
        </SubGrid>
      </div>
    </Section>
  );
}

export function TypeSection() {
  const { t } = useTranslation("design");
  return (
    <Section
      id="type"
      title={t("sections.type")}
      description={t("type.sansDescription")}
    >
      <div className="grid gap-6">
        <div className="grid gap-2 rounded-lg border border-line-subtle bg-surface p-4">
          {typeScale.map(([label, className, sample]) => (
            <div
              key={label}
              className="flex items-baseline gap-4 border-b border-line-subtle pb-2 last:border-0 last:pb-0"
            >
              <span className="w-28 shrink-0 font-mono text-2xs text-fg-subtle">
                {label}
              </span>
              <span className={cn("truncate text-fg", className)}>{sample}</span>
            </div>
          ))}
        </div>
        <div className="grid gap-2 rounded-lg border border-line-subtle bg-surface p-4">
          <p className="text-sm font-medium text-fg">{t("type.mono")}</p>
          <p className="font-mono text-sm text-fg-muted">
            claude-sonnet-5-5 · 12,480 tokens · thread_01J8F3
          </p>
          <p className="text-2xs text-fg-subtle">{t("type.monoDescription")}</p>
        </div>
      </div>
    </Section>
  );
}

export function ScaleSection() {
  const { t } = useTranslation("design");
  return (
    <Section
      id="scales"
      title={t("sections.spacing")}
      description={t("spacingDescription")}
    >
      <div className="grid gap-6">
        <div className="grid gap-1.5">
          {spacing.map((step) => (
            <div key={step} className="flex items-center gap-3">
              <span className="w-12 shrink-0 font-mono text-2xs text-fg-subtle">
                {step} · {step * 4}px
              </span>
              <div
                className="h-2 rounded-xs bg-accent/70"
                style={{ width: `var(--hc-space-${step})` }}
              />
            </div>
          ))}
        </div>

        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-fg-subtle">
            {t("sections.radius")}
          </h3>
          <p className="mb-3 text-2xs text-fg-subtle">{t("radiusDescription")}</p>
          <div className="flex flex-wrap gap-3">
            {radii.map(([token, value, className]) => (
              <div key={token} className="grid gap-1 text-center">
                <div
                  className={cn(
                    "size-16 border border-line-strong bg-sunken",
                    className,
                  )}
                />
                <span className="font-mono text-2xs text-fg-subtle">
                  {token} · {value}
                </span>
              </div>
            ))}
          </div>
        </div>

        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-fg-subtle">
            {t("sections.shadow")}
          </h3>
          <p className="mb-3 text-2xs text-fg-subtle">{t("shadowDescription")}</p>
          <div className="flex flex-wrap gap-4">
            {shadows.map(([token, className, usage]) => (
              <div key={token} className="grid gap-1">
                <div
                  className={cn(
                    "flex size-20 items-center justify-center rounded-lg bg-surface text-2xs text-fg-subtle",
                    className,
                  )}
                >
                  {token}
                </div>
                <span className="text-center text-2xs text-fg-subtle">{usage}</span>
              </div>
            ))}
          </div>
        </div>

        <div>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-fg-subtle">
            {t("sections.motion")}
          </h3>
          <p className="mb-3 text-2xs text-fg-subtle">{t("motionDescription")}</p>
          <div className="flex flex-wrap gap-3">
            {durations.map(([name, value, variable]) => (
              <div key={name} className="grid gap-1">
                <div className="group/sample flex h-12 w-28 items-center rounded-md border border-line-subtle bg-surface px-2">
                  <div
                    className="size-6 rounded-full bg-accent transition-transform group-hover/sample:translate-x-16"
                    style={{ transitionDuration: `var(${variable})` }}
                  />
                </div>
                <span className="font-mono text-2xs text-fg-subtle">
                  {name} · {value}
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </Section>
  );
}
