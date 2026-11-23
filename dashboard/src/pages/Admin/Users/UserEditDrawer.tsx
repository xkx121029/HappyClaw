/**
 * Drawer for editing a user: avatar, display details, role and permissions,
 * and resource policies.
 */

import { Button, Drawer, Form, Input } from "antd";
import type { FormInstance } from "antd";
import cx from "classnames";
import { CircleHelp, IdCard, Mail, ShieldCheck } from "lucide-react";
import { useTranslation } from "react-i18next";

import { userRoleDrift, type UserRole } from "../../../api/modules/userRoles";
import styles from "./index.module.less";
import { CollapsiblePermissionsField } from "./PermissionFields";
import { ProfileAvatarPicker } from "./ProfileAvatar";
import { ResourcePolicyFields } from "./ResourcePolicyFields";
import { UserRoleField } from "./UserRoleField";
import {
  FIELD_ICON_PROPS,
  type EditValues,
  type PermissionCatalogItem,
  type UserRow,
} from "./usersListTypes";

export function UserEditDrawer({
  open,
  target,
  onClose,
  form,
  submitting,
  onSubmit,
  userRoles,
  workspaceRootAllowed,
  actorIsAdmin,
  permCatalog,
  fsTreeRoots,
  isSelfAdmin,
  onSelectIcon,
  onPickAvatar,
  onRemoveAvatar,
}: {
  open: boolean;
  target: UserRow | null;
  onClose: () => void;
  form: FormInstance<EditValues>;
  submitting: boolean;
  onSubmit: (values: EditValues) => Promise<void>;
  userRoles: UserRole[];
  workspaceRootAllowed: boolean;
  actorIsAdmin: boolean;
  permCatalog: PermissionCatalogItem[];
  fsTreeRoots: string[];
  isSelfAdmin: boolean;
  onSelectIcon: (target: UserRow, icon: string | null) => Promise<void>;
  onPickAvatar: (target: UserRow, file: File) => Promise<void>;
  onRemoveAvatar: (target: UserRow) => Promise<void>;
}) {
  const { t } = useTranslation();
  return (
    <Drawer
      title={
        target
          ? t("adminUsers.modalEditTitle", {
              username: target.username,
            })
          : t("common.edit")
      }
      placement="right"
      open={open}
      onClose={onClose}
      width={Math.min(
        520,
        typeof window !== "undefined" ? window.innerWidth - 24 : 520,
      )}
      destroyOnHidden
      className={styles.createUserDrawer}
      styles={{ body: { paddingTop: 12, paddingBottom: 24 } }}
      footer={
        <div className={styles.createUserFooter}>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button
            type="primary"
            loading={submitting}
            onClick={() => form.submit()}
          >
            {t("common.save")}
          </Button>
        </div>
      }
    >
      <Form<EditValues>
        form={form}
        layout="vertical"
        requiredMark={false}
        onFinish={onSubmit}
        className={styles.createUserForm}
      >
        <div className={styles.createSection}>
          <div className={styles.createSectionTitle}>
            {t("adminUsers.createSectionAccount")}
          </div>
          {target ? (
            <ProfileAvatarPicker
              kind="user"
              avatarUrl={target.avatar_url}
              icon={target.avatar_icon}
              onSelectIcon={(icon) => onSelectIcon(target, icon)}
              onPick={(file) => onPickAvatar(target, file)}
              onRemove={() => onRemoveAvatar(target)}
            />
          ) : null}
          <Form.Item label={t("adminUsers.formDisplayName")} name="display_name">
            <Input prefix={<IdCard {...FIELD_ICON_PROPS} />} />
          </Form.Item>
          <Form.Item
            label={t("adminUsers.formEmail")}
            name="email"
            rules={[
              {
                type: "email",
                message: t("adminUsers.formEmailInvalid"),
              },
            ]}
          >
            <Input
              prefix={<Mail {...FIELD_ICON_PROPS} />}
              type="email"
              autoComplete="email"
            />
          </Form.Item>
        </div>

        <div className={styles.createSection}>
          <div className={styles.createSectionTitle}>
            {t("adminUsers.createSectionAccess")}
          </div>
          <div className={cx(styles.permAdminHint, styles.permSectionHint)}>
            <CircleHelp size={15} strokeWidth={2} />
            <span>{t("adminUsers.permEditHint")}</span>
          </div>
          <UserRoleField
            roles={userRoles}
            workspaceRootAllowed={workspaceRootAllowed}
            confirmOverwrite
            actorIsAdmin={actorIsAdmin}
            disabled={isSelfAdmin}
            diverged={
              Boolean(target) &&
              userRoleDrift(target as UserRow, userRoles) === "changed"
            }
            snapshotName={target?.role_name}
            staleName={
              target?.role_name &&
              !userRoles.some(
                (role) =>
                  role.user_role_id === target.role ||
                  role.user_role_name === target.role_name,
              )
                ? target.role_name
                : null
            }
          />
          {isSelfAdmin ? (
            <div className={styles.permAdminHint}>
              <span>{t("adminUsers.demoteSelf")}</span>
            </div>
          ) : null}
          <Form.Item noStyle shouldUpdate={(prev, cur) => prev.role !== cur.role}>
            {({ getFieldValue }) => {
              const isAdminRole = getFieldValue("role") === "admin";
              if (isAdminRole) {
                return (
                  <div className={styles.permAdminHint}>
                    <ShieldCheck size={15} strokeWidth={2} />
                    <span>{t("adminUsers.permAllHint")}</span>
                  </div>
                );
              }
              return <CollapsiblePermissionsField catalog={permCatalog} />;
            }}
          </Form.Item>
        </div>

        <ResourcePolicyFields
          fsTreeRoots={fsTreeRoots}
          workspaceRootAllowed={workspaceRootAllowed}
        />
      </Form>
    </Drawer>
  );
}
