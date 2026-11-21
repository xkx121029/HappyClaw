#!/usr/bin/env node
/**
 * Sync the backend OpenAPI document into `openapi/octop.openapi.json`.
 *
 *   npm run api:sync -- ../live-openapi.json
 *   npm run api:sync                      # boots nothing; expects a file argument
 *
 * FastAPI emits the same operationId for several `dsh-compat` proxy routes,
 * which makes `openapi-typescript` produce duplicate interface members. We
 * suffix the repeats (id, id_2, id_3 …) and nothing else, so the committed
 * document still matches the backend route for route.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

const source = process.argv[2];
if (!source) {
  console.error("usage: node scripts/sync-openapi.mjs <path-to-openapi.json>");
  process.exit(1);
}

const spec = JSON.parse(readFileSync(source, "utf8"));
const seen = new Map();
let renamed = 0;

for (const [path, item] of Object.entries(spec.paths ?? {})) {
  for (const method of ["get", "put", "post", "delete", "patch", "options", "head"]) {
    const operation = item?.[method];
    if (!operation?.operationId) continue;
    const id = operation.operationId;
    const count = (seen.get(id) ?? 0) + 1;
    seen.set(id, count);
    if (count > 1) {
      operation.operationId = `${id}_${count}`;
      renamed += 1;
    }
  }
}

const target = resolve(import.meta.dirname, "../openapi/octop.openapi.json");
writeFileSync(target, `${JSON.stringify(spec, null, 1)}\n`, "utf8");
console.log(
  `wrote ${target} — ${Object.keys(spec.paths ?? {}).length} paths, ${renamed} duplicate operationIds renamed`,
);
