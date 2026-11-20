/**
 * Design scale tokens — the single source of truth.
 *
 * These numbers are consumed twice:
 *   1. `scripts/gen-tokens.mjs` emits them as CSS custom properties
 *      (`styles/tokens.generated.css`) for stylesheets.
 *   2. `tokens/antd.ts` maps them onto Ant Design's theme tokens, which need
 *      real numbers rather than `var()` references.
 *
 * Key names deliberately match the existing CSS variable suffixes (`2xs`,
 * `2xl`, `3xl`) so the ~165 existing stylesheets keep resolving after the
 * variables become generated output.
 */

/** Type scale. 12px is the floor for user-visible text. */
export const FONT_SIZE = {
  "2xs": 12, // meta, timestamps, table captions
  xs: 13, // secondary copy, dense table cells
  sm: 14, // body default
  md: 15, // emphasized body, dialog copy
  lg: 16, // section / dialog titles
  xl: 20, // page titles
  "2xl": 24, // hero numbers
} as const;

export const LINE_HEIGHT = {
  tight: 1.3,
  normal: 1.55,
  relaxed: 1.7,
} as const;

export const FONT_WEIGHT = {
  regular: 400,
  medium: 500,
  semibold: 600,
} as const;

/**
 * Space scale — 4px base.
 *
 * Only these steps exist. Values like 3/5/7/9/11/14/18px that accumulated in
 * the stylesheets are normalised onto this grid by `scripts/codemod-tokens.mjs`.
 */
export const SPACE = {
  "2xs": 4,
  /** Dense only: list rows, tool-call rows, IDE panes. */
  dense: 6,
  xs: 8,
  sm: 12,
  md: 16,
  lg: 20,
  xl: 24,
  "2xl": 32,
  "3xl": 48,
} as const;

/**
 * Radius scale. `md: 8` was the most-used value in the stylesheets (101 uses)
 * yet had no token, which is why 8px/10px were interchangeable everywhere.
 */
export const RADIUS = {
  xs: 4,
  sm: 6,
  md: 8,
  lg: 12,
  xl: 16,
  "2xl": 20,
  full: 9999,
} as const;

/** Control heights, mirrored onto antd's `controlHeight*`. */
export const CONTROL_HEIGHT = {
  sm: 28,
  md: 34,
  lg: 40,
} as const;

/** Layout constants shared by the shell and the stylesheets. */
export const LAYOUT = {
  sidebarWidth: 240,
  headerHeight: 56,
  chatChromeHeight: 58,
} as const;

export type FontSizeKey = keyof typeof FONT_SIZE;
export type SpaceKey = keyof typeof SPACE;
export type RadiusKey = keyof typeof RADIUS;
