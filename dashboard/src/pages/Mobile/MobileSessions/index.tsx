import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Card, Empty, Input, Space, Spin, Tag, Typography } from "antd";
import { RefreshCw, Send, Smartphone } from "lucide-react";
import PageShell from "../../../layouts/PageShell";
import { message } from "../../../utils/antdMessage";
import { useServerTimezone } from "../../../hooks/useServerTimezone";
import { formatMessageTime } from "../../../utils/formatMessageTime";
import {
  connectorPairingApi,
  type PairedPhone,
  type PhoneReply,
} from "../../../api/modules/connectorPairing";

const { Text } = Typography;

/** 接口按时间倒序返回，气泡按对话顺序升序展示。 */
function sortReplies(list: PhoneReply[]): PhoneReply[] {
  return [...list].sort((a, b) => a.receivedAtMs - b.receivedAtMs);
}

/**
 * 「手机会话」：dashboard 与已配对手机之间的消息通道。
 *
 * 手机端通过 HappyClaw 连接器回复的内容出现在消息区（每 5 秒静默轮询），
 * dashboard 侧可以输入文本推送回所有已配对手机。
 */
export default function MobileSessionsPage() {
  const { t } = useTranslation();
  const timeZone = useServerTimezone();

  const [replies, setReplies] = useState<PhoneReply[]>([]);
  const [devices, setDevices] = useState<PairedPhone[]>([]);
  const [repliesLoading, setRepliesLoading] = useState(true);
  const [devicesLoading, setDevicesLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);

  const loadReplies = useCallback(
    async (showError: boolean) => {
      try {
        const res = await connectorPairingApi.replies(50);
        setReplies(sortReplies(res.replies ?? []));
      } catch (err) {
        if (showError) message.error((err as Error).message);
      } finally {
        setRepliesLoading(false);
      }
    },
    [],
  );

  const loadDevices = useCallback(async (showError: boolean) => {
    try {
      const res = await connectorPairingApi.devices();
      setDevices(res.devices ?? []);
    } catch (err) {
      if (showError) message.error((err as Error).message);
    } finally {
      setDevicesLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadReplies(true);
    void loadDevices(true);
  }, [loadDevices, loadReplies]);

  // 手机可能在别处回复，静默轮询保持消息区最新；卸载时清理。
  useEffect(() => {
    const timer = window.setInterval(() => {
      void loadReplies(false);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [loadReplies]);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      await Promise.all([loadReplies(true), loadDevices(true)]);
    } finally {
      setRefreshing(false);
    }
  }, [loadDevices, loadReplies]);

  const send = useCallback(async () => {
    const text = draft.trim();
    if (!text || sending) return;
    setSending(true);
    try {
      const res = await connectorPairingApi.pushMessage(text);
      setDraft("");
      message.success(
        t("mobileSessions.sent", "已推送到 {{count}} 台在线设备", {
          count: res.delivered,
        }),
      );
    } catch (err) {
      message.error((err as Error).message);
    } finally {
      setSending(false);
    }
  }, [draft, sending, t]);

  const hasDevices = devices.length > 0;

  return (
    <PageShell
      title={t("mobileSessions.title", "手机会话")}
      subtitle={t(
        "mobileSessions.description",
        "与已配对手机之间的消息通道，手机端通过 HappyClaw 连接器回复。",
      )}
      actions={
        <Button
          icon={<RefreshCw size={14} />}
          loading={refreshing}
          onClick={() => void refresh()}
        >
          {t("mobileSessions.refresh", "刷新")}
        </Button>
      }
    >
      <Space direction="vertical" size={16} style={{ width: "100%" }}>
        <Card
          size="small"
          title={
            <Space size={8}>
              <Smartphone size={16} />
              <span>{t("mobileSessions.devicesTitle", "已配对手机")}</span>
            </Space>
          }
          extra={
            <Tag color={hasDevices ? "blue" : undefined}>
              {t("mobileSessions.devicesCount", "已配对 {{count}} 台", {
                count: devices.length,
              })}
            </Tag>
          }
        >
          {devicesLoading ? (
            <Spin size="small" />
          ) : hasDevices ? (
            <Space size={8} wrap>
              {devices.map((device) => (
                <Tag key={device.deviceId} color="blue">
                  {device.name || device.deviceId}
                </Tag>
              ))}
            </Space>
          ) : (
            <Text type="secondary" style={{ fontSize: "var(--fn-text-xs)" }}>
              {t(
                "mobileSessions.noDevices",
                "还没有已配对的手机。请先在「手机控制」里完成配对，配对成功后设备会出现在这里。",
              )}
            </Text>
          )}
        </Card>

        <Card
          size="small"
          title={t("mobileSessions.messagesTitle", "消息记录")}
          extra={
            replies.length > 0 ? (
              <Tag>
                {t("mobileSessions.messagesCount", "{{count}} 条", {
                  count: replies.length,
                })}
              </Tag>
            ) : null
          }
        >
          {repliesLoading ? (
            <div style={{ padding: 32, textAlign: "center" }}>
              <Spin />
            </div>
          ) : replies.length === 0 ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={t(
                "mobileSessions.messagesEmpty",
                "还没有收到手机的消息。先在手机端的 HappyClaw 连接器里回复一条试试。",
              )}
            />
          ) : (
            <div style={{ maxHeight: 420, overflowY: "auto", paddingRight: 4 }}>
              {replies.map((item) => (
                <div
                  key={item.id}
                  style={{
                    display: "flex",
                    justifyContent: "flex-start",
                    marginBottom: 12,
                  }}
                >
                  <div style={{ maxWidth: "78%", minWidth: 0 }}>
                    <Space size={8} style={{ marginBottom: 4 }}>
                      <Text strong style={{ fontSize: 12 }}>
                        {item.deviceName || item.deviceId}
                      </Text>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {formatMessageTime(item.receivedAtMs, timeZone)}
                      </Text>
                    </Space>
                    <div
                      style={{
                        background: "var(--fn-bg-secondary, #f7f8fa)",
                        borderRadius: 10,
                        padding: "8px 12px",
                        fontSize: "var(--fn-text-xs)",
                        lineHeight: 1.6,
                        whiteSpace: "pre-wrap",
                        wordBreak: "break-word",
                      }}
                    >
                      {item.text}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card size="small" title={t("mobileSessions.composeTitle", "发送消息")}>
          <Space direction="vertical" size={12} style={{ width: "100%" }}>
            <Input.TextArea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              rows={4}
              maxLength={8000}
              showCount
              placeholder={t(
                "mobileSessions.composePlaceholder",
                "输入要推送到手机的消息…",
              )}
            />
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 12,
                flexWrap: "wrap",
              }}
            >
              <Text type="secondary" style={{ fontSize: 12 }}>
                {hasDevices
                  ? t(
                      "mobileSessions.composeHint",
                      "消息会推送给所有已配对手机，在线的会立即收到。",
                    )
                  : t(
                      "mobileSessions.composeDisabledHint",
                      "暂无已配对手机，先完成配对后才能发送。",
                    )}
              </Text>
              <Button
                type="primary"
                icon={<Send size={14} />}
                loading={sending}
                disabled={sending || !hasDevices || !draft.trim()}
                onClick={() => void send()}
              >
                {t("mobileSessions.send", "发送")}
              </Button>
            </div>
          </Space>
        </Card>
      </Space>
    </PageShell>
  );
}
