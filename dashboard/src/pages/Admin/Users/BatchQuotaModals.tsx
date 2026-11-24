/**
 * Modals for the batch quota actions: set a token quota or a max-agent limit
 * on every selected user.
 */

import { Form, Modal, Switch, Typography } from "antd";
import type { FormInstance } from "antd";
import { useTranslation } from "react-i18next";

import { MaxAgentsInput, TokenQuotaInput } from "./QuotaInputs";
import type {
  BatchMaxAgentsFormValues,
  BatchTokenFormValues,
} from "./usersListTypes";

const { Text } = Typography;

export function BatchTokenQuotaModal({
  open,
  count,
  submitting,
  onCancel,
  form,
  onSubmit,
}: {
  open: boolean;
  count: number;
  submitting: boolean;
  onCancel: () => void;
  form: FormInstance<BatchTokenFormValues>;
  onSubmit: (values: BatchTokenFormValues) => Promise<void>;
}) {
  const { t } = useTranslation();
  return (
    <Modal
      title={t("adminUsers.batchSetTokenTitle", { count })}
      open={open}
      onCancel={onCancel}
      onOk={() => form.submit()}
      okText={t("common.confirm")}
      cancelText={t("common.cancel")}
      confirmLoading={submitting}
      destroyOnHidden
    >
      <Text type="secondary" style={{ display: "block", marginBottom: 12 }}>
        {t("adminUsers.batchSetTokenHint")}
      </Text>
      <Form<BatchTokenFormValues>
        form={form}
        layout="vertical"
        onFinish={(values) => void onSubmit(values)}
      >
        <Form.Item
          label={t("adminUsers.policyTokenQuota")}
          extra={t("adminUsers.policyTokenQuotaHint")}
        >
          <Form.Item name="limit_token_quota" valuePropName="checked" noStyle>
            <Switch />
          </Form.Item>
        </Form.Item>
        <Form.Item
          noStyle
          shouldUpdate={(prev, cur) =>
            prev.limit_token_quota !== cur.limit_token_quota
          }
        >
          {({ getFieldValue }) =>
            getFieldValue("limit_token_quota") ? (
              <Form.Item
                name="token_quota"
                rules={[
                  {
                    required: true,
                    message: t("adminUsers.policyTokenQuotaRequired"),
                  },
                ]}
              >
                <TokenQuotaInput />
              </Form.Item>
            ) : null
          }
        </Form.Item>
      </Form>
    </Modal>
  );
}

export function BatchMaxAgentsModal({
  open,
  count,
  submitting,
  onCancel,
  form,
  onSubmit,
}: {
  open: boolean;
  count: number;
  submitting: boolean;
  onCancel: () => void;
  form: FormInstance<BatchMaxAgentsFormValues>;
  onSubmit: (values: BatchMaxAgentsFormValues) => Promise<void>;
}) {
  const { t } = useTranslation();
  return (
    <Modal
      title={t("adminUsers.batchSetMaxAgentsTitle", { count })}
      open={open}
      onCancel={onCancel}
      onOk={() => form.submit()}
      okText={t("common.confirm")}
      cancelText={t("common.cancel")}
      confirmLoading={submitting}
      destroyOnHidden
    >
      <Text type="secondary" style={{ display: "block", marginBottom: 12 }}>
        {t("adminUsers.batchSetMaxAgentsHint")}
      </Text>
      <Form<BatchMaxAgentsFormValues>
        form={form}
        layout="vertical"
        onFinish={(values) => void onSubmit(values)}
      >
        <Form.Item
          label={t("adminUsers.policyMaxAgents")}
          extra={t("adminUsers.policyMaxAgentsHint")}
        >
          <Form.Item name="limit_max_agents" valuePropName="checked" noStyle>
            <Switch />
          </Form.Item>
        </Form.Item>
        <Form.Item
          noStyle
          shouldUpdate={(prev, cur) =>
            prev.limit_max_agents !== cur.limit_max_agents
          }
        >
          {({ getFieldValue }) =>
            getFieldValue("limit_max_agents") ? (
              <Form.Item
                name="max_agents"
                rules={[
                  {
                    required: true,
                    message: t("adminUsers.policyMaxAgentsRequired"),
                  },
                ]}
              >
                <MaxAgentsInput />
              </Form.Item>
            ) : null
          }
        </Form.Item>
      </Form>
    </Modal>
  );
}
