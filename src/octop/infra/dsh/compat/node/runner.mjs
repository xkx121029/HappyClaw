/**
 * Persistent host for one DSH bundle.
 *
 * Protocol: newline-delimited JSON on stdin/stdout.
 *   Python -> runner: {id, method, params}
 *   runner -> Python: {id, ok, result} | {id, ok:false, error}
 *   runner -> Python: {event:"ready"|"log"|"unsupported", ...}
 *
 * The bundle runs in this process only. A crash is observed by Python as a
 * process exit and marked on that plugin alone.
 */

import { createInterface } from "node:readline";
import { register as registerModuleHooks } from "node:module";
import { pathToFileURL } from "node:url";
import { Context, hostServiceNames } from "./cordis-lite.mjs";
import { createHostServices, renderPromptEntries, SERVICE_GAPS } from "./host-services.mjs";

// Host packages such as ``@deepseek-ai/dsh-tools`` only exist inside DSH.
// Install the resolver hook before any bundle import so those specifiers fall
// back to the local compatibility modules instead of failing the mount.
registerModuleHooks("./loader-hooks.mjs", import.meta.url);

const pending = new Map();
let nextId = 1;

function send(payload) {
  try {
    process.stdout.write(`${JSON.stringify(payload)}\n`);
  } catch {
    /* the parent is gone */
  }
}

function safe(value, depth = 0) {
  if (value === undefined) return null;
  if (value === null || typeof value === "number" || typeof value === "string" || typeof value === "boolean") {
    return value;
  }
  if (depth > 3) return String(value);
  if (Array.isArray(value)) return value.slice(0, 50).map((item) => safe(item, depth + 1));
  if (typeof value === "object") {
    const out = {};
    for (const key of Object.keys(value).slice(0, 50)) {
      try {
        out[key] = safe(value[key], depth + 1);
      } catch {
        out[key] = null;
      }
    }
    return out;
  }
  return String(value);
}

function rpc(method, params) {
  const id = nextId++;
  return new Promise((resolve) => {
    pending.set(id, resolve);
    send({ rpc: true, id, method, params: params ?? {} });
    setTimeout(() => {
      if (pending.delete(id)) resolve(undefined);
    }, 15000).unref?.();
  });
}

const services = createHostServices({ pluginId: process.argv[2] || "dsh:unknown", rpc });
const { state } = services;
const ctx = new Context({ services: services.services });

let moduleRef = null;
let mountError = null;
let mounted = false;

async function mount(params) {
  if (mounted) return { already: true };
  mounted = true;
  const entry = params.entry;
  try {
    moduleRef = await import(pathToFileURL(entry).href);
  } catch (error) {
    return {
      ok: false,
      code: "IMPORT_FAILED",
      error: String(error && error.stack ? error.stack : error).slice(-2400),
    };
  }
  const declared = Array.isArray(moduleRef.inject) ? moduleRef.inject : [];
  // ``services`` is a Proxy that fabricates a stub for any unknown name, so
  // membership is meaningless. Only services the host really implements count.
  const missing = declared.filter((name) => !hostServiceNames.has(String(name).split(".")[0]));
  // Services that exist only to refuse get a reason code up front, so a plugin
  // that mounts fine but cannot schedule/upload is reported honestly.
  for (const name of declared) {
    const base = String(name).split(".")[0];
    const gap = SERVICE_GAPS[base];
    if (gap) state.unsupported.add(`service:${base}:${gap.code}`);
  }
  if (typeof moduleRef.apply !== "function" && typeof moduleRef.default !== "function") {
    return { ok: false, code: "ENTRY_SHAPE", exports: Object.keys(moduleRef).slice(0, 40) };
  }
  try {
    ctx.plugin(moduleRef, moduleRef.Config ? {} : undefined);
  } catch (error) {
    mountError = String(error && error.stack ? error.stack : error).slice(-2400);
    const code = /is not a function/.test(mountError) ? "SIGNATURE_MISMATCH" : "RUNTIME_THROW";
    return { ok: false, code, error: mountError, missing, unsupported: [...state.unsupported] };
  }
  await new Promise((resolve) => setTimeout(resolve, Number(params.settleMs) || 250));
  return {
    ok: true,
    code: missing.length ? "MISSING_API" : "OK",
    name: moduleRef.name || null,
    missing,
    published: describePublished(),
    routes: state.routes.map(({ kind, path }) => ({ kind, path })),
    tools: state.tools.map(({ name, description }) => ({ name, description })).filter((item) => item.name),
    prompts: state.prompts.map(({ name, kind, order }) => ({ name, kind, order })),
    unsupported: [...state.unsupported],
  };
}

function describePublished() {
  const out = {};
  for (const [key, value] of ctx.registry.entries()) {
    // ``services`` here is the ``{services, state}`` wrapper, so membership
    // must be checked against the real host service names.
    if (hostServiceNames.has(key)) continue;
    if (value === null || typeof value !== "object") {
      out[key] = safe(value);
    } else {
      try {
        out[key] = { type: "object", keys: Object.keys(value).slice(0, 25) };
      } catch {
        out[key] = { type: "object" };
      }
    }
  }
  return out;
}

function matchRoute(method, path) {
  const wanted = String(path || "/").split("?")[0];
  for (const route of state.routes) {
    const routePath = route.path.split("?")[0];
    if (route.kind !== "all" && route.kind !== method.toLowerCase()) continue;
    if (routePath === wanted) return route;
    const pattern = new RegExp(
      `^${routePath.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/:[A-Za-z_$][A-Za-z0-9_$]*/g, "[^/]+")}$`,
    );
    if (pattern.test(wanted)) return route;
  }
  return null;
}

async function handleHttp(params) {
  const route = matchRoute(params.method || "get", params.path);
  if (!route || typeof route.handler !== "function") {
    return { status: 404, body: JSON.stringify({ error: "DSH_ROUTE_NOT_FOUND" }) };
  }
  const bodyText = params.body ?? "";
  const req = {
    method: String(params.method || "GET").toUpperCase(),
    url: params.path,
    path: params.path,
    headers: params.headers || {},
    body: bodyText,
    json: () => {
      try {
        return JSON.parse(bodyText || "{}");
      } catch {
        return {};
      }
    },
    text: async () => bodyText,
    query: Object.fromEntries(new URLSearchParams(String(params.path).split("?")[1] || "")),
  };
  const chunks = [];
  let status = 200;
  const headers = {};
  const res = {
    get statusCode() {
      return status;
    },
    set statusCode(value) {
      status = Number(value) || 200;
    },
    setHeader: (key, value) => {
      headers[key] = String(value);
    },
    getHeader: (key) => headers[key],
    writeHead: (code, extra) => {
      status = Number(code) || status;
      Object.assign(headers, extra || {});
    },
    write: (chunk) => {
      if (chunk !== undefined) chunks.push(String(chunk));
      return true;
    },
    end: (chunk) => {
      if (chunk !== undefined) chunks.push(String(chunk));
    },
    json: (value) => {
      headers["content-type"] = "application/json";
      chunks.push(JSON.stringify(value));
    },
  };
  try {
    const returned = await route.handler(req, res);
    if (returned !== undefined && chunks.length === 0) {
      if (typeof returned === "string") chunks.push(returned);
      else chunks.push(JSON.stringify(returned));
    }
  } catch (error) {
    return {
      status: 500,
      headers,
      body: JSON.stringify({ error: "DSH_ROUTE_THROW", message: String(error && error.message ? error.message : error) }),
    };
  }
  return { status, headers, body: chunks.join("") };
}

async function handleToolCall(params) {
  const tool = state.tools.find((item) => item.name === params.name);
  if (!tool) {
    return { ok: false, code: "DSH_TOOL_NOT_FOUND", name: params.name };
  }
  const handler = tool.handler;
  if (typeof handler !== "function") {
    return { ok: false, code: "DSH_TOOL_NOT_CALLABLE", name: params.name };
  }
  try {
    const value = await handler(params.args || {}, { pluginId: state.pluginId, cwd: process.cwd() });
    return { ok: true, result: safe(value) };
  } catch (error) {
    return { ok: false, code: "DSH_TOOL_THROW", message: String(error && error.stack ? error.stack : error).slice(-2000) };
  }
}

async function dispatch(message) {
  const { id, method, params } = message;
  let result;
  try {
    if (method === "mount") result = await mount(params || {});
    else if (method === "http.request") result = await handleHttp(params || {});
    else if (method === "tools.call") result = await handleToolCall(params || {});
    else if (method === "prompt.list") {
      const context = (params && params.context) || {};
      result = {
        entries: await renderPromptEntries(state.prompts, {
          agent: context.agent || { id: "octop", cwd: process.cwd() },
          session: context.session || {},
          cwd: context.cwd || process.cwd(),
          locale: context.locale || "zh",
        }),
        unsupported: [...state.unsupported],
      };
    } else if (method === "event.emit") {
      result = { handled: ctx.emit(String((params && params.name) || ""), ...((params && params.args) || [])) };
    } else if (method === "state") {
      result = {
        mounted: true,
        published: describePublished(),
        tools: state.tools.map(({ name }) => name),
        prompts: state.prompts.map(({ name, kind }) => ({ name, kind })),
        routes: state.routes.map(({ kind, path }) => ({ kind, path })),
        unsupported: [...state.unsupported],
        mountError,
      };
    } else if (method === "ping") result = { ok: true };
    else if (method === "shutdown") {
      send({ id, ok: true, result: { stopping: true } });
      setTimeout(() => process.exit(0), 20);
      return;
    } else {
      result = { ok: false, code: "DSH_RPC_UNKNOWN", method };
    }
  } catch (error) {
    result = { ok: false, code: "DSH_RUNNER_THROW", message: String(error && error.stack ? error.stack : error) };
  }
  send({ id, ok: true, result });
}

createInterface({ input: process.stdin }).on("line", (line) => {
  if (!line.trim()) return;
  let message;
  try {
    message = JSON.parse(line);
  } catch {
    return;
  }
  if (!message || typeof message !== "object") return;
  // Messages without a method are answers to a runner-initiated rpc
  // (tools.register, prompt.section, ...). Dispatching them as new requests
  // used to answer DSH_RPC_UNKNOWN with the same id the host was waiting on,
  // which made a successful mount look like a failure.
  if (typeof message.method !== "string") {
    const id = Number(message.id);
    const resolve = pending.get(id);
    if (resolve) {
      pending.delete(id);
      resolve(message && "result" in message ? message.result : undefined);
    }
    return;
  }
  if (message.id !== undefined) void dispatch(message);
});

process.on("uncaughtException", (error) => {
  send({ event: "fatal", code: "RUNTIME_THROW", error: String(error && error.stack ? error.stack : error) });
  setTimeout(() => process.exit(1), 10);
});
process.on("unhandledRejection", (error) => {
  send({ event: "fatal", code: "RUNTIME_THROW", error: String(error && error.stack ? error.stack : error) });
});

send({ event: "boot", pid: process.pid });
