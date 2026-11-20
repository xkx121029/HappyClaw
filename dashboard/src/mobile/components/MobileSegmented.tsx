import type { ReactNode } from "react";
import cx from "classnames";

interface SegmentOption<T extends string> {
  value: T;
  label: ReactNode;
}

interface MobileSegmentedProps<T extends string> {
  options: SegmentOption<T>[];
  value: T;
  onChange: (value: T) => void;
}

export function MobileSegmented<T extends string>({
  options,
  value,
  onChange,
}: MobileSegmentedProps<T>) {
  return (
    <div className="m-seg" role="tablist">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="tab"
          aria-selected={option.value === value}
          className={cx("m-seg-item", option.value === value && "is-active")}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
