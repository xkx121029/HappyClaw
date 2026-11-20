import cx from "classnames";

import { Mascot } from "../Mascot";
import type { MascotState } from "../Mascot";
import styles from "./EmptyState.module.less";

interface OctopEmptyMascotProps {
  className?: string;
  /** Square edge in px; default 120. */
  size?: number;
  /** Expression; empty states default to a calm idle pose. */
  state?: MascotState;
}

/**
 * Octop empty-state mascot, rendered by the shared character engine.
 * Use inside custom empty UIs or pass as ``EmptyState`` icon /
 * antd ``Empty`` ``image``.
 */
export function OctopEmptyMascot({
  className,
  size = 120,
  state = "idle",
}: OctopEmptyMascotProps) {
  return (
    <Mascot
      size={size}
      state={state}
      className={cx(styles.mascot, className)}
    />
  );
}
