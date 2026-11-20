import { useEffect, useState } from "react";
import { Button } from "antd";
import { FolderOpen, FolderTree, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { Session } from "../hooks/useSessions";
import styles from "../index.module.less";

interface WorkspaceNoticeBarProps {
  session: Session;
  converting?: boolean;
  /** In-place: this conversation's directory becomes a project. */
  onConvert: () => void | Promise<void>;
  /** No directory yet: pick the folder that becomes the project root. */
  onChooseFolder: () => void;
}

const DISMISS_PREFIX = "happyclaw.chat.workspaceNotice.";

function dismissalKey(kind: string, threadId: string): string {
  return `${DISMISS_PREFIX}${kind}.${threadId}`;
}

function wasDismissed(key: string): boolean {
  try {
    return window.localStorage.getItem(key) === "1";
  } catch {
    return false;
  }
}

function rememberDismissal(key: string): void {
  try {
    window.localStorage.setItem(key, "1");
  } catch {
    /* private mode: the notice simply reappears next time */
  }
}

/**
 * Spec §3.2: opening or reading in a conversation without a workspace asks the
 * user what to do; the first user file written enables a separate conversation
 * workspace and says where it is.
 */
export default function WorkspaceNoticeBar({
  session,
  converting,
  onConvert,
  onChooseFolder,
}: WorkspaceNoticeBarProps) {
  const { t } = useTranslation();
  const kind =
    session.workspaceKind === "session"
      ? "session"
      : !session.projectId && !session.workspaceKind
        ? "none"
        : null;
  const key = kind ? dismissalKey(kind, session.id) : "";
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    setDismissed(kind ? wasDismissed(key) : false);
  }, [key, kind]);

  if (!kind || dismissed) return null;

  const dismiss = () => {
    rememberDismissal(key);
    setDismissed(true);
  };

  return (
    <div className={styles.chatWorkspaceNotice} role="status">
      <span className={styles.chatWorkspaceNoticeIcon}>
        {kind === "session" ? (
          <FolderTree size={16} aria-hidden />
        ) : (
          <FolderOpen size={16} aria-hidden />
        )}
      </span>
      <div className={styles.chatWorkspaceNoticeBody}>
        {kind === "session" ? (
          <>
            <span className={styles.chatWorkspaceNoticeTitle}>
              {t("chat.workspaceSessionOn", {
                defaultValue: "本对话已启用独立工作区",
              })}
            </span>
            <span
              className={styles.chatWorkspaceNoticePath}
              title={session.workspaceDir ?? ""}
            >
              {session.workspaceDir ?? ""}
            </span>
            <span className={styles.chatWorkspaceNoticeHint}>
              {t("chat.workspaceSessionOnHint", {
                defaultValue: "文件保存在这里，不会进入专家私有目录。",
              })}
            </span>
          </>
        ) : (
          <>
            <span className={styles.chatWorkspaceNoticeTitle}>
              {t("chat.workspaceMissing", {
                defaultValue: "本对话还没有工作区",
              })}
            </span>
            <span className={styles.chatWorkspaceNoticeHint}>
              {t("chat.workspaceMissingHint", {
                defaultValue:
                  "首次读写文件前，请选择文件夹；或仅本次临时读写。",
              })}
            </span>
          </>
        )}
      </div>
      <div className={styles.chatWorkspaceNoticeActions}>
        {kind === "session" ? (
          <Button size="small" loading={converting} onClick={() => void onConvert()}>
            {t("chat.workspaceConvert", { defaultValue: "转为项目" })}
          </Button>
        ) : (
          <>
            <Button size="small" type="primary" onClick={onChooseFolder}>
              {t("chat.workspacePickFolder", {
                defaultValue: "选择文件夹作为工作区…",
              })}
            </Button>
            <Button size="small" type="text" onClick={dismiss}>
              {t("chat.workspaceTemporary", { defaultValue: "仅本次临时读写" })}
            </Button>
          </>
        )}
        <button
          type="button"
          className={styles.chatWorkspaceNoticeClose}
          aria-label={t("chat.workspaceDismiss", { defaultValue: "关闭提示" })}
          onClick={dismiss}
        >
          <X size={14} aria-hidden />
        </button>
      </div>
    </div>
  );
}
