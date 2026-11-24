#!/usr/bin/env node
/**
 * One-off extraction: move the `--fn-*` declarations out of theme-vars.css into
 * a TypeScript table.
 *
 * The point is value fidelity, not tidiness: the generator that replaces this
 * file must reproduce every declaration byte for byte, so the extraction copies
 * the source text verbatim (selector order and per-block last-wins included).
 *
 *   node scripts/extract-tokens.mjs          # write src/styles/tokens/tables.ts
 */
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");
const source = resolve(root, "src/styles/theme-vars.css");
const target = resolve(root, "src/styles/tokens/tables.ts");

const css = readFileSync(source, "utf8");
const blocks = [];
let index = 0;

// Walk selector blocks in document order and keep only the ones that declare a
// --fn-* custom property.
for (;;) {
  const open = css.indexOf("{", index);
  if (open === -1) break;
  const selector = css.slice(index, open).trim();
  let depth = 0;
  let close = -1;
  for (let i = open; i < css.length; i += 1) {
    if (css[i] === "{") depth += 1;
    else if (css[i] === "}") {
      depth -= 1;
      if (depth === 0) {
        close = i;
        break;
      }
    }
  }
  if (close === -1) break;
  const body = css.slice(open + 1, close);
  const vars = new Map();
  for (const match of body.matchAll(/(--fn-[a-z0-9-]+)\s*:\s*([^;]+);/g)) {
    vars.set(match[1], match[2].trim());
  }
  if (vars.size > 0) blocks.push({ selector, vars: [...vars.entries()] });
  index = close + 1;
}

const lines = [
  "/*",
  " * Token table — the single source for every --fn-* custom property.",
  " *",
  " * Values are transcribed verbatim from the hand-written declarations that",
  " * used to live in `styles/theme-vars.css`; `scripts/gen-tokens.mjs` renders",
  " * them back out. Do not format the strings: they are CSS values, including",
  " * `var(...)` aliases, and the generator writes them unchanged.",
  " */",
  "",
  "export interface TokenBlock {",
  "  selector: string;",
  "  vars: [string, string][];",
  "}",
  "",
  "export const TOKEN_BLOCKS: TokenBlock[] = [",
];

for (const block of blocks) {
  lines.push("  {");
  lines.push(`    selector: ${JSON.stringify(block.selector)},`);
  lines.push("    vars: [");
  for (const [name, value] of block.vars) {
    lines.push(`      [${JSON.stringify(name)}, ${JSON.stringify(value)}],`);
  }
  lines.push("    ],");
  lines.push("  },");
}

lines.push("];", "");
writeFileSync(target, lines.join("\n"));
const total = blocks.reduce((sum, block) => sum + block.vars.length, 0);
console.log(
  `[extract-tokens] ${blocks.length} blocks, ${total} declarations -> ${target}`,
);
