import { request } from "@/api/request";
import type { OctopAgent } from "@/context/AgentContext";

export const HAPPYCLAW_EXPERT_ID = "happyclaw";

/** True when the built-in default expert is already present. */
export function hasHappyClawAgent(agents: OctopAgent[]): boolean {
  return agents.some(
    (agent) =>
      agent.agent_id === HAPPYCLAW_EXPERT_ID ||
      agent.template_name === HAPPYCLAW_EXPERT_ID,
  );
}

let inFlight: Promise<boolean> | null = null;

/**
 * Materialise the built-in HappyClaw expert for installs created before it
 * shipped. The endpoint is idempotent: an empty body reuses an existing agent
 * created from the same template. Returns ``false`` when the call fails so the
 * chat page can fall back to the previously stored expert instead of waiting
 * forever on a default that will never appear.
 */
export function ensureHappyClawAgent(): Promise<boolean> {
  if (inFlight) return inFlight;
  inFlight = request(`/agents/from-expert/${HAPPYCLAW_EXPERT_ID}`, {
    method: "POST",
    body: JSON.stringify({}),
  })
    .then(() => true)
    .catch(() => false);
  return inFlight;
}
