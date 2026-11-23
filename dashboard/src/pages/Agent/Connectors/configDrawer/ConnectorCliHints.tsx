import { useTranslation } from "react-i18next";

import type {
  ConnectorCatalogEntry,
  ConnectorCliInstallResult,
} from "../../../../api/modules/connectors";
import { isHostCliConnector } from "../connectorHostCli";
import styles from "../index.module.less";

export function ConnectorCliHints({
  entry,
  cliInfo,
}: {
  entry: ConnectorCatalogEntry;
  cliInfo: ConnectorCliInstallResult | null;
}) {
  const { t } = useTranslation();

  return (
    <>
      {entry && isHostCliConnector(entry.kind) && cliInfo && (
        <div
          className={
            cliInfo.ok === false || !cliInfo.installed
              ? styles.cliInstallHintError
              : styles.cliInstallHint
          }
        >
          {cliInfo.installed ? (
            <div>
              {t("connectors.cliInstalledHint", {
                binary: cliInfo.binary,
                version: cliInfo.version ?? "",
                defaultValue: cliInfo.version
                  ? `主机已检测到 ${cliInfo.binary}（${cliInfo.version}）`
                  : `主机已检测到 ${cliInfo.binary}`,
              })}
            </div>
          ) : (
            <div>
              {cliInfo.error ??
                t(
                  "connectors.cliMissingHint",
                  "主机尚未安装 CLI。可点击「安装 CLI」，或在 HappyClaw 主机终端手动执行下方命令。",
                )}
            </div>
          )}
          {(!cliInfo.installed || cliInfo.ok === false) &&
            cliInfo.install_command && (
              <code className={styles.cliInstallCommand}>
                {cliInfo.install_command}
              </code>
            )}
          {(!cliInfo.installed || cliInfo.ok === false) && (
            <div className={styles.cliInstallLinks}>
              {(cliInfo.guide_url || entry.guide_url) && (
                <a
                  href={cliInfo.guide_url || entry.guide_url || undefined}
                  target="_blank"
                  rel="noreferrer"
                >
                  {t("connectors.openCliDocs", "安装文档")}
                </a>
              )}
              {(cliInfo.doc_url || entry.doc_url) && (
                <a
                  href={cliInfo.doc_url || entry.doc_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  {t("connectors.openCliRepo", "项目主页")}
                </a>
              )}
            </div>
          )}
        </div>
      )}

      {entry?.kind === "obsidian-cli" && (
        <div className={styles.cliInstallHint}>
          <a
            href="https://obsidian.md/zh/cli"
            target="_blank"
            rel="noreferrer"
          >
            {t(
              "connectors.obsidianCliGuide",
              "Obsidian-cli官方安装指引：https://obsidian.md/zh/cli",
            )}
          </a>
        </div>
      )}
    </>
  );
}
