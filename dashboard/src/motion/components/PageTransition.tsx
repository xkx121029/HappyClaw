import { useRef, type ReactNode } from "react";
import { AnimatePresence, motion } from "motion/react";
import { useNavigationType } from "react-router-dom";
import { useMotionTokens } from "../MotionProvider";
import { hasPendingSharedElement } from "../sharedElements";

interface PageTransitionProps {
  /** 同一个 key 内（例如聊天切换会话）不重播转场。 */
  routeKey: string;
  children: ReactNode;
  className?: string;
}

/**
 * 页面转场：前进从右侧进入、后退从左侧回到原位，离开时加速退场。
 *
 * 退出与进入同时进行（新页面立刻可交互），不排队等待离场动画；
 * 退出层不接收指针事件，不会挡住点击。减少动态效果时只保留淡入淡出。
 */
export function PageTransition({
  routeKey,
  children,
  className,
}: PageTransitionProps) {
  const tokens = useMotionTokens();
  const navigationType = useNavigationType();
  const prevKeyRef = useRef(routeKey);
  const directionRef = useRef<1 | -1>(1);
  const sharedRef = useRef(false);

  if (prevKeyRef.current !== routeKey) {
    // POP = 浏览器后退/返回按钮，其余视为前进。
    directionRef.current = navigationType === "POP" ? -1 : 1;
    // 有共享元素承接时退化为淡入，让位给元素自身的位移。
    sharedRef.current = hasPendingSharedElement();
    prevKeyRef.current = routeKey;
  }

  const direction = directionRef.current;
  const shared = sharedRef.current;
  const enterShift = tokens.shift.md;
  const exitShift = Math.round(tokens.shift.sm * 0.75);

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
    >
      <AnimatePresence initial={false} mode="popLayout">
        <motion.div
          key={routeKey}
          className={className}
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            flexDirection: "column",
            minHeight: 0,
            overflow: "hidden",
          }}
          initial={
            shared
              ? { opacity: 0 }
              : { opacity: 0, x: direction * enterShift }
          }
          animate={{
            opacity: 1,
            x: 0,
            transition: {
              duration: shared
                ? tokens.duration.slow / 1000
                : tokens.duration.base / 1000,
              ease: tokens.enterBezier,
            },
          }}
          exit={{
            opacity: 0,
            x: shared ? 0 : -direction * exitShift,
            pointerEvents: "none",
            transition: {
              duration: tokens.duration.fast / 1000,
              ease: tokens.exitBezier,
            },
          }}
        >
          {children}
        </motion.div>
      </AnimatePresence>
    </div>
  );
}
