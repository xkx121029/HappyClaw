import { Typography } from "antd";
import { Check, X } from "lucide-react";

import styles from "../index.module.less";

export function ReadinessRow({
  label,
  ok,
  okText,
  failText,
}: {
  label: string;
  ok: boolean;
  okText: string;
  failText: string;
}) {
  return (
    <div className={styles.onnxReadinessRow}>
      <span className={styles.onnxReadinessLabel}>{label}</span>
      {ok ? (
        <Check size={13} color="var(--fn-color-success)" />
      ) : (
        <X size={13} color="var(--fn-color-warning)" />
      )}
      <Typography.Text type={ok ? "success" : "warning"}>
        {ok ? okText : failText}
      </Typography.Text>
    </div>
  );
}
