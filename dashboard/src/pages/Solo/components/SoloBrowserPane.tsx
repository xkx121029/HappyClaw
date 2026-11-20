import { useTranslation } from "react-i18next";
import { Button } from "antd";
import { Globe, RefreshCw } from "lucide-react";
import BrowserWorkspace from "../../../components/BrowserWorkspace";
import { useBrowserSessionState } from "../../../hooks/useBrowserSessionState";
import styles from "../solo.module.less";

interface SoloBrowserPaneProps {
  threadId: string | null;
  agentReady: boolean;
  /** 远端专家时才有的 Bridge 连接，和主对话用同一个来源。 */
  bridgeConnectionId?: string | null;
}

/**
 * SOLO 的浏览器预览页签。
 *
 * 直接复用主对话的 browser 会话钩子和 BrowserWorkspace；SOLO 不自己启动
 * 浏览器，只展示 agent 已经打开的那一个。没有会话时给出明确说明与刷新，
 * 不做“看起来能启动其实不能”的按钮。
 */
export default function SoloBrowserPane({
  threadId,
  agentReady,
  bridgeConnectionId,
}: SoloBrowserPaneProps) {
  const { t } = useTranslation();
  const canPreview = Boolean(threadId) && agentReady;
  const { sessionId, environment, isConnected, refresh } = useBrowserSessionState(
    threadId ?? undefined,
    canPreview,
    bridgeConnectionId,
  );

  if (sessionId) {
    return (
      <div className={styles.browserPane}>
        <BrowserWorkspace
          sessionId={sessionId}
          environment={environment}
          bridgeConnectionId={bridgeConnectionId}
          hideHeaderRefresh
          style={{ flex: 1, minHeight: 0 }}
        />
      </div>
    );
  }

  return (
    <div className={styles.browserEmpty}>
      <Globe size={20} className={styles.browserEmptyIcon} />
      <p className={styles.browserEmptyTitle}>{t("solo.browserEmptyTitle")}</p>
      <p className={styles.browserEmptyBody}>
        {!threadId
          ? t("solo.browserNoThread")
          : !agentReady
            ? t("solo.agentStoppedHint")
            : t("solo.browserEmptyBody")}
      </p>
      {canPreview && bridgeConnectionId ? (
        <p className={styles.browserEmptyNote}>{t("solo.browserRemoteHint")}</p>
      ) : null}
      {canPreview ? (
        <p className={styles.browserEmptyNote}>
          {isConnected
            ? t("solo.browserWaitingHint")
            : t("solo.browserStreamOffline")}
        </p>
      ) : null}
      <Button
        size="small"
        icon={<RefreshCw size={12} />}
        onClick={() => void refresh()}
        disabled={!canPreview}
      >
        {t("solo.browserRefresh")}
      </Button>
    </div>
  );
}
