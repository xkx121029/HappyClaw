import { useTranslation } from "react-i18next";

import { Mascot } from "../Mascot";
import OctopSpinner from "../OctopSpinner";
import styles from "./BrandLoading.module.less";

interface BrandLoadingProps {
  /** Status line beside the arc. Defaults to the shared loading label. */
  label?: string;
  /** Cover the viewport. Route fallbacks fill their parent instead. */
  viewport?: boolean;
}

/**
 * Full-page wait: the live mascot above the shared arc and a status line.
 * ``idle`` is used because the engine's ``loading`` morph is a whirl overlay
 * that drops the body, and ``waking`` ends on a wink that reads as a damaged
 * silhouette at small sizes.
 */
export default function BrandLoading({ label, viewport }: BrandLoadingProps) {
  const { t } = useTranslation();

  return (
    <div
      className={viewport ? `${styles.host} ${styles.viewport}` : styles.host}
      role="status"
      aria-live="polite"
    >
      <div className={styles.stack}>
        <div className={styles.brand}>
          <Mascot
            size={120}
            state="idle"
            surface="var(--fn-bg-layout)"
            label="HappyClaw"
          />
          <span className={styles.brandName}>HappyClaw</span>
        </div>
        <p className={styles.status}>
          <OctopSpinner />
          <span>{label ?? t("common.loading")}</span>
        </p>
      </div>
    </div>
  );
}
