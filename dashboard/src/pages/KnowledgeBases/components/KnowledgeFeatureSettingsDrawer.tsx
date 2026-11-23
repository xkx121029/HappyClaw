import type { Dispatch, SetStateAction } from "react";
import {
  Alert,
  Button,
  Drawer,
  Radio,
  Select,
  Spin,
  Switch,
  Typography,
} from "antd";
import { Download } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import cx from "classnames";

import type {
  KnowledgeCapability,
  KnowledgeOnnxModel,
} from "../../../api/modules/knowledgeBases";
import { formatSizeGb } from "../../../utils/embeddingDownload";
import styles from "../index.module.less";
import { ReadinessRow } from "./ReadinessRow";

export type KnowledgeRemoteProvider = {
  provider_id: string;
  provider_name: string;
  models: { id: string; name: string }[];
};

export type OnnxProbeResult = {
  ok: boolean;
  latency_ms?: number | null;
  dim?: number | null;
  error?: string | null;
};

export interface KnowledgeFeatureSettingsDrawerProps {
  featureModalOpen: boolean;
  setFeatureModalOpen: Dispatch<SetStateAction<boolean>>;
  isMobile: boolean;
  featureSaving: boolean;
  featureEnabledDraft: boolean;
  setFeatureEnabledDraft: Dispatch<SetStateAction<boolean>>;
  featureModel: string | undefined;
  setFeatureModel: Dispatch<SetStateAction<string | undefined>>;
  featureBackend: "onnx" | "remote";
  setFeatureBackend: Dispatch<SetStateAction<"onnx" | "remote">>;
  featureProviderId: string | undefined;
  setFeatureProviderId: Dispatch<SetStateAction<string | undefined>>;
  ocrEnabledDraft: boolean;
  setOcrEnabledDraft: Dispatch<SetStateAction<boolean>>;
  ocrBackend: "onnx" | "remote";
  setOcrBackend: Dispatch<SetStateAction<"onnx" | "remote">>;
  ocrModel: string | undefined;
  setOcrModel: Dispatch<SetStateAction<string | undefined>>;
  ocrProviderId: string | undefined;
  setOcrProviderId: Dispatch<SetStateAction<string | undefined>>;
  ocrRemoteProviders: KnowledgeRemoteProvider[];
  remoteProviders: KnowledgeRemoteProvider[];
  catalog: KnowledgeOnnxModel[];
  featureOptionsLoading: boolean;
  onnxDownloading: boolean;
  downloadProgressModel: string;
  onnxExpanded: boolean;
  onnxExpanding: boolean;
  loadEmbeddingOptions: (allOnnx?: boolean) => Promise<unknown>;
  startOnnxDownload: (modelId: string) => Promise<void>;
  onnxProbe: OnnxProbeResult | null;
  onnxProbing: boolean;
  runOnnxProbe: () => Promise<void>;
  capability: KnowledgeCapability | null;
  saveFeature: () => Promise<void>;
}

export function KnowledgeFeatureSettingsDrawer({
  featureModalOpen,
  setFeatureModalOpen,
  isMobile,
  featureSaving,
  featureEnabledDraft,
  setFeatureEnabledDraft,
  featureModel,
  setFeatureModel,
  featureBackend,
  setFeatureBackend,
  featureProviderId,
  setFeatureProviderId,
  ocrEnabledDraft,
  setOcrEnabledDraft,
  ocrBackend,
  setOcrBackend,
  ocrModel,
  setOcrModel,
  ocrProviderId,
  setOcrProviderId,
  ocrRemoteProviders,
  remoteProviders,
  catalog,
  featureOptionsLoading,
  onnxDownloading,
  downloadProgressModel,
  onnxExpanded,
  onnxExpanding,
  loadEmbeddingOptions,
  startOnnxDownload,
  onnxProbe,
  onnxProbing,
  runOnnxProbe,
  capability,
  saveFeature,
}: KnowledgeFeatureSettingsDrawerProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  return (
      <Drawer
        title={t("knowledgeBases.settingsTitle")}
        placement="right"
        width={isMobile ? "100%" : 520}
        // Below antd's default dialog layer (1000) so confirm/progress modals
        // opened from inside this drawer always stack above it.
        zIndex={990}
        open={featureModalOpen}
        onClose={() => setFeatureModalOpen(false)}
        destroyOnHidden
        footer={
          <div className={styles.drawerFooter}>
            <Button onClick={() => setFeatureModalOpen(false)}>
              {t("common.cancel")}
            </Button>
            <Button
              type="primary"
              loading={featureSaving}
              disabled={
                featureEnabledDraft
                  ? !featureModel ||
                    (featureBackend === "remote" && !featureProviderId) ||
                    (ocrEnabledDraft &&
                      ocrBackend === "remote" &&
                      (!ocrProviderId || !ocrModel)) ||
                    (featureBackend === "onnx" &&
                      !catalog.find((model) => model.id === featureModel)
                        ?.downloaded) ||
                    featureOptionsLoading ||
                    onnxDownloading
                  : false
              }
              onClick={() => void saveFeature()}
            >
              {t("common.save")}
            </Button>
          </div>
        }
      >
        <div className={styles.formOptions}>
          <div className={styles.formOptionRow}>
            <div className={styles.formOptionCopy}>
              <span className={styles.switchLabel}>
                {t("knowledgeBases.settingsOpen")}
              </span>
              <span className={styles.formOptionHint}>
                {t("knowledgeBases.settingsLead")}
              </span>
            </div>
            <Switch
              size="small"
              checked={featureEnabledDraft}
              onChange={setFeatureEnabledDraft}
            />
          </div>
        </div>

        {featureEnabledDraft ? (
          <Spin spinning={featureOptionsLoading}>
            <div className={styles.settingsBody}>
              <div className={styles.settingsFieldLabel}>
                {t("knowledgeBases.selectModel")}
              </div>
              <Radio.Group
                className={styles.featureBackend}
                value={featureBackend}
                onChange={(event) => {
                  setFeatureBackend(event.target.value);
                  setFeatureModel(undefined);
                }}
              >
                <Radio value="onnx">{t("knowledgeBases.localOnnx")}</Radio>
                <Radio value="remote">
                  {t("knowledgeBases.remoteEmbedding")}
                </Radio>
              </Radio.Group>
              {featureBackend === "remote" ? (
                <div className={styles.featureFields}>
                  <Select
                    value={featureProviderId}
                    onChange={(id) => {
                      setFeatureProviderId(id);
                      setFeatureModel(undefined);
                    }}
                    placeholder={t("knowledgeBases.selectProvider")}
                    options={remoteProviders.map((provider) => ({
                      value: provider.provider_id,
                      label: provider.provider_name,
                    }))}
                    notFoundContent={t("knowledgeBases.noProviders")}
                  />
                  <div className={styles.onnxModelList}>
                    {(
                      remoteProviders.find(
                        (provider) =>
                          provider.provider_id === featureProviderId,
                      )?.models ?? []
                    ).map((model) => {
                      const selected = featureModel === model.id;
                      return (
                        <button
                          key={model.id}
                          type="button"
                          className={cx(
                            styles.onnxModelItem,
                            selected && styles.onnxModelItemActive,
                          )}
                          onClick={() => setFeatureModel(model.id)}
                        >
                          <span className={styles.onnxModelName}>
                            {model.name}
                          </span>
                        </button>
                      );
                    })}
                    {featureProviderId &&
                    (remoteProviders.find(
                      (provider) => provider.provider_id === featureProviderId,
                    )?.models.length ?? 0) === 0 ? (
                      <Typography.Text
                        type="secondary"
                        className={styles.settingsHint}
                      >
                        {t("knowledgeBases.noModels")}
                      </Typography.Text>
                    ) : null}
                  </div>
                </div>
              ) : (
                <div className={styles.onnxModelList}>
                  {catalog.map((model) => {
                    const selected = featureModel === model.id;
                    const size = formatSizeGb(model.size_gb);
                    const downloading =
                      onnxDownloading && downloadProgressModel === model.id;
                    return (
                      <div
                        key={model.id}
                        className={cx(
                          styles.onnxModelItem,
                          selected && styles.onnxModelItemActive,
                        )}
                        onClick={() => setFeatureModel(model.id)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            setFeatureModel(model.id);
                          }
                        }}
                        role="button"
                        tabIndex={0}
                      >
                        <div className={styles.onnxModelInfo}>
                          <span className={styles.onnxModelName}>
                            {model.name}
                          </span>
                          <span className={styles.onnxModelMeta}>
                            {model.recommended
                              ? t("knowledgeBases.recommended")
                              : null}
                            {model.recommended ? " · " : null}
                            {size
                              ? t("knowledgeBases.approxSize", { size })
                              : t("knowledgeBases.sizeUnknown")}
                            {model.downloaded
                              ? null
                              : ` · ${t("knowledgeBases.notDownloaded")}`}
                          </span>
                        </div>
                        {model.downloaded ? null : (
                          <Button
                            size="small"
                            icon={<Download size={14} />}
                            loading={downloading}
                            disabled={onnxDownloading && !downloading}
                            onClick={(event) => {
                              event.stopPropagation();
                              setFeatureModel(model.id);
                              void startOnnxDownload(model.id);
                            }}
                          >
                            {t("knowledgeBases.downloadModel")}
                          </Button>
                        )}
                      </div>
                    );
                  })}
                  {catalog.length === 0 ? (
                    <Typography.Text
                      type="secondary"
                      className={styles.settingsHint}
                    >
                      {t("knowledgeBases.noModels")}
                    </Typography.Text>
                  ) : null}
                  {catalog.length > 0 && !onnxExpanded ? (
                    <Button
                      type="link"
                      loading={onnxExpanding}
                      className={styles.showMoreOnnx}
                      onClick={() => void loadEmbeddingOptions(true)}
                    >
                      {t("knowledgeBases.showMoreOnnx")}
                    </Button>
                  ) : null}
                </div>
              )}
              {featureBackend === "onnx" && featureModel ? (
                <div className={styles.onnxReadiness}>
                  <ReadinessRow
                    label={t("knowledgeBases.checkRuntime")}
                    ok={Boolean(capability?.checks.deps_available)}
                    okText={t("knowledgeBases.checkInstalled")}
                    failText={t("knowledgeBases.checkRuntimeMissing")}
                  />
                  <ReadinessRow
                    label={t("knowledgeBases.checkWeights")}
                    ok={Boolean(
                      catalog.find((model) => model.id === featureModel)
                        ?.downloaded,
                    )}
                    okText={t("knowledgeBases.checkDownloaded")}
                    failText={t("knowledgeBases.notDownloaded")}
                  />
                  <div className={styles.onnxReadinessRow}>
                    <span className={styles.onnxReadinessLabel}>
                      {t("knowledgeBases.checkEncode")}
                    </span>
                    {onnxProbe ? (
                      <Typography.Text
                        type={onnxProbe.ok ? "success" : "danger"}
                      >
                        {onnxProbe.ok
                          ? t("knowledgeBases.probeOk", {
                              dim: onnxProbe.dim ?? "?",
                              ms: Math.round(onnxProbe.latency_ms ?? 0),
                            })
                          : onnxProbe.error ?? t("knowledgeBases.probeFailed")}
                      </Typography.Text>
                    ) : (
                      <Typography.Text type="secondary">
                        {t("knowledgeBases.probeIdle")}
                      </Typography.Text>
                    )}
                    <Button
                      type="link"
                      size="small"
                      loading={onnxProbing}
                      onClick={() => void runOnnxProbe()}
                    >
                      {t("knowledgeBases.probeRun")}
                    </Button>
                  </div>
                </div>
              ) : null}
              <Typography.Text type="secondary" className={styles.settingsHint}>
                {t("knowledgeBases.enableDescription")}
              </Typography.Text>
              <Typography.Link onClick={() => navigate("/admin/models")}>
                {t("knowledgeBases.manageModels")}
              </Typography.Link>
              <div className={styles.ocrSettings}>
                <div className={styles.formOptionRow}>
                  <div className={styles.formOptionCopy}>
                    <span className={styles.switchLabel}>
                      {t("knowledgeBases.ocrTitle")}
                    </span>
                    <span className={styles.formOptionHint}>
                      {t("knowledgeBases.ocrDescription")}
                    </span>
                  </div>
                  <Switch
                    size="small"
                    checked={ocrEnabledDraft}
                    onChange={setOcrEnabledDraft}
                  />
                </div>
                {ocrEnabledDraft ? (
                  <div className={styles.featureFields}>
                    <Radio.Group
                      className={styles.featureBackend}
                      value={ocrBackend}
                      onChange={(event) => {
                        const backend = event.target.value as "onnx" | "remote";
                        setOcrBackend(backend);
                        setOcrModel(
                          backend === "onnx" ? "rapidocr" : undefined,
                        );
                        setOcrProviderId(undefined);
                      }}
                    >
                      <Radio value="onnx">{t("knowledgeBases.ocrLocal")}</Radio>
                      <Radio value="remote">
                        {t("knowledgeBases.ocrRemote")}
                      </Radio>
                    </Radio.Group>
                    {ocrBackend === "onnx" ? (
                      <div
                        className={cx(
                          styles.onnxModelItem,
                          styles.onnxModelItemActive,
                        )}
                      >
                        <div className={styles.onnxModelInfo}>
                          <span className={styles.onnxModelName}>
                            RapidOCR (ONNX)
                          </span>
                          <span className={styles.onnxModelMeta}>
                            {t("knowledgeBases.ocrLocalHint")}
                          </span>
                        </div>
                      </div>
                    ) : (
                      <>
                        <Alert
                          type="warning"
                          showIcon
                          message={t("knowledgeBases.ocrRemotePrivacy")}
                        />
                        <Select
                          value={ocrProviderId}
                          onChange={(id) => {
                            setOcrProviderId(id);
                            setOcrModel(undefined);
                          }}
                          placeholder={t("knowledgeBases.selectProvider")}
                          options={ocrRemoteProviders.map((provider) => ({
                            value: provider.provider_id,
                            label: provider.provider_name,
                          }))}
                          notFoundContent={t("knowledgeBases.ocrNoProviders")}
                        />
                        <Select
                          value={ocrModel}
                          onChange={setOcrModel}
                          placeholder={t("knowledgeBases.ocrSelectModel")}
                          options={(
                            ocrRemoteProviders.find(
                              (provider) =>
                                provider.provider_id === ocrProviderId,
                            )?.models ?? []
                          ).map((model) => ({
                            value: model.id,
                            label: model.name,
                          }))}
                          disabled={!ocrProviderId}
                          notFoundContent={t("knowledgeBases.ocrNoModels")}
                        />
                      </>
                    )}
                  </div>
                ) : null}
              </div>
            </div>
          </Spin>
        ) : null}
      </Drawer>
  );
}
