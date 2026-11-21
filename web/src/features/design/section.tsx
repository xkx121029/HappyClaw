import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

export function Section({
  id,
  title,
  description,
  children,
  className,
}: {
  id: string;
  title: string;
  description?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section id={id} className={cn("scroll-mt-16 border-t border-line-subtle pt-8", className)}>
      <header className="mb-4 grid gap-1">
        <h2 className="text-lg font-semibold text-fg">{title}</h2>
        {description ? (
          <p className="max-w-reading text-xs leading-relaxed text-fg-subtle">
            {description}
          </p>
        ) : null}
      </header>
      {children}
    </section>
  );
}

export function SubGrid({
  title,
  description,
  children,
  columns = 4,
}: {
  title?: string;
  description?: string;
  children: ReactNode;
  columns?: 2 | 3 | 4 | 5 | 6;
}) {
  return (
    <div className="grid gap-2">
      {title ? (
        <div className="grid gap-0.5">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-fg-subtle">
            {title}
          </h3>
          {description ? (
            <p className="text-2xs text-fg-subtle">{description}</p>
          ) : null}
        </div>
      ) : null}
      <div
        className={cn(
          "grid gap-2",
          columns === 2 && "grid-cols-2",
          columns === 3 && "grid-cols-2 md:grid-cols-3",
          columns === 4 && "grid-cols-2 md:grid-cols-4",
          columns === 5 && "grid-cols-2 md:grid-cols-5",
          columns === 6 && "grid-cols-3 md:grid-cols-6",
        )}
      >
        {children}
      </div>
    </div>
  );
}

/** A colour chip that shows the token name it is backed by. */
export function Swatch({
  name,
  variable,
  border = true,
  text,
}: {
  name: string;
  variable: string;
  border?: boolean;
  text?: string;
}) {
  return (
    <div className="overflow-hidden rounded-md border border-line-subtle bg-surface">
      <div
        className={cn("flex h-14 items-end p-2", border && "border-b border-line-subtle")}
        style={{ background: `var(${variable})` }}
      >
        <span
          className="rounded-xs bg-black/25 px-1 py-0.5 font-mono text-[10px] leading-tight text-white/80"
          style={text ? { color: text } : undefined}
        >
          {variable.replace("--hc-", "")}
        </span>
      </div>
      <p className="px-2 py-1.5 text-2xs text-fg-muted">{name}</p>
    </div>
  );
}
