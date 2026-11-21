import type { ChatAttachment } from "../hooks/sseHelpers";

/**
 * 输入框草稿：文本 + 附件元数据，按 (agentId, threadId) 存在本机。
 *
 * 相比旧的 sessionStorage 方案，这里用 localStorage，刷新或重开应用后
 * 未发送的内容仍然在；附件只存元数据（URL / 文件名等），不存文件本体。
 */

export type ComposerDraft = {
  text: string;
  attachments: ChatAttachment[];
};

export const COMPOSER_DRAFT_PREFIX = "octop:chat-draft:";
const DRAFT_VERSION = 2;
/** 单会话最多落盘的附件数量，避免 localStorage 被异常数据撑大。 */
const MAX_PERSISTED_ATTACHMENTS = 20;

const ATTACHMENT_KINDS = ["image", "file", "video", "audio"] as const;

export function composerDraftKey(
  agentId: string,
  threadId: string | null | undefined,
): string {
  return `${COMPOSER_DRAFT_PREFIX}${agentId}:${threadId ?? "__new__"}`;
}

function emptyDraft(): ComposerDraft {
  return { text: "", attachments: [] };
}

function optionalString(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function toAttachment(value: unknown): ChatAttachment | null {
  if (!value || typeof value !== "object") return null;
  const item = value as Partial<ChatAttachment>;
  if (typeof item.url !== "string" || !item.url) return null;
  const kind = ATTACHMENT_KINDS.includes(
    item.kind as (typeof ATTACHMENT_KINDS)[number],
  )
    ? (item.kind as ChatAttachment["kind"])
    : "file";
  return {
    url: item.url,
    filename: optionalString(item.filename),
    mediaType: optionalString(item.mediaType),
    workspacePath: optionalString(item.workspacePath),
    kind,
  };
}

function sanitizeAttachments(value: unknown): ChatAttachment[] {
  if (!Array.isArray(value)) return [];
  return value
    .map(toAttachment)
    .filter((item): item is ChatAttachment => item !== null)
    .slice(0, MAX_PERSISTED_ATTACHMENTS);
}

/** 读取某个会话的草稿；没有或数据损坏时返回空草稿。 */
export function readComposerDraft(
  agentId: string | null | undefined,
  threadId: string | null | undefined,
): ComposerDraft {
  if (!agentId) return emptyDraft();
  const key = composerDraftKey(agentId, threadId);
  try {
    const raw = localStorage.getItem(key);
    if (raw) {
      const parsed: unknown = JSON.parse(raw);
      if (parsed && typeof parsed === "object") {
        const obj = parsed as Record<string, unknown>;
        return {
          text: typeof obj.text === "string" ? obj.text : "",
          attachments: sanitizeAttachments(obj.attachments),
        };
      }
    }
  } catch {
    // localStorage 不可用或 JSON 损坏：继续尝试旧数据 / 返回空草稿
  }
  // 旧版本只把纯文本存在 sessionStorage；读到后下次持久化会迁到 localStorage。
  try {
    const legacy = sessionStorage.getItem(key);
    if (legacy) return { text: legacy, attachments: [] };
  } catch {
    // sessionStorage 不可用
  }
  return emptyDraft();
}

/** 持久化草稿；文本与附件都为空时删除该会话的 key。 */
export function writeComposerDraft(
  agentId: string | null | undefined,
  threadId: string | null | undefined,
  draft: ComposerDraft,
): void {
  if (!agentId) return;
  const key = composerDraftKey(agentId, threadId);
  const text = draft.text ?? "";
  const attachments = sanitizeAttachments(draft.attachments);
  try {
    if (!text && attachments.length === 0) {
      localStorage.removeItem(key);
    } else {
      localStorage.setItem(
        key,
        JSON.stringify({ v: DRAFT_VERSION, text, attachments }),
      );
    }
    sessionStorage.removeItem(key);
  } catch {
    // localStorage 不可用或配额不足：放弃本次持久化
  }
}

export function clearComposerDraft(
  agentId: string | null | undefined,
  threadId: string | null | undefined,
): void {
  writeComposerDraft(agentId, threadId, emptyDraft());
}
