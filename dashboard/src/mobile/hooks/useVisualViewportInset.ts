import { useEffect, useState } from "react";

/**
 * Height (px) the on-screen keyboard covers. ``0`` when it is closed.
 *
 * iOS Safari shrinks ``visualViewport`` instead of the layout viewport, so the
 * difference between the two is the keyboard overlap the composer must offset.
 */
export function useVisualViewportInset(): number {
  const [inset, setInset] = useState(0);

  useEffect(() => {
    const vv = window.visualViewport;
    if (!vv) return;
    const update = () => {
      const overlap = Math.max(
        0,
        window.innerHeight - vv.height - vv.offsetTop,
      );
      // Ignore sub-pixel jitter and the browser chrome resize on rotate.
      setInset(overlap > 80 ? Math.round(overlap) : 0);
    };
    update();
    vv.addEventListener("resize", update);
    vv.addEventListener("scroll", update);
    return () => {
      vv.removeEventListener("resize", update);
      vv.removeEventListener("scroll", update);
    };
  }, []);

  return inset;
}

/** True while the keyboard overlaps the layout viewport. */
export function useMobileKeyboardOpen(): boolean {
  return useVisualViewportInset() > 0;
}
