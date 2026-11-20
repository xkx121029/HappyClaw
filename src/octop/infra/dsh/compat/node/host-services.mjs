/**
 * Host services handed to a DSH bundle's Cordis context.
 *
 * ``createHostServices`` is shared by the disposable probe and the persistent
 * runner so both exercise the same surface. Methods the adapter cannot honour
 * are recorded in ``state.unsupported`` (and surface in ``/status``) instead of
 * crashing the mount; methods that do real work go through ``rpc`` to Python.
 */

const noop = () => {};

/**
 * Services the host half can resolve but cannot honour. The runner reports one
 * ``service:<name>:<code>`` entry per declared gap so ``/status`` explains *why*
 * a capability is missing instead of the plugin silently doing nothing.
 */
export const SERVICE_GAPS = {
  jobs: {
    code: "HOST_JOBS_UNSUPPORTED",
    reason:
      "插件定时任务需要宿主侧常驻调度器；v1 的 DSH 插件只有宿主半边与浏览器半边，调度不在此层",
  },
  "webServer.tapIndex": {
    code: "HOST_SERVER_HOOK_UNSUPPORTED",
    reason: "宿主不向插件开放服务端 index.html 注入",
  },
  attachments: {
    code: "HOST_ATTACHMENTS_UPLOAD_API_ONLY",
    reason: "附件由宿主上传接口写入 workspace/inbound，插件宿主半边不直接落盘",
  },
};

/** Structured refusal: callers see a stable code instead of ``undefined``. */
function refusal(serviceName, code, reason) {
  return { ok: false, service: serviceName, code, reason };
}

function unknownRecorder(name, unsupported) {
  return new Proxy(
    {},
    {
      get(_target, property) {
        if (typeof property === "symbol") return undefined;
        unsupported.add(`${name}.${String(property)}`);
        return () => undefined;
      },
      has() {
        return true;
      },
    },
  );
}

function service(name, methods, unsupported) {
  const proxy = new Proxy(methods, {
    get(target, property) {
      if (property in target) return target[property];
      if (typeof property === "symbol") return undefined;
      unsupported.add(`${name}.${String(property)}`);
      return () => undefined;
    },
  });
  return proxy;
}

/**
 * @param {{pluginId: string, rpc: (method: string, params?: object) => Promise<any>, mode?: string}} options
 */
export function createHostServices({ pluginId, rpc, mode = "runner" }) {
  const routes = [];
  const tools = [];
  const prompts = [];
  const unsupported = new Set();

  const webServerTapIndex = () => {
    unsupported.add("webServer.tapIndex:HOST_SERVER_HOOK_UNSUPPORTED");
    return refusal(
      "webServer",
      SERVICE_GAPS["webServer.tapIndex"].code,
      SERVICE_GAPS["webServer.tapIndex"].reason,
    );
  };

  const webServer = service(
    "webServer",
    {
      register: (route) => {
        if (!route) return noop;
        routes.push({
          kind: String(route.kind || route.method || "get").toLowerCase(),
          path: String(route.path || "/"),
          handler: route.handler || route.handle || route.fn,
        });
        return () => {
          const index = routes.indexOf(route);
          if (index >= 0) routes.splice(index, 1);
        };
      },
      routes: () => routes.map(({ kind, path }) => ({ kind, path })),
      tapIndex: webServerTapIndex,
      tap: webServerTapIndex,
      addMiddleware: webServerTapIndex,
    },
    unsupported,
  );

  const toolsService = service(
    "tools",
    {
      register: (definition) => {
        if (!definition) return noop;
        const name = String(definition.name || definition.id || "");
        tools.push({
          name,
          description: String(definition.description || ""),
          parameters:
            definition.parameters || definition.schema || definition.inputSchema || {
              type: "object",
              properties: {},
            },
          handler: definition.handler || definition.execute || definition.run || definition.call,
        });
        void rpc("tools.register", {
          name,
          description: String(definition.description || ""),
          parameters:
            definition.parameters || definition.schema || definition.inputSchema || {
              type: "object",
              properties: {},
            },
        });
        return () => {
          const index = tools.findIndex((item) => item.name === name);
          if (index >= 0) tools.splice(index, 1);
        };
      },
      get: (name) => tools.find((item) => item.name === name),
      list: () => tools.map((item) => item.name),
    },
    unsupported,
  );

  const promptDefs = (kind) => (definition) => {
    if (!definition) return noop;
    prompts.push({ ...definition, kind, text: definition.text });
    void rpc("prompt.section", {
      kind,
      name: String(definition.name || definition.id || ""),
      order: definition.order ?? 0,
    });
    return () => {
      const index = prompts.indexOf(definition);
      if (index >= 0) prompts.splice(index, 1);
    };
  };

  const systemPrompt = service(
    "systemPrompt",
    { section: promptDefs("section"), context: promptDefs("context") },
    unsupported,
  );

  const sessions = service(
    "sessions",
    {
      list: () => rpc("sessions.list").then((value) => (Array.isArray(value) ? value : [])),
      get: (id) => rpc("sessions.get", { id }),
      current: () => rpc("sessions.current"),
      open: (id) => rpc("sessions.open", { id }),
      on: () => noop,
    },
    unsupported,
  );

  const agents = service(
    "agents",
    {
      list: () => rpc("agents.list").then((value) => (Array.isArray(value) ? value : [])),
      get: (id) => rpc("agents.get", { id }),
      create: (options) => rpc("agents.create", options || {}),
    },
    unsupported,
  );

  const subagents = service(
    "subagents",
    {
      list: () => rpc("subagents.list").then((value) => (Array.isArray(value) ? value : [])),
      start: (options) => rpc("subagents.start", options || {}),
      startActivation: (options) => rpc("subagents.startActivation", options || {}),
    },
    unsupported,
  );

  const remote = service(
    "remote",
    {
      call: (method, params) => rpc("remote.call", { method, params, pluginId }),
      query: (method, params) => rpc("remote.call", { method, params, pluginId }),
      session: (id) => rpc("sessions.get", { id }),
      directoryPicker: () => rpc("directory.pick", { pluginId }),
      $on: () => noop,
    },
    unsupported,
  );

  const locale = service(
    "locale",
    {
      current: () => "zh",
      getLocale: () => "zh",
      register: () => noop,
      t: (key) => String(key),
    },
    unsupported,
  );

  const settings = service(
    "settings",
    {
      get: (key) => rpc("settings.get", { key }),
      set: (key, value) => rpc("settings.set", { key, value }),
      register: () => noop,
    },
    unsupported,
  );

  const policy = service(
    "policy",
    {
      get: () => undefined,
      allows: () => true,
      thresholds: {},
      check: async () => true,
    },
    unsupported,
  );

  const head = service(
    "head",
    {
      cwd: () => process.cwd(),
      values: () => ({}),
      parentSession: () => null,
      get: () => undefined,
    },
    unsupported,
  );

  const tokenMeter = service(
    "tokenMeter",
    { measure: (text) => Math.ceil(String(text || "").length / 4), record: noop },
    unsupported,
  );

  const directoryPicker = service(
    "directoryPicker",
    {
      pick: () => rpc("directory.pick", { pluginId }),
      capability: () => ({ available: false }),
    },
    unsupported,
  );

  const configEditor = service("configEditor", { edit: () => undefined, register: () => noop }, unsupported);
  const authorization = service(
    "authorization",
    { check: async () => true, has: () => true, request: async () => true },
    unsupported,
  );
  const slots = service("slots", { inject: () => noop, register: () => noop, list: () => [] }, unsupported);

  // Services real bundles inject but the adapter cannot honour offline. They are
  // present so a mount does not die on the property access; calling one records
  // ``llm.complete`` / ``workspaceRegistry.*`` as unsupported and returns
  // ``undefined`` instead of fabricating a result.
  const llm = service("llm", { models: () => [], complete: () => undefined, chat: () => undefined }, unsupported);
  const workspaceRegistry = service(
    "workspaceRegistry",
    { list: () => [], get: () => undefined, register: () => noop },
    unsupported,
  );
  const sessionQuery = service(
    "sessionQuery",
    { list: () => [], get: () => undefined, search: () => [] },
    unsupported,
  );

  // -- services that resolve but cannot be honoured -------------------------
  // They stay present so a mount does not die on the property access; calls
  // return a refusal carrying a stable code that ``/status`` shows verbatim.
  const jobsRefusal = () => refusal("jobs", SERVICE_GAPS.jobs.code, SERVICE_GAPS.jobs.reason);
  const jobs = service(
    "jobs",
    {
      supported: false,
      available: false,
      reasonCode: SERVICE_GAPS.jobs.code,
      reason: SERVICE_GAPS.jobs.reason,
      register: jobsRefusal,
      schedule: jobsRefusal,
      add: jobsRefusal,
      remove: jobsRefusal,
      start: jobsRefusal,
      stop: jobsRefusal,
      runNow: jobsRefusal,
      list: () => [],
      events: { subscribe: () => noop, on: () => noop },
    },
    unsupported,
  );

  /** Attachments live behind the host upload API; never fabricate a path. */
  async function attachmentCall(method, params) {
    const value = await rpc(`attachments.${method}`, { ...(params || {}), pluginId });
    if (value === undefined || value === null) {
      return refusal("attachments", SERVICE_GAPS.attachments.code, SERVICE_GAPS.attachments.reason);
    }
    return value;
  }
  const attachments = service(
    "attachments",
    {
      supported: true,
      reasonCode: SERVICE_GAPS.attachments.code,
      reason: SERVICE_GAPS.attachments.reason,
      saveImage: (input) => attachmentCall("saveImage", input || {}),
      readImage: (ref) => attachmentCall("readImage", { ref }),
      add: (input) => attachmentCall("add", { input }),
      upload: (input) => attachmentCall("upload", { input }),
      pathOf: (value) =>
        typeof value === "string" ? value : String(value?.path ?? value?.url ?? ""),
    },
    unsupported,
  );

  let defaultModelCache;
  const agentDefaultModel = service(
    "agentDefaultModel",
    {
      supported: true,
      reasonCode: "",
      get: () => defaultModelCache ?? null,
      current: () => defaultModelCache ?? null,
      currentSelection: () => defaultModelCache ?? null,
      async resolve() {
        if (defaultModelCache === undefined) {
          const value = await rpc("agents.defaultModel", { pluginId });
          defaultModelCache = typeof value === "string" ? value : (value?.id ?? null);
        }
        return defaultModelCache;
      },
      set: () =>
        refusal(
          "agentDefaultModel",
          "HOST_AGENT_DEFAULT_MODEL_READONLY",
          "默认模型由宿主设置页管理，插件只读",
        ),
      subscribe: () => noop,
    },
    unsupported,
  );

  const services = {
    cmdlineArgs: { get: () => [] },
    appExit: () => noop,
    appReady: () => ({ onReady: (fn) => { fn(); return noop; } }),
    webServer,
    tools: toolsService,
    systemPrompt,
    sessions,
    agents,
    subagents,
    remote,
    locale,
    settings,
    policy,
    head,
    tokenMeter,
    directoryPicker,
    configEditor,
    authorization,
    slots,
    llm,
    workspaceRegistry,
    sessionQuery,
    jobs,
    attachments,
    agentDefaultModel,
  };

  const state = {
    pluginId,
    mode,
    routes,
    tools,
    prompts,
    unsupported,
    unknownRecorder: () => unknownRecorder("ctx", unsupported),
  };

  return { services, state };
}

export async function renderPromptEntries(prompts, context) {
  const out = [];
  for (const definition of prompts) {
    let text = "";
    try {
      text =
        typeof definition.text === "function"
          ? await definition.text(context)
          : typeof definition.text === "string"
            ? definition.text
            : "";
    } catch (error) {
      out.push({
        name: String(definition.name || ""),
        kind: definition.kind,
        order: definition.order ?? 0,
        text: "",
        error: String(error && error.message ? error.message : error),
      });
      continue;
    }
    if (!text) continue;
    out.push({
      name: String(definition.name || ""),
      kind: definition.kind,
      order: definition.order ?? 0,
      text: String(text),
    });
  }
  return out;
}
