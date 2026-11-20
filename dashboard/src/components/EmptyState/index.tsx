import { Button } from "antd";
import { Inbox, AlertCircle } from "lucide-react";
import type { ReactNode } from "react";
import { OctopEmptyMascot } from "./OctopEmptyMascot";

interface EmptyStateProps {
  /** Icon element. Overrides the default variant icon. */
  icon?: ReactNode;
  /** Main title */
  title?: string;
  /** Descriptive subtitle */
  description?: string;
  /** Optional action button text */
  actionLabel?: string;
  /** Optional action button callback */
  onAction?: () => void;
  /**
   * A secondary escape hatch next to the primary action (e.g. "导入"),
   * for empties where more than one next step is legitimate.
   */
  secondaryAction?: ReactNode;
  /**
   * Visual variant:
   * - empty: inbox icon
   * - error: alert icon
   * - mascot: shared Octop empty mascot (prefer for list/detail empty shells)
   */
  variant?: "empty" | "error" | "mascot";
  /**
   * Set when the empty state is genuinely informational and there is nothing
   * the user can do (e.g. "no notifications"). Keeps the actionable-empties
   * rule honest instead of silently omitting the button.
   */
  passive?: boolean;
  className?: string;
}

/**
 * Generic empty/error state placeholder for list and table pages.
 * Provides a consistent visual treatment across the app.
 */
export function EmptyState({
  icon,
  title,
  description,
  actionLabel,
  onAction,
  secondaryAction,
  variant = "empty",
  passive = false,
  className,
}: EmptyStateProps) {
  const defaultIcon =
    variant === "error" ? (
      <AlertCircle
        size={40}
        strokeWidth={1.2}
        style={{ color: "var(--fn-color-danger)" }}
      />
    ) : variant === "mascot" ? (
      <OctopEmptyMascot />
    ) : (
      <Inbox
        size={40}
        strokeWidth={1.2}
        style={{ color: "var(--fn-text-quaternary, #bfbfbf)" }}
      />
    );

  return (
    <div
      className={className}
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "var(--fn-space-3xl) var(--fn-space-xl)",
        gap: "var(--fn-space-xs)",
        textAlign: "center",
      }}
    >
      <div style={{ marginBottom: "var(--fn-space-xs)" }}>
        {icon ?? defaultIcon}
      </div>
      {title && (
        <div
          style={{
            fontSize: "var(--fn-text-md)",
            fontWeight: "var(--fn-weight-semibold)",
            lineHeight: "var(--fn-leading-tight)",
            color: "var(--fn-text-primary)",
          }}
        >
          {title}
        </div>
      )}
      {description && (
        <div
          style={{
            fontSize: "var(--fn-text-xs)",
            color: "var(--fn-text-tertiary)",
            maxWidth: 320,
            lineHeight: "var(--fn-leading-normal)",
          }}
        >
          {description}
        </div>
      )}
      {!passive && (actionLabel && onAction) && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "var(--fn-space-xs)",
            marginTop: "var(--fn-space-sm)",
          }}
        >
          <Button type="primary" onClick={onAction}>
            {actionLabel}
          </Button>
          {secondaryAction}
        </div>
      )}
      {!passive && !actionLabel && secondaryAction && (
        <div style={{ marginTop: "var(--fn-space-sm)" }}>{secondaryAction}</div>
      )}
    </div>
  );
}

export { OctopEmptyMascot } from "./OctopEmptyMascot";
