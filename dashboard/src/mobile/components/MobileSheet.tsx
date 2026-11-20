import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import cx from "classnames";
import { useTranslation } from "react-i18next";

import { useFocusTrap } from "../../hooks/useFocusTrap";
import { MobileIcon } from "./MobileIcon";

interface MobileSheetProps {
  open: boolean;
  title?: ReactNode;
  onClose: () => void;
  children: ReactNode;
  height?: "auto" | "half" | "full";
}

/**
 * Bottom sheet with a grab handle, drag-to-dismiss and Esc support. Portaled to
 * ``body`` so it is never clipped by the app shell.
 */
export function MobileSheet({
  open,
  title,
  onClose,
  children,
  height = "auto",
}: MobileSheetProps) {
  const { t } = useTranslation();
  const dragStart = useRef<number | null>(null);
  // One node, two consumers: the focus trap and the drag handler.
  const panelRef = useFocusTrap<HTMLDivElement>(open, onClose);

  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [open]);

  if (!open) return null;

  const onPointerDown = (event: React.PointerEvent) => {
    dragStart.current = event.clientY;
    (event.target as HTMLElement).setPointerCapture?.(event.pointerId);
  };
  const onPointerMove = (event: React.PointerEvent) => {
    if (dragStart.current === null || !panelRef.current) return;
    const dy = Math.max(0, event.clientY - dragStart.current);
    panelRef.current.style.transform = `translateY(${dy}px)`;
    panelRef.current.style.transition = "none";
  };
  const onPointerUp = (event: React.PointerEvent) => {
    const start = dragStart.current;
    dragStart.current = null;
    if (!panelRef.current) return;
    const dy = start === null ? 0 : Math.max(0, event.clientY - start);
    panelRef.current.style.transition = "";
    panelRef.current.style.transform = "";
    if (dy > 80) onClose();
  };

  return createPortal(
    <div
      className="m-portal m-sheet-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className={cx(
          "m-sheet",
          height === "half" && "m-sheet--half",
          height === "full" && "m-sheet--full",
        )}
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        tabIndex={-1}
      >
        <div
          className="m-sheet-grab"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
        />
        {title ? (
          <div className="m-sheet-head">
            <div className="m-sheet-title">{title}</div>
            <button
              type="button"
              className="m-iconbtn"
              aria-label={t("common.close", "关闭")}
              onClick={onClose}
            >
              <MobileIcon name="close" size={20} />
            </button>
          </div>
        ) : null}
        <div className="m-sheet-body">{children}</div>
      </div>
    </div>,
    document.body,
  );
}
