import { Pin } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { Mascot, mascotStatusInk } from "../Mascot";
import { useBao } from "./BaoContext";
import styles from "./Bao.module.less";

interface ProjectBaoRowProps {
  projectKey: string;
  projectName: string;
}

/**
 * The per-project Bao conversation. Rendered as the first, pinned row of every
 * project in the chat session list so it reads as that project's top
 * conversation; opening it targets this project's scope explicitly instead of
 * re-inferring from the route.
 */
export default function ProjectBaoRow({
  projectKey,
  projectName,
}: ProjectBaoRowProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { tasks, name, appearance } = useBao();
  const running = tasks.filter(
    (task) =>
      task.projectKey === projectKey &&
      (task.status === "running" || task.status === "awaiting"),
  ).length;

  return (
    <button
      type="button"
      className={styles.projectBaoRow}
      data-testid="chat-project-bao"
      data-project-key={projectKey}
      aria-label={t("bao.projectEntry.open", { project: projectName })}
      onClick={() =>
        navigate(`/bao?project=${encodeURIComponent(projectKey)}`)
      }
    >
      <Pin size={12} className={styles.projectBaoPin} aria-hidden />
      <Mascot
        size={18}
        {...appearance}
        color={mascotStatusInk(appearance, running > 0 ? "working" : null)}
        state={running > 0 ? "working" : "idle"}
        className={styles.projectBaoGlyph}
        surface="var(--fn-bg-sidebar)"
      />
      <span className={styles.projectBaoLabel}>
        {t("bao.projectEntry.labelNamed", { name })}
      </span>
      {running > 0 ? (
        <span className={styles.projectBaoState}>
          {t("bao.projectEntry.running", { count: running })}
        </span>
      ) : null}
    </button>
  );
}
