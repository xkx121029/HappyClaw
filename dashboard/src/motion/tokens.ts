/**
 * 全站统一动效标尺。
 *
 * 三个维度：时长阶梯、缓动曲线、位移/缩放尺度。页面不再各写各的
 * transition，统一从这里取数（CSS 变量见 motion.css，JS 侧见本文件）。
 *
 * 设计取向：默认曲线「减速进入、加速离开」，宁短勿长；位移只做
 * transform / opacity，避免触发布局抖动。
 */

/** 用户可选的预设曲线。custom 走用户自定义贝塞尔。 */
export type MotionCurvePreset = "comfort" | "smooth" | "swift" | "spring" | "custom";

/** 速度档位：整体缩放时长阶梯。 */
export type MotionSpeed = "gentle" | "standard" | "brisk";

export const MOTION_CURVE_PRESETS: MotionCurvePreset[] = [
  "comfort",
  "smooth",
  "swift",
  "spring",
  "custom",
];

export const MOTION_SPEEDS: MotionSpeed[] = ["gentle", "standard", "brisk"];

export const DEFAULT_MOTION_CURVE: MotionCurvePreset = "comfort";
export const DEFAULT_MOTION_SPEED: MotionSpeed = "standard";

/** 速度档位对时长阶梯的缩放系数。 */
export const SPEED_SCALE: Record<MotionSpeed, number> = {
  gentle: 1.18,
  standard: 1,
  brisk: 0.82,
};

/** 时长阶梯（standard 档位，毫秒）。 */
export const BASE_DURATIONS = {
  instant: 90,
  fast: 130,
  base: 190,
  slow: 280,
  slower: 420,
  epic: 760,
} as const;

export type MotionDurationKey = keyof typeof BASE_DURATIONS;

/** 贝塞尔控制点：[x1, y1, x2, y2]。 */
export type Bezier = [number, number, number, number];

/**
 * 进入曲线：偏舒适，末端大幅减速。
 * spring 的 y 轴略微超过 1，只用于小面积元素，不做整页位移动画。
 */
export const ENTER_CURVES: Record<Exclude<MotionCurvePreset, "custom">, Bezier> = {
  comfort: [0.22, 1, 0.36, 1],
  smooth: [0.4, 0, 0.2, 1],
  swift: [0.2, 0, 0, 1],
  spring: [0.34, 1.28, 0.64, 1],
};

/** 离开曲线：加速离场，避免拖沓。 */
export const EXIT_CURVE: Bezier = [0.4, 0, 1, 1];

/** 自定义曲线的默认值（即 comfort）。 */
export const DEFAULT_CUSTOM_CURVE: Bezier = ENTER_CURVES.comfort;

/** 位移尺度（px）。列表项用 sm，卡片用 md，页面用 lg。 */
export const MOTION_SHIFTS = {
  xs: 4,
  sm: 8,
  md: 14,
  lg: 22,
  xl: 34,
} as const;

/** 缩放尺度。只用于「出现/消失」，不用于常态布局。 */
export const MOTION_SCALES = {
  subtle: 0.99,
  card: 0.97,
  hero: 0.94,
} as const;

export function bezierToCss(curve: Bezier): string {
  return `cubic-bezier(${curve.map((n) => round(n, 3)).join(", ")})`;
}

export function round(value: number, digits = 2): number {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

export interface ResolvedMotionTokens {
  duration: Record<MotionDurationKey, number>;
  /** 进入曲线（cubic-bezier 字符串）。 */
  enterEase: string;
  /** 离开曲线（cubic-bezier 字符串）。 */
  exitEase: string;
  /** 中性曲线，用于状态切换等非进出场动效。 */
  standardEase: string;
  /** 曲线控制点，供 motion/react 等 JS 动画使用。 */
  enterBezier: Bezier;
  exitBezier: Bezier;
  shift: Record<keyof typeof MOTION_SHIFTS, number>;
  scale: Record<keyof typeof MOTION_SCALES, number>;
  reduced: boolean;
}

export interface MotionTokenInput {
  curve: MotionCurvePreset;
  speed: MotionSpeed;
  custom: Bezier;
}

/** 把用户偏好折算成可直接消费的数值。 */
export function resolveMotionTokens(
  prefs: MotionTokenInput,
  reduced = false,
): ResolvedMotionTokens {
  const scale = SPEED_SCALE[prefs.speed] ?? 1;
  const duration = Object.fromEntries(
    Object.entries(BASE_DURATIONS).map(([key, value]) => [
      key,
      Math.round(value * scale),
    ]),
  ) as Record<MotionDurationKey, number>;

  const enterCurve =
    prefs.curve === "custom" ? prefs.custom : ENTER_CURVES[prefs.curve];

  return {
    duration,
    enterEase: bezierToCss(enterCurve),
    exitEase: bezierToCss(EXIT_CURVE),
    standardEase: bezierToCss(ENTER_CURVES.smooth),
    enterBezier: [...enterCurve] as Bezier,
    exitBezier: [...EXIT_CURVE] as Bezier,
    // 减少动态效果时保留淡入淡出，但取消位移与缩放。
    shift: reduced
      ? { xs: 0, sm: 0, md: 0, lg: 0, xl: 0 }
      : { ...MOTION_SHIFTS },
    scale: reduced
      ? { subtle: 1, card: 1, hero: 1 }
      : { ...MOTION_SCALES },
    reduced,
  };
}

/** 生成挂在 <html> 上的 CSS 变量；同时镜像到 --fn-* 让存量 transition 跟随。 */
export function motionCssVars(
  tokens: ResolvedMotionTokens,
): Record<string, string> {
  const { duration, shift, scale } = tokens;
  return {
    "--motion-duration-instant": `${duration.instant}ms`,
    "--motion-duration-fast": `${duration.fast}ms`,
    "--motion-duration-base": `${duration.base}ms`,
    "--motion-duration-slow": `${duration.slow}ms`,
    "--motion-duration-slower": `${duration.slower}ms`,
    "--motion-duration-epic": `${duration.epic}ms`,
    "--motion-ease-enter": tokens.enterEase,
    "--motion-ease-exit": tokens.exitEase,
    "--motion-ease-standard": tokens.standardEase,
    "--motion-shift-xs": `${shift.xs}px`,
    "--motion-shift-sm": `${shift.sm}px`,
    "--motion-shift-md": `${shift.md}px`,
    "--motion-shift-lg": `${shift.lg}px`,
    "--motion-shift-xl": `${shift.xl}px`,
    "--motion-scale-subtle": String(scale.subtle),
    "--motion-scale-card": String(scale.card),
    "--motion-scale-hero": String(scale.hero),
    // 存量组件读的是 --fn-*，统一跟随用户选择。
    "--fn-duration-fast": `${duration.fast}ms`,
    "--fn-duration-base": `${duration.base}ms`,
    "--fn-duration-slow": `${duration.slow}ms`,
    "--fn-ease-standard": tokens.standardEase,
    "--fn-ease-out": tokens.enterEase,
  };
}
