import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { pluginsApi, type InstalledPlugin } from "../../api/modules/plugins";
import { providerApi } from "../../api/modules/provider";
import { securityApi, type SecurityPolicy } from "../../api/modules/security";
import {
  octopSettingsApi,
  type OctopTimezoneSettings,
  type OctopUploadSettings,
  type SearchSourceSettings,
} from "../../api/modules/settings";
import type { ResolvedModel } from "../../api/types";
import { useAgent } from "../../context/AgentContext";
import { MobileChip } from "../components/MobileChip";
import { MobileEmpty } from "../components/MobileEmpty";
import { MobileListRow } from "../components/MobileListRow";
import { MobilePage } from "../components/MobilePage";
import { MobileSkeleton } from "../components/MobileSkeleton";

function useSectionTitles() {
  const { t } = useTranslation();
  return useMemo<Record<string, string>>(
    () => ({
      models: t("mobile.admin.groupModels", "模型"),
      security: t("mobile.admin.groupSecurity", "安全"),
      advanced: t("mobile.admin.groupAdvanced", "高级"),
      plugins: t("mobile.admin.groupPlugins", "插件"),
    }),
    [t],
  );
}

function Retry({ onRetry, title }: { onRetry: () => void; title: string }) {
  const { t } = useTranslation();
  return (
    <MobileEmpty
      icon="alert"
      title={title}
      description={t("mobile.common.loadFailedDesc", "网络或后端暂时不可用。")}
      action={
        <button
          type="button"
          className="m-btn m-btn--primary"
          onClick={onRetry}
        >
          {t("common.retry", "重试")}
        </button>
      }
    />
  );
}

function ModelsSection() {
  const { t } = useTranslation();
  const { activeAgentId } = useAgent();
  const [active, setActive] = useState<{
    provider_name: string;
    model: string;
  } | null>(null);
  const [models, setModels] = useState<ResolvedModel[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    const [current, list] = await Promise.allSettled([
      providerApi.getActiveModel(activeAgentId),
      providerApi.listResolvedModels(activeAgentId),
    ]);
    setActive(current.status === "fulfilled" ? current.value : null);
    setModels(list.status === "fulfilled" ? list.value : []);
    setFailed(current.status === "rejected" && list.status === "rejected");
    setLoading(false);
  }, [activeAgentId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <MobileSkeleton rows={3} />;
  if (failed)
    return (
      <Retry
        onRetry={() => void load()}
        title={t("mobile.admin.modelsLoadFailed", "模型信息加载失败")}
      />
    );

  return (
    <>
      {active ? (
        <div className="m-card m-card--accent m-mb8">
          <div className="m-card-desc">
            {t("mobile.admin.currentModel", "当前模型")}
          </div>
          <div className="m-card-title">{active.model}</div>
          <div className="m-card-desc">{active.provider_name}</div>
        </div>
      ) : null}

      {models.length === 0 ? (
        <MobileEmpty
          icon="bot"
          title={t("mobile.admin.noModelsTitle", "还没有可用模型")}
          description={t(
            "mobile.admin.noModelsDesc",
            "请先在桌面端配置模型供应商。",
          )}
        />
      ) : (
        <div className="m-group">
          {models.map((model) => (
            <MobileListRow
              key={`${model.provider_id}-${model.model}`}
              title={model.name || model.model}
              subtitle={model.provider_name}
              meta={
                model.context_window
                  ? `${Math.round(model.context_window / 1000)}K`
                  : undefined
              }
            />
          ))}
        </div>
      )}

      <div className="m-field-hint" style={{ marginTop: 12 }}>
        {t(
          "mobile.admin.modelsHint",
          "切换或新增模型请前往桌面端「管理 → 模型」。",
        )}
      </div>
    </>
  );
}

function SecuritySection() {
  const { t } = useTranslation();
  const [policy, setPolicy] = useState<SecurityPolicy | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  const piiStrategy = useMemo<Record<string, string>>(
    () => ({
      block: t("mobile.admin.piiBlock", "拦截"),
      redact: t("mobile.admin.piiRedact", "脱敏"),
      mask: t("mobile.admin.piiMask", "掩码"),
      hash: t("mobile.admin.piiHash", "哈希"),
    }),
    [t],
  );
  const scanMode = useMemo<Record<string, string>>(
    () => ({
      off: t("mobile.admin.scanOff", "关闭"),
      warn: t("mobile.admin.scanWarn", "仅警告"),
      block: t("mobile.admin.scanBlock", "拦截"),
    }),
    [t],
  );
  const guardMode = useMemo<Record<string, string>>(
    () => ({
      block: t("mobile.admin.scanBlock", "拦截"),
      warn: t("mobile.admin.scanWarn", "仅警告"),
      require_approval: t("mobile.admin.guardApproval", "需要人工确认"),
    }),
    [t],
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setPolicy(await securityApi.getPolicy());
      setFailed(false);
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <MobileSkeleton rows={3} />;
  if (failed || !policy) {
    return (
      <Retry
        onRetry={() => void load()}
        title={t("mobile.admin.securityLoadFailed", "安全策略加载失败")}
      />
    );
  }

  const onLabel = t("mobile.admin.on", "开启");
  const offLabel = t("mobile.admin.off", "关闭");

  return (
    <>
      <div className="m-group">
        <MobileListRow
          icon="shield"
          title={t("mobile.admin.hitl", "人工确认")}
          subtitle={t("mobile.admin.hitlSub", "危险操作执行前需要你确认")}
          right={
            <MobileChip tone={policy.hitl.enabled ? "ok" : "default"}>
              {policy.hitl.enabled ? onLabel : offLabel}
            </MobileChip>
          }
        />
        <MobileListRow
          icon="shield"
          title={t("mobile.admin.fsLimit", "文件系统限制")}
          subtitle={
            policy.filesystem.enabled
              ? t("mobile.admin.fsRules", "{{n}} 条规则", {
                  n: policy.filesystem.rules.length,
                })
              : t("mobile.admin.fsDisabled", "未启用")
          }
          right={
            <MobileChip tone={policy.filesystem.enabled ? "ok" : "default"}>
              {policy.filesystem.enabled ? onLabel : offLabel}
            </MobileChip>
          }
        />
        <MobileListRow
          icon="shield"
          title={t("mobile.admin.pii", "隐私信息防护")}
          subtitle={t("mobile.admin.piiSub", "检测并处理敏感内容")}
          right={
            <MobileChip tone={policy.pii.enabled ? "ok" : "default"}>
              {policy.pii.enabled
                ? piiStrategy[policy.pii.strategy] ?? policy.pii.strategy
                : offLabel}
            </MobileChip>
          }
        />
        <MobileListRow
          icon="shield"
          title={t("mobile.admin.skillScan", "技能扫描")}
          subtitle={t("mobile.admin.skillScanSub", "安装技能前检查风险")}
          meta={scanMode[policy.skill_scan.mode] ?? policy.skill_scan.mode}
        />
        <MobileListRow
          icon="shield"
          title={t("mobile.admin.toolGuard", "工具守卫")}
          subtitle={t("mobile.admin.toolGuardSub", "拦截高危工具调用")}
          meta={
            policy.tool_guard.enabled
              ? guardMode[policy.tool_guard.mode] ?? policy.tool_guard.mode
              : offLabel
          }
        />
      </div>

      <div className="m-field-hint" style={{ marginTop: 12 }}>
        {t(
          "mobile.admin.securityHint",
          "修改安全策略请前往桌面端「管理 → 安全」。",
        )}
      </div>
    </>
  );
}

function AdvancedSection() {
  const { t } = useTranslation();
  const [timezone, setTimezone] = useState<OctopTimezoneSettings | null>(null);
  const [upload, setUpload] = useState<OctopUploadSettings | null>(null);
  const [search, setSearch] = useState<SearchSourceSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  const searchSource = useMemo<Record<string, string>>(
    () => ({
      happysearch: t("mobile.admin.searchBuiltin", "内置搜索"),
      searchfree: t("mobile.admin.searchFree", "免费搜索"),
      both: t("mobile.admin.searchBoth", "两者兼用"),
    }),
    [t],
  );

  const load = useCallback(async () => {
    setLoading(true);
    const [tz, up, src] = await Promise.allSettled([
      octopSettingsApi.timezone(),
      octopSettingsApi.upload(),
      octopSettingsApi.searchSource(),
    ]);
    setTimezone(tz.status === "fulfilled" ? tz.value : null);
    setUpload(up.status === "fulfilled" ? up.value : null);
    setSearch(src.status === "fulfilled" ? src.value : null);
    setFailed(
      tz.status === "rejected" &&
        up.status === "rejected" &&
        src.status === "rejected",
    );
    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <MobileSkeleton rows={3} />;
  if (failed)
    return (
      <Retry
        onRetry={() => void load()}
        title={t("mobile.admin.advancedLoadFailed", "高级设置加载失败")}
      />
    );

  return (
    <>
      <div className="m-group">
        <MobileListRow
          icon="clock"
          title={t("mobile.admin.timezone", "服务器时区")}
          subtitle={t("mobile.admin.timezoneSub", "时间显示与定时任务按此计算")}
          meta={timezone?.timezone ?? "—"}
        />
        <MobileListRow
          icon="plug"
          title={t("mobile.admin.uploadLimit", "单文件上传上限")}
          meta={upload ? `${upload.max_upload_mb} MB` : "—"}
        />
        <MobileListRow
          icon="search"
          title={t("mobile.admin.searchSource", "搜索来源")}
          meta={
            search ? searchSource[search.effective] ?? search.effective : "—"
          }
        />
      </div>

      <div className="m-field-hint" style={{ marginTop: 12 }}>
        {t(
          "mobile.admin.advancedHint",
          "这些选项需要重启或修改配置文件，请前往桌面端「管理 → 高级」。",
        )}
      </div>
    </>
  );
}

function PluginsSection() {
  const { t } = useTranslation();
  const [plugins, setPlugins] = useState<InstalledPlugin[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setPlugins(await pluginsApi.list());
      setFailed(false);
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <MobileSkeleton rows={3} />;
  if (failed)
    return (
      <Retry
        onRetry={() => void load()}
        title={t("mobile.admin.pluginsLoadFailed", "插件列表加载失败")}
      />
    );
  if (plugins.length === 0) {
    return (
      <MobileEmpty
        icon="plug"
        title={t("mobile.admin.noPluginsTitle", "还没有安装插件")}
        description={t(
          "mobile.admin.noPluginsDesc",
          "请前往桌面端「管理 → 插件」安装。",
        )}
      />
    );
  }

  return (
    <>
      <div className="m-group">
        {plugins.map((plugin) => (
          <MobileListRow
            key={plugin.id}
            icon="plug"
            title={plugin.name || plugin.id}
            subtitle={plugin.description || plugin.kind || undefined}
            meta={plugin.version ?? undefined}
            right={
              <MobileChip tone={plugin.enabled === false ? "default" : "ok"}>
                {plugin.enabled === false
                  ? t("mobile.admin.pluginDisabled", "停用")
                  : t("mobile.admin.pluginEnabled", "启用")}
              </MobileChip>
            }
          />
        ))}
      </div>

      <div className="m-field-hint" style={{ marginTop: 12 }}>
        {t(
          "mobile.admin.pluginsHint",
          "安装、升级或配置插件请前往桌面端「管理 → 插件」。",
        )}
      </div>
    </>
  );
}

function AdminOverview() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { activeAgentId } = useAgent();
  const [model, setModel] = useState<string | null>(null);
  const [hitl, setHitl] = useState<boolean | null>(null);
  const [timezone, setTimezone] = useState<string | null>(null);
  const [pluginCount, setPluginCount] = useState<number | null>(null);

  useEffect(() => {
    let alive = true;
    const [activeModel, policy, tz, plugins] = [
      providerApi.getActiveModel(activeAgentId),
      securityApi.getPolicy(),
      octopSettingsApi.timezone(),
      pluginsApi.list(),
    ];
    void Promise.allSettled([activeModel, policy, tz, plugins]).then(
      (results) => {
        if (!alive) return;
        const [modelResult, policyResult, tzResult, pluginResult] = results;
        if (modelResult.status === "fulfilled") {
          const name = modelResult.value.model?.trim();
          const provider = modelResult.value.provider_name?.trim();
          setModel(
            name && provider
              ? `${name} · ${provider}`
              : name || provider || null,
          );
        } else {
          setModel(null);
        }
        setHitl(
          policyResult.status === "fulfilled"
            ? policyResult.value.hitl.enabled
            : null,
        );
        setTimezone(
          tzResult.status === "fulfilled" ? tzResult.value.timezone : null,
        );
        setPluginCount(
          pluginResult.status === "fulfilled"
            ? pluginResult.value.length
            : null,
        );
      },
    );
    return () => {
      alive = false;
    };
  }, [activeAgentId]);

  return (
    <MobilePage title={t("mobile.admin.title", "管理")} back>
      <div className="m-group">
        <MobileListRow
          icon="bot"
          title={t("mobile.admin.groupModels", "模型")}
          subtitle={t("mobile.admin.groupModelsSub", "当前模型与可用模型")}
          meta={model ?? "—"}
          chevron
          onClick={() => navigate("/m/admin/models")}
        />
        <MobileListRow
          icon="shield"
          title={t("mobile.admin.groupSecurity", "安全")}
          subtitle={t(
            "mobile.admin.groupSecuritySub",
            "人工确认、隐私与工具守卫",
          )}
          meta={
            hitl === null
              ? "—"
              : hitl
              ? t("mobile.admin.hitlOn", "人工确认开启")
              : t("mobile.admin.hitlOff", "人工确认关闭")
          }
          chevron
          onClick={() => navigate("/m/admin/security")}
        />
        <MobileListRow
          icon="gear"
          title={t("mobile.admin.groupAdvanced", "高级")}
          subtitle={t("mobile.admin.groupAdvancedSub", "时区、上传与搜索来源")}
          meta={timezone ?? "—"}
          chevron
          onClick={() => navigate("/m/admin/advanced")}
        />
        <MobileListRow
          icon="plug"
          title={t("mobile.admin.groupPlugins", "插件")}
          subtitle={t("mobile.admin.groupPluginsSub", "已安装的插件与启用状态")}
          meta={
            pluginCount === null
              ? "—"
              : t("mobile.admin.pluginCount", "{{n}} 个", { n: pluginCount })
          }
          chevron
          onClick={() => navigate("/m/admin/plugins")}
        />
      </div>

      <div className="m-field-hint" style={{ marginTop: 12 }}>
        {t(
          "mobile.admin.footer",
          "需要复杂编辑时，请使用桌面端管理页，改动会实时同步到手机端。",
        )}
      </div>
    </MobilePage>
  );
}

export function AdminPage() {
  const { t } = useTranslation();
  const { section } = useParams<{ section?: string }>();
  const sectionTitles = useSectionTitles();

  if (!section) return <AdminOverview />;
  if (!sectionTitles[section]) {
    return (
      <MobilePage title={t("mobile.admin.title", "管理")} back>
        <MobileEmpty
          icon="alert"
          title={t("mobile.admin.sectionMissingTitle", "页面不存在")}
          description={t(
            "mobile.admin.sectionMissingDesc",
            "这个管理分区还没有手机端页面。",
          )}
        />
      </MobilePage>
    );
  }

  return (
    <MobilePage title={sectionTitles[section]} back>
      {section === "models" ? <ModelsSection /> : null}
      {section === "security" ? <SecuritySection /> : null}
      {section === "advanced" ? <AdvancedSection /> : null}
      {section === "plugins" ? <PluginsSection /> : null}
    </MobilePage>
  );
}
