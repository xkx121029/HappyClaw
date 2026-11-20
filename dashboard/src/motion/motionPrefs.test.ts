import { afterEach, describe, expect, it } from "vitest";
import {
  DEFAULT_MOTION_PREFS,
  MOTION_PREFS_STORAGE_KEY,
  applyMotionPrefs,
  normalizeBezier,
  normalizeMotionPrefs,
  readMotionPrefs,
  writeMotionPrefs,
} from "./motionPrefs";
import {
  BASE_DURATIONS,
  ENTER_CURVES,
  EXIT_CURVE,
  bezierToCss,
  motionCssVars,
  resolveMotionTokens,
} from "./tokens";

afterEach(() => {
  localStorage.removeItem(MOTION_PREFS_STORAGE_KEY);
  const root = document.documentElement;
  root.removeAttribute("data-motion-curve");
  root.removeAttribute("data-motion-speed");
  root.removeAttribute("data-motion-reduced");
  root.removeAttribute("style");
});

describe("normalizeBezier", () => {
  it("keeps valid control points", () => {
    expect(normalizeBezier([0.3, 0.9, 0.5, 1])).toEqual([0.3, 0.9, 0.5, 1]);
  });

  it("clamps x into [0,1] and y into the allowed overshoot range", () => {
    expect(normalizeBezier([-1, 4, 2, -3])).toEqual([0, 1.6, 1, -0.6]);
  });

  it("falls back to the default curve for malformed input", () => {
    const fallback = ENTER_CURVES.comfort;
    expect(normalizeBezier(null)).toEqual(fallback);
    expect(normalizeBezier([1, 2, 3])).toEqual(fallback);
    expect(normalizeBezier([1, "x", 0.2, 1])).toEqual(fallback);
  });
});

describe("normalizeMotionPrefs", () => {
  it("rejects unknown preset and speed values", () => {
    const prefs = normalizeMotionPrefs({ curve: "bouncy", speed: "turbo" });
    expect(prefs.curve).toBe(DEFAULT_MOTION_PREFS.curve);
    expect(prefs.speed).toBe(DEFAULT_MOTION_PREFS.speed);
    expect(prefs.custom).toEqual(DEFAULT_MOTION_PREFS.custom);
  });
});

describe("resolveMotionTokens", () => {
  it("scales the duration ladder by speed", () => {
    const standard = resolveMotionTokens({
      curve: "comfort",
      speed: "standard",
      custom: ENTER_CURVES.comfort,
    });
    const gentle = resolveMotionTokens({
      curve: "comfort",
      speed: "gentle",
      custom: ENTER_CURVES.comfort,
    });
    const brisk = resolveMotionTokens({
      curve: "comfort",
      speed: "brisk",
      custom: ENTER_CURVES.comfort,
    });

    expect(standard.duration.base).toBe(BASE_DURATIONS.base);
    expect(gentle.duration.base).toBeGreaterThan(standard.duration.base);
    expect(brisk.duration.base).toBeLessThan(standard.duration.base);
  });

  it("uses the selected preset for entering and accelerates on exit", () => {
    const tokens = resolveMotionTokens({
      curve: "spring",
      speed: "standard",
      custom: ENTER_CURVES.comfort,
    });
    expect(tokens.enterBezier).toEqual(ENTER_CURVES.spring);
    expect(tokens.exitBezier).toEqual(EXIT_CURVE);
    expect(tokens.enterEase).toBe(bezierToCss(ENTER_CURVES.spring));
  });

  it("drops movement and scaling when reduced motion is requested", () => {
    const tokens = resolveMotionTokens(
      { curve: "comfort", speed: "standard", custom: ENTER_CURVES.comfort },
      true,
    );
    expect(tokens.reduced).toBe(true);
    expect(tokens.shift.md).toBe(0);
    expect(tokens.scale.card).toBe(1);
  });
});

describe("applyMotionPrefs", () => {
  it("writes tokens to the root element and mirrors legacy vars", () => {
    applyMotionPrefs({ curve: "swift", speed: "brisk", custom: ENTER_CURVES.comfort }, false);
    const root = document.documentElement;
    expect(root.getAttribute("data-motion-curve")).toBe("swift");
    expect(root.getAttribute("data-motion-speed")).toBe("brisk");
    expect(root.getAttribute("data-motion-reduced")).toBe("false");
    expect(root.style.getPropertyValue("--motion-ease-enter")).toBe(
      bezierToCss(ENTER_CURVES.swift),
    );
    expect(root.style.getPropertyValue("--fn-ease-out")).toBe(
      bezierToCss(ENTER_CURVES.swift),
    );
  });

  it("zeroes shift vars when reduced", () => {
    applyMotionPrefs(DEFAULT_MOTION_PREFS, true);
    expect(
      document.documentElement.style.getPropertyValue("--motion-shift-md"),
    ).toBe("0px");
  });
});

describe("readMotionPrefs / writeMotionPrefs", () => {
  it("round-trips preferences", () => {
    writeMotionPrefs({
      curve: "custom",
      speed: "gentle",
      custom: [0.1, 0.7, 0.3, 1],
    });
    expect(readMotionPrefs()).toEqual({
      curve: "custom",
      speed: "gentle",
      custom: [0.1, 0.7, 0.3, 1],
    });
  });

  it("falls back to defaults on corrupted storage", () => {
    localStorage.setItem(MOTION_PREFS_STORAGE_KEY, "{not json");
    expect(readMotionPrefs()).toEqual(DEFAULT_MOTION_PREFS);
  });
});

describe("motionCssVars", () => {
  it("mirrors duration and easing onto legacy --fn vars", () => {
    const tokens = resolveMotionTokens(
      { curve: "smooth", speed: "standard", custom: ENTER_CURVES.comfort },
      false,
    );
    const vars = motionCssVars(tokens);
    expect(vars["--fn-duration-base"]).toBe(`${tokens.duration.base}ms`);
    expect(vars["--fn-ease-standard"]).toBe(tokens.standardEase);
    expect(vars["--motion-duration-slow"]).toBe(`${tokens.duration.slow}ms`);
  });
});
