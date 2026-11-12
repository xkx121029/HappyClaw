import { useEffect, useMemo, useRef, useState } from "react";
import { Modal } from "antd";
import {
  Cpu,
  DatabaseBackup,
  MessageSquareText,
  Plus,
  Search,
  Settings,
  type LucideIcon,
} from "lucide-react";
import cx from "classnames";
import { useTranslation } from "react-i18next";

import styles from "../index.module.less";
import type { Session } from "../hooks/useSessions";

export interface PaletteModelOption {
  value: string;
  label: string;
  provider: string;
}

interface CommandPaletteProps {
  open: boolean;
  sessions: Session[];
  models: PaletteModelOption[];
  modelsReady: boolean;
  currentModel: string | null;
  onClose: () => void;
  onNewChat: () => void;
  onSelectSession: (id: string) => void;
  onSelectModel: (value: string | null) => void;
  onOpenSettings: () => void;
  onOpenBackup: () => void;
}

interface PaletteCommand {
  kind: "action" | "model" | "session";
  id: string;
  label: string;
  meta?: string;
  icon: LucideIcon;
  run: () => void;
}

const MAX_SESSIONS = 8;

/**
 * 单人本机命令面板（Ctrl/Cmd + K）。
 *
 * 只做四件事：新建会话、跳到最近会话、切换模型、打开本机设置。
 * 不引入全局状态层，数据全部由聊天页现有 hooks 提供。
 */
export default function CommandPalette({
  open,
  sessions,
  models,
  modelsReady,
  currentModel,
  onClose,
  onNewChat,
  onSelectSession,
  onSelectModel,
  onOpenSettings,
  onOpenBackup,
}: CommandPaletteProps) {
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setActiveIndex(0);
    const timer = window.setTimeout(() => inputRef.current?.focus(), 30);
    return () => window.clearTimeout(timer);
  }, [open]);

  const commands = useMemo<PaletteCommand[]>(() => {
    const actions: PaletteCommand[] = [
      {
        kind: "action",
        id: "new-chat",
        label: t("chat.palette.newChat", "新建会话"),
        meta: t("chat.palette.newChatHint", "Ctrl/Cmd + Shift + O"),
        icon: Plus,
        run: onNewChat,
      },
      {
        kind: "action",
        id: "settings",
        label: t("chat.palette.openSettings", "打开本机设置"),
        meta: t("chat.palette.openSettingsHint", "Ctrl/Cmd + ,"),
        icon: Settings,
        run: onOpenSettings,
      },
      {
        kind: "action",
        id: "backup",
        label: t("chat.palette.backup", "本机数据备份与恢复"),
        meta: t("chat.palette.backupHint", "导出 / 导入"),
        icon: DatabaseBackup,
        run: onOpenBackup,
      },
    ];

    const modelCommands: PaletteCommand[] = modelsReady
      ? models.map((model) => ({
          kind: "model" as const,
          id: `model:${model.value}`,
          label: model.label,
          meta:
            model.value === currentModel
              ? t("chat.palette.currentModel", "当前模型")
              : model.provider,
          icon: Cpu,
          run: () => onSelectModel(model.value),
        }))
      : [];

    const sessionCommands: PaletteCommand[] = sessions
      .slice(0, MAX_SESSIONS)
      .map((session) => ({
        kind: "session" as const,
        id: `session:${session.id}`,
        label: session.name,
        meta: session.pinned
          ? t("chat.palette.pinned", "已收藏")
          : t("chat.palette.session", "会话"),
        icon: MessageSquareText,
        run: () => onSelectSession(session.id),
      }));

    return [...actions, ...modelCommands, ...sessionCommands];
  }, [
    currentModel,
    models,
    modelsReady,
    onNewChat,
    onOpenBackup,
    onOpenSettings,
    onSelectModel,
    onSelectSession,
    sessions,
    t,
  ]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return commands;
    return commands.filter(
      (cmd) =>
        cmd.label.toLowerCase().includes(q) ||
        cmd.meta?.toLowerCase().includes(q),
    );
  }, [commands, query]);

  // 空结果时列表里没有可选行，键盘仍要能落到「新建会话 / 打开设置」上，
  // 否则 Enter 变成了死键。把这两个动作接进同一套上下键选择。
  const noResults = filtered.length === 0;
  const emptyActions = useMemo(
    () => commands.filter((cmd) => cmd.id === "new-chat" || cmd.id === "settings"),
    [commands],
  );
  const navigable = noResults ? emptyActions : filtered;

  useEffect(() => {
    setActiveIndex(0);
  }, [query]);

  const runCommand = (cmd: PaletteCommand | undefined) => {
    if (!cmd) return;
    onClose();
    // 让面板先关闭，再执行导航/切换，避免 Modal 焦点抢回输入框。
    window.setTimeout(cmd.run, 0);
  };

  const handleKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActiveIndex((index) => Math.min(index + 1, navigable.length - 1));
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      setActiveIndex((index) => Math.max(index - 1, 0));
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      runCommand(navigable[activeIndex]);
    }
  };

  let lastKind: PaletteCommand["kind"] | null = null;
  let flatIndex = -1;

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      closable={false}
      width={620}
      centered
      destroyOnHidden
      className={styles.commandPaletteModal}
      styles={{ body: { padding: 0 } }}
    >
      <div className={styles.commandPalette}>
        <div className={styles.cpSearch}>
          <Search size={16} strokeWidth={1.8} aria-hidden />
          <input
            ref={inputRef}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={t(
              "chat.palette.placeholder",
              "搜索会话、切换模型，或输入命令…",
            )}
            aria-label={t("chat.palette.placeholder", "搜索会话、切换模型，或输入命令…")}
            spellCheck={false}
          />
          <kbd className={styles.cpKbd}>Esc</kbd>
        </div>

        <div className={styles.cpList} role="listbox">
          {filtered.length === 0 ? (
            <div className={styles.cpEmpty}>
              <p className={styles.cpEmptyText}>
                {t("chat.palette.noResults", "没有匹配项，换个关键词试试。")}
              </p>
              <div className={styles.cpEmptyActions}>
                {emptyActions.map((cmd, index) => {
                  const Icon = cmd.icon;
                  return (
                    <button
                      key={cmd.id}
                      type="button"
                      className={cx(
                        styles.cpEmptyAction,
                        index === activeIndex && styles.cpEmptyActionActive,
                      )}
                      onMouseEnter={() => setActiveIndex(index)}
                      onClick={() => runCommand(cmd)}
                    >
                      <Icon size={14} strokeWidth={1.8} aria-hidden />
                      {cmd.label}
                    </button>
                  );
                })}
              </div>
            </div>
          ) : (
            filtered.map((cmd) => {
              flatIndex += 1;
              const index = flatIndex;
              const showGroup = cmd.kind !== lastKind;
              lastKind = cmd.kind;
              const Icon = cmd.icon;
              return (
                <div key={cmd.id}>
                  {showGroup ? (
                    <div className={styles.cpGroup}>
                      {cmd.kind === "action"
                        ? t("chat.palette.groupActions", "操作")
                        : cmd.kind === "model"
                          ? t("chat.palette.groupModels", "模型")
                          : t("chat.palette.groupSessions", "最近会话")}
                    </div>
                  ) : null}
                  <button
                    type="button"
                    role="option"
                    aria-selected={index === activeIndex}
                    className={cx(
                      styles.cpItem,
                      index === activeIndex && styles.cpItemActive,
                    )}
                    onMouseEnter={() => setActiveIndex(index)}
                    onClick={() => runCommand(cmd)}
                  >
                    <Icon size={16} strokeWidth={1.8} aria-hidden />
                    <span className={styles.cpLabel}>{cmd.label}</span>
                    {cmd.meta ? (
                      <span className={styles.cpMeta}>{cmd.meta}</span>
                    ) : null}
                  </button>
                </div>
              );
            })
          )}
        </div>

        <div className={styles.cpFooter}>
          <span>{t("chat.palette.footer", "↑↓ 选择 · ↵ 执行 · Esc 关闭")}</span>
          <span>{t("chat.palette.localOnly", "仅本机")}</span>
        </div>
      </div>
    </Modal>
  );
}
