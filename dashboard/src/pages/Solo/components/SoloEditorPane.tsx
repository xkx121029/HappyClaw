import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import { Button, Spin, Tooltip } from "antd";
import {
  FileCode2,
  Globe,
  Loader2,
  PanelRight,
  RefreshCw,
  Save,
  X,
} from "lucide-react";
import cx from "classnames";
import { workspaceApi } from "../../../api/modules/workspace";
import { apiErrorMessage } from "../../../utils/apiError";
import { message } from "@/utils/antdMessage";
import CodeEditor from "../../Agent/Workspace/components/CodeEditor";
import Splitter from "./Splitter";
import SoloToolTerminal from "./SoloTerminal";
import SoloBrowserPane from "./SoloBrowserPane";
import styles from "../solo.module.less";

interface SoloEditorPaneProps {
  agentId: string | null;
  agentReady: boolean;
  /** 浏览器预览要按会话找 agent 打开的页面。 */
  threadId: string | null;
  bridgeConnectionId?: string | null;
  filePath: string | null;
  onCloseFile: () => void;
  terminalRatio: number;
  onTerminalRatioChange: (ratio: number) => void;
  /** 文件树被容器压掉时，用这个入口以浮层打开。 */
  treeFitted: boolean;
  onToggleTree: () => void;
  /** 当前页签视图由外层控制。 */
  view: "editor" | "browser";
  onViewChange: (view: "editor" | "browser") => void;
}

function fileName(path: string): string {
  return path.replace(/\/+$/, "").split("/").pop() || path;
}

/** 中间栏：编辑器（顶部文件页签）+ 终端，两个区域之间可拖拽调高。 */
export default function SoloEditorPane({
  agentId,
  agentReady,
  threadId,
  bridgeConnectionId,
  filePath,
  onCloseFile,
  terminalRatio,
  onTerminalRatioChange,
  treeFitted,
  onToggleTree,
  view,
  onViewChange,
}: SoloEditorPaneProps) {
  const { t } = useTranslation();
  // 打开过浏览器页签后保持挂载，切回文件时不重复建立浏览器流。
  const [browserOpened, setBrowserOpened] = useState(false);
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

  // 从文件树里点开文件时回到编辑器，避免停在浏览器页签看不到内容。
  useEffect(() => {
    if (filePath) onViewChange("editor");
  }, [filePath, onViewChange]);

  // 外部（顶栏/命令面板）切到浏览器时也要挂载预览。
  useEffect(() => {
    if (view === "browser") setBrowserOpened(true);
  }, [view]);

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

  const breadcrumb = useMemo(() => {
    if (!filePath) return null;
    const parts = filePath.split("/").filter(Boolean);
    return (
      <div className={styles.fileBreadcrumb}>
        <span className={styles.crumbs}>
          {parts.map((part, index) => (
            <Fragment key={`${index}-${part}`}>
              {index > 0 ? <span>/</span> : null}
              {index === parts.length - 1 ? <b>{part}</b> : <span>{part}</span>}
            </Fragment>
          ))}
        </span>
      </div>
    );
  }, [filePath]);

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
    return <CodeEditor path={filePath} value={content} onChange={setContent} />;
  }, [agentId, agentReady, content, error, filePath, loading, t]);

  return (
    <section className={styles.editorColumn} ref={columnRef}>
      <div className={styles.editorPane}>
        <div className={styles.editorTabs}>
          {filePath ? (
            <div
              className={cx(
                styles.editorTab,
                view === "editor" && styles.editorTabActive,
              )}
              title={filePath}
              role="tab"
              aria-selected={view === "editor"}
              tabIndex={0}
              onClick={() => onViewChange("editor")}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onViewChange("editor");
                }
              }}
            >
              <FileCode2 size={13} className={styles.editorTabIcon} />
              <span className={styles.editorTabName}>
                {fileName(filePath)}
              </span>
              {dirty ? (
                <span className={styles.dirtyDot} title={t("solo.unsaved")} />
              ) : null}
              <button
                type="button"
                className={styles.editorTabClose}
                onClick={onCloseFile}
                aria-label={t("solo.closeFile")}
              >
                <X size={12} />
              </button>
            </div>
          ) : (
            <div
              className={cx(styles.editorTab, styles.editorTabPlaceholder)}
              title={t("solo.noOpenFile")}
            >
              <FileCode2 size={13} className={styles.editorTabIcon} />
              <span className={styles.editorTabName}>
                {t("solo.noOpenFile")}
              </span>
            </div>
          )}

          <button
            type="button"
            className={cx(
              styles.editorTab,
              view === "browser" && styles.editorTabActive,
            )}
            onClick={() => {
              setBrowserOpened(true);
              onViewChange("browser");
            }}
            title={t("solo.browserTab")}
          >
            <Globe size={13} className={styles.editorTabIcon} />
            <span className={styles.editorTabName}>{t("solo.browserTab")}</span>
          </button>

          <span className={styles.headerSpacer} />

          {view === "editor" && filePath ? (
            <>
              <Tooltip title={t("solo.save")}>
                <button
                  type="button"
                  className={styles.toolIconButton}
                  onClick={() => void save()}
                  disabled={!dirty || !agentReady || saving}
                  aria-label={t("solo.save")}
                >
                  {saving ? (
                    <Loader2 size={14} className={styles.spin} />
                  ) : (
                    <Save size={14} />
                  )}
                </button>
              </Tooltip>
              <Tooltip title={t("solo.reloadFile")}>
                <button
                  type="button"
                  className={styles.toolIconButton}
                  onClick={() => setReloadKey((key) => key + 1)}
                  aria-label={t("solo.reloadFile")}
                >
                  <RefreshCw size={14} />
                </button>
              </Tooltip>
            </>
          ) : null}
          {!treeFitted ? (
            <Tooltip title={t("solo.toggleFiles")}>
              <button
                type="button"
                className={styles.toolIconButton}
                onClick={onToggleTree}
                aria-label={t("solo.toggleFiles")}
              >
                <PanelRight size={14} />
              </button>
            </Tooltip>
          ) : null}
        </div>
        {breadcrumb}
        <div className={styles.editorBody}>
          {browserOpened ? (
            <div
              className={styles.browserPane}
              style={{ display: view === "browser" ? "flex" : "none" }}
            >
              <SoloBrowserPane
                threadId={threadId}
                agentReady={agentReady}
                bridgeConnectionId={bridgeConnectionId}
              />
            </div>
          ) : null}
          {view === "editor" ? editorBody : null}
        </div>
      </div>

      <Splitter
        orientation="horizontal"
        onDelta={handleTerminalDrag}
        label={t("solo.resizeTerminal")}
      />

      <div
        className={styles.terminalPane}
        style={{ height: `${Math.round(terminalRatio * 1000) / 10}%` }}
      >
        <SoloToolTerminal agentId={agentId} agentReady={agentReady} />
      </div>
    </section>
  );
}
