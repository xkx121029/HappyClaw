/**
 * 页间转场库 — 类型定义
 *
 * 页面只需要在路由表里声明自己的 module / depth / kind / stage / shared，
 * 转场的方向、层级、时序由库统一推导，页面组件不需要写任何 transition。
 */

/** 业务模块：顺序即侧栏自上而下的顺序，用于跨模块转场的方向语义。 */
export type TransitionModule =
  | "home"
  | "chat"
  | "solo"
  | "bao"
  | "agent"
  | "control"
  | "settings"
  | "admin"
  | "debug"
  | "misc";

/** 页面形态：决定同级页面之间用平移还是淡入。 */
export type RoutePageKind =
  | "hub"
  | "list"
  | "detail"
  | "tab"
  | "conversation"
  | "workspace"
  | "fallback";

/** 位移档位，映射到 motion token 的位移尺度。 */
export type ShiftStep = "none" | "xs" | "sm" | "md" | "lg" | "xl";

/** 时长档位，映射到 motion token 的时长阶梯。 */
export type DurationStep = "fast" | "base" | "slow";

/**
 * 单条路由声明。
 * - stage：复用同一个页面实例的 key（如聊天会话切换），相同 stage 不播转场。
 * - shared：该页面能承接的共享元素能力，仅作声明与核对用途。
 */
export interface RouteSpec {
  path: string;
  module: TransitionModule;
  depth: number;
  kind: RoutePageKind;
  stage?: string;
  shared?: string[];
}

export interface ResolvedRoute {
  spec: RouteSpec;
  path: string;
  stage: string;
  matched: "exact" | "pattern" | "prefix" | "fallback";
}

export type TransitionTone =
  | "lateral"
  | "depth-forward"
  | "depth-back"
  | "cross-forward"
  | "cross-back"
  | "tab"
  | "soft"
  | "none";

/** 进入/退出时相对最终位置的偏移规格。 */
export interface EdgeSpec {
  shift: ShiftStep;
  scale: number;
  opacity: number;
}

export interface TransitionPlan {
  tone: TransitionTone;
  /** 1 = 目标从前/右侧进来；-1 = 从后/左侧进来。 */
  direction: 1 | -1;
  enter: EdgeSpec;
  exit: EdgeSpec;
  duration: DurationStep;
  reason: string;
}

export interface TransitionCatalog {
  specs: RouteSpec[];
  resolve(pathname: string): ResolvedRoute;
}
