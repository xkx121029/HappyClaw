/**
 * Ant Design theme configuration.
 *
 * The single place that maps our design tokens onto antd's token names. Before
 * this existed, `App.tsx` hard-coded a second copy of the scale (fontSize 14 /
 * SM 12 / LG 16, radius 10/6/12/4, controlHeight 34/28/40) that disagreed with
 * the CSS custom properties — most visibly `--fn-text-lg: 17px` versus antd's
 * `fontSizeLG: 16`.
 */

import { theme as antdTheme, type ThemeConfig } from "antd";
import {
  CONTROL_HEIGHT,
  FONT_SIZE,
  RADIUS,
} from "./scales";
import { SEMANTIC_COLORS, type Mode } from "./colors";
import { brandFocusRing, brandTokensFor } from "../themePalettes";
import type { ThemePalette } from "../themePalettes";

export interface AntdThemeInput {
  isDark: boolean;
  isMobile: boolean;
  palette: ThemePalette;
  customColor?: string | null;
  /** Motion durations in ms from `motion/tokens.ts` (respects user preference). */
  motion: {
    reduced: boolean;
    fast: number;
    base: number;
    slow: number;
    enterEase: string;
  };
}

export function antdThemeConfig({
  isDark,
  isMobile,
  palette,
  customColor,
  motion,
}: AntdThemeInput): ThemeConfig {
  const mode: Mode = isDark ? "dark" : "light";
  const colors = SEMANTIC_COLORS[mode];
  const brandTokens = brandTokensFor(palette, isDark, customColor ?? undefined);
  const focusRing = brandFocusRing(palette, isDark, customColor ?? undefined);
  const ms = (value: number) => (motion.reduced ? "0.001s" : `${value}ms`);

  return {
    algorithm: isDark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
    token: {
      fontFamily:
        '-apple-system, BlinkMacSystemFont, "Segoe UI", "Inter", "Noto Sans SC", "Microsoft YaHei", sans-serif',
      fontSize: isMobile ? FONT_SIZE.md : FONT_SIZE.sm,
      fontSizeSM: FONT_SIZE["2xs"],
      fontSizeLG: FONT_SIZE.lg,
      fontSizeXL: FONT_SIZE.xl,
      lineHeight: 1.5715,
      borderRadius: RADIUS.md,
      borderRadiusXS: RADIUS.xs,
      borderRadiusSM: RADIUS.sm,
      borderRadiusLG: RADIUS.lg,
      controlHeight: isMobile ? 36 : CONTROL_HEIGHT.md,
      controlHeightSM: CONTROL_HEIGHT.sm,
      controlHeightLG: CONTROL_HEIGHT.lg,
      wireframe: false,
      motionDurationFast: ms(motion.fast),
      motionDurationMid: ms(motion.base),
      motionDurationSlow: ms(motion.slow),
      motionEaseInOut: motion.enterEase,
      motionEaseOut: motion.enterEase,
      boxShadow: "var(--fn-shadow-sm)",
      boxShadowSecondary: "var(--fn-shadow-popover)",
      controlOutline: focusRing,
      controlOutlineWidth: 3,
      colorBgBase: colors.bgContainer,
      colorBgLayout: colors.bgLayout,
      colorBgContainer: colors.bgContainer,
      colorBgElevated: colors.bgElevated,
      colorBgMask: colors.bgMask,
      colorTextBase: colors.textPrimary,
      colorText: colors.textPrimary,
      colorTextSecondary: colors.textSecondary,
      colorTextTertiary: colors.textTertiary,
      colorTextQuaternary: colors.textQuaternary,
      colorBorder: isDark ? colors.borderPrimary : colors.borderInput,
      colorBorderSecondary: colors.borderSecondary,
      colorFill: colors.bgHover,
      colorFillSecondary: colors.bgSecondary,
      colorFillTertiary: colors.bgHover,
      colorFillQuaternary: "transparent",
      colorBgTextHover: colors.bgHover,
      colorSuccess: colors.colorSuccess,
      colorWarning: colors.colorWarning,
      colorError: colors.colorDanger,
      colorInfo: colors.colorInfo,
      ...brandTokens,
    },
    components: {
      Button: {
        fontWeight: 500,
        primaryShadow: "none",
        defaultShadow: "none",
        dangerShadow: "none",
      },
      Card: {
        bodyPadding: 20,
        headerHeight: 48,
        // Titles match the CSS `--fn-text-md` emphasis step rather than
        // introducing a third size.
        headerFontSize: FONT_SIZE.md,
        headerBg: "transparent",
      },
      Table: {
        headerBg: colors.bgSecondary,
        headerColor: colors.textSecondary,
        rowHoverBg: colors.bgSecondary,
        borderColor: colors.borderPrimary,
        headerSplitColor: "transparent",
        headerBorderRadius: RADIUS.md,
        cellPaddingBlock: 10,
      },
      Modal: {
        headerBg: colors.bgElevated,
        contentBg: colors.bgElevated,
        titleFontSize: FONT_SIZE.lg,
      },
      Tooltip: {
        colorBgSpotlight: isDark ? "#262a3a" : "#111827",
        borderRadius: RADIUS.sm,
      },
      Tag: { borderRadiusSM: RADIUS.sm },
      Segmented: {
        itemSelectedBg: isDark ? "#262a3a" : colors.bgContainer,
      },
      Skeleton: isDark
        ? {
            gradientFromColor: "rgba(255,255,255,0.06)",
            gradientToColor: "rgba(255,255,255,0.12)",
          }
        : {
            gradientFromColor: "rgba(17,24,39,0.04)",
            gradientToColor: "rgba(17,24,39,0.08)",
          },
      ...(isDark
        ? {
            Input: { colorBgBase: colors.bgContainer },
            InputNumber: { colorBgBase: colors.bgContainer },
            Select: { selectorBg: colors.bgContainer },
            DatePicker: { colorBgBase: colors.bgContainer },
          }
        : {}),
    },
  };
}
