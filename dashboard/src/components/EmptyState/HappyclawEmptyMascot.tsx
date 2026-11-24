import cx from "classnames";

import { HAPPYCLAW_EMPTY_MASCOT_SRC } from "../../assets/mascot";
import styles from "./EmptyState.module.less";

interface HappyclawEmptyMascotProps {
  className?: string;
  /** Square edge in px; default 160. */
  size?: number;
}

/**
 * Octop empty-state mascot image with shared sizing.
 * Use inside custom empty UIs or pass as ``EmptyState`` icon /
 * antd ``Empty`` ``image``.
 */
export function HappyclawEmptyMascot({
  className,
  size = 160,
}: HappyclawEmptyMascotProps) {
  return (
    <img
      src={HAPPYCLAW_EMPTY_MASCOT_SRC}
      alt=""
      draggable={false}
      className={cx(styles.mascot, className)}
      style={size === 160 ? undefined : { width: size, height: size }}
    />
  );
}
