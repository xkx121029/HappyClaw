#!/usr/bin/env node
/**
 * Locale parity gate: every namespace must expose exactly the same key set in
 * `en` and `zh`, and the two files must agree on plural suffixes. Exits non-zero
 * on the first mismatch so CI can fail fast.
 */
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const root = new URL("../src/locales/", import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1");
const locales = ["en", "zh"];

/** Flattens a nested JSON object into dotted paths. */
function flatten(value, prefix = "", out = new Map()) {
  for (const [key, child] of Object.entries(value)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (child && typeof child === "object" && !Array.isArray(child)) {
      flatten(child, path, out);
    } else {
      out.set(path, child);
    }
  }
  return out;
}

let failed = false;
const names = readdirSync(join(root, locales[0])).filter((file) => file.endsWith(".json"));

for (const name of names) {
  const trees = locales.map((locale) => {
    const file = join(root, locale, name);
    return flatten(JSON.parse(readFileSync(file, "utf8")));
  });

  const [en, zh] = trees;
  const missingInZh = [...en.keys()].filter((key) => !zh.has(key));
  const missingInEn = [...zh.keys()].filter((key) => !en.has(key));

  const status =
    missingInZh.length === 0 && missingInEn.length === 0 ? "ok" : "MISMATCH";
  if (status !== "ok") failed = true;

  console.log(
    `${status.padEnd(9)} ${name.padEnd(16)} en=${String(en.size).padStart(3)} zh=${String(zh.size).padStart(3)}`,
  );
  if (missingInZh.length) console.log(`  missing in zh: ${missingInZh.join(", ")}`);
  if (missingInEn.length) console.log(`  missing in en: ${missingInEn.join(", ")}`);
}

process.exit(failed ? 1 : 0);
