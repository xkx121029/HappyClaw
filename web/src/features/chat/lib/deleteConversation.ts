/**
 * Delete one conversation (ported from `dashboard/src/pages/Chat/utils/
 * deleteConversation.tsx`).
 *
 * Only the request is here. The old file also opened an antd confirm dialog
 * with the compact / delete-only choice; that dialog is UI, so it belongs to
 * the component layer (`confirmDeleteConversation` was not ported).
 */
import type { TFunction } from "i18next";

import { apiErrorMessage, parseApiError } from "./apiError";
import { message as antMessage } from "./message";
import { octopThreadsApi, type ThreadDeleteResult } from "./octopThreads";

function deleteResultText(
  t: TFunction,
  compact: boolean,
  result: ThreadDeleteResult | undefined,
): string {
  if (compact && result?.compacted) return t("chat.deleteSessionCompacted");
  if (compact) return t("chat.deleteSessionCompactLater");
  return t("chat.deleteSessionLater");
}

/**
 * ``true`` when the thread was deleted.
 * ``null`` when DELETE returned 409 ``THREAD_TURN_ACTIVE`` — the thread stays,
 * and the confirmation dialog must stay open.
 * ``false`` for any other failure.
 */
export type DeleteConversationResult = boolean | null;

/** Delete one conversation. ``compact`` rebuilds the database before returning. */
export async function deleteConversation(
  agentId: string,
  threadId: string,
  compact: boolean,
  t: TFunction,
): Promise<DeleteConversationResult> {
  const closeLoading = compact
    ? antMessage.loading(t("chat.deleteSessionCompacting"))
    : undefined;
  try {
    const result = await octopThreadsApi.delete(agentId, threadId, compact);
    closeLoading?.();
    antMessage.success(deleteResultText(t, compact, result));
    return true;
  } catch (error) {
    closeLoading?.();
    if (parseApiError(error)?.code === "THREAD_TURN_ACTIVE") {
      antMessage.error(t("apiErrors.THREAD_TURN_ACTIVE"));
      return null;
    }
    antMessage.error(apiErrorMessage(error, t("sessions.deleteFailed"), t));
    return false;
  }
}
