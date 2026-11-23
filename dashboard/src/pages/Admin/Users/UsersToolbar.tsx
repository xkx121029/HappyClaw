/**
 * Page-top chrome of the users screen: the role legend, the search box, the
 * card/table view switcher and the refresh/invite/new-user actions, plus the
 * toolbar that appears while rows are selected.
 */

import { Button, Checkbox, Input, Segmented } from "antd";
import {
  Bot,
  Coins,
  LayoutGrid,
  Link2,
  List,
  Plus,
  Power,
  PowerOff,
  RefreshCw,
  Search,
  Trash2,
  X,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import expertStyles from "../../Experts/index.module.less";
import styles from "./index.module.less";
import { RoleLegend } from "./RoleDisplay";

export function UsersToolbar({
  searchQuery,
  onSearchChange,
  showCardView,
  visibleCount,
  selectedVisibleCount,
  onSelectAllVisible,
  viewMode,
  onViewModeChange,
  onRefresh,
  onInvite,
  onCreate,
}: {
  searchQuery: string;
  onSearchChange: (value: string) => void;
  showCardView: boolean;
  visibleCount: number;
  selectedVisibleCount: number;
  onSelectAllVisible: (checked: boolean) => void;
  viewMode: "table" | "card";
  onViewModeChange: (mode: "table" | "card") => void;
  onRefresh: () => void;
  onInvite: () => void;
  onCreate: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className={styles.pageTop}>
      <RoleLegend />
      <div className={expertStyles.gridToolbar}>
        <div className={styles.userSearchRow}>
          {showCardView ? (
            <Checkbox
              checked={
                visibleCount > 0 && selectedVisibleCount === visibleCount
              }
              indeterminate={
                selectedVisibleCount > 0 && selectedVisibleCount < visibleCount
              }
              disabled={visibleCount === 0}
              onChange={(e) => onSelectAllVisible(e.target.checked)}
            >
              {t("adminUsers.batchSelectAll")}
            </Checkbox>
          ) : null}
          <Input
            allowClear
            prefix={<Search size={14} />}
            value={searchQuery}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder={t("adminUsers.searchPlaceholder")}
            className={styles.userSearch}
          />
        </div>
        <div className={expertStyles.gridToolbarRight}>
          <Segmented
            size="small"
            value={viewMode}
            onChange={(v) => onViewModeChange(v as "table" | "card")}
            options={[
              {
                value: "card",
                label: (
                  <span className={expertStyles.viewModeLabel}>
                    <LayoutGrid size={14} />
                    {t("adminUsers.viewCard", "卡片")}
                  </span>
                ),
              },
              {
                value: "table",
                label: (
                  <span className={expertStyles.viewModeLabel}>
                    <List size={14} />
                    {t("adminUsers.viewTable", "表格")}
                  </span>
                ),
              },
            ]}
          />
          <Button icon={<RefreshCw size={14} />} onClick={onRefresh}>
            {t("common.refresh")}
          </Button>
          <Button icon={<Link2 size={14} />} onClick={onInvite}>
            {t("adminUsers.inviteUsers")}
          </Button>
          <Button type="primary" icon={<Plus size={14} />} onClick={onCreate}>
            {t("adminUsers.newUser")}
          </Button>
        </div>
      </div>
    </div>
  );
}

export function UsersBatchBar({
  count,
  submitting,
  onEnable,
  onDisable,
  onOpenToken,
  onOpenMaxAgents,
  onDelete,
  onClear,
}: {
  count: number;
  submitting: boolean;
  onEnable: () => void;
  onDisable: () => void;
  onOpenToken: () => void;
  onOpenMaxAgents: () => void;
  onDelete: () => void;
  onClear: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className={styles.batchBar} role="toolbar">
      <span className={styles.batchBarCount}>
        {t("adminUsers.batchSelected", { count })}
      </span>
      <div className={styles.batchBarActions}>
        <Button
          size="small"
          icon={<Power size={14} />}
          loading={submitting}
          onClick={onEnable}
        >
          {t("adminUsers.batchEnable")}
        </Button>
        <Button
          size="small"
          icon={<PowerOff size={14} />}
          loading={submitting}
          onClick={onDisable}
        >
          {t("adminUsers.batchDisable")}
        </Button>
        <Button
          size="small"
          icon={<Coins size={14} />}
          loading={submitting}
          onClick={onOpenToken}
        >
          {t("adminUsers.batchSetToken")}
        </Button>
        <Button
          size="small"
          icon={<Bot size={14} />}
          loading={submitting}
          onClick={onOpenMaxAgents}
        >
          {t("adminUsers.batchSetMaxAgents")}
        </Button>
        <Button
          size="small"
          danger
          icon={<Trash2 size={14} />}
          loading={submitting}
          onClick={onDelete}
        >
          {t("common.delete")}
        </Button>
        <Button
          size="small"
          type="text"
          icon={<X size={14} />}
          onClick={onClear}
          aria-label={t("adminUsers.batchClear")}
        >
          {t("adminUsers.batchClear")}
        </Button>
      </div>
    </div>
  );
}
