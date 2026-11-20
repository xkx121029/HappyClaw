import { useRef, type ReactNode } from "react";
import { AnimatePresence, motion } from "motion/react";
import { useLocation, useNavigationType } from "react-router-dom";
import { pendingSharedIds, useMotionTokens } from "../motion";
import type { ResolvedMotionTokens } from "../motion/tokens";
import { routeCatalog } from "./catalog";
import { resolveSharedRelay } from "./sharedRelay";
import {
  resolveRouteTransition,
  type NavigationType,
} from "./resolveTransition";
import type { EdgeSpec, TransitionCatalog, TransitionPlan } from "./types";

function shiftOf(
  step: EdgeSpec["shift"],
  tokens: ResolvedMotionTokens,
): number {
  return step === "none" ? 0 : tokens.shift[step];
}

/**
 * 页间转场的编排组件：放在路由出口，子节点是当前路由内容。
 *
 * - 方向、层级、时序全部由库推导，页面只维护 catalog 声明。
 * - 只动 transform / opacity；退出层不接收指针事件，不延迟新页面可交互时间。
 */
export function PageStage({
  children,
  className,
  catalog = routeCatalog,
}: {
  children: ReactNode;
  className?: string;
  catalog?: TransitionCatalog;
}) {
  const location = useLocation();
  const navigationType = useNavigationType() as NavigationType;
  const tokens = useMotionTokens();
  const route = catalog.resolve(location.pathname);

  const stageRef = useRef<{ stage: string; plan: TransitionPlan } | null>(null);
  const prevRef = useRef<typeof route | null>(null);

  if (!stageRef.current || stageRef.current.stage !== route.stage) {
    const from = prevRef.current;
    const plan = resolveRouteTransition({
      from,
      to: route,
      navigationType,
      reduced: tokens.reduced,
      shared: resolveSharedRelay(from, route, pendingSharedIds()),
    });
    stageRef.current = { stage: route.stage, plan };
    prevRef.current = route;
  }

  const plan = stageRef.current.plan;

  // 退场沿用「把进来时的位移倒放」：从哪来，回哪去。
  const edge = (
    value: EdgeSpec,
    direction: 1 | -1,
    rewind: boolean,
  ): { opacity: number; x: number; scale: number } => ({
    opacity: value.opacity,
    x: (rewind ? -1 : 1) * direction * shiftOf(value.shift, tokens),
    scale: value.scale,
  });

  const variants = {
    initial: (current: TransitionPlan) =>
      edge(current.enter, current.direction, false),
    animate: (current: TransitionPlan) => ({
      opacity: 1,
      x: 0,
      scale: 1,
      transition: {
        duration: tokens.duration[current.duration] / 1000,
        ease: tokens.enterBezier,
      },
    }),
    exit: (current: TransitionPlan) => ({
      ...edge(current.exit, current.direction, true),
      pointerEvents: "none",
      transition: {
        duration: tokens.duration.fast / 1000,
        ease: tokens.exitBezier,
      },
    }),
  };

  return (
    <div
      style={{
        position: "relative",
        flex: 1,
        minWidth: 0,
        minHeight: 0,
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
      }}
      data-transition-tone={plan.tone}
      data-transition-reason={plan.reason}
    >
      <AnimatePresence initial={false} mode="popLayout" custom={plan}>
        <motion.div
          key={route.stage}
          custom={plan}
          variants={variants}
          initial="initial"
          animate="animate"
          exit="exit"
          className={className}
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            flexDirection: "column",
            minHeight: 0,
            overflow: "hidden",
          }}
        >
          {children}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}
