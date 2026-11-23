import { useState } from "react";
import { message } from "@/utils/antdMessage";
import type { FormInstance } from "antd";
import { useTranslation } from "react-i18next";

import {
  connectorsApi,
  type ConnectorCatalogEntry,
  type ConnectorInstance,
} from "../../../../api/modules/connectors";
import type { ResourceVisibilityMode } from "../../../../api/modules/userGroups";
import { apiErrorMessage } from "../../../../utils/apiError";
import { clearFormDraft } from "../../../../utils/formDraft";
import { visibilityFields } from "../connectorFormValues";
import {
  isAuthPopupBlocked,
  navigateAuthWindow,
  tryOpenAuthPopup,
} from "../openAuthWindow";

export function useConnectorOAuth({
  entry,
  instance,
  form,
  connectorVisibility,
  connectorGroupIds,
  draftScope,
  onSaved,
  onClose,
}: {
  entry: ConnectorCatalogEntry | null;
  instance: ConnectorInstance | null;
  form: FormInstance;
  connectorVisibility: ResourceVisibilityMode;
  connectorGroupIds: string[];
  draftScope: string;
  onSaved: () => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [authorizing, setAuthorizing] = useState(false);

  const handleOAuth = async () => {
    if (!entry || authorizing) return;
    const popup = tryOpenAuthPopup("", "octop-oauth", "width=520,height=720");
    if (isAuthPopupBlocked(popup)) {
      message.error(
        t(
          "connectors.oauthPopupBlocked",
          "授权窗口被浏览器拦截，请允许本站弹出窗口后重试",
        ),
      );
      return;
    }

    setAuthorizing(true);
    let settled = false;
    let pollTimer: ReturnType<typeof setInterval> | undefined;
    let timeoutTimer: ReturnType<typeof setTimeout> | undefined;
    let stateId = "";

    const cleanup = () => {
      if (pollTimer !== undefined) clearInterval(pollTimer);
      if (timeoutTimer !== undefined) clearTimeout(timeoutTimer);
      window.removeEventListener("message", onMessage);
    };

    const finishWithTokens = async (tokens: Record<string, unknown>) => {
      if (settled) return;
      settled = true;
      cleanup();
      try {
        popup?.close();
      } catch {
        // ignore
      }
      try {
        const values = form.getFieldsValue();
        const credentials: Record<string, unknown> = {};
        if (tokens.access_token) credentials.access_token = tokens.access_token;
        if (tokens.refresh_token)
          credentials.refresh_token = tokens.refresh_token;
        if (tokens.expires_at) credentials.expires_at = tokens.expires_at;
        if (tokens.oauth_client_id)
          credentials.oauth_client_id = tokens.oauth_client_id;
        if (tokens.oauth_client_secret)
          credentials.oauth_client_secret = tokens.oauth_client_secret;
        if (tokens.openid) credentials.openid = tokens.openid;

        if (!credentials.access_token) {
          message.error(t("connectors.oauthFailed", "获取授权结果失败"));
          return;
        }

        if (
          connectorVisibility === "groups" &&
          connectorGroupIds.length === 0
        ) {
          message.error(t("resourceVisibility.needGroup"));
          return;
        }
        const share = visibilityFields(connectorVisibility, connectorGroupIds);
        if (instance) {
          await connectorsApi.patchInstance(instance.instance_id, {
            display_name: String(values.display_name || entry.name),
            description: String(values.description || entry.description),
            credentials,
            default_open: values.default_open === true,
            ...share,
          });
        } else {
          await connectorsApi.createInstance({
            kind: entry.kind,
            display_name: String(values.display_name || entry.name),
            description: String(values.description || entry.description),
            credentials,
            default_open: values.default_open === true,
            ...share,
          });
        }
        clearFormDraft(draftScope);
        message.success(t("connectors.createSuccess", "连接器已创建"));
        onSaved();
        onClose();
      } catch (e) {
        console.error(e);
        form.setFieldsValue({
          display_name: entry.name,
          description: entry.description,
          access_token: tokens.access_token,
          refresh_token: tokens.refresh_token,
          expires_at: tokens.expires_at,
          oauth_client_id: tokens.oauth_client_id,
          oauth_client_secret: tokens.oauth_client_secret,
          openid: tokens.openid,
        });
        message.error(
          apiErrorMessage(e, t("connectors.createFailed", "创建失败"), t),
        );
      } finally {
        setAuthorizing(false);
      }
    };

    const claimPending = async () => {
      if (settled || !stateId) return;
      try {
        const pending = await connectorsApi.oauthPending(stateId);
        await finishWithTokens(pending.tokens ?? {});
      } catch {
        // Pending not ready yet (404) — keep polling.
      }
    };

    const onMessage = (ev: MessageEvent) => {
      if (ev.origin !== window.location.origin) return;
      if (ev.data?.type !== "octop:connector-oauth") return;
      if (ev.data.state_id !== stateId) return;
      void claimPending();
    };

    try {
      const { authorize_url, state_id } = await connectorsApi.oauthStart(
        { type: "catalog", kind: entry.kind },
        "/connectors",
      );
      stateId = state_id;
      window.addEventListener("message", onMessage);
      // Ardot (and some IdPs) set COOP so window.opener is null after redirect;
      // poll pending so the parent still claims tokens without postMessage.
      pollTimer = setInterval(() => {
        void claimPending();
      }, 1500);
      timeoutTimer = setTimeout(
        () => {
          if (settled) return;
          settled = true;
          cleanup();
          try {
            popup?.close();
          } catch {
            // ignore
          }
          setAuthorizing(false);
          message.error(
            t("connectors.oauthTimedOut", "授权超时，请重试一键授权"),
          );
        },
        5 * 60 * 1000,
      );
      navigateAuthWindow(popup, authorize_url);
    } catch (e) {
      cleanup();
      try {
        popup?.close();
      } catch {
        // ignore
      }
      console.error(e);
      message.error(
        apiErrorMessage(e, t("connectors.oauthStartFailed", "无法启动 OAuth")),
      );
      setAuthorizing(false);
    }
  };

  return { authorizing, handleOAuth };
}
