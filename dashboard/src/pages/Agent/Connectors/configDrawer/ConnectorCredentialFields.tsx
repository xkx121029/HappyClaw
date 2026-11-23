import { Form, Input, Select } from "antd";
import type { FormInstance } from "antd";
import type { Dispatch, SetStateAction } from "react";
import { useTranslation } from "react-i18next";

import type {
  ConnectorCatalogEntry,
  ConnectorCredentialsPreview,
  FeishuUserAuthStartResult,
} from "../../../../api/modules/connectors";
import { authCodeGuideLabel } from "../connectorAuthLabels";
import { MAIL_PROVIDERS, mailProviderById } from "../connectorDefs";
import { configuredExtra, secretFieldRules } from "../connectorFieldRules";
import { isDifyMcpServerUrl } from "../guidedConnectorUtils";
import styles from "../index.module.less";

export function ConnectorCredentialFields({
  entry,
  form,
  hasStoredCredentials,
  preview,
  secretRequired,
  hideFieldGuide,
  manualUrl,
  mailProvider,
  selectedMailProvider,
  showManual,
  setShowManual,
  hasOAuthPopup,
  feishuAuthNeedsReauth,
  feishuUserReady,
  feishuUserAuth,
  feishuUserAuthBusy,
  feishuRefreshExpiresAt,
  handleFeishuUserAuthStart,
  handleFeishuUserAuthComplete,
  openUrl,
}: {
  entry: ConnectorCatalogEntry;
  form: FormInstance;
  hasStoredCredentials: boolean;
  preview: ConnectorCredentialsPreview | undefined;
  secretRequired: boolean;
  hideFieldGuide: boolean;
  manualUrl?: string;
  mailProvider: unknown;
  selectedMailProvider: ReturnType<typeof mailProviderById>;
  showManual: boolean;
  setShowManual: Dispatch<SetStateAction<boolean>>;
  hasOAuthPopup: boolean;
  feishuAuthNeedsReauth: boolean;
  feishuUserReady: boolean;
  feishuUserAuth: FeishuUserAuthStartResult | null;
  feishuUserAuthBusy: boolean;
  feishuRefreshExpiresAt: string | null;
  handleFeishuUserAuthStart: () => Promise<void>;
  handleFeishuUserAuthComplete: () => Promise<void>;
  openUrl: (url: string | null | undefined) => void;
}) {
  const { t } = useTranslation();

  return (
    <>
      {entry.auth_kind === "custom_fields" &&
        (entry.credential_fields ?? []).map((field) => {
          const isSecret = field.secret || field.field_type === "password";
          const input = isSecret ? (
            <Input.Password
              placeholder={
                hasStoredCredentials && field.secret
                  ? t("connectors.secretPlaceholder", "留空表示不修改")
                  : field.placeholder ?? undefined
              }
            />
          ) : (
            <Input placeholder={field.placeholder ?? undefined} />
          );
          return (
            <Form.Item
              key={field.key}
              name={field.key}
              label={field.label}
              rules={[
                ...(isSecret
                  ? secretFieldRules(field.required && secretRequired)
                  : [{ required: field.required }]),
                ...(entry.kind === "dify" && field.key === "mcp_url"
                  ? [
                      {
                        validator: (_: unknown, value: unknown) =>
                          !value || isDifyMcpServerUrl(String(value))
                            ? Promise.resolve()
                            : Promise.reject(
                                new Error(
                                  t(
                                    "connectors.difyMcpUrlInvalid",
                                    "请粘贴 Dify 访问点提供的完整 MCP Server URL",
                                  ),
                                ),
                              ),
                      },
                    ]
                  : []),
              ]}
              extra={
                configuredExtra(preview, `${field.key}_configured`, t) ??
                field.help
              }
            >
              {input}
            </Form.Item>
          );
        })}

      {entry.auth_kind === "personal_token" && (
        <Form.Item
          name="token"
          label={t("connectors.token", "访问 Token")}
          rules={secretFieldRules(secretRequired)}
          extra={
            configuredExtra(preview, "token_configured", t) ??
            (!hideFieldGuide && manualUrl ? (
              <a href={manualUrl} target="_blank" rel="noreferrer">
                {t("connectors.getTokenAt", "前往获取 Token")}
              </a>
            ) : !hideFieldGuide ? (
              <a href={entry.doc_url} target="_blank" rel="noreferrer">
                {t("connectors.getToken", "获取 Token")}
              </a>
            ) : undefined)
          }
        >
          <Input.Password
            placeholder={hasStoredCredentials ? "••••••••" : undefined}
          />
        </Form.Item>
      )}

      {entry.auth_kind === "auth_code" && (
        <>
          <Form.Item
            name="auth_code"
            label={t("connectors.authCode", "授权码")}
            rules={secretFieldRules(secretRequired)}
            extra={
              configuredExtra(preview, "auth_configured", t) ??
              (!hideFieldGuide && entry.manual_url ? (
                <a href={entry.manual_url} target="_blank" rel="noreferrer">
                  {authCodeGuideLabel(entry.kind, t)}
                </a>
              ) : !hideFieldGuide && manualUrl ? (
                <a href={manualUrl} target="_blank" rel="noreferrer">
                  {authCodeGuideLabel(entry.kind, t)}
                </a>
              ) : undefined)
            }
          >
            <Input.Password
              placeholder={
                hasStoredCredentials
                  ? t("connectors.secretPlaceholder", "留空表示不修改")
                  : t("connectors.authCodePlaceholder", "粘贴授权码")
              }
            />
          </Form.Item>
        </>
      )}

      {entry.kind === "feishu-cli" && (
        <>
          <Form.Item name="default_as" hidden>
            <Input />
          </Form.Item>
          <Form.Item name="cli_config_key" hidden>
            <Input />
          </Form.Item>
          <Form.Item
            name="app_id"
            label={t("connectors.feishuAppId", "App ID")}
            rules={[{ required: true }]}
            extra={
              !hideFieldGuide && manualUrl ? (
                <a href={manualUrl} target="_blank" rel="noreferrer">
                  {t(
                    "connectors.feishuAppCredDoc",
                    "在飞书开放平台创建应用并获取 App ID / App Secret",
                  )}
                </a>
              ) : undefined
            }
          >
            <Input
              placeholder={t(
                "connectors.feishuAppIdPlaceholder",
                "例如 cli_xxxxxxxx",
              )}
            />
          </Form.Item>
          <Form.Item
            name="app_secret"
            label={t("connectors.feishuAppSecret", "App Secret")}
            rules={secretFieldRules(secretRequired)}
            extra={configuredExtra(preview, "app_secret_configured", t)}
          >
            <Input.Password
              placeholder={
                hasStoredCredentials
                  ? t("connectors.secretPlaceholder", "留空表示不修改")
                  : t(
                      "connectors.feishuAppSecretPlaceholder",
                      "飞书应用 App Secret",
                    )
              }
            />
          </Form.Item>
          <div className={styles.feishuUserAuthBox}>
            <div className={styles.feishuUserAuthTitle}>
              {t("connectors.feishuUserAuthTitle", "飞书账号授权")}
            </div>
            <p className={styles.feishuUserAuthWhy}>
              {t(
                "connectors.feishuUserAuthWhy",
                "上方 App ID / Secret 只代表应用（Bot）。文档搜索、访问你云空间里的个人文档和日程等，必须以你的飞书账号身份调用，因此需要额外授权一次。授权后 Agent 只能访问你本人有权限的内容。",
              )}
            </p>
            <div className={styles.feishuUserAuthHint}>
              {feishuAuthNeedsReauth
                ? t(
                    "connectors.feishuUserAuthExpired",
                    "用户授权已失效，请重新登录授权。",
                  )
                : feishuUserReady
                ? t(
                    "connectors.feishuUserAuthReady",
                    "已授权，可搜索文档。",
                  )
                : feishuUserAuth
                ? t(
                    "connectors.feishuUserAuthPendingHint",
                    "请在弹出的页面完成授权，然后点「我已授权」。",
                  )
                : t(
                    "connectors.feishuUserAuthHint",
                    "点击登录授权，完成后点「我已授权」。",
                  )}
            </div>
            {feishuUserReady && feishuRefreshExpiresAt && (
              <div className={styles.feishuUserAuthHint}>
                {t(
                  "connectors.feishuUserAuthRefreshUntil",
                  "刷新令牌约有效至 {{time}}（到期后需重新授权）",
                  { time: feishuRefreshExpiresAt },
                )}
              </div>
            )}
            <div className={styles.quickAuthBar}>
              <Button
                type={
                  feishuUserReady && !feishuAuthNeedsReauth
                    ? "default"
                    : "primary"
                }
                loading={feishuUserAuthBusy}
                onClick={() => void handleFeishuUserAuthStart()}
              >
                {feishuUserReady || feishuAuthNeedsReauth
                  ? t("connectors.feishuUserAuthAgain", "重新授权")
                  : t("connectors.feishuUserAuthStart", "登录授权")}
              </Button>
              {feishuUserAuth && (
                <Button
                  type="primary"
                  loading={feishuUserAuthBusy}
                  onClick={() => void handleFeishuUserAuthComplete()}
                >
                  {t("connectors.feishuUserAuthConfirm", "我已授权")}
                </Button>
              )}
            </div>
            {feishuUserAuth && (
              <button
                type="button"
                className={styles.feishuUserAuthReopen}
                onClick={() => openUrl(feishuUserAuth.verification_url)}
              >
                {t("connectors.feishuUserAuthReopen", "未弹出？再打开一次")}
              </button>
            )}
          </div>
        </>
      )}

      {entry.kind === "wecom-cli" && (
        <>
          <Form.Item
            name="bot_id"
            label={t("connectors.wecomBotId", "Bot ID")}
            rules={[{ required: true }]}
            extra={
              !hideFieldGuide && manualUrl ? (
                <a href={manualUrl} target="_blank" rel="noreferrer">
                  {t(
                    "connectors.wecomBotCredDoc",
                    "在企业微信开放平台获取智能机器人 Bot ID / Secret",
                  )}
                </a>
              ) : undefined
            }
          >
            <Input
              placeholder={t(
                "connectors.wecomBotIdPlaceholder",
                "企业微信智能机器人 Bot ID",
              )}
            />
          </Form.Item>
          <Form.Item
            name="bot_secret"
            label={t("connectors.wecomBotSecret", "Secret")}
            rules={secretFieldRules(secretRequired)}
            extra={configuredExtra(preview, "bot_secret_configured", t)}
          >
            <Input.Password
              placeholder={
                hasStoredCredentials
                  ? t("connectors.secretPlaceholder", "留空表示不修改")
                  : t(
                      "connectors.wecomBotSecretPlaceholder",
                      "企业微信机器人 Secret",
                    )
              }
            />
          </Form.Item>
        </>
      )}

      {entry.auth_kind === "api_key" &&
        entry.kind !== "feishu-cli" &&
        entry.kind !== "wecom-cli" && (
          <>
            <Form.Item
              name="api_key"
              label={t("connectors.apiKey", "API Key")}
              rules={secretFieldRules(secretRequired)}
              extra={
                configuredExtra(preview, "api_key_configured", t) ??
                (!hideFieldGuide && manualUrl ? (
                  <a href={manualUrl} target="_blank" rel="noreferrer">
                    {t("connectors.apiKeyDoc", "查看如何获取 API Key")}
                  </a>
                ) : undefined)
              }
            >
              <Input.Password
                placeholder={
                  hasStoredCredentials
                    ? t("connectors.secretPlaceholder", "留空表示不修改")
                    : entry.kind === "tencent-ima"
                    ? t(
                        "connectors.imaApiKeyPlaceholder",
                        "从 IMA 配置页复制（仅展示一次）",
                      )
                    : t("connectors.apiKeyPlaceholder", "粘贴 API Key")
                }
              />
            </Form.Item>
            {entry.kind === "tencent-ima" && (
              <Form.Item
                name="client_id"
                label="Client ID"
                rules={[{ required: true }]}
              >
                <Input
                  placeholder={t(
                    "connectors.imaClientIdPlaceholder",
                    "从 IMA 配置页复制",
                  )}
                />
              </Form.Item>
            )}
            {entry.kind === "tencent-lexiang" && (
              <Form.Item
                name="client_id"
                label={t(
                  "connectors.lexiangCompanyFrom",
                  "企业标识 (company_from)",
                )}
                rules={[{ required: true }]}
              >
                <Input
                  placeholder={t(
                    "connectors.lexiangCompanyFromPlaceholder",
                    "从乐享凭证页复制",
                  )}
                />
              </Form.Item>
            )}
          </>
        )}

      {entry.auth_kind === "oauth2" && (
        <>
          <Form.Item name="access_token" hidden>
            <Input />
          </Form.Item>
          <Form.Item name="refresh_token" hidden>
            <Input />
          </Form.Item>
          <Form.Item name="expires_at" hidden>
            <Input />
          </Form.Item>
          <Form.Item name="oauth_client_id" hidden>
            <Input />
          </Form.Item>
          <Form.Item name="oauth_client_secret" hidden>
            <Input />
          </Form.Item>
          <Form.Item name="openid" hidden>
            <Input />
          </Form.Item>
          {preview?.oauth_configured && !showManual && (
            <div className={styles.configuredBadge}>
              {t("connectors.oauthConfigured", "已授权，可直接探测或保存")}
            </div>
          )}
          {entry.kind === "qcc" &&
            preview?.api_key_configured &&
            !showManual && (
              <div className={styles.configuredBadge}>
                {t(
                  "connectors.qccApiKeyConfigured",
                  "已配置 API Key，可直接探测或保存",
                )}
              </div>
            )}
          {entry.oauth_ready &&
            hasOAuthPopup &&
            !preview?.oauth_configured &&
            !(entry.kind === "qcc" && preview?.api_key_configured) && (
              <div
                style={{
                  fontSize: 13,
                  color: "var(--fn-text-tertiary)",
                  marginBottom: 8,
                }}
              >
                {entry.kind === "qcc"
                  ? t(
                      "connectors.qccOauthHint",
                      "点击「一键授权」完成登录后将自动保存；也可打开授权页获取 API Key 后粘贴",
                    )
                  : t(
                      "connectors.oauthHint",
                      "点击「一键授权」完成登录后将自动保存；也可手动粘贴 Token",
                    )}
              </div>
            )}
          {entry.kind === "qcc" ? (
            <Form.Item
              name="api_key"
              label={t("connectors.qccApiKey", "API Key")}
              extra={configuredExtra(preview, "api_key_configured", t)}
            >
              <Input.Password
                placeholder={
                  preview?.api_key_configured
                    ? t("connectors.secretPlaceholder", "留空表示不修改")
                    : t(
                        "connectors.qccApiKeyPlaceholder",
                        "粘贴企查查 API Key",
                      )
                }
              />
            </Form.Item>
          ) : (
            <>
              <div
                className={styles.manualToggle}
                onClick={() => setShowManual((v) => !v)}
                role="button"
                tabIndex={0}
              >
                {showManual
                  ? t("connectors.hideManual", "收起手动输入")
                  : t("connectors.showManual", "手动粘贴 Token")}
              </div>
              {showManual && (
                <Form.Item
                  name="access_token_manual"
                  label={t("connectors.accessTokenManual", "Access Token")}
                  extra={
                    manualUrl ? (
                      <a href={manualUrl} target="_blank" rel="noreferrer">
                        {t(
                          "connectors.manualTokenDoc",
                          "手动获取 Token 文档",
                        )}
                      </a>
                    ) : undefined
                  }
                >
                  <Input.Password
                    onChange={(e) =>
                      form.setFieldValue("access_token", e.target.value)
                    }
                  />
                </Form.Item>
              )}
            </>
          )}
        </>
      )}

      {entry.auth_kind === "imap_app_password" && (
        <>
          <Form.Item
            name="mail_provider"
            label={t("connectors.mailProvider", "邮箱服务商")}
            initialValue="qq"
          >
            <Select
              options={MAIL_PROVIDERS.map((item) => ({
                value: item.id,
                label: t(`connectors.mailProviders.${item.id}`),
              }))}
            />
          </Form.Item>
          <Form.Item
            name="email"
            label={t("connectors.email", "邮箱地址")}
            rules={[{ required: true }]}
          >
            <Input placeholder={selectedMailProvider.emailPlaceholder} />
          </Form.Item>
          <Form.Item
            name="password"
            label={t("connectors.authCode", "授权码")}
            rules={secretFieldRules(secretRequired)}
            extra={
              configuredExtra(preview, "password_configured", t) ??
              (selectedMailProvider.guideUrl ? (
                <a
                  href={selectedMailProvider.guideUrl}
                  target="_blank"
                  rel="noreferrer"
                >
                  {t(
                    "connectors.personalMailAuthGuide",
                    "如何获取邮箱授权码",
                  )}
                </a>
              ) : undefined)
            }
          >
            <Input.Password
              placeholder={
                hasStoredCredentials
                  ? t("connectors.secretPlaceholder", "留空表示不修改")
                  : undefined
              }
            />
          </Form.Item>
          {mailProvider === "custom" && (
            <>
              <Form.Item
                name="imap_host"
                label={t("connectors.imapHost", "IMAP 服务器")}
                rules={[{ required: true }]}
              >
                <Input placeholder="imap.example.com" />
              </Form.Item>
              <Form.Item
                name="smtp_host"
                label={t("connectors.smtpHost", "SMTP 服务器")}
                rules={[{ required: true }]}
              >
                <Input placeholder="smtp.example.com" />
              </Form.Item>
            </>
          )}
        </>
      )}

      {entry.auth_kind === "api_credentials" && (
        <>
          <Form.Item
            name="app_id"
            label="AppId"
            rules={[{ required: true }]}
          >
            <Input placeholder="企业 ID / AppId" />
          </Form.Item>
          <Form.Item
            name="sdk_id"
            label="SdkId"
            rules={[{ required: true }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="secret_key"
            label="Secret"
            rules={secretFieldRules(secretRequired)}
            extra={configuredExtra(preview, "secret_key_configured", t)}
          >
            <Input.Password
              placeholder={
                hasStoredCredentials
                  ? t("connectors.secretPlaceholder", "留空表示不修改")
                  : undefined
              }
            />
          </Form.Item>
        </>
      )}
    </>
  );
}
