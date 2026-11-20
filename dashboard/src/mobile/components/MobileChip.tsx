import type { ReactNode } from "react";
import cx from "classnames";

type ChipTone = "default" | "accent" | "warn" | "ok" | "danger";

export function MobileChip({
  children,
  tone = "default",
}: {
  children: ReactNode;
  tone?: ChipTone;
}) {
  return (
    <span className={cx("m-chip", tone !== "default" && `m-chip--${tone}`)}>
      {children}
    </span>
  );
}

export function MobileDot({ tone }: { tone?: "ok" | "warn" | "danger" }) {
  return <span className={cx("m-dot", tone && `m-dot--${tone}`)} />;
}
