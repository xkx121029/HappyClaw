/**
 * Drawer listing the agents owned by one user, opened from the users list.
 */

import { Drawer, Empty, Spin } from "antd";
import { useTranslation } from "react-i18next";

import type { OctopAgent } from "../../../context/AgentContext";
import { AgentCard } from "../../Experts/components/AgentCard";
import expertStyles from "../../Experts/index.module.less";
import type { UserRow } from "./usersListTypes";

export function UserAgentsDrawer({
  user,
  agents,
  loading,
  onClose,
  onEditAgent,
  onDeleted,
  onStateChange,
  onRefreshAgents,
}: {
  user: UserRow | null;
  agents: OctopAgent[];
  loading: boolean;
  onClose: () => void;
  onEditAgent: (agent: OctopAgent | null) => void;
  onDeleted: (agentId: string) => void;
  onStateChange: (agentId: string, newState: string) => void;
  onRefreshAgents: () => void;
}) {
  const { t } = useTranslation();
  return (
    <Drawer
      title={
        user ? t("adminUsers.agentsDrawerTitle", { username: user.username }) : ""
      }
      open={user !== null}
      onClose={onClose}
      width={400}
      destroyOnHidden
    >
      <Spin spinning={loading}>
        {agents.length === 0 ? (
          <Empty description={t("adminUsers.noAgents")} />
        ) : (
          <div
            className={expertStyles.cardGrid}
            style={{
              gridTemplateColumns: "1fr",
              padding: "8px 0 24px",
            }}
          >
            {agents.map((agent) => (
              <AgentCard
                key={agent.agent_id}
                agent={agent}
                iconName={agent.icon_name}
                iconUrl={agent.icon_url}
                accentColor={agent.color}
                onEdit={(id) =>
                  onEditAgent(agents.find((a) => a.agent_id === id) ?? null)
                }
                onDeleted={onDeleted}
                onStateChange={onStateChange}
                onPollSettled={onRefreshAgents}
              />
            ))}
          </div>
        )}
      </Spin>
    </Drawer>
  );
}
