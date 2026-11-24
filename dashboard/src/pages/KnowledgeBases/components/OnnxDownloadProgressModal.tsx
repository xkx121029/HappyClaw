import { Button, Modal, Progress, Typography } from "antd";
import { useTranslation } from "react-i18next";

import styles from "../index.module.less";

export interface OnnxDownloadProgressModalProps {
  downloadProgressOpen: boolean;
  downloadProgress: number;
  downloadProgressLabel: string;
  downloadProgressModel: string;
  dismissDownloadProgressToBackground: () => void;
}

export function OnnxDownloadProgressModal({
  downloadProgressOpen,
  downloadProgress,
  downloadProgressLabel,
  downloadProgressModel,
  dismissDownloadProgressToBackground,
}: OnnxDownloadProgressModalProps) {
  const { t } = useTranslation();
  return (
      <Modal
        open={downloadProgressOpen}
        title={t("models.localDownloadProgressTitle")}
        onCancel={dismissDownloadProgressToBackground}
        closable
        maskClosable
        destroyOnHidden={false}
        // Above modal.confirm (zIndexPopupBase + CONTAINER_MAX_OFFSET = 2000)
        // so this dialog is not covered while the confirm is closing.
        zIndex={2100}
        footer={
          <Button onClick={dismissDownloadProgressToBackground}>
            {t("models.localDownloadContinueBackground")}
          </Button>
        }
      >
        <div className={styles.downloadProgressLabel}>
          {downloadProgressLabel || downloadProgressModel}
        </div>
        <Progress percent={downloadProgress} status="active" />
        <Typography.Text type="secondary" className={styles.settingsHint}>
          {t("models.localDownloadBackgroundHint")}
        </Typography.Text>
      </Modal>
  );
}
