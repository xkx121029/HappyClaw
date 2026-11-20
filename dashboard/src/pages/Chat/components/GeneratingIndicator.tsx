import { useTranslation } from "react-i18next";
import { useElapsedSince } from "../../../hooks/useElapsedSeconds";
import { useAgent } from "../../../context/AgentContext";
import { isTeamAgent, isTeamHostSpeaker } from "../../../utils/teamAgent";
import { rewritePeerSpeakerId } from "../../../utils/remoteExpert";
import {
  Mascot,
  mascotStatusInk,
  useMascotAppearance,
} from "../../../components/Mascot";
import type { MascotState } from "../../../components/Mascot";
import { ExpertMessageAvatar } from "./MessageSender";
import styles from "../index.module.less";

interface GeneratingIndicatorProps {
  /**
   * Real stage of the turn: before the first token we are ``thinking``; once
   * content or tool calls stream in we are ``working``.
   */
  phase?: "thinking" | "working";
  /** When set, appends elapsed seconds (useful while waiting for the first token). */
  startedAt?: number | null;
  showElapsed?: boolean;
  /**
   * Host turn already settled; only team members (or late peers) are still
   * producing — softer named copy.
   */
  membersOnly?: boolean;
  /** Named speakers still generating (e.g. ["临床助手"]). */
  speakerNames?: ReadonlyArray<string>;
  /** Expert whose reply has not drawn a row yet. Keeps the avatar from popping in later. */
  showAvatar?: boolean;
  agentId?: string | null;
}

/**
 * The engine's own ``thinking`` morph collapses the body into three dots, so
 * the wait-for-first-token phase borrows ``curious`` (body + eyes stay on
 * screen) instead. ``working`` already keeps the body and is used as-is.
 */
const PHASE_MASCOT: Record<"thinking" | "working", MascotState> = {
  thinking: "curious",
  working: "working",
};

/**
 * Bottom-left live status for the turn. Stop/cancel stays on the composer —
 * this row is status text only so it can remain visible the whole time.
 */
function GeneratingAvatar({ agentId }: { agentId?: string | null }) {
  const { t } = useTranslation();
  const { agents, activeAgent } = useAgent();
  const isTeamRoom = isTeamAgent(activeAgent);
  const speakerId =
    rewritePeerSpeakerId(activeAgent?.agent_id, agentId) ||
    agentId ||
    activeAgent?.agent_id;
  const hostSpeaker = isTeamHostSpeaker(
    isTeamRoom,
    speakerId,
    activeAgent?.agent_id,
  );
  const expert =
    (speakerId && agents.find((item) => item.agent_id === speakerId)) ||
    (!isTeamRoom || hostSpeaker ? activeAgent : undefined);
  const avatarProfileId = hostSpeaker
    ? activeAgent?.agent_id
    : speakerId || undefined;
  if (!expert && !avatarProfileId) return null;
  const avatarTooltip = hostSpeaker
    ? t("chat.teamHostHover", {
        name: activeAgent?.name || expert?.name || "",
      })
    : expert?.name || undefined;
  return (
    <div className={styles.avatarCol}>
      <ExpertMessageAvatar
        name={expert?.name || avatarProfileId}
        color={expert?.color}
        iconName={expert?.icon_name}
        iconUrl={expert?.icon_url}
        tooltip={avatarTooltip}
        profileAgentId={avatarProfileId}
      />
    </div>
  );
}

export default function GeneratingIndicator({
  phase = "thinking",
  startedAt = null,
  showElapsed = false,
  membersOnly = false,
  speakerNames = [],
  showAvatar = false,
  agentId = null,
}: GeneratingIndicatorProps) {
  const { t } = useTranslation();
  const baoLook = useMascotAppearance();
  const elapsedAnchor =
    startedAt != null && startedAt > 0 ? startedAt : Date.now();
  const elapsed = useElapsedSince(elapsedAnchor);
  const showTimer = Boolean(
    !membersOnly && showElapsed && startedAt != null && startedAt > 0,
  );

  const named = speakerNames.filter((n) => n.trim());
  let label: string;
  if (membersOnly || named.length > 0) {
    if (named.length === 1) {
      label = t("chat.memberResponding", {
        name: named[0],
        defaultValue: "{{name}} 正在回答",
      });
    } else if (named.length > 1) {
      label = t("chat.membersRespondingNamed", {
        names: named.join(t("chat.nameJoin", { defaultValue: "、" })),
        defaultValue: "{{names}} 正在回答",
      });
    } else {
      label = t("chat.membersResponding", {
        defaultValue: "成员回答中",
      });
    }
  } else if (showTimer) {
    label = t("chat.generatingWithElapsed", {
      seconds: elapsed,
      defaultValue: "生成中 · {{seconds}}s",
    });
  } else {
    label = t("chat.generating", "生成中");
  }

  return (
    <div className={styles.turnInset}>
      <div className={styles.generatingIndicator}>
        {showAvatar ? <GeneratingAvatar agentId={agentId} /> : null}
        <div
          className={styles.generatingStatus}
          role="status"
          aria-live="polite"
        >
          <Mascot
            size={18}
            color={mascotStatusInk(baoLook, phase === "working" ? "working" : null)}
            state={PHASE_MASCOT[phase]}
            className={styles.generatingMascot}
            surface="var(--fn-bg-layout, var(--fn-bg-base))"
          />
          <span className={styles.thinkingDot} />
          <span className={styles.thinkingDot} />
          <span className={styles.thinkingDot} />
          <span className={styles.generatingText}>{label}</span>
        </div>
      </div>
    </div>
  );
}
