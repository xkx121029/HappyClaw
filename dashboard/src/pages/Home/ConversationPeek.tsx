import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { RefreshCw, X } from "lucide-react";
import { octopThreadsApi } from "../../api/modules/octopThreads";
import type { HomeSession } from "./homeActivityModel";
import styles from "./Home.module.less";

interface ConversationPeekProps {
  open: boolean;
  session: HomeSession | null;
  onClose: () => void;
}

interface PeekMessage {
  key: string;
  role: "user" | "assistant";
  text: string;
}

/** Newest history page the popover shows; the panel scrolls, no pagination. */
const PEEK_LIMIT = 14;
const PEEK_REFRESH_MS = 5_000;
const PEEK_TEXT_MAX = 1_400;

function messageText(content: unknown): string {
  if (typeof content === "string") {
    const trimmed = content.trim();
    // Some histories serialize the block list as a JSON string.
    if (trimmed.startsWith("[") || trimmed.startsWith("{")) {
      try {
        return messageText(JSON.parse(trimmed) as unknown);
      } catch {
        return trimmed;
      }
    }
    return trimmed;
  }
  if (!Array.isArray(content)) return "";
  const parts: string[] = [];
  for (const raw of content) {
    if (typeof raw === "string") {
      parts.push(raw);
      continue;
    }
    if (!raw || typeof raw !== "object") continue;
    const block = raw as Record<string, unknown>;
    if (typeof block.text === "string" && block.text.trim()) {
      parts.push(block.text);
    }
  }
  return parts.join("\n").trim();
}

/**
 * Small floating window with the current thread's last exchange.
 * Reads the existing history endpoint — no new channel, no page navigation.
 */
export default function ConversationPeek({
  open,
  session,
  onClose,
}: ConversationPeekProps) {
  const { t } = useTranslation();
  const [messages, setMessages] = useState<PeekMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const panelRef = useRef<HTMLDivElement | null>(null);

  const agentId = session?.agentId ?? "";
  const threadId = session?.threadId ?? "";

  const load = useCallback(async () => {
    if (!agentId || !threadId) return;
    setLoading(true);
    try {
      const history = await octopThreadsApi.history(agentId, threadId, {
        limit: PEEK_LIMIT,
      });
      const next: PeekMessage[] = [];
      for (let i = 0; i < history.messages.length; i += 1) {
        const message = history.messages[i];
        if (message.role !== "user" && message.role !== "assistant") continue;
        const text = messageText(message.content);
        if (!text) continue;
        next.push({
          key: message.id || `${message.role}-${i}`,
          role: message.role,
          text:
            text.length > PEEK_TEXT_MAX
              ? `${text.slice(0, PEEK_TEXT_MAX)}…`
              : text,
        });
      }
      setMessages(next.slice(-PEEK_LIMIT));
      setFailed(false);
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, [agentId, threadId]);

  useEffect(() => {
    if (!open) return;
    setMessages([]);
    setFailed(false);
    if (!agentId || !threadId) return;
    void load();
  }, [open, agentId, threadId, load]);

  useEffect(() => {
    if (!open || !agentId || !threadId) return;
    const id = window.setInterval(() => void load(), PEEK_REFRESH_MS);
    return () => window.clearInterval(id);
  }, [open, agentId, threadId, load]);

  useEffect(() => {
    if (open) panelRef.current?.focus();
  }, [open]);

  if (!open) return null;

  const status = session
    ? session.awaitingUser
      ? t("home.sessions.awaiting")
      : session.turnActive
        ? t("home.sessions.running")
        : t("home.sessions.idle")
    : "";

  return (
    <div
      ref={panelRef}
      className={styles.peek}
      role="dialog"
      aria-label={t("home.peek.title")}
      tabIndex={-1}
    >
      <header className={styles.peekHead}>
        <div className={styles.peekHeadText}>
          <p className={styles.peekTitle}>
            {session?.title || t("home.peek.untitled")}
          </p>
          <p className={styles.peekMeta}>
            {session ? `${session.agentName} · ${status}` : t("home.peek.noSession")}
          </p>
        </div>
        <button
          type="button"
          className={styles.peekIconButton}
          onClick={onClose}
          aria-label={t("home.peek.close")}
        >
          <X size={15} strokeWidth={1.9} />
        </button>
      </header>

      <div className={styles.peekBody}>
        {!session && (
          <p className={styles.peekHint}>{t("home.peek.emptyTitle")}</p>
        )}
        {session && loading && messages.length === 0 && (
          <p className={styles.peekHint}>{t("home.peek.loading")}</p>
        )}
        {session && failed && (
          <p className={styles.peekHint} role="alert">
            {t("home.peek.error")}
          </p>
        )}
        {session && !loading && !failed && messages.length === 0 && (
          <p className={styles.peekHint}>{t("home.peek.empty")}</p>
        )}
        {messages.map((message) => (
          <div
            key={message.key}
            className={styles.peekMessage}
            data-role={message.role}
          >
            <span className={styles.peekRole}>
              {t(`home.peek.role.${message.role}`)}
            </span>
            <p className={styles.peekText}>{message.text}</p>
          </div>
        ))}
      </div>

      <footer className={styles.peekFoot}>
        <span>{t("home.peek.count", { count: messages.length })}</span>
        <button
          type="button"
          className={styles.peekRefresh}
          onClick={() => void load()}
          disabled={!session || loading}
        >
          <RefreshCw size={13} strokeWidth={1.9} />
          {t("home.peek.refresh")}
        </button>
      </footer>
    </div>
  );
}
