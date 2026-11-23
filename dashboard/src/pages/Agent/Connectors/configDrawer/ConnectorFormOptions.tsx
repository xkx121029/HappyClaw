import { Alert, Form, Switch } from "antd";
import { useTranslation } from "react-i18next";

import {
  ResourceVisibilityFields,
  ResourceVisibilityGate,
} from "../../../../components/ResourceVisibilityFields";
import type { ResourceVisibilityMode } from "../../../../api/modules/userGroups";
import styles from "../index.module.less";

export function ConnectorFormOptions({
  defaultOpen,
  visibility,
  groupIds,
  onVisibilityChange,
}: {
  defaultOpen: boolean;
  visibility: ResourceVisibilityMode;
  groupIds: string[];
  onVisibilityChange: (
    visibility: ResourceVisibilityMode,
    groupIds: string[],
  ) => void;
}) {
  const { t } = useTranslation();

  return (
    <>
      <div className={styles.formOptions}>
        <div className={styles.formOptionRow}>
          <div className={styles.formOptionCopy}>
            <span className={styles.switchLabel}>
              {t("connectors.defaultEnabled", "是否默认开启")}
            </span>
            <span className={styles.formOptionHint}>
              {t(
                "connectors.defaultOpenHint",
                "关闭时需在对话中手动勾选才会注入工具。",
              )}
            </span>
          </div>
          <Form.Item name="default_open" valuePropName="checked" noStyle>
            <Switch size="small" />
          </Form.Item>
        </div>
        <ResourceVisibilityGate allowOwner visibility={visibility}>
          <div className={styles.formOptionRowVisibility}>
            <div className={styles.formOptionCopy}>
              <span className={styles.switchLabel}>
                {t("resourceVisibility.label")}
              </span>
              <span className={styles.formOptionHint}>
                {t("connectors.visibilityHint")}
              </span>
            </div>
            <ResourceVisibilityFields
              allowOwner
              visibility={visibility}
              groupIds={groupIds}
              onChange={(next) =>
                onVisibilityChange(
                  next.visibility,
                  next.visibility === "groups" ? next.groupIds : [],
                )
              }
            />
          </div>
        </ResourceVisibilityGate>
      </div>
      {defaultOpen ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginTop: 12, marginBottom: 0 }}
          message={t(
            "connectors.defaultOpenWarning",
            "开启后默认会在 Dashboard、IM 与 Cron（未特殊选连接器时）携带该工具（额外消耗 token）。Dashboard 可关本轮；Cron 若显式选择连接器则以选择为准。",
          )}
        />
      ) : null}
    </>
  );
}
