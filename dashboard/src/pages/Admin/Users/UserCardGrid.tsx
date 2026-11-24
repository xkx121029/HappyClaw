/**
 * Card view of the users list: one card per user with role, permission and
 * login-lock status plus the row actions.
 */

import { Button, Checkbox, Empty, Popconfirm, Spin, Switch, Tooltip } from "antd";
import cx from "classnames";
import { Bot, KeyRound, Lock, Pencil, ShieldCheck, Trash2 } from "lucide-react";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import type { UserRole } from "../../../api/modules/userRoles";
import type { OctopAgent } from "../../../context/AgentContext";
import { useServerTimezone } from "../../../hooks/useServerTimezone";
import styles from "./index.module.less";
import { PermissionSummary } from "./PermissionFields";
import { ProfileAvatar } from "./ProfileAvatar";
import { RoleNameMark } from "./RoleDisplay";
import { formatUserTs, lockRemainingSeconds } from "./userTime";
import type { UserRow } from "./usersListTypes";

export interface UserCardGridProps {
  rows: UserRow[];
  loading: boolean;
  agentsByUserId: Map<number, OctopAgent[]>;
  agentsLoading: boolean;
  currentUserId: number | null;
  permLabelByKey: Map<string, string>;
  selectedIds: number[];
  onToggleSelect: (id: number, checked: boolean) => void;
  onTogglePatch: (
    row: UserRow,
    patch: Partial<Pick<UserRow, "role" | "disabled" | "permissions">>,
  ) => Promise<boolean>;
  onEdit: (row: UserRow) => void;
  onShowAgents: (row: UserRow) => void;
  onResetPassword: (row: UserRow) => void;
  onResetMfa: (row: UserRow) => Promise<void>;
  onDelete: (row: UserRow) => Promise<void>;
  onUnlockLogin: (row: UserRow) => Promise<void>;
  nowSec: number;
  userRoles: UserRole[];
}

export function UserCardGrid({
  rows,
  loading,
  agentsByUserId,
  agentsLoading,
  currentUserId,
  permLabelByKey,
  selectedIds,
  onToggleSelect,
  onTogglePatch,
  onEdit,
  onShowAgents,
  onResetPassword,
  onResetMfa,
  onDelete,
  onUnlockLogin,
  nowSec,
  userRoles,
}: UserCardGridProps) {
  const { t } = useTranslation();
  const timeZone = useServerTimezone();
  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds]);
  if (loading && rows.length === 0) {
    return (
      <div className={styles.userGridLoading}>
        <Spin />
      </div>
    );
  }
  if (rows.length === 0) {
    return <Empty description={t("adminUsers.noUsers")} />;
  }
  return (
    <div className={styles.userCardGrid}>
      {rows.map((row) => {
        const agentCount = agentsByUserId.get(row.id)?.length ?? 0;
        const isSelf = row.id === currentUserId;
        const selected = selectedSet.has(row.id);
        const displayName = row.display_name?.trim() || row.username;
        const remaining = lockRemainingSeconds(row, nowSec);
        const isLocked = remaining > 0;
        const failedCount = row.login_failed_count ?? 0;
        return (
          <div
            key={row.id}
            className={cx(
              styles.userCard,
              selected && styles.userCardSelected,
              isLocked && styles.userCardLocked,
              row.disabled && styles.userCardDisabled,
            )}
          >
            <div className={styles.userCardBody}>
              <div className={styles.userCardTop}>
                <Checkbox
                  checked={selected}
                  onChange={(e) => onToggleSelect(row.id, e.target.checked)}
                  className={styles.userCardSelect}
                  aria-label={t("adminUsers.batchSelectUser", {
                    username: row.username,
                  })}
                />
                <span className={styles.userCardAvatarWrap}>
                  <ProfileAvatar
                    url={row.avatar_url}
                    icon={row.avatar_icon}
                    kind="user"
                    className={styles.userCardAvatar}
                  />
                  <span
                    className={cx(
                      styles.userCardStatusDot,
                      row.disabled && styles.userCardStatusDotOff,
                    )}
                  />
                </span>
                <div className={styles.userCardTitleBlock}>
                  <div className={styles.userCardNameRow}>
                    <h3 className={styles.userCardName}>{displayName}</h3>
                    {isSelf ? (
                      <span className={styles.userCardYou}>
                        {t("adminUsers.you")}
                      </span>
                    ) : null}
                  </div>
                  <p className={styles.userCardSub}>
                    <span>@{row.username}</span>
                    <span className={styles.userCardMetaSep}>·</span>
                    <RoleNameMark row={row} roles={userRoles} />
                  </p>
                </div>
              </div>
              <p className={styles.userCardDesc}>
                {row.email?.trim() || t("adminUsers.noEmail")}
                {row.created_at != null
                  ? ` · ${formatUserTs(row.created_at, timeZone)}`
                  : ""}
              </p>
              <div className={styles.userCardQuiet}>
                <PermissionSummary row={row} permLabelByKey={permLabelByKey} />
                {row.directory ? (
                  <span>{t("adminUsers.directoryBadge")}</span>
                ) : row.sso_linked ? (
                  <span>{t("adminUsers.ssoBadge")}</span>
                ) : null}
                {row.has_password ? (
                  <span>{t("adminUsers.passwordBadge")}</span>
                ) : null}
                {row.mfa_active ? (
                  <span>{t("adminUsers.mfaBadge")}</span>
                ) : null}
              </div>
              {isLocked ? (
                <div className={styles.userCardLockAlert}>
                  <Lock size={14} />
                  <span>
                    {t("adminUsers.loginLockActive", {
                      minutes: Math.max(1, Math.ceil(remaining / 60)),
                    })}
                  </span>
                  <Button
                    type="link"
                    size="small"
                    onClick={() => void onUnlockLogin(row)}
                  >
                    {t("adminUsers.unlockLogin")}
                  </Button>
                </div>
              ) : null}
              {!isLocked && failedCount > 0 ? (
                <div className={styles.userCardFailedHint}>
                  {t("adminUsers.loginFailedCount", { count: failedCount })}
                </div>
              ) : null}
            </div>
            <div className={styles.userCardFooter}>
              <button
                type="button"
                className={styles.userCardDetailLink}
                onClick={() => onShowAgents(row)}
              >
                <Bot size={14} />
                {t("adminUsers.colAgents")} {agentsLoading ? "…" : agentCount}
              </button>
              <span className={styles.userCardFooterSpacer} />
              <Switch
                size="small"
                checked={!row.disabled}
                onChange={(checked) =>
                  void onTogglePatch(row, { disabled: !checked })
                }
                aria-label={t("common.enabled")}
              />
              <Tooltip title={t("common.edit")} mouseEnterDelay={0.5}>
                <button
                  type="button"
                  className={styles.userCardIconBtn}
                  onClick={() => onEdit(row)}
                  aria-label={t("common.edit")}
                >
                  <Pencil size={15} />
                </button>
              </Tooltip>

              <Tooltip
                title={t("adminUsers.resetPassword")}
                mouseEnterDelay={0.5}
              >
                <button
                  type="button"
                  className={styles.userCardIconBtn}
                  onClick={() => onResetPassword(row)}
                  aria-label={t("adminUsers.resetPassword")}
                >
                  <KeyRound size={15} />
                </button>
              </Tooltip>

              <Popconfirm
                title={t("adminUsers.mfaResetConfirm", {
                  username: row.username,
                })}
                onConfirm={() => void onResetMfa(row)}
              >
                <Tooltip title={t("adminUsers.mfaReset")} mouseEnterDelay={0.5}>
                  <button
                    type="button"
                    className={styles.userCardIconBtn}
                    aria-label={t("adminUsers.mfaReset")}
                  >
                    <ShieldCheck size={15} />
                  </button>
                </Tooltip>
              </Popconfirm>

              <Popconfirm
                title={t("adminUsers.deleteConfirm", {
                  username: row.username,
                })}
                onConfirm={() => void onDelete(row)}
                disabled={isSelf}
              >
                <Tooltip
                  title={
                    isSelf ? t("adminUsers.deleteSelf") : t("common.delete")
                  }
                  mouseEnterDelay={0.5}
                >
                  <button
                    type="button"
                    className={cx(
                      styles.userCardIconBtn,
                      styles.userCardIconBtnDanger,
                    )}
                    disabled={isSelf}
                    aria-label={t("common.delete")}
                  >
                    <Trash2 size={15} />
                  </button>
                </Tooltip>
              </Popconfirm>
              <span className={styles.userCardIdBadge}>#{row.id}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
