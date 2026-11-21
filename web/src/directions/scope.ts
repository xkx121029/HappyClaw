import { useEffect, useSyncExternalStore } from "react";

import { useUiStore } from "@/stores/ui";

export type DirectionId = "a" | "b" | "c";
export type DirectionPageId = "chat" | "design";

export function isDirectionId(value: string): value is DirectionId {
  return value === "a" || value === "b" || value === "c";
}

export function isDirectionPageId(value: string): value is DirectionPageId {
  return value === "chat" || value === "design";
}

/**
 * Token files are scoped with `html[data-direction="…"]`, so the scope lives on
 * the document element. Every shared component then restyles itself through the
 * same variables it always used — no second copy of the component library.
 */
export function useDirectionScope(direction: DirectionId) {
  useEffect(() => {
    const root = document.documentElement;
    root.dataset.direction = direction;
    return () => {
      delete root.dataset.direction;
    };
  }, [direction]);
}

function subscribeToTheme(onChange: () => void) {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["class", "data-direction"],
  });
  return () => observer.disconnect();
}

/**
 * Read a semantic token back from the live stylesheet, so the hex printed on
 * the spec page is the one actually painted. Subscribes to the document's class
 * changes, which is how the theme flips.
 */
export function useTokenValue(token: string) {
  return useSyncExternalStore(
    subscribeToTheme,
    () =>
      getComputedStyle(document.documentElement)
        .getPropertyValue(token)
        .trim(),
    () => "",
  );
}

export function useThemeToggle() {
  const theme = useUiStore((state) => state.theme);
  const toggleTheme = useUiStore((state) => state.toggleTheme);
  return { theme, toggleTheme };
}
