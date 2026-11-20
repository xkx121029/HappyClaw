import { useEffect, useState } from "react";
import { KEYBOARD_GAP_THRESHOLD_PX, measureLayoutHeight } from "./viewport";

/**
 * True while the soft keyboard covers the bottom of the layout viewport.
 *
 * Used by the mobile tab bar: when the keyboard is up the bar would otherwise
 * sit above the keyboard (PWA) and steal space from the composer, or be buried
 * under it (mobile browser). Both read badly, so it simply steps aside.
 *
 * Android Chrome already resizes the layout viewport with the keyboard, so the
 * measured gap stays near zero there and the bar legitimately stays visible.
 */
export function useMobileKeyboardOpen(enabled: boolean): boolean {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!enabled || typeof window === "undefined") {
      setOpen(false);
      return;
    }
    const viewport = window.visualViewport;
    if (!viewport) return;

    const update = () => {
      const covered = measureLayoutHeight() - viewport.height - viewport.offsetTop;
      // Browser chrome alone is ~60–90px; a real keyboard is far taller.
      setOpen(covered > KEYBOARD_GAP_THRESHOLD_PX + 40);
    };

    viewport.addEventListener("resize", update);
    viewport.addEventListener("scroll", update);
    window.addEventListener("resize", update);
    update();

    return () => {
      viewport.removeEventListener("resize", update);
      viewport.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
    };
  }, [enabled]);

  return open;
}
