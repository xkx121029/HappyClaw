import { useEffect, useMemo, useRef, useState } from "react";
import { Modal } from "antd";
import { Search, type LucideIcon } from "lucide-react";
import cx from "classnames";

import styles from "./index.module.less";

export interface PaletteItem {
  id: string;
  label: string;
  meta?: string;
  icon?: LucideIcon;
  run: () => void;
}

export interface PaletteGroup {
  /** Stable id; also used to detect a group boundary while rendering. */
  kind: string;
  label: string;
  items: PaletteItem[];
}

interface PaletteSurfaceProps {
  open: boolean;
  onClose: () => void;
  /** Accessible name for the dialog and its search field. */
  label: string;
  placeholder: string;
  groups: PaletteGroup[];
  emptyText: string;
  /**
   * Actions offered when nothing matches. Without these, Enter would be a dead
   * key on an empty result list.
   */
  emptyActions?: PaletteItem[];
  footerHint: string;
  footerNote?: string;
  width?: number;
}

/**
 * Presentational command palette: one search field, grouped rows, arrow-key
 * selection, Enter to run, Esc to close.
 *
 * Two callers share it — the chat page (sessions / models / actions) and the
 * shell (every page destination), so the interaction model cannot drift.
 */
export default function PaletteSurface({
  open,
  onClose,
  label,
  placeholder,
  groups,
  emptyText,
  emptyActions = [],
  footerHint,
  footerNote,
  width = 620,
}: PaletteSurfaceProps) {
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setActiveIndex(0);
    const timer = window.setTimeout(() => inputRef.current?.focus(), 30);
    return () => window.clearTimeout(timer);
  }, [open]);

  const filteredGroups = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return groups;
    return groups
      .map((group) => ({
        ...group,
        items: group.items.filter(
          (item) =>
            item.label.toLowerCase().includes(q) ||
            item.meta?.toLowerCase().includes(q),
        ),
      }))
      .filter((group) => group.items.length > 0);
  }, [groups, query]);

  const filtered = useMemo(
    () => filteredGroups.flatMap((group) => group.items),
    [filteredGroups],
  );

  const navigable = filtered.length === 0 ? emptyActions : filtered;

  useEffect(() => {
    setActiveIndex(0);
  }, [query]);

  const runCommand = (item: PaletteItem | undefined) => {
    if (!item) return;
    onClose();
    // Let the modal unmount before navigating, or focus snaps back in.
    window.setTimeout(item.run, 0);
  };

  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((index) => Math.min(index + 1, navigable.length - 1));
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((index) => Math.max(index - 1, 0));
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      runCommand(navigable[activeIndex]);
    }
  };

  let flatIndex = -1;

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      closable={false}
      width={width}
      centered
      destroyOnHidden
      className={styles.commandPaletteModal}
      styles={{ body: { padding: 0 } }}
      aria-label={label}
    >
      <div className={styles.commandPalette}>
        <div className={styles.cpSearch}>
          <Search size={16} strokeWidth={1.8} aria-hidden />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            aria-label={placeholder}
            spellCheck={false}
          />
          <kbd className={styles.cpKbd}>Esc</kbd>
        </div>

        <div className={styles.cpList} role="listbox" aria-label={label}>
          {filtered.length === 0 ? (
            <div className={styles.cpEmpty}>
              <p className={styles.cpEmptyText}>{emptyText}</p>
              {emptyActions.length > 0 ? (
                <div className={styles.cpEmptyActions}>
                  {emptyActions.map((item, index) => {
                    const Icon = item.icon;
                    return (
                      <button
                        key={item.id}
                        type="button"
                        className={cx(
                          styles.cpEmptyAction,
                          index === activeIndex && styles.cpEmptyActionActive,
                        )}
                        onMouseEnter={() => setActiveIndex(index)}
                        onClick={() => runCommand(item)}
                      >
                        {Icon ? (
                          <Icon size={14} strokeWidth={1.8} aria-hidden />
                        ) : null}
                        {item.label}
                      </button>
                    );
                  })}
                </div>
              ) : null}
            </div>
          ) : (
            filteredGroups.map((group) => (
              <div key={group.kind}>
                <div className={styles.cpGroup}>{group.label}</div>
                {group.items.map((item) => {
                  flatIndex += 1;
                  const index = flatIndex;
                  const Icon = item.icon;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      role="option"
                      aria-selected={index === activeIndex}
                      className={cx(
                        styles.cpItem,
                        index === activeIndex && styles.cpItemActive,
                      )}
                      onMouseEnter={() => setActiveIndex(index)}
                      onClick={() => runCommand(item)}
                    >
                      {Icon ? (
                        <Icon size={16} strokeWidth={1.8} aria-hidden />
                      ) : null}
                      <span className={styles.cpLabel}>{item.label}</span>
                      {item.meta ? (
                        <span className={styles.cpMeta}>{item.meta}</span>
                      ) : null}
                    </button>
                  );
                })}
              </div>
            ))
          )}
        </div>

        <div className={styles.cpFooter}>
          <span>{footerHint}</span>
          {footerNote ? <span>{footerNote}</span> : null}
        </div>
      </div>
    </Modal>
  );
}

/** Total row count across groups; handy for callers that log or test. */
export function paletteItemCount(groups: PaletteGroup[]): number {
  return groups.reduce((sum, group) => sum + group.items.length, 0);
}

/** Flat list in render order — matches the keyboard-selection index. */
export function paletteFlatItems(groups: PaletteGroup[]): PaletteItem[] {
  return groups.flatMap((group) => group.items);
}
