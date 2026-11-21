import type { HTMLAttributes, ReactNode } from "react";

import { cn } from "@/lib/cn";

export function Card({
  className,
  interactive = false,
  ...props
}: HTMLAttributes<HTMLDivElement> & { interactive?: boolean }) {
  return (
    <div
      data-slot="card"
      className={cn(
        "rounded-lg border border-line bg-surface shadow-xs",
        interactive &&
          "cursor-pointer transition-[border-color,background-color,box-shadow] hover:border-line-strong hover:bg-raised hover:shadow-sm",
        className,
      )}
      {...props}
    />
  );
}

export function CardHeader({
  title,
  description,
  actions,
  className,
  children,
}: {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
  children?: ReactNode;
}) {
  return (
    <div
      className={cn(
        "flex items-start justify-between gap-4 border-b border-line-subtle px-4 py-3",
        className,
      )}
    >
      <div className="grid gap-0.5">
        {title ? (
          <h3 className="text-sm font-semibold text-fg">{title}</h3>
        ) : null}
        {description ? (
          <p className="text-xs text-fg-subtle">{description}</p>
        ) : null}
        {children}
      </div>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </div>
  );
}

export function CardBody({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-4", className)} {...props} />;
}

export function CardFooter({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "flex items-center justify-end gap-2 border-t border-line-subtle px-4 py-3",
        className,
      )}
      {...props}
    />
  );
}

/** Compact KPI tile used on dashboards and the settings overview. */
export function Stat({
  label,
  value,
  delta,
  icon,
}: {
  label: ReactNode;
  value: ReactNode;
  delta?: { value: string; tone: "up" | "down" | "flat" };
  icon?: ReactNode;
}) {
  const deltaTone =
    delta?.tone === "up"
      ? "text-success"
      : delta?.tone === "down"
        ? "text-danger"
        : "text-fg-subtle";
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between gap-2 text-fg-subtle">
        <span className="text-xs">{label}</span>
        {icon ? <span className="[&_svg]:size-4">{icon}</span> : null}
      </div>
      <p className="mt-2 font-mono text-2xl font-semibold tracking-tight text-fg">
        {value}
      </p>
      {delta ? (
        <p className={cn("mt-1 text-2xs", deltaTone)}>{delta.value}</p>
      ) : null}
    </Card>
  );
}
