import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
} from "react";
import {
  Alert,
  Button,
  Checkbox,
  Collapse,
  Drawer,
  Empty,
  Input,
  Modal,
  Popconfirm,
  Segmented,
  Space,
  Switch,
  Tag,
  Typography,
} from "antd";
import { message } from "@/utils/antdMessage";

import {
  BookOpen,
  LayoutGrid,
  List,
  Package,
  Plus,
  Store,
  Trash2,
  Upload,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";
import cx from "classnames";
import {
  pluginsApi,
  type DshInstalledPlugin,
  type DshInstalledView,
  type InstalledPlugin,
} from "../../../api/modules/plugins";
import type { ResourceVisibilityMode } from "../../../api/modules/userGroups";
import { ResourceVisibilityCollapse } from "../../../components/ResourceVisibilityFields";
import { ResizableTable } from "../../../components/ResizableTable";
import { CardSkeleton } from "../../../components/Skeleton";
import { useCardTableView } from "../../../hooks/useCardTableView";
import {
  ensureBuiltinToolRenderers,
  reloadPluginToolUis,
} from "../../../plugins/toolRenderers";
import { updateToolPluginIndex } from "../../../plugins/toolRenderers/toolPluginIndex";
import { apiErrorMessage } from "../../../utils/apiError";
import styles from "./index.module.less";
import { PluginIconView } from "./PluginIconView";
import { PluginGroupTag } from "./PluginGroupTag";
import { PluginCardMeta } from "./PluginCardMeta";
import { notifyPluginsChanged, PLUGINS_CHANGED_EVENT } from "./pluginsEvents";

const { Text, Paragraph } = Typography;

async function syncPluginUis(rows: InstalledPlugin[]): Promise<void> {
  ensureBuiltinToolRenderers();
  updateToolPluginIndex(rows);
  await reloadPluginToolUis(rows);
}

function statusTag(row: InstalledPlugin, t: (key: string) => string) {
  if (row.error)
    return (
      <Tag color="error" bordered={false}>
        {t("plugins.statusError")}
      </Tag>
    );
  if (row.enabled === false)
    return (
      <Tag color="default" bordered={false}>
        {t("plugins.statusDisabled")}
      </Tag>
    );
  return (
    <Tag color={row.loaded ? "success" : "default"} bordered={false}>
      {row.loaded ? t("plugins.statusLoaded") : t("plugins.statusIdle")}
    </Tag>
  );
}

/** Explicitly label DSH as having no UI surface: expected, not broken. */
function dshSurfaceTag(
  row: DshInstalledPlugin,
  t: (key: string) => string,
) {
  const supported = row.runtime.surface_supported;
  if (supported === true) return null;
  const reason =
    row.runtime.surface_reason ||
    t("plugins.uiNoSurfaceHint");
  return (
    <Tag bordered={false} title={reason}>
      {t("plugins.uiNoSurface")}
    </Tag>
  );
}

function octopSurfacesNotice(
  row: InstalledPlugin,
  t: (key: string, options?: Record<string, unknown>) => string,
) {
  const surfaces = row.ui?.surfaces ?? [];
  if (surfaces.length === 0) return null;
  const supported = surfaces
    .filter((surface) => surface.supported)
    .map((surface) => surface.title || surface.id);
  const unsupported = surfaces.filter((surface) => !surface.supported);
  return (
    <div style={{ marginTop: 6, fontSize: "var(--fn-text-2xs)", opacity: 0.7, lineHeight: 1.5 }}>
      {supported.length > 0 ? (
        <div>{t("plugins.uiSurfaceAt", { slots: supported.join("、") })}</div>
      ) : null}
      {unsupported.map((surface) => (
        <div key={surface.id}>
          {t("plugins.uiSurfaceUnsupported", {
            slot: surface.slot,
            code: surface.reason_code || "SURFACE_SLOT_UNKNOWN",
          })}
        </div>
      ))}
    </div>
  );
}

/** Runtime readiness for a DSH bundle, reusing the market panel's wording. */
function dshRuntimeTag(
  row: DshInstalledPlugin,
  t: (key: string) => string,
) {
  if (row.error)
    return (
      <Tag color="error" bordered={false}>
        {t("plugins.statusError")}
      </Tag>
    );
  if (row.runtime.status === "visible")
    return (
      <Tag color="success" bordered={false}>
        {t("plugins.dsh.runtimeVisible")}
      </Tag>
    );
  if (row.runtime.status === "broken")
    return (
      <Tag color="error" bordered={false}>
        {t("plugins.dsh.runtimeBroken")}
      </Tag>
    );
  return (
    <Tag color="warning" bordered={false}>
      {t("plugins.dsh.runtimeNotVisible")}
    </Tag>
  );
}

/** Server-wide plugin install, reload, enable, detail, and uninstall surface. */
export function InstalledPluginsPanel() {
  const { t } = useTranslation();
  const [, setSearchParams] = useSearchParams();
  const [plugins, setPlugins] = useState<InstalledPlugin[]>([]);
  const [dshInstalled, setDshInstalled] = useState<DshInstalledView | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [installOpen, setInstallOpen] = useState(false);
  const [installUrl, setInstallUrl] = useState("");
  const [installing, setInstalling] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);
  const [overwrite, setOverwrite] = useState(false);
  const [reloading, setReloading] = useState(false);
  const [togglingId, setTogglingId] = useState<string | null>(null);
  const [detail, setDetail] = useState<InstalledPlugin | null>(null);
  const { viewMode, setViewMode, showCardView } = useCardTableView("card");

  const fetchPlugins = useCallback(async () => {
    setLoading(true);
    // DSH bundles are tracked by the market ledger, not ``/plugins``; fetch
    // them separately so one failing source never blanks the host list.
    void pluginsApi
      .listDshInstalled()
      .then(setDshInstalled)
      .catch((err) => {
        console.warn("[plugins] dsh installed list failed:", err);
        setDshInstalled(null);
      });
    try {
      const rows = await pluginsApi.list();
      setPlugins(rows);
      void syncPluginUis(rows).catch((err) =>
        console.warn("[plugin-ui] sync after list failed:", err),
      );
    } catch (err) {
      message.error(t("plugins.loadError"));
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void fetchPlugins();
  }, [fetchPlugins]);

  useEffect(() => {
    const onChanged = () => {
      void fetchPlugins();
    };
    window.addEventListener(PLUGINS_CHANGED_EVENT, onChanged);
    return () => window.removeEventListener(PLUGINS_CHANGED_EVENT, onChanged);
  }, [fetchPlugins]);

  const handleInstall = async () => {
    const url = installUrl.trim();
    if (!url) return;
    setInstalling(true);
    try {
      await pluginsApi.install(url);
      message.success(t("plugins.installSuccess"));
      setInstallOpen(false);
      setInstallUrl("");
      notifyPluginsChanged();
      await fetchPlugins();
    } catch (err) {
      message.error(apiErrorMessage(err, t("plugins.installFailed"), t));
    } finally {
      setInstalling(false);
    }
  };

  const handleFileSelected = async (event: ChangeEvent<HTMLInputElement>) => {
    const next = event.target.files?.[0] ?? null;
    event.target.value = "";
    if (!next) return;
    if (!next.name.toLowerCase().endsWith(".zip")) {
      message.error(t("plugins.zipOnly"));
      return;
    }
    setUploading(true);
    try {
      await pluginsApi.upload(next, overwrite);
      message.success(t("plugins.installSuccess"));
      notifyPluginsChanged();
      await fetchPlugins();
    } catch (err) {
      message.error(apiErrorMessage(err, t("plugins.installFailed"), t));
    } finally {
      setUploading(false);
    }
  };

  const handleReload = async () => {
    setReloading(true);
    try {
      await pluginsApi.reload();
      message.success(t("plugins.reloadSuccess"));
      await fetchPlugins();
    } catch (err) {
      message.error(apiErrorMessage(err, t("plugins.reloadFailed"), t));
    } finally {
      setReloading(false);
    }
  };

  const handleUninstall = async (pluginId: string) => {
    try {
      await pluginsApi.uninstall(pluginId);
      message.success(t("plugins.uninstallSuccess"));
      if (detail?.id === pluginId) setDetail(null);
      notifyPluginsChanged();
      await fetchPlugins();
    } catch (err) {
      message.error(apiErrorMessage(err, t("plugins.uninstallFailed"), t));
    }
  };

  const handleToggleEnabled = async (
    row: InstalledPlugin,
    enabled: boolean,
  ) => {
    setTogglingId(row.id);
    try {
      const updated = await pluginsApi.setEnabled(row.id, enabled);
      setPlugins((prev) =>
        prev.map((item) =>
          item.id === row.id ? { ...item, ...updated } : item,
        ),
      );
      setDetail((prev) =>
        prev?.id === row.id ? { ...prev, ...updated } : prev,
      );
      message.success(
        enabled ? t("plugins.enabledSuccess") : t("plugins.disabledSuccess"),
      );
      await fetchPlugins();
    } catch (err) {
      message.error(apiErrorMessage(err, t("plugins.enableFailed"), t));
    } finally {
      setTogglingId(null);
    }
  };

  const columns = [
    {
      title: t("plugins.colName"),
      key: "name",
      width: 220,
      ellipsis: true,
      render: (_: unknown, row: InstalledPlugin) => (
        <span className={styles.tableNameCell}>
          <PluginIconView icon={row.icon} size={28} />
          <span className={styles.tableNameText}>{row.name || row.id}</span>
        </span>
      ),
    },
    {
      title: t("plugins.colId"),
      dataIndex: "id",
      key: "id",
      width: 160,
      ellipsis: true,
      render: (id: string) => <span className={styles.tableMono}>{id}</span>,
    },
    {
      title: t("plugins.colVersion"),
      dataIndex: "version",
      key: "version",
      width: 96,
      render: (version: string | undefined) => (
        <span className={styles.tableCellSingle}>{version || "—"}</span>
      ),
    },
    {
      title: t("plugins.colKind"),
      dataIndex: "kind",
      key: "kind",
      width: 100,
      render: (kind: string | undefined) => <Tag>{kind || "—"}</Tag>,
    },
    {
      title: t("plugins.colGroup"),
      dataIndex: "group",
      key: "group",
      width: 100,
      render: (group: string | null | undefined) =>
        group ? <PluginGroupTag group={group} /> : "—",
    },
    {
      title: t("plugins.colStatus"),
      key: "status",
      width: 110,
      render: (_: unknown, row: InstalledPlugin) => statusTag(row, t),
    },
    {
      title: t("plugins.colEnabled"),
      key: "enabled",
      width: 88,
      render: (_: unknown, row: InstalledPlugin) => (
        <Switch
          size="small"
          checked={row.enabled !== false}
          loading={togglingId === row.id}
          disabled={!!row.error}
          onChange={(checked) => void handleToggleEnabled(row, checked)}
        />
      ),
    },
    {
      title: t("plugins.colActions"),
      key: "actions",
      width: 128,
      render: (_: unknown, row: InstalledPlugin) => (
        <div className={styles.tableActions}>
          <Button type="link" size="small" onClick={() => setDetail(row)}>
            {t("plugins.viewDetails")}
          </Button>
          <Popconfirm
            title={t("plugins.uninstallConfirm", { id: row.id })}
            onConfirm={() => void handleUninstall(row.id)}
          >
            <Button
              type="text"
              danger
              size="small"
              className={styles.iconBtn}
              icon={<Trash2 size={15} />}
              aria-label={t("plugins.uninstall")}
            />
          </Popconfirm>
        </div>
      ),
    },
  ];

  return (
    <div className={styles.panel}>
      <Collapse
        className={styles.guide}
        items={[
          {
            key: "guide",
            label: (
              <span className={styles.guideLabel}>
                <BookOpen size={15} />
                {t("plugins.guideTitle")}
              </span>
            ),
            children: (
              <div className={styles.guideBody}>
                <div className={styles.guideSection}>
                  <Text strong>{t("plugins.guideDevelopTitle")}</Text>
                  <Paragraph className={styles.guideText}>
                    {t("plugins.guideDevelopBody")}
                  </Paragraph>
                </div>
                <div className={styles.guideSection}>
                  <Text strong>{t("plugins.guidePackageTitle")}</Text>
                  <Paragraph className={styles.guideText}>
                    {t("plugins.guidePackageBody")}
                  </Paragraph>
                </div>
                <div className={styles.guideSection}>
                  <Text strong>{t("plugins.guideImportTitle")}</Text>
                  <Paragraph className={styles.guideText}>
                    {t("plugins.guideImportBody")}
                  </Paragraph>
                </div>
                <div className={styles.guideSection}>
                  <Text strong>{t("plugins.guideExampleTitle")}</Text>
                  <pre className={styles.codeBlock}>
                    {t("plugins.guideExampleYaml")}
                  </pre>
                </div>
              </div>
            ),
          },
        ]}
      />

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 12 }}
        message={t("plugins.uiTrustTitle")}
        description={t("plugins.uiTrustNotice")}
      />

      <div className={styles.toolbar}>
        <div className={styles.toolbarLeft}>
          <span className={styles.toolbarCount}>
            {t("plugins.totalPlugins", { count: plugins.length })}
          </span>
        </div>
        <div className={styles.toolbarRight}>
          <Segmented
            size="small"
            value={viewMode}
            onChange={(v) => setViewMode(v as "card" | "table")}
            options={[
              {
                value: "card",
                label: (
                  <span className={styles.viewModeLabel}>
                    <LayoutGrid size={14} />
                    {t("plugins.viewCard")}
                  </span>
                ),
              },
              {
                value: "table",
                label: (
                  <span className={styles.viewModeLabel}>
                    <List size={14} />
                    {t("plugins.viewTable")}
                  </span>
                ),
              },
            ]}
          />
          <Checkbox
            checked={overwrite}
            onChange={(e) => setOverwrite(e.target.checked)}
          >
            {t("plugins.overwriteInstall")}
          </Checkbox>
          <Button loading={reloading} onClick={() => void handleReload()}>
            {t("plugins.reload")}
          </Button>
          <Button
            icon={<Upload size={16} />}
            loading={uploading}
            onClick={() => fileInputRef.current?.click()}
          >
            {t("plugins.installFromZip")}
          </Button>
          <Button
            type="primary"
            icon={<Plus size={16} />}
            onClick={() => setInstallOpen(true)}
          >
            {t("plugins.install")}
          </Button>
        </div>
      </div>

      {dshInstalled && dshInstalled.plugins.length > 0 ? (
        <section className={styles.dshInstalled}>
          <div className={styles.dshInstalledHead}>
            <div className={styles.dshInstalledHeading}>
              <Text strong>
                {t("plugins.dshInstalledTitle", {
                  count: dshInstalled.plugins.length,
                })}
              </Text>
              <span className={styles.dshInstalledHint}>
                {t("plugins.dshInstalledHint", {
                  path: dshInstalled.market_root,
                })}
              </span>
            </div>
            <Button
              size="small"
              icon={<Store size={14} />}
              onClick={() =>
                setSearchParams({ tab: "market" }, { replace: true })
              }
            >
              {t("plugins.dshInstalledManage")}
            </Button>
          </div>
          <div className={styles.dshInstalledList}>
            {dshInstalled.plugins.map((row) => (
              <div key={row.plugin_id} className={styles.dshInstalledRow}>
                <div className={styles.dshInstalledMain}>
                  <span className={styles.dshInstalledName}>
                    {row.name || row.plugin_id}
                  </span>
                  <span className={styles.tableMono}>{row.plugin_id}</span>
                </div>
                <div className={styles.dshInstalledMeta}>
                  <Tag bordered={false}>{row.version || "—"}</Tag>
                  {dshRuntimeTag(row, t)}
                  {dshSurfaceTag(row, t)}
                </div>
                <div className={styles.dshInstalledSource}>
                  {t("plugins.dshInstalledSource", {
                    source: row.source_url || t("plugins.dshInstalledLocalSource"),
                  })}
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {showCardView ? (
        loading ? (
          <div className={styles.loadingSkeleton}>
            <CardSkeleton count={3} />
          </div>
        ) : plugins.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={
              <div className={styles.emptyWithAction}>
                <div>{t("plugins.empty")}</div>
                <div className={styles.emptyHint}>{t("plugins.emptyHint")}</div>
                <Button
                  type="primary"
                  icon={<Store size={16} />}
                  onClick={() =>
                    setSearchParams({ tab: "market" }, { replace: true })
                  }
                >
                  {t("plugins.goToMarket")}
                </Button>
              </div>
            }
          />
        ) : (
          <div className={styles.cardGrid}>
            {plugins.map((row) => {
              const enabled = row.enabled !== false;
              return (
                <article
                  key={row.id}
                  className={cx(styles.card, !enabled && styles.cardDisabled)}
                >
                  <div className={styles.cardBody}>
                    <div className={styles.cardTop}>
                      <PluginIconView
                        icon={row.icon}
                        size={32}
                        className={styles.cardIcon}
                      />
                      <div className={styles.cardTitleCol}>
                        <h3 className={styles.cardName}>
                          {row.name || row.id}
                        </h3>
                        <PluginCardMeta
                          kind={row.kind}
                          group={row.group}
                          version={row.version}
                          trailing={statusTag(row, t)}
                        />
                      </div>
                    </div>
                    <p className={styles.cardDesc}>
                      {row.error ||
                        row.description ||
                        t("plugins.noDescription")}
                    </p>
                    {octopSurfacesNotice(row, t)}
                  </div>
                  <div className={styles.cardFooter}>
                    <button
                      type="button"
                      className={styles.detailLink}
                      onClick={() => setDetail(row)}
                    >
                      {t("plugins.viewDetails")}
                    </button>
                    <span className={styles.cardFooterSpacer} />
                    <Switch
                      size="small"
                      checked={enabled}
                      loading={togglingId === row.id}
                      disabled={!!row.error}
                      onChange={(checked) =>
                        void handleToggleEnabled(row, checked)
                      }
                    />
                    <Popconfirm
                      title={t("plugins.uninstallConfirm", { id: row.id })}
                      onConfirm={() => void handleUninstall(row.id)}
                    >
                      <Button
                        type="text"
                        danger
                        size="small"
                        className={styles.iconBtn}
                        icon={<Trash2 size={15} />}
                        aria-label={t("plugins.uninstall")}
                      />
                    </Popconfirm>
                  </div>
                </article>
              );
            })}
          </div>
        )
      ) : (
        <ResizableTable
          storageKey="admin-plugins"
          className={styles.table}
          rowKey="id"
          loading={loading}
          columns={columns}
          dataSource={plugins}
          pagination={false}
          scroll={{ x: 960 }}
          locale={{
            emptyText: (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={
                  <div className={styles.emptyWithAction}>
                    <div>{t("plugins.empty")}</div>
                    <div className={styles.emptyHint}>
                      {t("plugins.emptyHint")}
                    </div>
                    <Button
                      type="primary"
                      icon={<Store size={16} />}
                      onClick={() =>
                        setSearchParams({ tab: "market" }, { replace: true })
                      }
                    >
                      {t("plugins.goToMarket")}
                    </Button>
                  </div>
                }
              />
            ),
          }}
        />
      )}

      <Drawer
        title={
          detail ? (
            <div className={styles.drawerTitleBar}>
              <PluginIconView icon={detail.icon} size={32} />
              <div className={styles.drawerTitleMeta}>
                <div className={styles.drawerTitleText}>
                  {detail.name || detail.id}
                </div>
                <div className={styles.drawerTitleId}>{detail.id}</div>
              </div>
            </div>
          ) : (
            t("plugins.detailTitle")
          )
        }
        open={!!detail}
        onClose={() => setDetail(null)}
        width={500}
        destroyOnHidden
        styles={{ body: { paddingTop: 12, paddingBottom: 24 } }}
      >
        {detail ? (
          <div className={styles.drawerContent}>
            {detail.error ? (
              <Alert
                type="error"
                showIcon
                message={detail.error}
                className={styles.drawerAlert}
              />
            ) : null}

            <p className={styles.drawerDesc}>
              {detail.description || t("plugins.noDescription")}
            </p>

            <PluginCardMeta
              kind={detail.kind}
              group={detail.group}
              version={detail.version}
              trailing={
                <>
                  {statusTag(detail, t)}
                  {detail.ui?.entry ? (
                    <Tag color="blue" bordered={false}>
                      {t("plugins.hasUi")}
                    </Tag>
                  ) : null}
                </>
              }
            />

            <div className={styles.drawerEnableRow}>
              <div className={styles.drawerEnableText}>
                <span className={styles.drawerEnableLabel}>
                  {t("plugins.colEnabled")}
                </span>
                <span className={styles.drawerEnableHint}>
                  {t("plugins.detailEnableHint")}
                </span>
              </div>
              <Switch
                checked={detail.enabled !== false}
                loading={togglingId === detail.id}
                disabled={!!detail.error}
                onChange={(checked) =>
                  void handleToggleEnabled(detail, checked)
                }
              />
            </div>

            <ResourceVisibilityCollapse
              allowOwner={false}
              visibility={detail.visibility === "groups" ? "groups" : "all"}
              groupIds={detail.group_ids ?? []}
              hint={t("resourceVisibility.groupAccessHint")}
              defaultOpen={detail.visibility === "groups"}
              onChange={(next) => {
                const nextVisibility: ResourceVisibilityMode =
                  next.visibility === "groups" ? "groups" : "all";
                if (nextVisibility === "groups" && next.groupIds.length === 0) {
                  setDetail({
                    ...detail,
                    visibility: "groups",
                    group_ids: [],
                  });
                  return;
                }
                void pluginsApi
                  .setVisibility(detail.id, {
                    visibility: nextVisibility,
                    group_ids: nextVisibility === "groups" ? next.groupIds : [],
                  })
                  .then((updated) => {
                    setDetail(updated);
                    setPlugins((prev) =>
                      prev.map((row) =>
                        row.id === updated.id ? updated : row,
                      ),
                    );
                    message.success(t("plugins.visibilitySaved"));
                  })
                  .catch((err: unknown) => {
                    message.error(
                      apiErrorMessage(err, t("plugins.visibilityFailed"), t),
                    );
                  });
              }}
            />

            <section className={styles.drawerSection}>
              <h4 className={styles.drawerSectionTitle}>
                {t("plugins.detailInfo")}
              </h4>
              <div className={styles.detailList}>
                <div className={styles.detailRow}>
                  <span className={styles.detailLabel}>
                    {t("plugins.colPath")}
                  </span>
                  <span className={cx(styles.detailValue, styles.detailMono)}>
                    {detail.path || "—"}
                  </span>
                </div>
                <div className={styles.detailRow}>
                  <span className={styles.detailLabel}>
                    {t("plugins.colUi")}
                  </span>
                  <span className={cx(styles.detailValue, styles.detailMono)}>
                    {detail.ui?.entry || "—"}
                  </span>
                </div>
                <div className={styles.detailRow}>
                  <span className={styles.detailLabel}>
                    {t("plugins.colRequires")}
                  </span>
                  <span className={styles.detailValue}>
                    {(detail.requires || []).length > 0 ? (
                      <span className={styles.requiresTags}>
                        {detail.requires!.map((req) => (
                          <Tag key={req}>{req}</Tag>
                        ))}
                      </span>
                    ) : (
                      "—"
                    )}
                  </span>
                </div>
              </div>
            </section>
          </div>
        ) : null}
      </Drawer>

      <Modal
        title={t("plugins.installTitle")}
        open={installOpen}
        onCancel={() => setInstallOpen(false)}
        onOk={() => void handleInstall()}
        confirmLoading={installing}
        okText={t("plugins.install")}
      >
        <Space direction="vertical" style={{ width: "100%" }} size="middle">
          <Alert type="info" showIcon message={t("plugins.installUrlHint")} />
          <Input
            prefix={<Package size={16} />}
            placeholder={t("plugins.installUrlPlaceholder")}
            value={installUrl}
            onChange={(e) => setInstallUrl(e.target.value)}
            onPressEnter={() => void handleInstall()}
          />
        </Space>
      </Modal>

      <input
        ref={fileInputRef}
        type="file"
        accept=".zip,application/zip"
        style={{ display: "none" }}
        onChange={(e) => void handleFileSelected(e)}
      />
    </div>
  );
}
