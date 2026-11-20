/* eslint-disable @typescript-eslint/no-explicit-any */
/**
 * DSH browser-half loader shim.
 *
 * Market client bundles are not ESM: they call
 * ``window.__ModuleLoader__.load({id, factory})`` and receive a ``require``
 * that resolves ``react`` and the DSH client services. This module installs
 * that loader, mounts the exported plugin on a Cordis-like client context, and
 * translates ``ctx.slots`` registrations onto the two HappyClaw surface slots.
 *
 * Nothing here fabricates product state: sessions come from
 * ``host.data.read("sessions.running")`` and its subscription.
 */

import * as React from "react";
import * as ReactDOM from "react-dom";
import { createPortal } from "react-dom";

import type { OctopPluginUIHost } from "../toolRenderers/types";
import type { SurfaceContext, SurfaceSlot } from "../surfaces/types";
import { dshPrimitives } from "./primitivesShim";
import { SurfaceBoundary } from "../surfaces/SurfaceBoundary";
import { uploadFile } from "../../api/modules/upload";

declare global {
  interface Window {
    __ModuleLoader__?: {
      load: (registration: { id?: string; factory: (require: (spec: string) => any) => any }) => void;
    };
    __OCTOP_REACT__?: typeof React;
    __OCTOP_REACT_DOM__?: typeof ReactDOM;
    __OCTOP_DSH_REGISTRATIONS__?: Array<{
      id?: string;
      factory: (require: (spec: string) => any) => any;
    }>;
  }
}

export interface DshSlotEntry {
  id: string;
  dshSlot: string;
  order: number;
  title: string;
  render: any;
  /** ``meta.inject`` — props the plugin wants merged into its component. */
  inject?: () => Record<string, unknown>;
  /** Raw ``slots.register`` meta (``key``, ``locale``, ``label``…). */
  meta?: Record<string, any>;
}

export interface DshMountResult {
  pluginId: string;
  entries: DshSlotEntry[];
  unsupportedSlots: string[];
  unsupportedMembers: string[];
  exportKeys: string[];
  /** Shell-level props every DSH slot render receives (hooks, wide flag). */
  shellProps: Record<string, unknown>;
  /** Translator factory backed by ``ctx.locale.register`` tables. */
  translate?: (namespace?: string) => (key: string, vars?: Record<string, unknown>) => string;
  dispose: () => void;
}

interface SlotTarget {
  slot: SurfaceSlot;
  overlay: boolean;
}

/** DSH slot id -> HappyClaw surface slot (and whether it renders as a portal). */
export function mapDshSlot(dshSlot: string): SlotTarget | null {
  const slot = (dshSlot || "").trim();
  if (!slot) return null;
  // Composer slots must be matched before the generic ``conversation.*``
  // prefixes below, otherwise a left-slot widget would land at the top of the
  // message list.
  if (slot.startsWith("conversation.input.overlay") || slot.startsWith("conversation.input.float")) {
    return { slot: "conversation.input.overlay", overlay: false };
  }
  if (slot === "conversation.input" || slot.startsWith("conversation.input.left")) {
    return { slot: "conversation.input.left", overlay: false };
  }
  if (slot === "conversation.view" || slot.startsWith("conversation.view.")) {
    return { slot: "conversation.view", overlay: false };
  }
  if (
    slot === "settings.section" ||
    slot.startsWith("settings.section.") ||
    slot === "plugins.bundle.config" ||
    slot.startsWith("plugins.bundle.config.")
  ) {
    return { slot: "settings.section", overlay: false };
  }
  if (slot === "shell.overlay" || slot.startsWith("overlay.") || slot.startsWith("modal.") || slot.startsWith("toast.")) {
    return { slot: "chat.messages.top", overlay: true };
  }
  if (slot.startsWith("sidebar.") || slot.startsWith("home.")) {
    return { slot: "home.sidebar", overlay: false };
  }
  if (slot.startsWith("conversation.header") || slot.startsWith("chat.")) {
    return { slot: "chat.messages.top", overlay: false };
  }
  return null;
}

function installModuleLoader(): void {
  if (typeof window === "undefined") return;
  if (!window.__OCTOP_DSH_REGISTRATIONS__) {
    window.__OCTOP_DSH_REGISTRATIONS__ = [];
    window.__ModuleLoader__ = {
      load(registration) {
        if (registration && typeof registration.factory === "function") {
          window.__OCTOP_DSH_REGISTRATIONS__!.push(registration);
        }
      },
    };
    window.__OCTOP_REACT__ = React;
    window.__OCTOP_REACT_DOM__ = ReactDOM;
  }
}

/** ``react/jsx-runtime`` is a separate module; React itself has no ``jsx``. */
function jsxFactory(type: any, props: any, key?: any) {
  const config = key === undefined ? props : { ...(props || {}), key };
  return React.createElement(type, config);
}

const jsxRuntime = {
  Fragment: React.Fragment,
  jsx: jsxFactory,
  jsxs: jsxFactory,
  jsxDEV: jsxFactory,
};

function requireFrom(unsupported: Set<string>) {
  return (spec: string): any => {
    const normalized = String(spec || "");
    if (normalized === "react") return window.__OCTOP_REACT__ ?? React;
    if (normalized === "react-dom") return window.__OCTOP_REACT_DOM__ ?? ReactDOM;
    if (normalized === "react-dom/client") return (window.__OCTOP_REACT_DOM__ ?? ReactDOM) as any;
    if (normalized === "react/jsx-runtime") return jsxRuntime;
    if (normalized === "react/jsx-dev-runtime") return jsxRuntime;
    if (normalized === "@deepseek-ai/dsh-client-ui-primitives") return dshPrimitives;
    unsupported.add(`require:${normalized}`);
    // Do not throw here: a plugin that asks for an optional module usually
    // degrades, and the status report tells the user it was missing.
    return undefined;
  };
}

interface SnapshotStore<T> {
  getSnapshot: () => T;
  subscribe: (listener: () => void) => () => void;
}

function createStore<T>(
  host: OctopPluginUIHost,
  initial: T,
  map: (sessions: any[]) => T,
): SnapshotStore<T> & { refresh: () => Promise<void>; dispose: () => void } {
  let value = initial;
  const listeners = new Set<() => void>();
  const notify = () => {
    for (const listener of listeners) {
      try {
        listener();
      } catch {
        /* a broken subscriber is not our failure */
      }
    }
  };
  const apply = (payload: any) => {
    const sessions = Array.isArray(payload?.sessions) ? payload.sessions : Array.isArray(payload) ? payload : [];
    value = map(sessions);
    notify();
  };
  void host.data.read<any>("sessions.running").then(apply).catch(() => undefined);
  const off = host.data.subscribe<any>("sessions.running", apply);
  const refresh = async () => {
    try {
      apply(await host.data.read<any>("sessions.running"));
    } catch {
      /* keep the last good snapshot */
    }
  };
  return {
    getSnapshot: () => value,
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    refresh,
    dispose: () => {
      off();
      listeners.clear();
    },
  };
}

interface MountOptions {
  pluginId: string;
  host: OctopPluginUIHost;
  source: string;
  sourceUrl: string;
  /** Test seam: import this URL instead of building a Blob/data URL. */
  moduleUrl?: string;
}

async function importSourceModule(
  source: string,
  pluginId: string,
  moduleUrl?: string,
): Promise<void> {
  if (moduleUrl) {
    await import(/* @vite-ignore */ moduleUrl);
    return;
  }
  // Tests and SSR: a data:-URL import runs outside the jsdom realm, so the
  // bundle would not see ``window``/``document``. DSH bundles are plain
  // scripts (they only call ``window.__ModuleLoader__``), so evaluating them
  // in the current realm is equivalent.
  const inNode =
    typeof process !== "undefined" && Boolean((process as any).versions?.node);
  if (inNode) {
    // eslint-disable-next-line no-new-func
    new Function(`${source}\n//# sourceURL=octop-dsh:${pluginId}.js`)();
    return;
  }
  if (typeof Blob !== "undefined" && typeof URL?.createObjectURL === "function") {
    const blob = new Blob([source], { type: "text/javascript" });
    const blobUrl = URL.createObjectURL(blob);
    try {
      await import(/* @vite-ignore */ `${blobUrl}?plugin=${encodeURIComponent(pluginId)}`);
      return;
    } finally {
      URL.revokeObjectURL(blobUrl);
    }
  }
  await import(
    /* @vite-ignore */ `data:text/javascript;charset=utf-8,${encodeURIComponent(source)}`
  );
}

export async function mountDshClient({ pluginId, host, source, sourceUrl, moduleUrl }: MountOptions): Promise<DshMountResult> {
  installModuleLoader();
  const registrations = window.__OCTOP_DSH_REGISTRATIONS__!;
  const before = registrations.length;

  await importSourceModule(source, pluginId, moduleUrl);
  const captured = registrations.slice(before).filter((item) => item && typeof item.factory === "function");
  if (captured.length === 0) {
    throw new Error(`DSH_MODULE_LOADER_MISSING: ${sourceUrl}`);
  }

  const entries: DshSlotEntry[] = [];
  const unsupportedSlots = new Set<string>();
  const unsupportedMembers = new Set<string>();
  const disposers: Array<() => void> = [];

  const sessionList = createStore<{ byId: Record<string, any>; phase: string }>(host, { byId: {}, phase: "ready" }, (sessions) => {
    const byId: Record<string, any> = {};
    for (const row of sessions) {
      const id = String(row?.thread_id ?? row?.id ?? "");
      if (!id) continue;
      byId[id] = {
        id,
        title: row?.title ?? "",
        running: Boolean(row?.turn_active),
        agentId: row?.agent_id ?? null,
        agentName: row?.agent_name ?? "",
      };
    }
    return { byId, phase: "ready" };
  });

  const statusStore = createStore<Map<string, any>>(host, new Map(), (sessions) => {
    const map = new Map<string, any>();
    for (const row of sessions) {
      const id = String(row?.thread_id ?? row?.id ?? "");
      if (!id) continue;
      map.set(id, {
        running: Boolean(row?.turn_active),
        completionUnread: false,
        subagent: false,
        awaitingUser: Boolean(row?.awaiting_user),
      });
    }
    return map;
  });

  // Slot renders receive shell-level props in DSH: a ``wide`` flag plus store
  // hooks. Bundles call them directly (e.g. ``useSessions((s) => s.byId)``).
  const workspaceState = { archivedSessionIds: [] as string[] };
  const useSessions = (selector: (state: any) => unknown) =>
    selector(
      React.useSyncExternalStore(
        sessionList.subscribe,
        sessionList.getSnapshot,
        sessionList.getSnapshot,
      ),
    );
  const useSessionStatus = (selector: (state: any) => unknown) =>
    selector(
      React.useSyncExternalStore(
        statusStore.subscribe,
        statusStore.getSnapshot,
        statusStore.getSnapshot,
      ),
    );
  const useWorkspaces = (selector: (state: any) => unknown) => selector(workspaceState);
  const shellProps = { wide: false, useSessions, useSessionStatus, useWorkspaces };

  const slots = {
    inject(name: string, callback: () => void) {
      const target = mapDshSlot(name);
      if (!target) {
        unsupportedSlots.add(name);
        return () => {};
      }
      try {
        callback();
      } catch (error) {
        unsupportedMembers.add(`slots.inject:${name}:${String(error)}`);
      }
      return () => {};
    },
    register(meta: any, renderer: any) {
      const actualMeta = typeof meta === "string" ? { name: meta } : meta || {};
      const actualRender = typeof meta === "function" ? meta : renderer;
      const dshSlot = String(actualMeta.name || actualMeta.slot || "");
      const target = mapDshSlot(dshSlot);
      if (!target) {
        unsupportedSlots.add(dshSlot || "unknown");
        return () => {};
      }
      if (typeof actualRender !== "function") {
        unsupportedMembers.add(`slots.register:${dshSlot}:not-a-component`);
        return () => {};
      }
      const entry: DshSlotEntry = {
        id: String(actualMeta.id || `${dshSlot}:${entries.length}`),
        dshSlot,
        order: Number.isFinite(actualMeta.order) ? Number(actualMeta.order) : 100,
        title: String(actualMeta.label || actualMeta.title || dshSlot),
        render: actualRender,
        inject: typeof actualMeta.inject === "function" ? actualMeta.inject : undefined,
        meta: actualMeta,
      };
      entries.push(entry);
      return () => {
        const index = entries.indexOf(entry);
        if (index >= 0) entries.splice(index, 1);
      };
    },
    list: () => entries.map((entry) => entry.dshSlot),
  };

  const themeVars = new Map<string, string>();
  const uiTheme = {
    registerTheme(theme: any) {
      const id = String(theme?.id || theme?.name || "theme");
      const vars = theme?.vars || theme?.variables || {};
      const declarations = Object.entries(vars)
        .map(([key, value]) => `${key.startsWith("--") ? key : `--${key}`}: ${String(value)};`)
        .join("\n");
      const css = String(theme?.css || "") + (declarations ? `body[data-dsh-theme="${id}"] {\n${declarations}\n}` : "");
      if (css) {
        const style = document.createElement("style");
        style.dataset.dshTheme = id;
        style.textContent = css;
        document.head.appendChild(style);
        disposers.push(() => style.remove());
      }
      themeVars.set(id, css);
      // The host has no settings slot, so applying the first registered theme
      // is the honest way to make an appearance plugin visible.
      if (!document.body.dataset.dshTheme) apply(id);
      return () => {};
    },
    apply,
    setTheme: apply,
    getTheme: () => document.body.dataset.dshTheme || null,
    current: () => document.body.dataset.dshTheme || null,
    themes: () => [...themeVars.keys()],
  };

  function apply(id: string) {
    if (!id) return;
    document.body.dataset.dshTheme = id;
    if (typeof localStorage !== "undefined") {
      try {
        localStorage.setItem("octop.dsh.theme", id);
      } catch {
        /* private mode */
      }
    }
  }

  const localeListeners = new Set<() => void>();
  const localeTables = new Map<string, unknown>();
  const locale = {
    current: () => host.context.locale || "zh",
    getLocale: () => host.context.locale || "zh",
    register(namespace: string, table: unknown) {
      localeTables.set(String(namespace || "default"), table);
      for (const listener of localeListeners) {
        try {
          listener();
        } catch {
          /* ignore one broken subscriber */
        }
      }
      return () => {
        localeTables.delete(String(namespace || "default"));
      };
    },
    /** ``bind`` returns a translator: the only shape client bundles call. */
    bind: (namespace?: string) => (key: string, vars?: Record<string, unknown>) => {
      const ns = String(namespace || "default");
      const table = localeTables.get(ns) as any;
      const lang = host.context.locale || "zh";
      const dict = (table && (table[lang] || table.zh || table)) || {};
      let text = typeof dict[key] === "string" ? String(dict[key]) : String(key);
      if (vars) {
        text = text.replace(/\{(\w+)\}/g, (match, name: string) =>
          name in vars ? String(vars[name]) : match,
        );
      }
      return text;
    },
    subscribe: (listener: () => void) => {
      localeListeners.add(listener);
      return () => localeListeners.delete(listener);
    },
    t: (key: string) => String(key),
  };

  // -- host theme --------------------------------------------------------
  // DSH's ``theme`` service is a light/dark preference switch plus font
  // metrics; it is not the theme *registry* (``uiTheme``). Bundles call
  // ``setTheme("dark")`` and read ``getTheme().fontSizes``.
  const THEME_MODE_KEY = "octop.dsh.themeMode";
  const DSH_FONT_DEFAULTS: Record<string, number> = { text: 14, code: 11, terminal: 13 };
  const fontSizes: Record<string, number> = { ...DSH_FONT_DEFAULTS };
  const fontFamilies: Record<string, string> = { text: "", code: "", terminal: "" };
  const themeListeners = new Set<() => void>();
  /** CSS variables this plugin wrote; removed on uninstall. */
  const touchedVars = new Set<string>();
  const notifyTheme = () => {
    for (const listener of themeListeners) {
      try {
        listener();
      } catch {
        /* ignore one broken subscriber */
      }
    }
  };
  const readMode = (): "light" | "dark" | "system" => {
    if (typeof localStorage === "undefined") return "system";
    try {
      const stored = localStorage.getItem(THEME_MODE_KEY);
      if (stored === "light" || stored === "dark" || stored === "system") return stored;
    } catch {
      /* private mode */
    }
    return "system";
  };
  const prefersDark = () =>
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-color-scheme: dark)").matches;
  const applyHostMode = (mode: string) => {
    if (typeof document === "undefined") return;
    const resolved = mode === "system" ? (prefersDark() ? "dark" : "light") : mode === "dark" ? "dark" : "light";
    const root = document.documentElement;
    root.setAttribute("data-theme", resolved);
    root.classList.toggle("dark", resolved === "dark");
  };
  let themeMode = readMode() as "light" | "dark" | "system";
  const setCssVar = (name: string, value: string) => {
    if (typeof document === "undefined") return;
    touchedVars.add(name);
    if (value) document.documentElement.style.setProperty(name, value);
    else document.documentElement.style.removeProperty(name);
  };
  const themeService = {
    getTheme: () => ({
      preference: themeMode,
      mode: themeMode === "system" ? (prefersDark() ? "dark" : "light") : themeMode,
      fontSizes: { ...fontSizes },
      fontFamilies: { ...fontFamilies },
    }),
    setTheme(next: string) {
      themeMode = next === "light" || next === "dark" || next === "system" ? next : "system";
      applyHostMode(themeMode);
      try {
        localStorage.setItem(THEME_MODE_KEY, themeMode);
      } catch {
        /* private mode */
      }
      notifyTheme();
    },
    setFontSize(role: string, px: number) {
      const key = String(role || "text");
      const value = Number(px);
      if (!Number.isFinite(value)) return;
      fontSizes[key] = value;
      setCssVar(`--dsh-font-size-${key}`, `${value}px`);
      notifyTheme();
    },
    setFontFamily(role: string, family: string) {
      const key = String(role || "text");
      fontFamilies[key] = String(family || "");
      setCssVar(`--dsh-font-family-${key}`, String(family || ""));
      notifyTheme();
    },
    subscribe(listener: () => void) {
      themeListeners.add(listener);
      return () => themeListeners.delete(listener);
    },
  };
  applyHostMode(themeMode);
  // Do not seed ``--dsh-font-size-*`` here: the host UI consumes those
  // variables first, so seeding defaults would override the user's own reading
  // preferences for every DSH plugin. Only a plugin that actually calls
  // setFontSize/setFontFamily writes them.
  disposers.push(() => {
    for (const name of touchedVars) setCssVar(name, "");
    touchedVars.clear();
  });

  const remote = {
    $on(event: string, callback: (payload: any) => void) {
      const mapped = String(event).includes("session") ? "session.updated" : "session.updated";
      return host.events.on<any>(mapped as any, (payload) => {
        try {
          callback(payload);
        } catch {
          /* plugin callback failure stays inside the plugin */
        }
      });
    },
    session: () => undefined,
    directoryPicker: () => undefined,
    call: () => undefined,
    query: () => undefined,
  };

  const logger = {
    info: (...args: any[]) => console.info("[dsh]", pluginId, ...args),
    warn: (...args: any[]) => console.warn("[dsh]", pluginId, ...args),
    error: (...args: any[]) => console.error("[dsh]", pluginId, ...args),
    debug: () => {},
  };

  // -- missing host services (docs/dsh-compat-inventory.md §5) --------------
  // A service that cannot be honoured still resolves, so the plugin keeps
  // loading; every call returns a structured refusal with a stable code and
  // the code is reported back to the host as ``service:<name>:<code>``.
  const unsupportedFailure = (service: string, code: string, reason: string) => ({
    ok: false as const,
    service,
    code,
    reason,
  });

  const jobsReasonCode = "HOST_JOBS_UNSUPPORTED";
  const jobsReason =
    "插件定时任务需要宿主侧常驻调度器；v1 插件只存在于浏览器运行时，关闭面板即停止，因此不提供 jobs";
  const jobsRefusal = () => unsupportedFailure("jobs", jobsReasonCode, jobsReason);
  const jobs = {
    supported: false,
    available: false,
    reasonCode: jobsReasonCode,
    reason: jobsReason,
    register: jobsRefusal,
    schedule: jobsRefusal,
    add: jobsRefusal,
    remove: jobsRefusal,
    start: jobsRefusal,
    stop: jobsRefusal,
    runNow: jobsRefusal,
    list: () => [] as unknown[],
  };

  const webServerReasonCode = "HOST_SERVER_HOOK_UNSUPPORTED";
  const webServerReason =
    "v1 插件是客户端 ESM，宿主不向插件开放服务端 index.html 注入";
  const webServerRefusal = () =>
    unsupportedFailure("webServer", webServerReasonCode, webServerReason);
  const webServer = {
    supported: false,
    available: false,
    reasonCode: webServerReasonCode,
    reason: webServerReason,
    tapIndex: webServerRefusal,
    tap: webServerRefusal,
    addMiddleware: webServerRefusal,
    registerRoute: webServerRefusal,
  };

  async function uploadAttachment(file: File) {
    const agentId = host.getToolContext().agentId;
    if (!agentId) {
      return unsupportedFailure(
        "attachments",
        "HOST_AGENT_CONTEXT_MISSING",
        "附件上传需要当前会话的 Agent 上下文",
      );
    }
    try {
      const uploaded = await uploadFile(agentId, file);
      return { ok: true as const, ...uploaded };
    } catch (error) {
      return unsupportedFailure(
        "attachments",
        "HOST_ATTACHMENT_UPLOAD_FAILED",
        String(error),
      );
    }
  }
  const attachments = {
    supported: true,
    reasonCode: "",
    upload: uploadAttachment,
    add: uploadAttachment,
    /** Attachments are paths or URLs; keep the value the host gave us. */
    pathOf(value: unknown): string {
      if (typeof value === "string") return value;
      const record = value as { path?: unknown; url?: unknown } | null;
      return String(record?.path ?? record?.url ?? "");
    },
  };

  let cachedDefaultModel: string | null = null;
  let defaultModelLoaded = false;
  const defaultModelListeners = new Set<() => void>();
  const refreshDefaultModel = async () => {
    try {
      const payload = await host.request<any>("/agents");
      const list: any[] = Array.isArray(payload)
        ? payload
        : Array.isArray(payload?.agents)
          ? payload.agents
          : [];
      const agentId = host.getToolContext().agentId;
      const picked =
        list.find((row) => String(row?.id ?? row?.agent_id ?? "") === String(agentId ?? "")) ??
        list.find((row) => Boolean(row?.is_default)) ??
        list[0];
      const next =
        typeof picked?.default_model === "string" && picked.default_model
          ? picked.default_model
          : null;
      defaultModelLoaded = true;
      if (next !== cachedDefaultModel) {
        cachedDefaultModel = next;
        for (const listener of defaultModelListeners) {
          try {
            listener();
          } catch {
            /* ignore one broken subscriber */
          }
        }
      }
    } catch {
      /* keep the previous value; the host may be offline */
    }
  };
  const agentDefaultModel = {
    supported: true,
    reasonCode: "",
    get: () => cachedDefaultModel,
    current: () => cachedDefaultModel,
    async resolve() {
      if (!defaultModelLoaded) await refreshDefaultModel();
      return cachedDefaultModel;
    },
    refresh: refreshDefaultModel,
    set: () =>
      unsupportedFailure(
        "agentDefaultModel",
        "HOST_AGENT_DEFAULT_MODEL_READONLY",
        "默认模型由宿主设置页管理，插件只读",
      ),
    subscribe(listener: () => void) {
      defaultModelListeners.add(listener);
      if (!defaultModelLoaded) void refreshDefaultModel();
      return () => defaultModelListeners.delete(listener);
    },
  };

  /** Services that resolve but cannot honour the request. */
  const serviceGaps: Record<string, { code: string; reason: string }> = {
    jobs: { code: jobsReasonCode, reason: jobsReason },
    webServer: { code: webServerReasonCode, reason: webServerReason },
  };
  const accessedServices = new Set<string>();

  const effects: Array<() => void> = [];  const listeners = new Map<string, Set<(...args: any[]) => void>>();
  const services: Record<string, any> = {
    slots,
    sessions: {
      list: sessionList,
      open: () => undefined,
      get: () => undefined,
      binding: () => undefined,
      current: () => undefined,
    },
    uiSession: {
      sessionStatus: statusStore,
      sessions: { list: sessionList },
      retainedBy: { mainView: null },
      openSession: () => undefined,
    },
    uiWorkspace: { openSession: () => undefined },
    uiConversation: { openSession: () => undefined },
    layout: {
      width: () => (typeof window === "undefined" ? 0 : window.innerWidth),
      height: () => (typeof window === "undefined" ? 0 : window.innerHeight),
      edges: {},
      nodes: {},
      selectPanel: () => undefined,
    },
    locale,
    remote,
    logger,
    uiTheme,
    theme: themeService,
    config: {},
    configForms: (() => {
      const scopes = new Map<string, any>();
      const storageKey = (namespace: string) => `octop.dsh.config.${namespace}`;
      const readStored = (namespace: string): Record<string, unknown> => {
        try {
          const raw = window.localStorage.getItem(storageKey(namespace));
          const parsed = raw ? JSON.parse(raw) : null;
          return parsed && typeof parsed === "object" ? parsed : {};
        } catch {
          return {};
        }
      };
      const writeStored = (namespace: string, values: Record<string, unknown>) => {
        try {
          window.localStorage.setItem(storageKey(namespace), JSON.stringify(values));
        } catch {
          /* quota / private mode: keep the in-memory value */
        }
      };
      const applyPath = (
        target: Record<string, any>,
        path: string[],
        value: unknown,
      ): Record<string, any> => {
        if (!path.length) return target;
        const next = { ...target };
        let cursor: Record<string, any> = next;
        for (const part of path.slice(0, -1)) {
          const child = cursor[part];
          cursor[part] = child && typeof child === "object" ? { ...child } : {};
          cursor = cursor[part];
        }
        const leaf = path[path.length - 1];
        if (value === undefined) delete cursor[leaf];
        else cursor[leaf] = value;
        return next;
      };
      const scopeFor = (namespace: string) => {
        const key = String(namespace || "default");
        if (!scopes.has(key)) {
          let values: Record<string, unknown> = readStored(key);
          const listeners = new Set<() => void>();
          const emit = () => {
            for (const listener of listeners) {
              try {
                listener();
              } catch {
                /* ignore */
              }
            }
          };
          scopes.set(key, {
            // DSH's shape: ``value`` + ``writable`` + ``status``. ``values`` is
            // kept because a few bundles read the older alias.
            getSnapshot: () => ({ value: values, values, writable: true, status: "ready" }),
            values: () => values,
            get: (field: string) => values[field],
            set: (field: string, value: unknown) => {
              values = { ...values, [field]: value };
              writeStored(key, values);
              emit();
            },
            update: (next: Record<string, unknown>) => {
              values = { ...values, ...next };
              writeStored(key, values);
              emit();
            },
            replace: (next: Record<string, unknown>) => {
              values = { ...next };
              writeStored(key, values);
              emit();
            },
            /** ``mutate([{op:"set", path:["a","b"], value}])`` → accepted? */
            mutate: async (ops: Array<Record<string, any>>) => {
              let next = values;
              for (const op of Array.isArray(ops) ? ops : []) {
                const path = Array.isArray(op.path)
                  ? op.path.map(String)
                  : String(op.path ?? "").split(".").filter(Boolean);
                if (op.op === "set" || op.op === undefined) {
                  next = applyPath(next, path, op.value);
                } else if (op.op === "unset" || op.op === "delete") {
                  next = applyPath(next, path, undefined);
                } else if (op.op === "merge" && op.value && typeof op.value === "object") {
                  const existing = path.reduce<any>(
                    (acc, part) => (acc && typeof acc === "object" ? acc[part] : undefined),
                    next,
                  );
                  next = applyPath(next, path, {
                    ...(existing && typeof existing === "object" ? existing : {}),
                    ...op.value,
                  });
                } else {
                  return false;
                }
              }
              values = next;
              writeStored(key, values);
              emit();
              return true;
            },
            subscribe: (listener: () => void) => {
              listeners.add(listener);
              return () => listeners.delete(listener);
            },
          });
        }
        return scopes.get(key);
      };
      return {
        register: () => () => {},
        get: (namespace: string) => scopeFor(namespace),
        list: () => [...scopes.keys()],
        subscribe: () => () => {},
        // ``whileServed`` gates a card on the bundle page being open; there is
        // no bundle page in the host, so the card registers and its slot is
        // reported as unsupported instead of silently vanishing.
        whileServed: (_names: string[], callback: () => void) => {
          try {
            callback();
          } catch {
            /* ignore */
          }
          return () => {};
        },
      };
    })(),
    settings: { get: () => undefined, set: () => undefined },
    jobs,
    attachments,
    agentDefaultModel,
    webServer,
  };

  /** ``remote.pluginManager`` and friends resolve through dotted paths. */
  function resolveService(name: string): any {
    const path = String(name || "");
    if (!path) return undefined;
    accessedServices.add(path.split(".")[0]);
    if (path in services) return services[path];
    let cursor: any = services;
    for (const part of path.split(".")) {
      if (cursor === null || cursor === undefined) return undefined;
      cursor = cursor[part];
    }
    return cursor;
  }

  const ctx: any = {
    get(name: string) {
      return resolveService(name);
    },
    inject(deps: string[] | string, callback: (scope: any) => void) {
      const list = Array.isArray(deps) ? deps : [deps];
      const ready = list.every((dep) => resolveService(dep) !== undefined);
      if (!ready) {
        unsupportedMembers.add(`inject:${list.join(",")}`);
        return () => {};
      }
      try {
        const result = callback(ctx);
        if (typeof result === "function") effects.push(result);
      } catch (error) {
        unsupportedMembers.add(`inject:${list.join(",")}:${String(error)}`);
      }
      return () => {};
    },
    effect(fn: () => any) {
      try {
        const disposer = fn();
        if (typeof disposer === "function") effects.push(disposer);
      } catch (error) {
        unsupportedMembers.add(`effect:${String(error)}`);
      }
      return () => {};
    },
    on(event: string, handler: (...args: any[]) => void) {
      if (!listeners.has(event)) listeners.set(event, new Set());
      listeners.get(event)!.add(handler);
      return () => listeners.get(event)?.delete(handler);
    },
    emit(event: string, ...args: any[]) {
      let count = 0;
      for (const handler of listeners.get(event) || []) {
        try {
          handler(...args);
          count += 1;
        } catch (error) {
          unsupportedMembers.add(`emit:${event}:${String(error)}`);
        }
      }
      return count;
    },
    plugin(mod: any) {
      const target = mod && typeof mod.apply === "function" ? mod : mod?.default;
      if (!target || typeof target.apply !== "function") {
        throw new Error("DSH_CLIENT_ENTRY_SHAPE");
      }
      const declared = Array.isArray(target.inject) ? target.inject : [];
      const missing = declared.filter((name: string) => resolveService(name) === undefined);
      for (const name of missing) unsupportedMembers.add(`inject:${name}`);
      return target.apply(ctx, {});
    },
  };
  for (const [name, value] of Object.entries(services)) {
    (ctx as any)[name] = value;
  }

  const exportsList: string[] = [];
  for (const registration of captured) {
    const exported = registration.factory(requireFrom(unsupportedMembers));
    if (!exported) continue;
    exportsList.push(...Object.keys(exported));
    try {
      await ctx.plugin(exported);
    } catch (error) {
      if (String(error).includes("DSH_CLIENT_ENTRY_SHAPE")) continue;
      throw error;
    }
  }

  // Touched-but-unsupported services become visible gaps in the status report
  // instead of looking like working APIs.
  for (const name of accessedServices) {
    const gap = serviceGaps[name];
    if (gap) unsupportedMembers.add(`service:${name}:${gap.code}`);
  }

  return {
    pluginId,
    entries,
    unsupportedSlots: [...unsupportedSlots],
    unsupportedMembers: [...unsupportedMembers],
    exportKeys: exportsList,
    shellProps,
    translate: locale.bind,
    dispose: () => {
      for (const disposer of effects.splice(0)) {
        try {
          disposer();
        } catch {
          /* best effort */
        }
      }
      for (const disposer of disposers.splice(0)) {
        try {
          disposer();
        } catch {
          /* best effort */
        }
      }
      sessionList.dispose();
      statusStore.dispose();
      listeners.clear();
    },
  };
}

/**
 * ``meta.inject().hooks`` → ``useXxx(selector)`` props.
 *
 * DSH hands settings cards a hook backed by the bundle's own store. Without
 * this the card throws ``props.useXxx is not a function`` on first paint.
 *
 * The store's ``getSnapshot`` may build a fresh object per call, which makes
 * ``useSyncExternalStore`` loop forever, so each hook keeps a cache that is
 * only invalidated when the store notifies.
 */
function dshHookProps(
  entry: DshSlotEntry,
  hooks: Record<string, any> | null | undefined,
): Record<string, unknown> {
  if (!hooks || typeof hooks !== "object") return {};
  const holder = entry as any;
  const cells: Map<string, any> = holder.__hookCells ?? (holder.__hookCells = new Map());
  const out: Record<string, unknown> = {};
  for (const [name, hook] of Object.entries(hooks)) {
    if (!hook || typeof hook !== "object") continue;
    let cell = cells.get(name);
    if (!cell) {
      cell = { hook, value: undefined, valid: false, selector: (state: any) => state };
      cells.set(name, cell);
    }
    cell.hook = hook;
    const read = () => (typeof cell.hook.getSnapshot === "function" ? cell.hook.getSnapshot() : undefined);
    const subscribe = (listener: () => void) => {
      cell.valid = false;
      const dispose = typeof cell.hook.subscribe === "function"
        ? cell.hook.subscribe(() => {
            cell.valid = false;
            listener();
          })
        : undefined;
      return typeof dispose === "function" ? dispose : () => {};
    };
    const getSnapshot = () => {
      if (!cell.valid) {
        cell.value = cell.selector(read());
        cell.valid = true;
      }
      return cell.value;
    };
    out[`use${String(name).replace(/(^|[-_.\s])(\w)/g, (_, __, ch: string) => ch.toUpperCase())}`] = (
      selector: (state: any) => unknown = (state: any) => state,
    ) => {
      cell.selector = selector;
      // The hook name is derived from the DSH store name at runtime, so the
      // `use*` prefix cannot be static; this is still one real hook call.
      // eslint-disable-next-line react-hooks/rules-of-hooks
      return React.useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
    };
  }
  return out;
}

/**
 * Composer bridge for ``conversation.input.*`` entries.
 *
 * DSH hands these slots ``inputActions`` (setDraft / insertText / submit) so a
 * picker can drop a token into the composer. The HappyClaw surface contract
 * has no composer API, so the adapter drives the real textarea through native
 * setters + an ``input`` event, which is what React's controlled input needs.
 * Every action returns ``false`` when no composer is on screen.
 */
function composerTextarea(): HTMLTextAreaElement | null {
  if (typeof document === "undefined") return null;
  const active = document.activeElement;
  if (active instanceof HTMLTextAreaElement) return active;
  const visible = Array.from(document.querySelectorAll("textarea")).filter(
    (el) => !el.disabled && !el.readOnly && el.offsetParent !== null,
  );
  return visible.length ? visible[visible.length - 1] : null;
}

function writeComposer(text: string, append = false): boolean {
  const el = composerTextarea();
  if (!el) return false;
  const next = append ? `${el.value}${text}` : text;
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLTextAreaElement.prototype,
    "value",
  )?.set;
  setter?.call(el, next);
  el.dispatchEvent(new Event("input", { bubbles: true }));
  try {
    el.focus();
  } catch {
    /* focus is best effort */
  }
  return true;
}

const composerActions = {
  setDraft: (text: string) => writeComposer(String(text ?? "")),
  append: (text: string) => writeComposer(String(text ?? ""), true),
  insertText: (text: string) => writeComposer(String(text ?? ""), true),
  captureInsertion: () => null,
  submit: () => {
    const el = composerTextarea();
    if (!el) return false;
    el.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    return true;
  },
  focus: () => Boolean(composerTextarea()?.focus()),
};

/** React surface that renders every entry mapped onto one host slot. */
export function DshSlotSurface({
  result,
  slot,
  host,
  context,
}: {
  result: DshMountResult;
  slot: SurfaceSlot;
  host: OctopPluginUIHost;
  context?: SurfaceContext;
}) {
  const visible = result.entries.filter((entry) => mapDshSlot(entry.dshSlot)?.slot === slot);
  if (visible.length === 0) return null;
  return (
    <>
      {visible.map((entry) => {
        const target = mapDshSlot(entry.dshSlot)!;
        let injected: Record<string, unknown> = {};
        if (entry.inject) {
          try {
            injected = entry.inject() || {};
          } catch (error) {
            console.warn(`[dsh-compat] ${result.pluginId}:${entry.id} inject() failed:`, error);
          }
        }
        const message = context?.message;
        const props = {
          ...result.shellProps,
          ...injected,
          ...dshHookProps(entry, injected.hooks as Record<string, any> | undefined),
          ctx: null,
          host,
          pluginId: result.pluginId,
          // Keyed settings cards read ``namespace``/``t`` straight off props.
          namespace: entry.meta?.key ?? null,
          t: result.translate?.(entry.meta?.locale) ?? ((key: string) => key),
          session: context?.threadId ? { id: context.threadId } : null,
          ...(slot === "conversation.input.left" || slot === "conversation.input.overlay"
            ? { inputActions: composerActions }
            : {}),
          // ``conversation.view`` decorates one message; other slots get null so
          // a bundle can branch on it.
          message: message
            ? {
                id: message.id,
                role: message.role,
                content: message.content,
                createdAt: message.createdAt ?? null,
              }
            : null,
          threadId: context?.threadId ?? null,
          agentId: context?.agentId ?? null,
          entry,
        };
        const node = (
          <SurfaceBoundary pluginId={result.pluginId} surfaceId={`${slot}:${entry.id}`}>
            <DshEntryRenderer entry={entry} props={props} />
          </SurfaceBoundary>
        );
        if (!target.overlay) return <React.Fragment key={entry.id}>{node}</React.Fragment>;
        // Overlays float above the page, so they mount on <body> instead of
        // inheriting the sidebar/messages layout box.
        return createPortal(node, document.body, entry.id);
      })}
    </>
  );
}

function DshEntryRenderer({ entry, props }: { entry: DshSlotEntry; props: any }) {
  const Comp = entry.render;
  return <Comp {...props} />;
}
