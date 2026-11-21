import { useId, type ReactNode } from "react";

import { cn } from "@/lib/cn";

/**
 * CSS-only tooltip: hover and keyboard focus both reveal it, no portal and no
 * measurement. Fine for labels and shortcuts; use a popover for anything
 * interactive.
 */
export function Tooltip({
  content,
  children,
  side = "top",
  className,
}: {
  content: ReactNode;
  children: ReactNode;
  side?: "top" | "bottom" | "right";
  className?: string;
}) {
  const id = useId();
  return (
    <span className={cn("group/tooltip relative inline-flex", className)}>
      <span aria-describedby={id} className="inline-flex">
        {children}
      </span>
      <span
        role="tooltip"
        id={id}
        className={cn(
          "pointer-events-none absolute z-(--hc-z-popover) w-max max-w-56 rounded-sm border border-line bg-raised px-2 py-1 text-2xs text-fg shadow-md",
          "opacity-0 transition-opacity duration-(--hc-duration-fast) group-hover/tooltip:opacity-100 group-focus-within/tooltip:opacity-100",
          side === "top" && "bottom-full left-1/2 mb-1.5 -translate-x-1/2",
          side === "bottom" && "top-full left-1/2 mt-1.5 -translate-x-1/2",
          side === "right" && "left-full top-1/2 ml-2 -translate-y-1/2",
        )}
      >
        {content}
      </span>
    </span>
  );
}
