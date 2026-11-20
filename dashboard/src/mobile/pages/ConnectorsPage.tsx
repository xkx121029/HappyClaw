import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  connectorsApi,
  type ConnectorInstance,
} from "../../api/modules/connectors";
import { useAgent } from "../../context/AgentContext";
import { MobileChip } from "../components/MobileChip";
import { MobileEmpty } from "../components/MobileEmpty";
import { MobileIcon } from "../components/MobileIcon";
import { MobilePage } from "../components/MobilePage";
import { MobileSheet } from "../components/MobileSheet";
import { MobileSkeleton } from "../components/MobileSkeleton";
import { MobileSwitch } from "../components/MobileSwitch";
import { showMobileToast } from "../components/MobileToast";

type ChipTone = "ok" | "warn" | "danger" | "default";

function statusTone(status: string): ChipTone {
  const value = status.toLowerCase();
  if (value === "ready" || value === "connected" || value === "ok") return "ok";
  if (value.includes("auth") || value.includes("pending")) return "warn";
  if (value.includes("error") || value.includes("fail")) return "danger";
  return "default";
}

/** Status key → label; the raw status is shown when nothing maps. */
function statusKey(status: string): string | null {
  const value = status.toLowerCase();
  if (value === "ready" || value === "connected" || value === "ok")
    return "ready";
  if (value.includes("auth")) return "auth";
  if (value.includes("pending")) return "pending";
  if (value.includes("error") || value.includes("fail")) return "error";
  return null;
}

export function ConnectorsPage() {
  const { t } = useTranslation();
  const { activeAgentId, activeAgent } = useAgent();
  const [items, setItems] = useState<ConnectorInstance[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [detail, setDetail] = useState<ConnectorInstance | null>(null);
  const [testing, setTesting] = useState(false);

  const statusLabels = useMemo<Record<string, string>>(
    () => ({
      ready: t("mobile.connectors.statusReady", "可用"),
      auth: t("mobile.connectors.statusAuth", "需要授权"),
      pending: t("mobile.connectors.statusPending", "配置中"),
      error: t("mobile.connectors.statusError", "异常"),
      unknown: t("mobile.connectors.statusUnknown", "未知"),
    }),
    [t],
  );

  const labelFor = useCallback(
    (status: string): string => {
      const key = statusKey(status);
      return key ? statusLabels[key] : status || statusLabels.unknown;
    },
    [statusLabels],
  );

  const load = useCallback(async () => {
    try {
      setItems(await connectorsApi.listInstances(activeAgentId));
      setFailed(false);
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, [activeAgentId]);

  useEffect(() => {
    setLoading(true);
    void load();
  }, [load]);

  const toggleDefault = async (item: ConnectorInstance) => {
    const next = !item.default_open;
    setItems((prev) =>
      prev.map((row) =>
        row.instance_id === item.instance_id
          ? { ...row, default_open: next }
          : row,
      ),
    );
    if (detail?.instance_id === item.instance_id) {
      setDetail({ ...detail, default_open: next });
    }
    try {
      await connectorsApi.patchInstance(item.instance_id, {
        default_open: next,
      });
    } catch {
      setItems((prev) =>
        prev.map((row) =>
          row.instance_id === item.instance_id
            ? { ...row, default_open: item.default_open }
            : row,
        ),
      );
      showMobileToast(t("mobile.connectors.toggleFailed", "更新默认开启失败"));
    }
  };

  const testConnection = async (item: ConnectorInstance) => {
    if (testing) return;
    setTesting(true);
    try {
      const result = await connectorsApi.testInstance(item.instance_id);
      if (result.ok) {
        showMobileToast(
          result.tool_count
            ? t("mobile.connectors.testOkWithTools", {
                n: result.tool_count,
                defaultValue: "连接正常，发现 {{n}} 个工具",
              })
            : t("mobile.connectors.testOk", "连接正常"),
        );
      } else {
        showMobileToast(
          result.error || t("mobile.connectors.testFailed", "连接失败"),
        );
      }
      void load();
    } catch {
      showMobileToast(t("mobile.connectors.testRequestFailed", "测试连接失败"));
    } finally {
      setTesting(false);
    }
  };

  return (
    <MobilePage
      title={t("mobile.nav.connectors", "连接器")}
      back
      subtitle={activeAgent?.name}
    >
      {loading ? (
        <MobileSkeleton rows={4} />
      ) : failed ? (
        <MobileEmpty
          icon="alert"
          title={t("mobile.connectors.loadFailedTitle", "连接器加载失败")}
          action={
            <button
              type="button"
              className="m-btn m-btn--primary"
              onClick={() => void load()}
            >
              {t("common.retry", "重试")}
            </button>
          }
        />
      ) : items.length === 0 ? (
        <MobileEmpty
          icon="plug"
          title={t("mobile.connectors.emptyTitle", "还没有连接器")}
          description={t(
            "mobile.connectors.emptyDesc",
            "连接器在桌面端安装和授权，这里可以查看状态、测试连接和设置默认开启。",
          )}
        />
      ) : (
        <div className="m-stack">
          {items.map((item) => (
            <button
              type="button"
              key={item.instance_id}
              className="m-card is-tap"
              style={{ textAlign: "left" }}
              onClick={() => setDetail(item)}
            >
              <div className="m-spread">
                <div className="m-rowflex m-grow">
                  <span className="m-row-icon">
                    <MobileIcon name="plug" size={18} />
                  </span>
                  <span className="m-grow">
                    <span
                      className="m-card-title m-truncate"
                      style={{ display: "block" }}
                    >
                      {item.display_name}
                    </span>
                    <span className="m-card-desc m-clamp2">
                      {item.description || item.kind}
                    </span>
                  </span>
                </div>
                <MobileChip tone={statusTone(item.status)}>
                  {labelFor(item.status)}
                </MobileChip>
              </div>
              <div
                className="m-rowflex m-wrap"
                style={{ marginTop: 10, gap: 6 }}
              >
                <MobileChip>{item.kind}</MobileChip>
                {item.default_open ? (
                  <MobileChip tone="accent">
                    {t("mobile.connectors.defaultOn", "默认开启")}
                  </MobileChip>
                ) : null}
                {item.shared ? (
                  <MobileChip>
                    {t("mobile.knowledge.shared", "共享")}
                  </MobileChip>
                ) : null}
                {!item.has_credentials ? (
                  <MobileChip tone="warn">
                    {t("mobile.connectors.missingCredentials", "缺少凭据")}
                  </MobileChip>
                ) : null}
              </div>
            </button>
          ))}
        </div>
      )}

      <MobileSheet
        open={Boolean(detail)}
        title={detail?.display_name}
        onClose={() => setDetail(null)}
      >
        {detail ? (
          <div className="m-stack">
            <div className="m-group">
              <div className="m-field">
                <div className="m-field-main">
                  <div className="m-field-label">
                    {t("mobile.connectors.fieldStatus", "状态")}
                  </div>
                  <div className="m-field-hint">{detail.mcp_server_name}</div>
                </div>
                <MobileChip tone={statusTone(detail.status)}>
                  {labelFor(detail.status)}
                </MobileChip>
              </div>
              <div className="m-field">
                <div className="m-field-main">
                  <div className="m-field-label">
                    {t("mobile.connectors.fieldDefaultOpen", "默认开启")}
                  </div>
                  <div className="m-field-hint">
                    {t(
                      "mobile.connectors.fieldDefaultOpenHint",
                      "新对话自动带上这个连接器",
                    )}
                  </div>
                </div>
                <MobileSwitch
                  checked={Boolean(detail.default_open)}
                  onChange={() => void toggleDefault(detail)}
                  label={t("mobile.connectors.fieldDefaultOpen", "默认开启")}
                />
              </div>
              <div className="m-field">
                <div className="m-field-main">
                  <div className="m-field-label">
                    {t("mobile.connectors.fieldKind", "类型")}
                  </div>
                  <div className="m-field-hint">{detail.kind}</div>
                </div>
              </div>
              {detail.owner_display_name || detail.owner_username ? (
                <div className="m-field">
                  <div className="m-field-main">
                    <div className="m-field-label">
                      {t("mobile.connectors.fieldOwner", "所有者")}
                    </div>
                    <div className="m-field-hint">
                      {detail.owner_display_name || detail.owner_username}
                    </div>
                  </div>
                </div>
              ) : null}
            </div>
            {detail.description ? (
              <p className="m-hint">{detail.description}</p>
            ) : null}
            <button
              type="button"
              className="m-btn m-btn--primary m-btn--block"
              disabled={testing}
              onClick={() => void testConnection(detail)}
            >
              <MobileIcon name="refresh" size={16} />
              {testing
                ? t("mobile.connectors.testing", "测试中…")
                : t("mobile.connectors.test", "测试连接")}
            </button>
            <p className="m-hint">
              {t(
                "mobile.connectors.desktopOnlyHint",
                "安装、授权和高级配置请在桌面端完成。",
              )}
            </p>
          </div>
        ) : null}
      </MobileSheet>
    </MobilePage>
  );
}
