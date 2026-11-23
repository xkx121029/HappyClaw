/**
 * Drawer for creating a user: account details, role and permissions, optional
 * default expert, and resource policies.
 */

import { Button, Drawer, Form, Input, Switch } from "antd";
import type { FormInstance } from "antd";
import cx from "classnames";
import { CircleHelp, IdCard, Lock, LockOpen, Mail, ShieldCheck, User } from "lucide-react";
import { useTranslation } from "react-i18next";

import styles from "./index.module.less";
import { CollapsiblePermissionsField } from "./PermissionFields";
import { ProfileAvatarPicker } from "./ProfileAvatar";
import { ResourcePolicyFields } from "./ResourcePolicyFields";
import { UserRoleField } from "./UserRoleField";
import { ExpertTemplatePicker } from "./ExpertTemplatePicker";
import {
  DEFAULT_EXPERT_TEMPLATE_ID,
  FIELD_ICON_PROPS,
  type CreateValues,
  type ExpertTemplateOption,
  type PermissionCatalogItem,
} from "./usersListTypes";
import type { UserRole } from "../../../api/modules/userRoles";

export function UserCreateDrawer({
  open,
  onClose,
  form,
  submitting,
  onSubmit,
  expertTemplates,
  userRoles,
  workspaceRootAllowed,
  actorIsAdmin,
  permCatalog,
  fsTreeRoots,
  pendingUserIcon,
  onPickAvatar,
  onSelectIcon,
  onRemoveAvatar,
}: {
  open: boolean;
  onClose: () => void;
  form: FormInstance<CreateValues>;
  submitting: boolean;
  onSubmit: (values: CreateValues) => Promise<void>;
  expertTemplates: ExpertTemplateOption[];
  userRoles: UserRole[];
  workspaceRootAllowed: boolean;
  actorIsAdmin: boolean;
  permCatalog: PermissionCatalogItem[];
  fsTreeRoots: string[];
  pendingUserIcon: string | null;
  onPickAvatar: (file: File) => void;
  onSelectIcon: (icon: string | null) => void;
  onRemoveAvatar: () => void;
}) {
  const { t } = useTranslation();
  const directoryAccount = Form.useWatch("directory", form) === true;

  return (
    <Drawer
      title={t("adminUsers.modalNewTitle")}
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
            {t("common.create")}
          </Button>
        </div>
      }
    >
      <Form<CreateValues>
        form={form}
        layout="vertical"
        requiredMark={false}
        onFinish={onSubmit}
        initialValues={{
          role: "user",
          permissions: [],
          limit_workspace_root: false,
          limit_token_quota: false,
          limit_max_agents: false,
          create_default_expert: true,
          expert_template_id: DEFAULT_EXPERT_TEMPLATE_ID,
        }}
        className={styles.createUserForm}
      >
        <div className={styles.createSection}>
          <div className={styles.createSectionTitle}>
            {t("adminUsers.createSectionAccount")}
          </div>
          <ProfileAvatarPicker
            kind="user"
            icon={pendingUserIcon}
            onPick={async (file) => {
              onPickAvatar(file);
            }}
            onSelectIcon={(icon) => {
              onSelectIcon(icon);
            }}
            onRemove={() => onRemoveAvatar()}
          />
          <Form.Item
            label={t("adminUsers.formUsername")}
            name="username"
            rules={[
              { required: true, message: t("adminUsers.formUsername") },
              {
                pattern: /^[a-zA-Z0-9_-]{1,64}$/,
                message: t("wizard.admin.usernameRule"),
              },
            ]}
          >
            <Input prefix={<User {...FIELD_ICON_PROPS} />} autoFocus />
          </Form.Item>
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
          <Form.Item
            name="directory"
            label={t("adminUsers.formDirectory")}
            extra={t("adminUsers.formDirectoryHint")}
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>
          {!directoryAccount && (
            <>
              <Form.Item
                label={t("adminUsers.formPassword")}
                name="password"
                rules={[
                  { required: true, message: t("adminUsers.formPassword") },
                ]}
              >
                <Input.Password
                  prefix={<Lock {...FIELD_ICON_PROPS} />}
                  autoComplete="new-password"
                />
              </Form.Item>
              <Form.Item
                label={t("adminUsers.formPasswordConfirm")}
                name="confirm"
                dependencies={["password"]}
                rules={[
                  {
                    required: true,
                    message: t("adminUsers.formPasswordConfirm"),
                  },
                  ({ getFieldValue }) => ({
                    validator(_, value) {
                      if (!value || getFieldValue("password") === value) {
                        return Promise.resolve();
                      }
                      return Promise.reject(
                        new Error(t("wizard.admin.passwordMismatch")),
                      );
                    },
                  }),
                ]}
              >
                <Input.Password
                  prefix={<LockOpen {...FIELD_ICON_PROPS} />}
                  autoComplete="new-password"
                />
              </Form.Item>
            </>
          )}
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
            actorIsAdmin={actorIsAdmin}
          />
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

        <div className={styles.createSection}>
          <div className={styles.createSectionTitle}>
            {t("adminUsers.createSectionExpert")}
          </div>
          <Form.Item
            label={t("adminUsers.createDefaultExpert")}
            name="create_default_expert"
            valuePropName="checked"
            extra={t("adminUsers.createDefaultExpertHint")}
          >
            <Switch />
          </Form.Item>
          <Form.Item
            noStyle
            shouldUpdate={(prev, cur) =>
              prev.create_default_expert !== cur.create_default_expert
            }
          >
            {({ getFieldValue }) =>
              getFieldValue("create_default_expert") ? (
                <Form.Item
                  label={t("adminUsers.expertTemplate")}
                  name="expert_template_id"
                  rules={
                    expertTemplates.length > 0
                      ? [
                          {
                            required: true,
                            message: t("adminUsers.expertTemplateRequired"),
                          },
                        ]
                      : []
                  }
                >
                  <ExpertTemplatePicker options={expertTemplates} />
                </Form.Item>
              ) : null
            }
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
