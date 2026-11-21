import { createFileRoute } from "@tanstack/react-router";

import { AgentConfigPage } from "@/features/agent-config/AgentConfigPage";

export const Route = createFileRoute("/_app/agent-config")({
  component: AgentConfigPage,
});
