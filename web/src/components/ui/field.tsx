import { useId, type ReactNode } from "react";

import { cn } from "@/lib/cn";

export interface FieldProps {
  label?: ReactNode;
  hint?: ReactNode;
  error?: ReactNode;
  required?: boolean;
  htmlFor?: string;
  className?: string;
  children: ReactNode;
}

/**
 * One label/hint/error frame for every control, so form rows keep the same
 * rhythm no matter which control they wrap.
 */
export function Field({
  label,
  hint,
  error,
  required,
  htmlFor,
  className,
  children,
}: FieldProps) {
  return (
    <div className={cn("grid gap-1.5", className)}>
      {label ? (
        <label
          htmlFor={htmlFor}
          className="text-xs font-medium text-fg-muted"
        >
          {label}
          {required ? (
            <span aria-hidden className="ml-0.5 text-danger">
              *
            </span>
          ) : null}
        </label>
      ) : null}
      {children}
      {error ? (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
      ) : hint ? (
        <p className="text-xs text-fg-subtle">{hint}</p>
      ) : null}
    </div>
  );
}

/** Groups fields under one heading — used by the settings page sections. */
export function FieldGroup({
  title,
  description,
  children,
  className,
}: {
  title?: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  const id = useId();
  return (
    <section className={cn("grid gap-4", className)} aria-labelledby={id}>
      {title ? (
        <div className="grid gap-1">
          <h3 id={id} className="text-sm font-semibold text-fg">
            {title}
          </h3>
          {description ? (
            <p className="text-xs text-fg-subtle">{description}</p>
          ) : null}
        </div>
      ) : null}
      {children}
    </section>
  );
}
