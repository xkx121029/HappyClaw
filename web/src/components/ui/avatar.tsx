import { cn } from "@/lib/cn";

const sizes = {
  xs: "size-6 text-2xs",
  sm: "size-8 text-xs",
  md: "size-9 text-sm",
  lg: "size-11 text-md",
} as const;

/** Deterministic accent for a name, so the same agent always looks the same. */
function hueFor(seed: string): number {
  let hash = 0;
  for (let index = 0; index < seed.length; index += 1) {
    hash = (hash * 31 + seed.charCodeAt(index)) % 360;
  }
  return hash;
}

export interface AvatarProps {
  name: string;
  src?: string | null;
  size?: keyof typeof sizes;
  className?: string;
}

export function Avatar({ name, src, size = "sm", className }: AvatarProps) {
  const initials = name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part.charAt(0).toUpperCase())
    .join("");

  if (src) {
    return (
      <img
        src={src}
        alt={name}
        className={cn(
          "shrink-0 rounded-full object-cover ring-1 ring-line",
          sizes[size],
          className,
        )}
      />
    );
  }

  return (
    <span
      aria-hidden
      title={name}
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-full font-semibold ring-1 ring-inset ring-white/10",
        sizes[size],
        className,
      )}
      style={{
        backgroundColor: `hsl(${hueFor(name)} 55% 22%)`,
        color: `hsl(${hueFor(name)} 80% 82%)`,
      }}
    >
      {initials || "?"}
    </span>
  );
}
