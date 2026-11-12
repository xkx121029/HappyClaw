import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown, ChevronUp, Search, X } from "lucide-react";

import styles from "../index.module.less";

interface MessageSearchBarProps {
  query: string;
  total: number;
  activeIndex: number;
  onQueryChange: (value: string) => void;
  onPrev: () => void;
  onNext: () => void;
  onClose: () => void;
}

/** 会话内搜索条（Ctrl/Cmd + F）。浮层不参与列表布局，关闭时不会挤动消息。 */
export default function MessageSearchBar({
  query,
  total,
  activeIndex,
  onQueryChange,
  onPrev,
  onNext,
  onClose,
}: MessageSearchBarProps) {
  const { t } = useTranslation();
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  const empty = total === 0;

  return (
    <div className={styles.msgSearchBar} role="search">
      <Search
        size={15}
        strokeWidth={2.2}
        aria-hidden
        className={styles.msgSearchIcon}
      />
      <input
        ref={inputRef}
        className={styles.msgSearchInput}
        value={query}
        placeholder={t("chat.search.placeholder")}
        aria-label={t("chat.search.placeholder")}
        onChange={(event) => onQueryChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            onClose();
            return;
          }
          if (event.key === "Enter") {
            event.preventDefault();
            if (event.shiftKey) onPrev();
            else onNext();
          }
        }}
      />
      <span className={styles.msgSearchCount} aria-live="polite">
        {empty
          ? t("chat.search.noResults")
          : t("chat.search.count", {
              current: activeIndex + 1,
              total,
            })}
      </span>
      <button
        type="button"
        className={styles.msgSearchBtn}
        onClick={onPrev}
        disabled={empty}
        aria-label={t("chat.search.previous")}
        title={t("chat.search.previous")}
      >
        <ChevronUp size={15} strokeWidth={2.2} aria-hidden />
      </button>
      <button
        type="button"
        className={styles.msgSearchBtn}
        onClick={onNext}
        disabled={empty}
        aria-label={t("chat.search.next")}
        title={t("chat.search.next")}
      >
        <ChevronDown size={15} strokeWidth={2.2} aria-hidden />
      </button>
      <button
        type="button"
        className={styles.msgSearchBtn}
        onClick={onClose}
        aria-label={t("chat.search.close")}
        title={t("chat.search.close")}
      >
        <X size={15} strokeWidth={2.2} aria-hidden />
      </button>
    </div>
  );
}
