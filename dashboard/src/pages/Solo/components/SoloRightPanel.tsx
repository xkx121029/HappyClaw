import { useCallback, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Activity,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  FileCode2,
  Files,
  Loader2,
  RefreshCw,
  X,
} from "lucide-react";
import type { ChatMessage } from "../../Chat/hooks/sseHelpers";
import SoloActivityFeed, {
  buildSoloActivity,
  type SoloActivityItem,
} from "./SoloActivityFeed";
import SoloFileTree from "./SoloFileTree";
import SoloPlanPanel from "./SoloPlanPanel";
import SoloDiffDrawer from "./SoloDiffDrawer";
import Splitter from "./Splitter";
import styles from "../solo.module.less";

interface SoloRightPanelProps {
  agentId: string | null;
  agentReady: boolean;
  activePath: string | null;
  onOpenFile: (path: string) => void;
  onCloseFile: () => void;
  messages: ChatMessage[];
  isStreaming: boolean;
  timelineRatio: number;
  onTimelineRatioChange: (ratio: number) => void;
}

function fileName(path: string): string {
  return path.replace(/\/+$/, "").split("/").pop() || path;
}

/**
 * 右侧资源管理器（对应截图右栏）：
 * 打开的编辑器 → 文件树 → 底部 AI 动作时间线。
 */
export default function SoloRightPanel({
  agentId,
  agentReady,
  activePath,
  onOpenFile,
  onCloseFile,
  messages,
  isStreaming,
  timelineRatio,
  onTimelineRatioChange,
}: SoloRightPanelProps) {
  const { t } = useTranslation();
  const panelRef = useRef<HTMLElement>(null);
  const [refreshToken, setRefreshToken] = useState(0);
  const [actionsOpen, setActionsOpen] = useState(true);
  const [diffItem, setDiffItem] = useState<SoloActivityItem | null>(null);

  const actions = useMemo(
    () =>
      buildSoloActivity(messages, agentId, {
        user: t("solo.you"),
        expert: t("solo.expertReply"),
        tool: t("solo.toolCall"),
      }),
    [agentId, messages, t],
  );
  const runningCount = actions.filter((item) => item.running).length;
  const failedCount = actions.filter((item) => item.failed).length;

  const handleTimelineDrag = useCallback(
    (delta: number) => {
      const height = panelRef.current?.getBoundingClientRect().height ?? 0;
      if (height <= 0) return;
      onTimelineRatioChange(timelineRatio - delta / height);
    },
    [onTimelineRatioChange, timelineRatio],
  );

  return (
    <aside className={styles.rightPanel} ref={panelRef}>
      <header className={styles.phead}>
        <Files size={13} className={styles.headerIcon} />
        <span className={styles.pheadTitle}>{t("solo.explorer")}</span>
        <span className={styles.headerSpacer} />
        <button
          type="button"
          className={styles.pact}
          onClick={() => setRefreshToken((token) => token + 1)}
          disabled={!agentId || !agentReady}
          aria-label={t("solo.refreshFiles")}
        >
          <RefreshCw size={12} />
          {t("solo.refreshFiles")}
        </button>
      </header>

      <section className={styles.openEditors}>
        <div className={styles.sectionLabel}>{t("solo.openEditors")}</div>
        {activePath ? (
          <div className={styles.openEditorRow}>
            <button
              type="button"
              className={styles.openEditorName}
              onClick={() => onOpenFile(activePath)}
              title={activePath}
            >
              <FileCode2 size={12} />
              <span>{fileName(activePath)}</span>
            </button>
            <button
              type="button"
              className={styles.openEditorClose}
              onClick={onCloseFile}
              aria-label={t("solo.closeFile")}
            >
              <X size={11} />
            </button>
          </div>
        ) : (
          <div className={styles.sectionEmpty}>{t("solo.noOpenFile")}</div>
        )}
      </section>

      <section className={styles.treeSection}>
        <div className={styles.trsec}>
          <span className={styles.trsecLabel}>{t("solo.files")}</span>
          <span className={styles.headerSpacer} />
          <button
            type="button"
            className={styles.toolIconButton}
            onClick={() => setRefreshToken((token) => token + 1)}
            disabled={!agentId || !agentReady}
            aria-label={t("solo.refreshFiles")}
          >
            <RefreshCw size={12} />
          </button>
        </div>
        <div className={styles.treeSectionBody}>
          <SoloFileTree
            agentId={agentId}
            agentReady={agentReady}
            activePath={activePath}
            onOpenFile={onOpenFile}
            refreshToken={refreshToken}
            hideHeader
          />
        </div>
      </section>

      <SoloPlanPanel messages={messages} isStreaming={isStreaming} />

      {actionsOpen ? (
        <Splitter
          orientation="horizontal"
          onDelta={handleTimelineDrag}
          label={t("solo.resizeActions")}
        />
      ) : null}

      <section
        className={styles.actionsSection}
        style={actionsOpen ? { height: `${Math.round(timelineRatio * 1000) / 10}%` } : undefined}
      >
        <header className={styles.actionsHeader}>
          <Activity size={13} className={styles.headerIcon} />
          <span className={styles.paneTitle}>{t("solo.actions")}</span>
          {runningCount > 0 ? (
            <span className={styles.actionStatBusy}>
              <Loader2 size={10} className={styles.spin} />
              {t("solo.actionsRunning", { count: runningCount })}
            </span>
          ) : null}
          {failedCount > 0 ? (
            <span className={styles.actionStatFailed}>
              <AlertTriangle size={10} />
              {t("solo.actionsFailed", { count: failedCount })}
            </span>
          ) : null}
          <span className={styles.headerSpacer} />
          <button
            type="button"
            className={styles.toolIconButton}
            onClick={() => setActionsOpen((open) => !open)}
            aria-label={
              actionsOpen ? t("solo.collapseActions") : t("solo.expandActions")
            }
          >
            {actionsOpen ? (
              <ChevronDown size={13} />
            ) : (
              <ChevronUp size={13} />
            )}
          </button>
        </header>
        {actionsOpen ? (
          <div className={styles.actionsBody}>
            <SoloActivityFeed
              items={actions}
              agentId={agentId}
              isStreaming={isStreaming}
              onOpenFile={onOpenFile}
              onInspectDiff={setDiffItem}
            />
          </div>
        ) : null}
      </section>

      <SoloDiffDrawer
        item={diffItem}
        onClose={() => setDiffItem(null)}
        onOpenFile={onOpenFile}
      />
    </aside>
  );
}
