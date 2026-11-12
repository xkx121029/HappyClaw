import { Modal } from "antd";
import { useTranslation } from "react-i18next";

import { isMacPlatform } from "../../../utils/railShortcuts";
import { CHAT_SHORTCUTS, formatShortcut } from "../utils/chatShortcuts";
import styles from "../index.module.less";

interface ShortcutHelpDialogProps {
  open: boolean;
  onClose: () => void;
}

/** 快捷键帮助（Ctrl/Cmd + /）。纯清单，不做演示动画。 */
export default function ShortcutHelpDialog({
  open,
  onClose,
}: ShortcutHelpDialogProps) {
  const { t } = useTranslation();
  const isMac = isMacPlatform();

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      centered
      width={420}
      title={t("chat.shortcuts.title")}
      className={styles.shortcutModal}
    >
      <ul className={styles.shortcutList}>
        {CHAT_SHORTCUTS.map((row) => (
          <li key={row.id} className={styles.shortcutRow}>
            <span className={styles.shortcutLabel}>{t(row.labelKey)}</span>
            <kbd className={styles.shortcutKeys}>
              {formatShortcut(row.keys, isMac)}
            </kbd>
          </li>
        ))}
      </ul>
      <p className={styles.shortcutNote}>{t("chat.shortcuts.note")}</p>
    </Modal>
  );
}
