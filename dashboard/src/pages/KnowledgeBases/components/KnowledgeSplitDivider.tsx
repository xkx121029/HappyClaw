import { Tooltip } from "antd";
import type { PointerEvent as ReactPointerEvent } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import cx from "classnames";

import styles from "../index.module.less";

export interface KnowledgeSplitDividerProps {
  listPanelCollapsed: boolean;
  onResizeStart: (event: ReactPointerEvent<HTMLDivElement>) => void;
  onToggle: () => void;
}

/** Draggable divider between the base list and the detail pane. */
export function KnowledgeSplitDivider({
  listPanelCollapsed,
  onResizeStart,
  onToggle,
}: KnowledgeSplitDividerProps) {
  const { t } = useTranslation();
  return (
  <div
    data-split-divider=""
    className={cx(
      styles.splitDivider,
      listPanelCollapsed && styles.splitDividerCollapsed,
    )}
  >
    {!listPanelCollapsed ? (
      <div
        className={styles.resizeHandle}
        role="separator"
        aria-orientation="vertical"
        aria-label={t("knowledgeBases.resizeSidebar")}
        onPointerDown={onResizeStart}
      />
    ) : null}
    <Tooltip
      title={
        listPanelCollapsed
          ? t("knowledgeBases.expandListPanel")
          : t("knowledgeBases.collapseListPanel")
      }
    >
      <button
        type="button"
        className={styles.listPanelEdgeToggle}
        onClick={(event) => {
          event.stopPropagation();
          onToggle();
        }}
        onMouseDown={(event) => event.stopPropagation()}
        aria-label={
          listPanelCollapsed
            ? t("knowledgeBases.expandListPanel")
            : t("knowledgeBases.collapseListPanel")
        }
      >
        {listPanelCollapsed ? (
          <ChevronRight size={14} strokeWidth={2} />
        ) : (
          <ChevronLeft size={14} strokeWidth={2} />
        )}
      </button>
    </Tooltip>
  </div>
  );
}
