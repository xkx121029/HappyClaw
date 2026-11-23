/**
 * The numeric scales the antd theme needs as numbers (antd cannot take `var()`).
 *
 * These mirror the values in `tables.ts`; `scales.test.ts` asserts they still
 * match the generated CSS, so the two cannot drift silently.
 */
export const FONT_SIZE = {
  "2xs": 12,
  xs: 13,
  sm: 14,
  md: 15,
  lg: 16,
  xl: 20,
  "2xl": 24,
} as const;

export const CONTROL_HEIGHT = {
  sm: 28,
  md: 34,
  lg: 40,
} as const;

export const RADIUS = {
  xs: 4,
  sm: 6,
  md: 8,
  lg: 12,
  xl: 16,
} as const;
