import { describe, expect, it } from "vitest";
import {
  canAccessPath,
  pathPermissionKeys,
  routeNeedsPermission,
} from "../utils/permissions";
import { resolveSelectedKey, routeConfigs } from "./index";

/**
 * 单人本机模式（f43f2d73「移除账号体系」）之后，控制台不再按角色或模块权限
 * 裁剪入口：``pathPermissionKeys`` 恒为 ``null``、``canAccessPath`` 恒为
 * ``true``、路由也不再包 ``RequirePermission``。
 *
 * 这些用例把「没有任何受限路径」钉成契约。谁把权限关卡加回来，这里会先红。
 */
describe("single-user console gates nothing", () => {
  it("reports no permission requirement for any dashboard path", () => {
    for (const path of [
      "/chat",
      "/chat/AGT001/thread-1",
      "/experts",
      "/tasks",
      "/connectors",
      "/knowledge-bases",
      "/admin/users",
      "/admin/advanced",
      "/bridge/settings",
      "/remote-desktop/phone",
      "/personalization/skills",
      "/does-not-exist",
    ]) {
      expect(pathPermissionKeys(path)).toBeNull();
    }
  });

  it("lets the local user into every path regardless of holder permissions", () => {
    const holders = [
      null,
      { role: "user", permissions: [] },
      { role: "user", permissions: ["desktop"] },
      { role: "admin", permissions: [] },
    ];
    for (const holder of holders) {
      for (const path of ["/chat", "/experts", "/admin/users", "/bridge"]) {
        expect(canAccessPath(holder, path)).toBe(true);
      }
    }
  });

  it("never wraps a route config in RequirePermission", () => {
    for (const route of routeConfigs) {
      expect(routeNeedsPermission(route.path)).toBe(false);
    }
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
