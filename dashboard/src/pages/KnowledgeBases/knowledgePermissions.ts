import type { OctopUser } from "../../api/modules/auth";
import type { KnowledgeBase } from "../../api/modules/knowledgeBases";

export function canManageKnowledgeBase(
  base: Pick<KnowledgeBase, "owner_user_id">,
  user: OctopUser | null,
): boolean {
  return Boolean(
    user && (user.role === "admin" || base.owner_user_id === user.id),
  );
}

export function isKnowledgeOwner(
  base: Pick<KnowledgeBase, "owner_user_id">,
  user: OctopUser | null,
): boolean {
  return Boolean(user && base.owner_user_id === user.id);
}

export function formatKnowledgeOwner(
  base: Pick<
    KnowledgeBase,
    "owner_display_name" | "owner_username" | "owner_user_id"
  >,
): string {
  const displayName = base.owner_display_name?.trim() || "";
  const username = base.owner_username?.trim() || "";
  return displayName || username || String(base.owner_user_id);
}
