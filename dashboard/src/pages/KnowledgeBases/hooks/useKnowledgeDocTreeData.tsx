import { useMemo } from "react";
import { Folder } from "lucide-react";
import type { TFunction } from "i18next";

import type { KnowledgeDocument } from "../../../api/modules/knowledgeBases";
import {
  buildKnowledgeFileTree,
  canMoveKnowledgeEntryTo,
  KNOWLEDGE_DOC_TREE_ROOT,
  type KnowledgeFileTreeNode,
} from "../knowledgeFolder";
import type { DocTreeNode } from "../knowledgeDocTree";
import styles from "../index.module.less";

export interface UseKnowledgeDocTreeDataArgs {
  t: TFunction;
  documents: KnowledgeDocument[];
  moveTarget: KnowledgeDocument | null;
}

/** Folder tree for the sidebar, plus the same tree with invalid move targets disabled. */
export function useKnowledgeDocTreeData({
  t,
  documents,
  moveTarget,
}: UseKnowledgeDocTreeDataArgs) {
  const docTreeData = useMemo(() => {
    const toAntd = (node: KnowledgeFileTreeNode): DocTreeNode => ({
      key: node.path,
      path: node.path,
      isDir: true,
      isLeaf: !node.children?.length,
      title: (
        <span className={styles.docTreeNode}>
          <Folder size={13} className={styles.docTreeFolderIcon} aria-hidden />
          <span className={styles.docTreeName} title={node.name}>
            {node.name}
          </span>
        </span>
      ),
      children: node.children?.length ? node.children.map(toAntd) : undefined,
    });
    const root: DocTreeNode = {
      key: KNOWLEDGE_DOC_TREE_ROOT,
      path: "",
      isDir: true,
      isLeaf: false,
      title: (
        <span className={styles.docTreeNode}>
          <Folder size={13} className={styles.docTreeFolderIcon} aria-hidden />
          <span className={styles.docTreeName}>
            {t("knowledgeBases.documents")}
          </span>
        </span>
      ),
      children: buildKnowledgeFileTree(documents).map(toAntd),
    };
    return [root];
  }, [documents, t]);

  /** The folder tree again, with the places `moveTarget` cannot go greyed out. */
  const moveTreeData = useMemo(() => {
    if (!moveTarget) return [];
    const mark = (node: DocTreeNode): DocTreeNode => ({
      ...node,
      disabled: !canMoveKnowledgeEntryTo(moveTarget, node.path),
      children: (node.children as DocTreeNode[] | undefined)?.map(mark),
    });
    return docTreeData.map(mark);
  }, [docTreeData, moveTarget]);

  return { docTreeData, moveTreeData };
}
