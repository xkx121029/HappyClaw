import type { App } from "antd";
import type { TFunction } from "i18next";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  knowledgeBasesApi,
  type KnowledgeCapability,
  type KnowledgeOnnxModel,
} from "../../../api/modules/knowledgeBases";
import { apiErrorMessage } from "../../../utils/apiError";
import { formatSizeGb } from "../../../utils/embeddingDownload";
import type {
  KnowledgeRemoteProvider,
  OnnxProbeResult,
} from "../components/KnowledgeFeatureSettingsDrawer";

type AppApi = ReturnType<typeof App.useApp>;

export interface UseKnowledgeFeatureSettingsArgs {
  t: TFunction;
  message: AppApi["message"];
  modal: AppApi["modal"];
}

/** Knowledge-base embedding / OCR settings: capability, ONNX catalog, drafts. */
export function useKnowledgeFeatureSettings({
  t,
  message,
  modal,
}: UseKnowledgeFeatureSettingsArgs) {
  const [capability, setCapability] = useState<KnowledgeCapability | null>(
    null,
  );
  const [catalog, setCatalog] = useState<KnowledgeOnnxModel[]>([]);
  const [onnxDownloading, setOnnxDownloading] = useState(false);
  const [downloadProgressOpen, setDownloadProgressOpen] = useState(false);
  const [downloadProgress, setDownloadProgress] = useState(0);
  const [downloadProgressLabel, setDownloadProgressLabel] = useState("");
  const [downloadProgressModel, setDownloadProgressModel] = useState("");
  const onnxDownloadTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const [remoteProviders, setRemoteProviders] = useState<
    KnowledgeRemoteProvider[]
  >([]);
  const [featureModalOpen, setFeatureModalOpen] = useState(false);
  const [onnxProbe, setOnnxProbe] = useState<OnnxProbeResult | null>(null);
  const [onnxProbing, setOnnxProbing] = useState(false);
  const [featureEnabledDraft, setFeatureEnabledDraft] = useState(false);
  const [featureSaving, setFeatureSaving] = useState(false);
  const [featureModel, setFeatureModel] = useState<string>();
  const [featureBackend, setFeatureBackend] = useState<"onnx" | "remote">(
    "onnx",
  );
  const [featureProviderId, setFeatureProviderId] = useState<string>();
  const [featureOptionsLoading, setFeatureOptionsLoading] = useState(false);
  const [ocrEnabledDraft, setOcrEnabledDraft] = useState(false);
  const [ocrBackend, setOcrBackend] = useState<"onnx" | "remote">("onnx");
  const [ocrModel, setOcrModel] = useState<string>();
  const [ocrProviderId, setOcrProviderId] = useState<string>();
  const [ocrRemoteProviders, setOcrRemoteProviders] = useState<
    KnowledgeRemoteProvider[]
  >([]);
  const [onnxExpanded, setOnnxExpanded] = useState(false);
  const [onnxExpanding, setOnnxExpanding] = useState(false);
  const onnxExpandedRef = useRef(false);

  const loadCapability = useCallback(async () => {
    try {
      const nextCapability = await knowledgeBasesApi.getCapability();
      setCapability(nextCapability);
      setFeatureModel(nextCapability.selected_model || undefined);
      setFeatureBackend(nextCapability.backend);
      setFeatureProviderId(nextCapability.provider_id || undefined);
      setFeatureEnabledDraft(Boolean(nextCapability.feature_enabled));
      setOcrEnabledDraft(Boolean(nextCapability.ocr?.enabled));
      setOcrBackend(nextCapability.ocr?.backend ?? "onnx");
      setOcrModel(nextCapability.ocr?.model || "rapidocr");
      setOcrProviderId(nextCapability.ocr?.provider_id || undefined);
    } catch (error) {
      message.error(apiErrorMessage(error, t("knowledgeBases.loadFailed"), t));
    }
  }, [t]);

  const loadEmbeddingOptions = useCallback(
    async (allOnnx = false) => {
      if (allOnnx) {
        setOnnxExpanding(true);
      } else {
        setFeatureOptionsLoading(true);
      }
      try {
        const options = await knowledgeBasesApi.getEmbeddingOptions({
          allOnnx,
        });
        setCatalog(options.onnx);
        setRemoteProviders(options.remote);
        if (allOnnx) {
          onnxExpandedRef.current = true;
          setOnnxExpanded(true);
        }
        return options;
      } catch (error) {
        message.error(
          apiErrorMessage(error, t("knowledgeBases.loadFailed"), t),
        );
        return undefined;
      } finally {
        setFeatureOptionsLoading(false);
        setOnnxExpanding(false);
      }
    },
    [t],
  );

  const loadOcrOptions = useCallback(async () => {
    try {
      const options = await knowledgeBasesApi.getOcrOptions();
      setOcrRemoteProviders(options.remote);
      return options;
    } catch (error) {
      message.error(apiErrorMessage(error, t("knowledgeBases.loadFailed"), t));
      return undefined;
    }
  }, [t]);

  const stopOnnxDownloadWatch = useCallback(() => {
    if (onnxDownloadTimer.current) {
      clearInterval(onnxDownloadTimer.current);
      onnxDownloadTimer.current = null;
    }
  }, []);

  const applyOnnxDownloadProgress = useCallback(
    (modelId: string, status: string, progress: number) => {
      const pct = Math.max(0, Math.min(100, Math.round((progress || 0) * 100)));
      setDownloadProgress(pct);
      if (status === "loading") {
        setDownloadProgressLabel(
          t("models.onnxDownloadLoading", { model: modelId }),
        );
      } else if (status === "downloading") {
        setDownloadProgressLabel(
          t("models.onnxDownloading", { model: modelId }),
        );
      } else {
        setDownloadProgressLabel(t("models.localDownloadPreparing"));
      }
    },
    [t],
  );

  const finishOnnxDownload = useCallback(
    async (modelId: string, status: string, error?: string | null) => {
      stopOnnxDownloadWatch();
      setOnnxDownloading(false);
      setDownloadProgressOpen(false);
      await loadEmbeddingOptions(onnxExpandedRef.current);
      if (status === "done") {
        try {
          await knowledgeBasesApi.activateOnnx(modelId);
          message.success(t("knowledgeBases.onnxServiceEnabled"));
        } catch (activateError) {
          message.success(t("models.onnxDownloadDone", { model: modelId }));
          message.warning(
            apiErrorMessage(
              activateError,
              t("knowledgeBases.featureSaveFailed"),
              t,
            ),
          );
        }
        return;
      }
      message.error(error || t("models.onnxDownloadFailed"));
    },
    [loadEmbeddingOptions, stopOnnxDownloadWatch, t],
  );

  const watchOnnxDownloadStatus = useCallback(
    (modelId: string) => {
      stopOnnxDownloadWatch();
      let inFlight = false;
      let stopped = false;
      const tick = async () => {
        if (inFlight || stopped) return;
        inFlight = true;
        try {
          const state = await knowledgeBasesApi.getOnnxDownloadStatus();
          applyOnnxDownloadProgress(
            state.model_name || modelId,
            state.status,
            state.progress,
          );
          if (state.status === "done" || state.status === "failed") {
            stopped = true;
            stopOnnxDownloadWatch();
            await finishOnnxDownload(
              state.model_name || modelId,
              state.status,
              state.error,
            );
          }
        } catch (error) {
          stopped = true;
          stopOnnxDownloadWatch();
          await finishOnnxDownload(
            modelId,
            "failed",
            error instanceof Error ? error.message : String(error),
          );
        } finally {
          inFlight = false;
        }
      };
      onnxDownloadTimer.current = setInterval(() => {
        void tick();
      }, 500);
      void tick();
    },
    [applyOnnxDownloadProgress, finishOnnxDownload, stopOnnxDownloadWatch],
  );

  useEffect(() => () => stopOnnxDownloadWatch(), [stopOnnxDownloadWatch]);

  // A probe describes one model; drop it as soon as the draft points elsewhere.
  useEffect(() => {
    setOnnxProbe(null);
  }, [featureModel, featureBackend]);

  const runOnnxProbe = async () => {
    if (!featureModel) return;
    setOnnxProbing(true);
    try {
      setOnnxProbe(await knowledgeBasesApi.testOnnx(featureModel));
    } catch (error) {
      setOnnxProbe({
        ok: false,
        error: error instanceof Error ? error.message : String(error),
      });
    } finally {
      setOnnxProbing(false);
    }
  };

  const saveFeature = async (confirmed = false) => {
    if (!featureEnabledDraft) {
      setFeatureSaving(true);
      try {
        setCapability(await knowledgeBasesApi.setFeature({ enabled: false }));
        setFeatureModalOpen(false);
        message.success(t("knowledgeBases.featureDisabled"));
      } catch (error) {
        message.error(
          apiErrorMessage(error, t("knowledgeBases.featureSaveFailed"), t),
        );
      } finally {
        setFeatureSaving(false);
      }
      return;
    }
    if (!featureModel || (featureBackend === "remote" && !featureProviderId)) {
      return;
    }
    if (
      ocrEnabledDraft &&
      ocrBackend === "remote" &&
      (!ocrProviderId || !ocrModel)
    ) {
      return;
    }
    if (
      featureBackend === "onnx" &&
      !catalog.find((model) => model.id === featureModel)?.downloaded
    ) {
      message.warning(t("knowledgeBases.downloadNeedModel"));
      return;
    }
    if (
      !confirmed &&
      capability?.feature_enabled &&
      (capability.backend !== featureBackend ||
        capability.selected_model !== featureModel ||
        capability.provider_id !==
          (featureBackend === "remote" ? featureProviderId : "") ||
        capability.ocr?.enabled !== ocrEnabledDraft ||
        capability.ocr?.backend !== ocrBackend ||
        (ocrEnabledDraft &&
          ocrBackend === "remote" &&
          (capability.ocr?.model !== ocrModel ||
            capability.ocr?.provider_id !== ocrProviderId)))
    ) {
      modal.confirm({
        title: t("knowledgeBases.rebuildConfirmTitle"),
        content: t("knowledgeBases.rebuildConfirmDescription"),
        okText: t("common.confirm"),
        cancelText: t("common.cancel"),
        onOk: () => void saveFeature(true),
      });
      return;
    }
    setFeatureSaving(true);
    try {
      const next = await knowledgeBasesApi.setFeature({
        enabled: true,
        backend: featureBackend,
        model: featureModel,
        provider_id: featureBackend === "remote" ? featureProviderId : "",
        ocr_enabled: ocrEnabledDraft,
        ocr_backend: ocrBackend,
        ocr_model: ocrBackend === "remote" ? ocrModel : "rapidocr",
        ocr_provider_id: ocrBackend === "remote" ? ocrProviderId : "",
      });
      setCapability(next);
      setFeatureModalOpen(false);
      message.success(t("knowledgeBases.featureEnabled"));
    } catch (error) {
      message.error(
        apiErrorMessage(error, t("knowledgeBases.featureSaveFailed"), t),
      );
    } finally {
      setFeatureSaving(false);
    }
  };

  const openSettings = () => {
    const selectedModel = capability?.selected_model || undefined;
    const selectedBackend = capability?.backend ?? "onnx";
    onnxExpandedRef.current = false;
    setOnnxExpanded(false);
    setFeatureEnabledDraft(Boolean(capability?.feature_enabled));
    setFeatureBackend(selectedBackend);
    setFeatureModel(selectedModel);
    setFeatureProviderId(capability?.provider_id || undefined);
    setOcrEnabledDraft(Boolean(capability?.ocr?.enabled));
    setOcrBackend(capability?.ocr?.backend ?? "onnx");
    setOcrModel(capability?.ocr?.model || "rapidocr");
    setOcrProviderId(capability?.ocr?.provider_id || undefined);
    setFeatureModalOpen(true);
    void (async () => {
      const options = await loadEmbeddingOptions(false);
      const selectedInCatalog = Boolean(
        selectedModel &&
          options?.onnx.some((model) => model.id === selectedModel),
      );
      if (selectedBackend === "onnx" && selectedModel && !selectedInCatalog) {
        await loadEmbeddingOptions(true);
      }
    })();
    void loadOcrOptions();
    void knowledgeBasesApi.getOnnxDownloadStatus().then((state) => {
      if (state.status === "downloading" || state.status === "loading") {
        const modelId = state.model_name;
        setOnnxDownloading(true);
        setDownloadProgressModel(modelId);
        setDownloadProgressOpen(true);
        applyOnnxDownloadProgress(modelId, state.status, state.progress);
        watchOnnxDownloadStatus(modelId);
      }
    });
  };

  const startOnnxDownload = async (modelId: string) => {
    const selected = catalog.find((model) => model.id === modelId);
    const size = formatSizeGb(selected?.size_gb);
    modal.confirm({
      title: t("models.localDownloadConfirmTitle"),
      content: t("models.localDownloadConfirmOnnx", {
        name: modelId,
        size: size || t("knowledgeBases.sizeUnknown"),
      }),
      okText: t("knowledgeBases.downloadModel"),
      cancelText: t("common.cancel"),
      // Return void so antd closes this confirm immediately. An async onOk
      // stays open (OK button loading) until downloadOnnx settles, and
      // modal.confirm is pinned at z-index 2000, above the progress dialog.
      onOk: () => {
        setOnnxDownloading(true);
        setDownloadProgressModel(modelId);
        setDownloadProgress(0);
        setDownloadProgressLabel(t("models.localDownloadPreparing"));
        setDownloadProgressOpen(true);
        void knowledgeBasesApi.downloadOnnx(modelId).then(
          () => {
            watchOnnxDownloadStatus(modelId);
          },
          (error: unknown) => {
            setOnnxDownloading(false);
            setDownloadProgressOpen(false);
            message.error(
              apiErrorMessage(error, t("models.onnxDownloadFailed"), t),
            );
          },
        );
      },
    });
  };

  const dismissDownloadProgressToBackground = () => {
    setDownloadProgressOpen(false);
    message.info(t("models.localDownloadBackground"));
  };
  return {
    capability,
    setCapability,
    catalog,
    onnxDownloading,
    downloadProgressOpen,
    setDownloadProgressOpen,
    downloadProgress,
    downloadProgressLabel,
    downloadProgressModel,
    remoteProviders,
    featureModalOpen,
    setFeatureModalOpen,
    onnxProbe,
    onnxProbing,
    featureEnabledDraft,
    setFeatureEnabledDraft,
    featureSaving,
    featureModel,
    setFeatureModel,
    featureBackend,
    setFeatureBackend,
    featureProviderId,
    setFeatureProviderId,
    featureOptionsLoading,
    ocrEnabledDraft,
    setOcrEnabledDraft,
    ocrBackend,
    setOcrBackend,
    ocrModel,
    setOcrModel,
    ocrProviderId,
    setOcrProviderId,
    ocrRemoteProviders,
    onnxExpanded,
    onnxExpanding,
    loadCapability,
    loadEmbeddingOptions,
    loadOcrOptions,
    runOnnxProbe,
    saveFeature,
    openSettings,
    startOnnxDownload,
    dismissDownloadProgressToBackground,
  };
}
