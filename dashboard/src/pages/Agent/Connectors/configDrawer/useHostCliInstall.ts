import { useEffect, useState } from "react";
import { message } from "@/utils/antdMessage";
import { useTranslation } from "react-i18next";

import {
  connectorsApi,
  type ConnectorCatalogEntry,
  type ConnectorCliInstallResult,
} from "../../../../api/modules/connectors";
import { apiErrorMessage } from "../../../../utils/apiError";
import { copyText } from "../../../../utils/copyText";
import { isHostCliConnector } from "../connectorHostCli";

export function useHostCliInstall({
  open,
  entry,
}: {
  open: boolean;
  entry: ConnectorCatalogEntry | null;
}) {
  const { t } = useTranslation();
  const [cliInfo, setCliInfo] = useState<ConnectorCliInstallResult | null>(
    null,
  );
  const [installingCli, setInstallingCli] = useState(false);

  useEffect(() => {
    if (!open || !entry) return;
    setCliInfo(null);
    if (isHostCliConnector(entry.kind)) {
      void connectorsApi
        .cliStatus(entry.kind)
        .then(setCliInfo)
        .catch(() => {
          setCliInfo(null);
        });
    }
  }, [open, entry]);

  const handleCopyInstallCommand = async (command: string) => {
    const ok = await copyText(command);
    if (ok) {
      message.success(t("connectors.cliInstallCopied", "安装命令已复制"));
    } else {
      message.error(
        t("connectors.clipboardDenied", "无法读取剪贴板，请手动粘贴"),
      );
    }
  };

  const handleRefreshCliStatus = async () => {
    if (!entry || !isHostCliConnector(entry.kind)) return;
    try {
      const status = await connectorsApi.cliStatus(entry.kind);
      setCliInfo(status);
      if (status.installed) {
        message.success(
          t("connectors.cliAlreadyInstalled", {
            binary: status.binary,
            defaultValue: `${status.binary} 已安装`,
          }),
        );
      }
    } catch (e) {
      console.error(e);
      message.error(
        apiErrorMessage(
          e,
          t("connectors.cliInstallFailed", "主机 CLI 安装失败"),
          t,
        ),
      );
    }
  };

  const handleInstallCli = async () => {
    if (!entry || !isHostCliConnector(entry.kind) || installingCli) return;
    if (cliInfo?.installed) {
      await handleRefreshCliStatus();
      return;
    }
    setInstallingCli(true);
    try {
      const result = await connectorsApi.installCli(entry.kind);
      setCliInfo(result);
      if (result.ok) {
        message.success(
          result.already_installed
            ? t("connectors.cliAlreadyInstalled", {
                binary: result.binary,
                defaultValue: `${result.binary} 已安装`,
              })
            : t("connectors.cliInstallSuccess", {
                binary: result.binary,
                defaultValue: `${result.binary} 安装成功`,
              }),
        );
      } else {
        message.error(
          result.error ?? t("connectors.cliInstallFailed", "主机 CLI 安装失败"),
        );
      }
    } catch (e) {
      console.error(e);
      message.error(
        apiErrorMessage(
          e,
          t("connectors.cliInstallFailed", "主机 CLI 安装失败"),
          t,
        ),
      );
    } finally {
      setInstallingCli(false);
    }
  };

  return {
    cliInfo,
    installingCli,
    handleCopyInstallCommand,
    handleInstallCli,
  };
}
