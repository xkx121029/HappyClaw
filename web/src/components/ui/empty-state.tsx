import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

export interface EmptyStateProps {
  icon?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  size?: "sm" | "md" | "lg";
  className?: string;
}

/**
 * The one way to say "nothing here yet". Every list, table and panel uses it so
 * empty screens look intentional instead of broken.
 */
export function EmptyState({
  icon,
  title,
  description,
  action,
  size = "md",
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 text-center",
        size === "sm" && "gap-2 py-8",
        size === "md" && "py-14",
        size === "lg" && "py-20",
        className,
      )}
    >
      {icon ? (
        <span
          className={cn(
            "flex items-center justify-center rounded-xl border border-line-subtle bg-sunken text-fg-subtle",
            size === "sm" ? "size-9 [&_svg]:size-4" : "size-12 [&_svg]:size-5",
          )}
        >
          {icon}
        </span>
      ) : null}
      <div className="grid max-w-80 gap-1">
        <p
          className={cn(
            "font-medium text-fg",
            size === "sm" ? "text-sm" : "text-md",
          )}
        >
          {title}
        </p>
        {description ? (
          <p className="text-xs leading-relaxed text-fg-subtle">
            {description}
          </p>
        ) : null}
      </div>
      {action ? <div className="mt-1">{action}</div> : null}
    </div>
  );
}
