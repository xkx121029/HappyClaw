﻿// @vitest-environment jsdom
/**
 * Loader-shim tests.
 *
 * The first block is self-contained and always runs. The second block executes
 * the *real* market bundles named in ``DSH_COMPAT_BUNDLES`` (a JSON array of
 * ``{id, file}``) and is skipped when the variable is absent, so CI does not
 * depend on a developer's market directory.
 */

import { readFileSync } from "node:fs";
import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { OctopPluginUIHost } from "../toolRenderers/types";
import { DshSlotSurface, mapDshSlot, mountDshClient } from "./loaderShim";

function fakeHost(): OctopPluginUIHost {
  return {
    apiVersion: 1,
    registerRenderer() {},
    getToolContext() {
      return { agentId: null, threadId: null, locale: "zh", theme: "light" };
    },
    patchResult() {},
    async request() {
      return {};
    },
    openSidePanel() {},
    closeSidePanel() {},
    surfaces: {
      supports: () => true,
      list: () => [],
      register: () => () => {},
    },
    data: {
      async read() {
        return { updated_at: 0, sessions: [] };
      },
      subscribe: () => () => {},
    },
    events: {
      on: () => () => {},
    },
    context: { locale: "zh", theme: "light" },
  } as unknown as OctopPluginUIHost;
}

function tinyBundle(pluginId: string, slot: string): string {
  return `window.__ModuleLoader__.load({ id: ${JSON.stringify(pluginId)}, factory: (require) => {
    const React = require("react");
    const exports = {};
    exports.inject = ["slots"];
    exports.apply = (ctx) => {
      ctx.slots.inject(${JSON.stringify(slot)}, () => {
        ctx.slots.register({ name: ${JSON.stringify(slot)}, id: "widget" }, () => React.createElement("div", null, "hello"));
      });
    };
    return exports;
  } });`;
}

interface LiveBundle {
  id: string;
  file: string;
}

function liveBundles(): LiveBundle[] {
  const raw = process.env.DSH_COMPAT_BUNDLES;
  if (!raw) return [];
  try {
    return JSON.parse(raw) as LiveBundle[];
  } catch {
    return [];
  }
}

describe("mapDshSlot", () => {
  it("maps the slots HappyClaw exposes and leaves the rest unmapped", () => {
    expect(mapDshSlot("sidebar.footer.action")?.slot).toBe("home.sidebar");
    expect(mapDshSlot("shell.overlay")?.slot).toBe("chat.messages.top");
    expect(mapDshSlot("shell.overlay")?.overlay).toBe(true);
    expect(mapDshSlot("conversation.header.leading")?.slot).toBe("chat.messages.top");
    expect(mapDshSlot("settings.section")?.slot).toBe("settings.section");
    expect(mapDshSlot("plugins.bundle.config")?.slot).toBe("settings.section");
    expect(mapDshSlot("conversation.input.left")?.slot).toBe(
      "conversation.input.left",
    );
    expect(mapDshSlot("conversation.input.overlay")?.slot).toBe(
      "conversation.input.overlay",
    );
    expect(mapDshSlot("conversation.view")?.slot).toBe("conversation.view");
    expect(mapDshSlot("composer.toolbar.custom")).toBeNull();
  });
});

describe("mountDshClient", () => {
  it("mounts a ModuleLoader bundle and renders its sidebar entry", async () => {
    const source = tinyBundle("@demo/widget", "sidebar.footer.action");
    const result = await mountDshClient({
      pluginId: "dsh:demo",
      host: fakeHost(),
      source,
      sourceUrl: "inline",
    });
    expect(result.entries).toHaveLength(1);
    expect(result.unsupportedSlots).toEqual([]);

    const view = render(
      <DshSlotSurface result={result} slot="home.sidebar" host={fakeHost()} />,
    );
    expect(view.getByText("hello")).toBeTruthy();
    view.unmount();
    result.dispose();
  });

  it("reports touched-but-unsupported host services with reason codes", async () => {
    const source = `window.__ModuleLoader__.load({ id: "@demo/services", factory: (require) => {
      const exports = {};
      exports.inject = ["slots", "jobs", "webServer"];
      exports.apply = (ctx) => {
        ctx.get("jobs").register({ id: "tick" });
        ctx.get("webServer").tapIndex("<html></html>");
        ctx.slots.inject("sidebar.footer.action", () => {});
      };
      return exports;
    } });`;
    const result = await mountDshClient({
      pluginId: "dsh:services",
      host: fakeHost(),
      source,
      sourceUrl: "inline",
    });
    expect(result.unsupportedMembers).toContain(
      "service:jobs:HOST_JOBS_UNSUPPORTED",
    );
    expect(result.unsupportedMembers).toContain(
      "service:webServer:HOST_SERVER_HOOK_UNSUPPORTED",
    );
    result.dispose();
  });

  it("refuses attachments upload without an agent context", async () => {
    const source = `window.__ModuleLoader__.load({ id: "@demo/attach", factory: (require) => {
      const exports = {};
      exports.inject = ["slots", "attachments"];
      exports.apply = (ctx) => {
        globalThis.__attachResult = ctx.get("attachments").add(
          new File(["x"], "x.txt"),
        );
      };
      return exports;
    } });`;
    const result = await mountDshClient({
      pluginId: "dsh:attach",
      host: fakeHost(),
      source,
      sourceUrl: "inline",
    });
    // The mount result is stashed on `globalThis` by the fake loader.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const refusal = await (globalThis as any).__attachResult;
    expect(refusal.ok).toBe(false);
    expect(refusal.code).toBe("HOST_AGENT_CONTEXT_MISSING");
    result.dispose();
  });

  it("writes font roles into the variables the chat UI consumes", async () => {
    const source = `window.__ModuleLoader__.load({ id: "@demo/type", factory: (require) => {
      const exports = {};
      exports.inject = ["slots", "theme"];
      exports.apply = (ctx) => {
        const theme = ctx.get("theme");
        theme.setFontSize("text", 18);
        theme.setFontFamily("text", "Georgia, serif");
      };
      return exports;
    } });`;
    const result = await mountDshClient({
      pluginId: "dsh:type",
      host: fakeHost(),
      source,
      sourceUrl: "inline",
    });
    const root = document.documentElement;
    expect(root.style.getPropertyValue("--dsh-font-size-text")).toBe("18px");
    expect(root.style.getPropertyValue("--dsh-font-family-text")).toContain("Georgia");
    result.dispose();
    root.style.removeProperty("--dsh-font-size-text");
    root.style.removeProperty("--dsh-font-family-text");
  });

  it("reports unmappable slots instead of silently dropping them", async () => {
    const source = tinyBundle("@demo/toolbar", "composer.toolbar.custom");
    const result = await mountDshClient({
      pluginId: "dsh:demo2",
      host: fakeHost(),
      source,
      sourceUrl: "inline",
    });
    expect(result.entries).toHaveLength(0);
    expect(result.unsupportedSlots).toContain("composer.toolbar.custom");
    result.dispose();
  });
});

const bundles = liveBundles();
describe.skipIf(bundles.length === 0)("real market bundles", () => {
  for (const bundle of bundles) {
    it(`mounts ${bundle.id}`, async () => {
      const source = readFileSync(bundle.file, "utf8");
      const result = await mountDshClient({
        pluginId: bundle.id,
        host: fakeHost(),
        source,
        sourceUrl: bundle.file,
      });
      const slots = result.entries.map((entry) => entry.dshSlot);
      // eslint-disable-next-line no-console
      console.info(
        `[live] ${bundle.id}: entries=${slots.join(",") || "-"} unsupportedSlots=${result.unsupportedSlots.join(",") || "-"} unsupported=${result.unsupportedMembers.slice(0, 3).join(" | ") || "-"}`,
      );
      expect(result.exportKeys.length).toBeGreaterThan(0);
      expect(result.unsupportedSlots).not.toContain("");

      // Render every slot the bundle mapped into, so a component that mounts
      // but explodes on first paint is not reported as working.
      const mapped = new Set(
        result.entries
          .map((entry) => mapDshSlot(entry.dshSlot)?.slot)
          .filter((slot): slot is NonNullable<typeof slot> => Boolean(slot)),
      );
      for (const slot of mapped) {
        const view = render(
          <DshSlotSurface result={result} slot={slot} host={fakeHost()} />,
        );
        const text = (view.container.textContent || "").replace(/\s+/g, " ").slice(0, 80);
        const nodes = view.container.querySelectorAll("*").length;
        // eslint-disable-next-line no-console
        console.info(`[live] ${bundle.id}/${slot}: nodes=${nodes} text="${text}"`);
        expect(
          view.container.querySelector("[role=alert]"),
          `${bundle.id} crashed in ${slot}`,
        ).toBeNull();
        view.unmount();
      }

      // An input-area trigger must actually open its overlay, otherwise the
      // button is decoration. Click the first trigger and expect DOM growth.
      if (mapped.has("conversation.input.left") && mapped.has("conversation.input.overlay")) {
        const trigger = render(
          <DshSlotSurface result={result} slot="conversation.input.left" host={fakeHost()} />,
        );
        const button = trigger.container.querySelector("button");
        expect(button, `${bundle.id} rendered no input trigger`).not.toBeNull();
        fireEvent.click(button as HTMLElement);
        const overlay = render(
          <DshSlotSurface result={result} slot="conversation.input.overlay" host={fakeHost()} />,
        );
        const overlayNodes = overlay.container.querySelectorAll("*").length;
        // eslint-disable-next-line no-console
        console.info(`[live] ${bundle.id}/overlay-after-click nodes=${overlayNodes}`);
        expect(overlayNodes, `${bundle.id} overlay stayed empty after click`).toBeGreaterThan(1);
        overlay.unmount();
        trigger.unmount();
      }
      result.dispose();
    });
  }
});
