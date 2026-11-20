import { useLocalStorageState } from "ahooks";

/**
 * v2: thinking/tools collapse by default in every chat. The key is versioned
 * so browsers that stored the old "expanded" default pick up the new default.
 */
export const COLLAPSE_THINKING_SOLO_KEY = "octop:collapse-thinking:v2";
/** Team room preference (kept separate so toggling one does not affect the other). */
export const COLLAPSE_THINKING_TEAM_KEY = "octop:collapse-thinking:team:v2";

export function collapseThinkingStorageKey(isTeam: boolean): string {
  return isTeam ? COLLAPSE_THINKING_TEAM_KEY : COLLAPSE_THINKING_SOLO_KEY;
}

/**
 * Browser display preference for folding thinking/tool panels.
 * Team and solo chats use separate keys so toggling one does not affect the other.
 */
export function useCollapseThinking(isTeam = false) {
  return useLocalStorageState<boolean>(collapseThinkingStorageKey(isTeam), {
    defaultValue: true,
    listenStorageChange: true,
  });
}
