/**
 * Shims for ``@deepseek-ai/dsh-client-ui-primitives``.
 *
 * That package ships inside the DSH desktop shell, so a bundle that
 * ``require``s it gets ``undefined`` in HappyClaw and explodes on first paint
 * (e.g. whale-girl's settings card reads ``primitives.Switch``). These are
 * native controls with the same prop names the bundles actually use, styled
 * from the host theme variables so they do not look foreign.
 */

import React from "react";

// Third-party bundles pass arbitrary DOM props through these shims, so the
// prop bag has to stay open; narrowing it would reject valid call sites.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyProps = Record<string, any>;

const border = "1px solid var(--dsw-alias-border-l2, rgba(0,0,0,0.16))";
const primary = "var(--dsw-alias-brand-primary, #2563eb)";

function split(props: AnyProps, keys: string[]): [AnyProps, AnyProps] {
  const rest: AnyProps = { ...props };
  const picked: AnyProps = {};
  for (const key of keys) {
    if (key in rest) {
      picked[key] = rest[key];
      delete rest[key];
    }
  }
  return [rest, picked];
}

export const Button = React.forwardRef<HTMLButtonElement, AnyProps>(function DshButton(props, ref) {
  const [rest, own] = split(props, ["variant", "size", "style", "children"]);
  const variant = String(own.variant || "outline");
  return (
    <button
      ref={ref}
      type="button"
      {...rest}
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 6,
        padding: own.size === "sm" ? "3px 9px" : "6px 14px",
        borderRadius: 8,
        border: variant === "primary" ? "none" : border,
        background: variant === "primary" ? primary : "transparent",
        color: variant === "primary" ? "#fff" : "inherit",
        fontSize: own.size === "sm" ? 12 : 13,
        lineHeight: 1.4,
        cursor: rest.disabled ? "not-allowed" : "pointer",
        opacity: rest.disabled ? 0.5 : 1,
        ...(own.style || {}),
      }}
    >
      {own.children}
    </button>
  );
});

export const Input = React.forwardRef<HTMLInputElement, AnyProps>(function DshInput(props, ref) {
  const [rest, own] = split(props, ["style"]);
  return (
    <input
      ref={ref}
      {...rest}
      style={{
        padding: "4px 8px",
        borderRadius: 6,
        border,
        background: "var(--dsw-alias-bg-l1, transparent)",
        color: "inherit",
        fontSize: "var(--fn-text-xs)",
        ...(own.style || {}),
      }}
    />
  );
});

export const Textarea = React.forwardRef<HTMLTextAreaElement, AnyProps>(
  function DshTextarea(props, ref) {
    const [rest, own] = split(props, ["style"]);
    return (
      <textarea
        ref={ref}
        {...rest}
        style={{
          padding: "6px 8px",
          borderRadius: 6,
          border,
          background: "var(--dsw-alias-bg-l1, transparent)",
          color: "inherit",
          fontSize: "var(--fn-text-xs)",
          ...(own.style || {}),
        }}
      />
    );
  },
);

export const Select = React.forwardRef<HTMLSelectElement, AnyProps>(function DshSelect(props, ref) {
  const [rest, own] = split(props, ["style", "children"]);
  return (
    <select
      ref={ref}
      {...rest}
      style={{
        padding: "4px 8px",
        borderRadius: 6,
        border,
        background: "var(--dsw-alias-bg-l1, transparent)",
        color: "inherit",
        fontSize: "var(--fn-text-xs)",
        ...(own.style || {}),
      }}
    >
      {own.children}
    </select>
  );
});

export const Checkbox = React.forwardRef<HTMLInputElement, AnyProps>(function DshCheckbox(props, ref) {
  const [rest, own] = split(props, ["style"]);
  return <input ref={ref} type="checkbox" {...rest} style={{ cursor: "pointer", ...(own.style || {}) }} />;
});

/** DSH's toggle: ``checked``/``onChange(next: boolean)``/``label``. */
export function Switch(props: AnyProps) {
  const checked = props.checked === true;
  const disabled = props.disabled === true;
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={props.label}
      disabled={disabled}
      onClick={() => props.onChange?.(!checked)}
      style={{
        width: 34,
        height: 20,
        padding: 2,
        borderRadius: 999,
        border: "none",
        background: checked ? primary : "var(--dsw-alias-border-l2, rgba(0,0,0,0.2))",
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.5 : 1,
        display: "inline-flex",
        alignItems: "center",
        justifyContent: checked ? "flex-end" : "flex-start",
        transition: "background 120ms ease",
        ...(props.style || {}),
      }}
    >
      <span
        style={{
          width: 16,
          height: 16,
          borderRadius: "50%",
          background: "#fff",
          boxShadow: "0 1px 2px rgba(0,0,0,0.25)",
        }}
      />
    </button>
  );
}

/** Layout helpers some bundles reach for; harmless passthroughs. */
export function Field(props: AnyProps) {
  return <div style={{ display: "grid", gap: 4, ...(props.style || {}) }}>{props.children}</div>;
}

export function Label(props: AnyProps) {
  return (
    <span style={{ fontSize: 12, opacity: 0.8, ...(props.style || {}) }}>{props.children}</span>
  );
}

export function Tooltip(props: AnyProps) {
  return <span title={props.label || props.title || ""}>{props.children}</span>;
}

export const dshPrimitives = {
  Button,
  Input,
  Textarea,
  Select,
  Checkbox,
  Switch,
  Field,
  Label,
  Tooltip,
  default: {
    Button,
    Input,
    Textarea,
    Select,
    Checkbox,
    Switch,
    Field,
    Label,
    Tooltip,
  },
};

export default dshPrimitives;
