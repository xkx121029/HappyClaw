import type { CSSProperties } from "react";
import { App, Button, Spin } from "antd";
import { Settings } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router-dom";
import cx from "classnames";

import { useCurrentUser } from "../../hooks/useCurrentUser";
import { userCan } from "../../utils/permissions";
import {
  DEFAULT_KNOWLEDGE_LIMITS,
  type KnowledgeDocument,
} from "../../api/modules/knowledgeBases";

import { useCardTableView } from "../../hooks/useCardTableView";
import { useHorizontalResize } from "../../hooks/useHorizontalResize";
import { useIsMobile } from "../../hooks/useIsMobile";
import { useListPanelCollapsed } from "../../hooks/useListPanelCollapsed";
import { useServerTimezone } from "../../hooks/useServerTimezone";
import PageShell from "../../layouts/PageShell";
import { DOCS_VIEW_STORAGE_KEY, loadDocsViewMode } from "./knowledgeDocsView";
import { canManageKnowledgeBase } from "./knowledgePermissions";
import TextDocumentEditorModal from "./TextDocumentEditorModal";
import styles from "./index.module.less";
import { DocumentPreviewModal } from "./components/DocumentPreviewModal";
import { KnowledgeDetailsPane } from "./components/KnowledgeDetailsPane";
import {
  KnowledgeDocumentActions,
  KnowledgeEntryName,
} from "./components/KnowledgeDocumentEntry";
import {
  CreateFolderModal,
  MoveEntryModal,
  RenameEntryModal,
} from "./components/KnowledgeEntryDialogs";
import { KnowledgeBaseFormDrawer } from "./components/KnowledgeBaseFormDrawer";
import { KnowledgeBaseListAside } from "./components/KnowledgeBaseListAside";
import { KnowledgeFeatureSettingsDrawer } from "./components/KnowledgeFeatureSettingsDrawer";
import { KnowledgeSplitDivider } from "./components/KnowledgeSplitDivider";
import {
  KnowledgeEmptyGuide,
  KnowledgeEnableGuide,
} from "./components/KnowledgeStartGuides";
import { OnnxDownloadProgressModal } from "./components/OnnxDownloadProgressModal";
import { useKnowledgeFeatureSettings } from "./hooks/useKnowledgeFeatureSettings";
import { useKnowledgeWorkspace } from "./hooks/useKnowledgeWorkspace";
import { useKnowledgePreview } from "./hooks/useKnowledgePreview";
import { useKnowledgeEntries } from "./hooks/useKnowledgeEntries";
import { useKnowledgeBaseEditor } from "./hooks/useKnowledgeBaseEditor";
import { useKnowledgeDeepLink } from "./hooks/useKnowledgeDeepLink";
import { useKnowledgeDocTreeData } from "./hooks/useKnowledgeDocTreeData";

export default function KnowledgeBasesPage() {
  const { t } = useTranslation();
  const { modal, message } = App.useApp();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const isMobile = useIsMobile();
  const timeZone = useServerTimezone();
  const user = useCurrentUser();
  const canConfigureKb = userCan(user, "knowledge_settings");

  const {
    capability,
    catalog,
    onnxDownloading,
    downloadProgressOpen,
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
    runOnnxProbe,
    saveFeature,
    openSettings,
    startOnnxDownload,
    dismissDownloadProgressToBackground,
  } = useKnowledgeFeatureSettings({ t, message, modal });

  const {
    bases,
    selected,
    documents,
    selectedIdRef,
    loading,
    detailLoading,
    refreshing,
    setRefreshing,
    mobilePane,
    setMobilePane,
    loadBases,
    loadDetail,
    selectBase,
    confirmDeleteBase,
    addBaseToChat,
  } = useKnowledgeWorkspace({
    t,
    message,
    modal,
    navigate,
    isMobile,
    loadCapability,
  });

  const {
    previewOpen,
    previewLoading,
    previewFilename,
    setPreviewFilename,
    previewText,
    previewKind,
    previewDocId,
    previewHasOriginal,
    previewAsMarkdown,
    previewMode,
    setPreviewMode,
    previewFileAvailable,
    chunkItems,
    chunkLoading,
    chunkError,
    previewMaximized,
    mdOutlineOpen,
    setMdOutlineOpen,
    mdActiveOutlineIndex,
    mdFindOpen,
    setMdFindOpen,
    mdFindQuery,
    setMdFindQuery,
    mdFindIndex,
    setMdFindIndex,
    mdFindHitCount,
    mdBodyRef,
    mdFindInputRef,
    isRichPreview,
    previewableDocs,
    previewNavIndex,
    mdOutlineItems,
    scrollToMdHeading,
    jumpMdFind,
    requestClosePreview,
    togglePreviewFullscreen,
    loadDocumentChunks,
    openDocumentPreview,
    downloadDocumentOriginal,
    fetchPreviewBlob,
  } = useKnowledgePreview({ t, message, selected, documents });

  const onRenamePreview = (documentId: string, nextName: string) => {
    if (previewDocId === documentId) setPreviewFilename(nextName);
  };

  const {
    currentFolder,
    setCurrentFolder,
    docTreeExpanded,
    setDocTreeExpanded,
    folderModalOpen,
    setFolderModalOpen,
    folderName,
    setFolderName,
    renameModalOpen,
    setRenameModalOpen,
    renameTarget,
    renameName,
    setRenameName,
    moveTarget,
    setMoveTarget,
    moveDestination,
    setMoveDestination,
    moving,
    dragDepthRef,
    uploadState,
    uploadRef,
    dragActive,
    setDragActive,
    textEditorOpen,
    setTextEditorOpen,
    textEditorMode,
    textEditorLoading,
    textEditorSaving,
    textEditorName,
    textEditorFormat,
    textEditorContent,
    uploadDocuments,
    resetDragActive,
    createFolder,
    openRenameFolder,
    openRenameFile,
    renameEntry,
    openMoveEntry,
    moveEntry,
    deleteDocument,
    rebuildDocument,
    openCreateTextDocument,
    openEditTextDocument,
    saveTextDocument,
  } = useKnowledgeEntries({
    t,
    message,
    selected,
    selectedIdRef,
    documents,
    loadDetail,
    loadBases,
    capability,
    onRenamePreview,
  });

  const {
    baseDrawerOpen,
    setBaseDrawerOpen,
    editingBaseId,
    baseForm,
    iconName,
    iconUrl,
    pendingAvatarFile,
    setPendingAvatarFile,
    avatarBusy,
    setAvatarBusy,
    defaultOpenChecked,
    setDefaultOpenChecked,
    baseVisibility,
    setBaseVisibility,
    baseGroupIds,
    setBaseGroupIds,
    openCreate,
    openEdit,
    saveBase,
  } = useKnowledgeBaseEditor({
    t,
    message,
    bases,
    user,
    capability,
    loadBases,
    loadDetail,
    isMobile,
    setMobilePane,
  });
  useKnowledgeDeepLink({
    searchParams,
    setSearchParams,
    bases,
    documents,
    selected,
    detailLoading,
    selectBase,
    openDocumentPreview,
    setCurrentFolder,
    message,
    t,
  });

  const { docTreeData, moveTreeData } = useKnowledgeDocTreeData({
    t,
    documents,
    moveTarget,
  });

  const { viewMode, setViewMode, showCardView } = useCardTableView(
    loadDocsViewMode(),
  );

  const {
    size: sidebarWidth,
    isResizing,
    onResizeStart,
  } = useHorizontalResize({
    min: 220,
    max: 480,
    defaultSize: 280,
    storageKey: "octop:knowledge-bases:sidebar-width",
  });
  const { collapsed: listPanelCollapsed, toggle: toggleListPanel } =
    useListPanelCollapsed("octop:knowledge-bases:list-collapsed");
  const { collapsed: docTreeCollapsed, toggle: toggleDocTree } =
    useListPanelCollapsed("octop:knowledge-bases:doc-tree-collapsed", {
      defaultCollapsed: true,
    });
  const { size: docTreeWidth, onResizeStart: onDocTreeResizeStart } =
    useHorizontalResize({
      min: 180,
      max: 420,
      defaultSize: 220,
      storageKey: "octop:knowledge-bases:doc-tree-width",
    });

  const canManageSelected = Boolean(
    selected && canManageKnowledgeBase(selected, user),
  );
  const canWriteSelected = canManageSelected;
  const usable = Boolean(capability?.usable);
  const limits = capability?.limits ?? DEFAULT_KNOWLEDGE_LIMITS;
  const ownedBaseCount = user
    ? bases.filter((base) => base.owner_user_id === user.id).length
    : 0;
  const atBaseLimit = ownedBaseCount >= limits.max_bases_per_owner;

  const refresh = async () => {
    setRefreshing(true);
    try {
      await Promise.all([
        loadBases(),
        loadCapability(),
        selected ? loadDetail(selected.id) : Promise.resolve(),
      ]);
    } finally {
      setRefreshing(false);
    }
  };

  const renderDocumentActions = (document: KnowledgeDocument) => (
    <KnowledgeDocumentActions
      document={document}
      canWriteSelected={canWriteSelected}
      openDocumentPreview={openDocumentPreview}
      downloadDocumentOriginal={downloadDocumentOriginal}
      openEditTextDocument={openEditTextDocument}
      rebuildDocument={rebuildDocument}
      openRenameFolder={openRenameFolder}
      openMoveEntry={openMoveEntry}
      deleteDocument={deleteDocument}
    />
  );

  const renderEntryName = (
    document: KnowledgeDocument,
    nameClass?: string,
  ) => (
    <KnowledgeEntryName
      document={document}
      nameClass={nameClass}
      canWriteSelected={canWriteSelected}
      openRenameFile={openRenameFile}
    />
  );

  const showListPane = !isMobile || mobilePane === "list";
  const showDetailPane = !isMobile || mobilePane === "detail";
  const showListPanel = showListPane && (isMobile || !listPanelCollapsed);
  const showEnableGuide = !loading && !usable;
  const showEmptyGuide = !loading && usable && bases.length === 0;
  const emptyLayoutClassName = styles.emptyLayout;

  const onDocsViewChange = (value: string | number) => {
    const mode = value === "table" ? "table" : "card";
    setViewMode(mode);
    localStorage.setItem(DOCS_VIEW_STORAGE_KEY, mode);
  };

  return (
    <PageShell
      title={t("knowledgeBases.title")}
      subtitle={t("knowledgeBases.subtitle")}
      fill
      actions={
        canConfigureKb ? (
          <Button icon={<Settings size={15} />} onClick={openSettings}>
            {t("knowledgeBases.settingsTitle")}
          </Button>
        ) : undefined
      }
    >
      {loading ? (
        <div className={emptyLayoutClassName}>
          <div className={styles.centered}>
            <Spin />
          </div>
        </div>
      ) : showEnableGuide ? (
        <KnowledgeEnableGuide
          canConfigureKb={canConfigureKb}
          onOpenSettings={openSettings}
        />
      ) : showEmptyGuide ? (
        <KnowledgeEmptyGuide atBaseLimit={atBaseLimit} onCreate={openCreate} />
      ) : (
        <div
          className={cx(
            styles.layout,
            isResizing && styles.layoutResizing,
            isMobile && styles.layoutMobile,
          )}
          style={
            {
              "--knowledge-bases-sidebar-width": `${sidebarWidth}px`,
            } as CSSProperties
          }
        >
          {showListPanel ? (
            <KnowledgeBaseListAside
              bases={bases}
              selectedId={selected?.id ?? null}
              user={user}
              loading={loading}
              refreshing={refreshing}
              usable={usable}
              atBaseLimit={atBaseLimit}
              onRefresh={() => void refresh()}
              onCreate={openCreate}
              onSelect={selectBase}
              addBaseToChat={addBaseToChat}
              openEdit={openEdit}
              confirmDeleteBase={confirmDeleteBase}
            />
          ) : null}
          {!isMobile ? (
            <KnowledgeSplitDivider
              listPanelCollapsed={listPanelCollapsed}
              onResizeStart={onResizeStart}
              onToggle={toggleListPanel}
            />
          ) : null}
          {showDetailPane ? (
            <KnowledgeDetailsPane
              selected={selected}
              detailLoading={detailLoading}
              isMobile={isMobile}
              setMobilePane={setMobilePane}
              dragActive={dragActive}
              setDragActive={setDragActive}
              uploadDocuments={uploadDocuments}
              dragDepthRef={dragDepthRef}
              setFolderName={setFolderName}
              setFolderModalOpen={setFolderModalOpen}
              openDocumentPreview={openDocumentPreview}
              resetDragActive={resetDragActive}
              setCurrentFolder={setCurrentFolder}
              viewMode={viewMode}
              onDocsViewChange={onDocsViewChange}
              uploadRef={uploadRef}
              canWriteSelected={canWriteSelected}
              capability={capability}
              openCreateTextDocument={openCreateTextDocument}
              docTreeCollapsed={docTreeCollapsed}
              docTreeWidth={docTreeWidth}
              docTreeData={docTreeData}
              currentFolder={currentFolder}
              docTreeExpanded={docTreeExpanded}
              setDocTreeExpanded={setDocTreeExpanded}
              onDocTreeResizeStart={onDocTreeResizeStart}
              toggleDocTree={toggleDocTree}
              uploadState={uploadState}
              documents={documents}
              showCardView={showCardView}
              renderEntryName={renderEntryName}
              renderDocumentActions={renderDocumentActions}
              timeZone={timeZone}
            />
          ) : null}
        </div>
      )}

      <DocumentPreviewModal
        previewOpen={previewOpen}
        requestClosePreview={requestClosePreview}
        previewFilename={previewFilename}
        previewMode={previewMode}
        setPreviewMode={setPreviewMode}
        selectedId={selected?.id ?? null}
        previewDocId={previewDocId}
        chunkItems={chunkItems}
        chunkLoading={chunkLoading}
        chunkError={chunkError}
        loadDocumentChunks={loadDocumentChunks}
        previewFileAvailable={previewFileAvailable}
        previewNavIndex={previewNavIndex}
        previewableDocs={previewableDocs}
        openDocumentPreview={openDocumentPreview}
        previewMaximized={previewMaximized}
        togglePreviewFullscreen={togglePreviewFullscreen}
        previewHasOriginal={previewHasOriginal}
        downloadDocumentOriginal={downloadDocumentOriginal}
        isRichPreview={isRichPreview}
        isMobile={isMobile}
        previewKind={previewKind}
        fetchPreviewBlob={fetchPreviewBlob}
        previewAsMarkdown={previewAsMarkdown}
        mdOutlineItems={mdOutlineItems}
        mdOutlineOpen={mdOutlineOpen}
        setMdOutlineOpen={setMdOutlineOpen}
        mdActiveOutlineIndex={mdActiveOutlineIndex}
        scrollToMdHeading={scrollToMdHeading}
        mdFindOpen={mdFindOpen}
        setMdFindOpen={setMdFindOpen}
        mdFindQuery={mdFindQuery}
        setMdFindQuery={setMdFindQuery}
        mdFindIndex={mdFindIndex}
        setMdFindIndex={setMdFindIndex}
        mdFindHitCount={mdFindHitCount}
        mdFindInputRef={mdFindInputRef}
        mdBodyRef={mdBodyRef}
        jumpMdFind={jumpMdFind}
        previewLoading={previewLoading}
        previewText={previewText}
      />

      <CreateFolderModal
        folderModalOpen={folderModalOpen}
        setFolderModalOpen={setFolderModalOpen}
        folderName={folderName}
        setFolderName={setFolderName}
        createFolder={createFolder}
      />

      <RenameEntryModal
        renameModalOpen={renameModalOpen}
        setRenameModalOpen={setRenameModalOpen}
        renameTarget={renameTarget}
        renameName={renameName}
        setRenameName={setRenameName}
        renameEntry={renameEntry}
      />

      <MoveEntryModal
        moveTarget={moveTarget}
        setMoveTarget={setMoveTarget}
        moveDestination={moveDestination}
        setMoveDestination={setMoveDestination}
        moveEntry={moveEntry}
        moving={moving}
        moveTreeData={moveTreeData}
      />

      <TextDocumentEditorModal
        open={textEditorOpen}
        mode={textEditorMode}
        loading={textEditorLoading}
        saving={textEditorSaving}
        initialName={textEditorName}
        initialFormat={textEditorFormat}
        initialContent={textEditorContent}
        onCancel={() => setTextEditorOpen(false)}
        onSubmit={saveTextDocument}
      />

      <KnowledgeBaseFormDrawer
        baseDrawerOpen={baseDrawerOpen}
        setBaseDrawerOpen={setBaseDrawerOpen}
        editingBaseId={editingBaseId}
        isMobile={isMobile}
        baseForm={baseForm}
        iconName={iconName}
        iconUrl={iconUrl}
        pendingAvatarFile={pendingAvatarFile}
        setPendingAvatarFile={setPendingAvatarFile}
        avatarBusy={avatarBusy}
        setAvatarBusy={setAvatarBusy}
        defaultOpenChecked={defaultOpenChecked}
        setDefaultOpenChecked={setDefaultOpenChecked}
        baseVisibility={baseVisibility}
        setBaseVisibility={setBaseVisibility}
        baseGroupIds={baseGroupIds}
        setBaseGroupIds={setBaseGroupIds}
        saveBase={saveBase}
      />

      <KnowledgeFeatureSettingsDrawer
        featureModalOpen={featureModalOpen}
        setFeatureModalOpen={setFeatureModalOpen}
        isMobile={isMobile}
        featureSaving={featureSaving}
        featureEnabledDraft={featureEnabledDraft}
        setFeatureEnabledDraft={setFeatureEnabledDraft}
        featureModel={featureModel}
        setFeatureModel={setFeatureModel}
        featureBackend={featureBackend}
        setFeatureBackend={setFeatureBackend}
        featureProviderId={featureProviderId}
        setFeatureProviderId={setFeatureProviderId}
        ocrEnabledDraft={ocrEnabledDraft}
        setOcrEnabledDraft={setOcrEnabledDraft}
        ocrBackend={ocrBackend}
        setOcrBackend={setOcrBackend}
        ocrModel={ocrModel}
        setOcrModel={setOcrModel}
        ocrProviderId={ocrProviderId}
        setOcrProviderId={setOcrProviderId}
        ocrRemoteProviders={ocrRemoteProviders}
        remoteProviders={remoteProviders}
        catalog={catalog}
        featureOptionsLoading={featureOptionsLoading}
        onnxDownloading={onnxDownloading}
        downloadProgressModel={downloadProgressModel}
        onnxExpanded={onnxExpanded}
        onnxExpanding={onnxExpanding}
        loadEmbeddingOptions={loadEmbeddingOptions}
        startOnnxDownload={startOnnxDownload}
        onnxProbe={onnxProbe}
        onnxProbing={onnxProbing}
        runOnnxProbe={runOnnxProbe}
        capability={capability}
        saveFeature={() => saveFeature()}
      />
      <OnnxDownloadProgressModal
        downloadProgressOpen={downloadProgressOpen}
        downloadProgress={downloadProgress}
        downloadProgressLabel={downloadProgressLabel}
        downloadProgressModel={downloadProgressModel}
        dismissDownloadProgressToBackground={dismissDownloadProgressToBackground}
      />
    </PageShell>
  );
}
