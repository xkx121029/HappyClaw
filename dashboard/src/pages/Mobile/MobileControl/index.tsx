import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import {
  App,
  Button,
  Card,
  Empty,
  Popconfirm,
  Space,
  Table,
  Tag,
  Typography,
  type TableColumnsType,
} from "antd";
import { ArrowUpRight, RefreshCw, Settings2, Trash2 } from "lucide-react";
import PageShell from "../../../layouts/PageShell";
import ConnectorPairingPanel from "../../Control/RemoteDesktop/ConnectorPairingPanel";
import {
  connectorPairingApi,
  type PairedPhone,
} from "../../../api/modules/connectorPairing";

const { Text, Paragraph } = Typography;

function fmtTime(ms: number): string {
  if (!ms) return "—";
  return new Date(ms).toLocaleString(undefined, { hour12: false });
}

/**
 * 手机控制：配对请求、已配对设备与设备操作入口。
 *
 * 配对与设备数据全部来自连接器接口，页面只负责聚合展示，不缓存、
 * 不伪造离线设备。设备操作复用远控里的设备直连面板。
 */
export default function MobileControl() {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const navigate = useNavigate();

  const [devices, setDevices] = useState<PairedPhone[]>([]);
  const [loading, setLoading] = useState(false);
  const [revoking, setRevoking] = useState<string | null>(null);

  const refresh = useCallback(
    async (silent = false) => {
      if (!silent) setLoading(true);
      try {
        const res = await connectorPairingApi.devices();
        setDevices(res.devices ?? []);
      } catch (err) {
        if (!silent) message.error((err as Error).message);
      } finally {
        if (!silent) setLoading(false);
      }
    },
    [message],
  );

  useEffect(() => {
    void refresh(false);
  }, [refresh]);

  const revoke = useCallback(
    async (device: PairedPhone) => {
      setRevoking(device.deviceId);
      try {
        await connectorPairingApi.revokeDevice(device.deviceId);
        message.success(
          t("mobileControl.revoked", "已移除「{{name}}」", {
            name: device.name || device.deviceId,
          }),
        );
        await refresh(true);
      } catch (err) {
        message.error((err as Error).message);
      } finally {
        setRevoking(null);
      }
    },
    [message, refresh, t],
  );

  const columns: TableColumnsType<PairedPhone> = [
    {
      title: t("mobileControl.colDevice", "设备"),
      dataIndex: "name",
      render: (_: unknown, device) => (
        <Space direction="vertical" size={0}>
          <Text strong>{device.name || device.deviceId}</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {device.deviceId}
          </Text>
        </Space>
      ),
    },
    {
      title: t("mobileControl.colPlatform", "平台"),
      dataIndex: "platform",
      width: 150,
      render: (_: unknown, device) => (
        <Space size={6}>
          {device.platform ? <Tag>{device.platform}</Tag> : null}
          {device.appVersion ? (
            <Text type="secondary" style={{ fontSize: 12 }}>
              {device.appVersion}
            </Text>
          ) : null}
        </Space>
      ),
    },
    {
      title: t("mobileControl.colLastSeen", "最近在线"),
      dataIndex: "lastSeenAtMs",
      width: 190,
      render: (value: number) => fmtTime(value),
    },
    {
      title: t("mobileControl.colActions", "操作"),
      key: "actions",
      width: 110,
      render: (_: unknown, device) => (
        <Popconfirm
          title={t("mobileControl.revokeConfirm", "移除后该手机需要重新配对")}
          onConfirm={() => void revoke(device)}
          okText={t("mobileControl.revokeOk", "移除")}
          cancelText={t("mobileControl.cancel", "取消")}
        >
          <Button
            danger
            size="small"
            icon={<Trash2 size={14} />}
            loading={revoking === device.deviceId}
          >
            {t("mobileControl.revoke", "移除")}
          </Button>
        </Popconfirm>
      ),
    },
  ];

  return (
    <PageShell
      title={t("nav.mobileControl", "手机控制")}
      subtitle={t(
        "mobileControl.description",
        "配对与已连接设备，以及手机设备操作入口。",
      )}
      actions={
        <Button
          icon={<RefreshCw size={14} />}
          loading={loading}
          onClick={() => void refresh(false)}
        >
          {t("mobileControl.refresh", "刷新")}
        </Button>
      }
    >
      <Space direction="vertical" size={16} style={{ width: "100%" }}>
        <Card size="small">
          <ConnectorPairingPanel />
        </Card>

        <Card
          size="small"
          title={t("mobileControl.devicesTitle", "已配对设备")}
          extra={
            <Text type="secondary" style={{ fontSize: 12 }}>
              {t("mobileControl.devicesCount", "共 {{count}} 台", {
                count: devices.length,
              })}
            </Text>
          }
        >
          <Table<PairedPhone>
            size="small"
            rowKey="deviceId"
            pagination={false}
            loading={loading}
            columns={columns}
            dataSource={devices}
            locale={{
              emptyText: (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description={t(
                    "mobileControl.devicesEmpty",
                    "还没有已配对手机，在手机 App 发起配对后回到这里审核。",
                  )}
                />
              ),
            }}
          />
        </Card>

        <Card size="small" title={t("mobileControl.toolsTitle", "设备操作")}>
          <Paragraph type="secondary" style={{ marginBottom: 12 }}>
            {t(
              "mobileControl.toolsHint",
              "设备直连支持截图、点击、滑动、输入与应用/通知命令；ADB 工具由智能体在会话中调用。",
            )}
          </Paragraph>
          <Space wrap>
            <Button
              type="primary"
              icon={<ArrowUpRight size={14} />}
              onClick={() => navigate("/remote-desktop/link")}
            >
              {t("mobileControl.openDeviceLink", "打开设备操作")}
            </Button>
            <Button
              icon={<Settings2 size={14} />}
              onClick={() => navigate("/admin/advanced?tab=phone")}
            >
              {t("mobileControl.openPhoneAccess", "手机访问设置")}
            </Button>
          </Space>
        </Card>
      </Space>
    </PageShell>
  );
}
