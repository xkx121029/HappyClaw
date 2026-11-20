import { afterEach, describe, expect, it } from "vitest";
import {
  clearPluginSurfaces,
  listPluginSurfaces,
  listSurfacePlugins,
  registerPluginSurface,
  unregisterPluginSurfaces,
} from "./registry";
import type { OctopPluginUIHost } from "../toolRenderers/types";

const host = {} as OctopPluginUIHost;
const Component = () => null;

afterEach(() => {
  clearPluginSurfaces();
});

describe("plugin surface registry", () => {
  it("registers and removes a surface per plugin", () => {
    const dispose = registerPluginSurface(
      "plugin-a",
      {
        id: "progress",
        slot: "home.sidebar",
        title: "实时任务进度",
        component: Component,
      },
      host,
    );

    const registered = listPluginSurfaces("home.sidebar");
    expect(registered).toHaveLength(1);
    expect(registered[0].pluginId).toBe("plugin-a");
    expect(registered[0].title).toBe("实时任务进度");
    expect(registered[0].order).toBe(100);
    expect(listSurfacePlugins()).toEqual(["plugin-a"]);

    dispose();
    expect(listPluginSurfaces("home.sidebar")).toHaveLength(0);
    expect(listSurfacePlugins()).toEqual([]);
  });

  it("unregisters every surface owned by one plugin", () => {
    registerPluginSurface(
      "plugin-a",
      { id: "one", slot: "home.sidebar", component: Component },
      host,
    );
    registerPluginSurface(
      "plugin-a",
      { id: "two", slot: "home.sidebar", component: Component },
      host,
    );
    registerPluginSurface(
      "plugin-b",
      { id: "three", slot: "home.sidebar", component: Component },
      host,
    );

    unregisterPluginSurfaces("plugin-a");

    expect(listPluginSurfaces("home.sidebar").map((item) => item.id)).toEqual([
      "three",
    ]);
  });

  it("sorts by order then plugin id", () => {
    registerPluginSurface(
      "z-plugin",
      { id: "late", slot: "chat.messages.top", order: 200, component: Component },
      host,
    );
    registerPluginSurface(
      "a-plugin",
      { id: "early", slot: "chat.messages.top", order: 10, component: Component },
      host,
    );
    expect(listPluginSurfaces("chat.messages.top").map((item) => item.id)).toEqual([
      "early",
      "late",
    ]);
  });

  it("rejects unknown slots instead of mounting nowhere", () => {
    expect(() =>
      registerPluginSurface(
        "plugin-a",
        {
          id: "bad",
          // @ts-expect-error deliberately invalid for the runtime guard
          slot: "does.not.exist",
          component: Component,
        },
        host,
      ),
    ).toThrow("SURFACE_SLOT_UNKNOWN");
  });

  it("isolates slots from each other", () => {
    registerPluginSurface(
      "plugin-a",
      { id: "home", slot: "home.sidebar", component: Component },
      host,
    );
    expect(listPluginSurfaces("chat.messages.top")).toHaveLength(0);
  });

  it("accepts every slot declared by the v1 contract", () => {
    const slots = [
      "home.sidebar",
      "chat.messages.top",
      "conversation.view",
      "conversation.input.left",
      "conversation.input.overlay",
      "settings.section",
    ] as const;
    for (const slot of slots) {
      registerPluginSurface(
        "plugin-a",
        { id: `id-${slot}`, slot, component: Component },
        host,
      );
      expect(listPluginSurfaces(slot)).toHaveLength(1);
    }
  });
});
