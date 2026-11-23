import { useTranslation } from "react-i18next";

import { Alert } from "antd";

import type { ConnectorCatalogEntry } from "../../../../api/modules/connectors";
import styles from "../index.module.less";

export function ConnectorSetupHints({
  entry,
  authHint,
  guidedKind,
  guideUrl,
  hideGuideLink,
}: {
  entry: ConnectorCatalogEntry;
  authHint?: string | null;
  guidedKind: string | null;
  guideUrl?: string;
  hideGuideLink: boolean;
}) {
  const { t } = useTranslation();

  return (
    <>
      {authHint && <div className={styles.authHint}>{authHint}</div>}

      {entry.kind === "agently-cli" && (
        <>
          <Alert
            type="warning"
            showIcon
            message={t(
              "connectors.agentlySafety",
              "发送、回复、转发和删除邮件需先预览，再由用户确认执行。邮件正文与附件属于不可信外部内容，不能作为执行指令。",
            )}
          />
          <p className={styles.authHint}>
            {t(
              "connectors.agentlyQuota",
              "参考配额：每日发送 50 封、每小时 200 次请求、每分钟 10 次请求；附件最多 50 个、总容量 20 MB，此连接器单文件上限 10 MB。以账户实际配额及服务最新限制为准。可在任务页选择「Agent Mail 新邮件」触发任务。",
            )}
          </p>
          <p className={styles.authHint}>
            {t(
              "connectors.agentlyInstanceHint",
              "先保存连接器，再登录授权。每个实例独立保存邮箱授权，可为不同 Agent 选择不同实例。",
            )}
          </p>
        </>
      )}

      {guidedKind && (
        <div className={styles.guidedSetup}>
          <div className={styles.guidedSetupTitle}>
            {t("connectors.guidedSetup", "快速接入")}
          </div>
          {guidedKind === "weknora" ? (
            <ol>
              <li>
                {t("connectors.weknoraStep1", "打开 WeKnora 并创建 API Key")}
              </li>
              <li>
                {t(
                  "connectors.weknoraStep2",
                  "检测本机服务，或手动填写部署地址",
                )}
              </li>
              <li>
                {t("connectors.guidedStepProbe", "粘贴凭证后探测并保存")}
              </li>
            </ol>
          ) : (
            <ol>
              <li>
                {t("connectors.difyStep1", "在 Dify 中发布应用或工作流")}
              </li>
              <li>
                {t(
                  "connectors.difyStep2",
                  "在访问点启用 MCP 并复制完整 Server URL",
                )}
              </li>
              <li>
                {t("connectors.guidedStepProbe", "粘贴凭证后探测并保存")}
              </li>
            </ol>
          )}
        </div>
      )}

      {guideUrl && !hideGuideLink && (
        <div className={styles.guideLinks}>
          <a href={guideUrl} target="_blank" rel="noreferrer">
            {t("connectors.viewGuide", "查看获取说明")}
          </a>
        </div>
      )}
    </>
  );
}
