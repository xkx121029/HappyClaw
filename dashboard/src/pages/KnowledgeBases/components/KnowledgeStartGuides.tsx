import { Plus, Settings } from "lucide-react";
import { useTranslation } from "react-i18next";

import { OctopEmptyMascot } from "../../../components/EmptyState";
import StreamSetupGuide from "../../../components/StreamSetupGuide/StreamSetupGuide";
import styles from "../index.module.less";

export interface KnowledgeEnableGuideProps {
  canConfigureKb: boolean;
  onOpenSettings: () => void;
}

/** Shown while the embedding service is unavailable, or to a reader who cannot enable it. */
export function KnowledgeEnableGuide({
  canConfigureKb,
  onOpenSettings,
}: KnowledgeEnableGuideProps) {
  const { t } = useTranslation();
  return (
    <div className={styles.emptyLayout}>
      <StreamSetupGuide
        className={styles.emptyGuide}
        wide
        plain
        icon={<OctopEmptyMascot />}
        title={
          canConfigureKb
            ? t("knowledgeBases.enableGuideTitle")
            : t("knowledgeBases.unavailableTitle")
        }
        description={
          canConfigureKb
            ? t("knowledgeBases.enableGuideDesc")
            : t("knowledgeBases.unavailableDescriptionNonAdmin")
        }
        steps={
          canConfigureKb
            ? [
                {
                  label: t("knowledgeBases.enableGuideStepOpen"),
                  detail: t("knowledgeBases.enableGuideStepOpenDetail"),
                },
                {
                  label: t("knowledgeBases.enableGuideStepToggle"),
                  detail: t("knowledgeBases.enableGuideStepToggleDetail"),
                },
                {
                  label: t("knowledgeBases.enableGuideStepModel"),
                  detail: t("knowledgeBases.enableGuideStepModelDetail"),
                },
              ]
            : []
        }
        primaryAction={
          canConfigureKb
            ? {
                label: t("knowledgeBases.settingsTitle"),
                onClick: onOpenSettings,
                icon: <Settings size={14} />,
              }
            : undefined
        }
      />
    </div>
  );
}

export interface KnowledgeEmptyGuideProps {
  atBaseLimit: boolean;
  onCreate: () => void;
}

/** Shown when the service is ready but the user has no knowledge base yet. */
export function KnowledgeEmptyGuide({
  atBaseLimit,
  onCreate,
}: KnowledgeEmptyGuideProps) {
  const { t } = useTranslation();
  return (
    <div className={styles.emptyLayout}>
      <StreamSetupGuide
        className={styles.emptyGuide}
        wide
        plain
        icon={<OctopEmptyMascot />}
        title={t("knowledgeBases.emptyGuideTitle")}
        description={t("knowledgeBases.emptyGuideDesc")}
        steps={[
          {
            label: t("knowledgeBases.emptyGuideStepWhat"),
            detail: t("knowledgeBases.emptyGuideStepWhatDetail"),
          },
          {
            label: t("knowledgeBases.emptyGuideStepHow"),
            detail: t("knowledgeBases.emptyGuideStepHowDetail"),
          },
          {
            label: t("knowledgeBases.emptyGuideStepShare"),
            detail: t("knowledgeBases.emptyGuideStepShareDetail"),
          },
        ]}
        primaryAction={{
          label: t("knowledgeBases.create"),
          onClick: onCreate,
          icon: <Plus size={14} />,
          disabled: atBaseLimit,
        }}
      />
    </div>
  );
}
