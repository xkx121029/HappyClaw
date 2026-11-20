import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  App,
  Button,
  Empty,
  Space,
  Table,
  Tag,
  Typography,
  type TableColumnsType,
} from "antd";
import { Check, RefreshCw, X } from "lucide-react";
import {
  connectorPairingApi,
  type PendingPairRequest,
} from "../../../api/modules/connectorPairing";

interface Props {
  isVisible?: boolean;
  /** 待处理数量回传给父级，用于在标签页上显示角标。 */
  onPendingCount?: (count: number) => void;
}

const { Text } = Typography;

function fmtTime(ms: number): string {
  return new Date(ms).toLocaleString(undefined, { hour12: false });
}

function fmtRemaining(expiresAtMs: number): string {
  const seconds = Math.max(0, Math.round((expiresAtMs - Date.now()) / 1000));
  const mm = Math.floor(seconds / 60);
  const ss = seconds % 60;
  return `${mm}:${String(ss).padStart(2, "0")}`;
}

/**
 * 手机端连接器：待批准的配对请求。
 *
 * 手机 App 发起配对后，服务端会在这里列出一条请求；用户核对设备名、请求时间
 * 和配对码后同意或拒绝。数据每 5 秒拉取一次，因为手机端可能在别的设备上操作。
 */
export default function ConnectorPairingPanel({ isVisible = true, onPendingCount }: Props) {
  const { t } = useTranslation();
  const { message } = App.useApp();

  const [items, setItems] = useState<PendingPairRequest[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = useCallback(
    async (silent = true) => {
      if (!silent) setLoading(true);
      try {
        const res = await connectorPairingApi.pending();
        const list = res.requests ?? [];
        setItems(list);
        onPendingCount?.(list.length);
      } catch (err) {
        if (!silent) message.error((err as Error).message);
      } finally {
        if (!silent) setLoading(false);
      }
    },
    [message, onPendingCount],
  );

  useEffect(() => {
    void refresh(false);
  }, [refresh]);

  useEffect(() => {
    if (!isVisible) return;
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => window.clearInterval(timer);
  }, [isVisible, refresh]);

  const act = useCallback(
    async (item: PendingPairRequest, kind: "approve" | "reject") => {
      setBusy(item.requestId);
      try {
        const res =
          kind === "approve"
            ? await connectorPairingApi.approve(item)
            : await connectorPairingApi.reject(item);
        if (res.ok) {
          message.success(
            kind === "approve"
              ? t("remoteDesktopHub.connectorPairing.approved")
              : t("remoteDesktopHub.connectorPairing.rejected"),
          );
        } else {
          message.error(
            res.message || t("remoteDesktopHub.connectorPairing.failed"),
          );
        }
        await refresh();
      } catch (err) {
        message.error((err as Error).message);
      } finally {
        setBusy(null);
      }
    },
    [message, refresh, t],
  );

  const columns: TableColumnsType<PendingPairRequest> = [
    {
      title: t("remoteDesktopHub.connectorPairing.colDevice"),
      dataIndex: "deviceName",
      render: (_: unknown, item) => (
        <Space direction="vertical" size={0}>
          <Text strong>{item.deviceName || item.deviceId}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {[item.platform, item.appVersion].filter(Boolean).join(" · ") || "—"}
          </Text>
        </Space>
      ),
    },
    {
      title: t("remoteDesktopHub.connectorPairing.colRequestedAt"),
      dataIndex: "createdAtMs",
      width: 190,
      render: (value: number) => fmtTime(value),
    },
    {
      title: t("remoteDesktopHub.connectorPairing.colCode"),
      dataIndex: "code",
      width: 150,
      render: (value: string) => (
        <Text code style={{ fontSize: "var(--fn-text-md)", letterSpacing: 2 }}>
          {value}
        </Text>
      ),
    },
    {
      title: t("remoteDesktopHub.connectorPairing.colExpires"),
      dataIndex: "expiresAtMs",
      width: 130,
      render: (value: number) =>
        value > Date.now() ? (
          <Tag color="processing">
            {t("remoteDesktopHub.connectorPairing.expiresIn", {
              time: fmtRemaining(value),
            })}
          </Tag>
        ) : (
          <Tag>{t("remoteDesktopHub.connectorPairing.expired")}</Tag>
        ),
    },
    {
      title: t("remoteDesktopHub.connectorPairing.colActions"),
      key: "actions",
      width: 170,
      render: (_: unknown, item) => (
        <Space>
          <Button
            type="primary"
            size="small"
            icon={<Check size={14} />}
            loading={busy === item.requestId}
            onClick={() => void act(item, "approve")}
          >
            {t("remoteDesktopHub.connectorPairing.approve")}
          </Button>
          <Button
            danger
            size="small"
            icon={<X size={14} />}
            disabled={busy === item.requestId}
            onClick={() => void act(item, "reject")}
          >
            {t("remoteDesktopHub.connectorPairing.reject")}
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div style={{ flex: 1, minHeight: 0, overflow: "auto" }}>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          marginBottom: 4,
        }}
      >
        <Space size={8}>
          <Text strong style={{ fontSize: "var(--fn-text-md)" }}>
            {t("remoteDesktopHub.connectorPairing.title")}
          </Text>
          {items.length > 0 && (
            <Tag color="red">
              {t("remoteDesktopHub.connectorPairing.pendingCount", {
                count: items.length,
              })}
            </Tag>
          )}
        </Space>
        <Button
          size="small"
          icon={<RefreshCw size={14} />}
          loading={loading}
          onClick={() => void refresh(false)}
        >
          {t("remoteDesktopHub.connectorPairing.refresh")}
        </Button>
      </div>
      <Text type="secondary" style={{ fontSize: "var(--fn-text-xs)", display: "block", marginBottom: 16 }}>
        {t("remoteDesktopHub.connectorPairing.hint")}
      </Text>

      <Table<PendingPairRequest>
        size="small"
        rowKey="requestId"
        pagination={false}
        loading={loading}
        columns={columns}
        dataSource={items}
        locale={{
          emptyText: (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={t("remoteDesktopHub.connectorPairing.empty")}
            />
          ),
        }}
      />
    </div>
  );
}
