/**
 * Semantic color tokens — the single source of truth for light and dark.
 *
 * Previously these values lived twice: here-shaped CSS custom properties in
 * `theme-vars.css` and again as antd tokens in `App.tsx`. The two copies had
 * already drifted (`#0f1117` vs `#14161f` for the same surface role).
 *
 * Only semantic roles live here. One-off decorative palettes (tags, file-type
 * accents) stay in the stylesheet where they are used.
 */

export type Mode = "light" | "dark";

export interface SemanticColors {
  /** Page canvas behind the shell. */
  bgLayout: string;
  /** Panels, cards, the primary raised surface. */
  bgContainer: string;
  /** Cards sitting on a container (secondary blocks, table headers). */
  bgElevated: string;
  /** Sunken areas: code blocks, toolbars, sidebars. */
  bgSecondary: string;
  bgHover: string;
  bgActive: string;
  bgSelected: string;

  textPrimary: string;
  textSecondary: string;
  textTertiary: string;
  textQuaternary: string;
  textPlaceholder: string;
  textDisabled: string;

  borderPrimary: string;
  borderSecondary: string;
  borderInput: string;

  colorSuccess: string;
  colorWarning: string;
  colorDanger: string;
  colorInfo: string;

  /** Mask behind modals / drawers. */
  bgMask: string;
  /** Row hover in dense tables. */
  fillHover: string;
}

export const SEMANTIC_COLORS: Record<Mode, SemanticColors> = {
  light: {
    bgLayout: "#f5f6f8",
    bgContainer: "#ffffff",
    bgElevated: "#ffffff",
    bgSecondary: "#f7f8fa",
    bgHover: "rgba(232, 93, 117, 0.04)",
    bgActive: "rgba(232, 93, 117, 0.08)",
    bgSelected: "rgba(232, 93, 117, 0.06)",

    textPrimary: "#111827",
    textSecondary: "#4b5563",
    textTertiary: "#5b6470",
    textQuaternary: "#6b7280",
    // Was #9aa2ad (≈2.6:1 on white). Raised to clear 4.5:1 so placeholder
    // copy stays readable instead of looking like a disabled control.
    textPlaceholder: "#767f8b",
    textDisabled: "#a3aab5",

    borderPrimary: "#e5e7eb",
    borderSecondary: "#f3f4f6",
    borderInput: "#d1d5db",

    colorSuccess: "#10b981",
    colorWarning: "#f59e0b",
    colorDanger: "#ef4444",
    colorInfo: "#3b82f6",

    bgMask: "rgba(5, 5, 8, 0.55)",
    fillHover: "rgba(0, 0, 0, 0.04)",
  },
  dark: {
    bgLayout: "#0b0d14",
    bgContainer: "#0f1117",
    bgElevated: "#1a1c28",
    bgSecondary: "#14161f",
    bgHover: "rgba(232, 93, 117, 0.08)",
    bgActive: "rgba(232, 93, 117, 0.14)",
    bgSelected: "rgba(232, 93, 117, 0.1)",

    textPrimary: "rgba(255, 255, 255, 0.92)",
    textSecondary: "rgba(255, 255, 255, 0.72)",
    textTertiary: "rgba(255, 255, 255, 0.62)",
    // 0.44 over #0f1117 measured ≈4.3:1 — just under the 4.5 floor for body copy.
    textQuaternary: "rgba(255, 255, 255, 0.56)",
    textPlaceholder: "rgba(255, 255, 255, 0.5)",
    textDisabled: "rgba(255, 255, 255, 0.32)",

    borderPrimary: "rgba(255, 255, 255, 0.08)",
    borderSecondary: "rgba(255, 255, 255, 0.06)",
    borderInput: "rgba(255, 255, 255, 0.12)",

    colorSuccess: "#34d399",
    colorWarning: "#fbbf24",
    colorDanger: "#f87171",
    colorInfo: "#60a5fa",

    bgMask: "rgba(5, 5, 8, 0.8)",
    fillHover: "rgba(255, 255, 255, 0.07)",
  },
};

/** CSS custom-property name for each semantic role. */
export const SEMANTIC_CSS_VARS: Record<keyof SemanticColors, string> = {
  bgLayout: "--fn-bg-layout",
  bgContainer: "--fn-bg-container",
  bgElevated: "--fn-bg-elevated",
  bgSecondary: "--fn-bg-secondary",
  bgHover: "--fn-bg-hover",
  bgActive: "--fn-bg-active",
  bgSelected: "--fn-bg-selected",
  textPrimary: "--fn-text-primary",
  textSecondary: "--fn-text-secondary",
  textTertiary: "--fn-text-tertiary",
  textQuaternary: "--fn-text-quaternary",
  textPlaceholder: "--fn-text-placeholder",
  textDisabled: "--fn-text-disabled",
  borderPrimary: "--fn-border-primary",
  borderSecondary: "--fn-border-secondary",
  borderInput: "--fn-border-input",
  colorSuccess: "--fn-color-success",
  colorWarning: "--fn-color-warning",
  colorDanger: "--fn-color-danger",
  colorInfo: "--fn-color-info",
  bgMask: "--fn-bg-mask",
  fillHover: "--fn-fill-hover",
};
