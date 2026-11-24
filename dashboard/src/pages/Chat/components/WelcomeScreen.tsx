import { useState } from "react";
import { Button } from "antd";
import { useTranslation } from "react-i18next";
import { useWelcomeQuickCardsLayout } from "../hooks/useWelcomeQuickCardsLayout";
import WelcomeQuickCards, { WelcomeQuickCardProbe } from "./WelcomeQuickCards";
import styles from "../index.module.less";

// Animated WebP keeps alpha on Safari; VP9 WebM alpha is unreliable there.
const MASCOT_PEEK = "/happyclaw-mascot-peek.webp";
const MASCOT_TYPE = "/happyclaw-mascot-type.webp";
const MASCOT_IMAGES = [MASCOT_PEEK, MASCOT_TYPE];

function getRandomMascot(current?: string): string {
  if (MASCOT_IMAGES.length <= 1) return MASCOT_IMAGES[0];
  let next = current;
  // Avoid picking the same image twice in a row.
  while (next === current) {
    next = MASCOT_IMAGES[Math.floor(Math.random() * MASCOT_IMAGES.length)];
  }
  return next as string;
}

export interface WelcomeQuickCard {
  title: string;
  description: string;
  prompt: string;
  color: string;
  icon_name?: string | null;
  icon_url?: string | null;
  expertName?: string;
}

interface WelcomeScreenProps {
  onPromptClick: (text: string, options?: { prefill?: boolean }) => void;
  agentName?: string | null;
  welcomeSuffix?: string | null;
  quickCards: WelcomeQuickCard[];
  hideMascot?: boolean;
  isTeam?: boolean;
  /** 没有任何推荐卡片时，给一个直接聚焦输入框的动作。 */
  onStartChat?: () => void;
}

export default function WelcomeScreen({
  onPromptClick,
  agentName,
  welcomeSuffix,
  quickCards,
  hideMascot = false,
  isTeam = false,
  onStartChat,
}: WelcomeScreenProps) {
  const { t } = useTranslation();
  const [mascotSrc, setMascotSrc] = useState(MASCOT_PEEK);
  const {
    welcomeRef,
    headingRef,
    sectionTitleRef,
    probeRef,
    expanded,
    setExpanded,
    cards,
    showToggle,
    autoHideMascot,
  } = useWelcomeQuickCardsLayout(quickCards);

  const handleMascotClick = () => {
    setMascotSrc((prev) => getRandomMascot(prev));
  };

  const showMascot = !hideMascot && !autoHideMascot;

  return (
    <div className={styles.welcome} ref={welcomeRef}>
      <div className={styles.welcomeInner}>
        <div className={styles.welcomeHeading} ref={headingRef}>
          {showMascot && (
            <img
              className={styles.welcomeMascot}
              src={mascotSrc}
              alt=""
              draggable={false}
              onClick={handleMascotClick}
              role="button"
              tabIndex={0}
              title={t("chatWelcome.mascotSwitchHint")}
              aria-label="HappyClaw mascot"
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  handleMascotClick();
                }
              }}
            />
          )}
          <h1 className={styles.welcomeTitle}>
            {isTeam
              ? t("chatWelcome.teamHeading", {
                  name: agentName?.trim() || t("chatWelcome.teamNameFallback"),
                })
              : t("chatWelcome.greeting")}
          </h1>
          <p className={styles.welcomeSubtitle}>
            {isTeam ? (
              <span className={styles.welcomeSubtitleText}>
                {welcomeSuffix ?? t("chatWelcome.descriptionWithTeamSuffix")}
              </span>
            ) : agentName ? (
              <>
                <span className={styles.welcomeAgentLine}>
                  <span className={styles.welcomeAgentMention}>
                    @{agentName}
                  </span>
                </span>
                <span className={styles.welcomeSubtitleText}>
                  {welcomeSuffix ?? t("chatWelcome.descriptionWithAgentSuffix")}
                </span>
              </>
            ) : (
              t("chatWelcome.description")
            )}
          </p>
        </div>

        {quickCards.length > 0 ? (
          <WelcomeQuickCards
            cards={cards}
            showToggle={showToggle}
            expanded={expanded}
            onToggle={() => setExpanded((prev) => !prev)}
            onPromptClick={onPromptClick}
            sectionTitleRef={sectionTitleRef}
          />
        ) : onStartChat ? (
          <div className={styles.welcomeStart}>
            <Button type="primary" size="large" onClick={onStartChat}>
              {t("chatWelcome.startFirstChat", "开始第一个对话")}
            </Button>
            <p className={styles.welcomeStartHint}>
              {t(
                "chatWelcome.startFirstChatHint",
                "在下面的输入框里说一句话就行，之后可以随时新建会话。",
              )}
            </p>
          </div>
        ) : null}
      </div>

      {quickCards.length > 0 && <WelcomeQuickCardProbe probeRef={probeRef} />}
    </div>
  );
}
