/**
 * ``@deepseek-ai/schemastery`` compatibility shim.
 *
 * Bundles import it to declare their config schema. HappyClaw does not render
 * a DSH config page, so the only behaviour that matters is:
 *
 *   * every builder method chains (``z.boolean().default(true).volatile()``),
 *   * a schema can be called to produce a resolved value with defaults,
 *   * ``z.object`` nests the same way.
 *
 * Validation is intentionally permissive: a value that fails a check is kept
 * rather than rejected, because the plugin falls back to its own defaults.
 */

const CHAIN_METHODS = new Set([
  "default",
  "min",
  "max",
  "step",
  "required",
  "description",
  "role",
  "hidden",
  "disabled",
  "volatile",
  "comment",
  "extra",
  "link",
  "set",
  "alias",
  "deprecated",
  "deprecate",
  "permission",
  "collapse",
]);

function resolvedDefault(state) {
  if (state.default !== undefined) return state.default;
  if (state.kind === "object" && state.shape) {
    const out = {};
    for (const [key, schema] of Object.entries(state.shape)) {
      const value = schemaDefault(schema);
      if (value !== undefined) out[key] = value;
    }
    return out;
  }
  if (state.kind === "array") return [];
  if (state.kind === "dict") return {};
  return undefined;
}

function schemaDefault(schema) {
  if (schema && typeof schema === "object" && schema.__schemaState) {
    return resolvedDefault(schema.__schemaState);
  }
  return undefined;
}

function coerce(state, value) {
  if (value === undefined || value === null) return resolvedDefault(state);
  if (state.kind === "object" && state.shape && typeof value === "object") {
    const out = {};
    for (const [key, schema] of Object.entries(state.shape)) {
      const fallback = schemaDefault(schema);
      const given = value[key];
      out[key] = given === undefined ? fallback : given;
      if (out[key] === undefined) delete out[key];
    }
    return { ...value, ...out };
  }
  return value;
}

function makeSchema(kind, shape) {
  const state = { kind, shape, default: undefined };
  const callable = (value) => coerce(state, value);
  let proxy;
  proxy = new Proxy(callable, {
    get(target, prop) {
      if (prop === "__schemaState") return state;
      if (prop === "then" || prop === "toJSON") return undefined;
      if (prop === "toString" || prop === "valueOf") {
        return () => `[schemastery:${kind}]`;
      }
      if (prop in target) return Reflect.get(target, prop);
      if (typeof prop === "symbol") return undefined;
      return (...args) => {
        if (prop === "default") {
          state.default = args[0];
          return proxy;
        }
        if (prop === "min") state.min = args[0];
        if (prop === "max") state.max = args[0];
        if (!CHAIN_METHODS.has(prop)) {
          // Unknown builders are still chain-friendly so an unfamiliar schema
          // method cannot stop a bundle from importing.
          return proxy;
        }
        return proxy;
      };
    },
  });
  return proxy;
}

const z = {
  any: () => makeSchema("any"),
  string: () => makeSchema("string"),
  number: () => makeSchema("number"),
  natural: () => makeSchema("natural"),
  percent: () => makeSchema("percent"),
  boolean: () => makeSchema("boolean"),
  array: (inner) => makeSchema("array", inner),
  dict: (inner) => makeSchema("dict", inner),
  object: (shape) => makeSchema("object", shape),
  tuple: (shape) => makeSchema("tuple", shape),
  union: (options) => makeSchema("union", options),
  intersect: (options) => makeSchema("intersect", options),
  const: (value) => {
    const schema = makeSchema("const");
    schema.__schemaState.default = value;
    return schema;
  },
  is: () => true,
  resolve: (value) => value,
};

export const Schema = z;
export default z;
