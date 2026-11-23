import { Button } from "antd";
import {
  CheckCircle2,
  ClipboardPaste,
  Copy,
  Download,
  ExternalLink,
  RefreshCw,
  Sparkles,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import type {
  ConnectorCatalogEntry,
  ConnectorCliInstallResult,
} from "../../../../api/modules/connectors";
import {
  openAuthorizeLabel,
} from "../connectorAuthLabels";
import { isHostCliConnector } from "../connectorHostCli";
import styles from "../index.module.less";

export function ConnectorQuickAuthBar({
  entry,
  guidedKind,
  detectingLocalWeKnora,
  handleDetectLocalWeKnora,
  handleGuidedPaste,
  canInstallCli,
  cliInfo,
  installingCli,
  handleInstallCli,
  handleCopyInstallCommand,
  openUrl,
  hasOAuthPopup,
  authorizing,
  handleOAuth,
  hasAuthorizeUrl,
  hideTopAuth,
  openingAuthorize,
  handleOpenAuthorize,
  hasLoginUrl,
  handleOpenLogin,
  handlePasteToken,
}: {
  entry: ConnectorCatalogEntry;
  guidedKind: string | null;
  detectingLocalWeKnora: boolean;
  handleDetectLocalWeKnora: () => Promise<void>;
  handleGuidedPaste: () => Promise<void>;
  canInstallCli: boolean;
  cliInfo: ConnectorCliInstallResult | null;
  installingCli: boolean;
  handleInstallCli: () => Promise<void>;
  handleCopyInstallCommand: (command: string) => Promise<void>;
  openUrl: (url: string | null | undefined) => void;
  hasOAuthPopup?: boolean;
  authorizing: boolean;
  handleOAuth: () => Promise<void>;
  hasAuthorizeUrl: boolean;
  hideTopAuth: boolean;
  openingAuthorize: boolean;
  handleOpenAuthorize: () => Promise<void>;
  hasLoginUrl: boolean;
  handleOpenLogin: () => void;
  handlePasteToken: () => Promise<void>;
}) {
  const { t } = useTranslation();

  return (
      <div className={styles.quickAuthBar}>
        {guidedKind && (
          <>
            {guidedKind === "weknora" && (
              <Button
                icon={<RefreshCw size={14} />}
                loading={detectingLocalWeKnora}
                onClick={() => void handleDetectLocalWeKnora()}
              >
                {t("connectors.detectLocal", "检测本机服务")}
              </Button>
            )}
            <Button
              icon={<ClipboardPaste size={14} />}
              onClick={() => void handleGuidedPaste()}
            >
              {guidedKind === "dify"
                ? t("connectors.pasteMcpUrl", "粘贴 MCP 地址")
                : t("connectors.smartPaste", "智能粘贴")}
            </Button>
          </>
        )}
        {entry && isHostCliConnector(entry.kind) && (
          <>
            {canInstallCli && (
              <Button
                type={cliInfo?.installed ? "default" : "primary"}
                icon={
                  cliInfo?.installed ? (
                    <CheckCircle2 size={14} />
                  ) : (
                    <Download size={14} />
                  )
                }
                loading={installingCli}
                onClick={() => void handleInstallCli()}
              >
                {cliInfo?.installed
                  ? t("connectors.cliReady", "CLI 已就绪")
                  : t("connectors.installCli", "安装 CLI")}
              </Button>
            )}
            {!canInstallCli && cliInfo?.installed && (
              <Button
                type="default"
                icon={<CheckCircle2 size={14} />}
                disabled
              >
                {t("connectors.cliReady", "CLI 已就绪")}
              </Button>
            )}
            {!canInstallCli && !cliInfo?.installed && (
              <span className={styles.feishuUserAuthHint}>
                {t(
                  "connectors.cliInstallAdminOnly",
                  "需在本机终端安装，可复制命令直接执行",
                )}
              </span>
            )}
            {(cliInfo?.install_command ||
              entry.kind === "feishu-cli" ||
              entry.kind === "wecom-cli") && (
              <Button
                icon={<Copy size={14} />}
                onClick={() =>
                  void handleCopyInstallCommand(
                    cliInfo?.install_command ??
                      (entry.kind === "feishu-cli"
                        ? "npm install -g @larksuite/cli"
                        : "npm install -g @wecom/cli"),
                  )
                }
              >
                {t("connectors.copyInstallCommand", "复制安装命令")}
              </Button>
            )}
            {(cliInfo?.guide_url ||
              cliInfo?.doc_url ||
              entry.guide_url ||
              entry.doc_url) && (
              <Button
                icon={<ExternalLink size={14} />}
                onClick={() =>
                  openUrl(
                    cliInfo?.guide_url ||
                      entry.guide_url ||
                      cliInfo?.doc_url ||
                      entry.doc_url,
                  )
                }
              >
                {t("connectors.openCliDocs", "安装文档")}
              </Button>
            )}
          </>
        )}
        {hasOAuthPopup && (
          <Button
            type="primary"
            icon={<Sparkles size={14} />}
            loading={authorizing}
            onClick={() => void handleOAuth()}
          >
            {t("connectors.oneClickOAuth", "一键授权")}
          </Button>
        )}
        {hasAuthorizeUrl && !hideTopAuth && !hasOAuthPopup && (
          <Button
            type="primary"
            icon={<ExternalLink size={14} />}
            loading={openingAuthorize}
            onClick={() => void handleOpenAuthorize()}
          >
            {entry.kind === "qcc"
              ? t("connectors.qccOpenKeyPage", "打开授权页")
              : t("connectors.openAuthorizePage", "打开授权页")}
          </Button>
        )}
        {hasOAuthPopup && entry.kind === "qcc" && hasAuthorizeUrl && (
          <Button
            icon={<ExternalLink size={14} />}
            loading={openingAuthorize}
            onClick={() => void handleOpenAuthorize()}
          >
            {t("connectors.qccOpenKeyPage", "打开授权页")}
          </Button>
        )}
        {hasLoginUrl && !hideTopAuth && (
          <Button icon={<ExternalLink size={14} />} onClick={handleOpenLogin}>
            {t("connectors.openLoginPage", "打开登录页")}
          </Button>
        )}
        {!hideTopAuth &&
          !hasAuthorizeUrl &&
          !hasLoginUrl &&
          entry.quick_auth_url &&
          entry.auth_kind !== "oauth2" && (
            <Button
              type="primary"
              icon={<ExternalLink size={14} />}
              loading={openingAuthorize}
              onClick={() => void handleOpenAuthorize()}
            >
              {openAuthorizeLabel(entry.kind, t)}
            </Button>
          )}
        {(entry.auth_kind === "personal_token" ||
          entry.auth_kind === "auth_code" ||
          (entry.auth_kind === "api_key" &&
            entry.kind !== "feishu-cli" &&
            entry.kind !== "wecom-cli")) && (
          <Button
            icon={<ClipboardPaste size={14} />}
            onClick={() => void handlePasteToken()}
          >
            {t("connectors.pasteFromClipboard", "从剪贴板粘贴")}
          </Button>
        )}
      </div>
  );
}
