import { useEffect, useState, useCallback } from "react";
import { App, Button, Drawer, Form, Input, Radio, Typography, Spin } from "antd";

import {
  Activity,
  Check,
  CheckCircle,
  Search,
  Settings2,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import cx from "classnames";
import { envsApi } from "../../../api/modules/env";
import {
  octopSettingsApi,
  type SearchSourceSettings,
  type SearchSourceValue,
  type SearchStatus,
} from "../../../api/modules/settings";
import api from "../../../api";
import { customProviderLogo, getProviderLogo } from "../../../assets/providers";
import { apiErrorMessage } from "../../../utils/apiError";
import styles from "./index.module.less";

const { Text } = Typography;

interface SearchProvider {
  id: string;
  name: string;
  descriptionKey: string;
  docs_url?: string;
  required_keys: string[];
  configured: boolean;
}

const SEARCH_PROVIDERS: SearchProvider[] = [
  {
    id: "tavily",
    name: "Tavily",
    descriptionKey: "setupWizard.search.providers.tavily.desc",
    docs_url: "https://app.tavily.com/",
    required_keys: ["TAVILY_API_KEY"],
    configured: false,
  },
  {
    id: "brave",
    name: "Brave Search",
    descriptionKey: "setupWizard.search.providers.brave.desc",
    docs_url: "https://api.search.brave.com/",
    required_keys: ["BRAVE_API_KEY"],
    configured: false,
  },
  {
    id: "deepseek",
    name: "DeepSeek Search",
    descriptionKey: "setupWizard.search.providers.deepseek.desc",
    docs_url: "https://api-docs.deepseek.com/guides/search/",
    required_keys: ["DEEPSEEK_API_KEY"],
    configured: false,
  },
  {
    id: "google",
    name: "Google Search",
    descriptionKey: "setupWizard.search.providers.google.desc",
    docs_url: "https://programmablesearchengine.google.com/",
    required_keys: ["GOOGLE_API_KEY", "GOOGLE_CSE_ID"],
    configured: false,
  },
  {
    id: "kimi",
    name: "Kimi (Moonshot)",
    descriptionKey: "setupWizard.search.providers.kimi.desc",
    docs_url: "https://platform.moonshot.cn/",
    required_keys: ["MOONSHOT_API_KEY"],
    configured: false,
  },
  {
    id: "yuanbao",
    name: "元宝搜索",
    descriptionKey: "setupWizard.search.providers.yuanbao.desc",
    docs_url: "https://cloud.tencent.com/document/product/1806/130615",
    required_keys: ["TENCENTCLOUD_WSA_APIKEY"],
    configured: false,
  },
];

const SOURCE_OPTIONS: Array<{
  value: SearchSourceValue;
  titleKey: string;
  descKey: string;
}> = [
  {
    value: "happysearch",
    titleKey: "advancedSettings.search.sourceHappyTitle",
    descKey: "advancedSettings.search.sourceHappyDesc",
  },
  {
    value: "searchfree",
    titleKey: "advancedSettings.search.sourceNativeTitle",
    descKey: "advancedSettings.search.sourceNativeDesc",
  },
  {
    value: "both",
    titleKey: "advancedSettings.search.sourceBothTitle",
    descKey: "advancedSettings.search.sourceBothDesc",
  },
];

function searchProviderLogo(providerId: string): string {
  return getProviderLogo(providerId) ?? customProviderLogo;
}

interface ConfigureDrawerProps {
  provider: SearchProvider;
  envVars: Record<string, string>;
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
}

function ConfigureDrawer({
  provider,
  envVars,
  open,
  onClose,
  onSaved,
}: ConfigureDrawerProps) {
  const { t } = useTranslation();
  const { modal, message } = App.useApp();
  const [form] = Form.useForm();
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [revoking, setRevoking] = useState(false);

  useEffect(() => {
    if (!open) return;
    const initialValues: Record<string, string> = {};
    provider.required_keys.forEach((key) => {
      if (envVars[key]) initialValues[key] = envVars[key];
    });
    form.setFieldsValue(initialValues);
  }, [envVars, provider.required_keys, form, open]);

  const handleSave = async () => {
    try {
      setSaving(true);
      const values = (await form.validateFields()) as Record<string, string>;
      const allEnvs = { ...envVars };
      provider.required_keys.forEach((key) => {
        if (values[key]) allEnvs[key] = values[key];
      });
      await envsApi.batchSaveEnvs(allEnvs);
      message.success(
        t("setupWizard.search.saveSuccess", { name: provider.name }),
      );
      onSaved();
      onClose();
    } catch (err) {
      if (err && typeof err === "object" && "errorFields" in err) return;
      message.error(apiErrorMessage(err, t("setupWizard.search.saveFailed")));
    } finally {
      setSaving(false);
    }
  };

  const handleProbe = async () => {
    try {
      setTesting(true);
      const values = (await form.validateFields()) as Record<string, string>;
      const testEnvs = { ...envVars };
      provider.required_keys.forEach((key) => {
        if (values[key]) testEnvs[key] = values[key];
      });
      const result = await api.testSearch(provider.id, testEnvs);
      if (result.success) {
        message.success(
          t("setupWizard.search.testSuccess", { name: provider.name }),
        );
      } else {
        message.error(
          t("setupWizard.search.testFailed", {
            name: provider.name,
            error: result.error || result.error_type || "Unknown error",
          }),
        );
      }
    } catch (err) {
      if (err && typeof err === "object" && "errorFields" in err) return;
      message.error(
        t("setupWizard.search.testFailed", {
          name: provider.name,
          error: apiErrorMessage(err, String(err)),
        }),
      );
    } finally {
      setTesting(false);
    }
  };

  const handleRevoke = () => {
    modal.confirm({
      title: t("setupWizard.search.revokeTitle", { name: provider.name }),
      content: t("setupWizard.search.revokeConfirm", { name: provider.name }),
      okText: t("setupWizard.search.revoke"),
      okButtonProps: { danger: true },
      cancelText: t("common.cancel"),
      onOk: async () => {
        try {
          setRevoking(true);
          for (const key of provider.required_keys) {
            await envsApi.deleteEnv(key);
          }
          message.success(
            t("setupWizard.search.revokeSuccess", { name: provider.name }),
          );
          onSaved();
          onClose();
        } catch (err) {
          message.error(
            apiErrorMessage(err, t("setupWizard.search.revokeFailed")),
          );
        } finally {
          setRevoking(false);
        }
      },
    });
  };

  return (
    <Drawer
      title={t("advancedSettings.search.configureTitle", {
        name: provider.name,
      })}
      open={open}
      onClose={onClose}
      width={440}
      placement="right"
      destroyOnHidden
      footer={
        <div className={styles.drawerFooter}>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button
            icon={<Activity size={14} />}
            loading={testing}
            onClick={() => void handleProbe()}
          >
            {t("advancedSettings.search.probe")}
          </Button>
          <Button
            type="primary"
            loading={saving}
            onClick={() => void handleSave()}
          >
            {t("common.save")}
          </Button>
        </div>
      }
    >
      <div className={styles.drawerHint}>{t(provider.descriptionKey)}</div>
      <Form form={form} layout="vertical" requiredMark={false}>
        {provider.required_keys.map((key) => (
          <Form.Item
            key={key}
            name={key}
            label={key}
            rules={[
              {
                required: true,
                message: t("setupWizard.search.required", { key }),
              },
            ]}
            extra={
              key === "GOOGLE_CSE_ID" ? (
                <span>
                  {t("setupWizard.search.googleCseIdHint")}
                  {provider.docs_url ? (
                    <>
                      {" · "}
                      <a
                        href={provider.docs_url}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        {t("setupWizard.search.getApiKey")}
                      </a>
                    </>
                  ) : null}
                </span>
              ) : provider.docs_url && key === provider.required_keys[0] ? (
                <a
                  href={provider.docs_url}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  {t("setupWizard.search.getApiKey")}
                </a>
              ) : undefined
            }
          >
            <Input.Password
              placeholder={t("setupWizard.search.required", { key })}
              autoComplete="off"
            />
          </Form.Item>
        ))}
      </Form>
      {provider.configured ? (
        <Button
          danger
          icon={<Trash2 size={14} />}
          loading={revoking}
          onClick={handleRevoke}
        >
          {t("setupWizard.search.revoke")}
        </Button>
      ) : null}
    </Drawer>
  );
}

export default function SearchConfigPage() {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const [providers, setProviders] =
    useState<SearchProvider[]>(SEARCH_PROVIDERS);
  const [loading, setLoading] = useState(true);
  const [envVars, setEnvVars] = useState<Record<string, string>>({});
  const [editing, setEditing] = useState<SearchProvider | null>(null);
  const [sourceState, setSourceState] =
    useState<SearchSourceSettings | null>(null);
  const [status, setStatus] = useState<SearchStatus | null>(null);
  const [sourceSaving, setSourceSaving] = useState(false);

  const fetchEnvVars = useCallback(async () => {
    try {
      setLoading(true);
      const envs = await envsApi.listEnvs();
      const envMap: Record<string, string> = {};
      envs.forEach((env) => {
        envMap[env.key] = env.value;
      });
      setEnvVars(envMap);
      setProviders(
        SEARCH_PROVIDERS.map((p) => ({
          ...p,
          configured: p.required_keys.every((key) => !!envMap[key]),
        })),
      );
    } catch (err) {
      console.error("Failed to load env vars:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchSourceState = useCallback(async () => {
    try {
      setSourceState(await octopSettingsApi.searchSource());
    } catch (err) {
      console.error("Failed to load search source:", err);
      return;
    }
    try {
      setStatus(await octopSettingsApi.searchStatus());
    } catch (err) {
      console.error("Failed to load search runtime status:", err);
    }
  }, []);

  useEffect(() => {
    void fetchEnvVars();
    void fetchSourceState();
  }, [fetchEnvVars, fetchSourceState]);

  const sourceLabel = useCallback(
    (value?: string | null) => {
      switch (value) {
        case "happysearch":
          return t("advancedSettings.search.sourceHappyName");
        case "searchfree":
          return t("advancedSettings.search.sourceNativeName");
        case "both":
          return t("advancedSettings.search.sourceBothName");
        default:
          return value || "—";
      }
    },
    [t],
  );

  const handleSourceChange = async (value: SearchSourceValue) => {
    setSourceSaving(true);
    try {
      const next = await octopSettingsApi.putSearchSource({ source: value });
      setSourceState(next);
      if (next.applied) {
        message.success(t("advancedSettings.search.sourceSaveSuccess"));
      } else {
        message.warning(t("advancedSettings.search.sourceSavePending"), 6);
      }
      await fetchSourceState();
    } catch (err) {
      message.error(
        apiErrorMessage(err, t("advancedSettings.search.sourceSaveFailed")),
      );
    } finally {
      setSourceSaving(false);
    }
  };

  const sortedProviders = [...providers].sort((a, b) => {
    if (a.configured && !b.configured) return -1;
    if (!a.configured && b.configured) return 1;
    return 0;
  });

  const configuredProviders = providers.filter((p) => p.configured);
  const activeSource = configuredProviders[0];
  const configuredCount = configuredProviders.length;
  const engineEntries = Object.entries(
    status?.happysearch?.runtime?.engines_last ?? {},
  );
  const nativeLast = status?.searchfree?.runtime?.last;
  const originLabel =
    sourceState?.origin === "env"
      ? t("advancedSettings.search.sourceOriginEnv")
      : sourceState?.origin === "settings"
        ? t("advancedSettings.search.sourceOriginSettings")
        : t("advancedSettings.search.sourceOriginDefault");

  if (loading) {
    return (
      <div className={styles.loading}>
        <Spin />
      </div>
    );
  }

  return (
    <>
      <p className={styles.intro}>{t("advancedSettings.search.desc")}</p>

      <section className={styles.sourceSection}>
        <div className={styles.sourceSectionHeader}>
          <div>
            <p className={styles.sourceSectionTitle}>
              {t("advancedSettings.search.sourceSectionTitle")}
            </p>
            <p className={styles.sourceSectionDesc}>
              {t("advancedSettings.search.sourceSectionDesc")}
            </p>
          </div>
          <span className={styles.originBadge}>
            {t("advancedSettings.search.sourceOriginLabel")}: {originLabel}
          </span>
        </div>
        <Radio.Group
          className={styles.sourceGroup}
          value={sourceState?.effective}
          disabled={sourceSaving || !sourceState}
          onChange={(e) =>
            void handleSourceChange(e.target.value as SearchSourceValue)
          }
        >
          {SOURCE_OPTIONS.map((option) => (
            <Radio
              key={option.value}
              value={option.value}
              className={styles.sourceOption}
            >
              <span className={styles.sourceOptionTitle}>
                {t(option.titleKey)}
              </span>
              <span className={styles.sourceOptionDesc}>
                {t(option.descKey)}
              </span>
            </Radio>
          ))}
        </Radio.Group>
      </section>

      <div className={cx(styles.status, configuredCount > 0 && styles.statusOk)}>
        <span className={styles.statusIcon} aria-hidden="true">
          {configuredCount > 0 ? (
            <CheckCircle size={18} />
          ) : (
            <Search size={18} />
          )}
        </span>
        <div className={styles.statusBody}>
          <p className={styles.statusTitle}>
            {configuredCount > 0
              ? t("advancedSettings.search.thirdPartyAdditiveTitle", {
                  count: configuredCount,
                })
              : t("advancedSettings.search.thirdPartyNoneTitle")}
          </p>
          <p className={styles.statusDesc}>
            {configuredCount > 0
              ? t("advancedSettings.search.thirdPartyAdditiveDesc")
              : t("advancedSettings.search.thirdPartyNoneDesc")}
          </p>
        </div>
      </div>

      <div className={styles.runtimeBlock}>
        <div className={styles.runtimeTitle}>
          {t("advancedSettings.search.statusTitle")}
        </div>
        {status?.last ? (
          <div className={styles.statusGrid}>
            <div className={styles.statusItem}>
              <span className={styles.statusLabel}>
                {t("advancedSettings.search.statusEffective")}
              </span>
              <span className={styles.statusValue}>
                {sourceLabel(status.source.effective)}
              </span>
            </div>
            <div className={styles.statusItem}>
              <span className={styles.statusLabel}>
                {t("advancedSettings.search.statusLastSource")}
              </span>
              <span className={styles.statusValue}>
                {sourceLabel(status.last.used_source)}
              </span>
            </div>
            <div className={styles.statusItem}>
              <span className={styles.statusLabel}>
                {t("advancedSettings.search.statusLatency")}
              </span>
              <span className={styles.statusValue}>
                {status.last.elapsed_ms ?? 0} ms
              </span>
            </div>
            <div className={styles.statusItem}>
              <span className={styles.statusLabel}>
                {t("advancedSettings.search.statusFallbackCount")}
              </span>
              <span className={styles.statusValue}>
                {status.last.fallback_count}
              </span>
            </div>
            <div className={styles.statusItem}>
              <span className={styles.statusLabel}>
                {t("advancedSettings.search.statusLastStatus")}
              </span>
              <span className={styles.statusValue}>
                {status.last.status === "ok"
                  ? t("advancedSettings.search.statusOk")
                  : t("advancedSettings.search.statusError")}
                {status.last.degraded
                  ? ` · ${t("advancedSettings.search.statusDegraded")}`
                  : ""}
              </span>
            </div>
          </div>
        ) : (
          <p className={styles.statusDesc}>
            {t("advancedSettings.search.statusNever")}
          </p>
        )}
        {engineEntries.length > 0 ? (
          <div className={styles.engineChips}>
            {engineEntries.map(([name, info]) => (
              <span
                key={name}
                className={cx(
                  styles.engineChip,
                  info.status === "ok"
                    ? styles.engineChipOk
                    : styles.engineChipBad,
                )}
              >
                {name} · {info.count ?? 0}
              </span>
            ))}
          </div>
        ) : null}
        <p className={styles.runtimeLine}>
          {t("advancedSettings.search.statusNative")}:{" "}
          {nativeLast
            ? `${nativeLast.status ?? "—"} · ${nativeLast.elapsed_ms ?? 0} ms · ${
                nativeLast.returned ?? 0
              }${nativeLast.error ? ` · ${nativeLast.error}` : ""}`
            : t("advancedSettings.search.statusNever")}
        </p>
        <p className={styles.runtimeLine}>
          {t("advancedSettings.search.statusEngines")}:{" "}
          {status?.tools_visible?.join(", ") || "—"}
        </p>
      </div>

      <div className={styles.grid}>
        {sortedProviders.map((provider) => {
          const isActive = activeSource?.id === provider.id;
          const needsSetup = !provider.configured;
          const logo = searchProviderLogo(provider.id);
          const cardClass = cx(
            styles.card,
            isActive && styles.cardActive,
            needsSetup && styles.cardSetup,
          );

          return (
            <div
              key={provider.id}
              className={cardClass}
              role={needsSetup ? "button" : undefined}
              tabIndex={needsSetup ? 0 : undefined}
              onClick={needsSetup ? () => setEditing(provider) : undefined}
              onKeyDown={
                needsSetup
                  ? (e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setEditing(provider);
                      }
                    }
                  : undefined
              }
            >
              <div className={styles.cardHeader}>
                <div className={styles.logoTile}>
                  <img
                    src={logo}
                    alt={provider.name}
                    className={styles.logo}
                    draggable={false}
                  />
                </div>
                <div className={styles.titleBlock}>
                  <div className={styles.nameRow}>
                    <span className={styles.name}>{provider.name}</span>
                  </div>
                </div>
                <div className={styles.badges}>
                  {isActive ? (
                    <span className={cx(styles.badge, styles.badgeActive)}>
                      <Check size={11} />
                      {t("setupWizard.search.configured")}
                    </span>
                  ) : provider.configured ? (
                    <span className={cx(styles.badge, styles.badgeOk)}>
                      {t("setupWizard.search.configured")}
                    </span>
                  ) : (
                    <span className={cx(styles.badge, styles.badgeSetup)}>
                      {t("setupWizard.search.unconfigured")}
                    </span>
                  )}
                </div>
              </div>

              <p className={styles.description}>{t(provider.descriptionKey)}</p>

              <div className={styles.actions}>
                <Button
                  size="small"
                  type={needsSetup ? "primary" : "default"}
                  icon={<Settings2 size={14} />}
                  onClick={(e) => {
                    e.stopPropagation();
                    setEditing(provider);
                  }}
                >
                  {needsSetup
                    ? t("advancedSettings.search.configure")
                    : t("common.edit")}
                </Button>
              </div>
            </div>
          );
        })}
      </div>

      <Text className={styles.footer}>
        {t("setupWizard.search.configuredCount", {
          count: configuredCount,
          total: providers.length,
        })}
      </Text>

      {editing ? (
        <ConfigureDrawer
          provider={editing}
          envVars={envVars}
          open
          onClose={() => setEditing(null)}
          onSaved={() => void fetchEnvVars()}
        />
      ) : null}
    </>
  );
}

export { SearchConfigPage as SearchSettingsPanel };
