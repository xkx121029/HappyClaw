import { isRemoteShadowAgent } from "./remoteExpert";
import { isTeamAgent } from "./teamAgent";

/** Classic chat-nav filter under the search box. */
export type ChatNavScope = "sessions" | "projects" | "experts" | "teams" | "cloud";

/**
 * Tabs rendered under the search box. "cloud" is intentionally absent: cloud
 * collaboration is opened from its own entry and rendered as an internal view,
 * not as a peer category.
 */
export const CHAT_NAV_SCOPES: readonly ChatNavScope[] = [
  "sessions",
  "projects",
  "experts",
  "teams",
];

type NavAgent = {
  kind?: string | null;
  bridge?: boolean | null;
  agent_id?: string | null;
};

/**
 * Sessions first: a new visit lands on the cross-expert conversation list,
 * not on an expert directory. Projects / experts / teams remain one click away.
 */
export function initialChatNavScope(): ChatNavScope {
  return "sessions";
}

/**
 * "sessions" is the flat, cross-expert list and matches every agent.
 * "projects" also spans every agent — grouping happens in the list itself.
 * Experts include cloud experts. Teams include cloud teams.
 * Cloud is every remote shadow, expert or team.
 */
export function matchesChatNavScope(
  agent: NavAgent,
  scope: ChatNavScope,
): boolean {
  if (scope === "sessions" || scope === "projects") return true;
  if (scope === "cloud") return isRemoteShadowAgent(agent);
  if (scope === "teams") return isTeamAgent(agent);
  return !isTeamAgent(agent);
}
