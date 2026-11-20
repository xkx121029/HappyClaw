import type { CSSProperties, HTMLAttributes, ReactNode } from "react";
import cx from "classnames";

export type MotionEnterKind =
  | "rise"
  | "sink"
  | "fade"
  | "scale"
  | "from-left"
  | "from-right";

interface MotionEnterProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  /** 何时播放：只有真正新增的元素才传 true。 */
  animate?: boolean;
  kind?: MotionEnterKind;
  /** 列表错峰序号，建议不超过 6。 */
  index?: number;
  duration?: "fast" | "base" | "slow";
  style?: CSSProperties;
}

/**
 * 进场包裹层。只挂 CSS 动画（transform / opacity），不参与布局计算。
 */
export function MotionEnter({
  children,
  animate = true,
  kind = "rise",
  index = 0,
  duration = "base",
  className,
  style,
  ...rest
}: MotionEnterProps) {
  return (
    <div
      {...rest}
      className={cx(animate && "octop-enter", className)}
      data-motion={kind}
      data-motion-duration={duration}
      style={
        animate
          ? ({
              ...style,
              "--octop-enter-index": Math.min(index, 6),
            } as CSSProperties)
          : style
      }
    >
      {children}
    </div>
  );
}
