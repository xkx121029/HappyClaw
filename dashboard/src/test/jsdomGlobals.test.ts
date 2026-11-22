import { describe, expect, it } from "vitest";

/**
 * Guards for browser globals that jsdom exposes on ``window`` but vitest's
 * jsdom environment does not always mirror onto ``globalThis``.
 *
 * ``setup.ts`` aliases these onto the global so components referencing the
 * bare global (e.g. ``new MutationObserver(...)``) don't crash under the
 * threads pool. These tests pin that contract so a future jsdom / vitest
 * bump can't silently regress it.
 */
describe("jsdom environment globals (setup.ts)", () => {
  it("exposes MutationObserver as a constructor on globalThis", () => {
    expect(typeof globalThis.MutationObserver).toBe("function");

    const observer = new globalThis.MutationObserver(() => {});
    expect(typeof observer.observe).toBe("function");
    expect(typeof observer.unobserve).toBe("function");
    expect(typeof observer.disconnect).toBe("function");
    expect(typeof observer.takeRecords).toBe("function");

    // Observing the document must not throw in the jsdom environment.
    expect(() =>
      observer.observe(document.documentElement, { childList: true }),
    ).not.toThrow();
    expect(Array.isArray(observer.takeRecords())).toBe(true);
    observer.disconnect();
  });

  it("keeps ResizeObserver and IntersectionObserver constructors available", () => {
    expect(typeof globalThis.ResizeObserver).toBe("function");
    expect(typeof globalThis.IntersectionObserver).toBe("function");

    const ro = new globalThis.ResizeObserver(() => {});
    expect(typeof ro.observe).toBe("function");
    expect(typeof ro.disconnect).toBe("function");
    ro.disconnect();

    const io = new globalThis.IntersectionObserver(() => {});
    expect(Array.isArray(io.takeRecords())).toBe(true);
    io.disconnect();
  });
});
