import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

// Read from disk rather than `?raw`: the CSS pipeline normalises `?raw`
// imports to an empty string in this Vitest setup.
const css = readFileSync(resolve(process.cwd(), "src/styles/tokens.generated.css"), "utf8");

/** Declarations inside the generated blocks, comments removed. */
function declarations(source: string): string[] {
  const withoutComments = source.replace(/\/\*[\s\S]*?\*\//g, "");
  return withoutComments
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.startsWith("--fn-") && line.endsWith(";"));
}

describe("generated token CSS", () => {
  it("emits well-formed declarations", () => {
    const lines = declarations(css);
    expect(lines.length).toBeGreaterThan(50);
    for (const line of lines) {
      expect(line).toMatch(/^--fn-[a-z0-9-]+:\s*[^;{}]+;$/);
    }
  });

  it("never leaks a source comment into a value", () => {
    // A value like `16, // section titles` is not a valid CSS length, so
    // `var(--fn-text-lg)` silently falls back and the type scale is wrong.
    const offenders = declarations(css).filter((line) => line.includes("//"));
    expect(offenders).toEqual([]);
  });

  it("carries unitless or px values only", () => {
    const numeric = declarations(css).filter((line) =>
    /^--fn-(text-(?:2xs|xs|sm|md|lg|xl|2xl)|space|radius|control-height|sidebar)/.test(line),
  );
    expect(numeric.length).toBeGreaterThan(10);
    for (const line of numeric) {
      expect(line).toMatch(/:\s*\d+(\.\d+)?(px|rem|%)?;$/);
    }
  });

  it("keeps the body size at the documented 14px", () => {
    expect(css).toContain("--fn-text-sm: 14px;");
    expect(css).toContain("--fn-text-lg: 16px;");
  });
});
