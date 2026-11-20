/**
 * ``@deepseek-ai/dsh-tools`` compatibility shim.
 *
 * Bundles use it to declare tools. The definition object itself is already
 * what the host runner consumes (``name``/``description``/``parameters``/
 * ``execute``), so ``defineTool`` only has to pass it through. Anything else
 * the package may export is answered with a passthrough factory.
 */

export function defineTool(definition) {
  if (!definition || typeof definition !== "object") {
    throw new TypeError("defineTool expects a definition object");
  }
  return definition;
}

export function tool(definition) {
  return defineTool(definition);
}

function passthrough(..._args) {
  return undefined;
}

export default { defineTool, tool, passthrough };
