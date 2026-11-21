import {
  AlertTriangle,
  CheckCircle2,
  Info,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

const tones: Record<
  AlertTone,
  { wrap: string; icon: LucideIcon; iconClass: string }
> = {
  info: { wrap: "bg-info-soft text-fg", icon: Info, iconClass: "text-info" },
  success: {
    wrap: "bg-success-soft text-fg",
    icon: CheckCircle2,
    iconClass: "text-success",
  },
  warning: {
    wrap: "bg-warning-soft text-fg",
    icon: AlertTriangle,
    iconClass: "text-warning",
  },
  danger: {
    wrap: "bg-danger-soft text-fg",
    icon: XCircle,
    iconClass: "text-danger",
  },
};

export type AlertTone = "info" | "success" | "warning" | "danger";

export function Alert({
  tone = "info",
  title,
  children,
  action,
  className,
}: {
  tone?: AlertTone;
  title?: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  const { wrap, icon: Icon, iconClass } = tones[tone];
  return (
    <div
      role={tone === "danger" ? "alert" : "status"}
      className={cn(
        "flex gap-2.5 rounded-md px-3 py-2.5 text-sm",
        wrap,
        className,
      )}
    >
      <Icon aria-hidden className={cn("mt-0.5 size-4 shrink-0", iconClass)} />
      <div className="min-w-0 flex-1">
        {title ? <p className="font-medium">{title}</p> : null}
        {children ? (
          <div className="text-xs text-fg-muted [&:not(:first-child)]:mt-0.5">
            {children}
          </div>
        ) : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}
