import type { ReactNode } from "react";
import cx from "classnames";

interface MobileCardProps {
  children: ReactNode;
  onClick?: () => void;
  accent?: boolean;
  className?: string;
}

export function MobileCard({
  children,
  onClick,
  accent = false,
  className,
}: MobileCardProps) {
  const content = <>{children}</>;
  if (onClick) {
    return (
      <button
        type="button"
        className={cx("m-card is-tap", accent && "m-card--accent", className)}
        onClick={onClick}
      >
        {content}
      </button>
    );
  }
  return (
    <div className={cx("m-card", accent && "m-card--accent", className)}>
      {content}
    </div>
  );
}
