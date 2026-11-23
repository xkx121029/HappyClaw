/**
 * Modal for resetting one user's password.
 */

import { Form, Input, Modal, Typography } from "antd";
import type { FormInstance } from "antd";
import { Lock, LockOpen } from "lucide-react";
import { useTranslation } from "react-i18next";

import type { ResetValues } from "./usersListTypes";

const { Text } = Typography;

export function UserResetPasswordModal({
  username,
  open,
  onCancel,
  form,
  submitting,
  onSubmit,
}: {
  username: string | null;
  open: boolean;
  onCancel: () => void;
  form: FormInstance<ResetValues>;
  submitting: boolean;
  onSubmit: (values: ResetValues) => Promise<void>;
}) {
  const { t } = useTranslation();
  return (
    <Modal
      title={
        username ? t("adminUsers.modalResetTitle", { username }) : ""
      }
      open={open}
      onCancel={onCancel}
      onOk={() => form.submit()}
      okText={t("common.reset")}
      cancelText={t("common.cancel")}
      confirmLoading={submitting}
    >
      <Text type="secondary" style={{ display: "block", marginBottom: 8 }}>
        {t("adminUsers.resetHint")}
      </Text>
      <Form<ResetValues> form={form} layout="vertical" onFinish={onSubmit}>
        <Form.Item
          label={t("adminUsers.newPassword")}
          name="password"
          rules={[
            { required: true, message: t("adminUsers.newPasswordRequired") },
          ]}
        >
          <Input.Password
            autoComplete="new-password"
            prefix={
              <Lock size={14} style={{ color: "var(--fn-text-tertiary)" }} />
            }
          />
        </Form.Item>
        <Form.Item
          label={t("adminUsers.formPasswordConfirm")}
          name="confirm"
          dependencies={["password"]}
          rules={[
            { required: true, message: t("adminUsers.formPasswordConfirm") },
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
            autoComplete="new-password"
            prefix={
              <LockOpen size={14} style={{ color: "var(--fn-text-tertiary)" }} />
            }
          />
        </Form.Item>
      </Form>
    </Modal>
  );
}
