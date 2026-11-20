import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Monitor, Plug, Smartphone } from "lucide-react";
import PageShell from "../../../layouts/PageShell";
import { usePathTabs } from "../../../hooks/usePathTabs";
import { useCurrentUser } from "../../../hooks/useCurrentUser";
import { userCan } from "../../../utils/permissions";
import { connectorPairingApi } from "../../../api/modules/connectorPairing";
import DesktopPanel from "./DesktopPanel";
import DeviceLinkPanel from "../DeviceLink";
import ConnectorPairingPanel from "./ConnectorPairingPanel";
import styles from "./index.module.less";

export type RemoteDesktopTab = "desktop" | "link" | "pair";

const REMOTE_DESKTOP_TABS = ["desktop", "link", "pair"] as const satisfies
  readonly RemoteDesktopTab[];

const TAB_ICONS = {
  desktop: Monitor,
  link: Plug,
  pair: Smartphone,
} as const;

export default function RemoteDesktopPage() {
  const { t } = useTranslation();
  const user = useCurrentUser();
  const [pendingCount, setPendingCount] = useState(0);
  const canUsePhone = userCan(user, "mobile");

  // 待批准数量提示：没进入「手机配对」页时也要能看到，所以顶层单独轮询。
  useEffect(() => {
    if (!canUsePhone) return;
    let alive = true;
    const load = async () => {
      try {
        const res = await connectorPairingApi.pending();
        if (alive) setPendingCount(res.requests?.length ?? 0);
      } catch {
        /* 服务或权限不可用时保持上一次计数，不打断页面 */
      }
    };
    void load();
    const timer = window.setInterval(load, 15000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [canUsePhone]);

  const isAllowed = useCallback(
    (tab: RemoteDesktopTab) => {
      if (tab === "desktop") return userCan(user, "desktop");
      // 设备直连走 App 自建 TLS 链路，不依赖旧 ADB 手机能力开关
      if (tab === "link") return userCan(user, "mobile");
      // 手机配对（批准手机端连接器）同样只需 mobile 权限
      if (tab === "pair") return userCan(user, "mobile");
      return false;
    },
    [user],
  );

  const defaultTab: RemoteDesktopTab = userCan(user, "desktop")
    ? "desktop"
    : "link";

  const { activeTab, handleTabChange, isMounted } = usePathTabs({
    basePath: "/remote-desktop",
    tabs: REMOTE_DESKTOP_TABS,
    storageKey: "octop:remote-desktop:tab",
    defaultTab,
    isAllowed,
  });

  const pathTabs = useMemo(
    () => ({
      value: activeTab,
      onChange: handleTabChange,
      options: REMOTE_DESKTOP_TABS.filter((value) => isAllowed(value)).map(
        (value) => {
          const Icon = TAB_ICONS[value];
          const label = t(`remoteDesktopHub.tabs.${value}`);
          return {
            value,
            // 有待批准请求时直接在标签上给出数量，避免用户去找入口
            label:
              value === "pair" && pendingCount > 0
                ? `${label} (${pendingCount})`
                : label,
            icon: <Icon size={14} strokeWidth={2} />,
          };
        },
      ),
    }),
    [activeTab, handleTabChange, isAllowed, pendingCount, t],
  );

  const desktopVisible = activeTab === "desktop";
  const linkVisible = activeTab === "link";
  const pairVisible = activeTab === "pair";
  const pageTitle = `${t("remoteDesktopHub.title")} / ${t(
    `remoteDesktopHub.tabs.${activeTab}`,
  )}`;

  return (
    <PageShell
      title={pageTitle}
      subtitle={t("remoteDesktopHub.description")}
      fill
      pathTabs={pathTabs}
    >
      <div className={styles.panels}>
        {isMounted("desktop") && (
          <div
            className={styles.panel}
            style={{ display: activeTab === "desktop" ? "flex" : "none" }}
            aria-hidden={activeTab !== "desktop"}
          >
            <DesktopPanel embedded isVisible={desktopVisible} />
          </div>
        )}
        {isMounted("link") && (
          <div
            className={styles.panel}
            style={{ display: activeTab === "link" ? "flex" : "none" }}
            aria-hidden={activeTab !== "link"}
          >
            <DeviceLinkPanel embedded isVisible={linkVisible} />
          </div>
        )}
        {isMounted("pair") && (
          <div
            className={styles.panel}
            style={{ display: activeTab === "pair" ? "flex" : "none" }}
            aria-hidden={activeTab !== "pair"}
          >
            <ConnectorPairingPanel
              isVisible={pairVisible}
              onPendingCount={setPendingCount}
            />
          </div>
        )}
      </div>
    </PageShell>
  );
}
