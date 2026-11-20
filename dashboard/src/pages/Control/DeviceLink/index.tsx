import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Alert,
  App,
  Button,
  Descriptions,
  Input,
  InputNumber,
  Space,
  Table,
  Tag,
  Typography,
  type TableColumnsType,
} from "antd";
import {
  AppWindow,
  Camera,
  ListTree,
  MousePointerClick,
  MoveRight,
  Keyboard,
  Plug,
  Unplug,
} from "lucide-react";
import { requestBlob } from "../../../api/request";
import {
  deviceLinkApi,
  type CommandRecord,
  type CommandSpec,
  type DeviceLinkEvent,
  type DeviceLinkStatus,
} from "../../../api/modules/deviceLink";
import styles from "./index.module.less";

interface Props {
  embedded?: boolean;
  isVisible?: boolean;
}

const { Text } = Typography;

function fmtTime(ms: number | null | undefined): string {
  if (!ms) return "—";
  return new Date(ms).toLocaleTimeString();
}

function summaryOf(command?: CommandRecord): string {
  if (!command) return "—";
  if (command.error) return `${command.error.code}: ${command.error.message}`;
  return JSON.stringify(command.result ?? {}).slice(0, 160);
}

export default function DeviceLinkPanel({ isVisible = true }: Props) {
  const { t } = useTranslation();
  const { message } = App.useApp();

  const [status, setStatus] = useState<DeviceLinkStatus | null>(null);
  const [catalog, setCatalog] = useState<CommandSpec[]>([]);
  const [events, setEvents] = useState<DeviceLinkEvent[]>([]);
  const [busy, setBusy] = useState<string | null>(null);

  const [host, setHost] = useState("");
  const [port, setPort] = useState(17420);
  const [code, setCode] = useState("");
  const [clickX, setClickX] = useState(540);
  const [clickY, setClickY] = useState(1200);
  const [swipe, setSwipe] = useState({ x1: 540, y1: 1800, x2: 540, y2: 600, durationMs: 300 });
  const [text, setText] = useState("hello happyclaw");
  const [artifacts, setArtifacts] = useState<Record<string, string>>({});
  const [treePreview, setTreePreview] = useState<string>("");

  const refresh = useCallback(async () => {
    try {
      const next = await deviceLinkApi.status();
      setStatus(next);
      if (next.host) setHost((prev) => prev || next.host);
      if (next.port) setPort((prev) => prev || next.port);
    } catch {
      /* 后端不可用时保持上一次状态，页面不闪 */
    }
  }, []);

  useEffect(() => {
    void refresh();
    deviceLinkApi
      .catalog()
      .then((res) => setCatalog(res.commands))
      .catch(() => setCatalog([]));
  }, [refresh]);

  useEffect(() => {
    const dispose = deviceLinkApi.streamEvents(
      (next) => setStatus(next),
      (event) => setEvents((prev) => [event, ...prev].slice(0, 60)),
    );
    return dispose;
  }, []);

  useEffect(() => {
    if (!isVisible) return;
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => window.clearInterval(timer);
  }, [isVisible, refresh]);

  const runCommand = useCallback(
    async (name: string, params: Record<string, unknown> = {}) => {
      setBusy(name);
      try {
        const reply = await deviceLinkApi.command(name, params);
        if (reply.ok) {
          message.success(`${name} · ${reply.duration_ms ?? 0}ms${reply.replayed ? " (replayed)" : ""}`);
        } else {
          message.error(`${name} · ${reply.error?.code ?? "FAILED"}: ${reply.error?.message ?? ""}`);
        }
        if (name === "screen.screenshot" && reply.artifact) {
          const blob = await requestBlob(`/device-link/screenshot/${reply.artifact.split(/[\\/]/).pop()}`);
          const url = URL.createObjectURL(blob);
          setArtifacts((prev) => ({ ...prev, [reply.artifact as string]: url }));
        }
        if (name === "screen.tree") {
          setTreePreview(JSON.stringify(reply.result ?? {}, null, 2));
        }
        await refresh();
        return reply;
      } catch (err) {
        message.error(`${name}: ${(err as Error).message}`);
        return null;
      } finally {
        setBusy(null);
      }
    },
    [message, refresh],
  );

  const handlePair = useCallback(async () => {
    if (!host.trim() || !code.trim()) {
      message.warning(t("deviceLink.fillHint"));
      return;
    }
    setBusy("pair");
    try {
      const paired = await deviceLinkApi.pair(host.trim(), port, code.trim());
      setCode("");
      message.success(`${t("deviceLink.paired")}: ${paired.device_name}`);
      await deviceLinkApi.connect(host.trim(), port);
      await refresh();
    } catch (err) {
      message.error((err as Error).message);
    } finally {
      setBusy(null);
    }
  }, [code, host, message, port, refresh, t]);

  const handleConnect = useCallback(async () => {
    setBusy("connect");
    try {
      await deviceLinkApi.connect(host.trim() || undefined, port || undefined);
      await refresh();
    } catch (err) {
      message.error((err as Error).message);
    } finally {
      setBusy(null);
    }
  }, [host, message, port, refresh]);

  const handleDisconnect = useCallback(async () => {
    setBusy("disconnect");
    try {
      await deviceLinkApi.disconnect();
      await refresh();
    } catch (err) {
      message.error((err as Error).message);
    } finally {
      setBusy(null);
    }
  }, [message, refresh]);

  const stateColor = useMemo(() => {
    switch (status?.status) {
      case "online":
        return "green";
      case "connecting":
        return "blue";
      case "offline":
        return "orange";
      case "unpaired":
        return "default";
      default:
        return "default";
    }
  }, [status?.status]);

  const online = status?.status === "online";

  const actionCards = [
    {
      key: "screen.screenshot",
      label: t("deviceLink.screenshot"),
      icon: <Camera size={15} />,
      params: {},
    },
    {
      key: "screen.tree",
      label: t("deviceLink.tree"),
      icon: <ListTree size={15} />,
      params: {},
    },
    {
      key: "app.list",
      label: t("deviceLink.apps"),
      icon: <AppWindow size={15} />,
      params: {},
    },
  ] as const;

  const historyColumns: TableColumnsType<CommandRecord> = [
    {
      title: t("deviceLink.colTime"),
      dataIndex: "started_at",
      width: 110,
      render: (value: number) => fmtTime(value),
    },
    { title: t("deviceLink.colCommand"), dataIndex: "name", width: 150 },
    {
      title: t("deviceLink.colResult"),
      dataIndex: "ok",
      width: 90,
      render: (ok: boolean) => (
        <Tag color={ok ? "green" : "red"}>{ok ? "OK" : "FAIL"}</Tag>
      ),
    },
    {
      title: t("deviceLink.colDuration"),
      dataIndex: "duration_ms",
      width: 90,
      render: (value: number) => `${value}ms`,
    },
    {
      title: t("deviceLink.colDetail"),
      dataIndex: "result",
      render: (_: unknown, record: CommandRecord) => (
        <Text type="secondary" ellipsis={{ tooltip: summaryOf(record) }} style={{ maxWidth: 260 }}>
          {summaryOf(record)}
        </Text>
      ),
    },
    {
      title: t("deviceLink.colArtifact"),
      dataIndex: "artifact",
      width: 180,
      render: (artifact: string | null) =>
        artifact ? (
          <a href={artifacts[artifact] ?? "#"} target="_blank" rel="noreferrer">
            {t("deviceLink.viewImage")}
          </a>
        ) : (
          "—"
        ),
    },
  ];

  return (
    <div className={styles.root}>
      <div className={styles.toolbar}>
        <Space wrap>
          <Input
            addonBefore={t("deviceLink.host")}
            value={host}
            onChange={(e) => setHost(e.target.value)}
            placeholder="192.168.1.20"
            style={{ width: 260 }}
          />
          <InputNumber
            addonBefore={t("deviceLink.port")}
            value={port}
            min={1}
            max={65535}
            onChange={(value) => setPort(Number(value) || 0)}
            style={{ width: 160 }}
          />
          <Input
            addonBefore={t("deviceLink.code")}
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="8 位配对码"
            style={{ width: 220 }}
          />
          <Button
            type="primary"
            icon={<Plug size={14} />}
            loading={busy === "pair"}
            onClick={() => void handlePair()}
          >
            {t("deviceLink.pair")}
          </Button>
          <Button loading={busy === "connect"} onClick={() => void handleConnect()}>
            {t("deviceLink.connect")}
          </Button>
          <Button
            danger
            icon={<Unplug size={14} />}
            loading={busy === "disconnect"}
            disabled={!status?.connected_at && !online}
            onClick={() => void handleDisconnect()}
          >
            {t("deviceLink.disconnect")}
          </Button>
        </Space>
      </div>

      {!status?.paired && (
        <Alert
          className={styles.notice}
          type="info"
          showIcon
          message={t("deviceLink.unpairedHint")}
        />
      )}
      {status?.reason && (
        <Alert className={styles.notice} type="warning" showIcon message={status.reason} />
      )}

      <Descriptions
        size="small"
        bordered
        column={4}
        className={styles.descriptions}
        items={[
          {
            key: "state",
            label: t("deviceLink.status"),
            children: (
              <Tag color={stateColor}>{t(`deviceLink.state.${status?.status ?? "idle"}`)}</Tag>
            ),
          },
          { key: "device", label: t("deviceLink.device"), children: status?.device_name ?? "—" },
          {
            key: "heartbeat",
            label: t("deviceLink.lastHeartbeat"),
            children: fmtTime(status?.last_heartbeat_at),
          },
          {
            key: "latency",
            label: t("deviceLink.latency"),
            children: status?.latency_ms != null ? `${status.latency_ms}ms` : "—",
          },
          {
            key: "action",
            label: t("deviceLink.currentAction"),
            children: status?.current_action ?? "—",
          },
          {
            key: "reconnect",
            label: t("deviceLink.reconnect"),
            children: `${status?.reconnect_count ?? 0} / ${status?.commands_failed ?? 0}`,
          },
          {
            key: "endpoint",
            label: t("deviceLink.endpoint"),
            children: status ? `${status.host || "—"}:${status.port || "—"}` : "—",
          },
          {
            key: "fingerprint",
            label: t("deviceLink.fingerprint"),
            children: (
              <Text code style={{ fontSize: 12 }}>
                {(status?.device_fingerprint ?? "—").slice(0, 16)}…
              </Text>
            ),
          },
        ]}
      />

      <div className={styles.sectionTitle}>{t("deviceLink.capabilities")}</div>
      <Space wrap className={styles.actions}>
        {actionCards.map((item) => (
          <Button
            key={item.key}
            icon={item.icon}
            disabled={!online}
            loading={busy === item.key}
            onClick={() => void runCommand(item.key, item.params)}
          >
            {item.label}
          </Button>
        ))}
        <Space.Compact>
          <InputNumber value={clickX} onChange={(v) => setClickX(Number(v) || 0)} style={{ width: 80 }} />
          <InputNumber value={clickY} onChange={(v) => setClickY(Number(v) || 0)} style={{ width: 80 }} />
          <Button
            icon={<MousePointerClick size={14} />}
            disabled={!online}
            loading={busy === "ui.click"}
            onClick={() => void runCommand("ui.click", { x: clickX, y: clickY })}
          >
            {t("deviceLink.click")}
          </Button>
        </Space.Compact>
        <Space.Compact>
          <InputNumber
            value={swipe.x1}
            onChange={(v) => setSwipe({ ...swipe, x1: Number(v) || 0 })}
            style={{ width: 70 }}
          />
          <InputNumber
            value={swipe.y1}
            onChange={(v) => setSwipe({ ...swipe, y1: Number(v) || 0 })}
            style={{ width: 70 }}
          />
          <InputNumber
            value={swipe.x2}
            onChange={(v) => setSwipe({ ...swipe, x2: Number(v) || 0 })}
            style={{ width: 70 }}
          />
          <InputNumber
            value={swipe.y2}
            onChange={(v) => setSwipe({ ...swipe, y2: Number(v) || 0 })}
            style={{ width: 70 }}
          />
          <Button
            icon={<MoveRight size={14} />}
            disabled={!online}
            loading={busy === "ui.swipe"}
            onClick={() => void runCommand("ui.swipe", swipe)}
          >
            {t("deviceLink.swipe")}
          </Button>
        </Space.Compact>
        <Space.Compact>
          <Input
            value={text}
            onChange={(e) => setText(e.target.value)}
            style={{ width: 200 }}
            placeholder={t("deviceLink.textPlaceholder")}
          />
          <Button
            icon={<Keyboard size={14} />}
            disabled={!online}
            loading={busy === "ui.typeText"}
            onClick={() => void runCommand("ui.typeText", { text })}
          >
            {t("deviceLink.typeText")}
          </Button>
        </Space.Compact>
      </Space>

      {treePreview && (
        <>
          <div className={styles.sectionTitle}>{t("deviceLink.treePreview")}</div>
          <pre className={styles.pre}>{treePreview.slice(0, 4000)}</pre>
        </>
      )}

      <div className={styles.sectionTitle}>{t("deviceLink.history")}</div>
      <Table<CommandRecord>
        size="small"
        rowKey="command_id"
        pagination={false}
        scroll={{ y: 220 }}
        columns={historyColumns}
        dataSource={status?.recent_commands ?? []}
        locale={{ emptyText: t("deviceLink.noData") }}
      />

      <div className={styles.sectionTitle}>{t("deviceLink.events")}</div>
      <div className={styles.eventList}>
        {events.length === 0 && <Text type="secondary">{t("deviceLink.noData")}</Text>}
        {events.map((event) => (
          <div key={event.seq} className={styles.eventRow}>
            <span className={styles.eventTime}>{fmtTime(event.at)}</span>
            <Tag color={event.kind.startsWith("command") ? "blue" : "default"}>{event.kind}</Tag>
            <Text ellipsis={{ tooltip: JSON.stringify(event.data) }} style={{ maxWidth: 620 }}>
              {JSON.stringify(event.data)}
            </Text>
          </div>
        ))}
      </div>

      <div className={styles.footer}>
        <Text type="secondary">
          {t("deviceLink.catalogCount", { count: catalog.length })} · {t("deviceLink.protocolHint")}
        </Text>
      </div>
    </div>
  );
}
