import { ArrowUp, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/separator";
import { cn } from "@/lib/cn";
import { readStored, storageKeys, writeStored } from "@/lib/storage";

export function Composer({
  disabled,
  sending,
  onSend,
  disabledReason,
}: {
  disabled: boolean;
  sending: boolean;
  onSend: (text: string) => void;
  disabledReason?: string;
}) {
  const { t } = useTranslation("chat");
  const [value, setValue] = useState(() => readStored(storageKeys.chatDraft) ?? "");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    writeStored(storageKeys.chatDraft, value);
  }, [value]);

  // Grow with the content, up to a ceiling, then scroll.
  useEffect(() => {
    const node = textareaRef.current;
    if (!node) return;
    node.style.height = "auto";
    node.style.height = `${Math.min(node.scrollHeight, 200)}px`;
  }, [value]);

  const submit = () => {
    const text = value.trim();
    if (!text || disabled || sending) return;
    onSend(text);
    setValue("");
  };

  return (
    <div className="border-t border-line-subtle bg-surface/60 px-3 py-3 backdrop-blur-sm md:px-6">
      <div className="mx-auto w-full max-w-reading">
        <div
          className={cn(
            "flex items-end gap-2 rounded-lg border border-line bg-surface p-1.5 shadow-xs",
            "transition-[border-color,box-shadow] focus-within:border-line-focus focus-within:shadow-glow",
          )}
        >
          <textarea
            ref={textareaRef}
            value={value}
            disabled={disabled}
            rows={1}
            onChange={(event) => setValue(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                submit();
              }
            }}
            placeholder={disabled ? t("composer.disabled") : t("composer.placeholder")}
            aria-label={t("composer.placeholder")}
            className="max-h-[200px] min-h-9 flex-1 resize-none bg-transparent px-2 py-1.5 text-base leading-relaxed text-fg outline-none placeholder:text-fg-subtle disabled:cursor-not-allowed"
          />
          <Button
            variant="primary"
            size="icon-sm"
            aria-label={t("composer.send")}
            disabled={disabled || !value.trim() || sending}
            onClick={submit}
          >
            {sending ? <Square className="fill-current" /> : <ArrowUp />}
          </Button>
        </div>
        <p className="mt-1.5 flex items-center gap-1.5 px-1 text-2xs text-fg-subtle">
          {disabled && disabledReason ? (
            disabledReason
          ) : (
            <>
              <Kbd>Enter</Kbd> {t("composer.hint")}
            </>
          )}
        </p>
      </div>
    </div>
  );
}
