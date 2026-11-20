/**
 * Design-token guard.
 *
 * These assertions keep the single-source-of-truth architecture from silently
 * decaying: generated CSS must match the TS tables, the touch-scale aliases that
 * were retired must not come back, and every `--fn-*` reference in the
 * stylesheets must resolve to a declared variable.
 */

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";

/** Tests run with cwd = `dashboard/`; resolve paths from there. */
const STYLES = resolve(process.cwd(), "src/styles");
const SRC = resolve(process.cwd(), "src");
const GENERATED = join(STYLES, "tokens.generated.css");

/** Aliases merged into a canonical role; re-introducing one is a regression. */
const RETIRED_ALIASES = [
  "--fn-text-2xs-old",
  "--fn-color-error-muted",
];

/** Every `.css` / `.less` under src, excluding the generated file itself. */
function styleFiles(dir = SRC): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      if (entry === "node_modules" || entry === "dist") continue;
      out.push(...styleFiles(full));
      continue;
    }
    if (!/\.(css|less)$/.test(entry)) continue;
    if (full === GENERATED) continue;
    out.push(full);
  }
  return out;
}

function declaredVars(): Set<string> {
  const names = new Set<string>();
  for (const file of [GENERATED, ...styleFiles()]) {
    const text = readFileSync(file, "utf8");
    for (const match of text.matchAll(/(--fn-[\w-]+)\s*:/g)) {
      names.add(match[1]);
    }
  }
  return names;
}

function referencedVars(): Map<string, string[]> {
  const refs = new Map<string, string[]>();
  for (const file of styleFiles()) {
    const text = readFileSync(file, "utf8");
    for (const match of text.matchAll(/var\((--fn-[\w-]+)/g)) {
      const list = refs.get(match[1]) ?? [];
      list.push(relative(SRC, file).replace(/\\/g, "/"));
      refs.set(match[1], list);
    }
  }
  return refs;
}

describe("design tokens", () => {
  it("generated CSS matches the TS token tables", () => {
    // `gen-tokens.mjs --check` is the authoritative comparison; this asserts the
    // file exists and carries the drift warning so a manual edit is obvious.
    const text = readFileSync(GENERATED, "utf8");
    expect(text).toContain("AUTO-GENERATED");
    expect(text).toContain("--fn-text-lg: 16px");
    expect(text).toContain("--fn-radius-md: 8px");
  });

  it("no retired alias is referenced or declared", () => {
    const raw = [GENERATED, ...styleFiles()]
      .map((f) => readFileSync(f, "utf8"))
      .join("\n");
    for (const alias of RETIRED_ALIASES) {
      expect(raw).not.toContain(alias);
    }
  });

  it("every --fn-* reference resolves to a declared variable", () => {
    const declared = declaredVars();
    const missing: string[] = [];
    for (const [name, files] of referencedVars()) {
      // Skip focus-ring internals that are composed at use site.
      if (declared.has(name)) continue;
      missing.push(`${name} (${[...new Set(files)].slice(0, 3).join(", ")})`);
    }
    expect(missing).toEqual([]);
  });

  it("type scale never goes below 12px", () => {
    const text = readFileSync(GENERATED, "utf8");
    for (const match of text.matchAll(/--fn-text-[\w-]+:\s*(\d+(?:\.\d+)?)px/g)) {
      expect(Number(match[1])).toBeGreaterThanOrEqual(12);
    }
  });

  it("equal-value font sizes reference the generated scale", () => {
    // `scripts/codemod-tokens.mjs` replaced every hard-coded size that already
    // sits on the scale with a 1:1 token (same computed px). A new literal with
    // one of those values means a stylesheet opted out of the scale again.
    // Directories with their own work streams are excluded until their batch.
    const SKIP = [
      "pages/Home/",
      "pages/Admin/Plugins/",
      "pages/Settings/SearchConfig/",
      "mobile/",
    ];
    const scale = new Map<number, string>();
    for (const line of readFileSync(GENERATED, "utf8").split("\n")) {
      const match = /--fn-text-([\w-]+):\s*(\d+)px;\s*$/.exec(line.trim());
      if (match) scale.set(Number(match[2]), match[1]);
    }
    const offenders: string[] = [];
    for (const file of styleFiles()) {
      const rel = relative(SRC, file).replace(/\\/g, "/");
      if (SKIP.some((prefix) => rel.startsWith(prefix))) continue;
      for (const match of readFileSync(file, "utf8").matchAll(
        /(?<![\w-])font-size:\s*(\d+(?:\.\d+)?)px/g,
      )) {
        const token = scale.get(Number(match[1]));
        if (token) offenders.push(`${rel}: ${match[1]}px → var(--fn-text-${token})`);
      }
    }
    expect(offenders.slice(0, 20)).toEqual([]);
  });

  it("dark-mode CSS does not patch what the antd theme already provides", () => {
    // `antdThemeConfig` maps semantic tokens onto antd's token names, so a
    // `html[data-theme="dark"] .ant-*` rule that only restates a background or
    // text colour is dead weight that drifts. `!important` is the tell: the
    // remaining intentional overrides are written without it.
    const offenders: string[] = [];
    for (const file of styleFiles()) {
      const lines = readFileSync(file, "utf8").split("\n");
      let selectorOpen = false;
      let block: string[] = [];
      let blockStart = 0;
      lines.forEach((line, index) => {
        if (!selectorOpen) {
          if (!/data-theme="dark"/.test(line)) return;
          selectorOpen = true;
          block = [];
          blockStart = index + 1;
          // A one-line rule `sel { … }` closes immediately.
          if (line.includes("}")) selectorOpen = false;
          if (line.includes("{")) block.push(line.slice(line.indexOf("{")));
          return;
        }
        if (line.includes("{")) block.push(line.slice(line.indexOf("{")));
        if (line.includes("}")) {
          selectorOpen = false;
          if (block.join(" ").includes("!important")) {
            offenders.push(
              `${relative(SRC, file).replace(/\\/g, "/")}:${blockStart}`,
            );
          }
        }
      });
    }
    // Allow-list is empty: the refactor removed every one of these.
    expect(offenders).toEqual([]);
  });
});
