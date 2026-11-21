import {
  cloneElement,
  isValidElement,
  useEffect,
  useId,
  useRef,
  useState,
  type ReactElement,
  type ReactNode,
} from "react";

import { cn } from "@/lib/cn";

export interface MenuItem {
  key: string;
  label: ReactNode;
  icon?: ReactNode;
  onSelect?: () => void;
  danger?: boolean;
  disabled?: boolean;
  /** Renders a separator above this item. */
  separated?: boolean;
}

export interface DropdownMenuProps {
  trigger: ReactElement<{ onClick?: () => void; "aria-expanded"?: boolean; "aria-controls"?: string }>;
  items: MenuItem[];
  align?: "start" | "end";
  className?: string;
}

export function DropdownMenu({
  trigger,
  items,
  align = "end",
  className,
}: DropdownMenuProps) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const first = root.current?.querySelector<HTMLElement>('[role="menuitem"]');
    first?.focus();
  }, [open]);

  const triggerNode = isValidElement(trigger)
    ? cloneElement(trigger, {
        onClick: () => setOpen((value) => !value),
        "aria-expanded": open,
        "aria-controls": open ? menuId : undefined,
      })
    : trigger;

  return (
    <div ref={root} className={cn("relative inline-flex", className)}>
      {triggerNode}
      {open ? (
        <div
          id={menuId}
          role="menu"
          className={cn(
            "absolute top-full z-(--hc-z-popover) mt-1 min-w-44 rounded-md border border-line bg-raised p-1 shadow-overlay",
            "animate-[hc-pop-in_var(--hc-duration-fast)_var(--hc-ease-out)]",
            align === "end" ? "right-0" : "left-0",
          )}
          onKeyDown={(event) => {
            if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
            event.preventDefault();
            const nodes = Array.from(
              root.current?.querySelectorAll<HTMLElement>(
                '[role="menuitem"]:not([disabled])',
              ) ?? [],
            );
            const index = nodes.indexOf(document.activeElement as HTMLElement);
            const next =
              event.key === "ArrowDown"
                ? (index + 1) % nodes.length
                : (index - 1 + nodes.length) % nodes.length;
            nodes[next]?.focus();
          }}
        >
          {items.map((item) => (
            <div key={item.key}>
              {item.separated ? (
                <div className="my-1 h-px bg-line-subtle" role="separator" />
              ) : null}
              <button
                type="button"
                role="menuitem"
                disabled={item.disabled}
                onClick={() => {
                  item.onSelect?.();
                  setOpen(false);
                }}
                className={cn(
                  "flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-sm transition-colors",
                  "disabled:cursor-not-allowed disabled:opacity-40",
                  "[&_svg]:size-3.5 [&_svg]:text-fg-subtle",
                  item.danger
                    ? "text-danger hover:bg-danger-soft [&_svg]:text-danger"
                    : "text-fg-muted hover:bg-hover hover:text-fg",
                )}
              >
                {item.icon}
                <span className="flex-1 truncate">{item.label}</span>
              </button>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
