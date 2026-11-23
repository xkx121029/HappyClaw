/**
 * Searchable list of expert templates for the "create default expert"
 * option of the new-user drawer.
 */

import { Input } from "antd";
import cx from "classnames";
import { Check, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { ExpertIcon } from "../../Experts/components/iconForName";
import styles from "./index.module.less";
import type { ExpertTemplateOption } from "./usersListTypes";

export function ExpertTemplatePicker({
  value,
  onChange,
  options,
}: {
  value?: string;
  onChange?: (id: string) => void;
  options: ExpertTemplateOption[];
}) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const listRef = useRef<HTMLDivElement>(null);
  const scrolledFor = useRef<string | null>(null);
  const needle = query.trim().toLowerCase();
  const visible = useMemo(() => {
    if (!needle) return options;
    return options.filter((item) =>
      `${item.label} ${item.description ?? ""}`.toLowerCase().includes(needle),
    );
  }, [needle, options]);

  useEffect(() => {
    const list = listRef.current;
    if (!list || !value || scrolledFor.current === value) return;
    const selected = list.querySelector<HTMLElement>("[aria-selected='true']");
    if (!selected) return;
    const listRect = list.getBoundingClientRect();
    const itemRect = selected.getBoundingClientRect();
    if (itemRect.top < listRect.top) {
      list.scrollTop -= listRect.top - itemRect.top;
    } else if (itemRect.bottom > listRect.bottom) {
      list.scrollTop += itemRect.bottom - listRect.bottom;
    }
    scrolledFor.current = value;
  }, [value, visible]);

  return (
    <div className={styles.expertTemplatePicker}>
      <Input
        allowClear
        value={query}
        prefix={<Search size={14} />}
        placeholder={t("experts.searchPlaceholder")}
        onChange={(event) => setQuery(event.target.value)}
      />
      <div
        ref={listRef}
        className={styles.expertTemplateList}
        role="listbox"
        aria-label={t("adminUsers.expertTemplate")}
      >
        {visible.length === 0 ? (
          <div className={styles.expertTemplateEmpty}>
            {t("experts.searchEmpty")}
          </div>
        ) : (
          visible.map((item) => {
            const selected = item.id === value;
            return (
              <button
                key={item.id}
                type="button"
                role="option"
                aria-selected={selected}
                className={cx(
                  styles.expertTemplateRow,
                  selected && styles.expertTemplateRowSelected,
                )}
                onClick={() => onChange?.(item.id)}
              >
                <span className={styles.expertTemplateAvatar}>
                  <ExpertIcon
                    iconUrl={item.icon_url}
                    iconName={item.icon_name}
                    size={40}
                  />
                </span>
                <span className={styles.expertTemplateMeta}>
                  <span className={styles.expertTemplateName}>
                    {item.label}
                  </span>
                  {item.description ? (
                    <span className={styles.expertTemplateDesc}>
                      {item.description}
                    </span>
                  ) : null}
                </span>
                {selected ? (
                  <Check
                    size={16}
                    strokeWidth={2.5}
                    className={styles.expertTemplateCheck}
                    aria-hidden
                  />
                ) : null}
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}
