import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Dropdown, Switch } from "antd";
import type { MenuProps } from "antd";
import { useTranslation } from "react-i18next";
import {
  MoreVertical,
  Pin,
  PinOff,
  Pencil,
  Trash2,
  GitFork,
  Download,
  PanelsTopLeft,
} from "lucide-react";
import { confirmDeleteConversation } from "../utils/deleteConversation";
import type { Session } from "../hooks/useSessions";
import SessionChannelIcon from "./SessionChannelIcon";
import SessionShareMark from "./SessionShareMark";
import TeamChatBadge from "./TeamChatBadge";
import RemoteExpertHint from "./RemoteExpertHint";
import styles from "../index.module.less";
import { isImeComposing } from "../../../utils/ime";
import { useCollapseThinking } from "../hooks/useCollapseThinking";
import { rememberSharedRect, SharedElement } from "../../../motion";

interface ChatTitleBarProps {
  session: Session;
  title: string;
  onRename: (id: string, name: string) => void;
  onPin: (id: string, pinned: boolean) => void;
  onFork: (id: string) => void;
  onDelete: (
    id: string,
    compact: boolean,
  ) => void | Promise<boolean | null | void>;
  forkDisabled?: boolean;
  forkDisabledHint?: string;
  /** 有可导出消息时由父组件传入；未传则隐藏导出入口。 */
  onExportTranscript?: () => void;
  /** 传入后展示 SOLO 模式入口；未传则不渲染，避免脱离路由时依赖 useNavigate。 */
  onOpenSolo?: () => void;
  isTeam?: boolean;
  agent?: {
    bridge?: boolean | null;
    bridge_connection_name?: string | null;
    bridge_connection_icon?: string | null;
  } | null;
  /** 当前对话的工作区入口（chip + 菜单由父组件构建）；未传则不渲染。 */
  workspaceChip?: ReactNode;
}

export default function ChatTitleBar({
  session,
  title,
  onRename,
  onPin,
  onFork,
  onDelete,
  forkDisabled,
  forkDisabledHint,
  onExportTranscript,
  onOpenSolo,
  isTeam = false,
  agent = null,
  workspaceChip = null,
}: ChatTitleBarProps) {
  const { t } = useTranslation();
  const [collapseThinking, setCollapseThinking] = useCollapseThinking(isTeam);
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState(title);
  const inputRef = useRef<HTMLInputElement>(null);

  // 离开会话前记住标题位置：按下指针（即将点击侧栏/返回）时记录一次，
  // 回到列表页由同名标题的共享元素接着落回原处。
  const titleRef = useRef<HTMLHeadingElement>(null);
  const titleValueRef = useRef(title);
  titleValueRef.current = title;
  useEffect(() => {
    const record = () => {
      const el = titleRef.current;
      const value = titleValueRef.current;
      if (!el || !value) return;
      rememberSharedRect(
        `thread-title:${value}`,
        el.getBoundingClientRect(),
      );
    };
    document.addEventListener("pointerdown", record, true);
    return () => document.removeEventListener("pointerdown", record, true);
  }, []);

  useEffect(() => {
    if (!isEditing) setEditValue(title);
  }, [title, isEditing]);

  useEffect(() => {
    if (isEditing) {
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [isEditing]);

  const commitEdit = useCallback(() => {
    const trimmed = editValue.trim();
    if (trimmed && trimmed !== session.name) {
      onRename(session.id, trimmed);
    } else {
      setEditValue(title);
    }
    setIsEditing(false);
  }, [editValue, session.id, session.name, onRename, title]);

  const menuItems: MenuProps["items"] = useMemo(
    () => [
      {
        key: "collapse-thinking",
        label: t("chat.collapseThinking"),
        title: t("chat.collapseThinkingHint"),
        icon: (
          <Switch
            size="small"
            checked={collapseThinking}
            tabIndex={-1}
            aria-label={t("chat.collapseThinking")}
          />
        ),
        onClick: () => setCollapseThinking(!collapseThinking),
      },
      { type: "divider" },
      {
        key: "pin",
        label: session.pinned
          ? t("chat.unpin", "取消置顶")
          : t("chat.pin", "置顶"),
        icon: session.pinned ? <PinOff size={14} /> : <Pin size={14} />,
        onClick: () => onPin(session.id, !session.pinned),
      },
      {
        key: "fork",
        label: t("chat.fork", "分叉"),
        icon: <GitFork size={14} />,
        disabled: forkDisabled,
        title: forkDisabled && forkDisabledHint ? forkDisabledHint : undefined,
        onClick: () => onFork(session.id),
      },
      ...(onExportTranscript
        ? [
            {
              key: "export-transcript",
              label: t("chat.exportTranscript", "导出为 Markdown"),
              title: t(
                "chat.exportTranscriptHint",
                "把当前会话保存为 Markdown 文件",
              ),
              icon: <Download size={14} />,
              onClick: () => onExportTranscript(),
            },
          ]
        : []),
      {
        key: "delete",
        label: t("common.delete"),
        icon: <Trash2 size={14} />,
        danger: true,
        onClick: () => {
          confirmDeleteConversation(t, (compact) =>
            onDelete(session.id, compact),
          );
        },
      },
    ],
    [
      collapseThinking,
      setCollapseThinking,
      session.id,
      session.pinned,
      onPin,
      onFork,
      onExportTranscript,
      onDelete,
      forkDisabled,
      forkDisabledHint,
      t,
    ],
  );

  return (
    <div className={styles.chatTitleBar}>
      <div className={styles.chatTitleLeft}>
        <SessionChannelIcon
          channelType={session.channelType}
          size={13}
          className={styles.chatTitleLeadingIcon}
        />
        {isEditing ? (
          <input
            ref={inputRef}
            className={styles.chatTitleInput}
            value={editValue}
            onChange={(e) => setEditValue(e.target.value)}
            onBlur={commitEdit}
            onKeyDown={(e) => {
              if (isImeComposing(e)) return;
              if (e.key === "Enter") commitEdit();
              if (e.key === "Escape") {
                setEditValue(title);
                setIsEditing(false);
              }
            }}
          />
        ) : (
          <div className={styles.chatTitleHeading}>
            <h1 ref={titleRef} className={styles.chatTitleText} title={title}>
              {title ? (
                <SharedElement
                  as="span"
                  id={`thread-title:${title}`}
                  activeKey={title}
                >
                  {title}
                </SharedElement>
              ) : (
                title
              )}
            </h1>
            <SessionShareMark
              contributed={session.contributed}
              owned={session.owned}
            />
            <TeamChatBadge show={isTeam} />
            <RemoteExpertHint agent={agent} />
            {session.pinned ? (
              <Pin
                size={13}
                strokeWidth={2}
                className={styles.chatTitlePinMark}
                aria-hidden
              />
            ) : null}
          </div>
        )}
      </div>
      <div className={styles.chatTitleActions}>
        {workspaceChip}
        {onOpenSolo ? (
          <button
            type="button"
            className={styles.chatTitleEditBtn}
            onClick={onOpenSolo}
            aria-label={t("solo.openSolo")}
            title={t("solo.openSolo")}
          >
            <PanelsTopLeft size={14} strokeWidth={2} aria-hidden />
          </button>
        ) : null}
        <button
          type="button"
          className={styles.chatTitleEditBtn}
          onClick={() => setIsEditing(true)}
          onPointerDown={(event) => {
            // 避免失焦解除禁用后，同一次点击又重新打开编辑。
            if (isEditing) event.preventDefault();
          }}
          disabled={isEditing}
          aria-label={t("common.edit")}
          title={t("common.edit")}
        >
          <Pencil size={14} strokeWidth={2} aria-hidden />
        </button>
        <Dropdown
          menu={{ items: menuItems }}
          trigger={["click"]}
          placement="bottomRight"
        >
          <button
            type="button"
            className={styles.chatTitleEditBtn}
            aria-label={t("common.more", "更多")}
          >
            <MoreVertical size={14} strokeWidth={2} aria-hidden />
          </button>
        </Dropdown>
      </div>
    </div>
  );
}
