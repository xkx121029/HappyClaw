import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  ChevronLeft,
  Crosshair,
  MessageSquareText,
  Play,
  Sparkles,
  Square,
} from "lucide-react";
import { octopThreadsApi } from "../../api/modules/octopThreads";
import { providerApi } from "../../api/modules/provider";
import type { ResolvedModel } from "../../api/types";
import {
  MODEL_AUTO_VALUE,
  modelOptionLabel,
  modelOptionValue,
} from "../../utils/modelOptions";
import type { RingSegment } from "./homeActivityModel";
import type { HomeActionResult } from "./useHomeActivity";
import styles from "./Home.module.less";

interface SessionQuickMenuProps {
  /** Arc under the pointer; ``null`` closes the menu. */
  segment: RingSegment | null;
  /** Viewport coordinates of the right click. */
  anchor: { x: number; y: number } | null;
  onClose: () => void;
  /** Send a follow-up; the server queues it when the turn is still running. */
  onSend: (
    agentId: string,
    threadId: string,
    text: string,
  ) => Promise<HomeActionResult>;
  /** Cancel the thread's current turn over its live socket. */
  onStop: (agentId: string, threadId: string) => Promise<HomeActionResult>;
  onOpenPeek: (segment: RingSegment) => void;
  onLocate: (segment: RingSegment) => void;
}

type Mode = "root" | "compose" | "stop" | "model" | "locate";

interface Feedback {
  tone: "ok" | "warn" | "error";
  text: string;
}

const MENU_WIDTH = 268;

/** Stable action codes returned by the hook, translated for the feedback line. */
const REASON_KEYS: Record<string, string> = {
  empty: "home.menu.reason.empty",
  socket: "home.menu.reason.socket",
  forbidden: "home.menu.reason.forbidden",
  thread_gone: "home.menu.reason.threadGone",
  no_ack: "home.menu.reason.noAck",
  rejected: "home.menu.reason.rejected",
};

/**
 * Quick actions for one ring arc.
 *
 * Every action goes through an existing channel (``user_turn`` / ``cancel`` on
 * the chat WS, ``PATCH /threads/{id}`` for the model, the router for navigation)
 * and reports the real outcome — nothing is marked successful optimistically.
 * Keyboard: Esc closes, ↑/↓/Home/End move, Enter activates.
 */
export default function SessionQuickMenu({
  segment,
  anchor,
  onClose,
  onSend,
  onStop,
  onOpenPeek,
  onLocate,
}: SessionQuickMenuProps) {
  const { t } = useTranslation();
  const menuRef = useRef<HTMLDivElement | null>(null);
  const [mode, setMode] = useState<Mode>("root");
  const [draft, setDraft] = useState("");
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  const [models, setModels] = useState<ResolvedModel[]>([]);
  const [modelState, setModelState] = useState<"idle" | "loading" | "error">(
    "idle",
  );
  const [currentModel, setCurrentModel] = useState("");
  const [pending, setPending] = useState(false);
  const [pos, setPos] = useState({ x: 0, y: 0 });

  const open = Boolean(segment && anchor);
  const agentId = segment?.agentId ?? "";
  const threadId = segment?.threadId ?? "";
  const aggregate = (segment?.overflow ?? 0) > 0;
  const segmentKey = segment?.key ?? "";

  // A different arc is a different conversation: reset every per-arc view.
  useEffect(() => {
    if (!open) return;
    setMode("root");
    setDraft("");
    setFeedback(null);
    setModels([]);
    setModelState("idle");
    setCurrentModel(segment?.modelRef ?? "");
    setPending(false);
  }, [open, segmentKey, segment?.modelRef]);

  // Keep the menu inside the viewport; measured before paint to avoid a jump.
  useLayoutEffect(() => {
    if (!anchor) return;
    const width = menuRef.current?.offsetWidth ?? MENU_WIDTH;
    const height = menuRef.current?.offsetHeight ?? 320;
    const margin = 12;
    setPos({
      x: Math.max(
        margin,
        Math.min(anchor.x, window.innerWidth - width - margin),
      ),
      y: Math.max(
        margin,
        Math.min(anchor.y, window.innerHeight - height - margin),
      ),
    });
  }, [anchor, mode, models.length, open]);

  // Focus the first control so arrow keys work without a click.
  useEffect(() => {
    if (!open) return;
    menuRef.current
      ?.querySelector<HTMLElement>("[data-menu-focus]")
      ?.focus();
  }, [open, mode]);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (menuRef.current?.contains(event.target as Node)) return;
      onClose();
    };
    window.addEventListener("pointerdown", onPointerDown, true);
    return () =>
      window.removeEventListener("pointerdown", onPointerDown, true);
  }, [open, onClose]);

  // Models come from the same resolved list the composer uses.
  useEffect(() => {
    if (!open || mode !== "model" || !agentId) return;
    if (models.length > 0 || modelState === "loading") return;
    let cancelled = false;
    setModelState("loading");
    providerApi
      .listResolvedModels(agentId)
      .then((list) => {
        if (cancelled) return;
        setModels(list);
        setModelState("idle");
      })
      .catch(() => {
        if (!cancelled) setModelState("error");
      });
    return () => {
      cancelled = true;
    };
  }, [open, mode, agentId, models.length, modelState]);

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      onClose();
      return;
    }
    const tag = (event.target as HTMLElement | null)?.tagName;
    const editing = tag === "TEXTAREA" || tag === "INPUT";
    if (
      event.key !== "ArrowDown" &&
      event.key !== "ArrowUp" &&
      event.key !== "Home" &&
      event.key !== "End"
    ) {
      return;
    }
    // Let the caret move inside the composer.
    if (editing) return;
    const root = menuRef.current;
    if (!root) return;
    const items = Array.from(
      root.querySelectorAll<HTMLElement>("[data-menu-focus]:not(:disabled)"),
    );
    if (items.length === 0) return;
    event.preventDefault();
    const active = document.activeElement;
    let index = items.findIndex((item) => item === active);
    if (event.key === "Home") index = 0;
    else if (event.key === "End") index = items.length - 1;
    else if (event.key === "ArrowDown") index += 1;
    else index -= 1;
    items[(index + items.length) % items.length].focus();
  };

  if (!open || !segment) return null;

  const status = segment.awaitingUser
    ? t("home.sessions.awaiting")
    : segment.turnActive
      ? t("home.sessions.running")
      : t("home.sessions.idle");

  const reasonText = (result: HomeActionResult) => {
    const code = result.reason?.trim() || "rejected";
    const key = REASON_KEYS[code];
    return key ? t(key) : t("home.menu.failedWith", { reason: code });
  };

  const submitDraft = async () => {
    const text = draft.trim();
    if (!text || !agentId || !threadId || pending) return;
    setPending(true);
    const result = await onSend(agentId, threadId, text);
    setPending(false);
    if (!result.ok) {
      // ``no_ack`` means the frame left the browser but the server never
      // confirmed it — say so instead of claiming the message landed.
      setFeedback(
        result.reason === "no_ack"
          ? { tone: "warn", text: t("home.menu.sendNoAck") }
          : { tone: "error", text: reasonText(result) },
      );
      return;
    }
    setFeedback({
      tone: "ok",
      text: t(
        result.queued || segment.turnActive
          ? "home.menu.sentQueued"
          : "home.menu.sentNow",
      ),
    });
    setDraft("");
    setMode("root");
  };

  const confirmStop = async () => {
    if (!agentId || !threadId || pending) return;
    setPending(true);
    const result = await onStop(agentId, threadId);
    setPending(false);
    if (!result.ok) {
      setFeedback(
        result.reason === "no_ack"
          ? { tone: "warn", text: t("home.menu.stopNoAck") }
          : { tone: "error", text: reasonText(result) },
      );
      setMode("root");
      return;
    }
    setFeedback({ tone: "ok", text: t("home.menu.stopSent") });
    setMode("root");
  };

  const chooseModel = async (value: string) => {
    if (!agentId || !threadId) return;
    try {
      await octopThreadsApi.patch(agentId, threadId, {
        model_ref: value || null,
      });
      setCurrentModel(value);
      setFeedback({ tone: "ok", text: t("home.menu.modelSwitched") });
      setMode("root");
    } catch (error) {
      const reason = error instanceof Error ? error.message.trim() : "";
      setFeedback({
        tone: "error",
        text: reason
          ? `${t("home.menu.modelFailed")}: ${reason}`
          : t("home.menu.modelFailed"),
      });
    }
  };

  const renderRoot = () => (
    <>
      <button
        type="button"
        role="menuitem"
        className={styles.menuItem}
        data-menu-focus
        disabled={aggregate}
        onClick={() => setMode("compose")}
      >
        <Play size={14} strokeWidth={1.9} />
        <span className={styles.menuItemText}>
          {t("home.menu.append")}
          <span className={styles.menuItemHint}>
            {t(
              segment.turnActive
                ? "home.menu.appendQueued"
                : "home.menu.appendIdle",
            )}
          </span>
        </span>
      </button>
      <button
        type="button"
        role="menuitem"
        className={`${styles.menuItem} ${styles.menuDanger}`}
        data-menu-focus
        disabled={aggregate || !segment.turnActive}
        onClick={() => setMode("stop")}
      >
        <Square size={14} strokeWidth={1.9} />
        <span className={styles.menuItemText}>
          {t("home.menu.stop")}
          <span className={styles.menuItemHint}>
            {segment.turnActive
              ? t("home.menu.stopHint")
              : t("home.menu.stopIdle")}
          </span>
        </span>
      </button>
      <button
        type="button"
        role="menuitem"
        className={styles.menuItem}
        data-menu-focus
        disabled={aggregate}
        onClick={() => setMode("model")}
      >
        <Sparkles size={14} strokeWidth={1.9} />
        <span className={styles.menuItemText}>
          {t("home.menu.model")}
          <span className={styles.menuItemHint}>
            {currentModel
              ? currentModel
              : t("home.menu.modelDefault")}
          </span>
        </span>
      </button>
      <button
        type="button"
        role="menuitem"
        className={styles.menuItem}
        data-menu-focus
        disabled={aggregate}
        onClick={() => {
          onOpenPeek(segment);
          onClose();
        }}
      >
        <MessageSquareText size={14} strokeWidth={1.9} />
        <span className={styles.menuItemText}>{t("home.menu.peek")}</span>
      </button>
      <button
        type="button"
        role="menuitem"
        className={styles.menuItem}
        data-menu-focus
        disabled={aggregate}
        onClick={() => setMode("locate")}
      >
        <Crosshair size={14} strokeWidth={1.9} />
        <span className={styles.menuItemText}>{t("home.menu.locate")}</span>
      </button>
    </>
  );

  return (
    <div
      ref={menuRef}
      className={styles.menu}
      style={{ left: pos.x, top: pos.y }}
      role="menu"
      aria-label={t("home.menu.title")}
      data-home-menu=""
      tabIndex={-1}
      onKeyDown={onKeyDown}
    >
      <header className={styles.menuHead}>
        <span className={styles.menuTitle}>
          {segment.overflow > 0
            ? t("home.menu.aggregateTitle", { count: segment.overflow })
            : segment.title}
        </span>
        <span className={styles.menuMeta}>
          {segment.agentName ? `${segment.agentName} · ${status}` : status}
        </span>
      </header>

      {aggregate ? (
        <p className={styles.menuHint}>{t("home.menu.aggregate")}</p>
      ) : mode === "root" ? (
        renderRoot()
      ) : mode === "compose" ? (
        <div className={styles.menuBody}>
          <p className={styles.menuHint}>
            {t(
              segment.turnActive
                ? "home.menu.appendQueued"
                : "home.menu.appendIdle",
            )}
          </p>
          <textarea
            className={styles.menuField}
            value={draft}
            rows={3}
            autoFocus
            aria-label={t("home.menu.append")}
            placeholder={t("home.menu.draftPlaceholder")}
            onChange={(event) => setDraft(event.target.value)}
          />
          <div className={styles.menuRow}>
            <button
              type="button"
              className={styles.menuButton}
              onClick={() => setMode("root")}
            >
              <ChevronLeft size={13} strokeWidth={2} />
              {t("home.menu.back")}
            </button>
            <button
              type="button"
              className={`${styles.menuButton} ${styles.menuPrimary}`}
              data-menu-focus
              disabled={!draft.trim() || pending}
              onClick={() => void submitDraft()}
            >
              {t("home.menu.send")}
            </button>
          </div>
        </div>
      ) : mode === "stop" ? (
        <div className={styles.menuBody}>
          <p className={styles.menuHint}>{t("home.menu.stopConfirmHint")}</p>
          <div className={styles.menuRow}>
            <button
              type="button"
              className={styles.menuButton}
              data-menu-focus
              onClick={() => setMode("root")}
            >
              {t("home.menu.cancel")}
            </button>
            <button
              type="button"
              className={`${styles.menuButton} ${styles.menuDangerButton}`}
              data-menu-focus
              disabled={pending}
              onClick={() => void confirmStop()}
            >
              {t("home.menu.stopConfirm")}
            </button>
          </div>
        </div>
      ) : mode === "locate" ? (
        <div className={styles.menuBody}>
          <p className={styles.menuHint}>{t("home.menu.locateHint")}</p>
          <p className={styles.menuTarget}>
            <span>{segment.title}</span>
            <span className={styles.menuTargetMeta}>{segment.agentName}</span>
          </p>
          <div className={styles.menuRow}>
            <button
              type="button"
              className={styles.menuButton}
              data-menu-focus
              onClick={() => setMode("root")}
            >
              {t("home.menu.cancel")}
            </button>
            <button
              type="button"
              className={`${styles.menuButton} ${styles.menuPrimary}`}
              data-menu-focus
              onClick={() => {
                onLocate(segment);
                onClose();
              }}
            >
              {t("home.menu.locateConfirm")}
            </button>
          </div>
        </div>
      ) : (
        <div className={styles.menuBody}>
          <p className={styles.menuHint}>{t("home.menu.modelScope")}</p>
          {modelState === "loading" && (
            <p className={styles.menuHint}>{t("home.menu.modelLoading")}</p>
          )}
          {modelState === "error" && (
            <p className={styles.menuHint} role="alert">
              {t("home.menu.modelError")}
            </p>
          )}
          {modelState === "idle" && models.length === 0 && (
            <p className={styles.menuHint}>{t("home.menu.modelEmpty")}</p>
          )}
          <div className={styles.menuModels}>
            <button
              type="button"
              role="menuitem"
              className={styles.menuModel}
              data-menu-focus
              data-current={currentModel === MODEL_AUTO_VALUE}
              onClick={() => void chooseModel(MODEL_AUTO_VALUE)}
            >
              <span>{t("home.menu.modelAuto")}</span>
              {currentModel === MODEL_AUTO_VALUE && (
                <span className={styles.menuBadge}>
                  {t("home.menu.modelCurrent")}
                </span>
              )}
            </button>
            {models.map((model) => {
              const value = modelOptionValue(model);
              return (
                <button
                  key={value}
                  type="button"
                  role="menuitem"
                  className={styles.menuModel}
                  data-menu-focus
                  data-current={currentModel === value}
                  onClick={() => void chooseModel(value)}
                >
                  <span>{modelOptionLabel(model)}</span>
                  {currentModel === value && (
                    <span className={styles.menuBadge}>
                      {t("home.menu.modelCurrent")}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
          <div className={styles.menuRow}>
            <button
              type="button"
              className={styles.menuButton}
              onClick={() => setMode("root")}
            >
              <ChevronLeft size={13} strokeWidth={2} />
              {t("home.menu.back")}
            </button>
          </div>
        </div>
      )}

      {feedback && (
        <p
          className={styles.menuFeedback}
          data-tone={feedback.tone}
          role="status"
        >
          {feedback.text}
        </p>
      )}
    </div>
  );
}
