/**
 * Role display pieces: the role-name cell used by the user card and table
 * views, and the explanatory legend above the users toolbar.
 */

import { Tag } from "antd";
import cx from "classnames";
import { useTranslation } from "react-i18next";

import {
  snapshotRoleLabel,
  userRoleDrift,
  userRoleLabel,
  type UserRole,
} from "../../../api/modules/userRoles";
import styles from "./index.module.less";
import { ProfileAvatar } from "./ProfileAvatar";
import type { UserRow } from "./usersListTypes";

export function RoleNameMark({
  row,
  roles,
  className,
}: {
  row: UserRow;
  roles: UserRole[];
  className?: string;
}) {
  const { t } = useTranslation();
  const name = row.role_name?.trim();
  const drift = userRoleDrift(row, roles);
  const matched = row.role
    ? roles.find((role) => role.user_role_id === row.role)
    : name
    ? roles.find((role) => role.user_role_name === name)
    : undefined;
  const label =
    snapshotRoleLabel(name, roles, t, row.role) ||
    (matched ? userRoleLabel(matched, t) : "");
  if (!label && drift !== "missing") {
    return <span className={className}>—</span>;
  }
  return (
    <span className={cx(styles.roleNameMark, className)}>
      {matched ? (
        <ProfileAvatar
          url={matched.avatar_url}
          icon={matched.avatar_icon}
          kind="role"
          className={styles.roleSelectIcon}
        />
      ) : null}
      <span className={styles.roleNameText}>
        {label || t("adminUsers.roleNameMissing")}
      </span>
      {drift === "changed" ? (
        <Tag>{t("adminUsers.roleNameChanged")}</Tag>
      ) : null}
      {drift === "missing" && label ? (
        <Tag>{t("adminUsers.roleNameMissing")}</Tag>
      ) : null}
    </span>
  );
}

export function RoleLegend() {
  const { t } = useTranslation();
  return (
    <div className={styles.roleLegend} role="note">
      <span className={styles.roleLegendLabel}>
        {t("adminUsers.roleLegendTitle")}
      </span>
      <p className={styles.roleLegendText}>{t("adminUsers.roleLegend")}</p>
    </div>
  );
}
