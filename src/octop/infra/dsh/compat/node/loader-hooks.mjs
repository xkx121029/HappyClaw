/**
 * ESM resolution shims for host packages that only exist inside DSH.
 *
 * A bundle that does ``import { defineTool } from '@deepseek-ai/dsh-tools'``
 * cannot even load when HappyClaw hosts it. ``register()`` from this file is
 * installed by ``runner.mjs``; it keeps the real package when one is installed
 * and falls back to a compatibility module otherwise. The fallback is minimal
 * but functional: tools are plain definitions and schemas only need to build
 * defaults, not validate the DSH config UI.
 */

const SHIMS = new Map([
  ["@deepseek-ai/dsh-tools", "./shims/dsh-tools.mjs"],
  ["@deepseek-ai/schemastery", "./shims/schemastery.mjs"],
  ["@deepseek-ai/schemastery/esm", "./shims/schemastery.mjs"],
]);

export async function resolve(specifier, context, nextResolve) {
  const shim = SHIMS.get(specifier);
  if (!shim) return nextResolve(specifier, context);
  try {
    return await nextResolve(specifier, context);
  } catch (error) {
    if (String(error && error.code) !== "ERR_MODULE_NOT_FOUND") throw error;
    return {
      url: new URL(shim, import.meta.url).href,
      shortCircuit: true,
    };
  }
}
