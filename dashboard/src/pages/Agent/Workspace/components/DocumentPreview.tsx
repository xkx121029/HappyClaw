/**
 * DocumentPreview — workspace wrapper around ``DocumentPreviewCore``.
 *
 * Bytes are fetched through the authenticated ``requestBlob`` helper.
 */

import { useCallback } from "react";
import { App } from "antd";
import { useTranslation } from "react-i18next";
import DocumentPreviewCore from "../../../../components/DocumentPreviewCore";
import { requestBlob } from "../../../../api/request";
import { apiErrorMessage } from "../../../../utils/apiError";
import { saveBlobAsFile } from "../../../../utils/saveBlobAsFile";
import { withFromWorkspace } from "../../../../utils/fromWorkspace";
import type { DocKind } from "../utils/docKind";
import styles from "../index.module.less";

interface DocumentPreviewProps {
  agentId?: string;
  /** Conversation whose project/session directory holds the document. */
  threadId?: string | null;
  path: string;
  kind: DocKind;
  /** Workspace UI paths use true; chat/tool paths use false. */
  fromWorkspace?: boolean;
  fetchUrl?: string;
}

function documentDownloadUrl(
  agentId: string,
  path: string,
  fromWorkspace: boolean,
  threadId?: string | null,
): string {
  const scope = threadId ? `&thread_id=${encodeURIComponent(threadId)}` : "";
  const url = `/agents/${encodeURIComponent(
    agentId,
  )}/workspace/download?path=${encodeURIComponent(path)}${scope}`;
  return fromWorkspace ? withFromWorkspace(url) : `${url}&from_workspace=false`;
}

export default function DocumentPreview({
  agentId,
  threadId,
  path,
  kind,
  fromWorkspace = true,
  fetchUrl,
}: DocumentPreviewProps) {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const apiPath =
    fetchUrl || documentDownloadUrl(agentId ?? "", path, fromWorkspace, threadId);
  const filename = path.split("/").filter(Boolean).pop() || path;

  const fetchBlob = useCallback(
    (
      onProgress?: (loaded: number, total: number) => void,
      signal?: AbortSignal,
    ) => requestBlob(apiPath, { signal }, onProgress),
    [apiPath],
  );

  const onDownload = useCallback(async () => {
    try {
      const blob = await requestBlob(apiPath);
      await saveBlobAsFile(blob, filename);
    } catch (error) {
      message.error(apiErrorMessage(error, t("workspace.downloadFailed"), t));
    }
  }, [apiPath, filename, message, t]);

  return (
    <div className={styles.documentPreview}>
      <DocumentPreviewCore
        kind={kind}
        filename={filename}
        fetchBlob={fetchBlob}
        onDownload={onDownload}
      />
    </div>
  );
}
