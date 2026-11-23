/**
 * Role selector form field for the user create/edit drawers. Picking a role
 * copies that role's permissions and resource policies into the form.
 */

import { Form, Input, Modal, Select } from "antd";
import { useRef } from "react";
import { useTranslation } from "react-i18next";

import { userRoleLabel, type UserRole } from "../../../api/modules/userRoles";
import { policyFieldsFromRole } from "./policyForm";
import { RoleSelectLabel } from "./ProfileAvatar";

export function UserRoleField({
  roles,
  workspaceRootAllowed,
  staleName,
  confirmOverwrite,
  actorIsAdmin,
  diverged,
  snapshotName,
  disabled,
}: {
  roles: UserRole[];
  workspaceRootAllowed: boolean;
  staleName?: string | null;
  confirmOverwrite?: boolean;
  actorIsAdmin?: boolean;
  diverged?: boolean;
  snapshotName?: string | null;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const form = Form.useFormInstance();
  const selectedId = Form.useWatch("role", form) as string | undefined;
  const showStale = Boolean(staleName) && !selectedId;
  const selectedRole = roles.find((role) => role.user_role_id === selectedId);
  const showDiverged =
    Boolean(diverged) &&
    Boolean(snapshotName) &&
    selectedRole?.user_role_name === snapshotName;
  const visibleRoles =
    actorIsAdmin === false
      ? roles.filter((role) => role.system_role !== "admin")
      : roles;
  const committedId = useRef<string | null>(
    (form.getFieldValue("role") as string | null | undefined) ?? null,
  );
  const committedName = useRef<string | null>(
    (form.getFieldValue("role_name") as string | null | undefined) ?? null,
  );

  const applyRole = (role: UserRole) => {
    const next: Record<string, unknown> = {
      role: role.user_role_id,
      role_name: role.user_role_name,
    };
    if (role.system_role !== "admin") {
      next.permissions = [...role.permissions];
      Object.assign(next, policyFieldsFromRole(role, workspaceRootAllowed));
    } else {
      next.permissions = [];
    }
    form.setFieldsValue(next);
    committedId.current = role.user_role_id;
    committedName.current = role.user_role_name;
  };

  return (
    <>
      <Form.Item name="role_name" hidden>
        <Input />
      </Form.Item>
      <Form.Item
        label={t("adminUsers.formUserRole")}
        name="role"
        rules={[
          { required: true, message: t("adminUsers.formUserRolePlaceholder") },
        ]}
        extra={
          showStale
            ? t("adminUsers.formUserRoleStale", { name: staleName })
            : showDiverged
            ? t("adminUsers.formRoleDiverged")
            : t("adminUsers.formUserRoleHint")
        }
      >
        <Select
          disabled={disabled}
          placeholder={t("adminUsers.formUserRolePlaceholder")}
          options={visibleRoles.map((role) => ({
            value: role.user_role_id,
            label: userRoleLabel(role, t),
          }))}
          optionRender={(option) => {
            const role = visibleRoles.find(
              (item) => item.user_role_id === option.value,
            );
            if (!role) return option.label;
            return (
              <RoleSelectLabel
                url={role.avatar_url}
                icon={role.avatar_icon}
                label={userRoleLabel(role, t)}
              />
            );
          }}
          labelRender={(option) => {
            const role = visibleRoles.find(
              (item) => item.user_role_id === option.value,
            );
            if (!role) return option.label;
            return (
              <RoleSelectLabel
                url={role.avatar_url}
                icon={role.avatar_icon}
                label={userRoleLabel(role, t)}
              />
            );
          }}
          onChange={(id) => {
            const next = (id as string | null | undefined) ?? null;
            if (next == null) {
              form.setFieldsValue({ role: null, role_name: null });
              committedId.current = null;
              committedName.current = null;
              return;
            }
            const role = visibleRoles.find(
              (item) => item.user_role_id === next,
            );
            if (!role) return;
            if (!confirmOverwrite || committedId.current === next) {
              applyRole(role);
              return;
            }
            Modal.confirm({
              title: t("adminUsers.roleApplyConfirm"),
              content: t("adminUsers.roleApplyConfirmHint"),
              okText: t("common.confirm"),
              cancelText: t("common.cancel"),
              onOk: () => applyRole(role),
              onCancel: () => {
                form.setFieldsValue({
                  role: committedId.current,
                  role_name: committedName.current,
                });
              },
            });
          }}
        />
      </Form.Item>
    </>
  );
}
