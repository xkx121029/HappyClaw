import type { ReactNode } from "react";
import cx from "classnames";

import { MobileIcon, type MobileIconName } from "./MobileIcon";

interface MobileListRowProps {
  title: ReactNode;
  subtitle?: ReactNode;
  icon?: MobileIconName;
  iconNode?: ReactNode;
  meta?: ReactNode;
  right?: ReactNode;
  chevron?: boolean;
  onClick?: () => void;
  className?: string;
}

export function MobileListRow({
  title,
  subtitle,
  icon,
  iconNode,
  meta,
  right,
  chevron = false,
  onClick,
  className,
}: MobileListRowProps) {
  const body = (
    <>
      {icon || iconNode ? (
        <span className="m-row-icon">
          {iconNode ?? <MobileIcon name={icon!} size={19} />}
        </span>
      ) : null}
      <span className="m-row-main">
        <span className="m-row-title">{title}</span>
        {subtitle ? <span className="m-row-sub">{subtitle}</span> : null}
      </span>
      {meta ? <span className="m-row-meta">{meta}</span> : null}
      {right}
      {chevron ? (
        <span className="m-row-chevron">
          <MobileIcon name="chevron" size={17} />
        </span>
      ) : null}
    </>
  );

  if (onClick) {
    return (
      <button
        type="button"
        className={cx("m-row", className)}
        onClick={onClick}
      >
        {body}
      </button>
    );
  }
  return <div className={cx("m-row", className)}>{body}</div>;
}
