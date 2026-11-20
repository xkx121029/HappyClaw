import { useEffect, useRef } from "react";
import cx from "classnames";
import { useTranslation } from "react-i18next";

import { MobileIcon } from "./MobileIcon";
import { useVisualViewportInset } from "../hooks/useVisualViewportInset";

interface MobileComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onStop?: () => void;
  streaming?: boolean;
  disabled?: boolean;
  placeholder?: string;
  onPlus?: () => void;
  hint?: string;
}

/** Auto-growing message input with a circular send/stop control. */
export function MobileComposer({
  value,
  onChange,
  onSend,
  onStop,
  streaming = false,
  disabled = false,
  placeholder,
  onPlus,
  hint,
}: MobileComposerProps) {
  const { t } = useTranslation();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const keyboardInset = useVisualViewportInset();
  const resolvedPlaceholder =
    placeholder ?? t("mobile.composer.placeholder", "发消息…");

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 120)}px`;
  }, [value]);

  const canSend = value.trim().length > 0 && !disabled;

  return (
    <div
      className="m-composer-wrap"
      style={
        keyboardInset > 0
          ? { paddingBottom: Math.max(8, keyboardInset - 12) }
          : undefined
      }
    >
      <div className="m-composer">
        {onPlus ? (
          <button
            type="button"
            className="m-iconbtn"
            aria-label={t("mobile.composer.more", "更多操作")}
            onClick={onPlus}
            disabled={disabled}
          >
            <MobileIcon name="plus" size={20} />
          </button>
        ) : null}
        <textarea
          ref={textareaRef}
          rows={1}
          value={value}
          placeholder={resolvedPlaceholder}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (
              event.key === "Enter" &&
              !event.shiftKey &&
              !event.nativeEvent.isComposing
            ) {
              event.preventDefault();
              if (canSend) onSend();
            }
          }}
        />
        <button
          type="button"
          className={cx("m-composer-send", streaming && "is-stop")}
          aria-label={
            streaming
              ? t("mobile.composer.stop", "停止生成")
              : t("mobile.composer.send", "发送")
          }
          onClick={streaming ? onStop : onSend}
          disabled={!streaming && !canSend}
        >
          <MobileIcon name={streaming ? "stop" : "send"} size={18} />
        </button>
      </div>
      {hint ? <div className="m-composer-hint">{hint}</div> : null}
    </div>
  );
}
