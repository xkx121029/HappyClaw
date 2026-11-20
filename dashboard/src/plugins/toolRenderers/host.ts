import { request } from "../../api/request";
import i18n from "../../i18n";
import {
  mergePatchedToolOutput,
  parseOctopToolOutput,
} from "./parseToolOutput";
import { registerToolRenderer } from "./registry";
import { PLUGIN_UI_API_VERSION, isSurfaceSlot } from "../surfaces/types";
import {
  listPluginSurfaceInfo,
  registerPluginSurface,
} from "../surfaces/registry";
import {
  readPluginData,
  subscribePluginData,
  subscribePluginEvent,
} from "../surfaces/data";
import type {
  OctopPluginUIHost,
  ToolRenderContext,
  ToolRendererRegistration,
} from "./types";

let contextOverride: Partial<ToolRenderContext> = {};
let dockHandlers: {
  openSidePanel?: (opts: {
    callId: string;
    title?: string;
    toolName?: string;
  }) => void;
  closeSidePanel?: (callId: string) => void;
} = {};

/** Chat page wires dock open/close for plugin ``host.openSidePanel``. */
export function setPluginUiDockHandlers(handlers: typeof dockHandlers): void {
  dockHandlers = handlers;
}

/** Chat page sets agent/thread so plugin UIs can call scoped APIs. */
export function setPluginUiToolContext(
  partial: Partial<ToolRenderContext>,
): void {
  contextOverride = { ...contextOverride, ...partial };
}

function readTheme(): "light" | "dark" {
  if (typeof document === "undefined") return "light";
  const attr = document.documentElement.getAttribute("data-theme");
  if (attr === "dark") return "dark";
  if (document.documentElement.classList.contains("dark")) return "dark";
  return "light";
}

function createHost(defaultPluginId: string): OctopPluginUIHost {
  const host: OctopPluginUIHost = {
    apiVersion: PLUGIN_UI_API_VERSION,
    registerRenderer(reg) {
      const pluginId = reg.pluginId ?? defaultPluginId;
      const full: ToolRendererRegistration = {
        id: reg.id,
        pluginId,
        tools: reg.tools,
        component: reg.component,
      };
      registerToolRenderer(full);
    },
    getToolContext(): ToolRenderContext {
      return {
        agentId: contextOverride.agentId ?? null,
        threadId: contextOverride.threadId ?? null,
        locale: contextOverride.locale ?? i18n.language ?? "en",
        theme: contextOverride.theme ?? readTheme(),
      };
    },
    patchResult(callId: string, nextData: unknown) {
      if (!callId) return;
      // Dynamic: the chat store is only reachable once a tool UI exists, and
      // the app shell imports this host for every page.
      void import("../../pages/Chat/hooks/chatStore").then((mod) => {
        mod.patchToolResultData(callId, nextData);
      });
    },
    request<T = unknown>(path: string, init?: RequestInit) {
      return request<T>(path, init);
    },
    openSidePanel(opts) {
      dockHandlers.openSidePanel?.(opts);
    },
    closeSidePanel(callId) {
      dockHandlers.closeSidePanel?.(callId);
    },
    surfaces: {
      supports: isSurfaceSlot,
      list(slot) {
        return listPluginSurfaceInfo(slot);
      },
      register(reg) {
        return registerPluginSurface(defaultPluginId, reg, host);
      },
    },
    data: {
      read<T = unknown>(domain: string) {
        return readPluginData<T>(domain);
      },
      subscribe<T = unknown>(domain: string, cb: (value: T) => void) {
        return subscribePluginData<T>(domain, cb);
      },
    },
    events: {
      on<T = unknown>(event: string, cb: (payload: T) => void) {
        return subscribePluginEvent<T>(event, cb);
      },
    },
    get context() {
      return {
        locale: contextOverride.locale ?? i18n.language ?? "en",
        theme: contextOverride.theme ?? readTheme(),
      };
    },
  };
  return host;
}

/** Host bound to ``builtin`` for first-party renderers. */
export const builtinPluginHost: OctopPluginUIHost = createHost("builtin");

/** Build a host scoped to an installed plugin id (for dynamic UI modules). */
export function createPluginUiHost(pluginId: string): OctopPluginUIHost {
  return createHost(pluginId);
}

export { parseOctopToolOutput, mergePatchedToolOutput };
