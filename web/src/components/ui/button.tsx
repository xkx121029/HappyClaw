import { Loader2 } from "lucide-react";
import {
  cloneElement,
  forwardRef,
  isValidElement,
  type ButtonHTMLAttributes,
  type ReactElement,
  type ReactNode,
} from "react";

import { cn } from "@/lib/cn";

export type ButtonVariant =
  | "primary"
  | "secondary"
  | "ghost"
  | "subtle"
  | "danger"
  | "link";
export type ButtonSize = "xs" | "sm" | "md" | "lg" | "icon" | "icon-sm";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  leadingIcon?: ReactNode;
  trailingIcon?: ReactNode;
  block?: boolean;
  /** Render the single child element (e.g. a router link) with button styling. */
  asChild?: boolean;
}

const base =
  "relative inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md font-medium " +
  "select-none transition-[background-color,color,border-color,box-shadow,transform] " +
  "disabled:pointer-events-none disabled:opacity-50 " +
  "active:translate-y-px [&_svg]:shrink-0";

const variants: Record<ButtonVariant, string> = {
  primary:
    "bg-accent text-fg-onaccent shadow-xs hover:bg-accent-hover active:bg-accent-active",
  secondary:
    "bg-surface text-fg border border-line shadow-xs hover:bg-hover hover:border-line-strong",
  ghost: "text-fg-muted hover:bg-hover hover:text-fg",
  subtle: "bg-sunken text-fg-muted hover:bg-active hover:text-fg",
  danger:
    "bg-danger-soft text-danger border border-transparent hover:border-danger/40 hover:bg-danger/20",
  link: "text-accent-fg underline-offset-4 hover:underline px-0 shadow-none active:translate-y-0",
};

const sizes: Record<ButtonSize, string> = {
  xs: "h-6 px-2 text-2xs [&_svg]:size-3 rounded-sm",
  sm: "h-8 px-3 text-xs [&_svg]:size-3.5",
  md: "h-9 px-3.5 text-base [&_svg]:size-4",
  lg: "h-11 px-5 text-md [&_svg]:size-4",
  icon: "size-9 [&_svg]:size-4",
  "icon-sm": "size-8 [&_svg]:size-3.5",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  function Button(
    {
      className,
      variant = "secondary",
      size = "md",
      loading = false,
      leadingIcon,
      trailingIcon,
      block = false,
      asChild = false,
      children,
      disabled,
      type = "button",
      ...props
    },
    ref,
  ) {
    const classes = cn(
      base,
      variants[variant],
      sizes[size],
      block && "w-full",
      disabled && "pointer-events-none opacity-50",
      className,
    );

    const content = (
      <>
        {loading ? (
          <Loader2 aria-hidden className="animate-[hc-spin_0.7s_linear_infinite]" />
        ) : (
          leadingIcon
        )}
        {children}
        {trailingIcon}
      </>
    );

    if (asChild && isValidElement(children)) {
      const child = children as ReactElement<{ className?: string }>;
      return cloneElement(
        child,
        { className: cn(classes, child.props.className) },
        content,
      );
    }

    return (
      <button
        ref={ref}
        type={type}
        data-slot="button"
        data-variant={variant}
        data-size={size}
        disabled={disabled || loading}
        aria-busy={loading || undefined}
        className={classes}
        {...props}
      >
        {content}
      </button>
    );
  },
);
