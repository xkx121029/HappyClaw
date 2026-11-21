import { cn } from "@/lib/cn";

const sizes = {
  xs: "size-3 border",
  sm: "size-4 border-[1.5px]",
  md: "size-5 border-2",
  lg: "size-7 border-[3px]",
} as const;

export interface SpinnerProps {
  size?: keyof typeof sizes;
  className?: string;
  label?: string;
}

export function Spinner({ size = "md", className, label }: SpinnerProps) {
  return (
    <span
      role="status"
      aria-label={label}
      className={cn(
        "inline-block animate-[hc-spin_0.7s_linear_infinite] rounded-full border-line-strong border-t-accent",
        sizes[size],
        className,
      )}
    />
  );
}

/** Full-panel loading state — keeps layout stable while data resolves. */
export function LoadingBlock({
  label,
  className,
}: {
  label?: string;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex min-h-40 flex-col items-center justify-center gap-3 text-fg-subtle",
        className,
      )}
    >
      <Spinner label={label} />
      {label ? <p className="text-xs">{label}</p> : null}
    </div>
  );
}
