/**
 * Dynamic mount probe for one DSH bundle.
 *
 * Usage: ``node probe.mjs '<json>'`` with ``{entry, inject, settleMs, cwd}``.
 * It imports the host entry, mounts it on the shared Cordis-compatible context,
 * then prints one JSON line and exits. Disposable by design; the persistent
 * runtime lives in ``runner.mjs`` and uses the same host services.
 */

import { pathToFileURL } from "node:url";
import { Context } from "./cordis-lite.mjs";
import { createHostServices } from "./host-services.mjs";

const req = JSON.parse(process.argv[2] || "{}");
const finished = { value: false };

function result(value) {
  if (finished.value) return;
  finished.value = true;
  try {
    console.log(JSON.stringify(value));
  } catch (error) {
    console.log(JSON.stringify({ class: "FAILED", code: "RUNTIME_THROW", error: String(error) }));
  }
  process.exit(0);
}

process.on("uncaughtException", (error) =>
  result({ class: "FAILED", code: "RUNTIME_THROW", error: String(error && error.stack ? error.stack : error).slice(-2000) }),
);
process.on("unhandledRejection", (error) =>
  result({ class: "FAILED", code: "RUNTIME_THROW", error: String(error && error.stack ? error.stack : error).slice(-2000) }),
);

function classifyError(message) {
  if (/is not a function/.test(message)) return "SIGNATURE_MISMATCH";
  if (/Cannot find package '@deepseek-ai\//.test(message)) return "MISSING_API";
  if (/Cannot find (module|package)/.test(message)) return "MISSING_API";
  if (/\.node\b|NODE_MODULE_VERSION/.test(message)) return "NATIVE_MODULE";
  return "RUNTIME_THROW";
}

const { services, state } = createHostServices({
  pluginId: req.entry || "probe",
  rpc: async () => undefined,
  mode: "probe",
});
const ctx = new Context({ services });

let mod;
try {
  mod = await import(pathToFileURL(req.entry).href);
} catch (error) {
  const message = String(error && error.stack ? error.stack : error).slice(-2000);
  const code = classifyError(message);
  result({
    class: "FAILED",
    code,
    error: message,
    missing_packages: [...message.matchAll(/'(@deepseek-ai\/[^']+)'/g)].map((match) => match[1]),
  });
}

const declared = Array.isArray(mod.inject) ? mod.inject : [];
const missing = declared.filter((name) => !(name in services));

if (typeof mod.apply !== "function" && typeof mod.default !== "function") {
  result({
    class: "FAILED",
    code: "ENTRY_SHAPE",
    error: "module exports neither apply() nor a plugin function default",
    exports: Object.keys(mod).slice(0, 40),
  });
}

let mountError = null;
try {
  ctx.plugin(mod, mod.Config ? {} : undefined);
} catch (error) {
  mountError = String(error && error.stack ? error.stack : error).slice(-2000);
}

await new Promise((resolve) => setTimeout(resolve, Number(req.settleMs) || 400));

const published = {};
for (const [key, value] of Object.entries(ctx.published())) {
  if (value === undefined) continue;
  if (value === null || typeof value !== "object") {
    published[key] = value;
    continue;
  }
  try {
    published[key] = { type: "object", keys: Object.keys(value).slice(0, 25) };
  } catch {
    published[key] = { type: typeof value };
  }
}

if (mountError) {
  result({
    class: "FAILED",
    code: classifyError(mountError),
    error: mountError,
    missing,
    accessed: [...new Set(ctx.accessed)],
    published,
    routes: state.routes.length,
    tools: state.tools.length,
    sections: state.prompts.length,
    unsupported: [...state.unsupported].slice(0, 30),
  });
}

result({
  class: missing.length ? "PARTIAL" : "OK",
  code: missing.length ? "MISSING_API" : "OK",
  name: mod.name || null,
  missing,
  accessed: [...new Set(ctx.accessed)],
  provided: Object.keys(ctx.published()).slice(0, 30),
  published,
  routes: state.routes.map(({ kind, path }) => ({ kind, path })).slice(0, 20),
  tools: state.tools.map(({ name }) => name).filter(Boolean).slice(0, 30),
  sections: state.prompts.map(({ name, kind }) => ({ name, kind })).slice(0, 20),
  unsupported: [...state.unsupported].slice(0, 30),
});
