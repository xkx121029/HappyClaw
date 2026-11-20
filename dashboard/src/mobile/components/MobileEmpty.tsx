import type { ReactNode } from "react";

import { MobileIcon, type MobileIconName } from "./MobileIcon";

interface MobileEmptyProps {
  icon?: MobileIconName;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  secondary?: ReactNode;
}

export function MobileEmpty({
  icon = "spark",
  title,
  description,
  action,
  secondary,
}: MobileEmptyProps) {
  return (
    <div className="m-empty">
      <span className="m-empty-icon">
        <MobileIcon name={icon} size={30} />
      </span>
      <div className="m-empty-title">{title}</div>
      {description ? <div className="m-empty-desc">{description}</div> : null}
      {action || secondary ? (
        <div className="m-empty-actions">
          {action}
          {secondary}
        </div>
      ) : null}
    </div>
  );
}
