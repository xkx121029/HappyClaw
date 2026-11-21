import { cn } from "@/lib/cn";

export function Progress({
  value,
  max = 100,
  tone = "accent",
  className,
  label,
}: {
  value: number;
  max?: number;
  tone?: "accent" | "success" | "warning" | "danger";
  className?: string;
  label?: string;
}) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  const fill =
    tone === "success"
      ? "bg-success"
      : tone === "warning"
        ? "bg-warning"
        : tone === "danger"
          ? "bg-danger"
          : "bg-accent";
  return (
    <div
      role="progressbar"
      aria-valuenow={Math.round(value)}
      aria-valuemin={0}
      aria-valuemax={max}
      aria-label={label}
      className={cn(
        "h-1.5 w-full overflow-hidden rounded-full bg-sunken",
        className,
      )}
    >
      <div
        className={cn(
          "h-full rounded-full transition-[width] duration-(--hc-duration-slow) ease-out",
          fill,
        )}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}
