import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  Button,
  Empty,
  Input,
  Modal,
  Pagination,
  Progress,
  Select,
  Tag,
} from "antd";
import { message } from "@/utils/antdMessage";
import { Download, Plus, RefreshCw, Trash2, UploadCloud, Wrench } from "lucide-react";
import { useTranslation } from "react-i18next";
import cx from "classnames";
import {
  pluginsApi,
  type DshDependencyReport,
  type DshInstallProgress,
  type DshInstallResult,
  type DshMarketEntry,
  type DshMarketView,
  type DshRuntimeStatus,
  type DshStatusView,
} from "../../../api/modules/plugins";
import { apiErrorMessage, parseApiError } from "../../../utils/apiError";
import styles from "./index.module.less";
import { PluginIconView } from "./PluginIconView";
import { notifyPluginsChanged } from "./pluginsEvents";

const PAGE_SIZE_OPTIONS = [12, 24, 48, 96];
const PROGRESS_POLL_MS = 700;

type LoadOutcome =
  | { kind: "installed"; name: string; version: string }
  | {
      kind: "not_ready";
      name: string;
      version: string;
      code: string | null;
      reason: string;
    }
  | {
      kind: "deps_failed";
      name: string;
      version: string;
      code: string | null;
      reason: string;
      missing: string[];
      cause: DshDependencyReport["cause"];
    }
  | { kind: "failed"; name: string; code: string | null; reason: string };

function runtimeTagColor(status: DshRuntimeStatus["status"]): string {
  if (status === "visible") return "success";
  if (status === "missing") return "default";
  if (status === "broken") return "error";
  return "warning";
}

function sourceTagColor(
  status: "ok" | "stale" | "slow" | "error" | "unknown",
): string {
  if (status === "ok") return "success";
  if (status === "stale" || status === "slow") return "warning";
  if (status === "error") return "error";
  return "default";
}

export function DshMarketPanel() {
  const { t } = useTranslation();
  const [view, setView] = useState<DshMarketView | null>(null);
  const [status, setStatus] = useState<DshStatusView | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [probing, setProbing] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [sourceDraft, setSourceDraft] = useState("");
  const [adding, setAdding] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [loadOutcome, setLoadOutcome] = useState<LoadOutcome | null>(null);
  const [selected, setSelected] = useState<Record<string, string>>({});
  const [queryDraft, setQueryDraft] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(PAGE_SIZE_OPTIONS[1]);
  const [progress, setProgress] = useState<DshInstallProgress | null>(null);
  const pollRef = useRef<number | null>(null);

  const stopProgressPolling = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  useEffect(() => stopProgressPolling, [stopProgressPolling]);

  const startProgressPolling = useCallback(
    (pluginId: string) => {
      stopProgressPolling();
      const poll = async () => {
        try {
          const result = await pluginsApi.dshInstallProgress(pluginId);
          setProgress(result.progress);
        } catch {
          // Progress is advisory; the install response still carries the result.
        }
      };
      void poll();
      pollRef.current = window.setInterval(() => void poll(), PROGRESS_POLL_MS);
    },
    [stopProgressPolling],
  );

  const fetchMarket = useCallback(
    async (force = false) => {
      if (force) setRefreshing(true);
      else setLoading(true);
      try {
        const params = { q: query, page, pageSize };
        const next = force
          ? await pluginsApi.refreshDshMarket(params)
          : await pluginsApi.listDshMarket(params);
        setView(next);
        setLoadFailed(false);
      } catch (err) {
        setLoadFailed(true);
        message.error(apiErrorMessage(err, t("plugins.dsh.loadFailed"), t));
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [page, pageSize, query, t],
  );

  const loadStatus = useCallback(
    async (probe = false) => {
      if (probe) setProbing(true);
      try {
        setStatus(await pluginsApi.dshStatus(probe));
      } catch (err) {
        if (probe) {
          message.error(apiErrorMessage(err, t("plugins.dsh.statusFailed"), t));
        }
      } finally {
        setProbing(false);
      }
    },
    [t],
  );

  useEffect(() => {
    void fetchMarket();
  }, [fetchMarket]);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  const handleAddSource = async () => {
    const url = sourceDraft.trim();
    if (!url) return;
    setAdding(true);
    try {
      await pluginsApi.addDshSource(url);
      setSourceDraft("");
      await fetchMarket(true);
    } catch (err) {
      message.error(apiErrorMessage(err, t("plugins.dsh.addSourceFailed"), t));
    } finally {
      setAdding(false);
    }
  };

  const handleRemoveSource = (url: string) => {
    Modal.confirm({
      title: t("plugins.dsh.remove"),
      content: t("plugins.dsh.removeConfirm"),
      okText: t("common.confirm"),
      cancelText: t("plugins.dsh.cancel"),
      onOk: async () => {
        try {
          await pluginsApi.removeDshSource(url);
          await fetchMarket(true);
        } catch (err) {
          message.error(
            apiErrorMessage(err, t("plugins.dsh.removeSourceFailed"), t),
          );
        }
      },
    });
  };

  const versionFor = (row: DshMarketEntry): string =>
    selected[row.plugin_id] ||
    row.installed_version ||
    row.recommended_version ||
    row.versions[0] ||
    "";

  const recordOutcome = useCallback(
    (row: DshMarketEntry, result: DshInstallResult, action: "install" | "upgrade") => {
      const name = row.name || row.plugin_id;
      if (result.status.includes("dependency_failed")) {
        const dependency = result.dependency;
        setLoadOutcome({
          kind: "deps_failed",
          name,
          version: result.version,
          code: dependency?.code ?? "DSH_DEP_INSTALL_FAILED",
          reason: dependency?.message || result.runtime.reason,
          missing: dependency?.missing ?? [],
          cause: dependency?.cause ?? "unknown",
        });
        message.warning(t("plugins.dsh.dependencyFailed"));
      } else if (result.runtime.status === "visible") {
        setLoadOutcome({ kind: "installed", name, version: result.version });
        message.success(
          action === "upgrade"
            ? t("plugins.dsh.upgradeSuccess")
            : t("plugins.dsh.installSuccess"),
        );
      } else {
        setLoadOutcome({
          kind: "not_ready",
          name,
          version: result.version,
          code: result.runtime.error_code,
          reason: result.runtime.reason || result.runtime.notes.join("; "),
        });
        message.warning(t("plugins.dsh.installedNotReady"));
      }
      notifyPluginsChanged();
    },
    [t],
  );

  const recordLoadFailure = useCallback(
    (row: DshMarketEntry, err: unknown) => {
      const parsed = parseApiError(err);
      setLoadOutcome({
        kind: "failed",
        name: row.name || row.plugin_id,
        code: parsed?.code ?? null,
        reason: apiErrorMessage(err, t("plugins.installFailed"), t),
      });
      message.error(apiErrorMessage(err, t("plugins.installFailed"), t));
    },
    [t],
  );

  const handleInstall = async (row: DshMarketEntry, force = false) => {
    const version = force
      ? row.installed_version || versionFor(row)
      : versionFor(row);
    setBusyId(row.plugin_id);
    setLoadOutcome(null);
    setProgress(null);
    startProgressPolling(row.plugin_id);
    try {
      const result = await pluginsApi.installDsh(row.plugin_id, version, force);
      recordOutcome(row, result, "install");
      // The catalog snapshot is still valid after a local install; only the
      // runtime state changed, so reload the page instead of re-downloading.
      await fetchMarket();
      await loadStatus();
    } catch (err) {
      recordLoadFailure(row, err);
    } finally {
      stopProgressPolling();
      setBusyId(null);
    }
  };

  const handleUpgrade = async (row: DshMarketEntry) => {
    const version = versionFor(row);
    setBusyId(row.plugin_id);
    setLoadOutcome(null);
    setProgress(null);
    startProgressPolling(row.plugin_id);
    try {
      const result = await pluginsApi.upgradeDsh(row.plugin_id, version);
      recordOutcome(row, result, "upgrade");
      await fetchMarket();
      await loadStatus();
    } catch (err) {
      recordLoadFailure(row, err);
    } finally {
      stopProgressPolling();
      setBusyId(null);
    }
  };

  const handleUninstall = (row: DshMarketEntry) => {
    Modal.confirm({
      title: t("plugins.dsh.uninstall"),
      content: t("plugins.dsh.uninstallConfirm", {
        name: row.name || row.plugin_id,
        version: row.installed_version || "",
      }),
      okText: t("plugins.dsh.uninstall"),
      okButtonProps: { danger: true },
      cancelText: t("plugins.dsh.cancel"),
      onOk: async () => {
        setBusyId(row.plugin_id);
        try {
          const result = await pluginsApi.uninstallDsh(
            row.plugin_id,
            row.installed_version || undefined,
          );
          if (result.cleaned) {
            message.success(t("plugins.dsh.cleanupDone"));
          } else {
            message.info(
              t("plugins.dsh.cleanupPartial", {
                version: result.version,
                versions: result.remaining_versions.join(", "),
              }),
            );
          }
          notifyPluginsChanged();
          await fetchMarket();
          await loadStatus();
        } catch (err) {
          message.error(apiErrorMessage(err, t("plugins.installFailed"), t));
        } finally {
          setBusyId(null);
        }
      },
    });
  };

  const sourceOptions = useMemo(
    () =>
      (view?.sources ?? []).map((source) => ({
        url: source.url,
        ok: source.status === "ok",
      })),
    [view],
  );

  return (
    <section className={styles.dshSection}>
      <div className={styles.dshHeader}>
        <div>
          <h3 className={styles.dshTitle}>{t("plugins.dsh.title")}</h3>
          <p className={styles.dshSubtitle}>{t("plugins.dsh.subtitle")}</p>
        </div>
        <div className={styles.dshHeaderActions}>
          {sourceOptions.length > 0 ? (
            <span className={styles.dshSourceCount}>
              {t("plugins.dsh.sourceCount", { count: sourceOptions.length })}
            </span>
          ) : null}
          <Button
            size="small"
            icon={<RefreshCw size={14} />}
            loading={refreshing}
            onClick={() => void fetchMarket(true)}
          >
            {t("plugins.dsh.refresh")}
          </Button>
        </div>
      </div>

      {status ? (
        <div className={styles.dshStatusBar}>
          <Tag
            bordered={false}
            color={status.runtime.ready ? "success" : "default"}
          >
            {status.runtime.ready
              ? t("plugins.dsh.runtimeReady")
              : t("plugins.dsh.runtimeNotReady")}
          </Tag>
          {status.runtime.reason_code ? (
            <span className={styles.dshStatusReason} title={status.runtime.reason}>
              {status.runtime.reason_code} · {status.runtime.reason}
            </span>
          ) : null}
          {status.stages.some((stage) => stage.effective) ? (
            <span className={styles.dshStatusMeta}>
              {t("plugins.dsh.stagesLabel")}:{" "}
              {status.stages
                .filter((stage) => stage.effective)
                .map((stage) => stage.name)
                .join(" · ")}
            </span>
          ) : null}
          {status.runtime.node.version ? (
            <span className={styles.dshStatusMeta}>
              Node {status.runtime.node.version}
            </span>
          ) : null}
          <span className={styles.dshStatusSpacer} />
          <Button
            size="small"
            type="text"
            loading={probing}
            onClick={() => void loadStatus(true)}
          >
            {t("plugins.dsh.probe")}
          </Button>
        </div>
      ) : null}

      {busyId && progress ? (
        <div className={styles.dshProgress}>
          <Progress
            percent={Math.round((progress.progress ?? 0) * 100)}
            status={progress.status === "failed" ? "exception" : "active"}
            size="small"
          />
          <div className={styles.dshProgressMeta}>
            <span>
              {t(`plugins.dsh.phase.${progress.phase}`, {
                defaultValue: progress.message,
              })}
            </span>
            {progress.detail ? (
              <span className={styles.dshProgressDetail} title={progress.detail}>
                {progress.detail}
              </span>
            ) : null}
          </div>
        </div>
      ) : null}

      {status?.last_failure ? (
        <Alert
          type="warning"
          showIcon
          className={styles.dshError}
          message={`${t("plugins.dsh.lastFailure")} · ${
            status.last_failure.kind === "execute"
              ? t("plugins.dsh.failureExecute")
              : t("plugins.dsh.failureLoad")
          } · ${status.last_failure.code}`}
          description={`${status.last_failure.plugin_id} · ${status.last_failure.reason}`}
        />
      ) : null}

      <div className={styles.dshAddRow}>
        <Input
          allowClear
          value={sourceDraft}
          placeholder={t("plugins.dsh.sourcePlaceholder")}
          onChange={(event) => setSourceDraft(event.target.value)}
          onPressEnter={() => void handleAddSource()}
          className={styles.dshSourceInput}
        />
        <Button
          type="primary"
          icon={<Plus size={14} />}
          loading={adding}
          disabled={!sourceDraft.trim()}
          onClick={() => void handleAddSource()}
        >
          {t("plugins.dsh.addSource")}
        </Button>
      </div>

      {loading && !view ? null : loadFailed && !view ? (
        <Alert
          type="error"
          showIcon
          message={t("plugins.dsh.loadFailed")}
          action={
            <Button size="small" onClick={() => void fetchMarket(true)}>
              {t("common.retry")}
            </Button>
          }
        />
      ) : (view?.sources.length ?? 0) === 0 ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={
            <div className={styles.dshEmpty}>
              <strong>{t("plugins.dsh.emptyTitle")}</strong>
              <p>{t("plugins.dsh.emptyHint")}</p>
              <code className={styles.dshFormatHint}>
                {t("plugins.dsh.formatHint")}
              </code>
            </div>
          }
        />
      ) : (
        <>
          <div className={styles.dshSourceList}>
            {(view?.sources ?? []).map((source) => (
              <div key={source.url} className={styles.dshSourceRow}>
                <div className={styles.dshSourceMeta}>
                  <span className={styles.dshSourceUrl} title={source.url}>
                    {source.url}
                  </span>
                  <Tag bordered={false} color={sourceTagColor(source.status)}>
                    {source.status === "ok"
                      ? t("plugins.dsh.sourceOk")
                      : source.status === "stale"
                        ? t("plugins.dsh.sourceStale")
                        : source.status === "slow"
                          ? t("plugins.dsh.sourceSlow")
                          : source.status === "error"
                            ? t("plugins.dsh.sourceError")
                            : t("plugins.dsh.sourceUnknown")}
                  </Tag>
                  {source.builtin ? (
                    <Tag bordered={false}>{t("plugins.dsh.builtin")}</Tag>
                  ) : null}
                  <span className={styles.dshSourceCount}>
                    {t("plugins.dsh.entryCount", {
                      count: source.entry_count,
                    })}
                  </span>
                  {source.fetched_at ? (
                    <span className={styles.dshFetchedAt}>
                      {source.fetched_at}
                    </span>
                  ) : null}
                </div>
                <Button
                  size="small"
                  danger
                  type="text"
                  icon={<Trash2 size={14} />}
                  aria-label={t("plugins.dsh.remove")}
                  onClick={() => handleRemoveSource(source.url)}
                />
              </div>
            ))}
          </div>

          {(view?.sources ?? [])
            .filter((source) => source.status === "slow")
            .map((source) => (
              <Alert
                key={`slow-${source.url}`}
                type="info"
                showIcon
                className={styles.dshError}
                message={t("plugins.dsh.sourceSlowTitle")}
                description={`${source.url} · ${
                  source.error?.code ?? "PLUGIN_SOURCE_SLOW"
                }${source.budget_seconds ? ` · ${source.budget_seconds}s` : ""}`}
              />
            ))}

          {(view?.sources ?? [])
            .filter((source) => source.status === "stale")
            .map((source) => (
              <Alert
                key={`stale-${source.url}`}
                type="warning"
                showIcon
                className={styles.dshError}
                message={t("plugins.dsh.sourceStaleTitle", {
                  count: source.entry_count,
                })}
                description={`${source.url} · ${
                  source.error?.code ?? "PLUGIN_SOURCE_SLOW"
                }${source.budget_seconds ? ` · ${source.budget_seconds}s` : ""}`}
              />
            ))}

          {(view?.sources ?? [])
            .filter((source) => source.status === "error" && source.error)
            .map((source) => (
              <Alert
                key={`err-${source.url}`}
                type="error"
                showIcon
                className={styles.dshError}
                message={`${source.error?.code}: ${source.error?.message}`}
                description={
                  source.error?.details?.path
                    ? `path: ${String(source.error.details.path)}`
                    : source.url
                }
              />
            ))}

          <div className={styles.dshToolbar}>
            <Input.Search
              allowClear
              value={queryDraft}
              placeholder={t("plugins.dsh.searchPlaceholder")}
              className={styles.dshSearch}
              onChange={(event) => setQueryDraft(event.target.value)}
              onSearch={(value) => {
                setQuery(value.trim());
                setPage(1);
              }}
            />
            <span className={styles.dshSourceCount}>
              {t("plugins.dsh.resultCount", { count: view?.total ?? 0 })}
            </span>
          </div>

          {loadOutcome ? (
            <Alert
              type={
                loadOutcome.kind === "installed"
                  ? "success"
                  : loadOutcome.kind === "not_ready"
                    ? "warning"
                    : "error"
              }
              showIcon
              closable
              onClose={() => setLoadOutcome(null)}
              className={styles.dshError}
              message={
                loadOutcome.kind === "installed"
                  ? t("plugins.dsh.loadInstalled", {
                      name: loadOutcome.name,
                      version: loadOutcome.version,
                    })
                  : `${t(
                      loadOutcome.kind === "deps_failed"
                        ? "plugins.dsh.loadDepsFailed"
                        : loadOutcome.kind === "not_ready"
                          ? "plugins.dsh.loadNotReady"
                          : "plugins.dsh.loadFailed",
                    )} · ${loadOutcome.code ?? "UNKNOWN"}`
              }
              description={
                loadOutcome.kind === "installed"
                  ? undefined
                  : loadOutcome.kind === "deps_failed"
                    ? `${loadOutcome.name} · ${t(
                        `plugins.dsh.depCause.${loadOutcome.cause ?? "unknown"}`,
                      )}${
                        loadOutcome.missing.length > 0
                          ? ` · ${t("plugins.dsh.missingPackages", {
                              packages: loadOutcome.missing.join(", "),
                            })}`
                          : ""
                      } · ${loadOutcome.reason}`
                    : `${loadOutcome.name} · ${loadOutcome.reason}`
              }
            />
          ) : null}

          {(view?.entries.length ?? 0) === 0 ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={
                view?.query
                  ? t("plugins.dsh.searchEmpty")
                  : t("plugins.dsh.emptyTitle")
              }
            />
          ) : (
            <div className={styles.cardGrid}>
              {(view?.entries ?? []).map((row) => {
                const installed = row.installed;
                const selectedVersion = versionFor(row);
                const canUpgrade =
                  installed && selectedVersion !== row.installed_version;
                const runtime = row.runtime;
                const showRuntimeWarning =
                  installed && runtime.status !== "visible";
                return (
                  <article
                    key={row.plugin_id}
                    className={cx(styles.card, installed && styles.cardInstalled)}
                  >
                    <div className={styles.cardBody}>
                      <div className={styles.cardTop}>
                        <PluginIconView
                          icon={row.icon}
                          size={32}
                          className={styles.cardIcon}
                          crossOrigin="anonymous"
                          fadeIn
                        />
                        <div className={styles.cardTitleCol}>
                          <h3 className={styles.cardName}>
                            {row.name || row.plugin_id}
                          </h3>
                          <div className={styles.dshTagRow}>
                            <Tag bordered={false}>DSH</Tag>
                            <Tag
                              bordered={false}
                              title={runtime.surface_reason || t("plugins.uiNoSurfaceHint")}
                            >
                              {t("plugins.uiNoSurface")}
                            </Tag>
                            {installed ? (
                              <Tag
                                bordered={false}
                                color={runtimeTagColor(runtime.status)}
                              >
                                {runtime.status === "visible"
                                  ? t("plugins.dsh.runtimeVisible")
                                  : runtime.status === "broken"
                                    ? t("plugins.dsh.runtimeBroken")
                                    : t("plugins.dsh.runtimeNotVisible")}
                              </Tag>
                            ) : (
                              <Tag bordered={false}>
                                {t("plugins.dsh.notInstalled")}
                              </Tag>
                            )}
                            {row.update_available ? (
                              <Tag bordered={false} color="processing">
                                {t("plugins.marketUpdateAvailable")}
                              </Tag>
                            ) : null}
                          </div>
                        </div>
                      </div>
                      <p className={styles.cardDesc}>
                        {row.description || t("plugins.dsh.noDescription")}
                      </p>

                      {row.source_url ? (
                        <div
                          className={styles.dshCardSource}
                          title={row.source_url}
                        >
                          {`${t("plugins.dsh.sourceLabel")}: ${row.source_url}`}
                        </div>
                      ) : null}

                      {showRuntimeWarning ? (
                        <Alert
                          type="warning"
                          showIcon
                          className={styles.dshCardAlert}
                          message={
                            runtime.error_code
                              ? t("plugins.dsh.errorCode", {
                                  code: runtime.error_code,
                                })
                              : t("plugins.dsh.runtimeNotVisible")
                          }
                          description={runtime.reason || undefined}
                        />
                      ) : null}

                      <Select
                        size="small"
                        className={styles.dshVersionSelect}
                        value={selectedVersion || undefined}
                        placeholder={t("plugins.dsh.versionPlaceholder")}
                        options={row.versions.map((version) => ({
                          value: version,
                          label:
                            version === row.recommended_version
                              ? `${version} · ${t("plugins.dsh.recommended")}`
                              : version,
                        }))}
                        onChange={(value) =>
                          setSelected((prev) => ({
                            ...prev,
                            [row.plugin_id]: value,
                          }))
                        }
                      />

                      {installed ? (
                        <div className={styles.dshInstalledLine}>
                          {t("plugins.dsh.installed", {
                            version: row.installed_version || "",
                          })}
                        </div>
                      ) : null}
                    </div>

                    <div className={styles.cardFooter}>
                      <span className={styles.tableMono}>{row.plugin_id}</span>
                      <span className={styles.cardFooterSpacer} />
                      {installed ? (
                        <>
                          {runtime.status !== "visible" ? (
                            <Button
                              size="small"
                              icon={<Wrench size={14} />}
                              loading={busyId === row.plugin_id}
                              onClick={() => void handleInstall(row, true)}
                            >
                              {t("plugins.dsh.repair")}
                            </Button>
                          ) : null}
                          <Button
                            size="small"
                            danger
                            onClick={() => handleUninstall(row)}
                            loading={busyId === row.plugin_id}
                          >
                            {t("plugins.dsh.uninstall")}
                          </Button>
                          <Button
                            type="primary"
                            size="small"
                            icon={<UploadCloud size={14} />}
                            disabled={!canUpgrade}
                            loading={busyId === row.plugin_id}
                            onClick={() => void handleUpgrade(row)}
                          >
                            {t("plugins.dsh.upgrade")}
                          </Button>
                        </>
                      ) : (
                        <Button
                          type="primary"
                          size="small"
                          icon={<Download size={14} />}
                          loading={busyId === row.plugin_id}
                          onClick={() => void handleInstall(row)}
                        >
                          {t("plugins.dsh.loadNow")}
                        </Button>
                      )}
                    </div>
                  </article>
                );
              })}
            </div>
          )}

          {(view?.total_pages ?? 0) > 1 ? (
            <div className={styles.dshPager}>
              <Pagination
                size="small"
                current={view?.page ?? 1}
                pageSize={view?.page_size ?? pageSize}
                total={view?.total ?? 0}
                showSizeChanger
                pageSizeOptions={PAGE_SIZE_OPTIONS}
                onChange={(nextPage, nextSize) => {
                  if (nextSize !== pageSize) {
                    setPageSize(nextSize);
                    setPage(1);
                    return;
                  }
                  setPage(nextPage);
                }}
              />
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}
