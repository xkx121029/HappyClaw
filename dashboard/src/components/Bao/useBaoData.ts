import { useCallback, useEffect, useRef, useState } from "react";

import {
  baoApi,
  type BaoChatMessage,
  type BaoChatResponse,
  type BaoOverview,
  type BaoSettings,
} from "../../api/modules/bao";
import { clearLegacyTasks, fromServerTask, loadLegacyTasks, type BaoTaskRecord } from "./baoTaskStore";

let legacyMigration: Promise<void> | null = null;

async function migrateLegacyTasksOnce(): Promise<void> {
  if (legacyMigration) return legacyMigration;
  legacyMigration = (async () => {
    const rows = loadLegacyTasks();
    if (rows.length === 0) return;
    try {
      await baoApi.importTasks(rows);
      clearLegacyTasks();
    } catch {
      // Keep the old key so the next page load retries instead of losing data.
    }
  })();
  return legacyMigration;
}

export function useBaoOverview(open: boolean) {
  const [overview, setOverview] = useState<BaoOverview | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const requestSeq = useRef(0);

  const reload = useCallback(async (silent = false) => {
    const seq = ++requestSeq.current;
    if (!silent) setLoading(true);
    try {
      const next = await baoApi.overview();
      if (seq === requestSeq.current) {
        setOverview(next);
        setError(null);
      }
    } catch (err) {
      if (seq === requestSeq.current) {
        setError(err instanceof Error ? err : new Error(String(err)));
      }
    } finally {
      if (seq === requestSeq.current && !silent) setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!open) return;
    void reload();
  }, [open, reload]);

  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === "visible") void reload(true);
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [reload]);

  return { overview, loading, error, reload };
}

/**
 * Server-backed dispatch ledger.
 *
 * Results are written by the Worker's turn-completion hook, so this hook has no
 * polling timer: it refreshes on mount, when the Bao page opens, and when the
 * tab becomes visible again. That single compensating refresh covers the case
 * where the page was closed while a turn finished.
 */
export function useBaoTasks(open: boolean) {
  const [tasks, setTasks] = useState<BaoTaskRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const requestSeq = useRef(0);

  const refreshTasks = useCallback(async () => {
    const seq = ++requestSeq.current;
    setLoading(true);
    try {
      const response = await baoApi.tasks();
      if (seq === requestSeq.current) {
        setTasks(response.tasks.map(fromServerTask));
      }
    } catch {
      // Keep the last server snapshot; the next visible/open refresh retries.
    } finally {
      if (seq === requestSeq.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      await migrateLegacyTasksOnce();
      if (!cancelled) await refreshTasks();
    })();
    return () => {
      cancelled = true;
    };
  }, [refreshTasks]);

  useEffect(() => {
    if (!open) return;
    void refreshTasks();
  }, [open, refreshTasks]);

  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === "visible") void refreshTasks();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [refreshTasks]);

  return { tasks, loading, refreshTasks };
}

function mergeMessages(
  current: BaoChatMessage[],
  incoming: BaoChatMessage[],
): BaoChatMessage[] {
  const byId = new Map(current.map((message) => [message.id, message]));
  for (const message of incoming) byId.set(message.id, message);
  return [...byId.values()].sort((a, b) => a.created_at - b.created_at);
}

/**
 * Bao's conversation memory. Loaded on mount and whenever the page becomes
 * visible again; each send returns the persisted user/assistant messages so the
 * transcript never guesses.
 */
export function useBaoChat(open: boolean) {
  const [messages, setMessages] = useState<BaoChatMessage[]>([]);
  const requestSeq = useRef(0);

  const refreshChat = useCallback(async () => {
    const seq = ++requestSeq.current;
    try {
      const response = await baoApi.chatHistory();
      if (seq === requestSeq.current) setMessages(response.messages);
    } catch {
      // Keep the last transcript; the next open/visible refresh retries.
    }
  }, []);

  useEffect(() => {
    void refreshChat();
  }, [refreshChat]);

  useEffect(() => {
    if (!open) return;
    void refreshChat();
  }, [open, refreshChat]);

  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === "visible") void refreshChat();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [refreshChat]);

  const send = useCallback(
    async (body: Parameters<typeof baoApi.chat>[0]): Promise<BaoChatResponse> => {
      const response = await baoApi.chat(body);
      setMessages((current) => mergeMessages(current, response.messages));
      return response;
    },
    [],
  );

  return { messages, refreshChat, send };
}

/** Persisted Bao identity/notification settings (name, mute, onboarding). */
export function useBaoSettings(enabled = true) {
  const [settings, setSettings] = useState<BaoSettings | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    void (async () => {
      try {
        const next = await baoApi.settings();
        if (!cancelled) setSettings(next);
      } catch {
        // The default name/mute stays in effect until the server answers.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [enabled]);

  const update = useCallback(async (patch: Partial<BaoSettings>) => {
    const next = await baoApi.updateSettings(patch);
    setSettings(next);
    return next;
  }, []);

  return { settings, update };
}
