/**
 * Permission editing and display: the checkbox picker used inside the user and
 * role forms, its collapsible form wrapper, the fold header they share, and the
 * read-only summary badge shown in the card and table views.
 */

import { Checkbox, Form, Tooltip, Typography } from "antd";
import cx from "classnames";
import { Check, ChevronDown, ChevronRight } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { preferencesApi } from "../../../api/modules/preferences";
import type { SidebarNavLayout } from "../../../layouts/sidebarNavLayout";
import styles from "./index.module.less";
import { buildPermissionPickerGroups } from "./permissionPickerLayout";
import type { PermissionCatalogItem, UserRow } from "./usersListTypes";

const { Text } = Typography;

export interface PermissionCheckboxPickerProps {
  value?: string[];
  onChange?: (value: string[]) => void;
  catalog: PermissionCatalogItem[];
  disabled?: boolean;
}

function PermFoldHeader({
  title,
  titleClassName,
  open,
  disabled,
  checkable,
  checked,
  indeterminate,
  countLabel,
  onToggle,
  onCheck,
}: {
  title: string;
  titleClassName: string;
  open: boolean;
  disabled?: boolean;
  checkable: boolean;
  checked: boolean;
  indeterminate: boolean;
  countLabel: string | null;
  onToggle: () => void;
  onCheck: (checked: boolean) => void;
}) {
  return (
    <div className={styles.permFoldHeader}>
      {checkable ? (
        <Checkbox
          checked={checked}
          indeterminate={indeterminate}
          disabled={disabled}
          aria-label={title}
          onChange={(e) => onCheck(e.target.checked)}
        />
      ) : null}
      <button
        type="button"
        className={styles.permCollapseBtn}
        aria-expanded={open}
        onClick={onToggle}
      >
        <span className={styles.permChevron} aria-hidden>
          {open ? (
            <ChevronDown size={14} strokeWidth={2} />
          ) : (
            <ChevronRight size={14} strokeWidth={2} />
          )}
        </span>
        <span className={titleClassName}>{title}</span>
      </button>
      {countLabel ? (
        <span className={styles.permGroupCount}>{countLabel}</span>
      ) : null}
    </div>
  );
}

export function PermissionCheckboxPicker({
  value,
  onChange,
  catalog,
  disabled,
}: PermissionCheckboxPickerProps) {
  const { t } = useTranslation();
  const selected = value ?? [];
  const selectedSet = useMemo(() => new Set(selected), [selected]);
  const [navLayout, setNavLayout] = useState<SidebarNavLayout | null>(null);
  const [navReady, setNavReady] = useState(false);
  const [collapsedIds, setCollapsedIds] = useState<ReadonlySet<string>>(
    () => new Set(),
  );

  useEffect(() => {
    let cancelled = false;
    void preferencesApi
      .get()
      .then((prefs) => {
        if (!cancelled) setNavLayout(prefs.sidebar_nav ?? null);
      })
      .catch(() => {
        // Keep the default groups when preferences cannot be loaded.
      })
      .finally(() => {
        if (!cancelled) setNavReady(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const groups = useMemo(
    () => buildPermissionPickerGroups(catalog, navLayout, t),
    [catalog, navLayout, t],
  );

  const toggle = (key: string, checked: boolean) => {
    if (disabled) return;
    if (checked) {
      onChange?.([...selected, key]);
      return;
    }
    onChange?.(selected.filter((k) => k !== key));
  };

  const setGroup = (keys: string[], checked: boolean) => {
    if (disabled) return;
    if (checked) {
      const next = new Set(selected);
      for (const k of keys) next.add(k);
      onChange?.(Array.from(next));
      return;
    }
    const drop = new Set(keys);
    onChange?.(selected.filter((k) => !drop.has(k)));
  };

  const toggleCollapsed = (id: string) => {
    setCollapsedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  if (catalog.length === 0) {
    return (
      <div className={styles.permEmpty}>
        <Text type="secondary">{t("adminUsers.permCatalogEmpty")}</Text>
      </div>
    );
  }

  if (!navReady) return null;

  return (
    <div
      className={cx(styles.permPicker, disabled && styles.permPickerDisabled)}
    >
      {groups.map((group) => {
        const keys = group.blocks.flatMap((block) =>
          block.kind === "page"
            ? block.items.map((item) => item.key)
            : block.items.flatMap((chip) =>
                chip.kind === "permission" ? [chip.item.key] : [],
              ),
        );
        const checkedCount = keys.filter((k) => selectedSet.has(k)).length;
        const allChecked = checkedCount === keys.length && keys.length > 0;
        const indeterminate = checkedCount > 0 && !allChecked;
        const renderChips = (
          items: (
            | { kind: "permission"; item: PermissionCatalogItem }
            | { kind: "always"; key: string; label: string }
          )[],
        ) => (
          <div className={styles.permGrid} role="group">
            {items.map((chip) => {
              if (chip.kind === "always") {
                return (
                  <div
                    key={chip.key}
                    className={cx(styles.permChip, styles.permChipAlways)}
                    title={t("adminUsers.permAlwaysOn")}
                  >
                    <span className={styles.permChipLabel}>{chip.label}</span>
                    <span className={styles.permChipAlwaysTag}>
                      {t("adminUsers.permAlwaysOn")}
                    </span>
                  </div>
                );
              }
              const item = chip.item;
              const checked = selectedSet.has(item.key);
              return (
                <button
                  key={item.key}
                  type="button"
                  disabled={disabled}
                  aria-pressed={checked}
                  className={cx(
                    styles.permChip,
                    checked && styles.permChipSelected,
                  )}
                  onClick={() => toggle(item.key, !checked)}
                >
                  <span className={styles.permChipCheck} aria-hidden>
                    {checked ? <Check size={12} strokeWidth={2.5} /> : null}
                  </span>
                  <span className={styles.permChipLabel}>{item.label}</span>
                </button>
              );
            })}
          </div>
        );
        const groupOpen = !collapsedIds.has(group.id);
        return (
          <section key={group.id} className={styles.permGroup}>
            <PermFoldHeader
              title={group.label}
              titleClassName={styles.permGroupTitle}
              open={groupOpen}
              disabled={disabled}
              checkable={keys.length > 0}
              checked={allChecked}
              indeterminate={indeterminate}
              countLabel={
                keys.length > 0 ? `${checkedCount}/${keys.length}` : null
              }
              onToggle={() => toggleCollapsed(group.id)}
              onCheck={(checked) => setGroup(keys, checked)}
            />
            {groupOpen
              ? group.blocks.map((block) => {
                  if (block.kind === "chips") {
                    const chipKey = block.items
                      .map((chip) =>
                        chip.kind === "always" ? chip.key : chip.item.key,
                      )
                      .join(",");
                    return <div key={chipKey}>{renderChips(block.items)}</div>;
                  }
                  const pageId = `${group.id}:${block.id}`;
                  const pageOpen = !collapsedIds.has(pageId);
                  const pageKeys = block.items.map((item) => item.key);
                  const pageChecked = pageKeys.filter((k) =>
                    selectedSet.has(k),
                  ).length;
                  const pageAll =
                    pageChecked === pageKeys.length && pageKeys.length > 0;
                  const pageIndeterminate = pageChecked > 0 && !pageAll;
                  return (
                    <div
                      key={block.id}
                      className={cx(
                        styles.permPage,
                        !pageOpen && styles.permPageCollapsed,
                      )}
                    >
                      <PermFoldHeader
                        title={block.title}
                        titleClassName={styles.permPageTitle}
                        open={pageOpen}
                        disabled={disabled}
                        checkable={pageKeys.length > 0}
                        checked={pageAll}
                        indeterminate={pageIndeterminate}
                        countLabel={`${pageChecked}/${pageKeys.length}`}
                        onToggle={() => toggleCollapsed(pageId)}
                        onCheck={(checked) => setGroup(pageKeys, checked)}
                      />
                      {pageOpen
                        ? renderChips(
                            block.items.map((item) => ({
                              kind: "permission" as const,
                              item,
                            })),
                          )
                        : null}
                    </div>
                  );
                })
              : null}
          </section>
        );
      })}
    </div>
  );
}

/** Keeps the permissions field registered while the picker is unmounted. */
function PermissionValueKeeper(_props: {
  value?: string[];
  onChange?: (value: string[]) => void;
}) {
  return null;
}

export function CollapsiblePermissionsField({
  catalog,
}: {
  catalog: PermissionCatalogItem[];
}) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const permissions = Form.useWatch("permissions") as string[] | undefined;
  const count = permissions?.length ?? 0;

  return (
    <div className={styles.permSectionFold}>
      <div className={styles.permFoldHeader}>
        <button
          type="button"
          className={styles.permCollapseBtn}
          aria-expanded={open}
          onClick={() => setOpen((prev) => !prev)}
        >
          <span className={styles.permChevron} aria-hidden>
            {open ? (
              <ChevronDown size={14} strokeWidth={2} />
            ) : (
              <ChevronRight size={14} strokeWidth={2} />
            )}
          </span>
          <span className={styles.permGroupTitle}>
            {t("adminUsers.colPermissions")}
          </span>
        </button>
        <span className={styles.permGroupCount}>
          {t("adminUsers.permCount", { count })}
        </span>
      </div>
      <Form.Item
        name="permissions"
        preserve
        hidden={!open}
        className={styles.createUserPermItem}
      >
        {open ? (
          <PermissionCheckboxPicker catalog={catalog} />
        ) : (
          <PermissionValueKeeper />
        )}
      </Form.Item>
    </div>
  );
}

export function PermissionSummary({
  row,
  permLabelByKey,
}: {
  row: UserRow;
  permLabelByKey: Map<string, string>;
}) {
  const { t } = useTranslation();
  if (row.role === "admin") {
    return (
      <span className={cx(styles.permBadge, styles.permBadgeAll)}>
        {t("adminUsers.permAll")}
      </span>
    );
  }
  const keys = row.permissions ?? [];
  if (keys.length === 0) {
    return <span className={styles.permBadgeMuted}>—</span>;
  }
  const names = keys.map((key) => permLabelByKey.get(key) ?? key);
  return (
    <Tooltip title={names.join("、")}>
      <span className={styles.permBadge}>
        {t("adminUsers.permCount", { count: keys.length })}
      </span>
    </Tooltip>
  );
}
