import { useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { Check, Folder, FolderX, X } from "lucide-react";
import cx from "classnames";
import { ExpertIcon } from "../../Experts/components/iconForName";
import { projectsApi, type Project } from "../../../api/modules/projects";
import { useFocusTrap } from "../../../hooks/useFocusTrap";
import styles from "./NewSessionSheet.module.less";

/** Minimal expert shape this picker needs (matches ``ChatAgentOption``). */
export interface NewSessionExpert {
  agent_id: string;
  name: string;
  icon_name?: string | null;
  icon_url?: string | null;
  color?: string | null;
  bridge_disconnected?: boolean;
}

interface NewSessionSheetProps {
  open: boolean;
  onClose: () => void;
  experts: NewSessionExpert[];
  activeAgentId: string | null;
  /** Create the conversation with this expert, optionally inside a project. */
  onStart: (agentId: string, projectId: string | null) => void;
}

/**
 * Mobile "new conversation" picker. Mirrors the desktop flow: pick any enabled
 * expert and, optionally, the project the conversation belongs to. Starting
 * lands on the new chat immediately so the composer is ready to type.
 */
export default function NewSessionSheet({
  open,
  onClose,
  experts,
  activeAgentId,
  onStart,
}: NewSessionSheetProps) {
  const { t } = useTranslation();
  const [agentId, setAgentId] = useState(activeAgentId ?? "");
  const [projectId, setProjectId] = useState<string | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [loadingProjects, setLoadingProjects] = useState(false);

  const sortedProjects = useMemo(
    () => projects.filter((project) => !project.is_default),
    [projects],
  );

  useEffect(() => {
    if (!open) return;
    setAgentId(activeAgentId ?? experts[0]?.agent_id ?? "");
    setProjectId(null);
    let cancelled = false;
    setLoadingProjects(true);
    projectsApi
      .list()
      .then((rows) => {
        if (!cancelled) setProjects(rows);
      })
      .catch(() => {
        if (!cancelled) setProjects([]);
      })
      .finally(() => {
        if (!cancelled) setLoadingProjects(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, activeAgentId, experts]);

  // Esc, focus containment and focus restore for the sheet.
  const trapRef = useFocusTrap<HTMLDivElement>(open, onClose);

  const handleStart = useCallback(() => {
    if (!agentId) return;
    onStart(agentId, projectId);
  }, [agentId, projectId, onStart]);

  if (!open) return null;

  return createPortal(
    <div className={styles.root} role="presentation">
      <div className={styles.backdrop} role="presentation" onClick={onClose} />
      <div
        ref={trapRef}
        className={styles.panel}
        role="dialog"
        aria-modal="true"
        aria-label={t("chat.newSessionTitle", "新建会话")}
        tabIndex={-1}
      >
        <div className={styles.grabZone}>
          <span className={styles.grabber} aria-hidden />
        </div>
        <header className={styles.header}>
          <h2 className={styles.title}>
            {t("chat.newSessionTitle", "新建会话")}
          </h2>
          <button
            type="button"
            className={styles.closeBtn}
            onClick={onClose}
            aria-label={t("common.close", "关闭")}
          >
            <X size={18} strokeWidth={1.9} />
          </button>
        </header>

        <div className={styles.body}>
          <section className={styles.section}>
            <h3 className={styles.sectionTitle}>
              {t("chat.newSessionExpert", "选择专家")}
            </h3>
            <div className={styles.expertList}>
              {experts.map((expert) => {
                const active = expert.agent_id === agentId;
                const accent = expert.color || "var(--fn-color-brand)";
                return (
                  <button
                    key={expert.agent_id}
                    type="button"
                    className={cx(styles.row, active && styles.rowActive)}
                    onClick={() => setAgentId(expert.agent_id)}
                    aria-pressed={active}
                  >
                    <span
                      className={styles.avatar}
                      style={{
                        color: accent,
                        background: `${accent}14`,
                        boxShadow: `0 0 0 1px ${accent}22`,
                      }}
                    >
                      <ExpertIcon
                        iconUrl={expert.icon_url}
                        iconName={expert.icon_name ?? null}
                        size={expert.icon_url?.trim() ? 24 : 16}
                      />
                    </span>
                    <span className={styles.rowName}>{expert.name}</span>
                    {expert.bridge_disconnected ? (
                      <span className={styles.rowHint}>
                        {t("chat.remoteDisconnected", "远端离线")}
                      </span>
                    ) : null}
                    {active ? (
                      <Check
                        size={18}
                        strokeWidth={2.2}
                        className={styles.check}
                      />
                    ) : null}
                  </button>
                );
              })}
              {experts.length === 0 ? (
                <p className={styles.empty}>
                  {t("chat.newSessionNoExperts", "还没有可用的专家。")}
                </p>
              ) : null}
            </div>
          </section>

          <section className={styles.section}>
            <h3 className={styles.sectionTitle}>
              {t("chat.newSessionProject", "项目归属")}
              <span className={styles.optional}>
                {t("mobileConnect.optional", "可选")}
              </span>
            </h3>
            <div className={styles.expertList}>
              <button
                type="button"
                className={cx(
                  styles.row,
                  projectId === null && styles.rowActive,
                )}
                onClick={() => setProjectId(null)}
                aria-pressed={projectId === null}
              >
                <span className={styles.avatarNeutral}>
                  <FolderX size={16} strokeWidth={1.8} />
                </span>
                <span className={styles.rowName}>
                  {t("chat.newSessionNoProject", "不归入项目")}
                </span>
                {projectId === null ? (
                  <Check size={18} strokeWidth={2.2} className={styles.check} />
                ) : null}
              </button>
              {sortedProjects.map((project) => {
                const active = project.project_id === projectId;
                return (
                  <button
                    key={project.project_id}
                    type="button"
                    className={cx(styles.row, active && styles.rowActive)}
                    onClick={() => setProjectId(project.project_id)}
                    aria-pressed={active}
                  >
                    <span className={styles.avatarNeutral}>
                      <Folder size={16} strokeWidth={1.8} />
                    </span>
                    <span className={styles.rowName}>{project.name}</span>
                    {project.root_dir ? (
                      <span className={styles.rowHint}>{project.root_dir}</span>
                    ) : null}
                    {active ? (
                      <Check
                        size={18}
                        strokeWidth={2.2}
                        className={styles.check}
                      />
                    ) : null}
                  </button>
                );
              })}
              {!loadingProjects && sortedProjects.length === 0 ? (
                <p className={styles.empty}>
                  {t(
                    "chat.newSessionNoProjects",
                    "还没有项目；选择「不归入项目」即可直接开始。",
                  )}
                </p>
              ) : null}
            </div>
          </section>
        </div>

        <footer className={styles.footer}>
          <button
            type="button"
            className={styles.startBtn}
            onClick={handleStart}
            disabled={!agentId}
          >
            {t("chat.newSessionStart", "开始新会话")}
          </button>
        </footer>
      </div>
    </div>,
    document.body,
  );
}
