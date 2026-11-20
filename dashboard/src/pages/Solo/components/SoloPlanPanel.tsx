import { useState } from "react";
import { useTranslation } from "react-i18next";
import cx from "classnames";
import {
  Ban,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Circle,
  ListTodo,
  Loader2,
} from "lucide-react";
import type { ChatMessage } from "../../Chat/hooks/useChat";
import {
  collectWriteTodosFromMessages,
  countCompletedTodos,
} from "../../../utils/parseWriteTodos";
import styles from "../solo.module.less";

interface SoloPlanPanelProps {
  messages: ChatMessage[];
  isStreaming: boolean;
}

/**
 * 任务计划：把本轮所有 `write_todos` 合并成一份步骤清单，状态随工具更新实时变化。
 * 和右栏动作时间线分工不同——时间线是「做了什么」，这里是「还剩什么」。
 */
export default function SoloPlanPanel({
  messages,
  isStreaming,
}: SoloPlanPanelProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(true);
  const items = collectWriteTodosFromMessages(messages);

  if (items.length === 0) return null;

  const done = countCompletedTodos(items);
  const headingId = "solo-plan-heading";

  return (
    <section className={styles.planSection}>
      <header className={styles.planHeader}>
        <ListTodo size={13} className={styles.headerIcon} />
        <span className={styles.paneTitle} id={headingId}>
          {t("solo.plan")}
        </span>
        <span className={styles.planProgress}>
          {t("solo.planProgress", { done, total: items.length })}
        </span>
        <span className={styles.headerSpacer} />
        <button
          type="button"
          className={styles.toolIconButton}
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          aria-controls="solo-plan-list"
          aria-label={
            open ? t("solo.collapsePlan") : t("solo.expandPlan")
          }
        >
          {open ? <ChevronDown size={13} /> : <ChevronUp size={13} />}
        </button>
      </header>
      {open ? (
        <ol
          className={styles.planBody}
          id="solo-plan-list"
          aria-labelledby={headingId}
        >
          {items.map((item) => {
            const completed = item.status === "completed";
            const cancelled = item.status === "cancelled";
            const active = item.status === "in_progress";
            return (
              <li
                key={item.id}
                className={cx(
                  styles.planItem,
                  completed && styles.planItemDone,
                  cancelled && styles.planItemCancelled,
                  active && styles.planItemActive,
                )}
              >
                <span
                  className={styles.planIcon}
                  role="img"
                  aria-label={
                    completed
                      ? t("solo.planStatus.completed")
                      : cancelled
                        ? t("solo.planStatus.cancelled")
                        : active
                          ? t("solo.planStatus.inProgress")
                          : t("solo.planStatus.pending")
                  }
                >
                  {completed ? (
                    <CheckCircle2 size={12} className={styles.planIconDone} />
                  ) : cancelled ? (
                    <Ban size={12} />
                  ) : active ? (
                    <Loader2
                      size={12}
                      className={cx(
                        styles.planIconActive,
                        isStreaming && styles.spin,
                      )}
                    />
                  ) : (
                    <Circle size={12} />
                  )}
                </span>
                <span className={styles.planText}>{item.content}</span>
              </li>
            );
          })}
        </ol>
      ) : null}
    </section>
  );
}
