/**
 * Resource-policy section of the user and role forms: workspace root
 * restriction, token quota and max-agent limits.
 */

import { Form, Switch } from "antd";
import cx from "classnames";
import { useTranslation } from "react-i18next";

import RootDirSelect from "../../Experts/components/RootDirSelect";
import styles from "./index.module.less";
import { MaxAgentsInput, TokenQuotaInput } from "./QuotaInputs";

export function ResourcePolicyFields({
  fsTreeRoots,
  workspaceRootAllowed,
}: {
  fsTreeRoots: string[];
  workspaceRootAllowed: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div className={cx(styles.createSection, styles.policySection)}>
      <div className={styles.createSectionTitle}>
        {t("adminUsers.createSectionPolicy")}
      </div>
      <Form.Item
        label={t("adminUsers.policyWorkspaceRoot")}
        extra={
          workspaceRootAllowed
            ? t("adminUsers.policyWorkspaceRootHint", {
                localShell: t("experts.backendModes.localShell"),
                filesystem: t("experts.backendModes.filesystem"),
              })
            : t("adminUsers.policyWorkspaceRootContainerHint")
        }
      >
        <Form.Item name="limit_workspace_root" valuePropName="checked" noStyle>
          <Switch disabled={!workspaceRootAllowed} />
        </Form.Item>
      </Form.Item>
      {workspaceRootAllowed ? (
        <Form.Item
          noStyle
          shouldUpdate={(prev, cur) =>
            prev.limit_workspace_root !== cur.limit_workspace_root
          }
        >
          {({ getFieldValue }) =>
            getFieldValue("limit_workspace_root") ? (
              <Form.Item
                name="workspace_root_dir"
                rules={[
                  {
                    required: true,
                    message: t("adminUsers.policyWorkspaceRootRequired"),
                  },
                ]}
              >
                <RootDirSelect treeRoots={fsTreeRoots} />
              </Form.Item>
            ) : null
          }
        </Form.Item>
      ) : null}
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
    </div>
  );
}
