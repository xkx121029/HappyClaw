import { useState } from "react";
import { Checkbox, Input } from "antd";
import { Plus, Trash2, Eye, EyeOff } from "lucide-react";
import { useTranslation } from "react-i18next";
import cx from "classnames";
import { isSensitiveKey } from "../utils";
import styles from "../index.module.less";

export interface Row {
  key: string;
  value: string;
  isNew?: boolean;
}

interface EnvRowProps {
  row: Row;
  idx: number;
  checked: boolean;
  error?: string;
  onToggle: (idx: number) => void;
  onChange: (idx: number, field: "key" | "value", val: string) => void;
  onInsert: (idx: number) => void;
  onRemove: (idx: number) => void;
}

export function EnvRow({
  row,
  idx,
  checked,
  error,
  onToggle,
  onChange,
  onInsert,
  onRemove,
}: EnvRowProps) {
  const { t } = useTranslation();
  const [isValueVisible, setIsValueVisible] = useState(false);
  const isSensitive = isSensitiveKey(row.key);

  return (
    <div className={cx(styles.envRow, checked && styles.envRowSelected)}>
      <Checkbox
        checked={checked}
        onChange={() => onToggle(idx)}
        className={styles.rowCheckbox}
        aria-label={t("environments.selectVariable")}
      />

      <div className={styles.fieldsWrap}>
        <div className={cx(styles.inputGroup, error && styles.inputGroupError)}>
          <span className={styles.inputLabel}>{t("environments.key")}</span>
          <Input
            value={row.key}
            placeholder={t("environments.variableNamePlaceholder")}
            disabled={!row.isNew}
            onChange={(e) => onChange(idx, "key", e.target.value)}
            className={styles.inputField}
            autoFocus={row.isNew}
          />
        </div>

        <div className={styles.inputGroup}>
          <span className={styles.inputLabel}>{t("environments.value")}</span>
          <div className={styles.valueInputWrapper}>
            <Input
              value={row.value}
              placeholder={t("environments.valuePlaceholder")}
              onChange={(e) => onChange(idx, "value", e.target.value)}
              className={styles.inputField}
              type={isSensitive && !isValueVisible ? "password" : "text"}
            />
            {isSensitive && (
              <button
                type="button"
                className={styles.valueToggleBtn}
                onClick={() => setIsValueVisible(!isValueVisible)}
                title={
                  isValueVisible
                    ? t("environments.hideValue")
                    : t("environments.showValue")
                }
                aria-label={
                  isValueVisible
                    ? t("environments.hideValue")
                    : t("environments.showValue")
                }
              >
                {isValueVisible ? <Eye size={16} /> : <EyeOff size={16} />}
              </button>
            )}
          </div>
        </div>
      </div>

      <div className={styles.rowActions}>
        <button
          type="button"
          className={styles.rowIconBtn}
          onClick={() => onInsert(idx)}
          title={t("environments.insertRowBelow")}
          aria-label={t("environments.insertRowBelow")}
        >
          <Plus size={16} />
        </button>
        <button
          type="button"
          className={cx(styles.rowIconBtn, styles.rowIconBtnDanger)}
          onClick={() => onRemove(idx)}
          title={t("environments.deleteRow")}
          aria-label={t("environments.deleteRow")}
        >
          <Trash2 size={16} />
        </button>
      </div>

      {error && <div className={styles.rowError}>{error}</div>}
    </div>
  );
}
