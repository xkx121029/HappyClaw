import { Modal } from "antd";
import { useTranslation } from "react-i18next";

import {
  COMPOSER_SHORTCUTS,
  SHELL_SHORTCUTS,
  formatShortcutKeys,
  isMacUser,
  type ShortcutRow,
} from "./shortcutCatalog";
import styles from "./ShortcutSheet.module.less";

interface ShortcutSheetProps {
  open: boolean;
  onClose: () => void;
  /** Show the composer section; true inside a conversation. */
  includeComposer?: boolean;
}

/** Global shortcut cheatsheet (`?`). Pure list, no animation. */
export default function ShortcutSheet({
  open,
  onClose,
  includeComposer = true,
}: ShortcutSheetProps) {
  const { t } = useTranslation();
  const isMac = isMacUser();

  const renderGroup = (rows: ShortcutRow[]) => (
    <ul className={styles.list}>
      {rows.map((row) => (
        <li key={row.id} className={styles.row}>
          <span className={styles.label}>{t(row.labelKey, row.label)}</span>
          <kbd className={styles.keys}>
            {formatShortcutKeys(row.keys, isMac)}
          </kbd>
        </li>
      ))}
    </ul>
  );

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      centered
      width={440}
      title={t("shortcuts.title", "键盘快捷键")}
    >
      <div className={styles.groupTitle}>
        {t("shortcuts.groupGlobal", "全局")}
      </div>
      {renderGroup(SHELL_SHORTCUTS)}
      {includeComposer ? (
        <>
          <div className={styles.groupTitle}>
            {t("shortcuts.groupComposer", "对话")}
          </div>
          {renderGroup(COMPOSER_SHORTCUTS)}
        </>
      ) : null}
      <p className={styles.note}>
        {t(
          "shortcuts.note",
          "桌面端 Enter 发送、Shift + Enter 换行；移动端 Enter 换行。随时按 ? 重新打开本页。",
        )}
      </p>
    </Modal>
  );
}
