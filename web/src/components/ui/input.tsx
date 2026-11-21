import { forwardRef, type InputHTMLAttributes, type ReactNode } from "react";

import { cn } from "@/lib/cn";

const control =
  "w-full rounded-md border border-line bg-surface px-3 text-base text-fg shadow-xs " +
  "transition-[border-color,box-shadow,background-color] placeholder:text-fg-subtle " +
  "hover:border-line-strong disabled:cursor-not-allowed disabled:bg-sunken disabled:text-fg-disabled " +
  "aria-[invalid=true]:border-danger focus-visible:outline-none focus-visible:border-line-focus " +
  "focus-visible:shadow-glow";

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  leadingIcon?: ReactNode;
  trailingSlot?: ReactNode;
  invalid?: boolean;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  { className, leadingIcon, trailingSlot, invalid, ...props },
  ref,
) {
  if (!leadingIcon && !trailingSlot) {
    return (
      <input
        ref={ref}
        data-slot="input"
        aria-invalid={invalid || undefined}
        className={cn(control, "h-9", className)}
        {...props}
      />
    );
  }
  return (
    <div className={cn("relative flex items-center", className)}>
      {leadingIcon ? (
        <span className="pointer-events-none absolute left-3 flex text-fg-subtle [&_svg]:size-4">
          {leadingIcon}
        </span>
      ) : null}
      <input
        ref={ref}
        data-slot="input"
        aria-invalid={invalid || undefined}
        className={cn(
          control,
          "h-9",
          leadingIcon && "pl-9",
          trailingSlot && "pr-9",
        )}
        {...props}
      />
      {trailingSlot ? (
        <span className="absolute right-2 flex items-center">
          {trailingSlot}
        </span>
      ) : null}
    </div>
  );
});

export const Textarea = forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement> & { invalid?: boolean }
>(function Textarea({ className, invalid, ...props }, ref) {
  return (
    <textarea
      ref={ref}
      data-slot="textarea"
      aria-invalid={invalid || undefined}
      className={cn(control, "min-h-20 resize-y py-2 leading-normal", className)}
      {...props}
    />
  );
});
