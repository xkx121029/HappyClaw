import { beforeEach, describe, expect, it, vi } from "vitest";

const STORAGE_KEY = "octop.bao.appearance.v1";

/** Fresh module state per test: the store snapshots localStorage at import. */
async function loadModule() {
  vi.resetModules();
  return import("./appearance");
}

describe("shared mascot appearance", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("starts from one default record", async () => {
    const mod = await loadModule();
    expect(mod.getMascotAppearance()).toEqual(mod.DEFAULT_MASCOT_APPEARANCE);
    expect(mod.DEFAULT_MASCOT_APPEARANCE).toEqual({
      shape: "pebble",
      color: "black",
      bodyColor: null,
      eyeColor: null,
      followTheme: false,
    });
  });

  it("publishes the saved look to every surface and caches it for boot", async () => {
    const mod = await loadModule();
    const look = {
      shape: "gem",
      color: "violet",
      bodyColor: "#123456",
      eyeColor: "#ffffff",
      followTheme: false,
    } as const;

    mod.syncMascotAppearance(look);

    expect(mod.getMascotAppearance()).toEqual(look);
    expect(JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}")).toEqual(
      look,
    );

    // Surfaces rendered before settings load (boot, crash, setup) read the cache.
    const reloaded = await loadModule();
    expect(reloaded.getMascotAppearance()).toEqual(look);
  });

  it("keeps the reference stable when the record did not change", async () => {
    const mod = await loadModule();
    const look = {
      shape: "bean",
      color: "blue",
      bodyColor: null,
      eyeColor: null,
      followTheme: true,
    } as const;

    mod.syncMascotAppearance(look);
    const first = mod.getMascotAppearance();
    mod.syncMascotAppearance({ ...look });

    expect(mod.getMascotAppearance()).toBe(first);
  });

  it("resets to the default look and clears the cache", async () => {
    const mod = await loadModule();
    mod.syncMascotAppearance({
      shape: "leaf",
      color: "green",
      bodyColor: "#00ff00",
      eyeColor: null,
      followTheme: false,
    });

    mod.resetMascotAppearance();

    expect(mod.getMascotAppearance()).toEqual(mod.DEFAULT_MASCOT_APPEARANCE);
    expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
  });
});

describe("mascotStatusInk", () => {
  const base = {
    shape: "pebble",
    color: "black",
    bodyColor: null,
    eyeColor: null,
    followTheme: false,
  } as const;

  it("uses the live-state inks on the default palette", async () => {
    const mod = await loadModule();
    expect(mod.mascotStatusInk(base, "working")).toBe("orange");
    expect(mod.mascotStatusInk(base, "error")).toBe("red");
    expect(mod.mascotStatusInk(base, null)).toBe("black");
  });

  it("never overrides a custom or theme-following body", async () => {
    const mod = await loadModule();
    expect(
      mod.mascotStatusInk({ ...base, bodyColor: "#123456" }, "working"),
    ).toBe("black");
    expect(mod.mascotStatusInk({ ...base, followTheme: true }, "error")).toBe(
      "black",
    );
  });
});
