import { afterEach, describe, expect, it } from "vitest";
import {
  DEFAULT_FONT_SCALE,
  FONT_SCALE_STORAGE_KEY,
  applyFontScale,
  initFontScale,
  readFontScale,
  writeFontScale,
} from "./fontScaleStorage";

afterEach(() => {
  localStorage.removeItem(FONT_SCALE_STORAGE_KEY);
  document.documentElement.removeAttribute("data-font-scale");
});

describe("fontScaleStorage", () => {
  it("defaults to the standard scale", () => {
    expect(readFontScale()).toBe(DEFAULT_FONT_SCALE);
    expect(DEFAULT_FONT_SCALE).toBe("standard");
  });

  it("falls back to standard for unknown stored values", () => {
    localStorage.setItem(FONT_SCALE_STORAGE_KEY, "huge");
    expect(readFontScale()).toBe("standard");
  });

  it("persists the chosen scale", () => {
    writeFontScale("large");

    expect(localStorage.getItem(FONT_SCALE_STORAGE_KEY)).toBe("large");
    expect(readFontScale()).toBe("large");
    expect(document.documentElement.getAttribute("data-font-scale")).toBe(
      "large",
    );
  });

  it("applies the stored scale on boot", () => {
    localStorage.setItem(FONT_SCALE_STORAGE_KEY, "small");

    expect(initFontScale()).toBe("small");
    expect(document.documentElement.getAttribute("data-font-scale")).toBe(
      "small",
    );
  });

  it("applyFontScale only touches the data attribute", () => {
    applyFontScale("large");
    expect(document.documentElement.dataset.fontScale).toBe("large");
  });
});
