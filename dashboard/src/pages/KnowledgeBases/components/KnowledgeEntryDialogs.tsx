import type { Dispatch, SetStateAction } from "react";
import { Input, Modal, Tree } from "antd";
import { useTranslation } from "react-i18next";

import type { KnowledgeDocument } from "../../../api/modules/knowledgeBases";
import { isImeComposing } from "../../../utils/ime";
import {
  KNOWLEDGE_DOC_TREE_ROOT,
  knowledgeBasename,
  knowledgeFileNameParts,
} from "../knowledgeFolder";
import type { DocTreeNode } from "../knowledgeDocTree";
import styles from "../index.module.less";

export interface CreateFolderModalProps {
  folderModalOpen: boolean;
  setFolderModalOpen: Dispatch<SetStateAction<boolean>>;
  folderName: string;
  setFolderName: Dispatch<SetStateAction<string>>;
  createFolder: () => Promise<void>;
}

export function CreateFolderModal({
  folderModalOpen,
  setFolderModalOpen,
  folderName,
  setFolderName,
  createFolder,
}: CreateFolderModalProps) {
  const { t } = useTranslation();
  return (
      <Modal
        title={t("knowledgeBases.createFolder")}
        open={folderModalOpen}
        onCancel={() => setFolderModalOpen(false)}
        onOk={() => void createFolder()}
        okText={t("common.create")}
        cancelText={t("common.cancel")}
        destroyOnHidden
      >
        <Input
          value={folderName}
          onChange={(event) => setFolderName(event.target.value)}
          placeholder={t("knowledgeBases.folderNamePlaceholder")}
          onPressEnter={(event) => {
            if (!isImeComposing(event)) void createFolder();
          }}
        />
      </Modal>
  );
}

export interface RenameEntryModalProps {
  renameModalOpen: boolean;
  setRenameModalOpen: Dispatch<SetStateAction<boolean>>;
  renameTarget: KnowledgeDocument | null;
  renameName: string;
  setRenameName: Dispatch<SetStateAction<string>>;
  renameEntry: () => Promise<void>;
}

export function RenameEntryModal({
  renameModalOpen,
  setRenameModalOpen,
  renameTarget,
  renameName,
  setRenameName,
  renameEntry,
}: RenameEntryModalProps) {
  const { t } = useTranslation();
  return (
      <Modal
        title={t(
          renameTarget && !renameTarget.is_dir
            ? "knowledgeBases.renameFile"
            : "knowledgeBases.renameFolder",
        )}
        open={renameModalOpen}
        onCancel={() => setRenameModalOpen(false)}
        onOk={() => void renameEntry()}
        okText={t("common.save")}
        cancelText={t("common.cancel")}
        destroyOnHidden
      >
        <Input
          autoFocus
          value={renameName}
          addonAfter={
            renameTarget && !renameTarget.is_dir
              ? knowledgeFileNameParts(
                  renameTarget.path || renameTarget.filename,
                ).suffix || undefined
              : undefined
          }
          onChange={(event) => setRenameName(event.target.value)}
          placeholder={t(
            renameTarget && !renameTarget.is_dir
              ? "knowledgeBases.filenamePlaceholder"
              : "knowledgeBases.folderNamePlaceholder",
          )}
          onPressEnter={(event) => {
            if (!isImeComposing(event)) void renameEntry();
          }}
        />
      </Modal>
  );
}

export interface MoveEntryModalProps {
  moveTarget: KnowledgeDocument | null;
  setMoveTarget: Dispatch<SetStateAction<KnowledgeDocument | null>>;
  moveDestination: string | null;
  setMoveDestination: Dispatch<SetStateAction<string | null>>;
  moveEntry: () => Promise<void>;
  moving: boolean;
  moveTreeData: DocTreeNode[];
}

export function MoveEntryModal({
  moveTarget,
  setMoveTarget,
  moveDestination,
  setMoveDestination,
  moveEntry,
  moving,
  moveTreeData,
}: MoveEntryModalProps) {
  const { t } = useTranslation();
  return (
      <Modal
        title={t("knowledgeBases.moveTitle", {
          name: moveTarget
            ? knowledgeBasename(moveTarget.path || moveTarget.filename)
            : "",
        })}
        open={moveTarget !== null}
        onCancel={() => setMoveTarget(null)}
        onOk={() => void moveEntry()}
        okText={t("knowledgeBases.moveConfirm")}
        okButtonProps={{ disabled: moveDestination === null }}
        confirmLoading={moving}
        cancelText={t("common.cancel")}
        destroyOnHidden
      >
        <p className={styles.moveHint}>{t("knowledgeBases.moveHint")}</p>
        <div className={styles.moveTree}>
          <Tree
            blockNode
            defaultExpandAll
            treeData={moveTreeData}
            selectedKeys={
              moveDestination === null
                ? []
                : [moveDestination || KNOWLEDGE_DOC_TREE_ROOT]
            }
            onSelect={(_keys, info) => {
              setMoveDestination(
                info.selected ? (info.node as DocTreeNode).path : null,
              );
            }}
          />
        </div>
      </Modal>
  );
}
