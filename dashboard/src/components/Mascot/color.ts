/**
 * Colour helpers for user-picked Bao inks.
 *
 * The engine accepts any CSS colour, but a near-black pick on the dark theme
 * turns the character into a smudge. Everything that stores a hex goes through
 * ``readableOn`` so the rendered mascot always keeps a usable contrast, while
 * the stored value stays exactly what the user chose.
 */

export const MIN_CONTRAST = 3;

export function normalizeHex(value: string | null | undefined): string | null {
  if (!value) return null;
  const raw = value.trim().replace(/^#/, "");
  if (!/^[0-9a-fA-F]{6}$/.test(raw)) return null;
  return `#${raw.toLowerCase()}`;
}

function parseRgb(hex: string): [number, number, number] | null {
  const normalized = normalizeHex(hex);
  if (!normalized) return null;
  return [
    Number.parseInt(normalized.slice(1, 3), 16),
    Number.parseInt(normalized.slice(3, 5), 16),
    Number.parseInt(normalized.slice(5, 7), 16),
  ];
}

function toHex(rgb: [number, number, number]): string {
  return `#${rgb
    .map((channel) =>
      Math.max(0, Math.min(255, Math.round(channel)))
        .toString(16)
        .padStart(2, "0"),
    )
    .join("")}`;
}

function channelLuminance(channel: number): number {
  const value = channel / 255;
  return value <= 0.03928
    ? value / 12.92
    : ((value + 0.055) / 1.055) ** 2.4;
}

export function relativeLuminance(hex: string): number {
  const rgb = parseRgb(hex);
  if (!rgb) return 0;
  const [r, g, b] = rgb;
  return (
    0.2126 * channelLuminance(r) +
    0.7152 * channelLuminance(g) +
    0.0722 * channelLuminance(b)
  );
}

export function contrastRatio(a: string, b: string): number {
  const la = relativeLuminance(a);
  const lb = relativeLuminance(b);
  const light = Math.max(la, lb);
  const dark = Math.min(la, lb);
  return (light + 0.05) / (dark + 0.05);
}

export function meetsContrast(
  hex: string,
  surfaceHex: string,
  min = MIN_CONTRAST,
): boolean {
  return contrastRatio(hex, surfaceHex) >= min;
}

/**
 * Blend ``hex`` toward white on dark surfaces and toward black on light ones
 * until it clears ``min`` against ``surfaceHex``. Returns the input untouched
 * when it already passes or when either colour is not a hex value.
 */
export function readableOn(
  hex: string,
  surfaceHex: string,
  min = MIN_CONTRAST,
): string {
  if (!normalizeHex(hex) || !normalizeHex(surfaceHex)) return hex;
  if (meetsContrast(hex, surfaceHex, min)) return hex;
  const rgb = parseRgb(hex);
  const surface = parseRgb(surfaceHex);
  if (!rgb || !surface) return hex;
  // Pick the direction that can actually reach the target contrast: a mid-tone
  // body (e.g. the dark-theme black ink, #c2c2c2) needs dark eyes, while a very
  // dark surface needs light ones.
  const towardsWhite =
    contrastRatio("#ffffff", surfaceHex) >= contrastRatio("#000000", surfaceHex);
  const target: [number, number, number] = towardsWhite
    ? [255, 255, 255]
    : [0, 0, 0];
  for (let step = 1; step <= 20; step += 1) {
    const mix = step / 20;
    const candidate = toHex([
      rgb[0] + (target[0] - rgb[0]) * mix,
      rgb[1] + (target[1] - rgb[1]) * mix,
      rgb[2] + (target[2] - rgb[2]) * mix,
    ]);
    if (meetsContrast(candidate, surfaceHex, min)) return candidate;
  }
  return toHex(target);
}

/** Read a ``--fn-*`` hex token from the document root. */
export function readRootHex(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const value = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
  return normalizeHex(value) ?? fallback;
}

/**
 * Resolve the engine's ``--fg`` to a hex. The engine writes either a plain
 * colour or ``light-dark(a, b)``; the latter is left unresolved by
 * ``getComputedStyle`` on custom properties, so pick the half for the scheme.
 */
export function resolveColorHex(raw: string, dark: boolean): string | null {
  const value = raw.trim();
  if (!value) return null;
  const pair = value.match(/^light-dark\(\s*([^,]+?)\s*,\s*(.+?)\s*\)$/i);
  if (pair) return normalizeHex(dark ? pair[2] : pair[1]);
  return normalizeHex(value);
}
