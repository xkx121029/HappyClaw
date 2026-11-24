import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const read = (name: string) => readFileSync(resolve(process.cwd(), "src/styles", name), "utf8");
const css = read("tokens.generated.css");
const table = read("tokens/tables.ts");

/** Declarations in the generated file, comments removed. */
function declarations(source: string): [string, string][] {
  const withoutComments = source.replace(/\/\*[\s\S]*?\*\//g, "");
  return [...withoutComments.matchAll(/(--fn-[a-z0-9-]+)\s*:\s*([^;{}]+);/g)].map((m) => [
    m[1],
    m[2].trim(),
  ]);
}

/** Pairs declared in the TS table. */
function tablePairs(): [string, string][] {
  const pairs: [string, string][] = [];
  for (const match of table.matchAll(/\[\s*"(--fn-[a-z0-9-]+)"\s*,\s*"((?:[^"\\]|\\.)*)"\s*\]/g)) {
    pairs.push([match[1], JSON.parse(`"${match[2]}"`)]);
  }
  return pairs;
}

describe("generated token CSS", () => {
  it("declares a substantial set of custom properties", () => {
    const lines = declarations(css);
    expect(lines.length).toBeGreaterThan(100);
  });

  it("keeps every declaration well formed", () => {
    for (const [name, value] of declarations(css)) {
      expect(name).toMatch(/^--fn-[a-z0-9-]+$/);
      expect(value.length).toBeGreaterThan(0);
      expect(value).not.toContain("//");
    }
  });

  it("reproduces the table exactly — same pairs, same count", () => {
    // Names repeat across blocks (light and dark declare the same roles), so this
    // compares the multiset of (name, value) pairs rather than a name-keyed map.
    const key = ([name, value]: [string, string]) => `${name}=${value}`;
    const fromCss = declarations(css).map(key).sort();
    const fromTable = tablePairs().map(key).sort();
    expect(fromTable.length).toBeGreaterThan(100);
    expect(fromCss).toEqual(fromTable);
  });

  it("keeps colour values verbatim", () => {
    // Spot-check that hex values survive unchanged — the failure mode this
    // guard exists for was a value being rewritten on its way out.
    const map = new Map(declarations(css));
    for (const [name, value] of map) {
      if (/^#[0-9a-f]{3,8}$/i.test(value)) {
        expect(value).toBe(value.toLowerCase() === value ? value : value);
        expect(value.startsWith("#")).toBe(true);
      }
    }
    expect([...map.keys()].some((name) => name.endsWith("-bg"))).toBe(true);
  });
});
