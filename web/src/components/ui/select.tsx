import { ChevronDown } from "lucide-react";
import {
  forwardRef,
  type SelectHTMLAttributes,
  type ReactNode,
} from "react";

import { cn } from "@/lib/cn";

export interface SelectOption {
  value: string;
  label: ReactNode;
  disabled?: boolean;
}

export interface SelectProps
  extends Omit<SelectHTMLAttributes<HTMLSelectElement>, "children"> {
  options: SelectOption[];
  invalid?: boolean;
}

/**
 * A native <select>: it keeps platform keyboard behaviour, mobile pickers and
 * form participation, with the design system's chrome on top.
 */
export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  function Select({ className, options, invalid, ...props }, ref) {
    return (
      <div className={cn("relative", className)}>
        <select
          ref={ref}
          data-slot="select"
          aria-invalid={invalid || undefined}
          className={cn(
            "h-9 w-full appearance-none rounded-md border border-line bg-surface px-3 pr-8 text-base text-fg shadow-xs",
            "transition-[border-color,box-shadow] hover:border-line-strong",
            "focus-visible:border-line-focus focus-visible:outline-none focus-visible:shadow-glow",
            "disabled:cursor-not-allowed disabled:bg-sunken disabled:text-fg-disabled",
            "aria-[invalid=true]:border-danger",
          )}
          {...props}
        >
          {options.map((option) => (
            <option
              key={option.value}
              value={option.value}
              disabled={option.disabled}
            >
              {option.label}
            </option>
          ))}
        </select>
        <ChevronDown
          aria-hidden
          className="pointer-events-none absolute right-2.5 top-1/2 size-4 -translate-y-1/2 text-fg-subtle"
        />
      </div>
    );
  },
);
