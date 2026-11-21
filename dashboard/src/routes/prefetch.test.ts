import { describe, expect, it } from "vitest";
import { buildNavSections } from "../layouts/sidebarNav";
import { prefetchRoute, ROUTE_PREFETCH_PATHS } from "./prefetch";

/**
 * Hovering a sidebar item calls prefetchRoute(item.path). If a nav path is
 * missing from the prefetch table, hovering it silently no-ops and the page
 * still loads cold on click — an easy regression when wiring a new route.
 * This guard pins the table to the actual sidebar surface.
 */
describe("route hover-prefetch table", () => {
  it("covers every sidebar nav path exposed by buildNavSections", () => {
    const navPaths = buildNavSections().flatMap((section) =>
      section.items.map((item) => item.path),
    );
    const covered = new Set(ROUTE_PREFETCH_PATHS);
    const missing = navPaths.filter((p) => !covered.has(p));
    expect(missing).toEqual([]);
  });

  it("covers the first-class sidebar buttons rendered outside buildNavSections", () => {
    const covered = new Set(ROUTE_PREFETCH_PATHS);
    expect(covered.has("/solo")).toBe(true);
    expect(covered.has("/bao")).toBe(true);
    expect(covered.has("/bridge")).toBe(true);
  });

  it("prefetchRoute is a safe no-op for unknown paths", () => {
    expect(() => prefetchRoute("/not-a-real-route")).not.toThrow();
    expect(() => prefetchRoute("/home")).not.toThrow();
  });
});