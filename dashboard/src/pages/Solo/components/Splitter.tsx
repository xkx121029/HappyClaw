import { useCallback, useRef, useState } from "react";
import cx from "classnames";
import styles from "../solo.module.less";

interface SplitterProps {
  /** vertical = 左右分栏（横向拖动），horizontal = 上下分栏（纵向拖动）。 */
  orientation: "vertical" | "horizontal";
  /** 每次指针移动的增量（像素，向右/向下为正）。 */
  onDelta: (delta: number) => void;
  label: string;
}

const KEYBOARD_STEP = 16;

export default function Splitter({
  orientation,
  onDelta,
  label,
}: SplitterProps) {
  const [dragging, setDragging] = useState(false);
  const lastPos = useRef(0);

  const handlePointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      // preventDefault 会阻止浏览器默认聚焦，键盘调节（Arrow 键）仍要可用。
      event.preventDefault();
      event.currentTarget.focus();
      event.currentTarget.setPointerCapture(event.pointerId);
      lastPos.current =
        orientation === "vertical" ? event.clientX : event.clientY;
      setDragging(true);
    },
    [orientation],
  );

  const handlePointerMove = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (!dragging) return;
      const pos = orientation === "vertical" ? event.clientX : event.clientY;
      const delta = pos - lastPos.current;
      lastPos.current = pos;
      if (delta !== 0) onDelta(delta);
    },
    [dragging, onDelta, orientation],
  );

  const stopDragging = useCallback(() => setDragging(false), []);

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      const dec = orientation === "vertical" ? "ArrowLeft" : "ArrowUp";
      const inc = orientation === "vertical" ? "ArrowRight" : "ArrowDown";
      if (event.key === dec) {
        event.preventDefault();
        onDelta(-KEYBOARD_STEP);
      } else if (event.key === inc) {
        event.preventDefault();
        onDelta(KEYBOARD_STEP);
      }
    },
    [onDelta, orientation],
  );

  return (
    <div
      role="separator"
      tabIndex={0}
      aria-label={label}
      aria-orientation={orientation}
      className={cx(
        styles.splitter,
        orientation === "vertical" ? styles.splitterV : styles.splitterH,
        dragging && styles.splitterActive,
      )}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={stopDragging}
      onPointerCancel={stopDragging}
      onKeyDown={handleKeyDown}
    >
      <span className={styles.splitterGrip} />
    </div>
  );
}
