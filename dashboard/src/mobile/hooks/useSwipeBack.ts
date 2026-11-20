import { useEffect, useRef } from "react";

interface SwipeBackOptions {
  enabled?: boolean;
  onBack: () => void;
}

/**
 * Left-edge swipe-to-go-back. Only fires for a mostly-horizontal gesture that
 * starts within 24px of the left edge, so it never fights the message list.
 */
export function useSwipeBack({ enabled = true, onBack }: SwipeBackOptions) {
  const callback = useRef(onBack);
  callback.current = onBack;

  useEffect(() => {
    if (!enabled) return;
    let startX = 0;
    let startY = 0;
    let tracking = false;

    const onStart = (event: TouchEvent) => {
      if (event.touches.length !== 1) return;
      const touch = event.touches[0];
      tracking = touch.clientX < 24;
      startX = touch.clientX;
      startY = touch.clientY;
    };

    const onMove = (event: TouchEvent) => {
      if (!tracking || event.touches.length !== 1) return;
      const touch = event.touches[0];
      const dx = touch.clientX - startX;
      const dy = Math.abs(touch.clientY - startY);
      if (dx < -12 || dy > 48) {
        tracking = false;
        return;
      }
      if (dx > 72 && dy < 40) {
        tracking = false;
        callback.current();
      }
    };

    const onEnd = () => {
      tracking = false;
    };

    window.addEventListener("touchstart", onStart, { passive: true });
    window.addEventListener("touchmove", onMove, { passive: true });
    window.addEventListener("touchend", onEnd, { passive: true });
    window.addEventListener("touchcancel", onEnd, { passive: true });
    return () => {
      window.removeEventListener("touchstart", onStart);
      window.removeEventListener("touchmove", onMove);
      window.removeEventListener("touchend", onEnd);
      window.removeEventListener("touchcancel", onEnd);
    };
  }, [enabled]);
}
