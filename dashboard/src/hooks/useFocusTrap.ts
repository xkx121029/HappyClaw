import { useEffect, useRef } from "react";

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Keep keyboard focus inside a custom overlay and restore it on close.
 *
 * Our own sheets / drawers (mobile bottom sheets, the "mine" panel, chat
 * previews) are plain divs, so antd's trap does not apply to them. Without
 * this, Tab walks out of the overlay into the page behind it, and closing the
 * overlay leaves focus on `<body>`.
 *
 * Usage:
 *   const ref = useFocusTrap<HTMLDivElement>(open, onClose);
 *   return <div ref={ref}>…</div>;
 *
 * The hook also closes on Escape unless `closeOnEscape` is false.
 */
export function useFocusTrap<T extends HTMLElement>(
  active: boolean,
  onClose?: () => void,
  { closeOnEscape = true }: { closeOnEscape?: boolean } = {},
): { current: T | null } {
  // Mutable so callers that also need the node (drag handlers, layout
  // measurement) can share the same ref instead of a second one.
  const containerRef = useRef<T | null>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!active) return;
    const container = containerRef.current;
    previouslyFocused.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;

    const focusFirst = () => {
      if (!container) return;
      const target =
        container.querySelector<HTMLElement>(FOCUSABLE) ?? container;
      target.focus({ preventScroll: true });
    };
    // Wait one frame so the overlay has actually painted (mobile sheets mount
    // the content in the same tick they become visible).
    const raf = requestAnimationFrame(focusFirst);

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && closeOnEscape) {
        event.preventDefault();
        onClose?.();
        return;
      }
      if (event.key !== "Tab" || !container) return;
      const items = Array.from(
        container.querySelectorAll<HTMLElement>(FOCUSABLE),
      ).filter((el) => el.offsetParent !== null || el === document.activeElement);
      if (items.length === 0) {
        event.preventDefault();
        container.focus({ preventScroll: true });
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const current = document.activeElement;
      if (!event.shiftKey && current === last) {
        event.preventDefault();
        first.focus();
      } else if (event.shiftKey && current === first) {
        event.preventDefault();
        last.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown);
    return () => {
      cancelAnimationFrame(raf);
      document.removeEventListener("keydown", onKeyDown);
      previouslyFocused.current?.focus?.({ preventScroll: true });
    };
  }, [active, onClose, closeOnEscape]);

  return containerRef;
}

/**
 * Enter/Space activation for elements that must stay non-button (custom rows,
 * cards). Returns the props to spread so the element is keyboard-equivalent to
 * a button while keeping its existing markup.
 */
export function keyboardActivationProps(
  onActivate: () => void,
  { disabled = false }: { disabled?: boolean } = {},
) {
  if (disabled) return {};
  return {
    role: "button" as const,
    tabIndex: 0,
    onKeyDown: (event: React.KeyboardEvent) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        onActivate();
      }
    },
  };
}
