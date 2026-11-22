/**
 * Vitest jsdom setup.
 *
 * Antd's components rely on a few browser APIs jsdom doesn't ship:
 *   - ``window.matchMedia`` (used by Grid responsive breakpoints)
 *   - ``ResizeObserver`` (used by Card/Drawer/Modal portals)
 *   - ``IntersectionObserver`` (used by virtual lists)
 *
 * Recharts also wants ``ResizeObserver`` for the ``ResponsiveContainer``;
 * it'll log a console error otherwise even though our snapshot tests
 * don't actually render the chart at a real size.
 */

import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";
import { message, notification } from "antd";

// Toasts in tests never need to auto-dismiss, and antd's close timer fires
// after the jsdom environment is torn down (`window is not defined` from
// rc-notification). `duration: 0` skips the timer entirely.
message.config({ duration: 0 });
notification.config({ duration: 0 });

// Auto-mock react-i18next so components' ``t(key, fallback)`` calls
// resolve synchronously to ``fallback`` without needing the real
// i18n module (which would async-fetch tool labels and add 1-2s of
// console noise per test file).
vi.mock("react-i18next", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-i18next")>();

  type TOptions = Record<string, unknown> & { defaultValue?: string };

  // Interpolate ``{{name}}`` placeholders like real i18next so tests can
  // assert user-visible copy such as "已捕获 42 条对话记忆".
  const interpolate = (template: string, options?: TOptions): string => {
    if (!options) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (match, name: string) =>
      name in options ? String(options[name]) : match,
    );
  };

  return {
    ...actual,
    useTranslation: () => ({
      t: (
        key: string,
        fallback?: string | TOptions,
        options?: TOptions,
      ): string => {
        if (typeof fallback === "string") return interpolate(fallback, options);
        if (fallback && typeof fallback === "object") {
          const template = fallback.defaultValue ?? key;
          return interpolate(template, fallback);
        }
        return key;
      },
      i18n: { language: "zh", changeLanguage: () => Promise.resolve() },
    }),
    Trans: ({ children }: { children?: React.ReactNode }) => children,
  };
});

afterEach(() => {
  cleanup();
});

if (typeof window !== "undefined") {
  // matchMedia
  // A plain function, not ``vi.fn``: ``vi.restoreAllMocks()`` in a suite would
  // strip a mock implementation mid-file, and components that probe
  // ``prefers-reduced-motion`` (the mascot engine) would then throw.
  if (!window.matchMedia) {
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: (query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addListener: () => {},
        removeListener: () => {},
        addEventListener: () => {},
        removeEventListener: () => {},
        dispatchEvent: () => false,
      }),
    });
  }

  // ResizeObserver
  class _ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  if (!window.ResizeObserver) {
    (
      window as unknown as { ResizeObserver: typeof _ResizeObserver }
    ).ResizeObserver = _ResizeObserver;
  }

  // IntersectionObserver
  class _IntersectionObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords() {
      return [];
    }
    root = null;
    rootMargin = "";
    thresholds = [];
  }
  if (!window.IntersectionObserver) {
    (
      window as unknown as {
        IntersectionObserver: typeof _IntersectionObserver;
      }
    ).IntersectionObserver = _IntersectionObserver;
  }

  // MutationObserver
  // jsdom implements MutationObserver on ``window``, but vitest's jsdom
  // environment does not reliably expose it as a bare global, and jsdom's
  // implementation omits the spec's ``unobserve`` method. Either gap crashes
  // components that do ``new MutationObserver(...)`` (ChatInput, MessageList,
  // Mascot, CodeEditor, …) or call ``observer.unobserve()``. Install a
  // deterministic no-op stub — matching ResizeObserver / IntersectionObserver
  // above — unless the environment already provides a complete implementation.
  const ExistingMO = (globalThis as { MutationObserver?: unknown })
    .MutationObserver;
  const moHasUnobserve =
    typeof ExistingMO === "function" &&
    typeof (ExistingMO as { prototype?: { unobserve?: unknown } }).prototype
      ?.unobserve === "function";
  if (!moHasUnobserve) {
    class _MutationObserver {
      observe() {}
      unobserve() {}
      disconnect() {}
      takeRecords() {
        return [];
      }
    }
    (
      globalThis as unknown as { MutationObserver: typeof _MutationObserver }
    ).MutationObserver = _MutationObserver;
  }

  // DOMMatrix — pdfjs-dist evaluates matrix math on import, and jsdom has no
  // DOMMatrix, which surfaces as ``ReferenceError: DOMMatrix is not defined``
  // for every suite that transitively imports react-pdf. A stub with the
  // 2D fields pdfjs reads is enough: these suites never rasterize a page.
  if (!("DOMMatrix" in window)) {
    class _DOMMatrix {
      a = 1;
      b = 0;
      c = 0;
      d = 1;
      e = 0;
      f = 0;
      m11 = 1;
      m12 = 0;
      m21 = 0;
      m22 = 1;
      m41 = 0;
      m42 = 0;
      is2D = true;
      isIdentity = true;
      constructor(_init?: unknown) {}
      multiplySelf() {
        return this;
      }
      invertSelf() {
        return this;
      }
      translateSelf() {
        return this;
      }
      scaleSelf() {
        return this;
      }
      rotateSelf() {
        return this;
      }
      toString() {
        return "matrix(1, 0, 0, 1, 0, 0)";
      }
      static fromMatrix() {
        return new _DOMMatrix();
      }
      static fromFloat32Array() {
        return new _DOMMatrix();
      }
      static fromFloat64Array() {
        return new _DOMMatrix();
      }
    }
    (window as unknown as { DOMMatrix: typeof _DOMMatrix }).DOMMatrix =
      _DOMMatrix;
    (globalThis as unknown as { DOMMatrix: typeof _DOMMatrix }).DOMMatrix =
      _DOMMatrix;
  }

  // jsdom doesn't implement ``getComputedStyle().transition`` properly,
  // so antd's wave / motion can throw — silence that one noisy console
  // warning without hiding real errors.
  const _origError = console.error.bind(console);
  console.error = (...args: unknown[]) => {
    const first = args[0];
    if (
      typeof first === "string" &&
      (first.includes(
        "Not implemented: HTMLFormElement.prototype.requestSubmit",
      ) ||
        first.includes("React does not recognize the") ||
        first.includes("antd: ") ||
        first.includes("[antd:"))
    ) {
      return;
    }
    _origError(...args);
  };
}
