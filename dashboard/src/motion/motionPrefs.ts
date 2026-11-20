/**
 * 动效偏好：预设曲线 + 速度档位 + 自定义贝塞尔。
 *
 * 存储在本机 localStorage，启动时写入 <html> 的 CSS 变量，刷新后仍然生效。
 * 系统开启「减少动态效果」时由 Provider 统一降级为无位移淡入淡出。
 */

import {
  DEFAULT_CUSTOM_CURVE,
  DEFAULT_MOTION_CURVE,
  DEFAULT_MOTION_SPEED,
  MOTION_CURVE_PRESETS,
  MOTION_SPEEDS,
  motionCssVars,
  resolveMotionTokens,
  type Bezier,
  type MotionCurvePreset,
  type MotionSpeed,
} from "./tokens";

export const MOTION_PREFS_STORAGE_KEY = "octop:motion-prefs";

export interface MotionPrefs {
  curve: MotionCurvePreset;
  speed: MotionSpeed;
  /** 仅 curve === "custom" 时生效。 */
  custom: Bezier;
}

export const DEFAULT_MOTION_PREFS: MotionPrefs = {
  curve: DEFAULT_MOTION_CURVE,
  speed: DEFAULT_MOTION_SPEED,
  custom: DEFAULT_CUSTOM_CURVE,
};

export function isCurvePreset(value: unknown): value is MotionCurvePreset {
  return (
    typeof value === "string" &&
    (MOTION_CURVE_PRESETS as string[]).includes(value)
  );
}

export function isMotionSpeed(value: unknown): value is MotionSpeed {
  return (
    typeof value === "string" && (MOTION_SPEEDS as string[]).includes(value)
  );
}

function toNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

/**
 * 校验并归一化贝塞尔：x 必须在 [0,1]，y 允许轻微过冲但不能失控。
 * 任一控制点非法时整体回退到默认舒适曲线。
 */
export function normalizeBezier(value: unknown): Bezier {
  if (!Array.isArray(value) || value.length !== 4) {
    return [...DEFAULT_CUSTOM_CURVE] as Bezier;
  }
  const nums = value.map(toNumber);
  if (nums.some((n) => n === null)) {
    return [...DEFAULT_CUSTOM_CURVE] as Bezier;
  }
  const [x1, y1, x2, y2] = nums as number[];
  const clamp = (n: number, min: number, max: number) =>
    Math.min(max, Math.max(min, n));
  // x 越界会让曲线出现回折，直接夹取；y 只限制在可解释范围内。
  return [
    clamp(x1, 0, 1),
    clamp(y1, -0.6, 1.6),
    clamp(x2, 0, 1),
    clamp(y2, -0.6, 1.6),
  ];
}

export function normalizeMotionPrefs(value: unknown): MotionPrefs {
  if (!value || typeof value !== "object") return { ...DEFAULT_MOTION_PREFS };
  const obj = value as Record<string, unknown>;
  return {
    curve: isCurvePreset(obj.curve) ? obj.curve : DEFAULT_MOTION_CURVE,
    speed: isMotionSpeed(obj.speed) ? obj.speed : DEFAULT_MOTION_SPEED,
    custom: normalizeBezier(obj.custom),
  };
}

export function readMotionPrefs(): MotionPrefs {
  try {
    const raw = localStorage.getItem(MOTION_PREFS_STORAGE_KEY);
    if (!raw) return { ...DEFAULT_MOTION_PREFS };
    return normalizeMotionPrefs(JSON.parse(raw));
  } catch {
    return { ...DEFAULT_MOTION_PREFS };
  }
}

export function writeMotionPrefs(prefs: MotionPrefs): void {
  try {
    localStorage.setItem(
      MOTION_PREFS_STORAGE_KEY,
      JSON.stringify(normalizeMotionPrefs(prefs)),
    );
  } catch {
    // localStorage 不可用：本次仍已生效，只是刷新后回退
  }
}

/** 系统是否要求减少动态效果。 */
export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * 把偏好落到 DOM：data 属性便于 CSS 分支，变量用于具体数值。
 * reduced 由 Provider 传入，内部不重复读系统偏好。
 */
export function applyMotionPrefs(prefs: MotionPrefs, reduced: boolean): void {
  if (typeof document === "undefined") return;
  const normalized = normalizeMotionPrefs(prefs);
  const root = document.documentElement;
  const tokens = resolveMotionTokens(normalized, reduced);
  const vars = motionCssVars(tokens);
  for (const [name, value] of Object.entries(vars)) {
    root.style.setProperty(name, value);
  }
  root.setAttribute("data-motion-curve", normalized.curve);
  root.setAttribute("data-motion-speed", normalized.speed);
  root.setAttribute("data-motion-reduced", reduced ? "true" : "false");
}

/** 启动时应用一次，避免首帧按默认曲线闪一下。 */
export function initMotionPrefs(): MotionPrefs {
  const prefs = readMotionPrefs();
  applyMotionPrefs(prefs, prefersReducedMotion());
  return prefs;
}
