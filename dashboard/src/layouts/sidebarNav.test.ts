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
    const sections = buildNavSections({ mobileEnabled: true });
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
    const keys = buildNavSections({ mobileEnabled: true }).flatMap((section) =>
      section.items.map((item) => item.key),
    );
    expect(new Set(keys)).toEqual(new Set(SIDEBAR_NAV_KEYS));
    const grouped = buildNavSections({ mobileEnabled: true }).filter(
      (section) => section.id,
    );
    expect(grouped.map((section) => section.id)).toEqual([
      "settings",
      "control",
      "admin",
    ]);
  });

  it("no longer exposes user or team management entries", () => {
    const keys = buildNavSections({ mobileEnabled: true }).flatMap((section) =>
      section.items.map((item) => item.key),
    );
    expect(keys).not.toContain("admin-users");
  });
});
