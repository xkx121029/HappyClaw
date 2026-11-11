import { useCallback, useState } from "react";
import { Button, message, Result } from "antd";
import cx from "classnames";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { request } from "../../../api/request";
import { apiErrorMessage } from "../../../utils/apiError";
import { useAgent } from "../../../context/AgentContext";
import { OctopEmptyMascot } from "../../../components/EmptyState";
import type { OctopAgent } from "../../../context/AgentContext";
import {
  formatAgentError,
  isAgentModelConfigError,
} from "../../../utils/agentError";
import styles from "../index.module.less";
import ModelConfigEmpty from "./ModelConfigEmpty";

interface AgentNotReadyScreenProps {
  agent: OctopAgent | null;
  noAgents?: boolean;
  loading?: boolean;
  /** Whether this user may open the model settings themselves. */
  canConfigureModels?: boolean;
  /**
   * Whether at least one usable model exists. ``undefined`` means the list is
   * not known yet, so the screen keeps the enable card instead of claiming the
   * setup is incomplete.
   */
  hasUsableModels?: boolean;
}

export default function AgentNotReadyScreen({
  agent,
  noAgents = false,
  loading = false,
  canConfigureModels = true,
  hasUsableModels,
}: AgentNotReadyScreenProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { refresh } = useAgent();
  const [enabling, setEnabling] = useState(false);

  const handleEnable = useCallback(async () => {
    if (!agent) return;
    setEnabling(true);
    try {
      await request(`/agents/${agent.agent_id}/start`, { method: "POST" });
      message.success(t("chat.enableExpertStarted", { name: agent.name }));
      await refresh({ silent: true, force: true });
    } catch (error) {
      message.error(
        apiErrorMessage(
          error,
          t("chat.enableExpertFailed", "启用专家失败，请重试。"),
          t,
        ),
      );
    } finally {
      setEnabling(false);
    }
  }, [agent, refresh, t]);

  if (loading) {
    return (
      <div className={styles.agentNotReady}>
        <div
          className={styles.messageSkeleton}
          role="status"
          aria-busy="true"
          aria-label={t("chat.loadingAgents", "正在加载专家")}
        >
          <div className={styles.messageSkeletonRow}>
            <div className={styles.messageSkeletonAvatar} />
            <div className={styles.messageSkeletonBody}>
              <div
                className={styles.messageSkeletonLine}
                style={{ width: "70%" }}
              />
              <div
                className={styles.messageSkeletonLine}
                style={{ width: "48%" }}
              />
            </div>
          </div>
          <div
            className={cx(
              styles.messageSkeletonRow,
              styles.messageSkeletonRowUser,
            )}
          >
            <div className={styles.messageSkeletonBody}>
              <div
                className={styles.messageSkeletonBubble}
                style={{ width: "42%", marginLeft: "58%", height: 30 }}
              />
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (noAgents) {
    return (
      <div className={styles.noAgentsEmpty}>
        <div className={styles.noAgentsEmptyInner}>
          <div className={styles.noAgentsEmptyIcon}>
            <OctopEmptyMascot className={styles.noAgentsEmptyMascot} />
          </div>
          <h1 className={styles.noAgentsEmptyTitle}>
            {t("chat.noAgentsTitle")}
          </h1>
          <p className={styles.noAgentsEmptyHint}>{t("chat.noAgentsHint")}</p>
          <Button
            type="primary"
            size="large"
            onClick={() => navigate("/experts")}
          >
            {t("chat.createExpert")}
          </Button>
        </div>
      </div>
    );
  }

  if (!agent) {
    return (
      <div className={styles.agentNotReady}>
        <Result status="info" title={t("chat.pickAgent")} />
      </div>
    );
  }

  const state = agent.state;
  const errorText = formatAgentError(agent.last_error, t);
  const isModelError = isAgentModelConfigError(agent.last_error);
  const disconnected = Boolean(agent.bridge && agent.bridge_disconnected);

  /**
   * "No model configured" reaches us as an agent start failure, so this screen
   * used to answer a setup step with a red cross and "专家启动失败" — the exact
   * alarm reserved for a broken agent. Nothing failed here: the friendly
   * prompt already exists for that case, so show it. A disconnected bridge
   * still wins, because that is the state the user has to act on right now and
   * last_error may only be a leftover.
   */
  if (state === "failed" && isModelError && !disconnected) {
    return <ModelConfigEmpty canConfigure={canConfigureModels} />;
  }

  /**
   * First launch often has an expert created but not started. Two distinct
   * setup steps deserve two distinct answers: no model at all sends the user
   * to model settings, while a configured model offers a one-click start
   * right here instead of bouncing to the experts page.
   */
  if (hasUsableModels === false && !disconnected) {
    return <ModelConfigEmpty canConfigure={canConfigureModels} />;
  }

  if ((state === "stopped" || state === "created") && !disconnected) {
    return (
      <div className={styles.agentNotReady}>
        <div className={styles.agentEnableCard}>
          <h1 className={styles.agentEnableTitle}>
            {t("chat.enableExpertTitle", "这个专家还没启用")}
          </h1>
          <p className={styles.agentEnableHint}>
            {t(
              "chat.enableExpertHint",
              "启用后就能开始对话，已有的配置和会话都会保留。",
            )}
          </p>
          <Button
            type="primary"
            size="large"
            loading={enabling}
            onClick={handleEnable}
          >
            {t("chat.enableExpert", "启用这个专家")}
          </Button>
        </div>
      </div>
    );
  }

  let title = t("chat.agentNotRunning");
  let subTitle = t("chat.agentNotRunningHint");

  if (disconnected) {
    const inbound = Boolean(agent.bridge_inbound);
    title = t("chat.remoteExpert.disconnectedTitle");
    subTitle = inbound
      ? agent.bridge_connection_name
        ? t("chat.remoteExpert.waitForPeerNamed", {
            name: agent.bridge_connection_name,
          })
        : t("chat.remoteExpert.waitForPeer")
      : agent.bridge_connection_name
      ? t("chat.remoteExpert.disconnectedHintNamed", {
          name: agent.bridge_connection_name,
        })
      : t("chat.remoteExpert.disconnectedHint");
  } else if (state === "failed") {
    title = t("chat.agentFailed");
    subTitle = errorText || t("chat.agentFailedHint");
  } else if (state === "stopped" || state === "created") {
    title = t("chat.agentNotRunning");
    subTitle = t("chat.agentNotRunningHint");
  } else if (state === "starting" || state === "stopping") {
    title = t("chat.agentStarting");
    subTitle = t("chat.agentStartingHint");
  }

  return (
    <div className={styles.agentNotReady}>
      <Result
        status={
          disconnected
            ? "warning"
            : state === "failed"
            ? "error"
            : state === "stopped" || state === "created"
            ? "warning"
            : "info"
        }
        title={title}
        subTitle={subTitle}
        extra={
          disconnected ? (
            <Button type="primary" onClick={() => navigate("/bridge")}>
              {t(
                agent.bridge_inbound
                  ? "chat.remoteExpert.openBridge"
                  : "chat.remoteExpert.reconnect",
              )}
            </Button>
          ) : (
            <Button type="primary" onClick={() => navigate("/experts")}>
              {t("chat.goToExperts")}
            </Button>
          )
        }
      />
    </div>
  );
}
