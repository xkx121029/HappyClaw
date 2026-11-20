import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, Empty, Spin } from "antd";
import {
  ChevronDown,
  ChevronRight,
  FileText,
  Folder,
  FolderOpen,
  RefreshCw,
} from "lucide-react";
import { Link } from "react-router-dom";
import cx from "classnames";
import { workspaceApi } from "../../../api/modules/workspace";
import type { WorkspaceEntry } from "../../../api/types";
import { apiErrorMessage } from "../../../utils/apiError";
import styles from "../solo.module.less";

interface SoloFileTreeProps {
  agentId: string | null;
  agentReady: boolean;
  activePath: string | null;
  onOpenFile: (path: string) => void;
  /** 由外层资源管理器头部触发的刷新计数。 */
  refreshToken?: number;
  /** 外层已经提供标题栏时隐藏自带的「文件」头部。 */
  hideHeader?: boolean;
}

function entryName(path: string): string {
  return path.replace(/\/+$/, "").split("/").pop() || path;
}

function sortEntries(rows: WorkspaceEntry[]): WorkspaceEntry[] {
  return [...rows].sort((a, b) => {
    const dirDiff = Number(Boolean(b.is_dir)) - Number(Boolean(a.is_dir));
    if (dirDiff !== 0) return dirDiff;
    return entryName(a.path).localeCompare(entryName(b.path));
  });
}

export default function SoloFileTree({
  agentId,
  agentReady,
  activePath,
  onOpenFile,
  refreshToken = 0,
  hideHeader = false,
}: SoloFileTreeProps) {
  const { t } = useTranslation();
  const [entries, setEntries] = useState<Record<string, WorkspaceEntry[]>>({});
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [loadingPaths, setLoadingPaths] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [query, setQuery] = useState("");

  const loadDir = useCallback(
    async (path: string) => {
      if (!agentId) return;
      setLoadingPaths((prev) => [...prev.filter((p) => p !== path), path]);
      try {
        const rows = await workspaceApi.getAgentTree(agentId, path);
        setEntries((prev) => ({ ...prev, [path]: sortEntries(rows) }));
        setError(null);
      } catch (err) {
        setError(apiErrorMessage(err, t("solo.treeLoadFailed"), t));
      } finally {
        setLoadingPaths((prev) => prev.filter((p) => p !== path));
      }
    },
    [agentId, t],
  );

  useEffect(() => {
    setEntries({});
    setExpanded(new Set());
    setError(null);
    setQuery("");
    if (!agentId || !agentReady) return;
    void loadDir("/");
  }, [agentId, agentReady, loadDir]);

  const handleRefresh = useCallback(async () => {
    if (!agentId || !agentReady) return;
    setRefreshing(true);
    const openDirs = Array.from(expanded);
    setEntries((prev) => {
      const next: Record<string, WorkspaceEntry[]> = {};
      // 保留已展开目录的旧内容，刷新时整体重取，避免树闪烁成空。
      for (const key of openDirs) {
        if (prev[key]) next[key] = prev[key];
      }
      return next;
    });
    await loadDir("/");
    await Promise.all(openDirs.map((dir) => loadDir(dir)));
    setRefreshing(false);
  }, [agentId, agentReady, expanded, loadDir]);

  const refreshRef = useRef(handleRefresh);
  refreshRef.current = handleRefresh;

  // 外层头部的刷新按钮只改计数，避免把 handleRefresh 放进依赖导致重复刷新。
  useEffect(() => {
    if (refreshToken > 0) void refreshRef.current();
  }, [refreshToken]);

  const toggleDir = useCallback(
    (path: string) => {
      setExpanded((prev) => {
        const next = new Set(prev);
        if (next.has(path)) {
          next.delete(path);
        } else {
          next.add(path);
          if (!entries[path]) void loadDir(path);
        }
        return next;
      });
    },
    [entries, loadDir],
  );

  const flatMatches = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return null;
    const all = Object.values(entries).flat();
    const seen = new Set<string>();
    return all
      .filter((entry) => {
        if (seen.has(entry.path)) return false;
        seen.add(entry.path);
        return entryName(entry.path).toLowerCase().includes(needle);
      })
      .slice(0, 200);
  }, [entries, query]);

  const renderLevel = (path: string, depth: number): React.ReactNode[] =>
    (entries[path] ?? []).flatMap((entry) => {
      const isDir = Boolean(entry.is_dir);
      const isOpen = expanded.has(entry.path);
      const isLoading = loadingPaths.includes(entry.path);
      const name = entryName(entry.path);
      const row = (
        <button
          type="button"
          key={entry.path}
          className={cx(
            styles.treeRow,
            !isDir && entry.path === activePath && styles.treeRowActive,
          )}
          style={{ paddingLeft: 8 + depth * 12 }}
          onClick={() => (isDir ? toggleDir(entry.path) : onOpenFile(entry.path))}
          title={entry.path}
        >
          <span className={styles.treeChevron}>
            {isDir ? (
              isOpen ? (
                <ChevronDown size={12} />
              ) : (
                <ChevronRight size={12} />
              )
            ) : null}
          </span>
          {isDir ? (
            isOpen ? (
              <FolderOpen size={14} className={styles.treeDirIcon} />
            ) : (
              <Folder size={14} className={styles.treeDirIcon} />
            )
          ) : (
            <FileText size={14} className={styles.treeFileIcon} />
          )}
          <span className={styles.treeName}>{name}</span>
          {isLoading ? <Spin size="small" /> : null}
        </button>
      );
      if (isDir && isOpen) {
        return [row, ...renderLevel(entry.path, depth + 1)];
      }
      return [row];
    });

  const body = () => {
    if (!agentId) {
      return <div className={styles.panePlaceholder}>{t("solo.noAgentHint")}</div>;
    }
    if (!agentReady) {
      return (
        <div className={styles.panePlaceholder}>
          <p>{t("solo.workspaceNotWired")}</p>
          <Link to="/experts">
            <Button size="small">{t("solo.goExperts")}</Button>
          </Link>
        </div>
      );
    }
    if (error && Object.keys(entries).length === 0) {
      return (
        <div className={styles.panePlaceholder}>
          <p className={styles.placeholderError}>{error}</p>
          <Button size="small" onClick={() => void loadDir("/")}>
            {t("common.retry")}
          </Button>
        </div>
      );
    }
    if (flatMatches) {
      if (flatMatches.length === 0) {
        return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("solo.noMatches")} />;
      }
      return (
        <div className={styles.treeScroll}>
          {flatMatches.map((entry) => (
            <button
              type="button"
              key={`search-${entry.path}`}
              className={cx(
                styles.treeRow,
                entry.path === activePath && styles.treeRowActive,
              )}
              onClick={() => (entry.is_dir ? toggleDir(entry.path) : onOpenFile(entry.path))}
              title={entry.path}
            >
              {entry.is_dir ? (
                <Folder size={14} className={styles.treeDirIcon} />
              ) : (
                <FileText size={14} className={styles.treeFileIcon} />
              )}
              <span className={styles.treeName}>{entry.path}</span>
            </button>
          ))}
        </div>
      );
    }
    if (!entries["/"] && loadingPaths.includes("/")) {
      return (
        <div className={styles.panePlaceholder}>
          <Spin size="small" />
        </div>
      );
    }
    if (entries["/"] && entries["/"].length === 0) {
      return <div className={styles.panePlaceholder}>{t("solo.workspaceEmpty")}</div>;
    }
    return <div className={styles.treeScroll}>{renderLevel("/", 0)}</div>;
  };

  return (
    <aside className={styles.treePane}>
      {!hideHeader ? (
        <header className={styles.paneHeader}>
          <span className={styles.paneTitle}>{t("solo.files")}</span>
          <Button
            type="text"
            size="small"
            icon={<RefreshCw size={13} />}
            loading={refreshing}
            onClick={() => void handleRefresh()}
            disabled={!agentId || !agentReady}
            aria-label={t("solo.refreshFiles")}
          />
        </header>
      ) : null}
      <div className={styles.treeSearch}>
        <input
          className={styles.treeSearchInput}
          type="text"
          placeholder={t("solo.searchFiles")}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          disabled={!agentId || !agentReady}
          aria-label={t("solo.searchFiles")}
        />
      </div>
      {error && Object.keys(entries).length > 0 ? (
        <div className={styles.treeError}>{error}</div>
      ) : null}
      <div className={styles.treeBody}>{body()}</div>
    </aside>
  );
}
