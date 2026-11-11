/**
 * Window sizing shared by the Early Window and the Dashboard window.
 *
 * The floor keeps the desktop layout intact: the Dashboard falls back to its
 * mobile layout under 767px, and the sidebar already spends 220px of the width,
 * so anything narrower would not be a window the app knows how to fill.
 */
export const MIN_WINDOW_SIZE = { width: 960, height: 600 } as const;

/** Size of the Dashboard window on first launch; later launches restore the last bounds. */
export const DEFAULT_WINDOW_SIZE = { width: 1280, height: 800 } as const;

/**
 * The floor squeezed into the display's work area.
 *
 * A 1366x768 laptop at 150% scaling exposes about 910x480 DIPs, which is less
 * than `MIN_WINDOW_SIZE`. Keeping the nominal floor there would put part of the
 * window off-screen with no way to reach it, so the minimum shrinks to what the
 * screen can actually show.
 */
export function fitMinWindowSize(workArea: { width: number; height: number }): {
  width: number;
  height: number;
} {
  return {
    width: Math.min(MIN_WINDOW_SIZE.width, Math.round(workArea.width)),
    height: Math.min(MIN_WINDOW_SIZE.height, Math.round(workArea.height)),
  };
}

