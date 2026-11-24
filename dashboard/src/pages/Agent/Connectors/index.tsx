import { useCallback, useEffect, useMemo, useState } from "react";
import { Button, Spin } from "antd";
import { message } from "@/utils/antdMessage";

import {
  Blocks,
  Link2,
  Plug,
  Plus,
  RefreshCw,
  Wrench,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";

import PageShell from "../../../layouts/PageShell";
import PillScroller from "../../../components/PillScroller";
import TabBar, { type TabBarItem } from "../../../components/TabLabel/TabBar";
import StreamSetupGuide from "../../../components/StreamSetupGuide/StreamSetupGuide";
import { HappyclawEmptyMascot } from "../../../components/EmptyState/HappyclawEmptyMascot";
import { useCurrentUser } from "../../../hooks/useCurrentUser";
import { CONNECTOR_TAB_PERMISSIONS, userCan } from "../../../utils/permissions";
import {
  connectorsApi,
  type ConnectorCatalogEntry,
  type ConnectorInstance,
} from "../../../api/modules/connectors";
import { ConnectorCard } from "./ConnectorCard";
import { ConnectorInstanceCard } from "./ConnectorInstanceCard";
import { CustomMcpTab } from "./CustomMcpTab";
import { ConnectorConfigDrawer } from "./configDrawer/ConnectorConfigDrawer";
import {
  CONNECTOR_CATEGORY_ALL,
  connectorCategoryOptions,
  matchesConnectorCategory,
} from "./connectorCategories";
import { notifyConnectorsChanged } from "./customMcpUtils";
import { useConnectorInstances } from "./useConnectors";
import { ResourceAudienceFilter } from "../../../components/ResourceAudienceFilter";
import {
  matchesResourceAudience,
  type ResourceAudience,
} from "../../../utils/resourceAudience";
import styles from "./index.module.less";

type ConnectorTab = "enabled" | "builtin" | "custom";

const CONNECTOR_TABS: TabBarItem<ConnectorTab>[] = [
  { key: "enabled", labelKey: "connectors.tabEnabled", icon: Link2 },
  { key: "builtin", labelKey: "connectors.tabBuiltin", icon: Blocks },
  { key: "custom", labelKey: "connectors.tabCustom", icon: Wrench },
];

export default function ConnectorsPage() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const [activeTab, setActiveTab] = useState<ConnectorTab>("enabled");
  const [activeCategory, setActiveCategory] = useState(CONNECTOR_CATEGORY_ALL);
  const [drawerEntry, setDrawerEntry] = useState<ConnectorCatalogEntry | null>(
    null,
  );
  const [drawerInstance, setDrawerInstance] =
    useState<ConnectorInstance | null>(null);
  const [customFocusServerName, setCustomFocusServerName] = useState<
    string | null
  >(null);
  const { catalog, instances, loading, refresh } = useConnectorInstances();
  const user = useCurrentUser();
  const visibleConnectorTabs = useMemo(
    () =>
      CONNECTOR_TABS.filter((tab) =>
        userCan(user, CONNECTOR_TAB_PERMISSIONS[tab.key]),
      ),
    [user],
  );
  const resolvedConnectorTab = visibleConnectorTabs.some(
    (tab) => tab.key === activeTab,
  )
    ? activeTab
    : visibleConnectorTabs[0]?.key ?? "enabled";
  const [audience, setAudience] = useState<ResourceAudience>("all");
  const visibleInstances = useMemo(
    () =>
      instances.filter((instance) =>
        matchesResourceAudience(audience, {
          owned: user != null && instance.owner_user_id === user.id,
          shared: instance.shared,
        }),
      ),
    [audience, instances, user],
  );

  const configuredCount = useMemo(() => {
    return instances.filter((instance) => instance.has_credentials).length;
  }, [instances]);

  const categoryOptions = useMemo(
    () =>
      connectorCategoryOptions(
        catalog.map((entry) => entry.category),
        (category) => t(`connectors.category.${category}`, category),
        t("connectors.categoryAll"),
      ),
    [catalog, t],
  );
  const showCategoryPills = categoryOptions.length > 1;

  useEffect(() => {
    if (
      activeCategory &&
      !categoryOptions.some((option) => option.value === activeCategory)
    ) {
      setActiveCategory(CONNECTOR_CATEGORY_ALL);
    }
  }, [activeCategory, categoryOptions]);

  const catalogByKind = useMemo(() => {
    const byKind = new Map<string, ConnectorCatalogEntry>();
    for (const entry of catalog) byKind.set(entry.kind, entry);
    return byKind;
  }, [catalog]);

  const visibleCatalog = useMemo(
    () =>
      catalog.filter((entry) =>
        matchesConnectorCategory(entry.category, activeCategory),
      ),
    [activeCategory, catalog],
  );
  const categoryInstances = useMemo(
    () =>
      visibleInstances.filter((instance) =>
        matchesConnectorCategory(
          catalogByKind.get(instance.kind)?.category,
          activeCategory,
        ),
      ),
    [activeCategory, catalogByKind, visibleInstances],
  );
  const visibleConfiguredCount = useMemo(() => {
    if (!activeCategory) return configuredCount;
    const kinds = new Set(visibleCatalog.map((entry) => entry.kind));
    return instances.filter(
      (instance) => instance.has_credentials && kinds.has(instance.kind),
    ).length;
  }, [activeCategory, configuredCount, instances, visibleCatalog]);

  const categoryPills = showCategoryPills ? (
    <PillScroller
      className={styles.categoryScroller}
      options={categoryOptions}
      active={activeCategory}
      onSelect={setActiveCategory}
      prevLabel={t("experts.marketScenePrev")}
      nextLabel={t("experts.marketSceneNext")}
    />
  ) : null;

  useEffect(() => {
    const oauthState = searchParams.get("oauth_state");
    if (!oauthState) return;
    void (async () => {
      try {
        const pending = await connectorsApi.oauthPending(oauthState);
        const kind = String(pending.kind || "");
        const entry = catalog.find((c) => c.kind === kind);
        const tokens = pending.tokens ?? {};
        if (!entry || !tokens.access_token) {
          message.error(t("connectors.oauthFailed", "获取授权结果失败"));
          return;
        }
        const credentials: Record<string, unknown> = {
          access_token: tokens.access_token,
        };
        if (tokens.refresh_token)
          credentials.refresh_token = tokens.refresh_token;
        if (tokens.expires_at) credentials.expires_at = tokens.expires_at;
        if (tokens.oauth_client_id)
          credentials.oauth_client_id = tokens.oauth_client_id;
        if (tokens.oauth_client_secret)
          credentials.oauth_client_secret = tokens.oauth_client_secret;
        if (tokens.openid) credentials.openid = tokens.openid;

        await connectorsApi.createInstance({
          kind: entry.kind,
          display_name: entry.name,
          description: entry.description,
          credentials,
          default_open: false,
        });
        await refresh();
        notifyConnectorsChanged();
        message.success(t("connectors.createSuccess", "连接器已创建"));
      } catch {
        message.error(t("connectors.oauthFailed", "获取授权结果失败"));
      }
      searchParams.delete("oauth_state");
      setSearchParams(searchParams, { replace: true });
    })();
  }, [searchParams, setSearchParams, catalog, refresh, t]);

  const handleConfigure = useCallback(
    (entry: ConnectorCatalogEntry, instance: ConnectorInstance | null) => {
      setDrawerEntry(entry);
      setDrawerInstance(instance);
    },
    [],
  );

  const handleSaved = useCallback(async () => {
    await refresh();
    notifyConnectorsChanged();
  }, [refresh]);

  const handleCloseDrawer = useCallback(() => {
    setDrawerEntry(null);
    setDrawerInstance(null);
  }, []);

  return (
    <PageShell.Tabbed
      title={t("pageShell.connectors.title")}
      subtitle={t("pageShell.connectors.subtitle")}
      tabBar={
        <TabBar
          tabs={visibleConnectorTabs}
          activeKey={resolvedConnectorTab}
          onChange={(key) => {
            if (key === "custom") setCustomFocusServerName(null);
            setActiveTab(key);
          }}
        />
      }
    >
      {resolvedConnectorTab === "custom" ? (
        <CustomMcpTab focusServerName={customFocusServerName} />
      ) : resolvedConnectorTab === "enabled" ? (
        loading ? (
          <div className={styles.loadingState}>
            <Spin />
          </div>
        ) : (
          <>
            {instances.length === 0 ? (
              <div className={styles.emptyLayout}>
                <StreamSetupGuide
                  className={styles.emptyGuide}
                  wide
                  plain
                  icon={<HappyclawEmptyMascot />}
                  title={t("connectors.emptyGuideTitle")}
                  description={t("connectors.emptyGuideDesc")}
                  steps={[
                    {
                      label: t("connectors.emptyGuideStepWhat"),
                      detail: t("connectors.emptyGuideStepWhatDetail"),
                    },
                    {
                      label: t("connectors.emptyGuideStepHow"),
                      detail: t("connectors.emptyGuideStepHowDetail"),
                    },
                    {
                      label: t("connectors.emptyGuideStepShare"),
                      detail: t("connectors.emptyGuideStepShareDetail"),
                    },
                  ]}
                  primaryAction={{
                    label: t("connectors.emptyGuideBrowseBuiltin"),
                    onClick: () => setActiveTab("builtin"),
                    icon: <Plug size={14} />,
                  }}
                  secondaryAction={{
                    label: t("connectors.emptyGuideAddCustom"),
                    onClick: () => {
                      setCustomFocusServerName(null);
                      setActiveTab("custom");
                    },
                    icon: <Plus size={14} />,
                    type: "default",
                  }}
                />
              </div>
            ) : (
              <>
                <div className={styles.listToolbar}>
                  <div className={styles.listToolbarStart}>
                    <span className={styles.listToolbarMeta}>
                      {t("connectors.enabledSummary", {
                        count: categoryInstances.length,
                        defaultValue: "已启用 {{count}} 个连接器实例",
                      })}
                    </span>
                    <ResourceAudienceFilter
                      value={audience}
                      onChange={(value) =>
                        setAudience(value as ResourceAudience)
                      }
                    />
                  </div>
                  <Button
                    icon={<RefreshCw size={14} />}
                    loading={loading}
                    onClick={() => void refresh()}
                  >
                    {t("common.refresh")}
                  </Button>
                </div>
                {categoryPills}
                {visibleInstances.length === 0 ? (
                  <div className={styles.filterEmpty}>
                    {t("resourceAudience.empty")}
                  </div>
                ) : categoryInstances.length === 0 ? (
                  <div className={styles.filterEmpty}>
                    {t("connectors.categoryEmpty")}
                  </div>
                ) : (
                  <div className={styles.typeGrid}>
                    {categoryInstances.map((instance) => (
                      <ConnectorInstanceCard
                        key={instance.instance_id}
                        instance={instance}
                        catalogEntry={catalog.find(
                          (entry) => entry.kind === instance.kind,
                        )}
                        onEdit={(item) => {
                          if (item.kind === "custom-mcp") {
                            setCustomFocusServerName(item.mcp_server_name);
                            setActiveTab("custom");
                            return;
                          }
                          const entry = catalog.find(
                            (row) => row.kind === item.kind,
                          );
                          if (entry) handleConfigure(entry, item);
                        }}
                        onChanged={handleSaved}
                      />
                    ))}
                  </div>
                )}
              </>
            )}
          </>
        )
      ) : (
        <>
          <div className={styles.listToolbar}>
            <span className={styles.listToolbarMeta}>
              {t("connectors.listSummary", {
                total: visibleCatalog.length,
                configured: visibleConfiguredCount,
                defaultValue:
                  "当前支持 {{total}} 个连接器，已配置 {{configured}} 个",
              })}
            </span>
            <Button
              icon={<RefreshCw size={14} />}
              loading={loading}
              onClick={() => void refresh()}
            >
              {t("common.refresh")}
            </Button>
          </div>
          {categoryPills}
          {loading ? (
            <div className={styles.loadingState}>
              <Spin />
            </div>
          ) : activeCategory && visibleCatalog.length === 0 ? (
            <div className={styles.filterEmpty}>
              {t("connectors.categoryEmpty")}
            </div>
          ) : (
            <div className={styles.typeGrid}>
              {visibleCatalog.map((entry) => (
                <ConnectorCard
                  key={entry.kind}
                  entry={entry}
                  onConfigure={handleConfigure}
                />
              ))}
            </div>
          )}
        </>
      )}

      <ConnectorConfigDrawer
        open={drawerEntry !== null}
        entry={drawerEntry}
        instance={drawerInstance}
        onClose={handleCloseDrawer}
        onSaved={(created) => {
          if (created) setDrawerInstance(created);
          void handleSaved();
        }}
      />
    </PageShell.Tabbed>
  );
}
