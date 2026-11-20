import { useCallback, useEffect, useRef } from "react";
import cx from "classnames";
import styles from "../solo.module.less";

export type SoloMenuItem =
  | {
      key: string;
      label: string;
      hint?: string;
      icon?: React.ReactNode;
      active?: boolean;
    }
  | { type: "separator" };

interface SoloMenuProps {
  items: SoloMenuItem[];
  onSelect: (key: string) => void;
  onClose: () => void;
  /** 定位由调用方的 `.menuAnchor` + 这里的修饰类共同决定。 */
  className?: string;
  ariaLabel?: string;
}

/**
 * 参照稿 `.menu / .tmi / .tsep` 的轻量下拉。
 *
 * 不用 AntD Dropdown：参照稿的菜单是 card 底、1px 边、radius 8、padding 6，
 * 自带 shadow 与 33px 行高，AntD 的弹层结构对不上这些度量。
 */
export default function SoloMenu({
  items,
  onSelect,
  onClose,
  className,
  ariaLabel,
}: SoloMenuProps) {
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handlePointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) onClose();
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [onClose]);

  const handleClick = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      event.stopPropagation();
    },
    [],
  );

  return (
    <div
      ref={rootRef}
      role="menu"
      aria-label={ariaLabel}
      className={cx(styles.menu, className)}
      onClick={handleClick}
    >
      {items.map((item, index) =>
        "type" in item ? (
          <div key={`sep-${index}`} className={styles.tsep} role="separator" />
        ) : (
          <button
            key={item.key || `item-${index}`}
            type="button"
            role="menuitem"
            className={cx(styles.tmi, item.active && styles.tmiActive)}
            onClick={() => onSelect(item.key)}
          >
            {item.icon}
            <span>{item.label}</span>
            {item.hint ? <span className={styles.tmiHint}>{item.hint}</span> : null}
          </button>
        ),
      )}
    </div>
  );
}
