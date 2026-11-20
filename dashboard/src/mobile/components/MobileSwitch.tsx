import cx from "classnames";

interface MobileSwitchProps {
  checked: boolean;
  onChange?: (checked: boolean) => void;
  disabled?: boolean;
  label?: string;
}

export function MobileSwitch({
  checked,
  onChange,
  disabled = false,
  label,
}: MobileSwitchProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled || !onChange}
      className={cx("m-switch", checked && "is-on")}
      onClick={() => onChange?.(!checked)}
    />
  );
}
