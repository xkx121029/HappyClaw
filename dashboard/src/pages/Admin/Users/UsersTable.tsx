/**
 * Table view of the users list, including the login-lock status cell it uses.
 */

import { Button, Popconfirm, Space, Switch, Tag, Tooltip, Typography } from "antd";
import cx from "classnames";
import {
  Bot,
  KeyRound,
  Pencil,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { ResizableTable } from "@/components/ResizableTable";

import type { UserRole } from "../../../api/modules/userRoles";
import type { OctopAgent } from "../../../context/AgentContext";
import styles from "./index.module.less";
import { PermissionSummary } from "./PermissionFields";
import { ProfileAvatar } from "./ProfileAvatar";
import { RoleNameMark } from "./RoleDisplay";
import { formatUserTs, lockRemainingSeconds } from "./userTime";
import type { UserRow } from "./usersListTypes";

const { Text } = Typography;

/**
 * Compact login-lock status indicator. Used by both the card view
 * (inline in a `userCard2Row`) and the table view (table cell).
 */
function UserLoginLock({
  row,
  nowSec,
  onUnlock,
}: {
  row: UserRow;
  nowSec: number;
  onUnlock: () => void;
}) {
  const { t } = useTranslation();
  const failedCount = row.login_failed_count ?? 0;
  if (!row.login_locked) {
    if (failedCount > 0) {
      return (
        <Text type="secondary" style={{ fontSize: 12 }}>
          {t("adminUsers.loginFailedCount", { count: failedCount })}
        </Text>
      );
    }
    return (
      <Text type="secondary" style={{ fontSize: 12 }}>
        {t("adminUsers.loginLockNone")}
      </Text>
    );
  }
  const remaining = lockRemainingSeconds(row, nowSec);
  const minutes = Math.max(1, Math.ceil(remaining / 60));
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        flexWrap: "wrap",
        justifyContent: "flex-end",
      }}
    >
      <Tag color="error" style={{ margin: 0, fontSize: 11, lineHeight: "18px" }}>
        {t("adminUsers.loginLockActive", { minutes })}
      </Tag>
      <Button
        size="small"
        type="link"
        onClick={onUnlock}
        style={{ padding: 0, fontSize: 12, height: "auto" }}
      >
        {t("adminUsers.unlockLogin")}
      </Button>
    </span>
  );
}

export function UsersTable({
  rows,
  loading,
  selectedIds,
  onSelectionChange,
  currentUserId,
  agentsByUserId,
  agentsLoading,
  permLabelByKey,
  userRoles,
  nowSec,
  timeZone,
  isMobile,
  onShowAgents,
  onTogglePatch,
  onEdit,
  onResetPassword,
  onResetMfa,
  onDelete,
  onUnlockLogin,
}: {
  rows: UserRow[];
  loading: boolean;
  selectedIds: number[];
  onSelectionChange: (ids: number[]) => void;
  currentUserId: number | null;
  agentsByUserId: Map<number, OctopAgent[]>;
  agentsLoading: boolean;
  permLabelByKey: Map<string, string>;
  userRoles: UserRole[];
  nowSec: number;
  timeZone: string;
  isMobile: boolean;
  onShowAgents: (row: UserRow) => void;
  onTogglePatch: (
    row: UserRow,
    patch: Partial<Pick<UserRow, "role" | "disabled" | "permissions">>,
  ) => Promise<boolean>;
  onEdit: (row: UserRow) => void;
  onResetPassword: (row: UserRow) => void;
  onResetMfa: (row: UserRow) => Promise<void>;
  onDelete: (row: UserRow) => Promise<void>;
  onUnlockLogin: (row: UserRow) => Promise<void>;
}) {
  const { t } = useTranslation();
  return (
    <ResizableTable
      storageKey="admin-users"
      rowKey="id"
      size="middle"
      className={styles.userTable}
      loading={loading}
      dataSource={rows}
      pagination={false}
      scroll={{ x: 1360 }}
      rowSelection={{
        selectedRowKeys: selectedIds,
        onChange: (keys) => onSelectionChange(keys.map((key) => Number(key))),
        preserveSelectedRowKeys: true,
      }}
      rowClassName={(row) =>
        cx(
          row.disabled && styles.userTableRowDisabled,
          row.login_locked && styles.userTableRowLocked,
        )
      }
      columns={[
        {
          title: t("adminUsers.colUsername"),
          width: 240,
          fixed: isMobile ? undefined : "left",
          render: (_, row) => {
            const displayName = row.display_name?.trim() || row.username;
            return (
              <div className={styles.userCell}>
                <ProfileAvatar
                  url={row.avatar_url}
                  icon={row.avatar_icon}
                  kind="user"
                  className={styles.userCellAvatar}
                />
                <span className={styles.userCellText}>
                  <span className={styles.userCellName}>
                    {displayName}
                    {row.id === currentUserId && (
                      <span className={styles.userCellYou}>
                        {t("adminUsers.you")}
                      </span>
                    )}
                  </span>
                  <span className={styles.userCellHandle}>
                    @{row.username}
                  </span>
                </span>
              </div>
            );
          },
        },
        {
          title: t("adminUsers.colEmail"),
          width: 180,
          ellipsis: true,
          render: (_, row) => (
            <span className={styles.userCellMuted}>
              {row.email?.trim() || "—"}
            </span>
          ),
        },
        {
          title: t("adminUsers.colAuth"),
          width: 120,
          render: (_, row) => {
            const parts = [
              row.directory
                ? t("adminUsers.directoryBadge")
                : row.sso_linked
                ? t("adminUsers.ssoBadge")
                : null,
              row.has_password ? t("adminUsers.passwordBadge") : null,
              row.mfa_active ? t("adminUsers.mfaBadge") : null,
            ].filter(Boolean);
            return (
              <span className={styles.userCellMuted}>
                {parts.length ? parts.join(" · ") : "—"}
              </span>
            );
          },
        },
        {
          title: t("adminUsers.colAgents"),
          width: 80,
          render: (_, row) => {
            const count = agentsByUserId.get(row.id)?.length ?? 0;
            return (
              <button
                type="button"
                className={styles.userCellLink}
                onClick={() => onShowAgents(row)}
              >
                <Bot size={13} />
                {agentsLoading ? "…" : count}
              </button>
            );
          },
        },
        {
          title: t("adminUsers.colRoleName"),
          width: 220,
          render: (_, row) => (
            <RoleNameMark
              row={row}
              roles={userRoles}
              className={styles.userCellMuted}
            />
          ),
        },
        {
          title: t("adminUsers.colPermissions"),
          width: 120,
          render: (_, row) => (
            <PermissionSummary row={row} permLabelByKey={permLabelByKey} />
          ),
        },
        {
          title: t("common.enabled"),
          width: 72,
          render: (_, row) => (
            <Switch
              size="small"
              checked={!row.disabled}
              onChange={(checked) => onTogglePatch(row, { disabled: !checked })}
            />
          ),
        },
        {
          title: t("adminUsers.colCreatedAt"),
          dataIndex: "created_at",
          width: 156,
          render: (ts: number | undefined) => (
            <span className={styles.userCellMuted}>
              {formatUserTs(ts, timeZone)}
            </span>
          ),
        },
        {
          title: t("adminUsers.colLoginLock"),
          width: 180,
          render: (_, row) => (
            <UserLoginLock
              row={row}
              nowSec={nowSec}
              onUnlock={() => void onUnlockLogin(row)}
            />
          ),
        },
        {
          title: t("adminUsers.colActions"),
          width: 120,
          fixed: isMobile ? undefined : "right",
          render: (_, row) => (
            <Space size={4}>
              <Tooltip title={t("common.edit")}>
                <button
                  type="button"
                  className={styles.userCardIconBtn}
                  onClick={() => onEdit(row)}
                  aria-label={t("common.edit")}
                >
                  <Pencil size={14} />
                </button>
              </Tooltip>
              <Tooltip title={t("adminUsers.resetPassword")}>
                <button
                  type="button"
                  className={styles.userCardIconBtn}
                  onClick={() => onResetPassword(row)}
                  aria-label={t("adminUsers.resetPassword")}
                >
                  <KeyRound size={14} />
                </button>
              </Tooltip>
              <Popconfirm
                title={t("adminUsers.mfaResetConfirm", {
                  username: row.username,
                })}
                onConfirm={() => void onResetMfa(row)}
              >
                <Tooltip title={t("adminUsers.mfaReset")}>
                  <button
                    type="button"
                    className={styles.userCardIconBtn}
                    aria-label={t("adminUsers.mfaReset")}
                  >
                    <ShieldCheck size={14} />
                  </button>
                </Tooltip>
              </Popconfirm>
              <Popconfirm
                title={t("adminUsers.deleteConfirm", {
                  username: row.username,
                })}
                onConfirm={() => onDelete(row)}
                disabled={row.id === currentUserId}
              >
                <Tooltip
                  title={
                    row.id === currentUserId
                      ? t("adminUsers.deleteSelf")
                      : t("common.delete")
                  }
                >
                  <button
                    type="button"
                    className={cx(
                      styles.userCardIconBtn,
                      styles.userCardIconBtnDanger,
                    )}
                    disabled={row.id === currentUserId}
                    aria-label={t("common.delete")}
                  >
                    <Trash2 size={14} />
                  </button>
                </Tooltip>
              </Popconfirm>
            </Space>
          ),
        },
      ]}
    />
  );
}
