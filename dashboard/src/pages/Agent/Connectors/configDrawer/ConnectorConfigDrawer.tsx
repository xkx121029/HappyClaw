import { useCallback, useEffect, useRef, useState } from "react";
import { Button, Drawer, Form, Input, Spin } from "antd";
import { message } from "@/utils/antdMessage";

import {
  Activity,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { TextAssistBar } from "../../../../components/TextAssistBar";
import type { ResourceVisibilityMode } from "../../../../api/modules/userGroups";
import { useCurrentUser } from "../../../../hooks/useCurrentUser";
import { useIsMobile } from "../../../../hooks/useIsMobile";
import { PERM, userCanAny } from "../../../../utils/permissions";
import { apiErrorMessage, probeErrorMessage } from "../../../../utils/apiError";
import { copyText } from "../../../../utils/copyText";
import {
  clearFormDraft,
  loadFormDraft,
  saveFormDraft,
} from "../../../../utils/formDraft";
import {
  connectorsApi,
  type ConnectorAuthInfo,
  type ConnectorCatalogEntry,
  type ConnectorCliInstallResult,
  type ConnectorInstance,
  type ConnectorInstanceDetail,
  type FeishuUserAuthStartResult,
} from "../../../../api/modules/connectors";
import { AgentlyAuth } from "../AgentlyAuth";
import { ConnectorSetupHints } from "./ConnectorSetupHints";
import { ConnectorCredentialFields } from "./ConnectorCredentialFields";
import { ConnectorCliHints } from "./ConnectorCliHints";
import { ConnectorQuickAuthBar } from "./ConnectorQuickAuthBar";
import { ConnectorFormOptions } from "./ConnectorFormOptions";
import { ConnectorProbeResult } from "./ConnectorProbeResult";
import {
  buildCredentials,
  customCredentialConfigChanged,
  hasFreshCredentialInput,
} from "../connectorCredentials";
import {
  INLINE_CREDENTIAL_GUIDE_KINDS,
  HIDE_INLINE_FIELD_GUIDE_KINDS,
  mailProviderById,
} from "../connectorDefs";
import {
  previewToFormValues,
  visibilityFields,
  visibilityFromDetail,
} from "../connectorFormValues";
import { isHostCliConnector } from "../connectorHostCli";
import {
  extractHttpUrl,
  isGuidedConnector,
} from "../guidedConnectorUtils";
import { oauthCallbackSupported } from "../oauthCallback";
import {
  isAuthPopupBlocked,
  navigateAuthWindow,
  openExternalBrowserUrl,
  tryOpenAuthPopup,
} from "../openAuthWindow";
import styles from "../index.module.less";

export function ConnectorConfigDrawer({
  open,
  entry,
  instance,
  onClose,
  onSaved,
}: {
  open: boolean;
  entry: ConnectorCatalogEntry | null;
  instance: ConnectorInstance | null;
  onClose: () => void;
  onSaved: (created?: ConnectorInstance) => void;
}) {
  const { t } = useTranslation();
  const isMobile = useIsMobile();
  const user = useCurrentUser();
  const canInstallCli = userCanAny(user, PERM.connectors);
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const [probing, setProbing] = useState(false);
  const [authorizing, setAuthorizing] = useState(false);
  const [openingAuthorize, setOpeningAuthorize] = useState(false);
  const [showManual, setShowManual] = useState(false);
  const [authInfo, setAuthInfo] = useState<ConnectorAuthInfo | null>(null);
  const [instanceDetail, setInstanceDetail] =
    useState<ConnectorInstanceDetail | null>(null);
  const [probeResult, setProbeResult] = useState<
    { name: string; description: string }[] | null
  >(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [cliInfo, setCliInfo] = useState<ConnectorCliInstallResult | null>(
    null,
  );
  const [installingCli, setInstallingCli] = useState(false);
  const [detectingLocalWeKnora, setDetectingLocalWeKnora] = useState(false);
  const [feishuUserAuth, setFeishuUserAuth] =
    useState<FeishuUserAuthStartResult | null>(null);
  const [feishuUserAuthBusy, setFeishuUserAuthBusy] = useState(false);
  const [feishuUserReady, setFeishuUserReady] = useState(false);
  const [feishuAuthNeedsReauth, setFeishuAuthNeedsReauth] = useState(false);
  const [feishuRefreshExpiresAt, setFeishuRefreshExpiresAt] = useState<
    string | null
  >(null);
  const [connectorVisibility, setConnectorVisibility] =
    useState<ResourceVisibilityMode>("owner");
  const [connectorGroupIds, setConnectorGroupIds] = useState<string[]>([]);

  const hasStoredCredentials = Boolean(
    instanceDetail?.has_credentials ?? instance?.has_credentials,
  );
  const mailProvider = Form.useWatch("mail_provider", form) ?? "qq";
  const defaultOpen = Form.useWatch("default_open", form) === true;
  const selectedMailProvider = mailProviderById(String(mailProvider));
  const draftScope = entry
    ? instance
      ? `connector:${instance.instance_id}`
      : `connector:new:${entry.kind}`
    : "";
  const restoringDraftRef = useRef(false);

  const applyConnectorDraft = useCallback(() => {
    if (!draftScope) return;
    const draft = loadFormDraft(draftScope);
    if (!draft) return;
    restoringDraftRef.current = true;
    form.setFieldsValue(draft);
    restoringDraftRef.current = false;
  }, [draftScope, form]);

  useEffect(() => {
    if (!open || !entry) return;
    setShowManual(false);
    setAuthInfo(null);
    setInstanceDetail(null);
    setProbeResult(null);
    setCliInfo(null);
    setFeishuUserAuth(null);
    setFeishuUserReady(false);
    setFeishuAuthNeedsReauth(false);
    setFeishuRefreshExpiresAt(null);
    form.resetFields();
    form.setFieldsValue({
      display_name: entry.name,
      description: entry.description,
      default_open: false,
    });
    setConnectorVisibility("owner");
    setConnectorGroupIds([]);

    void connectorsApi
      .authInfo(entry.kind)
      .then(setAuthInfo)
      .catch(() => {
        setAuthInfo({
          authorize_url: entry.quick_auth_url ?? null,
          login_url: entry.login_url ?? null,
          guide_url: entry.guide_url ?? entry.doc_url ?? null,
          manual_url:
            entry.manual_url ?? entry.guide_url ?? entry.doc_url ?? null,
          auth_hint: entry.auth_hint ?? null,
        });
      });

    if (isHostCliConnector(entry.kind)) {
      void connectorsApi
        .cliStatus(entry.kind)
        .then(setCliInfo)
        .catch(() => {
          setCliInfo(null);
        });
    }

    if (instance) {
      setLoadingDetail(true);
      void connectorsApi
        .getInstance(instance.instance_id)
        .then((detail) => {
          setInstanceDetail(detail);
          form.setFieldsValue(previewToFormValues(entry, detail));
          const next = visibilityFromDetail(detail);
          setConnectorVisibility(next.visibility);
          setConnectorGroupIds(next.groupIds);
          if (detail.credentials_preview?.oauth_configured) {
            setShowManual(false);
          }
          if (detail.credentials_preview?.user_auth_configured) {
            const needs =
              detail.credentials_preview.user_auth_needs_reauth === true ||
              detail.credentials_preview.user_auth_valid === false;
            setFeishuAuthNeedsReauth(needs);
            setFeishuUserReady(!needs);
            setFeishuRefreshExpiresAt(
              detail.credentials_preview.user_refresh_expires_at ?? null,
            );
          }
          applyConnectorDraft();
        })
        .catch(() => {
          form.setFieldsValue({
            display_name: instance.display_name || entry.name,
            description: instance.description || entry.description,
            default_open: instance.default_open === true,
          });
          const next = visibilityFromDetail(instance);
          setConnectorVisibility(next.visibility);
          setConnectorGroupIds(next.groupIds);
          applyConnectorDraft();
        })
        .finally(() => setLoadingDetail(false));
    } else {
      applyConnectorDraft();
    }
  }, [open, entry, instance, form, applyConnectorDraft]);

  const openUrl = (url: string | null | undefined) => {
    if (!url) return;
    openExternalBrowserUrl(url);
  };

  /** Open sync under the click gesture so popup blockers don't swallow async opens. */
  const openAuthPopupPlaceholder = (): Window | null => {
    const popup = tryOpenAuthPopup(
      "about:blank",
      "octop-connector-auth",
      "width=720,height=800",
    );
    if (popup) {
      try {
        popup.document.title = "Feishu Auth";
        popup.document.body.innerHTML =
          '<p style="font:14px/1.5 system-ui;padding:24px;color:#666">Loading…</p>';
      } catch {
        // Cross-origin / closed — ignore.
      }
    }
    return popup;
  };

  const handleOpenAuthorize = async () => {
    if (!entry) return;
    setOpeningAuthorize(true);
    try {
      const { authorize_url } = await connectorsApi.authorizeUrl(entry.kind);
      if (!authorize_url) {
        message.error(t("connectors.authUrlMissing", "无法获取授权页地址"));
        return;
      }
      openUrl(authorize_url);
    } catch (e) {
      console.error(e);
      message.error(
        apiErrorMessage(e, t("connectors.authUrlFailed", "打开授权页失败"), t),
      );
    } finally {
      setOpeningAuthorize(false);
    }
  };

  const handleOpenLogin = () => {
    openUrl(authInfo?.login_url);
  };

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

  const extractPastedCredential = (text: string): string => {
    const trimmed = text.trim();
    try {
      const url = new URL(trimmed);
      const fromQuery =
        url.searchParams.get("code") ??
        url.searchParams.get("access_token") ??
        url.searchParams.get("token");
      if (fromQuery) return fromQuery;
    } catch {
      // not a full URL
    }
    const match = trimmed.match(/access_token=([^&\s#]+)/i);
    if (match?.[1]) {
      try {
        return decodeURIComponent(match[1]);
      } catch {
        return match[1];
      }
    }
    const mcpMatch = trimmed.match(/mcp_token=([^\s;,&"']+)/i);
    if (mcpMatch?.[1]) {
      return mcpMatch[1];
    }
    return trimmed;
  };

  const handlePasteToken = async () => {
    try {
      const text = (await navigator.clipboard.readText()).trim();
      if (!text) {
        message.warning(t("connectors.clipboardEmpty", "剪贴板为空"));
        return;
      }
      if (entry?.auth_kind === "personal_token") {
        form.setFieldValue("token", extractPastedCredential(text));
      } else if (entry?.auth_kind === "auth_code") {
        form.setFieldValue("auth_code", text);
      } else if (entry?.auth_kind === "api_key") {
        form.setFieldValue("api_key", text);
      }
      message.success(t("connectors.pasteSuccess", "已粘贴"));
    } catch {
      message.error(
        t("connectors.clipboardDenied", "无法读取剪贴板，请手动粘贴"),
      );
    }
  };

  const handleGuidedPaste = async () => {
    if (!entry || !isGuidedConnector(entry.kind)) return;
    try {
      const text = (await navigator.clipboard.readText()).trim();
      if (!text) {
        message.warning(t("connectors.clipboardEmpty", "剪贴板为空"));
        return;
      }
      const pastedUrl = extractHttpUrl(text);
      if (entry.kind === "dify") {
        if (!pastedUrl) {
          message.warning(
            t("connectors.difyPasteUrlRequired", "剪贴板中没有 MCP URL"),
          );
          return;
        }
        form.setFieldValue("mcp_url", pastedUrl);
        await form.validateFields(["mcp_url"]);
      } else if (pastedUrl) {
        form.setFieldValue("base_url", pastedUrl);
      } else {
        form.setFieldValue("api_key", text);
      }
      saveFormDraft(
        draftScope,
        form.getFieldsValue() as Record<string, unknown>,
      );
      message.success(t("connectors.pasteSuccess", "已粘贴"));
    } catch (error) {
      if (error && typeof error === "object" && "errorFields" in error) {
        message.warning(
          t(
            "connectors.difyMcpUrlInvalid",
            "请粘贴 Dify 访问点提供的完整 MCP Server URL",
          ),
        );
        return;
      }
      message.error(
        t("connectors.clipboardDenied", "无法读取剪贴板，请手动粘贴"),
      );
    }
  };

  const handleDetectLocalWeKnora = async () => {
    if (detectingLocalWeKnora) return;
    setDetectingLocalWeKnora(true);
    try {
      const result = await connectorsApi.detectLocalWeKnora();
      if (!result.found || !result.base_url) {
        message.warning(
          t(
            "connectors.weknoraNotFound",
            "未在 HappyClaw 主机的 127.0.0.1:8080 检测到 WeKnora",
          ),
        );
        return;
      }
      form.setFieldValue("base_url", result.base_url);
      saveFormDraft(
        draftScope,
        form.getFieldsValue() as Record<string, unknown>,
      );
      message.success(
        t("connectors.weknoraFound", "已检测到本机 WeKnora 并填入地址"),
      );
    } catch (error) {
      console.error(error);
      message.error(
        apiErrorMessage(
          error,
          t("connectors.weknoraDetectFailed", "检测本机 WeKnora 失败"),
          t,
        ),
      );
    } finally {
      setDetectingLocalWeKnora(false);
    }
  };

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

  const handleProbe = async () => {
    if (!entry) return;
    const values = form.getFieldsValue();
    const preview = instanceDetail?.credentials_preview ?? {};
    const freshSecret = hasFreshCredentialInput(entry, values);
    const feishuAppIdChanged =
      entry.kind === "feishu-cli" &&
      Boolean(preview.app_id) &&
      String(values.app_id ?? "").trim() !==
        String(preview.app_id ?? "").trim();
    const wecomBotIdChanged =
      entry.kind === "wecom-cli" &&
      Boolean(preview.bot_id) &&
      String(values.bot_id ?? "").trim() !==
        String(preview.bot_id ?? "").trim();
    const customConfigChanged = customCredentialConfigChanged(
      entry,
      values,
      preview,
    );
    const customHasStoredSecret = (entry.credential_fields ?? []).some(
      (field) => field.secret && preview[`${field.key}_configured`] === true,
    );
    const identityChanged =
      feishuAppIdChanged || wecomBotIdChanged || customConfigChanged;
    if (
      identityChanged &&
      !freshSecret &&
      (entry.auth_kind !== "custom_fields" || customHasStoredSecret)
    ) {
      message.warning(
        entry.kind === "feishu-cli"
          ? t(
              "connectors.probeNeedSecretAfterAppIdChange",
              "App ID 已修改，请填写 App Secret 后再探测",
            )
          : entry.kind === "wecom-cli"
          ? t(
              "connectors.probeNeedSecretAfterBotIdChange",
              "Bot ID 已修改，请填写 Secret 后再探测",
            )
          : t(
              "connectors.probeNeedSecretAfterConfigChange",
              "连接配置已修改，请重新填写密钥后再探测",
            ),
      );
      return;
    }
    const freshInput = freshSecret || identityChanged;
    // Only reuse saved creds when the form still matches the stored identity.
    const canUseStored = hasStoredCredentials && instance && !freshInput;

    if (!canUseStored) {
      try {
        await form.validateFields();
      } catch {
        message.warning(
          t("connectors.probeNeedConfig", "请先填写连接配置后再探测"),
        );
        return;
      }
    }

    setProbing(true);
    setProbeResult(null);
    try {
      const r = canUseStored
        ? await connectorsApi.testInstance(instance.instance_id)
        : await connectorsApi.testCredentials({
            kind: entry.kind,
            credentials: buildCredentials(entry, values),
          });
      if (r.ok) {
        const tools = r.tools ?? [];
        setProbeResult(tools);
        if (canUseStored) {
          message.success(
            t(
              "connectors.probeUsedStoredCredentials",
              "探测通过（使用已保存的凭证）",
            ),
          );
        }
      } else {
        setProbeResult(null);
        message.error(
          probeErrorMessage(r, t("connectors.probeFailed", "探测失败"), t),
        );
      }
    } catch (e) {
      console.error(e);
      message.error(
        apiErrorMessage(e, t("connectors.probeFailed", "探测失败"), t),
      );
    } finally {
      setProbing(false);
    }
  };

  const handleSubmit = async () => {
    if (!entry) return;
    try {
      await form.validateFields();
    } catch {
      return;
    }
    const values = form.getFieldsValue();
    if (entry.auth_kind === "oauth2") {
      const token = String(values.access_token ?? "").trim();
      const apiKey =
        entry.kind === "qcc" ? String(values.api_key ?? "").trim() : "";
      if (!hasStoredCredentials && !token && !apiKey) {
        message.warning(
          entry.kind === "qcc"
            ? t(
                "connectors.qccNeedAuthOrKey",
                "请先完成一键授权，或填写 API Key",
              )
            : t("connectors.oauthNeedToken", "请先完成授权或手动填写 Token"),
        );
        return;
      }
    }
    if (connectorVisibility === "groups" && connectorGroupIds.length === 0) {
      message.error(t("resourceVisibility.needGroup"));
      return;
    }
    setSaving(true);
    try {
      const payload = buildCredentials(entry, values);
      const share = visibilityFields(connectorVisibility, connectorGroupIds);
      if (instance) {
        await connectorsApi.patchInstance(instance.instance_id, {
          display_name: values.display_name as string,
          description: values.description as string,
          credentials: payload,
          default_open: values.default_open === true,
          ...share,
        });
      } else {
        const created = await connectorsApi.createInstance({
          kind: entry.kind,
          display_name: values.display_name as string,
          description: values.description as string,
          credentials: payload,
          default_open: values.default_open === true,
          ...share,
        });
        if (entry.kind === "agently-cli" || entry.kind === "dingtalk-cli") {
          clearFormDraft(draftScope);
          message.success(t("connectors.createSuccess", "连接器已创建"));
          onSaved(created);
          return;
        }
      }
      message.success(
        instance
          ? t("connectors.saveSuccess", "连接器已保存")
          : t("connectors.createSuccess", "连接器已创建"),
      );
      clearFormDraft(draftScope);
      onSaved();
      onClose();
    } catch (e) {
      console.error(e);
      message.error(
        apiErrorMessage(e, t("connectors.createFailed", "创建失败"), t),
      );
    } finally {
      setSaving(false);
    }
  };

  if (!entry) return null;

  const hasOAuthPopup =
    entry.auth_kind === "oauth2" &&
    entry.oauth_ready &&
    oauthCallbackSupported();
  const hasAuthorizeUrl = Boolean(authInfo?.authorize_url);
  const hasLoginUrl = Boolean(authInfo?.login_url);
  const guideUrl = authInfo?.guide_url ?? entry.guide_url ?? entry.doc_url;
  const manualUrl = authInfo?.manual_url ?? entry.manual_url ?? guideUrl;
  const catalogAuthHint = authInfo?.auth_hint ?? entry.auth_hint;
  const authHint =
    entry.kind === "qcc" && !hasOAuthPopup
      ? t(
          "connectors.qccApiKeyOnlyHint",
          "当前环境无法完成 OAuth 回调。请打开授权页获取 API Key，粘贴后探测并保存。",
        )
      : catalogAuthHint;
  const guidedKind = isGuidedConnector(entry.kind) ? entry.kind : null;

  const preview = instanceDetail?.credentials_preview;
  const secretRequired = !hasStoredCredentials;
  const hideTopAuth = entry
    ? INLINE_CREDENTIAL_GUIDE_KINDS.has(entry.kind)
    : false;
  const hideFieldGuide = entry
    ? HIDE_INLINE_FIELD_GUIDE_KINDS.has(entry.kind)
    : false;
  const hideGuideLink =
    hideTopAuth ||
    Boolean(entry?.quick_auth_url && guideUrl === entry.quick_auth_url);

  return (
    <Drawer
      title={
        instance
          ? t("connectors.editConnection", {
              name: entry.name,
              defaultValue: `编辑 ${entry.name} 连接器`,
            })
          : t("connectors.createConnection", {
              name: entry.name,
              defaultValue: `创建 ${entry.name} 连接器`,
            })
      }
      open={open}
      onClose={onClose}
      width={isMobile ? "100%" : 480}
      destroyOnHidden
      footer={
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button
            icon={<Activity size={14} />}
            loading={probing}
            disabled={entry.kind === "agently-cli" && !hasStoredCredentials}
            onClick={() => void handleProbe()}
          >
            {t("connectors.probe", "探测")}
          </Button>
          <Button
            type="primary"
            loading={saving}
            onClick={() => void handleSubmit()}
          >
            {t("common.save")}
          </Button>
        </div>
      }
    >
      <div className={styles.drawerBody}>
        {loadingDetail ? (
          <div className={styles.drawerLoading}>
            <Spin size="small" />
          </div>
        ) : null}

        <ConnectorSetupHints
          entry={entry}
          authHint={authHint}
          guidedKind={guidedKind}
          guideUrl={guideUrl}
          hideGuideLink={hideGuideLink}
        />

        <ConnectorQuickAuthBar
          entry={entry}
          guidedKind={guidedKind}
          detectingLocalWeKnora={detectingLocalWeKnora}
          handleDetectLocalWeKnora={handleDetectLocalWeKnora}
          handleGuidedPaste={handleGuidedPaste}
          canInstallCli={canInstallCli}
          cliInfo={cliInfo}
          installingCli={installingCli}
          handleInstallCli={handleInstallCli}
          handleCopyInstallCommand={handleCopyInstallCommand}
          openUrl={openUrl}
          hasOAuthPopup={hasOAuthPopup}
          authorizing={authorizing}
          handleOAuth={handleOAuth}
          hasAuthorizeUrl={hasAuthorizeUrl}
          hideTopAuth={hideTopAuth}
          openingAuthorize={openingAuthorize}
          handleOpenAuthorize={handleOpenAuthorize}
          hasLoginUrl={hasLoginUrl}
          handleOpenLogin={handleOpenLogin}
          handlePasteToken={handlePasteToken}
        />

        <ConnectorCliHints entry={entry} cliInfo={cliInfo} />

        {open &&
          (entry.kind === "agently-cli" || entry.kind === "dingtalk-cli") &&
          instance && (
            <AgentlyAuth
              key={instance.instance_id}
              kind={entry.kind}
              instanceId={instance.instance_id}
              installed={cliInfo?.installed === true}
              onChanged={() => {
                void connectorsApi
                  .getInstance(instance.instance_id)
                  .then((detail) =>
                    setInstanceDetail((current) =>
                      current?.instance_id === detail.instance_id
                        ? detail
                        : current,
                    ),
                  )
                  .catch(() => undefined);
                onSaved();
              }}
            />
          )}

        <Form
          form={form}
          layout="vertical"
          onValuesChange={(_, all) => {
            if (!restoringDraftRef.current && draftScope) {
              saveFormDraft(
                draftScope,
                all as unknown as Record<string, unknown>,
              );
            }
          }}
        >
          <div className={styles.configSectionTitle}>
            {t("connectors.configSection", "连接配置")}
          </div>
          <Form.Item
            name="display_name"
            label={t("connectors.displayName", "显示名称")}
            rules={[{ required: true }]}
          >
            <Input placeholder={entry.name} />
          </Form.Item>
          <Form.Item
            name="description"
            label={t("connectors.description", "描述")}
            rules={[{ required: true }]}
            className={styles.textAssistField}
          >
            <Input.TextArea
              autoSize={{ minRows: 2, maxRows: 5 }}
              placeholder={entry.description}
            />
          </Form.Item>
          <TextAssistBar
            kind="connector.description"
            getName={() =>
              String(form.getFieldValue("display_name") ?? entry.name ?? "")
            }
            getText={() => String(form.getFieldValue("description") ?? "")}
            onApply={(text) =>
              form.setFieldsValue({ description: text.slice(0, 500) })
            }
          />

          <ConnectorCredentialFields
            entry={entry}
            form={form}
            hasStoredCredentials={hasStoredCredentials}
            preview={preview}
            secretRequired={secretRequired}
            hideFieldGuide={hideFieldGuide}
            manualUrl={manualUrl}
            mailProvider={mailProvider}
            selectedMailProvider={selectedMailProvider}
            showManual={showManual}
            setShowManual={setShowManual}
            hasOAuthPopup={hasOAuthPopup}
            feishuAuthNeedsReauth={feishuAuthNeedsReauth}
            feishuUserReady={feishuUserReady}
            feishuUserAuth={feishuUserAuth}
            feishuUserAuthBusy={feishuUserAuthBusy}
            feishuRefreshExpiresAt={feishuRefreshExpiresAt}
            handleFeishuUserAuthStart={handleFeishuUserAuthStart}
            handleFeishuUserAuthComplete={handleFeishuUserAuthComplete}
            openUrl={openUrl}
          />

          <ConnectorFormOptions
            defaultOpen={defaultOpen}
            visibility={connectorVisibility}
            groupIds={connectorGroupIds}
            onVisibilityChange={(visibility, groupIds) => {
              setConnectorVisibility(visibility);
              setConnectorGroupIds(groupIds);
            }}
          />
        </Form>

        {probeResult !== null && (
          <ConnectorProbeResult tools={probeResult} />
        )}
      </div>
    </Drawer>
  );
}
