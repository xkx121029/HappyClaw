/**
 * Quota inputs for the resource-policy form: a token count with quick presets
 * and an agent-count limit with the same preset affordance.
 */

import { InputNumber } from "antd";
import cx from "classnames";
import { useTranslation } from "react-i18next";

import styles from "./index.module.less";

/** Common quotas admins pick — values are absolute token counts. */
const TOKEN_QUOTA_PRESETS = [
  1_000_000, 5_000_000, 10_000_000, 50_000_000, 100_000_000,
] as const;

const MAX_AGENTS_PRESETS = [1, 3, 5, 10, 20] as const;

function formatMillionsLabel(tokens: number): string {
  const millions = tokens / 1_000_000;
  if (Number.isInteger(millions)) return String(millions);
  return millions.toFixed(2).replace(/\.?0+$/, "");
}

function formatTokenQuotaExact(tokens: number): string {
  return tokens.toLocaleString("en-US");
}

export interface TokenQuotaInputProps {
  value?: number | null;
  onChange?: (value: number | null) => void;
}

export function TokenQuotaInput({ value, onChange }: TokenQuotaInputProps) {
  const { t } = useTranslation();
  const numeric =
    typeof value === "number" && Number.isFinite(value) ? value : null;

  return (
    <div className={styles.tokenQuotaField}>
      <InputNumber
        value={numeric ?? undefined}
        onChange={(next) => onChange?.(typeof next === "number" ? next : null)}
        min={0}
        step={1_000_000}
        style={{ width: "100%" }}
        placeholder={t("adminUsers.policyTokenQuotaPlaceholder")}
        formatter={(raw) =>
          `${raw ?? ""}`.replace(/\B(?=(\d{3})+(?!\d))/g, ",")
        }
        parser={(raw) => {
          const cleaned = (raw ?? "").replace(/,/g, "");
          if (!cleaned) return undefined as unknown as number;
          return Number(cleaned);
        }}
      />
      <div className={styles.tokenQuotaPresets} role="group">
        <span className={styles.tokenQuotaPresetsLabel}>
          {t("adminUsers.policyTokenQuotaPresets")}
        </span>
        {TOKEN_QUOTA_PRESETS.map((preset) => {
          const selected = numeric === preset;
          return (
            <button
              key={preset}
              type="button"
              className={cx(
                styles.tokenQuotaPreset,
                selected && styles.tokenQuotaPresetActive,
              )}
              onClick={() => onChange?.(preset)}
            >
              {t("adminUsers.policyTokenQuotaPreset", {
                millions: formatMillionsLabel(preset),
              })}
            </button>
          );
        })}
      </div>
      {numeric != null && numeric > 0 ? (
        <div className={styles.tokenQuotaPreview}>
          {t("adminUsers.policyTokenQuotaPreview", {
            millions: formatMillionsLabel(numeric),
            exact: formatTokenQuotaExact(numeric),
          })}
        </div>
      ) : null}
    </div>
  );
}

export interface MaxAgentsInputProps {
  value?: number | null;
  onChange?: (value: number | null) => void;
}

export function MaxAgentsInput({ value, onChange }: MaxAgentsInputProps) {
  const { t } = useTranslation();
  const numeric =
    typeof value === "number" && Number.isFinite(value) ? value : null;

  return (
    <div className={styles.tokenQuotaField}>
      <InputNumber
        value={numeric ?? undefined}
        onChange={(next) => onChange?.(typeof next === "number" ? next : null)}
        min={0}
        step={1}
        style={{ width: "100%" }}
        placeholder={t("adminUsers.policyMaxAgentsPlaceholder")}
      />
      <div className={styles.tokenQuotaPresets} role="group">
        <span className={styles.tokenQuotaPresetsLabel}>
          {t("common.tokenCountPresets")}
        </span>
        {MAX_AGENTS_PRESETS.map((preset) => {
          const selected = numeric === preset;
          return (
            <button
              key={preset}
              type="button"
              className={cx(
                styles.tokenQuotaPreset,
                selected && styles.tokenQuotaPresetActive,
              )}
              onClick={() => onChange?.(preset)}
            >
              {preset}
            </button>
          );
        })}
      </div>
    </div>
  );
}
