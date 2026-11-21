import { useRef, type KeyboardEvent, type ReactNode } from "react";

import { cn } from "@/lib/cn";

export interface TabItem {
  value: string;
  label: ReactNode;
  badge?: ReactNode;
  disabled?: boolean;
}

export interface TabsProps {
  items: TabItem[];
  value: string;
  onValueChange: (value: string) => void;
  className?: string;
  /** `line` for page sections, `pill` for filters inside a toolbar. */
  variant?: "line" | "pill";
  ariaLabel?: string;
}

/**
 * Roving-tabindex tablist: arrow keys move focus, Home/End jump to the ends,
 * exactly what a native tab widget is expected to do.
 */
export function Tabs({
  items,
  value,
  onValueChange,
  className,
  variant = "line",
  ariaLabel,
}: TabsProps) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);

  const focusAt = (index: number) => {
    const enabled = items.filter((item) => !item.disabled);
    if (enabled.length === 0) return;
    const target = items.findIndex(
      (item) => item === enabled[Math.min(index, enabled.length - 1)],
    );
    refs.current[target]?.focus();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      event.preventDefault();
      focusAt(index + 1);
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      event.preventDefault();
      focusAt(index - 1);
    } else if (event.key === "Home") {
      event.preventDefault();
      focusAt(0);
    } else if (event.key === "End") {
      event.preventDefault();
      focusAt(items.length - 1);
    }
  };

  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className={cn(
        "flex items-center gap-1 overflow-x-auto",
        variant === "line" && "border-b border-line",
        variant === "pill" && "rounded-md bg-sunken p-0.5",
        className,
      )}
    >
      {items.map((item, index) => {
        const active = item.value === value;
        return (
          <button
            key={item.value}
            ref={(element) => {
              refs.current[index] = element;
            }}
            role="tab"
            type="button"
            aria-selected={active}
            tabIndex={active ? 0 : -1}
            disabled={item.disabled}
            onClick={() => onValueChange(item.value)}
            onKeyDown={(event) => onKeyDown(event, index)}
            className={cn(
              "relative inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap text-sm transition-colors",
              "disabled:cursor-not-allowed disabled:opacity-40",
              variant === "line" &&
                cn(
                  "-mb-px border-b-2 px-3 py-2",
                  active
                    ? "border-accent text-fg"
                    : "border-transparent text-fg-muted hover:text-fg",
                ),
              variant === "pill" &&
                cn(
                  "rounded-sm px-2.5 py-1",
                  active
                    ? "bg-surface text-fg shadow-xs"
                    : "text-fg-muted hover:text-fg",
                ),
            )}
          >
            {item.label}
            {item.badge}
          </button>
        );
      })}
    </div>
  );
}

export interface SegmentedOption<T extends string> {
  value: T;
  label: ReactNode;
  icon?: ReactNode;
}

export function Segmented<T extends string>({
  options,
  value,
  onChange,
  className,
  ariaLabel,
}: {
  options: SegmentedOption<T>[];
  value: T;
  onChange: (value: T) => void;
  className?: string;
  ariaLabel?: string;
}) {
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      className={cn(
        "inline-flex items-center gap-0.5 rounded-md border border-line bg-sunken p-0.5",
        className,
      )}
    >
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(option.value)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-sm px-2.5 py-1 text-xs font-medium transition-colors",
              "[&_svg]:size-3.5",
              active
                ? "bg-surface text-fg shadow-xs"
                : "text-fg-subtle hover:text-fg",
            )}
          >
            {option.icon}
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
