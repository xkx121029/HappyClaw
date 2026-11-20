import type { CSSProperties } from "react";
import cx from "classnames";

interface MobileAvatarProps {
  name: string;
  src?: string | null;
  color?: string | null;
  size?: number;
  square?: boolean;
  className?: string;
}

/** Round (or squircle) avatar with a deterministic initial fallback. */
export function MobileAvatar({
  name,
  src,
  color,
  size = 40,
  square = false,
  className,
}: MobileAvatarProps) {
  const initial = (name || "?").trim().slice(0, 1).toUpperCase();
  const style: CSSProperties = {
    width: size,
    height: size,
    fontSize: Math.max(12, Math.round(size * 0.42)),
    background: color || undefined,
  };
  return (
    <span
      className={cx("m-avatar", square && "m-avatar--square", className)}
      style={style}
      aria-hidden={Boolean(src)}
    >
      {src ? <img src={src} alt={name} /> : initial}
    </span>
  );
}
