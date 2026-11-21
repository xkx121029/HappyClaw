import type { HTMLAttributes } from "react";

import { cn } from "@/lib/cn";

export function Separator({
  orientation = "horizontal",
  className,
  ...props
}: HTMLAttributes<HTMLDivElement> & {
  orientation?: "horizontal" | "vertical";
}) {
  return (
    <div
      role="separator"
      aria-orientation={orientation}
      className={cn(
        "shrink-0 bg-line-subtle",
        orientation === "horizontal" ? "h-px w-full" : "h-full w-px",
        className,
      )}
      {...props}
    />
  );
}

export function Kbd({ children }: { children: string }) {
  return (
    <kbd className="inline-flex h-5 min-w-5 items-center justify-center rounded-xs border border-line bg-sunken px-1.5 font-mono text-2xs text-fg-muted">
      {children}
    </kbd>
  );
}
