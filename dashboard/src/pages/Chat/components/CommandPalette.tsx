import { useMemo } from "react";
import {
  Bot,
  Brain,
  Cable,
  Cpu,
  DatabaseBackup,
  FileDown,
  Keyboard,
  MessageSquareText,
  Plus,
  Settings,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import PaletteSurface, {
  type PaletteGroup,
  type PaletteItem,
} from "../../../components/CommandPalette/PaletteSurface";
import type { Session } from "../hooks/useSessions";
import { pickRecentSessions } from "../utils/recentSessions";

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
  onOpenShortcuts: () => void;
  /** 打开专家 / 连接器 / 记忆页的导航动作。 */
  onOpenExperts: () => void;
  onOpenConnectors: () => void;
  onOpenMemory: () => void;
  /** 当前会话有可导出消息时传入；未传则隐藏导出动作。 */
  onExportTranscript?: () => void;
}

/**
 * 单人本机命令面板（Ctrl/Cmd + K）。
 *
 * 只做这几件事：新建/导出会话、跳最近会话、切换模型、打开设置与常用页面。
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
  onOpenShortcuts,
  onOpenExperts,
  onOpenConnectors,
  onOpenMemory,
  onExportTranscript,
}: CommandPaletteProps) {
  const { t } = useTranslation();
  // 只用已加载的会话列表，不额外请求；按最近访问而不是侧栏的收藏置顶顺序。
  const recentSessions = useMemo(
    () => pickRecentSessions(sessions),
    [sessions],
  );

  const actionItems = useMemo<PaletteItem[]>(
    () => [
      {
        id: "new-chat",
        label: t("chat.palette.newChat", "新建会话"),
        meta: t("chat.palette.newChatHint", "Ctrl/Cmd + Shift + O"),
        icon: Plus,
        run: onNewChat,
      },
      ...(onExportTranscript
        ? [
            {
              id: "export-transcript",
              label: t(
                "chat.palette.exportTranscript",
                "导出当前会话为 Markdown",
              ),
              meta: t("chat.palette.exportTranscriptHint", "保存为 .md 文件"),
              icon: FileDown,
              run: onExportTranscript,
            },
          ]
        : []),
      {
        id: "settings",
        label: t("chat.palette.openSettings", "打开本机设置"),
        meta: t("chat.palette.openSettingsHint", "Ctrl/Cmd + ,"),
        icon: Settings,
        run: onOpenSettings,
      },
      {
        id: "open-experts",
        label: t("chat.palette.openExperts", "打开专家页"),
        meta: t("chat.palette.openExpertsHint", "启用与配置专家"),
        icon: Bot,
        run: onOpenExperts,
      },
      {
        id: "open-connectors",
        label: t("chat.palette.openConnectors", "打开连接器"),
        meta: t("chat.palette.openConnectorsHint", "管理本机工具接入"),
        icon: Cable,
        run: onOpenConnectors,
      },
      {
        id: "open-memory",
        label: t("chat.palette.openMemory", "打开记忆库"),
        meta: t("chat.palette.openMemoryHint", "查看长期记忆"),
        icon: Brain,
        run: onOpenMemory,
      },
      {
        id: "backup",
        label: t("chat.palette.backup", "本机数据备份与恢复"),
        meta: t("chat.palette.backupHint", "导出 / 导入"),
        icon: DatabaseBackup,
        run: onOpenBackup,
      },
      {
        id: "shortcuts",
        label: t("chat.palette.shortcuts", "键盘快捷键"),
        meta: t("chat.palette.shortcutsHint", "Ctrl/Cmd + /"),
        icon: Keyboard,
        run: onOpenShortcuts,
      },
    ],
    [
      onExportTranscript,
      onNewChat,
      onOpenBackup,
      onOpenConnectors,
      onOpenExperts,
      onOpenMemory,
      onOpenSettings,
      onOpenShortcuts,
      t,
    ],
  );

  const groups = useMemo<PaletteGroup[]>(() => {
    const modelItems: PaletteItem[] = modelsReady
      ? models.map((model) => ({
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

    const sessionItems: PaletteItem[] = recentSessions.map((session) => ({
      id: `session:${session.id}`,
      label: session.name,
      meta: session.pinned
        ? t("chat.palette.pinned", "已收藏")
        : t("chat.palette.session", "会话"),
      icon: MessageSquareText,
      run: () => onSelectSession(session.id),
    }));

    return [
      { kind: "action", label: t("chat.palette.groupActions", "操作"), items: actionItems },
      ...(modelItems.length > 0
        ? [{ kind: "model", label: t("chat.palette.groupModels", "模型"), items: modelItems }]
        : []),
      ...(sessionItems.length > 0
        ? [
            {
              kind: "session",
              label: t("chat.palette.groupSessions", {
                total: recentSessions.length,
                defaultValue: "最近 {{total}} 条会话",
              }),
              items: sessionItems,
            },
          ]
        : []),
    ];
  }, [
    actionItems,
    currentModel,
    models,
    modelsReady,
    onSelectModel,
    onSelectSession,
    recentSessions,
    t,
  ]);

  // 空结果时列表里没有可选行，键盘仍要能落到「新建会话 / 打开设置」上，
  // 否则 Enter 变成了死键。
  const emptyActions = useMemo(
    () => actionItems.filter((item) => item.id === "new-chat" || item.id === "settings"),
    [actionItems],
  );

  return (
    <PaletteSurface
      open={open}
      onClose={onClose}
      label={t("chat.palette.placeholder", "搜索会话、切换模型，或输入命令…")}
      placeholder={t(
        "chat.palette.placeholder",
        "搜索会话、切换模型，或输入命令…",
      )}
      groups={groups}
      emptyText={t("chat.palette.noResults", "没有匹配项，换个关键词试试。")}
      emptyActions={emptyActions}
      footerHint={t("chat.palette.footer", "↑↓ 选择 · ↵ 执行 · Esc 关闭")}
      footerNote={t("chat.palette.localOnly", "仅本机")}
    />
  );
}
