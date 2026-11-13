import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Spin, Tooltip } from "antd";
import { FileCode2, PanelRight, RotateCw, Save, X } from "lucide-react";
import cx from "classnames";
import { workspaceApi } from "../../../api/modules/workspace";
import { apiErrorMessage } from "../../../utils/apiError";
import { message } from "@/utils/antdMessage";
import CodeEditor from "../../Agent/Workspace/components/CodeEditor";
import Splitter from "./Splitter";
import SoloToolTerminal from "./SoloTerminal";
import styles from "../solo.module.less";

interface SoloEditorPaneProps {
  agentId: string | null;
  agentReady: boolean;
  filePath: string | null;
  onCloseFile: () => void;
  terminalRatio: number;
  onTerminalRatioChange: (ratio: number) => void;
  /** 文件树被容器压掉时，用这个入口以浮层打开。 */
  treeFitted: boolean;
  onToggleTree: () => void;
}

function fileName(path: string): string {
  return path.replace(/\/+$/, "").split("/").pop() || path;
}

export default function SoloEditorPane({
  agentId,
  agentReady,
  filePath,
  onCloseFile,
  terminalRatio,
  onTerminalRatioChange,
  treeFitted,
  onToggleTree,
}: SoloEditorPaneProps) {
  const { t } = useTranslation();
  const [content, setContent] = useState("");
  const [original, setOriginal] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const columnRef = useRef<HTMLDivElement>(null);

  const dirty = !loading && !error && content !== original;

  useEffect(() => {
    if (!agentId || !filePath) {
      setContent("");
      setOriginal("");
      setError(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    workspaceApi
      .readWorkspaceFile(agentId, filePath)
      .then((result) => {
        if (cancelled) return;
        setContent(result.content);
        setOriginal(result.content);
      })
      .catch((err) => {
        if (cancelled) return;
        setContent("");
        setOriginal("");
        setError(apiErrorMessage(err, t("solo.fileReadFailed"), t));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [agentId, filePath, reloadKey, t]);

  const save = useCallback(async () => {
    if (!agentId || !filePath || saving) return;
    if (content === original) return;
    setSaving(true);
    try {
      await workspaceApi.createWorkspaceFile(agentId, filePath, content);
      setOriginal(content);
      message.success(t("solo.saved"));
    } catch (err) {
      message.error(apiErrorMessage(err, t("solo.saveFailed"), t));
    } finally {
      setSaving(false);
    }
  }, [agentId, content, filePath, original, saving, t]);

  const saveRef = useRef(save);
  saveRef.current = save;

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey)) return;
      if (event.key.toLowerCase() !== "s") return;
      event.preventDefault();
      void saveRef.current();
    };
    window.addEventListener("keydown", handler, true);
    return () => window.removeEventListener("keydown", handler, true);
  }, []);

  const handleTerminalDrag = useCallback(
    (delta: number) => {
      const height = columnRef.current?.getBoundingClientRect().height ?? 0;
      if (height <= 0) return;
      onTerminalRatioChange(terminalRatio - delta / height);
    },
    [onTerminalRatioChange, terminalRatio],
  );

  const editorBody = useMemo(() => {
    if (!agentId) {
      return (
        <div className={styles.panePlaceholder}>{t("solo.noAgentHint")}</div>
      );
    }
    if (!agentReady) {
      return (
        <div className={styles.panePlaceholder}>{t("solo.editorNotWired")}</div>
      );
    }
    if (!filePath) {
      return (
        <div className={styles.panePlaceholder}>
          <FileCode2 size={18} />
          <p>{t("solo.pickFileHint")}</p>
        </div>
      );
    }
    if (loading) {
      return (
        <div className={styles.panePlaceholder}>
          <Spin size="small" />
        </div>
      );
    }
    if (error) {
      return (
        <div className={styles.panePlaceholder}>
          <p className={styles.placeholderError}>{error}</p>
          <Button size="small" onClick={() => setReloadKey((key) => key + 1)}>
            {t("common.retry")}
          </Button>
        </div>
      );
    }
    return (
      <CodeEditor path={filePath} value={content} onChange={setContent} />
    );
  }, [agentId, agentReady, content, error, filePath, loading, t]);

  return (
    <section className={styles.editorColumn} ref={columnRef}>
      <div className={styles.editorPane}>
        <header className={styles.paneHeader}>
          <FileCode2 size={14} className={styles.headerIcon} />
          <span className={styles.paneTitle}>
            {filePath ? fileName(filePath) : t("solo.editor")}
          </span>
          {filePath ? (
            <span className={styles.panePath} title={filePath}>
              {filePath}
            </span>
          ) : null}
          {dirty ? <span className={styles.dirtyDot} title={t("solo.unsaved")} /> : null}
          <span className={styles.headerSpacer} />
          {filePath ? (
            <>
              <Tooltip title={t("solo.save")}>
                <Button
                  type="text"
                  size="small"
                  icon={<Save size={14} />}
                  loading={saving}
                  disabled={!dirty || !agentReady}
                  onClick={() => void save()}
                  aria-label={t("solo.save")}
                />
              </Tooltip>
              <Tooltip title={t("solo.closeFile")}>
                <Button
                  type="text"
                  size="small"
                  icon={<X size={14} />}
                  onClick={onCloseFile}
                  aria-label={t("solo.closeFile")}
                />
              </Tooltip>
            </>
          ) : null}
          {!treeFitted ? (
            <Tooltip title={t("solo.toggleFiles")}>
              <Button
                type="text"
                size="small"
                icon={<PanelRight size={14} />}
                onClick={onToggleTree}
                aria-label={t("solo.toggleFiles")}
              />
            </Tooltip>
          ) : null}
        </header>
        <div className={styles.editorBody}>{editorBody}</div>
      </div>

      <Splitter
        orientation="horizontal"
        onDelta={handleTerminalDrag}
        label={t("solo.resizeTerminal")}
      />

      <div
        className={cx(styles.terminalPane)}
        style={{ height: `${Math.round(terminalRatio * 1000) / 10}%` }}
      >
        <header className={styles.paneHeader}>
          <RotateCw size={13} className={styles.headerIcon} />
          <span className={styles.paneTitle}>{t("solo.terminal")}</span>
        </header>
        <div className={styles.terminalBody}>
          <SoloToolTerminal agentId={agentId} agentReady={agentReady} />
        </div>
      </div>
    </section>
  );
}
