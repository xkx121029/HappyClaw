import * as React from "react";
import * as ReactJSX from "react/jsx-runtime";
import { builtinPluginHost } from "./host";
import { registerToolRenderer } from "./registry";
import type { ToolRenderProps } from "./types";

let builtinsRegistered = false;

declare global {
  interface Window {
    __OCTOP_REACT__?: typeof React;
    __OCTOP_JSX__?: typeof ReactJSX;
  }
}

/** Expose React for plugin ESM blobs (no bundler import map). */
function exposeReactGlobals(): void {
  if (typeof window === "undefined") return;
  window.__OCTOP_REACT__ = React;
  window.__OCTOP_JSX__ = ReactJSX;
}

/**
 * ``DefaultToolRenderer`` imports the Chat stylesheet (182 kB of Less across
 * fourteen partials). It is registered from the app shell, so a static import
 * here put that stylesheet in the first paint of every page — including
 * pages that never render a tool call. Load it on first use instead.
 */
const LazyDefaultToolRenderer = React.lazy(() =>
  import("./builtin/DefaultToolRenderer").then((mod) => ({
    default: mod.DefaultToolRenderer,
  })),
);

function DefaultToolRendererHost(props: ToolRenderProps) {
  return React.createElement(
    React.Suspense,
    { fallback: null },
    React.createElement(LazyDefaultToolRenderer, props),
  );
}

/** Register first-party fallback renderer once. */
export function ensureBuiltinToolRenderers(): void {
  if (builtinsRegistered) return;
  builtinsRegistered = true;
  exposeReactGlobals();
  registerToolRenderer({
    id: "default",
    pluginId: "builtin",
    component: DefaultToolRendererHost,
  });
  void builtinPluginHost;
}
