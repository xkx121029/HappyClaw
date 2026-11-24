import { useTranslation } from "react-i18next";

import { CheckCircle2 } from "lucide-react";

import styles from "../index.module.less";

export function ConnectorProbeResult({
  tools,
}: {
  tools: { name: string; description: string }[];
}) {
  const { t } = useTranslation();

  return (
    <div className={styles.probeResult}>
      <div className={styles.probeResultHeader}>
        <CheckCircle2
          size={18}
          className={styles.probeResultIcon}
          aria-hidden
        />
        <div className={styles.probeResultMeta}>
          <div className={styles.probeResultTitle}>
            {t("connectors.probeToolsTitle", "探测成功")}
          </div>
          <div className={styles.probeResultSubtitle}>
            {tools.length > 0
              ? t("connectors.probeToolsHint", {
                  count: tools.length,
                  defaultValue: `连接正常，获取以下工具列表（共 ${tools.length} 个）`,
                })
              : t(
                  "connectors.probeToolsEmpty",
                  "连接正常，但未发现可用工具",
                )}
          </div>
        </div>
      </div>
      {tools.length > 0 && (
        <ul className={styles.probeToolList}>
          {tools.map((tool, index) => (
            <li key={tool.name} className={styles.probeToolItem}>
              <span className={styles.probeToolIndex}>{index + 1}</span>
              <div className={styles.probeToolBody}>
                <div className={styles.probeToolName}>{tool.name}</div>
                {tool.description ? (
                  <div className={styles.probeToolDesc}>
                    {tool.description}
                  </div>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
