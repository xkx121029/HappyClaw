import { describe, expect, it } from "vitest";

import {
  APPEARANCE_EXPORT_MARKER,
  DEFAULT_APPEARANCE,
  checkCustomCss,
  exportAppearance,
  importAppearance,
  isDefaultAppearance,
  parseAppearance,
  readAppearance,
  writeAppearance,
} from "./settings";
import { antdOverrides, cssVars, radiusPx, scaledControlHeight, scaledFontSize } from "./derive";

describe("defaults", () => {
  it("is the 'leave everything alone' state", () => {
    expect(isDefaultAppearance(DEFAULT_APPEARANCE)).toBe(true);
  });

  it("produces no antd overrides and no CSS variables", () => {
    // The whole guarantee that a user who never opens the page sees the old
    // appearance: nothing is written when nothing is chosen.
    expect(antdOverrides(DEFAULT_APPEARANCE)).toEqual({});
    expect(cssVars(DEFAULT_APPEARANCE)).toEqual({});
  });
});

describe("parseAppearance", () => {
  it("falls back to defaults for junk", () => {
    expect(parseAppearance(null)).toEqual(DEFAULT_APPEARANCE);
    expect(parseAppearance("nonsense")).toEqual(DEFAULT_APPEARANCE);
  });

  it("keeps valid values and rejects invalid ones", () => {
    const parsed = parseAppearance({
      radius: "12",
      density: "roomy",
      fontSize: "xl",
      fontFamily: "serif",
      pack: "warmPaper",
    });
    expect(parsed.radius).toBe("12");
    expect(parsed.density).toBe("standard");
    expect(parsed.fontSize).toBe("xl");
    expect(parsed.fontFamily).toBe("serif");
    expect(parsed.pack).toBe("warmPaper");
  });

  it("clamps a custom radius into 0..64", () => {
    expect(parseAppearance({ radius: "custom", customRadius: 999 }).customRadius).toBe(64);
    expect(parseAppearance({ radius: "custom", customRadius: -5 }).customRadius).toBe(0);
  });

  it("drops custom CSS that fails validation", () => {
    const parsed = parseAppearance({ customCss: "@import url('http://x/y.css');" });
    expect(parsed.customCss).toBe("");
  });
});

describe("checkCustomCss", () => {
  it("accepts ordinary rules", () => {
    expect(checkCustomCss(".octop-btn { border-radius: 2px; }").ok).toBe(true);
    expect(checkCustomCss("").ok).toBe(true);
  });

  it("refuses the injection surface", () => {
    expect(checkCustomCss("@import 'x.css';").reason).toBe("import");
    expect(checkCustomCss(".a { background: url(https://evil/x.png); }").reason).toBe("remoteUrl");
    expect(checkCustomCss("<script>alert(1)</script>").reason).toBe("script");
    expect(checkCustomCss(".a { color: red;").reason).toBe("unbalanced");
  });
});

describe("derivation", () => {
  it("maps radius choices to pixels", () => {
    expect(radiusPx({ ...DEFAULT_APPEARANCE, radius: "default" })).toBeNull();
    expect(radiusPx({ ...DEFAULT_APPEARANCE, radius: "0" })).toBe(0);
    expect(radiusPx({ ...DEFAULT_APPEARANCE, radius: "16" })).toBe(16);
    expect(radiusPx({ ...DEFAULT_APPEARANCE, radius: "custom", customRadius: 11 })).toBe(11);
  });

  it("scales density monotonically around the standard control height", () => {
    const standard = scaledControlHeight(34, "standard");
    expect(standard).toBe(34);
    expect(scaledControlHeight(34, "compact")).toBeLessThan(standard);
    expect(scaledControlHeight(34, "comfortable")).toBeGreaterThan(standard);
  });

  it("scales the type ramp monotonically", () => {
    const standard = scaledFontSize(14, "standard");
    expect(scaledFontSize(14, "xs")).toBeLessThan(standard);
    expect(scaledFontSize(14, "xl")).toBeGreaterThan(standard);
  });

  it("emits antd radius + tokens only for what changed", () => {
    const overrides = antdOverrides({ ...DEFAULT_APPEARANCE, radius: "0", density: "compact" });
    expect(overrides.token?.borderRadius).toBe(0);
    expect(overrides.token?.controlHeight).toBeLessThan(34);
    expect(overrides.token?.fontFamily).toBeUndefined();
  });

  it("emits matching CSS variables for the LESS surfaces", () => {
    const vars = cssVars({ ...DEFAULT_APPEARANCE, radius: "12", fontSize: "large" });
    expect(vars["--fn-radius-md"]).toBe("12px");
    expect(Number(vars["--fn-text-sm"].replace("px", ""))).toBeGreaterThan(14);
  });
});

describe("persistence and transfer", () => {
  it("round-trips through storage", () => {
    const store = new Map<string, string>();
    const storage = {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => void store.set(key, value),
    } as unknown as Storage;
    const settings = { ...DEFAULT_APPEARANCE, radius: "4", density: "compact" } as const;
    writeAppearance(settings, storage);
    expect(readAppearance(storage)).toEqual(settings);
  });

  it("exports with a marker and imports its own export", () => {
    const settings = { ...DEFAULT_APPEARANCE, radius: "16", customCss: ".a{color:red}" };
    const text = exportAppearance(settings);
    expect(JSON.parse(text).marker).toBe(APPEARANCE_EXPORT_MARKER);
    const result = importAppearance(text);
    expect(result.ok).toBe(true);
    expect(result.settings).toEqual(settings);
  });

  it("refuses foreign JSON", () => {
    expect(importAppearance('{"radius":"8"}').error).toBe("marker");
    expect(importAppearance("not json").error).toBe("parse");
  });
});
