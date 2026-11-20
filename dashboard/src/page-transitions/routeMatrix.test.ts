import { describe, expect, it } from "vitest";
import { routeConfigs } from "../routes";
import {
  createTransitionCatalog,
  DEFAULT_ROUTE_SPECS,
  resolveRoute,
  resolveRouteTransition,
  resolveSharedRelay,
  routeCatalog,
} from "./index";
import type { RouteSpec } from "./types";

const plan = (
  fromPath: string | null,
  toPath: string,
  navigationType: "PUSH" | "POP" | "REPLACE" = "PUSH",
  options: { reduced?: boolean; shared?: boolean } = {},
) =>
  resolveRouteTransition({
    from: fromPath ? resolveRoute(fromPath) : null,
    to: resolveRoute(toPath),
    navigationType,
    reduced: options.reduced ?? false,
    shared: options.shared ?? false,
  });

describe("路由矩阵：全部路由都有明确转场", () => {
  const paths = routeConfigs
    .map((route) => route.path)
    .filter((path) => path !== "*");

  it("声明表覆盖 routes/index.tsx 里的每一条路由", () => {
    const missing = paths.filter(
      (path) => routeCatalog.resolve(path).matched === "fallback",
    );
    expect(missing).toEqual([]);
  });

  it("未知路径才落到 fallback", () => {
    expect(resolveRoute("/__not_a_page__").matched).toBe("fallback");
    expect(plan("/tasks", "/__not_a_page__").tone).toBe("soft");
  });

  it("每条声明都带模块、层级与页面形态", () => {
    for (const spec of DEFAULT_ROUTE_SPECS) {
      expect(spec.module, spec.path).toBeTruthy();
      expect(Number.isInteger(spec.depth), spec.path).toBe(true);
      expect(spec.kind, spec.path).toBeTruthy();
    }
  });

  it("动态路由与通配前缀能落到具体页面", () => {
    expect(resolveRoute("/chat/agent-1/thread-9").stage).toBe("chat");
    expect(resolveRoute("/personalization/skills").matched).toBe("prefix");
    expect(resolveRoute("/personalization/skills").stage).toBe(
      "personalization",
    );
  });
});

describe("路由矩阵：方向与层级语义", () => {
  it("首页 → 控制台是跨模块前进", () => {
    const result = plan("/home", "/tasks");
    expect(result.tone).toBe("cross-forward");
    expect(result.direction).toBe(1);
    expect(result.enter.shift).toBe("xl");
  });

  it("控制台 → 首页是跨模块后退", () => {
    const result = plan("/home", "/tasks");
    expect(result.tone).toBe("cross-forward");
    expect(plan("/tasks", "/home").direction).toBe(-1);
    expect(plan("/tasks", "/home").tone).toBe("cross-back");
  });

  it("后退导航总把方向翻过来", () => {
    expect(plan("/home", "/tasks", "POP").direction).toBe(-1);
    expect(plan("/experts", "/connectors", "POP").direction).toBe(-1);
  });

  it("同级列表之间用横向平移", () => {
    const forward = plan("/experts", "/connectors");
    expect(forward.tone).toBe("lateral");
    expect(forward.enter.shift).toBe("lg");
    expect(forward.exit.shift).toBe("md");
    expect(forward.duration).toBe("base");
  });

  it("列表进详情用深度推进，返回时反向", () => {
    const forward = plan("/experts", "/agent-config");
    expect(forward.tone).toBe("depth-forward");
    expect(forward.direction).toBe(1);
    expect(forward.enter.scale).toBeLessThan(1);

    const back = plan("/agent-config", "/experts");
    expect(back.tone).toBe("depth-back");
    expect(back.direction).toBe(-1);
  });

  it("平级页签位移更短、节奏更快", () => {
    const tab = plan("/experts", "/personalization/skills");
    expect(tab.tone).toBe("tab");
    expect(tab.enter.shift).toBe("sm");
    expect(tab.duration).toBe("fast");
  });

  it("同一页面实例内切换不播转场（会话 / 个人中心页签）", () => {
    expect(plan("/chat/agent-1/thread-1", "/chat/agent-2/thread-2").tone).toBe(
      "none",
    );
    expect(plan("/personalization/skills", "/personalization/tools").tone).toBe(
      "none",
    );
    expect(plan("/tasks", "/tasks").tone).toBe("none");
  });

  it("设置页之间是层级推进", () => {
    expect(plan("/admin/models", "/admin/backend").tone).toBe("depth-forward");
    expect(plan("/admin/backend", "/admin/plugins").tone).toBe("lateral");
  });
});

describe("路由矩阵：降级与时序", () => {
  it("首次渲染不播动画", () => {
    const result = resolveRouteTransition({
      from: null,
      to: resolveRoute("/home"),
      navigationType: "PUSH",
      reduced: false,
      shared: false,
    });
    expect(result.tone).toBe("none");
    expect(result.reason).toBe("initial");
  });

  it("减少动态效果时只保留淡入淡出", () => {
    const result = plan("/home", "/tasks", "PUSH", { reduced: true });
    expect(result.tone).toBe("soft");
    expect(result.enter.shift).toBe("none");
    expect(result.enter.scale).toBe(1);
    expect(result.enter.opacity).toBe(0);
    expect(result.reason).toBe("reduced-motion");
  });

  it("共享元素接力时整页让位给 FLIP", () => {
    const result = plan("/home", "/chat/a/thread-1", "PUSH", { shared: true });
    expect(result.tone).toBe("soft");
    expect(result.duration).toBe("slow");
    expect(result.enter.shift).toBe("none");
    expect(result.reason).toBe("shared-element");
  });

  it("只使用位移 / 缩放 / 透明度三类别名", () => {
    for (const [from, to] of [
      ["/home", "/tasks"],
      ["/experts", "/agent-config"],
      ["/experts", "/connectors"],
      ["/experts", "/personalization/skills"],
    ] as const) {
      const result = plan(from, to);
      expect(Object.keys(result.enter).sort()).toEqual([
        "opacity",
        "scale",
        "shift",
      ]);
    }
  });
});

describe("共享元素接力：由库统一判定", () => {
  const relay = (from: string, to: string, ids: string[]) =>
    resolveSharedRelay(resolveRoute(from), resolveRoute(to), ids);

  it("双方都声明了同一种能力、且确有记录时才接力", () => {
    expect(relay("/home", "/chat/a/t1", ["thread-title:初次问候"])).toBe(true);
    expect(relay("/home", "/chat/a/t1", ["job-1"])).toBe(false);
    expect(relay("/home", "/chat/a/t1", [])).toBe(false);
  });

  it("目标页没有同源元素就不硬凑", () => {
    expect(relay("/home", "/tasks", ["thread-title:x"])).toBe(false);
    expect(relay("/experts", "/chat/a/t1", ["thread-title:x"])).toBe(false);
  });

  it("同一个页面实例内不接力", () => {
    expect(relay("/chat/a/t1", "/chat/a/t2", ["thread-title:x"])).toBe(false);
  });

  it("声明了能力但没记录时整页仍走完整转场", () => {
    const result = resolveRouteTransition({
      from: resolveRoute("/home"),
      to: resolveRoute("/chat/a/t1"),
      navigationType: "PUSH",
      reduced: false,
      shared: relay("/home", "/chat/a/t1", []),
    });
    expect(result.reason).toBe("module home->chat");
  });
});

describe("路由目录：声明式扩展", () => {
  it("新增页面只加声明，不用改库", () => {
    const extra: RouteSpec[] = [
      { path: "/reports", module: "agent", depth: 0, kind: "list" },
      {
        path: "/reports/:id",
        module: "agent",
        depth: 1,
        kind: "detail",
        shared: ["report-title"],
      },
    ];
    const catalog = createTransitionCatalog([...DEFAULT_ROUTE_SPECS, ...extra]);

    expect(catalog.resolve("/reports").stage).toBe("/reports");
    expect(catalog.resolve("/reports/r-1").spec.depth).toBe(1);

    const pushed = resolveRouteTransition({
      from: catalog.resolve("/reports"),
      to: catalog.resolve("/reports/r-1"),
      navigationType: "PUSH",
      reduced: false,
      shared: true,
    });
    expect(pushed.reason).toBe("shared-element");
  });

  it("重复声明会直接报错，避免路由被悄悄覆盖", () => {
    expect(() =>
      createTransitionCatalog([
        { path: "/a", module: "agent", depth: 0, kind: "list" },
        { path: "/a", module: "agent", depth: 0, kind: "list" },
      ]),
    ).toThrow(/重复声明/);
  });

  it("前缀声明按最长前缀匹配", () => {
    const catalog = createTransitionCatalog([
      { path: "/workbench/*", module: "control", depth: 0, kind: "workspace" },
      {
        path: "/workbench/cloud/*",
        module: "control",
        depth: 1,
        kind: "detail",
      },
      { path: "*", module: "misc", depth: 0, kind: "fallback" },
    ]);
    expect(catalog.resolve("/workbench/terminal").spec.depth).toBe(0);
    expect(catalog.resolve("/workbench/cloud/files").spec.depth).toBe(1);
  });
});
