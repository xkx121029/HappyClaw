import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { Segmented } from "antd";
import {
  AlertTriangle,
  CheckCircle,
  FileJson,
  Info,
  RefreshCw,
  XCircle,
} from "lucide-react";
import cx from "classnames";
import { updateApi, ReleaseCheckResult } from "../../../api/modules/update";
import { formatBytes } from "../../../utils/embeddingDownload";
import styles from "./UpdateConfig.module.less";

type Channel = "stable" | "beta";

interface ReleaseFeedPanelProps {
  /** Running build version; the backend falls back to it when omitted. */
  currentVersion?: string | null;
}

/**
 * Read-only release manifest check. Unlike the upgrade panel above it never
 * downloads or installs anything: it shows what the published manifest says
 * and explains why a check failed.
 */
export default function ReleaseFeedPanel({
  currentVersion,
}: ReleaseFeedPanelProps) {
  const { t } = useTranslation();
  const [channel, setChannel] = useState<Channel>("stable");
  const [result, setResult] = useState<ReleaseCheckResult | null>(null);
  const [checking, setChecking] = useState(false);
  const [requestFailed, setRequestFailed] = useState(false);

  const handleCheck = useCallback(async () => {
    setChecking(true);
    setRequestFailed(false);
    try {
      const next = await updateApi.checkReleaseFeed({
        currentVersion,
        channel,
      });
      setResult(next);
    } catch {
      setResult(null);
      setRequestFailed(true);
    } finally {
      setChecking(false);
    }
  }, [channel, currentVersion]);

  const errorText = result?.error_code
    ? t(`advancedSettings.update.releaseFeed.errors.${result.error_code}`, {
        defaultValue:
          result.error || t("advancedSettings.update.releaseFeed.networkError"),
      })
    : result?.error || t("advancedSettings.update.releaseFeed.networkError");

  return (
    <section
      className={styles.panel}
      aria-label={t("advancedSettings.update.releaseFeed.title")}
    >
      <div className={styles.panelTitleRow}>
        <span className={styles.panelTitleIcon}>
          <FileJson size={16} />
        </span>
        <h3 className={styles.panelTitle}>
          {t("advancedSettings.update.releaseFeed.title")}
        </h3>
      </div>
      <p className={styles.panelDesc}>
        {t("advancedSettings.update.releaseFeed.description")}
      </p>

      <div className={styles.feedControls}>
        <div className={styles.feedChannel}>
          <span>{t("advancedSettings.update.releaseFeed.channelLabel")}</span>
          <Segmented<Channel>
            size="small"
            value={channel}
            disabled={checking}
            onChange={(value) => setChannel(value)}
            options={[
              {
                label: t("advancedSettings.update.releaseFeed.channelStable"),
                value: "stable",
              },
              {
                label: t("advancedSettings.update.releaseFeed.channelBeta"),
                value: "beta",
              },
            ]}
          />
        </div>
        <button
          type="button"
          className={styles.btnSecondary}
          onClick={() => void handleCheck()}
          disabled={checking}
        >
          <RefreshCw
            size={14}
            className={checking ? styles.spinning : undefined}
          />
          {checking
            ? t("advancedSettings.update.releaseFeed.checking")
            : t("advancedSettings.update.releaseFeed.checkButton")}
        </button>
      </div>

      {requestFailed && (
        <div className={cx(styles.alert, styles.alertError)}>
          <XCircle size={15} />
          <span>{t("advancedSettings.update.releaseFeed.networkError")}</span>
        </div>
      )}

      {!result && !requestFailed && (
        <p className={styles.feedEmpty}>
          {t("advancedSettings.update.releaseFeed.notChecked")}
        </p>
      )}

      {result && (
        <div className={styles.feedResult}>
          {!result.ok ? (
            <div className={cx(styles.alert, styles.alertError)}>
              <XCircle size={15} />
              <span>{errorText}</span>
            </div>
          ) : (
            <>
              <div className={styles.versionGrid}>
                <div className={styles.versionCard}>
                  <span className={styles.versionLabel}>
                    {t("advancedSettings.update.releaseFeed.currentVersion")}
                  </span>
                  <span className={styles.versionValue}>
                    {result.current_version}
                  </span>
                </div>
                <div className={styles.versionCard}>
                  <span className={styles.versionLabel}>
                    {t("advancedSettings.update.releaseFeed.latestVersion")}
                  </span>
                  <span className={styles.versionValue}>
                    {result.latest_version ?? "—"}
                  </span>
                  <div className={styles.versionBadges}>
                    {result.has_update ? (
                      <span className={styles.badge}>
                        {t(
                          "advancedSettings.update.releaseFeed.updateAvailable",
                        )}
                      </span>
                    ) : (
                      <span className={styles.notChecked}>
                        {t("advancedSettings.update.releaseFeed.upToDate")}
                      </span>
                    )}
                  </div>
                </div>
              </div>

              <div className={styles.feedMeta}>
                {result.published_at && (
                  <span>
                    {t("advancedSettings.update.releaseFeed.publishedAt")}:{" "}
                    {result.published_at}
                  </span>
                )}
                {result.source && (
                  <span>
                    {t("advancedSettings.update.releaseFeed.source")}:{" "}
                    {result.source}
                  </span>
                )}
                <span>
                  {t("advancedSettings.update.releaseFeed.channelLabel")}:{" "}
                  {result.channel}
                </span>
              </div>

              {!result.supported && result.minimum_supported_version && (
                <div className={cx(styles.alert, styles.alertWarn)}>
                  <AlertTriangle size={15} />
                  <span>
                    {t("advancedSettings.update.releaseFeed.belowMinimum", {
                      version: result.minimum_supported_version,
                    })}
                  </span>
                </div>
              )}

              {result.stale && (
                <div className={cx(styles.alert, styles.alertWarn)}>
                  <AlertTriangle size={15} />
                  <span>
                    {t("advancedSettings.update.releaseFeed.stale")}
                    {result.error_code ? ` (${errorText})` : ""}
                  </span>
                </div>
              )}

              {result.cached && !result.stale && (
                <div className={cx(styles.alert, styles.alertInfo)}>
                  <Info size={15} />
                  <span>{t("advancedSettings.update.releaseFeed.cached")}</span>
                </div>
              )}

              {result.release_notes && (
                <div>
                  <p className={styles.feedSectionTitle}>
                    {t("advancedSettings.update.releaseFeed.notes")}
                  </p>
                  <pre className={styles.feedNotes}>{result.release_notes}</pre>
                </div>
              )}

              <div>
                <p className={styles.feedSectionTitle}>
                  {t("advancedSettings.update.releaseFeed.artifacts")}
                </p>
                {result.artifacts.length === 0 ? (
                  <p className={styles.feedEmpty}>
                    {t("advancedSettings.update.releaseFeed.noArtifacts")}
                  </p>
                ) : (
                  <div className={styles.feedArtifacts}>
                    {result.artifacts.map((artifact) => (
                      <div
                        className={styles.feedArtifact}
                        key={artifact.filename}
                      >
                        <div>
                          <div className={styles.feedArtifactName}>
                            {artifact.filename}
                          </div>
                          <div className={styles.feedArtifactMeta}>
                            {artifact.platform}/{artifact.arch}
                            {artifact.kind ? ` · ${artifact.kind}` : ""}
                          </div>
                          <div className={styles.feedSha}>
                            SHA256 {artifact.sha256}
                          </div>
                        </div>
                        <div className={styles.feedArtifactMeta}>
                          {formatBytes(artifact.size_bytes)}
                        </div>
                        <div className={styles.feedArtifactLink}>
                          <a
                            href={artifact.url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {t("advancedSettings.update.releaseFeed.download")}
                          </a>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {!result.has_update && (
                <div className={cx(styles.alert, styles.alertSuccess)}>
                  <CheckCircle size={15} />
                  <span>
                    {t("advancedSettings.update.releaseFeed.upToDate")}
                  </span>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </section>
  );
}
