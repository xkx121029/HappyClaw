/**
 * 正文字号档位（小 / 标准 / 大）。
 *
 * 只调字号相关 CSS 变量，不动布局断点与间距；设置保存在本机，
 * 通过 `html[data-font-scale]` 立即生效，刷新后由启动流程重新应用。
 */

export type FontScale = "small" | "standard" | "large";

export const FONT_SCALE_STORAGE_KEY = "octop:font-scale";
export const DEFAULT_FONT_SCALE: FontScale = "standard";

export const FONT_SCALES: FontScale[] = ["small", "standard", "large"];

export function isFontScale(value: unknown): value is FontScale {
  return typeof value === "string" && (FONT_SCALES as string[]).includes(value);
}

/** 读取本机字号档位；非法或未设置时回退到标准。 */
export function readFontScale(): FontScale {
  try {
    const raw = localStorage.getItem(FONT_SCALE_STORAGE_KEY);
    return isFontScale(raw) ? raw : DEFAULT_FONT_SCALE;
  } catch {
    return DEFAULT_FONT_SCALE;
  }
}

/** 把档位写到 `html[data-font-scale]`，CSS 变量随之切换。 */
export function applyFontScale(scale: FontScale): void {
  if (typeof document === "undefined") return;
  document.documentElement.setAttribute("data-font-scale", scale);
}

/** 持久化并立即应用。 */
export function writeFontScale(scale: FontScale): void {
  applyFontScale(scale);
  try {
    localStorage.setItem(FONT_SCALE_STORAGE_KEY, scale);
  } catch {
    // localStorage 不可用：本次仍已生效，只是刷新后回退
  }
}

/** 应用启动时读取并应用一次，保证刷新后档位仍生效。 */
export function initFontScale(): FontScale {
  const scale = readFontScale();
  applyFontScale(scale);
  return scale;
}
