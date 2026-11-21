import { Check } from "lucide-react";
import {
  forwardRef,
  type InputHTMLAttributes,
  type ReactNode,
} from "react";

import { cn } from "@/lib/cn";

export interface CheckboxProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, "type"> {
  label?: ReactNode;
  description?: ReactNode;
}

export const Checkbox = forwardRef<HTMLInputElement, CheckboxProps>(
  function Checkbox({ className, label, description, id, ...props }, ref) {
    const control = (
      <span className="relative inline-flex size-4 shrink-0 items-center justify-center">
        <input
          ref={ref}
          id={id}
          type="checkbox"
          data-slot="checkbox"
          className={cn(
            "peer size-4 cursor-pointer appearance-none rounded-xs border border-line-strong bg-surface",
            "transition-[background-color,border-color] checked:border-accent checked:bg-accent",
            "disabled:cursor-not-allowed disabled:opacity-50",
            "focus-visible:outline-none focus-visible:shadow-glow",
            className,
          )}
          {...props}
        />
        <Check
          aria-hidden
          className="pointer-events-none absolute size-3 text-fg-onaccent opacity-0 peer-checked:opacity-100"
          strokeWidth={3}
        />
      </span>
    );

    if (!label && !description) return control;

    return (
      <label className="flex cursor-pointer items-start gap-2.5">
        <span className="pt-0.5">{control}</span>
        <span className="grid gap-0.5">
          {label ? <span className="text-base text-fg">{label}</span> : null}
          {description ? (
            <span className="text-xs text-fg-subtle">{description}</span>
          ) : null}
        </span>
      </label>
    );
  },
);

export interface SwitchProps {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  disabled?: boolean;
  label?: ReactNode;
  description?: ReactNode;
  id?: string;
  className?: string;
}

export function Switch({
  checked,
  onCheckedChange,
  disabled,
  label,
  description,
  id,
  className,
}: SwitchProps) {
  const control = (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onCheckedChange(!checked)}
      data-slot="switch"
      className={cn(
        "relative h-5 w-9 shrink-0 rounded-full border border-transparent transition-colors",
        "disabled:cursor-not-allowed disabled:opacity-50",
        checked ? "bg-accent" : "bg-line-strong",
      )}
    >
      <span
        className={cn(
          "absolute top-0.5 size-3.5 rounded-full bg-white shadow-xs transition-[left] duration-(--hc-duration-fast)",
          checked ? "left-[18px]" : "left-0.5",
        )}
      />
    </button>
  );

  if (!label) return <span className={className}>{control}</span>;

  return (
    <div className={cn("flex items-start justify-between gap-6", className)}>
      <label htmlFor={id} className="grid cursor-pointer gap-0.5">
        <span className="text-base text-fg">{label}</span>
        {description ? (
          <span className="text-xs text-fg-subtle">{description}</span>
        ) : null}
      </label>
      {control}
    </div>
  );
}
