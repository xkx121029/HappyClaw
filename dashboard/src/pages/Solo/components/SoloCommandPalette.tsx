import { useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import cx from "classnames";
import { Search } from "lucide-react";
import styles from "../solo.module.less";

export interface SoloCommandItem {
  key: string;
  label: string;
  hint?: string;
  icon?: React.ReactNode;
}

export interface SoloCommandGroup {
  label: string;
  items: SoloCommandItem[];
}

interface SoloCommandPaletteProps {
  groups: SoloCommandGroup[];
  onClose: () => void;
  onRun: (key: string) => void;
}

/**
 * 参照稿 `.cmdk` 的命令面板：46px 输入行 + 分组 + 34px 行。
 *
 * ↑↓ 移动、Enter 执行、Esc 关闭；输入按 label 本地过滤。
 */
export default function SoloCommandPalette({
  groups,
  onClose,
  onRun,
}: SoloCommandPaletteProps) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);

  const filtered = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) return groups;
    return groups
      .map((group) => ({
        ...group,
        items: group.items.filter((item) =>
          item.label.toLowerCase().includes(keyword),
        ),
      }))
      .filter((group) => group.items.length > 0);
  }, [groups, query]);

  const flat = useMemo(
    () => filtered.flatMap((group) => group.items),
    [filtered],
  );

  const activeKey = flat[Math.min(activeIndex, flat.length - 1)]?.key ?? null;

  const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((index) =>
        flat.length === 0 ? 0 : (index + 1) % flat.length,
      );
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((index) =>
        flat.length === 0 ? 0 : (index - 1 + flat.length) % flat.length,
      );
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      if (activeKey) onRun(activeKey);
    }
  };

  return (
    <>
      <div className={styles.commandScrim} onMouseDown={onClose} />
      <div
        className={styles.commandPalette}
        role="dialog"
        aria-label={t("solo.commands")}
      >
        <div className={styles.commandInputRow}>
          <Search size={14} />
          <input
            autoFocus
            className={styles.commandInput}
            value={query}
            placeholder={t("solo.commands")}
            onChange={(event) => {
              setQuery(event.target.value);
              setActiveIndex(0);
            }}
            onKeyDown={handleKeyDown}
          />
        </div>
        <div className={styles.commandList} ref={listRef}>
          {flat.length === 0 ? (
            <div className={styles.commandEmpty}>{t("solo.noMatches")}</div>
          ) : (
            filtered.map((group) => (
              <div key={group.label}>
                <div className={styles.commandGroup}>{group.label}</div>
                {group.items.map((item) => (
                  <button
                    key={item.key}
                    type="button"
                    className={cx(
                      styles.commandRow,
                      item.key === activeKey && styles.commandRowActive,
                    )}
                    onMouseEnter={() => setActiveIndex(flat.indexOf(item))}
                    onClick={() => onRun(item.key)}
                  >
                    {item.icon}
                    <span>{item.label}</span>
                    {item.hint ? (
                      <span className={styles.commandHint}>{item.hint}</span>
                    ) : null}
                  </button>
                ))}
              </div>
            ))
          )}
        </div>
      </div>
    </>
  );
}
