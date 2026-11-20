import { describe, expect, it } from "vitest";
import { canAccessPath, pathPermissionKeys } from "../utils/permissions";
import { isWorkbenchPath, resolveSelectedKey, routeConfigs } from "./index";

describe("pathPermissionKeys（单人本机模式）", () => {
  it("does not gate any dashboard path", () => {
    expect(isWorkbenchPath("/workbench")).toBe(true);
    // 单人本机模式没有受限路径：所有页面对本机唯一使用者开放。
    for (const path of [
      "/workbench",
      "/workbench/terminal",
      "/workbench/browser",
      "/terminal",
      "/remote-browser",
      "/remote-desktop",
      "/remote-desktop/desktop",
      "/remote-desktop/link",
      "/acp",
      "/admin/users",
      "/admin/advanced",
      "/admin/models",
      "/admin/voice",
      "/bridge",
      "/bridge/settings",
      "/experts",
      "/tasks",
      "/token-usage",
      "/connectors",
      "/skill-packages",
      "/personalization/skills",
      "/personalization/channels",
      "/personalization/tools",
      "/personalization/plugins",
      "/personalization/memory",
      "/memory",
      "/knowledge-bases",
      "/chat",
      "/personalization/acp",
    ]) {
      expect(pathPermissionKeys(path)).toBeNull();
    }
  });

  it("canAccessPath always allows the single local user", () => {
    expect(canAccessPath(null, "/admin/users")).toBe(true);
    expect(canAccessPath({ role: "user", permissions: [] }, "/acp")).toBe(true);
    expect(
      canAccessPath(
        { role: "user", permissions: ["desktop"] },
        "/remote-desktop",
      ),
    ).toBe(true);
    expect(canAccessPath({ role: "admin", permissions: [] }, "/acp")).toBe(
      true,
    );
    expect(
      canAccessPath(
        { role: "user", permissions: ["knowledge_bases"] },
        "/knowledge-bases",
      ),
    ).toBe(true);
    expect(
      canAccessPath({ role: "user", permissions: [] }, "/admin/advanced"),
    ).toBe(true);
  });
});

describe("unknown dashboard paths", () => {
  it("do not highlight a sidebar item", () => {
    expect(resolveSelectedKey("/does-not-exist")).toBe("");
  });

  it("are caught by the not-found route", () => {
    expect(routeConfigs.some((rc) => rc.path === "*")).toBe(true);
  });
});
