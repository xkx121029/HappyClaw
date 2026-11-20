import { Button, Input, Modal } from "antd";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { Mascot } from "../Mascot";
import { useBao } from "./BaoContext";
import styles from "./BaoNamingDialog.module.less";

interface BaoNamingDialogProps {
  open: boolean;
  /** Current name, pre-filled when renaming. */
  initialName?: string;
  /** ``true`` for the first-run prompt, which explains what Bao does. */
  firstRun?: boolean;
  onCancel: () => void;
  onSubmit: (name: string) => void;
}

/**
 * First-run naming (and later renaming) for the mascot. Deliberately small:
 * one field, one mascot, no wizard — the setup flow already has its own steps.
 */
export default function BaoNamingDialog({
  open,
  initialName = "",
  firstRun = false,
  onCancel,
  onSubmit,
}: BaoNamingDialogProps) {
  const { t } = useTranslation();
  const { appearance } = useBao();
  const [value, setValue] = useState(initialName);
  const trimmed = value.trim();

  useEffect(() => {
    if (open) setValue(initialName);
  }, [open, initialName]);

  return (
    <Modal
      open={open}
      title={t(
        firstRun ? "bao.identity.dialogTitle" : "bao.identity.renameTitle",
        firstRun ? "给这位助手起个名字" : "给宝改个名字",
      )}
      onCancel={onCancel}
      destroyOnHidden
      width={420}
      footer={[
        <Button key="cancel" onClick={onCancel}>
          {t("common.cancel", "取消")}
        </Button>,
        <Button
          key="ok"
          type="primary"
          disabled={trimmed.length === 0}
          onClick={() => onSubmit(trimmed)}
        >
          {t("bao.identity.confirm", "就叫这个名字")}
        </Button>,
      ]}
    >
      <div className={styles.body}>
        <Mascot
          size={72}
          {...appearance}
          state={firstRun ? "curious" : "happy"}
          surface="var(--fn-bg-elevated)"
        />
        <p className={styles.hint}>
          {t(
            "bao.identity.dialogHint",
            "它会陪你跨项目派活、处理报错，也在首次配置里带路。名字之后随时能改。",
          )}
        </p>
        <Input
          autoFocus
          maxLength={12}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onPressEnter={() => {
            if (trimmed) onSubmit(trimmed);
          }}
          placeholder={t("bao.identity.namePlaceholder", "例如：小宝")}
          aria-label={t("bao.identity.dialogTitle", "给这位助手起个名字")}
        />
        <span className={styles.limit}>
          {t("bao.identity.limit", "1–12 个字符")}
        </span>
      </div>
    </Modal>
  );
}
