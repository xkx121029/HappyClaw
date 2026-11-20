// ``DefaultToolRenderer`` is NOT re-exported here on purpose: this barrel is
// imported by the app shell (``MainLayout`` → ``usePluginToolUis``), and that
// renderer pulls the whole 182 kB Chat stylesheet. Import it from
// ``builtin/DefaultToolRenderer`` where it is actually rendered.
export {
  builtinPluginHost,
  createPluginUiHost,
  setPluginUiToolContext,
  setPluginUiDockHandlers,
} from "./host";
export {
  loadInstalledPluginUis,
  reloadPluginToolUis,
  resetPluginUiLoader,
  isPluginUiLoaded,
} from "./loader";
export {
  parseOctopToolOutput,
  mergePatchedToolOutput,
  resolvePluginUiData,
} from "./parseToolOutput";
export {
  registerToolRenderer,
  resolveToolRenderer,
  clearToolRenderers,
  unregisterPluginRenderers,
  listRegisteredRenderers,
  subscribeToolRenderers,
  getToolRendererVersion,
} from "./registry";
export { ensureBuiltinToolRenderers } from "./ensureBuiltins";
export { usePluginToolUis } from "./usePluginToolUis";
export { useToolRendererVersion } from "./useToolRendererVersion";
export type {
  OctopPluginUIHost,
  ParsedToolOutput,
  PluginUiModule,
  ToolRenderProps,
  ToolRendererRegistration,
  ToolRenderStatus,
} from "./types";
