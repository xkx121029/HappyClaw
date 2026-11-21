import { X } from "lucide-react";
import {
  useCallback,
  useEffect,
  useRef,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";

import { cn } from "@/lib/cn";

import { Button } from "./button";

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])';

export interface DialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
  size?: "sm" | "md" | "lg";
  closeLabel?: string;
}

/**
 * Modal dialog on the native <dialog> element, which gives us the top layer,
 * Escape handling and focus containment from the platform instead of a focus
 * trap we would have to maintain.
 */
export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  size = "md",
  closeLabel = "Close",
}: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (open && !node.open) {
      node.showModal();
      const first = bodyRef.current?.querySelector<HTMLElement>(FOCUSABLE);
      first?.focus();
    } else if (!open && node.open) {
      node.close();
    }
  }, [open]);

  const onCancel = useCallback(
    (event: React.SyntheticEvent<HTMLDialogElement>) => {
      event.preventDefault();
      onOpenChange(false);
    },
    [onOpenChange],
  );

  const onClickBackdrop = (event: React.MouseEvent<HTMLDialogElement>) => {
    if (event.target === ref.current) onOpenChange(false);
  };

  if (typeof document === "undefined") return null;

  return createPortal(
    <dialog
      ref={ref}
      onCancel={onCancel}
      onClick={onClickBackdrop}
      className={cn(
        "hc-dialog m-auto w-[calc(100vw-2rem)] rounded-xl border border-line bg-surface p-0 text-fg shadow-overlay",
        size === "sm" && "max-w-96",
        size === "md" && "max-w-lg",
        size === "lg" && "max-w-2xl",
        "backdrop:bg-overlay backdrop:backdrop-blur-[2px]",
        "animate-[hc-pop-in_var(--hc-duration-base)_var(--hc-ease-out)]",
      )}
    >
      <header className="flex items-start justify-between gap-4 border-b border-line-subtle px-4 py-3">
        <div className="grid gap-0.5">
          <h2 className="text-md font-semibold">{title}</h2>
          {description ? (
            <p className="text-xs text-fg-subtle">{description}</p>
          ) : null}
        </div>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={closeLabel}
          onClick={() => onOpenChange(false)}
        >
          <X />
        </Button>
      </header>
      <div ref={bodyRef} className="max-h-[70vh] overflow-y-auto px-4 py-4">
        {children}
      </div>
      {footer ? (
        <footer className="flex items-center justify-end gap-2 border-t border-line-subtle px-4 py-3">
          {footer}
        </footer>
      ) : null}
    </dialog>,
    document.body,
  );
}
