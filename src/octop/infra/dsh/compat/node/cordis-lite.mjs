/**
 * A deliberately small Cordis-compatible context.
 *
 * It implements exactly the surface real DSH host entries were observed to
 * use: ``provide/get/inject/effect/on/emit/plugin``, service properties and a
 * disposer-based lifecycle. Unknown services return ``undefined`` like Cordis
 * does, but every access is recorded so the adapter can report what a plugin
 * asked for and did not get.
 */

export class Context {
  constructor({ name = "root", services = {} } = {}) {
    this.name = name;
    this.registry = new Map();
    this.accessed = [];
    this.unsupported = [];
    this.effects = [];
    this.listeners = new Map();
    this._deferred = [];
    this._providedByPlugin = new Set();
    this.config = {};
    this.fiber = { dispose: () => this.dispose() };
    this.logger = {
      info: (...args) => console.error("[dsh]", ...args),
      warn: (...args) => console.error("[dsh]", ...args),
      error: (...args) => console.error("[dsh]", ...args),
      debug: () => {},
      trace: () => {},
    };
    for (const [serviceName, value] of Object.entries(services)) {
      this.provide(serviceName, value);
    }
  }

  provide(name, value) {
    this.registry.set(name, value);
    this._providedByPlugin.add(name);
    this._define(name, value);
    this._flush();
    return () => {
      this.registry.delete(name);
    };
  }

  _define(name, value) {
    if (!name || name in this) return;
    try {
      Object.defineProperty(this, name, {
        configurable: true,
        enumerable: true,
        get: () => this.registry.get(name),
      });
    } catch {
      /* non-configurable names simply stay get-only */
    }
  }

  get(name) {
    this.accessed.push(name);
    return this.registry.get(name);
  }

  set(name, value) {
    return this.provide(name, value);
  }

  inject(deps, callback) {
    const list = Array.isArray(deps) ? deps : [deps];
    const ready = list.every((dep) => this.registry.has(dep));
    if (!ready) {
      this._deferred.push({ deps: list, callback });
      return () => {};
    }
    try {
      const result = callback(this);
      if (typeof result === "function") this.effects.push(result);
    } catch (error) {
      this.unsupported.push({
        member: "inject",
        deps: list,
        error: String(error && error.stack ? error.stack : error),
      });
    }
    return () => {};
  }

  _flush() {
    if (!this._deferred.length) return;
    const pending = this._deferred;
    this._deferred = [];
    for (const item of pending) {
      if (item.deps.every((dep) => this.registry.has(dep))) {
        try {
          const result = item.callback(this);
          if (typeof result === "function") this.effects.push(result);
        } catch (error) {
          this.unsupported.push({
            member: "inject",
            deps: item.deps,
            error: String(error && error.stack ? error.stack : error),
          });
        }
      } else {
        this._deferred.push(item);
      }
    }
  }

  effect(fn, label) {
    try {
      const disposer = fn();
      if (typeof disposer === "function") {
        this.effects.push(disposer);
        return disposer;
      }
    } catch (error) {
      this.unsupported.push({
        member: "effect",
        label: label || null,
        error: String(error && error.stack ? error.stack : error),
      });
    }
    return () => {};
  }

  on(event, handler) {
    if (!this.listeners.has(event)) this.listeners.set(event, new Set());
    this.listeners.get(event).add(handler);
    return () => {
      this.listeners.get(event)?.delete(handler);
    };
  }

  emit(event, ...args) {
    let handled = 0;
    for (const bucket of [event, "*"]) {
      for (const handler of this.listeners.get(bucket) || []) {
        try {
          handler(...args);
          handled += 1;
        } catch (error) {
          this.unsupported.push({
            member: "emit",
            event,
            error: String(error && error.stack ? error.stack : error),
          });
        }
      }
    }
    return handled;
  }

  plugin(mod, config) {
    const plugin = mod && mod.default && typeof mod.default === "function" && !mod.apply ? mod.default : mod;
    if (typeof plugin === "function") {
      return plugin(this, config ?? this.config);
    }
    if (!plugin || typeof plugin.apply !== "function") {
      const error = new Error("DSH bundle has no apply()");
      error.code = "ENTRY_SHAPE";
      throw error;
    }
    return plugin.apply(this, config ?? this.config);
  }

  dispose() {
    for (const disposer of this.effects.splice(0)) {
      try {
        disposer();
      } catch {
        /* teardown is best effort */
      }
    }
  }

  /** Services the plugin itself published (not the host stubs). */
  published() {
    const out = {};
    for (const [name, value] of this.registry.entries()) {
      if (hostServiceNames.has(name)) continue;
      out[name] = value;
    }
    return out;
  }
}

/** Service names the host stubs own; used to separate plugin publications. */
export const hostServiceNames = new Set([
  "cmdlineArgs",
  "appExit",
  "appReady",
  "webServer",
  "tools",
  "systemPrompt",
  "sessions",
  "subagents",
  "agents",
  "slots",
  "locale",
  "remote",
  "authorization",
  "settings",
  "configEditor",
  "directoryPicker",
  "tokenMeter",
  "policy",
  "head",
  "llm",
  "workspaceRegistry",
  "sessionQuery",
  "jobs",
  "attachments",
  "agentDefaultModel",
]);
