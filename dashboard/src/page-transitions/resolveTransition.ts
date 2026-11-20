import { MODULE_ORDER } from "./catalog";
import type { ResolvedRoute, TransitionPlan } from "./types";

const NONE: TransitionPlan = {
  tone: "none",
  direction: 1,
  enter: { shift: "none", scale: 1, opacity: 1 },
  exit: { shift: "none", scale: 1, opacity: 1 },
  duration: "fast",
  reason: "none",
};

const SOFT: TransitionPlan = {
  tone: "soft",
  direction: 1,
  enter: { shift: "none", scale: 1, opacity: 0 },
  exit: { shift: "none", scale: 1, opacity: 0 },
  duration: "base",
  reason: "soft",
};

// 深度推进：目标从更靠前的位置推入，来源退到更远的一层。
const DEPTH_ENTER = { shift: "xl" as const, scale: 0.96, opacity: 0 };
const DEPTH_EXIT = { shift: "md" as const, scale: 1.02, opacity: 0 };

// 跨模块：比同级平移更明确的方向感，但仍不抢内容。
const CROSS_ENTER = { shift: "xl" as const, scale: 0.985, opacity: 0 };
const CROSS_EXIT = { shift: "lg" as const, scale: 1.01, opacity: 0 };

// 同级页面：纯横向平移。
const LATERAL_ENTER = { shift: "lg" as const, scale: 1, opacity: 0 };
const LATERAL_EXIT = { shift: "md" as const, scale: 1, opacity: 0 };

// 页签：位移更短、节奏更快，避免在同一块内容上来回大幅晃动。
const TAB_ENTER = { shift: "sm" as const, scale: 1, opacity: 0 };
const TAB_EXIT = { shift: "xs" as const, scale: 1, opacity: 0 };

export type NavigationType = "PUSH" | "POP" | "REPLACE";

export interface ResolveTransitionInput {
  from: ResolvedRoute | null;
  to: ResolvedRoute;
  navigationType: NavigationType;
  reduced: boolean;
  /** 目标页是否正在承接共享元素。 */
  shared: boolean;
}

/**
 * 纯函数：把「从哪到哪」解析成一份可测试的转场计划。
 *
 * 优先级：减少动态 > 首次渲染 > 同实例 > 共享元素 > 404 > 层级 > 跨模块 > 同级。
 */
export function resolveRouteTransition({
  from,
  to,
  navigationType,
  reduced,
  shared,
}: ResolveTransitionInput): TransitionPlan {
  if (reduced) {
    return {
      ...SOFT,
      reason: "reduced-motion",
      enter: { shift: "none", scale: 1, opacity: 0 },
    };
  }
  if (!from || from.stage === to.stage) {
    return { ...NONE, reason: from ? "same-stage" : "initial" };
  }
  if (to.spec.kind === "fallback" || from.spec.kind === "fallback") {
    return { ...SOFT, reason: "fallback" };
  }
  if (shared) {
    // 共享元素已经承担了连续性，整页只做淡入，避免两种运动打架。
    return { ...SOFT, reason: "shared-element", duration: "slow" };
  }

  const goingBack = navigationType === "POP";
  const sameModule = from.spec.module === to.spec.module;

  if (sameModule && to.spec.depth !== from.spec.depth) {
    const forward = to.spec.depth > from.spec.depth;
    return {
      tone: forward ? "depth-forward" : "depth-back",
      direction: forward ? 1 : -1,
      enter: DEPTH_ENTER,
      exit: DEPTH_EXIT,
      duration: "base",
      reason: `depth ${from.spec.depth}->${to.spec.depth}`,
    };
  }

  if (!sameModule) {
    const moduleForward =
      MODULE_ORDER[to.spec.module] >= MODULE_ORDER[from.spec.module];
    const direction: 1 | -1 = goingBack ? -1 : moduleForward ? 1 : -1;
    return {
      tone: direction === 1 ? "cross-forward" : "cross-back",
      direction,
      enter: CROSS_ENTER,
      exit: CROSS_EXIT,
      duration: "base",
      reason: `module ${from.spec.module}->${to.spec.module}`,
    };
  }

  const isTab =
    to.spec.kind === "tab" ||
    from.spec.kind === "tab" ||
    to.spec.kind === "conversation" ||
    from.spec.kind === "conversation";
  const direction: 1 | -1 = goingBack ? -1 : 1;

  return isTab
    ? {
        tone: "tab",
        direction,
        enter: TAB_ENTER,
        exit: TAB_EXIT,
        duration: "fast",
        reason: "tab",
      }
    : {
        tone: "lateral",
        direction,
        enter: LATERAL_ENTER,
        exit: LATERAL_EXIT,
        duration: "base",
        reason: "lateral",
      };
}
