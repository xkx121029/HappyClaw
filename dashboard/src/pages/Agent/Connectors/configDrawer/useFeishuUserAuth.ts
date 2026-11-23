import { useEffect, useState } from "react";
import { message } from "@/utils/antdMessage";
import type { FormInstance } from "antd";
import { useTranslation } from "react-i18next";

import {
  connectorsApi,
  type ConnectorCatalogEntry,
  type ConnectorInstance,
  type ConnectorInstanceDetail,
  type FeishuUserAuthStartResult,
} from "../../../../api/modules/connectors";
import { apiErrorMessage } from "../../../../utils/apiError";
import { navigateAuthWindow } from "../openAuthWindow";
import { openAuthPopupPlaceholder } from "./authPopup";

export function useFeishuUserAuth({
  open,
  entry,
  instance,
  instanceDetail,
  hasStoredCredentials,
  form,
}: {
  open: boolean;
  entry: ConnectorCatalogEntry | null;
  instance: ConnectorInstance | null;
  instanceDetail: ConnectorInstanceDetail | null;
  hasStoredCredentials: boolean;
  form: FormInstance;
}) {
  const { t } = useTranslation();
  const [feishuUserAuth, setFeishuUserAuth] =
    useState<FeishuUserAuthStartResult | null>(null);
  const [feishuUserAuthBusy, setFeishuUserAuthBusy] = useState(false);
  const [feishuUserReady, setFeishuUserReady] = useState(false);
  const [feishuAuthNeedsReauth, setFeishuAuthNeedsReauth] = useState(false);
  const [feishuRefreshExpiresAt, setFeishuRefreshExpiresAt] = useState<
    string | null
  >(null);

  useEffect(() => {
    if (!open || !entry) return;
    setFeishuUserAuth(null);
    setFeishuUserReady(false);
    setFeishuAuthNeedsReauth(false);
    setFeishuRefreshExpiresAt(null);
  }, [open, entry, instance]);

  const preview = instanceDetail?.credentials_preview;
  useEffect(() => {
    if (!preview?.user_auth_configured) return;
    const needs =
      preview.user_auth_needs_reauth === true ||
      preview.user_auth_valid === false;
    setFeishuAuthNeedsReauth(needs);
    setFeishuUserReady(!needs);
    setFeishuRefreshExpiresAt(preview.user_refresh_expires_at ?? null);
  }, [preview]);

  const handleFeishuUserAuthStart = async () => {
    if (!entry || entry.kind !== "feishu-cli" || feishuUserAuthBusy) return;
    const popup = openAuthPopupPlaceholder();
    setFeishuUserAuthBusy(true);
    try {
      let started: FeishuUserAuthStartResult;
      if (instance?.instance_id && hasStoredCredentials) {
        started = await connectorsApi.feishuUserAuthStartInstance(
          instance.instance_id,
        );
      } else {
        try {
          await form.validateFields(["app_id", "app_secret"]);
        } catch {
          popup?.close();
          message.warning(
            t(
              "connectors.feishuUserAuthNeedApp",
              "请先填写 App ID 与 App Secret",
            ),
          );
          return;
        }
        const values = form.getFieldsValue();
        const app_id = String(values.app_id ?? "").trim();
        const app_secret = String(values.app_secret ?? "").trim();
        if (!app_id || !app_secret) {
          popup?.close();
          message.warning(
            t(
              "connectors.feishuUserAuthNeedApp",
              "请先填写 App ID 与 App Secret",
            ),
          );
          return;
        }
        started = await connectorsApi.feishuUserAuthStart({
          app_id,
          app_secret,
          cli_config_key:
            String(values.cli_config_key ?? "").trim() || undefined,
        });
      }
      form.setFieldsValue({ cli_config_key: started.cli_config_key });
      setFeishuUserAuth(started);
      setFeishuUserReady(false);
      navigateAuthWindow(popup, started.verification_url);
      message.success(
        t(
          "connectors.feishuUserAuthStarted",
          "已打开授权页，完成后点「我已授权」",
        ),
      );
    } catch (e) {
      popup?.close();
      console.error(e);
      message.error(
        apiErrorMessage(e, t("connectors.feishuUserAuthFailed", "授权失败"), t),
      );
    } finally {
      setFeishuUserAuthBusy(false);
    }
  };

  const handleFeishuUserAuthComplete = async () => {
    if (!entry || entry.kind !== "feishu-cli" || !feishuUserAuth) return;
    setFeishuUserAuthBusy(true);
    try {
      let done;
      if (instance?.instance_id && hasStoredCredentials) {
        done = await connectorsApi.feishuUserAuthCompleteInstance(
          instance.instance_id,
          {
            device_code: feishuUserAuth.device_code,
            cli_config_key: feishuUserAuth.cli_config_key,
          },
        );
      } else {
        const values = form.getFieldsValue();
        const app_id = String(values.app_id ?? "").trim();
        const app_secret = String(values.app_secret ?? "").trim();
        const cli_config_key = String(
          values.cli_config_key ?? feishuUserAuth.cli_config_key ?? "",
        ).trim();
        if (!app_id || !app_secret || !cli_config_key) {
          message.warning(
            t(
              "connectors.feishuUserAuthNeedApp",
              "请先填写 App ID 与 App Secret",
            ),
          );
          return;
        }
        done = await connectorsApi.feishuUserAuthComplete({
          app_id,
          app_secret,
          device_code: feishuUserAuth.device_code,
          cli_config_key,
        });
      }
      form.setFieldsValue({
        default_as: "user",
        cli_config_key: done.cli_config_key,
      });
      setFeishuUserReady(true);
      setFeishuAuthNeedsReauth(false);
      setFeishuUserAuth(null);
      const persisted = Boolean(instance?.instance_id) && hasStoredCredentials;
      if (done.warning || done.search_docs_scope === false) {
        message.warning(
          done.warning ||
            t(
              "connectors.feishuUserAuthWarning",
              "已登录，但文档搜索权限可能未开通，请检查开放平台权限后重新授权",
            ),
        );
      } else {
        message.success(
          persisted
            ? t("connectors.feishuUserAuthSuccessSaved", "授权完成")
            : t("connectors.feishuUserAuthSuccess", "授权完成，请保存连接器"),
        );
      }
    } catch (e) {
      console.error(e);
      message.error(
        apiErrorMessage(e, t("connectors.feishuUserAuthFailed", "授权失败"), t),
      );
    } finally {
      setFeishuUserAuthBusy(false);
    }
  };

  return {
    feishuUserAuth,
    feishuUserAuthBusy,
    feishuUserReady,
    feishuAuthNeedsReauth,
    feishuRefreshExpiresAt,
    handleFeishuUserAuthStart,
    handleFeishuUserAuthComplete,
  };
}
