import { useTranslation } from "react-i18next";
import { Drawer, Tag } from "antd";
import { FileCode2 } from "lucide-react";
import { useState, type CSSProperties } from "react";
import cx from "classnames";
import type { SoloActivityItem } from "./SoloActivityFeed";
import styles from "../solo.module.less";

interface SoloDiffDrawerProps {
  item: SoloActivityItem | null;
  onClose: () => void;
  onOpenFile: (path: string) => void;
}

function fileName(path: string): string {
  return path.replace(/\/+$/, "").split("/").pop() || path;
}

/**
 * 文件改动只读视图。
 *
 * agent 已经把改动写进磁盘，这里只展示它能拿到的 diff，不提供「应用/回退」，
 * 避免做出看起来能撤销、实际撤销不了的按钮。要改内容请到编辑器里手动改并保存。
 */
export default function SoloDiffDrawer({
  item,
  onClose,
  onOpenFile,
}: SoloDiffDrawerProps) {
  const { t } = useTranslation();
  const [wrap, setWrap] = useState(false);
  const lines = item?.diff?.lines ?? [];
  const path = item?.filePaths[0] ?? item?.target ?? "";
  const open = item !== null;
  const lineStyle: CSSProperties | undefined = wrap
    ? { whiteSpace: "pre-wrap", wordBreak: "break-word" }
    : undefined;

  return (
    <Drawer
      open={open}
      onClose={onClose}
      width={520}
      destroyOnClose
      rootClassName={styles.diffDrawerRoot}
      title={
        <span className={styles.diffTitle}>
          <FileCode2 size={15} />
          {path ? fileName(path) : t("solo.diffTitle")}
          {item?.diff ? (
            <>
              <span className={styles.diffTitleAdd}>+{item.diff.added}</span>
              <span className={styles.diffTitleDel}>−{item.diff.removed}</span>
            </>
          ) : null}
          <Tag className={styles.diffReadOnlyTag}>{t("solo.diffReadOnlyTag")}</Tag>
        </span>
      }
      footer={
        <div className={styles.diffFooter}>
          <button
            type="button"
            className={styles.pact}
            onClick={() => setWrap((value) => !value)}
          >
            {wrap ? t("solo.diffNoWrap") : t("solo.diffWrap")}
          </button>
          <span className={styles.diffFooterSpacer} />
          <button type="button" className={styles.pact} onClick={onClose}>
            {t("solo.close")}
          </button>
          <button
            type="button"
            className={styles.pact}
            disabled={!path}
            onClick={() => {
              if (!path) return;
              onOpenFile(path);
              onClose();
            }}
          >
            {t("solo.openInEditor")}
          </button>
        </div>
      }
    >
      <div className={styles.diffPane}>
        <div className={styles.diffNotice}>{t("solo.diffReadOnlyNotice")}</div>
        <div className={styles.diffBody}>
          {lines.length === 0 ? (
            <div className={styles.diffEmpty}>{t("solo.diffEmpty")}</div>
          ) : (
            <>
              {path ? (
                <div className={styles.diffFileHead}>
                  <span>{path}</span>
                  {item?.diff ? (
                    <>
                      <span className={styles.diffStatAdd}>+{item.diff.added}</span>
                      <span className={styles.diffStatDel}>−{item.diff.removed}</span>
                    </>
                  ) : null}
                </div>
              ) : null}
              {lines.map((line, index) => (
                <div
                  key={`${index}-${line.type}`}
                  className={cx(
                    styles.diffLine,
                    line.type === "add" && styles.diffLineAdd,
                    line.type === "del" && styles.diffLineDel,
                  )}
                  style={lineStyle}
                >
                  <span className={styles.diffSign} aria-hidden>
                    {line.type === "add" ? "+" : line.type === "del" ? "−" : " "}
                  </span>
                  <span className={styles.diffText}>{line.text || " "}</span>
                </div>
              ))}
            </>
          )}
        </div>
      </div>
    </Drawer>
  );
}
