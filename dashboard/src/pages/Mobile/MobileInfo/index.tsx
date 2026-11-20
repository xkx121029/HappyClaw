import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type CSSProperties,
} from "react";
import { useTranslation } from "react-i18next";
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Empty,
  List,
  Skeleton,
  Space,
  Switch,
  Tag,
  Typography,
} from "antd";
import {
  AppWindow,
  Bell,
  CalendarDays,
  RefreshCw,
  Smartphone,
} from "lucide-react";
import PageShell from "../../../layouts/PageShell";
import {
  deviceLinkApi,
  type DeviceLinkState,
  type DeviceLinkStatus,
  type TodaySnapshot,
} from "../../../api/modules/deviceLink";
import { useServerTimezone } from "../../../hooks/useServerTimezone";
import { formatMessageTime } from "../../../utils/formatMessageTime";
import { message } from "@/utils/antdMessage";
import styles from "./MobileInfo.module.less";

const { Text } = Typography;

const MAX_APPS = 50;

const CARD_BODY_STYLE: CSSProperties = {
  flex: 1,
  minHeight: 0,
  overflow: "auto",
  padding: 12,
};

const STATE_LABELS: Record<DeviceLinkState, string> = {
  idle: "空闲",
  connecting: "连接中",
  online: "在线",
  offline: "离线",
  unpaired: "未配对",
};

const STATE_COLORS: Record<DeviceLinkState, string | undefined> = {
  idle: undefined,
  connecting: "blue",
  online: "green",
  offline: undefined,
  unpaired: "orange",
};

interface AppEntry {
  package: string;
  label: string;
  isSystem: boolean;
  launchable: boolean;
}

interface AppListResult {
  apps: AppEntry[];
  count: number;
  truncated: boolean;
}

interface DeviceNotification {
  key: string;
  package: string;
  appLabel: string;
  title: string;
  text: string;
  postedAt: number;
  ongoing: boolean;
  category?: string;
}

interface NotificationListResult {
  granted: boolean;
  connected: boolean;
  notifications: DeviceNotification[];
  count: number;
  settingsAction?: string;
  message?: string;
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function fmtTime(ms: number | null | undefined, timeZone: string): string {
  if (!ms) return "—";
  return formatMessageTime(ms, timeZone) || "—";
}

export default function MobileInfoPage() {
  const { t } = useTranslation();
  const timeZone = useServerTimezone();

  const [status, setStatus] = useState<DeviceLinkStatus | null>(null);
  const [today, setToday] = useState<TodaySnapshot | null>(null);
  const [loading, setLoading] = useState(true);

  const [apps, setApps] = useState<AppListResult | null>(null);
  const [appsLoading, setAppsLoading] = useState(false);

  const [notifications, setNotifications] =
    useState<NotificationListResult | null>(null);
  const [notificationsLoading, setNotificationsLoading] = useState(false);

  const [consentSaving, setConsentSaving] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    const [statusResult, todayResult] = await Promise.allSettled([
      deviceLinkApi.status(),
      deviceLinkApi.today(),
    ]);

    if (statusResult.status === "fulfilled") {
      setStatus(statusResult.value);
    } else {
      message.error(
        `${t("mobileInfo.deviceStatus", "设备状态")}: ${errorMessage(
          statusResult.reason,
        )}`,
      );
    }

    if (todayResult.status === "fulfilled") {
      setToday(todayResult.value);
    } else {
      message.error(
        `${t("mobileInfo.today", "Today 融合")}: ${errorMessage(
          todayResult.reason,
        )}`,
      );
    }

    setLoading(false);
  }, [t]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleLoadApps = useCallback(async () => {
    setAppsLoading(true);
    try {
      const reply = await deviceLinkApi.command("app.list", {
        launchableOnly: true,
      });
      if (!reply.ok) {
        message.error(
          reply.error?.message ??
            t("mobileInfo.commandFailed", "读取失败，请稍后重试"),
        );
        return;
      }
      setApps((reply.result ?? null) as unknown as AppListResult | null);
    } catch (err) {
      message.error(errorMessage(err));
    } finally {
      setAppsLoading(false);
    }
  }, [t]);

  const handleLoadNotifications = useCallback(async () => {
    setNotificationsLoading(true);
    try {
      const reply = await deviceLinkApi.command("notification.list", {
        limit: 20,
      });
      if (!reply.ok) {
        message.error(
          reply.error?.message ??
            t("mobileInfo.commandFailed", "读取失败，请稍后重试"),
        );
        return;
      }
      setNotifications(
        (reply.result ?? null) as unknown as NotificationListResult | null,
      );
    } catch (err) {
      message.error(errorMessage(err));
    } finally {
      setNotificationsLoading(false);
    }
  }, [t]);

  const handleConsentChange = useCallback(
    async (value: boolean) => {
      const previous = today?.config.notificationConsent ?? false;
      setToday((current) =>
        current
          ? {
              ...current,
              config: { ...current.config, notificationConsent: value },
            }
          : current,
      );
      setConsentSaving(true);
      try {
        const reply = await deviceLinkApi.updateToday({
          notificationConsent: value,
        });
        setToday((current) =>
          current ? { ...current, config: reply.config } : current,
        );
        message.success(t("mobileInfo.consentSaved", "已更新通知采集授权"));
      } catch (err) {
        setToday((current) =>
          current
            ? {
                ...current,
                config: {
                  ...current.config,
                  notificationConsent: previous,
                },
              }
            : current,
        );
        message.error(errorMessage(err));
      } finally {
        setConsentSaving(false);
      }
    },
    [t, today?.config.notificationConsent],
  );

  const todayItems = useMemo(() => today?.snapshot.items ?? [], [today]);

  const visibleApps = useMemo(
    () => apps?.apps.slice(0, MAX_APPS) ?? [],
    [apps],
  );

  const deviceState = status?.status ?? "idle";
  const showGuide =
    Boolean(status) && (!status?.paired || status?.status === "offline");

  return (
    <PageShell
      title={t("mobileInfo.title", "手机信息")}
      subtitle={t(
        "mobileInfo.subtitle",
        "设备状态、应用与通知、Today 融合数据",
      )}
      fill
      actions={
        <Button
          icon={<RefreshCw size={14} />}
          loading={loading}
          onClick={() => void refresh()}
        >
          {t("mobileInfo.refresh", "刷新")}
        </Button>
      }
    >
      <div className={styles.root}>
        <Card
          size="small"
          className={styles.card}
          styles={{ body: CARD_BODY_STYLE }}
          title={
            <Space size={6}>
              <Smartphone size={15} />
              <span>{t("mobileInfo.deviceStatus", "设备状态")}</span>
            </Space>
          }
        >
          {loading && !status ? (
            <Skeleton active paragraph={{ rows: 4 }} />
          ) : status ? (
            <>
              <Descriptions
                size="small"
                column={{ xs: 1, sm: 2 }}
                items={[
                  {
                    key: "state",
                    label: t("mobileInfo.stateLabel", "状态"),
                    children: (
                      <Tag color={STATE_COLORS[deviceState]}>
                        {t(
                          `mobileInfo.state.${deviceState}`,
                          STATE_LABELS[deviceState],
                        )}
                      </Tag>
                    ),
                  },
                  {
                    key: "device",
                    label: t("mobileInfo.deviceName", "设备名"),
                    children: status.device_name ?? "—",
                  },
                  {
                    key: "endpoint",
                    label: t("mobileInfo.endpoint", "地址"),
                    children: `${status.host || "—"}:${status.port || "—"}`,
                  },
                  {
                    key: "latency",
                    label: t("mobileInfo.latency", "延迟"),
                    children:
                      status.latency_ms != null
                        ? `${status.latency_ms}ms`
                        : "—",
                  },
                  {
                    key: "heartbeat",
                    label: t("mobileInfo.lastHeartbeat", "最后心跳"),
                    children: fmtTime(status.last_heartbeat_at, timeZone),
                  },
                  {
                    key: "commandsTotal",
                    label: t("mobileInfo.commandsTotal", "指令总数"),
                    children: status.commands_total,
                  },
                  {
                    key: "commandsFailed",
                    label: t("mobileInfo.commandsFailed", "失败数"),
                    children: status.commands_failed,
                  },
                ]}
              />
              {showGuide && (
                <Alert
                  style={{ marginTop: 12 }}
                  type="info"
                  showIcon
                  message={
                    status.paired
                      ? t(
                          "mobileInfo.offlineHint",
                          "设备已离线，请确认手机 App 已启动并与电脑处于同一网络。",
                        )
                      : t(
                          "mobileInfo.unpairedHint",
                          "尚未配对手机，请先在手机 App 中完成配对。",
                        )
                  }
                />
              )}
            </>
          ) : (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={t("mobileInfo.deviceEmpty", "暂无设备状态数据")}
            />
          )}
        </Card>

        <Card
          size="small"
          className={styles.card}
          styles={{ body: CARD_BODY_STYLE }}
          title={
            <Space size={6}>
              <AppWindow size={15} />
              <span>{t("mobileInfo.apps", "应用")}</span>
            </Space>
          }
          extra={
            <Button
              size="small"
              loading={appsLoading}
              onClick={() => void handleLoadApps()}
            >
              {t("mobileInfo.readApps", "读取应用列表")}
            </Button>
          }
        >
          {apps ? (
            <>
              <div className={styles.summaryRow}>
                <Text type="secondary">
                  {t("mobileInfo.appCount", "共 {{total}} 个应用", {
                    total: apps.count,
                  })}
                </Text>
                {apps.truncated && (
                  <Text type="warning">
                    {t(
                      "mobileInfo.appTruncated",
                      "列表已截断，仅显示前 {{shown}} 条",
                      { shown: visibleApps.length },
                    )}
                  </Text>
                )}
              </div>
              <List
                size="small"
                split
                dataSource={visibleApps}
                rowKey={(app) => app.package}
                locale={{
                  emptyText: t("mobileInfo.appsEmpty", "没有可启动的应用"),
                }}
                renderItem={(app) => (
                  <List.Item>
                    <div className={styles.itemBody}>
                      <Space size={6} wrap>
                        <Text strong ellipsis>
                          {app.label || app.package}
                        </Text>
                        <Tag color={app.isSystem ? undefined : "blue"}>
                          {app.isSystem
                            ? t("mobileInfo.systemApp", "系统应用")
                            : t("mobileInfo.userApp", "用户应用")}
                        </Tag>
                      </Space>
                      <Text
                        type="secondary"
                        style={{ fontSize: 12 }}
                        ellipsis={{ tooltip: app.package }}
                      >
                        {app.package}
                      </Text>
                    </div>
                  </List.Item>
                )}
              />
            </>
          ) : (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={t(
                "mobileInfo.appsHint",
                "读取后显示手机上的可启动应用",
              )}
            />
          )}
        </Card>

        <Card
          size="small"
          className={styles.card}
          styles={{ body: CARD_BODY_STYLE }}
          title={
            <Space size={6}>
              <Bell size={15} />
              <span>{t("mobileInfo.notifications", "通知")}</span>
            </Space>
          }
          extra={
            <Button
              size="small"
              loading={notificationsLoading}
              onClick={() => void handleLoadNotifications()}
            >
              {t("mobileInfo.readNotifications", "读取最近通知")}
            </Button>
          }
        >
          {notifications && notifications.granted === false ? (
            <Alert
              type="warning"
              showIcon
              message={
                notifications.message ||
                t("mobileInfo.notificationDenied", "通知访问权限未授予")
              }
              description={
                notifications.settingsAction
                  ? t(
                      "mobileInfo.settingsActionHint",
                      "请在手机设置中打开通知使用权（设置入口：{{action}}）",
                      { action: notifications.settingsAction },
                    )
                  : t(
                      "mobileInfo.notificationDeniedHint",
                      "请在手机系统设置中为 HappyClaw 开启通知使用权后重试。",
                    )
              }
            />
          ) : notifications && notifications.connected === false ? (
            <Alert
              type="info"
              showIcon
              message={t(
                "mobileInfo.notificationDisconnected",
                "手机通知服务未连接",
              )}
            />
          ) : notifications ? (
            <List
              size="small"
              split
              dataSource={notifications.notifications}
              rowKey={(item) => item.key}
              locale={{
                emptyText: t("mobileInfo.notificationsEmpty", "暂无最近通知"),
              }}
              renderItem={(item) => (
                <List.Item>
                  <div className={styles.itemBody}>
                    <div className={styles.itemMeta}>
                      <Tag color="blue">{item.appLabel || item.package}</Tag>
                      {item.ongoing && (
                        <Tag color="green">
                          {t("mobileInfo.ongoing", "进行中")}
                        </Tag>
                      )}
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {fmtTime(item.postedAt, timeZone)}
                      </Text>
                    </div>
                    {item.title && <Text strong>{item.title}</Text>}
                    {item.text && (
                      <Text
                        type="secondary"
                        style={{ fontSize: 12, whiteSpace: "pre-wrap" }}
                      >
                        {item.text}
                      </Text>
                    )}
                  </div>
                </List.Item>
              )}
            />
          ) : (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={t(
                "mobileInfo.notificationsHint",
                "读取后显示手机最近的通知",
              )}
            />
          )}
        </Card>

        <Card
          size="small"
          className={styles.card}
          styles={{ body: CARD_BODY_STYLE }}
          title={
            <Space size={6}>
              <CalendarDays size={15} />
              <span>{t("mobileInfo.today", "Today 融合")}</span>
            </Space>
          }
        >
          {today ? (
            <>
              <Descriptions
                size="small"
                column={{ xs: 1, sm: 2 }}
                items={[
                  {
                    key: "updated",
                    label: t("mobileInfo.todayUpdated", "更新时间"),
                    children: fmtTime(today.snapshot.updatedAt, timeZone),
                  },
                  {
                    key: "day",
                    label: t("mobileInfo.todayDay", "日期"),
                    children: today.snapshot.day ?? "—",
                  },
                ]}
              />
              <div className={styles.consentRow}>
                <Text>{t("mobileInfo.todayConsent", "通知采集授权")}</Text>
                <Switch
                  size="small"
                  checked={Boolean(today.config.notificationConsent)}
                  loading={consentSaving}
                  onChange={(value) => void handleConsentChange(value)}
                />
              </div>
              {todayItems.length > 0 ? (
                <List
                  size="small"
                  split
                  dataSource={todayItems}
                  rowKey={(item) =>
                    item.id ??
                    `${item.source ?? ""}-${item.at ?? ""}-${item.title ?? ""}`
                  }
                  renderItem={(item) => {
                    const at =
                      item.at ??
                      (typeof item.postedAt === "number"
                        ? item.postedAt
                        : undefined);
                    return (
                      <List.Item>
                        <div className={styles.itemBody}>
                          <div className={styles.itemMeta}>
                            {item.source && <Tag>{item.source}</Tag>}
                            {item.kind && <Tag color="blue">{item.kind}</Tag>}
                            {at != null && (
                              <Text type="secondary" style={{ fontSize: 12 }}>
                                {fmtTime(at, timeZone)}
                              </Text>
                            )}
                          </div>
                          <Text strong>
                            {item.title ||
                              t("mobileInfo.untitled", "未命名条目")}
                          </Text>
                          {item.text && (
                            <Text type="secondary" style={{ fontSize: 12 }}>
                              {item.text}
                            </Text>
                          )}
                        </div>
                      </List.Item>
                    );
                  }}
                />
              ) : (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description={t("mobileInfo.todayEmpty", "今天还没有聚合条目")}
                />
              )}
            </>
          ) : loading ? (
            <Skeleton active paragraph={{ rows: 3 }} />
          ) : (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={t("mobileInfo.todayNotLoaded", "Today 数据尚未加载")}
            />
          )}
        </Card>
      </div>
    </PageShell>
  );
}
