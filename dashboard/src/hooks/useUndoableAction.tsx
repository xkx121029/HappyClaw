import { useCallback, useEffect, useRef } from "react";
import { App } from "antd";
import { useTranslation } from "react-i18next";

const UNDO_WINDOW_MS = 5000;

/**
 * Run a destructive action with a 5-second undo window.
 *
 * Today every delete in the app is final: there is no trash, and the dialogs
 * only warn that it cannot be undone. For a single-user workspace that is a
 * real data-loss path (a mis-click removes a conversation for good).
 *
 * `onCommit` runs immediately (the UI must reflect the deletion), and
 * `onUndo` restores it. The undo toast is the only user-facing surface, so it
 * carries the object name to make the action identifiable.
 */
export function useUndoableAction() {
  const { message } = App.useApp();
  const { t } = useTranslation();
  const timers = useRef(new Map<string, number>());

  useEffect(() => {
    const pending = timers.current;
    return () => {
      for (const id of pending.values()) window.clearTimeout(id);
      pending.clear();
    };
  }, []);

  return useCallback(
    ({
      key,
      label,
      onCommit,
      onUndo,
    }: {
      key: string;
      /** Human-readable object name, e.g. the conversation title. */
      label: string;
      onCommit: () => void | Promise<void>;
      onUndo: () => void | Promise<void>;
    }) => {
      void onCommit();

      const hide = (id: string) => {
        message.destroy(id);
        timers.current.delete(id);
      };

      const timer = window.setTimeout(() => {
        hide(key);
      }, UNDO_WINDOW_MS);
      timers.current.set(key, timer);

      message.open({
        key,
        type: "success",
        duration: UNDO_WINDOW_MS / 1000,
        content: (
          <span>
            {t("common.deletedWithUndo", "已删除「{{name}}」", { name: label })}
          </span>
        ),
        onClick: () => {
          const pending = timers.current.get(key);
          if (pending !== undefined) window.clearTimeout(pending);
          hide(key);
          void onUndo();
          message.success(t("common.restored", "已恢复"));
        },
      });
    },
    [message, t],
  );
}
