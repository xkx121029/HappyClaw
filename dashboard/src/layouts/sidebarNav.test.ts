import { describe, expect, it } from "vitest";
import {
  SIDEBAR_GROUPED_NAV_KEYS,
  SIDEBAR_NAV_KEYS,
  buildNavSections,
  isGroupedNavKey,
} from "./sidebarNav";

describe("sidebarNav", () => {
  it("marks catalog keys as grouped", () => {
    for (const key of SIDEBAR_GROUPED_NAV_KEYS) {
      expect(isGroupedNavKey(key)).toBe(true);
    }
    expect(isGroupedNavKey("chat")).toBe(false);
    expect(isGroupedNavKey("experts")).toBe(false);
  });

  it("places grouped keys only under sections with groupKey", () => {
    // 单人模式：导航不再按角色裁剪，本机直接拿到完整目录。
    const sections = buildNavSections();
    const flatKeys = new Set(
      sections
        .filter((s) => !s.groupKey)
        .flatMap((s) => s.items.map((i) => i.key)),
    );
    const groupedKeys = new Set(
      sections
        .filter((s) => s.groupKey)
        .flatMap((s) => s.items.map((i) => i.key)),
    );
    for (const key of groupedKeys) {
      expect(isGroupedNavKey(key)).toBe(true);
      expect(flatKeys.has(key)).toBe(false);
    }
    for (const key of flatKeys) {
      expect(isGroupedNavKey(key)).toBe(false);
    }
  });

  it("covers every catalog key from the local owner nav", () => {
    const keys = buildNavSections().flatMap((section) =>
      section.items.map((item) => item.key),
    );
    // ``home`` and ``quick-chat`` are pinned outside the customizable catalog,
    // so they are not part of ``SIDEBAR_NAV_KEYS`` (and never reach the backend
    // layout whitelist).
    expect(new Set(keys)).toEqual(
      new Set([...SIDEBAR_NAV_KEYS, "home", "quick-chat"]),
    );
    expect(keys.filter((key) => key === "home")).toHaveLength(1);
    expect(keys.filter((key) => key === "quick-chat")).toHaveLength(1);
    // Two levels only: the four daily destinations plus one 设置 group. Every
    // configurable surface lives under it so the first level stays scannable.
    const grouped = buildNavSections().filter((section) => section.id);
    expect(grouped.map((section) => section.id)).toEqual(["settings"]);
  });

  it("keeps daily destinations outside the settings group", () => {
    const [primary, settings] = buildNavSections();
    expect(primary.id).toBeUndefined();
    expect(primary.items.map((item) => item.key)).toEqual([
      "home",
      "chat",
      "quick-chat",
      "experts",
      "tasks",
    ]);
    expect(settings.id).toBe("settings");
    expect(primary.items.length).toBeLessThanOrEqual(5);
  });

  it("no longer exposes user or team management entries", () => {
    const keys = buildNavSections().flatMap((section) =>
      section.items.map((item) => item.key),
    );
    expect(keys).not.toContain("admin-users");
  });
});
