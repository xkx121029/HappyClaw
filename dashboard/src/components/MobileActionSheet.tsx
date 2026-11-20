import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import cx from "classnames";
import styles from "./MobileActionSheet.module.less";

export interface MobileActionSheetItem {
  key: string;
  label: string;
  icon?: ReactNode;
  /** Right-aligned extra information, e.g. a count. */
  meta?: ReactNode;
  hint?: string;
  disabled?: boolean;
  danger?: boolean;
  onSelect: () => void;
}

interface MobileActionSheetProps {
  open: boolean;
  title?: string;
  subtitle?: string;
  items: MobileActionSheetItem[];
  onClose: () => void;
}

const DISMISS_AFTER_DRAG_PX = 90;

/**
 * Phone bottom sheet for secondary actions.
 *
 * Owns the behaviours a sheet needs to feel native: portal outside the page
 * scroll container, backdrop + Escape + swipe-down dismissal, safe-area
 * padding, and 48px rows so every action is comfortably tappable.
 */
export default function MobileActionSheet({
  open,
  title,
  subtitle,
  items,
  onClose,
}: MobileActionSheetProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const restoreFocusRef = useRef<Element | null>(null);
  const [dragY, setDragY] = useState(0);
  const drag = useRef({ startY: 0, active: false });

  const handleClose = useCallback(() => {
    setDragY(0);
    onClose();
  }, [onClose]);

  useEffect(() => {
    if (!open) return;
    restoreFocusRef.current = document.activeElement;
    panelRef.current?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !event.defaultPrevented) {
        event.preventDefault();
        handleClose();
      }
    };
    window.addEventListener("keydown", onKeyDown);

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    return () => {
      window.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
      const target = restoreFocusRef.current;
      if (target instanceof HTMLElement) target.focus();
    };
  }, [handleClose, open]);

  if (!open) return null;

  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    drag.current = { startY: event.clientY, active: true };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!drag.current.active) return;
    const dy = Math.max(0, event.clientY - drag.current.startY);
    setDragY(dy);
  };

  const endDrag = () => {
    if (!drag.current.active) return;
    drag.current.active = false;
    if (dragY > DISMISS_AFTER_DRAG_PX) {
      handleClose();
      return;
    }
    setDragY(0);
  };

  return createPortal(
    <div className={styles.root} role="presentation">
      <div
        className={styles.backdrop}
        role="presentation"
        style={{ opacity: Math.max(0.2, 1 - dragY / 320) }}
        onClick={handleClose}
      />
      <div
        ref={panelRef}
        className={cx(styles.panel, drag.current.active && styles.panelDragging)}
        style={{ transform: `translateY(${dragY}px)` }}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
      >
        <div
          className={styles.grabZone}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
        >
          <span className={styles.grabber} aria-hidden />
        </div>

        {title ? (
          <div className={styles.head}>
            <p className={styles.title}>{title}</p>
            {subtitle ? <p className={styles.subtitle}>{subtitle}</p> : null}
          </div>
        ) : null}

        <div className={styles.list}>
          {items.map((item) => (
            <button
              key={item.key}
              type="button"
              className={cx(styles.item, item.danger && styles.itemDanger)}
              disabled={item.disabled}
              onClick={() => {
                item.onSelect();
                handleClose();
              }}
            >
              {item.icon ? (
                <span className={styles.itemIcon} aria-hidden>
                  {item.icon}
                </span>
              ) : null}
              <span className={styles.itemText}>
                <span className={styles.itemLabel}>{item.label}</span>
                {item.hint ? (
                  <span className={styles.itemHint}>{item.hint}</span>
                ) : null}
              </span>
              {item.meta ? (
                <span className={styles.itemMeta}>{item.meta}</span>
              ) : null}
            </button>
          ))}
        </div>
        <div className={styles.safeBottom} />
      </div>
    </div>,
    document.body,
  );
}
